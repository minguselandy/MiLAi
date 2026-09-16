#!/usr/bin/env python3
"""Run isolated DG-16 operability probes without a successful reader call."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import DEFAULT_ENV_FILE, OpenedDevCase, _atomic_json
from evals.dg14.contracts import DG14HistoryEvent
from evals.dg14.provider import DG14ProviderError, MatchedVllmProvider
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.paper.provider import PaperProviderError
from scripts.run_dg15_single_case import _json_value, _wait_cleanup
from scripts.run_dg16_q6 import _verify_cleanup

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg16/operability"
QUESTION = "How much did I spend on each coffee mug for my coworkers?"
QUESTION_AT = "2026-08-27T09:00:00Z"
MATRIX = (
    ("c1-b32", 1, 32),
    ("c4-b16", 4, 16),
    ("c4-b32", 4, 32),
)


class DG16OperabilityError(RuntimeError):
    """An operability invariant failed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _token_counter(text: str) -> int:
    """Conservative local counter sufficient for the tiny synthetic probe."""

    return max(1, len(text.encode("utf-8")) // 3)


def _case() -> OpenedDevCase:
    events = tuple(
        DG14HistoryEvent.from_mapping(value)
        for value in (
            {
                "case_id": "dg16-operability-coffee",
                "session_ordinal": 0,
                "original_session_id": "operability-price",
                "turn_ordinal": 0,
                "role": "user",
                "content": "I spent $60 on coffee mugs for my coworkers.",
                "observed_at": "2026-08-26T09:00:00Z",
            },
            {
                "case_id": "dg16-operability-coffee",
                "session_ordinal": 1,
                "original_session_id": "operability-count",
                "turn_ordinal": 0,
                "role": "user",
                "content": "I bought 5 coffee mugs for my coworkers.",
                "observed_at": "2026-08-26T10:00:00Z",
            },
        )
    )
    return OpenedDevCase(
        case_id="dg16-operability-coffee",
        category="synthetic-operability",
        question=QUESTION,
        question_at=QUESTION_AT,
        sessions=(),
        history_events=events,
    )


def _semantic_signature(derived: dict[str, Any]) -> dict[str, Any]:
    trace = derived.get("trace")
    if not isinstance(trace, dict):
        raise DG16OperabilityError("composition result lacks a typed trace")
    slots = trace.get("slots")
    if not isinstance(slots, list):
        raise DG16OperabilityError("composition trace lacks slots")
    return {
        "status": derived.get("status"),
        "operator": derived.get("operator"),
        "value": derived.get("value"),
        "unit": derived.get("unit"),
        "source_turn_refs": sorted(derived.get("source_turn_refs", [])),
        "slot_states": [
            {"name": slot.get("name"), "status": slot.get("status")}
            for slot in slots
            if isinstance(slot, dict)
        ],
        "retrieval_attempts": trace.get("retrieval_attempts"),
        "expansion": trace.get("expansion"),
        "join": trace.get("join"),
        "terminal_reason": trace.get("terminal_reason"),
        "completeness": derived.get("completeness"),
    }


def _validate_trace(derived: dict[str, Any]) -> None:
    signature = _semantic_signature(derived)
    if signature["status"] != "COMPLETE":
        raise DG16OperabilityError("probe composition was not complete")
    if signature["operator"] != "DIVIDE_EVIDENCE_VALUES":
        raise DG16OperabilityError("probe selected the wrong operator")
    if signature["value"] != 12 or signature["unit"] != "USD_PER_ITEM":
        raise DG16OperabilityError("probe composition returned the wrong value")
    if signature["retrieval_attempts"] != 2:
        raise DG16OperabilityError("typed trace did not record per-slot attempts")
    if not signature["expansion"] or not signature["join"]:
        raise DG16OperabilityError("typed trace lacks expansion or join")
    if signature["terminal_reason"] != "COMPLETE":
        raise DG16OperabilityError("typed trace lacks a complete terminal reason")


def _slot_retrieval(
    session: LocalDG15RuntimeSession,
    scope: dict[str, object],
    expected_evidence_id: str,
) -> dict[str, Any]:
    transport = MultiplexedStdioMcpTransport(session.adapter_config().dg14_config())
    try:
        transport.open_case(scope)
        response = dict(
            transport.call(
                "reader-detail",
                "milai_memory_resolve",
                {
                    "query": "coffee mugs paid price",
                    "required_freshness": "CURRENT",
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 10,
                    "max_context_tokens": 512,
                    "reference_time": QUESTION_AT,
                },
            )
        )
    finally:
        transport.close()
    items = response.get("items")
    if not isinstance(items, list):
        raise DG16OperabilityError("single-slot retrieval lacks items")
    evidence_ids = [
        str(item.get("evidence_id")) for item in items if isinstance(item, dict)
    ]
    if expected_evidence_id not in evidence_ids:
        raise DG16OperabilityError("single TOTAL_PRICE retrieval missed its Evidence")
    access_trace = response.get("access_trace")
    return {
        "slot": "TOTAL_PRICE",
        "logical_attempts": 1,
        "status": response.get("status"),
        "terminal_stage": access_trace.get("terminal_stage")
        if isinstance(access_trace, dict)
        else None,
        "evidence_ids": evidence_ids,
    }


def _reader_failure_probe(adapter: Any, result: Any) -> dict[str, Any]:
    before = asdict(adapter.stats())

    def unavailable_post_json(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, str]]:
        raise PaperProviderError("injected unavailable reader transport")

    provider = MatchedVllmProvider(post_json=unavailable_post_json)
    error_type: str | None = None
    try:
        provider.answer(
            run_id="dg16-operability-reader-failure",
            case_id="dg16-operability-coffee",
            method_id="DG16-OPERABILITY-UNAVAILABLE-READER",
            question=QUESTION,
            question_as_of=QUESTION_AT,
            memory_context=result.context,
            token_budget=2048,
        )
    except DG14ProviderError as exc:
        error_type = type(exc).__name__
    else:
        raise DG16OperabilityError("unavailable reader probe unexpectedly succeeded")
    after = asdict(adapter.stats())
    if after != before:
        raise DG16OperabilityError("reader failure changed adapter Memory state")
    return {
        "reader_identity": "frozen-loopback-vllm",
        "fault_injection": "TRANSPORT_UNAVAILABLE_BEFORE_RESPONSE",
        "expected_failure_observed": True,
        "failure_type": error_type,
        "automatic_retries": 0,
        "memory_state_before": before,
        "memory_state_after": after,
        "memory_state_unchanged": True,
    }


