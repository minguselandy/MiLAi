"""Pure Q1R Context archive construction from Runtime-owned matched replay output."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from evals.dg17.q1r_causality import (
    CONTEXT_ARCHIVE_SCHEMA,
    POLICIES,
    canonical_sha256,
    validate_context_archive,
)


class Q1RContextArchiveError(RuntimeError):
    """Runtime replay output could not be sealed as a causal Context archive."""


def build_evidence_snapshot(
    *,
    case_id: str,
    events: Sequence[Mapping[str, Any]],
    governance_receipts: Sequence[Mapping[str, Any]],
    runtime_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    receipts = {
        _required_text(item, "event_id"): item for item in governance_receipts
    }
    if len(receipts) != len(events):
        raise Q1RContextArchiveError("Evidence governance denominator drifted")
    source_events: list[dict[str, Any]] = []
    for event in events:
        event_id = _required_text(event, "event_id")
        receipt = receipts.get(event_id)
        if receipt is None:
            raise Q1RContextArchiveError("Evidence event lacks governed provenance")
        if event.get("case_id") != case_id:
            raise Q1RContextArchiveError("Evidence event crossed the case boundary")
        source_events.append(
            {
                **dict(event),
                "evidence_id": _required_text(receipt, "evidence_id"),
                "source_ref": _required_text(receipt, "source_ref"),
                "outbox_id": _required_text(receipt, "outbox_id"),
                "canonical_changed": receipt.get("canonical_changed") is True,
            }
        )
    if any(item["canonical_changed"] for item in source_events):
        raise Q1RContextArchiveError("Raw Evidence snapshot changed canonical truth")
    return {
        "schema_version": "q1r-evidence-snapshot-v0.1",
        "case_id": case_id,
        "classification": "PUBLIC_DEIDENTIFIED_DEV",
        "source_event_count": len(source_events),
        "source_events": source_events,
        "runtime_snapshot": dict(runtime_snapshot),
        "immutable_after_ingest": True,
        "formal_holdout_consumed": False,
    }


def build_context_record(
    *,
    case_id: str,
    token_budget: int,
    policy: str,
    execution_body: Mapping[str, Any],
    evidence_snapshot_digest: str,
    policy_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if policy not in POLICIES:
        raise Q1RContextArchiveError("unknown Q1R replay policy")
    memory_context = _mapping(execution_body, "memory_context")
    receipt = _mapping(execution_body, "context_receipt")
    context = _required_text(memory_context, "text")
    reader_digest = _required_digest(memory_context, "reader_context_digest")
    semantic_digest = _required_digest(memory_context, "semantic_context_digest")
    if hashlib.sha256(context.encode("utf-8")).hexdigest() != reader_digest:
        raise Q1RContextArchiveError("Runtime Reader Context digest drifted")
    if receipt.get("reader_context_digest") != reader_digest:
        raise Q1RContextArchiveError("ContextReceipt Reader digest drifted")
    if receipt.get("semantic_context_digest") != semantic_digest:
        raise Q1RContextArchiveError("ContextReceipt semantic digest drifted")
    raw_mapping = receipt.get("receipt_mapping")
    if not isinstance(raw_mapping, list) or not raw_mapping:
        raise Q1RContextArchiveError("ContextReceipt alias mapping is empty")
    receipt_mapping = [dict(_mapping_value(item, "receipt_mapping")) for item in raw_mapping]
    windows = _mapping_list(memory_context.get("windows"), "memory_context.windows")
    aliases = [_required_text(item, "alias") for item in receipt_mapping]
    sufficiency = execution_body.get("sufficiency_decision")
    memory_query_ir = execution_body.get("memory_query_ir")
    requirements = (
        memory_query_ir.get("requirements")
        if isinstance(memory_query_ir, Mapping)
        else []
    )
    progressive_l1 = execution_body.get("progressive_l1")
    acquisition_trace = (
        {
            "plan": progressive_l1.get("acquisition_plan"),
            "probe_dispositions": progressive_l1.get(
                "acquisition_probe_dispositions"
            ),
            "candidate_counts": progressive_l1.get("candidate_counts"),
        }
        if isinstance(progressive_l1, Mapping)
        and progressive_l1.get("acquisition_plan") is not None
        else None
    )
    semantic_mediators = {
        "acquisition_trace": acquisition_trace,
        "memory_status": execution_body.get("status"),
        "selected_source_refs": _text_list(
            memory_context,
            "selected_source_turn_refs",
        ),
        "selected_order": aliases,
        "evidence_prose": [_required_text(window, "text") for window in windows],
        "speaker_time": [
            {
                "alias": f"E{ordinal}",
                "speakers": window.get("speakers", []),
                "observed_at": window.get("observed_at"),
            }
            for ordinal, window in enumerate(windows, start=1)
        ],
        "scope_authority": {
            "authority_class": memory_context.get("authority_class"),
            "canonical_mutation": receipt.get("canonical_mutation"),
        },
        "binding_annotations": {
            "requirements": requirements,
            "window_requirement_priority": [
                window.get("requirement_priority") for window in windows
            ],
        },
        "sufficiency": sufficiency,
        "derived_result": execution_body.get("derived_result"),
        "truncation": memory_context.get("context_truncated"),
    }
    access_trace = _mapping(execution_body, "access_trace")
    spans = _mapping(access_trace, "spans")
    query_latency = spans.get("runtime_kernel_ms")
    if (
        isinstance(query_latency, bool)
        or not isinstance(query_latency, (int, float))
        or query_latency < 0
    ):
        raise Q1RContextArchiveError("Runtime replay lacks query latency")
    return {
        "case_id": case_id,
        "token_budget": token_budget,
        "policy": policy,
        "context": context,
        "context_sha256": reader_digest,
        "context_tokens": memory_context.get("estimated_tokens"),
        "query_latency_ms": float(query_latency),
        "evidence_snapshot_digest": evidence_snapshot_digest,
        "context_identity": {
            "semantic_context_digest": semantic_digest,
            "reader_context_digest": reader_digest,
            "receipt_mapping": receipt_mapping,
        },
        "semantic_mediators": semantic_mediators,
        "semantic_mediator_digest": canonical_sha256(semantic_mediators),
        "policy_metadata": dict(policy_metadata),
        "retrieval_trace": {
            "trace_id": execution_body.get("trace_id"),
            "terminal_stage": access_trace.get("terminal_stage"),
            "attempted_stages": access_trace.get("attempted_stages"),
            "stop_reason": access_trace.get("stop_reason"),
            "structural_cost": access_trace.get("structural_cost"),
        },
    }


def seal_context_archive(
    *,
    run_id: str,
    selection: Mapping[str, Any],
    snapshots: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    snapshot_entries = []
    for snapshot in snapshots:
        case_id = _required_text(snapshot, "case_id")
        snapshot_entries.append(
            {
                "case_id": case_id,
                "evidence_snapshot_digest": canonical_sha256(snapshot),
                "evidence_snapshot": dict(snapshot),
            }
        )
    archive = {
        "schema": CONTEXT_ARCHIVE_SCHEMA,
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "label_fields_available": False,
        "historical_answer_reuse": False,
        "selection": dict(selection),
        "record_count": len(records),
        "snapshots": snapshot_entries,
        "records": [dict(record) for record in records],
    }
    case_ids = [_required_text(snapshot, "case_id") for snapshot in snapshots]
    validate_context_archive(archive, case_ids=case_ids)
    return archive


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value.get(key)
    if not isinstance(raw, Mapping):
        raise Q1RContextArchiveError(f"{key} mapping is missing")
    return raw


def _mapping_value(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Q1RContextArchiveError(f"{path} entry is malformed")
    return value


def _mapping_list(value: object, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise Q1RContextArchiveError(f"{path} must be a list")
    return [_mapping_value(item, path) for item in value]


def _required_text(value: Mapping[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise Q1RContextArchiveError(f"{key} must be a non-empty string")
    return raw


def _required_digest(value: Mapping[str, Any], key: str) -> str:
    raw = _required_text(value, key)
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise Q1RContextArchiveError(f"{key} must be a lowercase SHA-256")
    return raw


def _text_list(value: Mapping[str, Any], key: str) -> list[str]:
    raw = value.get(key)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise Q1RContextArchiveError(f"{key} must be a string list")
    return list(raw)
