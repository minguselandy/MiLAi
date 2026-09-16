#!/usr/bin/env python3
"""Produce sealed Q1R dual-policy Contexts from one Runtime retrieval per cell."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.domain import MemoryResolveBudget, MemoryResolveRequest

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _atomic_json,
    _local_token_counter,
)
from evals.dg14.contracts import DG14Error, normalize_lme_timestamp
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import BUDGETS, load_public_dev_cases
from evals.dg17.q1r_causality import POLICIES, canonical_sha256
from evals.dg17.q1r_context_archive import (
    Q1RContextArchiveError,
    build_context_record,
    build_evidence_snapshot,
    seal_context_archive,
)

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/q1r"


class Q1RContextRunError(RuntimeError):
    """The label-free same-snapshot Context production failed."""


def run(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path,
    tokenizer_path: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise Q1RContextRunError("output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    cases, selection = load_public_dev_cases()
    token_counter = _local_token_counter(tokenizer_path)
    snapshots: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []

    for ordinal, case in enumerate(cases, start=1):
        case_started = time.perf_counter()
        case_root = output_root / "cases" / case.case_id
        session = LocalDG15RuntimeSession(
            output_root=case_root,
            env_file=env_file,
            mcp_concurrency=mcp_concurrency,
            projection_batch_size=projection_batch_size,
        )
        adapter: Any | None = None
        cleanup: dict[str, Any] = {"status": "NOT_SUBMITTED"}
        close_result: dict[str, Any] = {"status": "NOT_CREATED"}
        runtime: dict[str, Any] = {}
        readiness: dict[str, Any] = {}
        case_replays: list[tuple[int, Any]] = []
        try:
            runtime = dict(session.start(f"{run_id}-{case.case_id}"))
            adapter = session.adapter_for_case(case, token_counter)
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            for budget in BUDGETS:
                request = MemoryResolveRequest(
                    query=f"Recall previous history evidence: {case.question}",
                    requested_scope=dict(namespace.scope),
                    required_freshness="CURRENT",
                    consistency_mode="CANONICAL_REQUIRED",
                    budget=MemoryResolveBudget(
                        max_results=50,
                        max_candidates=60,
                        max_context_tokens=budget,
                        max_latency_ms=500,
                    ),
                    reference_time=datetime.fromisoformat(
                        normalize_lme_timestamp(case.question_at).replace(
                            "Z", "+00:00"
                        )
                    ),
                )
                replay = session.matched_resolve(
                    request,
                    f"{run_id}-{case.case_id}-{budget}-q1r",
                )
                if set(replay.policy_executions) != set(POLICIES):
                    raise Q1RContextRunError("Runtime replay policy denominator drifted")
                if replay.evidence_snapshot_digest != canonical_sha256(
                    replay.evidence_snapshot
                ):
                    raise Q1RContextRunError("Runtime snapshot digest drifted")
                case_replays.append((budget, replay))
            runtime_snapshots = {
                canonical_sha256(replay.evidence_snapshot)
                for _budget, replay in case_replays
            }
            if len(runtime_snapshots) != 1:
                raise Q1RContextRunError(
                    "Runtime Evidence snapshot changed between Context budgets"
                )
            governance = [dict(item) for item in adapter.export_governance_receipts()]
            event_payloads = [
                {**event.canonical(), "event_id": event.event_id}
                for event in case.history_events
            ]
            evidence_snapshot = build_evidence_snapshot(
                case_id=case.case_id,
                events=event_payloads,
                governance_receipts=governance,
                runtime_snapshot=case_replays[0][1].evidence_snapshot,
            )
            snapshot_digest = canonical_sha256(evidence_snapshot)
            snapshots.append(evidence_snapshot)
            for budget, replay in case_replays:
                for policy in POLICIES:
                    records.append(
                        build_context_record(
                            case_id=case.case_id,
                            token_budget=budget,
                            policy=policy,
                            execution_body=replay.policy_executions[policy].body,
                            evidence_snapshot_digest=snapshot_digest,
                            policy_metadata=replay.policy_metadata[policy],
                        )
                    )
            cleanup = dict(adapter.cleanup())
        except Q1RContextArchiveError as exc:
            raise Q1RContextRunError(
                f"case {case.case_id} produced an invalid Context archive"
            ) from exc
        finally:
            primary_failure_pending = sys.exc_info()[0] is not None
            emergency_cleanup_error: BaseException | None = None
            if adapter is not None and cleanup.get("status") == "NOT_SUBMITTED":
                try:
                    cleanup = dict(adapter.cleanup())
                except (DG14Error, OSError, subprocess.SubprocessError, TimeoutError) as exc:
                    emergency_cleanup_error = exc
                    cleanup = {
                        "status": "EMERGENCY_CLEANUP_FAILED",
                        "error_type": type(exc).__name__,
                    }
            close_result = dict(session.close())
            if emergency_cleanup_error is not None and not primary_failure_pending:
                raise emergency_cleanup_error
        lifecycle.append(
            {
                "case_id": case.case_id,
                "runtime": runtime,
                "readiness": readiness,
                "cleanup": cleanup,
                "runtime_close": close_result,
                "wall_ms": round((time.perf_counter() - case_started) * 1_000, 6),
            }
        )
        print(
            json.dumps(
                {
                    "stage": "q1r-contexts",
                    "case": ordinal,
                    "case_count": len(cases),
                    "case_id": case.case_id,
                    "record_count": len(records),
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )

    archive = seal_context_archive(
        run_id=run_id,
        selection=selection,
        snapshots=snapshots,
        records=records,
    )
    contexts_path = output_root / "contexts.json"
    _atomic_json(contexts_path, archive)
    receipt = {
        "schema": "milai.dg17.q1r-context-producer.v0.1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "historical_answer_reuse": False,
        "case_count": len(cases),
        "record_count": len(records),
        "retrieval_execution_count": len(cases) * len(BUDGETS),
        "policy_context_count": len(records),
        "same_execution_policy_views_per_retrieval": 2,
        "context_archive": {
            "path": str(contexts_path),
            "sha256": _sha256(contexts_path),
        },
        "selection": selection,
        "lifecycle": lifecycle,
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "producer-receipt.json", receipt)
    return receipt


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=32)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        env_file=args.env_file,
        tokenizer_path=args.tokenizer,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
    )
    receipt_path = output_root / "producer-receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path),
                "receipt_sha256": _sha256(receipt_path),
                "context_archive": receipt["context_archive"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