def _denied_evidence_probe(
    session: LocalDG15RuntimeSession,
    *,
    run_id: str,
    cell_name: str,
) -> dict[str, Any]:
    """Capture one unreadable Evidence and prove it cannot enter a read result."""

    token = f"dg16-denied-{hashlib.sha256(run_id.encode()).hexdigest()[:16]}"
    project_id = f"dg16-denied-{hashlib.sha256(f'{run_id}:{cell_name}'.encode()).hexdigest()[:16]}"
    scope: dict[str, object] = {"project_ids": [project_id]}
    transport = MultiplexedStdioMcpTransport(session.adapter_config().dg14_config())
    try:
        transport.open_case(scope)
        captured = dict(
            transport.call(
                "submitter",
                "milai_evidence_capture",
                {
                    "operation_id": f"{run_id}-{cell_name}-denied-capture",
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": f"operability://{run_id}/{cell_name}/denied",
                    "subject_id": "dg16-denied-operability",
                    "observed_at": QUESTION_AT,
                    "content": f"unreadable marker {token}",
                    "permission_snapshot": {
                        "readable": False,
                        "project_ids": [project_id],
                    },
                    "confirmation": "CAPTURE",
                    "retention_state": "READABLE",
                    "data_classification": "DEIDENTIFIED",
                },
            )
        )
        outbox_id = captured.get("outbox_id")
        if not isinstance(outbox_id, str) or not outbox_id:
            raise DG16OperabilityError("denied Evidence capture lacks outbox ID")
        readiness = dict(
            transport.call(
                "reader-detail",
                "milai_projection_readiness_wait",
                {
                    "target_outbox_id": outbox_id,
                    "required_projections": ["evidence"],
                    "expected_versions": {"evidence": "evidence-search-v1"},
                    "timeout_ms": 15_000,
                    "poll_interval_ms": 25,
                },
            )
        )
        resolved = dict(
            transport.call(
                "reader-detail",
                "milai_memory_resolve",
                {
                    "query": token,
                    "required_freshness": "CURRENT",
                    "consistency_mode": "CANONICAL_REQUIRED",
                    "limit": 10,
                    "max_context_tokens": 512,
                    "reference_time": QUESTION_AT,
                },
            )
        )
        items = resolved.get("items")
        accepted = int(
            isinstance(items, list)
            and any(
                isinstance(item, dict)
                and item.get("evidence_id") == captured.get("evidence_id")
                for item in items
            )
        )
        cleanup_submission = dict(
            transport.call(
                "operator",
                "milai_namespace_cleanup_submit",
                {
                    "project_id": project_id,
                    "operation_id": f"{run_id}-{cell_name}-denied-cleanup",
                    "reason_code": "SOURCE_REMOVED",
                    "confirmation": "CLEANUP_NAMESPACE",
                },
            )
        )
    finally:
        transport.close()
    cleanup_readiness, post_cleanup, permission_bypass = _verify_cleanup(
        session, scope, cleanup_submission, token
    )
    if accepted or permission_bypass:
        raise DG16OperabilityError("denied Evidence or denied operation was accepted")
    return {
        "accepted": accepted,
        "denominator": 1,
        "capture_receipt": _json_value(captured),
        "readiness": _json_value(readiness),
        "resolve_status": resolved.get("status"),
        "resolve_items": _json_value(items),
        "cleanup_submission": _json_value(cleanup_submission),
        "cleanup_readiness": _json_value(cleanup_readiness),
        "post_cleanup_status": post_cleanup.get("status"),
    }


