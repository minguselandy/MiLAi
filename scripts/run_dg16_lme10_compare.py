#!/usr/bin/env python3
"""Run a paired ten-case DG-16 MiLA versus BM25-T LME characterization."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _atomic_json,
    _baseline_event,
    _local_token_counter,
)
from evals.dg14.contracts import DG14ContractError, normalize_lme_timestamp
from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import (
    BUDGETS,
    METHODS,
    compare_summaries,
    load_public_dev_cases,
    load_public_dev_labels,
    score_records,
    sha256_file,
    summarize_lifecycle,
    summarize_records,
)
from evals.paper.adapters.baselines import OfficialBM25Adapter
from evals.paper.provider import MODEL_ID
from scripts.run_dg15_single_case import _json_value, _wait_cleanup
from scripts.run_dg16_q6 import (
    _process_identity,
    _provider_record,
    _reader_models,
    _verify_cleanup,
)

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg16/lme10"
COMPUTE_SPEC = ROOT / ".aris/compute/dg14-local-vllm-spec.json"
EXPECTED_COMPUTE_SPEC_CANONICAL_SHA256 = (
    "2d820c80a03d4f48f8ec631af92a530a0330036690eab2b7b7c2e6548794d424"
)


class DG16LME10RunError(RuntimeError):
    """The paired live experiment failed before its sealed denominator."""


def _canonical_json_sha256(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _selected_milai_trace(result: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    trace: list[dict[str, Any]] = []
    for item in result.provenance:
        if not item.context_selected or item.session_id in seen:
            continue
        seen.add(item.session_id)
        trace.append(
            {
                "rank": len(trace) + 1,
                "session_id": item.session_id,
                "source_id": item.source_id,
            }
        )
    return trace


def _context_record(
    *,
    case: Any,
    method_id: str,
    budget: int,
    result: Any,
) -> dict[str, Any]:
    if method_id == "DG16-MILAI-MCP":
        usage = dict(result.usage)
        trace = _selected_milai_trace(result)
        selected_refs = sorted(
            {compact_lme_source_ref(value) for value in result.selected_source_refs}
        )
        raw_resolve = dict(result.raw_resolve)
        memory_context = raw_resolve.get("memory_context")
        if not isinstance(memory_context, dict):
            raise DG16LME10RunError("Runtime MemoryContext is missing from archive")
        runtime_semantics = {
            "derived_result": _json_value(raw_resolve.get("derived_result")),
            "query_plan": _json_value(raw_resolve.get("query_plan")),
            "context_receipt": _json_value(raw_resolve.get("context_receipt")),
            "evidence_items": _json_value(raw_resolve.get("items")),
            "sufficiency_decision": _json_value(
                raw_resolve.get("sufficiency_decision")
            ),
            "search_trace": _json_value(raw_resolve.get("search_trace")),
            "context_identity": {
                "semantic_context_digest": memory_context.get(
                    "semantic_context_digest"
                ),
                "reader_context_digest": memory_context.get(
                    "reader_context_digest"
                ),
                "receipt_mapping": (
                    raw_resolve.get("context_receipt", {}).get("receipt_mapping")
                    if isinstance(raw_resolve.get("context_receipt"), dict)
                    else None
                ),
            },
        }
    else:
        usage = {
            **dict(result.usage),
            "retrieval_logical_calls": int(result.usage.get("retriever_calls", 0)),
        }
        trace = [dict(item) for item in result.trace]
        selected_refs = list(result.source_ids)
        runtime_semantics = {}
    return {
        "case_id": case.case_id,
        "category": case.category,
        "method_id": method_id,
        "token_budget": budget,
        "context": result.context,
        "context_sha256": hashlib.sha256(result.context.encode()).hexdigest(),
        "context_tokens": result.declared_tokens,
        "query_latency_ms": result.latency_ms,
        "retrieval_trace": trace,
        "selected_source_refs": selected_refs,
        "usage": _json_value(usage),
        **runtime_semantics,
    }


def _run_bm25_case(
    *, case: Any, run_id: str, token_counter: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    case_started = time.perf_counter()
    adapter = OfficialBM25Adapter(granularity="turn", token_counter=token_counter)
    reset_started = time.perf_counter()
    adapter.reset(run_id, case.case_id)
    reset_ms = (time.perf_counter() - reset_started) * 1000
    events = tuple(
        _baseline_event(
            case,
            session_ordinal=session_ordinal,
            turn_ordinal=turn_ordinal,
        )
        for session_ordinal, session in enumerate(case.sessions)
        for turn_ordinal, _turn in enumerate(session.turns)
    )
    ingest_started = time.perf_counter()
    for event in events:
        adapter.ingest(event)
    ingest_ms = (time.perf_counter() - ingest_started) * 1000
    finalize_started = time.perf_counter()
    adapter.finalize()
    finalize_ms = (time.perf_counter() - finalize_started) * 1000
    contexts: list[dict[str, Any]] = []
    query_ms = 0.0
    for budget in BUDGETS:
        result = adapter.query(
            case.question,
            normalize_lme_timestamp(case.question_at),
            budget,
            "default",
        )
        query_ms += result.latency_ms
        contexts.append(
            _context_record(
                case=case,
                method_id="LME-BM25-T",
                budget=budget,
                result=result,
            )
        )
    cleanup_started = time.perf_counter()
    adapter.close()
    cleanup_ms = (time.perf_counter() - cleanup_started) * 1000
    total_ms = (time.perf_counter() - case_started) * 1000
    lifecycle = {
        "case_id": case.case_id,
        "method_id": "LME-BM25-T",
        "event_count": len(events),
        "runtime_start_ms": 0.0,
        "reset_ms": reset_ms,
        "ingest_ms": ingest_ms,
        "finalize_ms": finalize_ms,
        "query_ms": query_ms,
        "cleanup_ms": cleanup_ms,
        "runtime_close_ms": 0.0,
        "total_lifecycle_ms": total_ms,
        "logical_mcp_calls": 0,
        "physical_mcp_batches": 0,
    }
    return contexts, lifecycle


def _run_milai_case(
    *,
    case: Any,
    run_id: str,
    case_root: Path,
    token_counter: Any,
    env_file: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
    cleanup_timeout_seconds: float,
    cleanup_readiness_timeout_ms: int,
    allowed_statuses: frozenset[str] = frozenset({"HIT", "PARTIAL"}),
    verify_wrong_scope: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    case_started = time.perf_counter()
    session = LocalDG15RuntimeSession(
        output_root=case_root,
        env_file=env_file,
        mcp_concurrency=mcp_concurrency,
        projection_batch_size=projection_batch_size,
    )
    case_receipt: dict[str, Any] | None = None
    close_result: dict[str, Any] = {"status": "NOT_CREATED"}
    close_ms = 0.0
    try:
        started = time.perf_counter()
        runtime = dict(session.start(f"{run_id}-{case.case_id}"))
        runtime_start_ms = (time.perf_counter() - started) * 1000
        adapter = session.adapter_for_case(case, token_counter)
        started = time.perf_counter()
        namespace = adapter.reset(run_id, case.case_id)
        reset_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        adapter.ingest_many(case.history_events)
        ingest_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        readiness = dict(adapter.finalize())
        finalize_ms = (time.perf_counter() - started) * 1000
        wrong_scope_accepted = False
        if verify_wrong_scope:
            try:
                adapter.query(
                    case.question,
                    case.question_at,
                    BUDGETS[0],
                    task_context={"project_ids": ["wrong-project"]},
                )
            except DG14ContractError:
                pass
            else:
                wrong_scope_accepted = True
                raise DG16LME10RunError(
                    f"case {case.case_id} accepted a wrong TaskContext scope"
                )
        contexts: list[dict[str, Any]] = []
        query_ms = 0.0
        for budget in BUDGETS:
            result = adapter.query(case.question, case.question_at, budget)
            if result.status not in allowed_statuses or (
                result.status != "ABSTAINED" and not result.provenance
            ):
                raise DG16LME10RunError(
                    f"case {case.case_id}/{budget} lacks usable provenance"
                )
            query_ms += result.latency_ms
            contexts.append(
                _context_record(
                    case=case,
                    method_id="DG16-MILAI-MCP",
                    budget=budget,
                    result=result,
                )
            )
        stats = adapter.stats()
        cleanup_started = time.perf_counter()
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
        cleanup_ms = (time.perf_counter() - cleanup_started) * 1000
        stale_accepted = (
            post_cleanup.get("status") == "HIT" or post_cleanup.get("items") != []
        )
        if stale_accepted or permission_bypass:
            raise DG16LME10RunError(
                f"case {case.case_id} failed cleanup or permission isolation"
            )
        call_records = [asdict(item) for item in adapter.export_call_records()]
        case_receipt = {
            "schema": "milai.dg16.lme10-case.v1",
            "status": "SUCCEEDED",
            "case_id": case.case_id,
            "runtime": _json_value(runtime),
            "namespace": asdict(namespace),
            "evidence_count": len(case.history_events),
            "readiness": _json_value(readiness),
            "contexts": [
                {key: value for key, value in context.items() if key != "context"}
                for context in contexts
            ],
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
            "mcp_calls": call_records,
            "stage_trace": [asdict(item) for item in adapter.export_stage_trace()],
            "safety": {
                "wrong_scope": {
                    "denominator": int(verify_wrong_scope),
                    "accepted": int(wrong_scope_accepted),
                },
                "wrong_principal_write": {
                    "denominator": 1,
                    "accepted": int(permission_bypass),
                },
                "revoked_evidence": {
                    "denominator": 1,
                    "accepted": int(stale_accepted),
                },
                "canonical_promotion": {
                    "denominator": len(case.history_events),
                    "accepted": stats.claim_count,
                },
                "silent_fallback": {
                    "denominator": len(contexts),
                    "accepted": sum(
                        int(context["usage"].get("fallback_used") is True)
                        for context in contexts
                    ),
                },
            },
        }
        lifecycle = {
            "case_id": case.case_id,
            "method_id": "DG16-MILAI-MCP",
            "event_count": len(case.history_events),
            "runtime_start_ms": runtime_start_ms,
            "reset_ms": reset_ms,
            "ingest_ms": ingest_ms,
            "finalize_ms": finalize_ms,
            "query_ms": query_ms,
            "cleanup_ms": cleanup_ms,
            "runtime_close_ms": 0.0,
            "total_lifecycle_ms": 0.0,
            "logical_mcp_calls": len(call_records),
            "physical_mcp_batches": stats.physical_mcp_batches,
        }
    finally:
        started = time.perf_counter()
        close_result = dict(session.close())
        close_ms = (time.perf_counter() - started) * 1000
    if case_receipt is None:
        raise DG16LME10RunError(f"case {case.case_id} produced no receipt")
    persistent_worker = close_result.get("persistent_worker")
    if (
        close_result.get("status") != "PASS"
        or not isinstance(persistent_worker, dict)
        or persistent_worker.get("status") != "STOPPED"
    ):
        raise DG16LME10RunError(f"case {case.case_id} runtime did not close")
    lifecycle["runtime_close_ms"] = close_ms
    lifecycle["total_lifecycle_ms"] = (time.perf_counter() - case_started) * 1000
    case_receipt["runtime_cleanup"] = _json_value(close_result)
    case_receipt["lifecycle"] = _json_value(lifecycle)
    _atomic_json(case_root / "receipt.json", case_receipt)
    return contexts, lifecycle, case_receipt


def run_comparison(
    *,
    run_id: str,
    output_root: Path,
    reader_url: str,
    tokenizer_path: Path,
    env_file: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
    cleanup_timeout_seconds: float,
    cleanup_readiness_timeout_ms: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG16LME10RunError("output exists; choose a fresh run ID")
    compute_spec_canonical_sha256 = _canonical_json_sha256(COMPUTE_SPEC)
    if compute_spec_canonical_sha256 != EXPECTED_COMPUTE_SPEC_CANONICAL_SHA256:
        raise DG16LME10RunError("compute specification canonical identity drifted")
    output_root.mkdir(parents=True)
    experiment_started = time.perf_counter()
    cases, selection = load_public_dev_cases()
    token_counter = _local_token_counter(tokenizer_path)
    contexts: list[dict[str, Any]] = []
    lifecycle_records: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []

    for ordinal, case in enumerate(cases, start=1):
        bm25_contexts, bm25_lifecycle = _run_bm25_case(
            case=case,
            run_id=run_id,
            token_counter=token_counter,
        )
        contexts.extend(bm25_contexts)
        lifecycle_records.append(bm25_lifecycle)
        case_root = output_root / "cases" / case.case_id
        case_root.mkdir(parents=True)
        milai_contexts, milai_lifecycle, case_receipt = _run_milai_case(
            case=case,
            run_id=run_id,
            case_root=case_root,
            token_counter=token_counter,
            env_file=env_file,
            mcp_concurrency=mcp_concurrency,
            projection_batch_size=projection_batch_size,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
            cleanup_readiness_timeout_ms=cleanup_readiness_timeout_ms,
        )
        contexts.extend(milai_contexts)
        lifecycle_records.append(milai_lifecycle)
        case_receipts.append(case_receipt)
        print(
            json.dumps(
                {
                    "stage": "contexts",
                    "case": ordinal,
                    "case_count": len(cases),
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )

    if len(contexts) != 40 or len(lifecycle_records) != 20:
        raise DG16LME10RunError("context or lifecycle denominator is incomplete")
    context_archive = {
        "schema": "milai.dg16.lme10-contexts.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "label_fields_available": False,
        "record_count": len(contexts),
        "records": contexts,
    }
    _atomic_json(output_root / "contexts.json", context_archive)

    provider = MatchedVllmProvider(reader_url)
    by_cell = {
        (context["case_id"], context["method_id"], context["token_budget"]): context
        for context in contexts
    }
    generation_schedule: list[dict[str, Any]] = []
    product_records: list[dict[str, Any]] = []
    for case_ordinal, case in enumerate(cases):
        for budget_ordinal, budget in enumerate(BUDGETS):
            order = list(METHODS)
            if (case_ordinal + budget_ordinal) % 2:
                order.reverse()
            for method_id in order:
                context = by_cell[(case.case_id, method_id, budget)]
                answer = provider.answer(
                    run_id=run_id,
                    case_id=case.case_id,
                    method_id=method_id,
                    question=case.question,
                    question_as_of=case.question_at,
                    memory_context=str(context["context"]),
                    token_budget=budget,
                )
                product_records.append(
                    {
                        **{
                            key: value
                            for key, value in context.items()
                            if key != "context"
                        },
                        "answer": answer.answer,
                        "provider": _provider_record(answer),
                    }
                )
                generation_schedule.append(
                    {
                        "ordinal": len(generation_schedule),
                        "case_id": case.case_id,
                        "token_budget": budget,
                        "method_id": method_id,
                        "seed": answer.seed,
                    }
                )
        print(
            json.dumps(
                {
                    "stage": "generation",
                    "case": case_ordinal + 1,
                    "case_count": len(cases),
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(product_records) != 40:
        raise DG16LME10RunError("generation denominator is incomplete")
    generation_archive = {
        "schema": "milai.dg16.lme10-generations.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "record_count": len(product_records),
        "schedule": generation_schedule,
        "records": product_records,
    }
    _atomic_json(output_root / "generations.json", generation_archive)

    source_ids = tuple(case.case_id for case in cases)
    labels, label_identity = load_public_dev_labels(source_ids)
    scored = score_records(product_records, labels)
    summaries = summarize_records(scored)
    lifecycle = summarize_lifecycle(lifecycle_records)
    comparison = compare_summaries(summaries, lifecycle)
    receipt = {
        "schema": "milai.dg16.lme10-comparison.v1",
        "status": "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "run_id": run_id,
        "configuration": {
            "case_count": 10,
            "methods": list(METHODS),
            "token_budgets": list(BUDGETS),
            "record_count": 40,
            "reader_model_id": MODEL_ID,
            "provider_seed_run_id": run_id,
            "automatic_retries": 0,
            "mcp_concurrency": mcp_concurrency,
            "projection_batch_size": projection_batch_size,
            "dense_enabled": False,
            "reranker_enabled": False,
        },
        "selection": selection,
        "execution_identity": {
            "hostname": platform.node(),
            "reader_url": reader_url,
            "reader_models": _reader_models(reader_url),
            "reader_process": _process_identity(7860),
            "provider_contract": full_provider_contract(),
            "provider_contract_sha256": full_provider_contract_sha256(),
            "compute_spec": {
                "path": str(COMPUTE_SPEC.relative_to(ROOT)),
                "file_sha256": sha256_file(COMPUTE_SPEC),
                "canonical_sha256": compute_spec_canonical_sha256,
            },
        },
        "product_plane": {
            "label_fields_available": False,
            "context_record_count": len(contexts),
            "generation_record_count": len(product_records),
            "case_receipts": [
                {
                    "case_id": case["case_id"],
                    "sha256": sha256_file(
                        output_root / "cases" / case["case_id"] / "receipt.json"
                    ),
                }
                for case in case_receipts
            ],
            "contexts_sha256": sha256_file(output_root / "contexts.json"),
            "generations_sha256": sha256_file(output_root / "generations.json"),
        },
        "scoring_plane": {
            "labels_loaded_after_generation_record_count": len(product_records),
            "label_source": label_identity,
            "scorer": "DG11_PAPER_DETERMINISTIC_NORMALIZED_EM_F1_V1",
            "retrieval_unit": "pseudonymized answer session",
        },
        "summaries": summaries,
        "lifecycle": lifecycle,
        "comparison": comparison,
        "lifecycle_records": lifecycle_records,
        "records": scored,
        "experiment_wall_ms": round(
            (time.perf_counter() - experiment_started) * 1000, 6
        ),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--mcp-concurrency", type=int, choices=(1, 2, 4, 8), default=4)
    parser.add_argument(
        "--projection-batch-size", type=int, choices=(1, 16, 32, 64), default=32
    )
    parser.add_argument("--cleanup-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--cleanup-readiness-timeout-ms", type=int, default=60_000)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run_comparison(
        run_id=args.run_id,
        output_root=output_root,
        reader_url=args.reader_url,
        tokenizer_path=args.tokenizer,
        env_file=args.env_file,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
        cleanup_timeout_seconds=args.cleanup_timeout_seconds,
        cleanup_readiness_timeout_ms=args.cleanup_readiness_timeout_ms,
    )
    receipt_path = (output_root / "receipt.json").resolve()
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": sha256_file(receipt_path),
                "comparison": receipt["comparison"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
