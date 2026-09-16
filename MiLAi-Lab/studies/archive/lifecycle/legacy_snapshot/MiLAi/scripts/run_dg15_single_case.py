#!/usr/bin/env python3
"""Run one real DG-15 Raw Evidence MCP lifecycle and write its receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    OPENED_DEV_CASE_IDS,
    OPENED_DEV_INPUT_PATH,
    _atomic_json,
    _local_token_counter,
    load_opened_dev,
)
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.runtime_session import LocalDG15RuntimeSession

DEFAULT_RUN_ROOT = ROOT / "var/dg15/runs"
DG14_BASELINE_FILES = (
    ROOT / "MiLAi_DG-14_LongMemEval_MCP适配与对比实验_GOALS.md",
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/comparison.json",
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/analysis.md",
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/scored-records.json",
)


class DG15SingleCaseError(RuntimeError):
    """The single-case execution did not prove the DG-15 lifecycle contract."""

    def __init__(
        self, message: str, *, details: Mapping[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _wait_cleanup(
    adapter: Any,
    *,
    evidence_count: int,
    timeout_seconds: float,
) -> tuple[dict[str, object], list[dict[str, object]], float]:
    started = time.perf_counter()
    while True:
        status = dict(adapter.cleanup_status(offset=0, limit=100))
        terminal = (
            status.get("canonical_blocked_count") == evidence_count
            and status.get("projection_purged_count") == evidence_count
            and status.get("primary_bytes_erased_count") == evidence_count
        )
        if terminal:
            break
        if time.perf_counter() - started >= timeout_seconds:
            raise DG15SingleCaseError(
                "namespace cleanup did not reach its terminal stages",
                details={
                    "cleanup_status": status,
                    "wait_ms": round((time.perf_counter() - started) * 1_000, 6),
                },
            )
        time.sleep(0.5)

    outcomes: list[dict[str, object]] = []
    for offset in range(0, evidence_count, 100):
        page = dict(adapter.cleanup_status(offset=offset, limit=100))
        raw_items = page.get("item_outcomes")
        if not isinstance(raw_items, list):
            raise DG15SingleCaseError("namespace cleanup status lacks per-item outcomes")
        outcomes.extend(dict(item) for item in raw_items if isinstance(item, dict))
    if len(outcomes) != evidence_count or len(
        {item.get("evidence_id") for item in outcomes}
    ) != evidence_count:
        raise DG15SingleCaseError("namespace cleanup item denominator is incomplete")
    return status, outcomes, (time.perf_counter() - started) * 1_000


def run_single_case(
    *,
    run_id: str,
    case_id: str,
    output_root: Path,
    input_path: Path = OPENED_DEV_INPUT_PATH,
    tokenizer_path: Path = DEFAULT_TOKENIZER,
    env_file: Path = DEFAULT_ENV_FILE,
    cleanup_timeout_seconds: float = 60.0,
    mcp_concurrency: int = 1,
    projection_batch_size: int = 32,
) -> dict[str, object]:
    """Execute Raw Evidence -> MCP -> projection -> resolve -> cleanup once."""

    if output_root.exists():
        raise DG15SingleCaseError("output already exists; choose a fresh run-id")
    _partition, cases = load_opened_dev(input_path)
    case = next((item for item in cases if item.case_id == case_id), None)
    if case is None:
        raise DG15SingleCaseError("case is outside the frozen opened-development set")
    output_root.mkdir(parents=True)
    baseline = {str(path.relative_to(ROOT)): _sha256(path) for path in DG14_BASELINE_FILES}
    baseline_before = dict(baseline)
    counter = _local_token_counter(tokenizer_path)
    session = LocalDG15RuntimeSession(
        output_root=output_root,
        env_file=env_file,
        mcp_concurrency=mcp_concurrency,
        projection_batch_size=projection_batch_size,
    )
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    receipt: dict[str, object] | None = None
    try:
        runtime = dict(session.start(run_id))
        adapter = session.adapter_for_case(case, counter)
        namespace = adapter.reset(run_id, case.case_id)
        adapter.ingest_many(case.history_events)
        readiness = dict(adapter.finalize())
        result = adapter.query(case.question, case.question_at, 2048)
        if result.status not in {"HIT", "PARTIAL"} or not result.provenance:
            raise DG15SingleCaseError("Raw Evidence resolve returned no usable provenance")
        if adapter.stats().claim_count != 0:
            raise DG15SingleCaseError("Raw Evidence lane created canonical claims")

        cleanup_submission = dict(adapter.cleanup())
        try:
            cleanup_status, cleanup_items, cleanup_wait_ms = _wait_cleanup(
                adapter,
                evidence_count=len(case.history_events),
                timeout_seconds=cleanup_timeout_seconds,
            )
        except DG15SingleCaseError as exc:
            _atomic_json(
                output_root / "failure.json",
                {
                    "schema": "milai.dg15.single-case-failure.v1",
                    "status": "FAILED",
                    "run_id": run_id,
                    "case_id": case.case_id,
                    "stage": "cleanup",
                    "error": str(exc),
                    "details": _json_value(exc.details),
                    "worker_status": _json_value(session.worker_status()),
                    "worker_metrics": _json_value(session.projection_metrics()),
                    "adapter_stats": asdict(adapter.stats()),
                },
            )
            raise

        verification_transport = MultiplexedStdioMcpTransport(
            session.adapter_config().dg14_config()
        )
        try:
            verification_transport.open_case(namespace.scope)
            target_purge_outbox_id = cleanup_submission.get("target_purge_outbox_id")
            if not isinstance(target_purge_outbox_id, str) or not target_purge_outbox_id:
                raise DG15SingleCaseError("cleanup submission lacks its purge target")
            cleanup_readiness = verification_transport.call(
                "reader-detail",
                "milai_projection_readiness_wait",
                {
                    "target_outbox_id": target_purge_outbox_id,
                    "required_projections": ["evidence", "fts", "vector", "purge"],
                    "expected_versions": {
                        "evidence": "evidence-search-v1",
                        "fts": "canonical-fts-v1",
                        "vector": "canonical-vector-v1",
                        "purge": "purge-v1",
                    },
                    "timeout_ms": 15_000,
                    "poll_interval_ms": 25,
                },
            )
            if cleanup_readiness.get("status") != "READY":
                raise DG15SingleCaseError(
                    "all-lane cleanup readiness was not reached",
                    details={"cleanup_readiness": cleanup_readiness},
                )
            post_cleanup = verification_transport.call(
                "reader-detail",
                "milai_memory_resolve",
                {
                    "query": f"Recall previous history evidence: {case.question}",
                    "required_freshness": "CURRENT",
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 50,
                    "max_context_tokens": 8_000,
                },
            )
        finally:
            verification_transport.close()
        if post_cleanup.get("status") == "HIT" or post_cleanup.get("items") != []:
            raise DG15SingleCaseError("revoked Raw Evidence remained queryable")

        stats = adapter.stats()
        receipt = {
            "schema": "milai.dg15.single-case-e2e.v1",
            "status": "SUCCEEDED",
            "classification": "OPENED_DEVELOPMENT_ONLY",
            "run_id": run_id,
            "case_id": case.case_id,
            "method_id": adapter.method_id,
            "formal_holdout_consumed": False,
            "label_fields_available_to_product_path": False,
            "dg14_baseline_sha256": baseline,
            "runtime": _json_value(runtime),
            "configuration": {
                "mcp_concurrency": mcp_concurrency,
                "projection_batch_size": projection_batch_size,
                "provider_calls": 0,
                "automatic_retries": 0,
            },
            "namespace": asdict(namespace),
            "evidence_count": len(case.history_events),
            "canonical_claim_count": stats.claim_count,
            "readiness": _json_value(readiness),
            "resolve": {
                "status": result.status,
                "context_sha256": hashlib.sha256(result.context.encode()).hexdigest(),
                "context_tokens": result.declared_tokens,
                "source_ids": list(result.source_ids),
                "provenance": [asdict(item) for item in result.provenance],
                "usage": _json_value(result.usage),
                "derived_result": _json_value(
                    result.raw_resolve.get("derived_result")
                ),
            },
            "cleanup": {
                "submission": _json_value(cleanup_submission),
                "terminal_status": _json_value(cleanup_status),
                "item_outcomes": _json_value(cleanup_items),
                "wait_ms": round(cleanup_wait_ms, 6),
                "all_lane_readiness": _json_value(cleanup_readiness),
                "post_cleanup_resolve_status": post_cleanup.get("status"),
                "post_cleanup_items": post_cleanup.get("items"),
            },
            "adapter_stats": asdict(stats),
            "worker_metrics": _json_value(session.projection_metrics()),
            "mcp_calls": [asdict(item) for item in adapter.export_call_records()],
            "stage_trace": [asdict(item) for item in adapter.export_stage_trace()],
        }
    finally:
        runtime_cleanup = session.close()

    if receipt is None:
        raise DG15SingleCaseError("single-case execution produced no receipt")
    receipt["runtime_cleanup"] = _json_value(runtime_cleanup)
    if runtime_cleanup.get("status") != "PASS":
        raise DG15SingleCaseError("fresh Runtime database cleanup failed")
    persistent_worker = runtime_cleanup.get("persistent_worker")
    if not isinstance(persistent_worker, Mapping) or persistent_worker.get(
        "status"
    ) != "STOPPED":
        raise DG15SingleCaseError("persistent worker did not stop cleanly")
    baseline_after = {str(path.relative_to(ROOT)): _sha256(path) for path in DG14_BASELINE_FILES}
    if baseline_after != baseline_before:
        raise DG15SingleCaseError("DG-14 frozen baseline changed during DG-15 execution")
    receipt["dg14_baseline_unchanged"] = True
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", choices=OPENED_DEV_CASE_IDS, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--inputs", type=Path, default=OPENED_DEV_INPUT_PATH)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--cleanup-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--mcp-concurrency", type=int, choices=(1, 2, 4, 8), default=1)
    parser.add_argument(
        "--projection-batch-size", type=int, choices=(1, 16, 32, 64), default=32
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    receipt = run_single_case(
        run_id=args.run_id,
        case_id=args.case_id,
        output_root=args.run_dir or DEFAULT_RUN_ROOT / args.run_id,
        input_path=args.inputs,
        tokenizer_path=args.tokenizer,
        env_file=args.env_file,
        cleanup_timeout_seconds=args.cleanup_timeout_seconds,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