def _run_cell(
    *,
    run_id: str,
    cell_name: str,
    concurrency: int,
    batch_size: int,
    output_root: Path,
    env_file: Path,
    reader_failure_probe: bool,
) -> dict[str, Any]:
    case = _case()
    cell_root = output_root / "cells" / cell_name
    cell_root.mkdir(parents=True)
    session = LocalDG15RuntimeSession(
        output_root=cell_root,
        env_file=env_file,
        mcp_concurrency=concurrency,
        projection_batch_size=batch_size,
    )
    receipt: dict[str, Any] | None = None
    runtime_cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
    try:
        runtime = dict(session.start(f"{run_id}-{cell_name}"))
        adapter = session.adapter_for_case(case, _token_counter)
        namespace = adapter.reset(run_id, case.case_id)
        adapter.ingest_many(case.history_events)
        readiness = dict(adapter.finalize())
        result = adapter.query(QUESTION, QUESTION_AT, 2048)
        raw_derived = result.raw_resolve.get("derived_result")
        if not isinstance(raw_derived, dict):
            raise DG16OperabilityError("operator probe lacks a derived result")
        derived = dict(raw_derived)
        _validate_trace(derived)
        price_id = next(
            str(item["evidence_id"])
            for item in derived["operands"]
            if item.get("slot") == "TOTAL_PRICE"
        )
        slot_retrieval = _slot_retrieval(
            session, dict(namespace.scope), price_id
        )
        reader_failure = (
            _reader_failure_probe(adapter, result)
            if reader_failure_probe
            else {"status": "NOT_RUN_IN_THIS_CELL"}
        )
        denied_evidence = (
            _denied_evidence_probe(
                session,
                run_id=run_id,
                cell_name=cell_name,
            )
            if reader_failure_probe
            else {"status": "NOT_RUN_IN_THIS_CELL"}
        )
        cleanup_submission = dict(adapter.cleanup())
        cleanup_status, cleanup_items, cleanup_wait_ms = _wait_cleanup(
            adapter,
            evidence_count=len(case.history_events),
            timeout_seconds=60,
        )
        cleanup_readiness, post_cleanup, permission_bypass = _verify_cleanup(
            session,
            dict(namespace.scope),
            cleanup_submission,
            QUESTION,
        )
        if permission_bypass:
            raise DG16OperabilityError("reader profile bypassed capture permission")
        receipt = {
            "schema": "milai.dg16.operability-cell.v1",
            "status": "SUCCEEDED",
            "cell": cell_name,
            "configuration": {
                "mcp_concurrency": concurrency,
                "projection_batch_size": batch_size,
                "automatic_retries": 0,
            },
            "runtime": _json_value(runtime),
            "namespace": asdict(namespace),
            "readiness": _json_value(readiness),
            "operator_result": _json_value(derived),
            "semantic_signature": _semantic_signature(derived),
            "single_slot_retrieval": _json_value(slot_retrieval),
            "reader_failure": _json_value(reader_failure),
            "denied_evidence": _json_value(denied_evidence),
            "cleanup": {
                "submission": _json_value(cleanup_submission),
                "terminal_status": _json_value(cleanup_status),
                "item_outcomes": _json_value(cleanup_items),
                "wait_ms": round(cleanup_wait_ms, 6),
                "all_lane_readiness": _json_value(cleanup_readiness),
                "post_cleanup_status": post_cleanup.get("status"),
                "post_cleanup_items": post_cleanup.get("items"),
            },
            "worker_metrics": _json_value(session.projection_metrics()),
        }
    finally:
        runtime_cleanup = dict(session.close())
    if receipt is None:
        raise DG16OperabilityError(f"cell {cell_name} produced no receipt")
    receipt["runtime_cleanup"] = _json_value(runtime_cleanup)
    worker = runtime_cleanup.get("persistent_worker")
    if (
        runtime_cleanup.get("status") != "PASS"
        or not isinstance(worker, dict)
        or worker.get("status") != "STOPPED"
    ):
        raise DG16OperabilityError(f"cell {cell_name} did not cleanly stop")
    _atomic_json(cell_root / "receipt.json", receipt)
    return receipt


