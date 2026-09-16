#!/usr/bin/env python3
"""Run the five-case DG-16 Raw Evidence product path with matched vLLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import urllib.request
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
from evals.dg14.contracts import DG14ContractError, DG14TransportError
from evals.dg14.provider import (
    MatchedVllmProvider,
    ProviderResult,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.q0 import load_evaluation_fixture
from evals.dg16.q6 import evaluate_release_gate, score_product_records
from evals.paper.provider import MODEL_ID
from scripts.run_dg15_single_case import DG14_BASELINE_FILES, _json_value, _wait_cleanup

DG14_PROVIDER_SEED_RUN_ID = "dg14-matched-001-20260826"
DG14_SCORED_RECORDS = (
    ROOT / "var/dg14/runs/dg14-matched-001-20260826/scored-records.json"
)
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg16/q6"
MAX_READINESS_CALL_TIMEOUT_MS = 15_000


class DG16ProductEvaluationError(RuntimeError):
    """The real product-path lifecycle or its immutable comparison failed."""


def _wait_all_lane_cleanup(
    transport: MultiplexedStdioMcpTransport,
    *,
    target_outbox_id: str,
    total_timeout_ms: int,
) -> dict[str, object]:
    """Use bounded 15-second API waits without retrying the product query."""

    remaining_ms = total_timeout_ms
    history: list[dict[str, object]] = []
    readiness: dict[str, object] = {"status": "NOT_STARTED"}
    while remaining_ms > 0:
        call_timeout_ms = min(MAX_READINESS_CALL_TIMEOUT_MS, remaining_ms)
        readiness = dict(
            transport.call(
                "reader-detail",
                "milai_projection_readiness_wait",
                {
                    "target_outbox_id": target_outbox_id,
                    "required_projections": ["evidence", "fts", "vector", "purge"],
                    "expected_versions": {
                        "evidence": "evidence-search-v1",
                        "fts": "canonical-fts-v1",
                        "vector": "canonical-vector-v1",
                        "purge": "purge-v1",
                    },
                    "timeout_ms": call_timeout_ms,
                    "poll_interval_ms": 25,
                },
            )
        )
        history.append(
            {
                "call": len(history) + 1,
                "timeout_ms": call_timeout_ms,
                "status": readiness.get("status"),
            }
        )
        if readiness.get("status") == "READY":
            break
        if readiness.get("status") not in {
            "TIMEOUT",
            "PROJECTION_READINESS_TIMEOUT",
        }:
            break
        remaining_ms -= call_timeout_ms
    readiness["bounded_wait"] = {
        "total_timeout_ms": total_timeout_ms,
        "per_call_timeout_max_ms": MAX_READINESS_CALL_TIMEOUT_MS,
        "calls": history,
    }
    return readiness


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG16ProductEvaluationError(f"JSON artifact is not an object: {path}")
    return value


def _reader_models(base_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(
        f"{base_url.rstrip('/')}/v1/models", timeout=30
    ) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise DG16ProductEvaluationError("reader model identity exceeded 4 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise DG16ProductEvaluationError("reader model identity is malformed")
    return value


def _process_identity(port: int) -> dict[str, Any]:
    marker = str(port)
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (OSError, UnicodeDecodeError):
            continue
        if marker in command and "vllm" in command:
            return {"pid": int(entry.name), "command": command.strip()}
    return {"pid": None, "command": "UNAVAILABLE"}


def _provider_record(value: ProviderResult) -> dict[str, Any]:
    raw = asdict(value)
    context = str(raw.pop("context"))
    raw["context_sha256"] = hashlib.sha256(context.encode()).hexdigest()
    return raw


def _verify_cleanup(
    session: LocalDG15RuntimeSession,
    namespace_scope: dict[str, object],
    cleanup_submission: dict[str, object],
    question: str,
    *,
    timeout_ms: int = 60_000,
) -> tuple[dict[str, object], dict[str, object], bool]:
    transport = MultiplexedStdioMcpTransport(session.adapter_config().dg14_config())
    permission_bypass = False
    try:
        transport.open_case(namespace_scope)
        try:
            transport.call("reader-detail", "milai_evidence_capture", {})
        except DG14TransportError:
            pass
        else:
            permission_bypass = True
        target = cleanup_submission.get("target_purge_outbox_id")
        if not isinstance(target, str) or not target:
            raise DG16ProductEvaluationError("cleanup lacks target purge outbox ID")
        readiness = _wait_all_lane_cleanup(
            transport,
            target_outbox_id=target,
            total_timeout_ms=timeout_ms,
        )
        if readiness.get("status") != "READY":
            raise DG16ProductEvaluationError(
                "cleanup all-lane barrier was not ready: "
                f"{json.dumps(readiness, ensure_ascii=False, sort_keys=True)}"
            )
        post_cleanup = transport.call(
            "reader-detail",
            "milai_memory_resolve",
            {
                "query": f"Recall previous history evidence: {question}",
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "limit": 50,
                "max_context_tokens": 8_000,
            },
        )
    finally:
        transport.close()
    return readiness, post_cleanup, permission_bypass


def run_product_evaluation(
    *,
    run_id: str,
    output_root: Path,
    reader_url: str,
    provider_method_id: str,
    tokenizer_path: Path,
    env_file: Path,
    cleanup_timeout_seconds: float,
    cleanup_readiness_timeout_ms: int,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    """Run all product cells before loading any evaluation labels."""

    if output_root.exists():
        raise DG16ProductEvaluationError("output exists; choose a fresh run ID")
    if not 1_000 <= cleanup_readiness_timeout_ms <= 90_000:
        raise DG16ProductEvaluationError(
            "cleanup readiness timeout must be between 1,000 and 90,000 ms"
        )
    output_root.mkdir(parents=True)
    baseline_before = {
        str(path.relative_to(ROOT)): _sha256(path) for path in DG14_BASELINE_FILES
    }
    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    if tuple(case.case_id for case in cases) != OPENED_DEV_CASE_IDS:
        raise DG16ProductEvaluationError("opened-development case order drifted")
    provider = MatchedVllmProvider(reader_url)
    token_counter = _local_token_counter(tokenizer_path)
    product_records: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []
    safety_counts = {
        "canonical_promotion": {"accepted": 0, "denominator": 0},
        "cross_case_contamination": {"accepted": 0, "denominator": 0},
        "label_leakage": {"accepted": 0, "denominator": 0},
        "permission_denied_bypass": {"accepted": 0, "denominator": 0},
        "silent_fallback": {"accepted": 0, "denominator": 0},
        "stale_revoked_evidence_acceptance": {"accepted": 0, "denominator": 0},
        "wrong_scope_acceptance": {"accepted": 0, "denominator": 0},
    }

    for case in cases:
        case_root = output_root / "cases" / case.case_id
        case_root.mkdir(parents=True)
        session = LocalDG15RuntimeSession(
            output_root=case_root,
            env_file=env_file,
            mcp_concurrency=mcp_concurrency,
            projection_batch_size=projection_batch_size,
        )
        case_receipt: dict[str, Any] | None = None
        runtime_cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
        try:
            runtime = dict(session.start(f"{run_id}-{case.case_id}"))
            adapter = session.adapter_for_case(case, token_counter)
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            safety_counts["wrong_scope_acceptance"]["denominator"] += 1
            try:
                adapter.query(
                    case.question,
                    case.question_at,
                    512,
                    task_context={"project_ids": ["wrong-project"]},
                )
            except DG14ContractError:
                pass
            else:
                safety_counts["wrong_scope_acceptance"]["accepted"] += 1

            case_records: list[dict[str, Any]] = []
            for budget in (512, 2048):
                result = adapter.query(case.question, case.question_at, budget)
                if result.status not in {"HIT", "PARTIAL"} or not result.provenance:
                    raise DG16ProductEvaluationError(
                        f"case {case.case_id}/{budget} lacks usable provenance"
                    )
                answer = provider.answer(
                    run_id=DG14_PROVIDER_SEED_RUN_ID,
                    case_id=case.case_id,
                    method_id=provider_method_id,
                    question=case.question,
                    question_as_of=case.question_at,
                    memory_context=result.context,
                    token_budget=budget,
                )
                derived = result.raw_resolve.get("derived_result")
                derived_mapping = derived if isinstance(derived, dict) else {}
                selected_refs = sorted(
                    {
                        compact_lme_source_ref(source_ref)
                        for source_ref in result.selected_source_refs
                    }
                )
                all_refs = sorted(
                    {
                        compact_lme_source_ref(source_ref)
                        for item in result.provenance
                        for source_ref in item.source_refs
                    }
                )
                record = {
                    "case_id": case.case_id,
                    "token_budget": budget,
                    "method_id": provider_method_id,
                    "retrieval_method_id": result.method_id,
                    "status": result.status,
                    "answer": answer.answer,
                    "provider": _provider_record(answer),
                    "context_sha256": hashlib.sha256(
                        result.context.encode()
                    ).hexdigest(),
                    "context_tokens": result.declared_tokens,
                    "selected_source_refs": selected_refs,
                    "all_source_refs": all_refs,
                    "derived_source_turn_refs": [
                        compact_lme_source_ref(str(source_ref))
                        for source_ref in derived_mapping.get("source_turn_refs", [])
                    ],
                    "derived_result": _json_value(derived),
                    "provenance": [asdict(item) for item in result.provenance],
                    "usage": _json_value(result.usage),
                }
                case_records.append(record)
                safety_counts["cross_case_contamination"]["denominator"] += len(
                    result.provenance
                )
                safety_counts["label_leakage"]["denominator"] += 1
                safety_counts["silent_fallback"]["denominator"] += 1
                safety_counts["silent_fallback"]["accepted"] += int(
                    result.usage.get("fallback_used") is True
                )

            stats = adapter.stats()
            safety_counts["canonical_promotion"]["denominator"] += len(
                case.history_events
            )
            safety_counts["canonical_promotion"]["accepted"] += stats.claim_count
            cleanup_submission = dict(adapter.cleanup())
            cleanup_status, cleanup_items, cleanup_wait_ms = _wait_cleanup(
                adapter,
                evidence_count=len(case.history_events),
                timeout_seconds=cleanup_timeout_seconds,
            )
            cleanup_readiness, post_cleanup, permission_bypass = _verify_cleanup(
                session,
                dict(namespace.scope),
                cleanup_submission,
                case.question,
                timeout_ms=cleanup_readiness_timeout_ms,
            )
            safety_counts["permission_denied_bypass"]["denominator"] += 1
            safety_counts["permission_denied_bypass"]["accepted"] += int(
                permission_bypass
            )
            safety_counts["stale_revoked_evidence_acceptance"]["denominator"] += 1
            stale_accepted = (
                post_cleanup.get("status") == "HIT" or post_cleanup.get("items") != []
            )
            safety_counts["stale_revoked_evidence_acceptance"]["accepted"] += int(
                stale_accepted
            )
            if stale_accepted:
                raise DG16ProductEvaluationError(
                    f"case {case.case_id} remained queryable after cleanup"
                )
            case_receipt = {
                "schema": "milai.dg16.q6-case.v1",
                "status": "SUCCEEDED",
                "case_id": case.case_id,
                "runtime": _json_value(runtime),
                "namespace": asdict(namespace),
                "evidence_count": len(case.history_events),
                "canonical_claim_count": stats.claim_count,
                "readiness": _json_value(readiness),
                "product_records": case_records,
                "cleanup": {
                    "submission": _json_value(cleanup_submission),
                    "terminal_status": _json_value(cleanup_status),
                    "item_outcomes": _json_value(cleanup_items),
                    "wait_ms": round(cleanup_wait_ms, 6),
                    "all_lane_readiness": _json_value(cleanup_readiness),
                    "post_cleanup_status": post_cleanup.get("status"),
                    "post_cleanup_items": post_cleanup.get("items"),
                },
                "adapter_stats": asdict(stats),
                "worker_metrics": _json_value(session.projection_metrics()),
                "mcp_calls": [asdict(item) for item in adapter.export_call_records()],
                "stage_trace": [asdict(item) for item in adapter.export_stage_trace()],
            }
        finally:
            runtime_cleanup = dict(session.close())

        if case_receipt is None:
            raise DG16ProductEvaluationError(
                f"case {case.case_id} produced no terminal receipt"
            )
        case_receipt["runtime_cleanup"] = _json_value(runtime_cleanup)
        persistent_worker = runtime_cleanup.get("persistent_worker")
        if (
            runtime_cleanup.get("status") != "PASS"
            or not isinstance(persistent_worker, dict)
            or persistent_worker.get("status") != "STOPPED"
        ):
            raise DG16ProductEvaluationError(
                f"case {case.case_id} did not close its isolated runtime"
            )
        _atomic_json(case_root / "receipt.json", case_receipt)
        case_receipts.append(case_receipt)
        product_records.extend(case_receipt["product_records"])

    if len(product_records) != 10:
        raise DG16ProductEvaluationError("product execution did not seal all 10 cells")

    # Evaluation-plane labels and label-derived DG14 scores are opened only here.
    fixture = load_evaluation_fixture(cases=cases)
    frozen_baseline = _load_json(DG14_SCORED_RECORDS)
    raw_baseline_records = frozen_baseline.get("records")
    if not isinstance(raw_baseline_records, list):
        raise DG16ProductEvaluationError("frozen DG14 scored records are malformed")
    scoring = score_product_records(product_records, fixture, raw_baseline_records)
    gate = evaluate_release_gate(scoring["summaries"], safety_counts)
    baseline_after = {
        str(path.relative_to(ROOT)): _sha256(path) for path in DG14_BASELINE_FILES
    }
    if baseline_after != baseline_before:
        raise DG16ProductEvaluationError("DG14 frozen baseline changed during Q6")
    receipt = {
        "schema": "milai.dg16.q6-product-evaluation.v1",
        "status": "SUCCEEDED" if gate["status"] == "PASS" else "CHARACTERIZED",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_holdout_consumed": False,
        "run_id": run_id,
        "configuration": {
            "mcp_concurrency": mcp_concurrency,
            "projection_batch_size": projection_batch_size,
            "token_budgets": [512, 2048],
            "reader_model_id": MODEL_ID,
            "provider_method_id": provider_method_id,
            "provider_seed_run_id": DG14_PROVIDER_SEED_RUN_ID,
            "automatic_retries": 0,
            "cleanup_readiness_timeout_ms": cleanup_readiness_timeout_ms,
            "dense_enabled": False,
            "reranker_enabled": False,
        },
        "execution_identity": {
            "hostname": platform.node(),
            "reader_url": reader_url,
            "reader_models": _reader_models(reader_url),
            "reader_process": _process_identity(7860),
            "provider_contract": full_provider_contract(),
            "provider_contract_sha256": full_provider_contract_sha256(),
        },
        "product_plane": {
            "label_fields_available": False,
            "record_count": len(product_records),
            "case_receipts": [
                {
                    "case_id": receipt["case_id"],
                    "sha256": _sha256(
                        output_root / "cases" / receipt["case_id"] / "receipt.json"
                    ),
                }
                for receipt in case_receipts
            ],
        },
        "scoring_plane": {
            "labels_loaded_after_product_record_count": len(product_records),
            "fixture_sha256": _sha256(
                ROOT / "evals/dg16/fixtures/opened-dev-evidence-atoms.v1.json"
            ),
            "dg14_scored_records_sha256": _sha256(DG14_SCORED_RECORDS),
        },
        "records": scoring["records"],
        "summaries": scoring["summaries"],
        "safety": safety_counts,
        "gate": gate,
        "dg14_baseline_sha256": baseline_before,
        "dg14_baseline_unchanged": True,
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--provider-method-id", default="DG16-MILAI-MCP-COMPOSED")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--cleanup-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--cleanup-readiness-timeout-ms", type=int, default=60_000)
    parser.add_argument("--mcp-concurrency", type=int, choices=(1, 2, 4, 8), default=4)
    parser.add_argument(
        "--projection-batch-size", type=int, choices=(1, 16, 32, 64), default=32
    )
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run_product_evaluation(
        run_id=args.run_id,
        output_root=output_root,
        reader_url=args.reader_url,
        provider_method_id=args.provider_method_id,
        tokenizer_path=args.tokenizer,
        env_file=args.env_file,
        cleanup_timeout_seconds=args.cleanup_timeout_seconds,
        cleanup_readiness_timeout_ms=args.cleanup_readiness_timeout_ms,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
    )
    receipt_path = (output_root / "receipt.json").resolve()
    try:
        display_receipt_path = receipt_path.relative_to(ROOT)
    except ValueError:
        display_receipt_path = receipt_path
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(display_receipt_path),
                "receipt_sha256": _sha256(receipt_path),
                "gate": receipt["gate"],
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["gate"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