def run_operability(*, run_id: str, output_root: Path, env_file: Path) -> dict[str, Any]:
    if output_root.exists():
        raise DG16OperabilityError("output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    cells = [
        _run_cell(
            run_id=run_id,
            cell_name=name,
            concurrency=concurrency,
            batch_size=batch_size,
            output_root=output_root,
            env_file=env_file,
            reader_failure_probe=index == 0,
        )
        for index, (name, concurrency, batch_size) in enumerate(MATRIX)
    ]
    signatures = {cell["cell"]: cell["semantic_signature"] for cell in cells}
    concurrency_invariant = signatures["c1-b32"] == signatures["c4-b32"]
    batch_invariant = signatures["c4-b16"] == signatures["c4-b32"]
    if not concurrency_invariant or not batch_invariant:
        raise DG16OperabilityError("worker/batch settings changed semantic output")
    receipt = {
        "schema": "milai.dg16.operability.v1",
        "status": "SUCCEEDED",
        "classification": "SYNTHETIC_OPERABILITY_ONLY",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "successful_reader_calls": 0,
        "matrix": [
            {
                "cell": cell["cell"],
                "configuration": cell["configuration"],
                "receipt_sha256": _sha256(
                    output_root / "cells" / str(cell["cell"]) / "receipt.json"
                ),
            }
            for cell in cells
        ],
        "gates": {
            "single_case": True,
            "single_operator": True,
            "single_slot_retrieval": True,
            "typed_trace_complete": True,
            "reader_unavailable_memory_state_unchanged": True,
            "worker_concurrency_semantic_invariant": concurrency_invariant,
            "projection_batch_semantic_invariant": batch_invariant,
            "cleanup_complete": True,
        },
        "semantic_signature": signatures["c4-b32"],
        "reader_failure": cells[0]["reader_failure"],
        "denied_evidence": cells[0]["denied_evidence"],
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run_operability(
        run_id=args.run_id, output_root=output_root, env_file=args.env_file
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str((output_root / "receipt.json").relative_to(ROOT)),
                "receipt_sha256": _sha256(output_root / "receipt.json"),
                "gates": receipt["gates"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
