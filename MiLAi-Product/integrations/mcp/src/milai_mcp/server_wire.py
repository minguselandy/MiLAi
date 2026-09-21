"""MCP wire identity primitives."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from milai_mcp.server_contracts import _READ_ONLY_TOOL_NAMES

_MAX_OUTPUT_BYTES = 65_536
_WIDE_MAX_OUTPUT_BYTES = 262_144


def _wire_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _bounded(value: dict[str, Any], *, max_output_bytes: int = _MAX_OUTPUT_BYTES) -> dict[str, Any]:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if len(raw) <= max_output_bytes:
        return value
    return {
        "status": "TRUNCATED",
        "reason": "MCP_OUTPUT_LIMIT",
        "original_bytes": len(raw),
    }


def _with_mcp_guidance(
    value: dict[str, Any],
    message: str,
    *,
    next_tool: str | None = None,
    when: str | None = None,
    next_arguments: dict[str, Any] | None = None,
    ordinary: bool = False,
) -> dict[str, Any]:
    """Attach a short server-authored next-step hint without trusting result data."""

    guidance: dict[str, Any] = {
        "source": "MILAI_SERVER",
        "message": message,
    }
    if next_tool is not None:
        guidance["next_tool"] = next_tool
        guidance["optional"] = True
        if next_tool in {
            "milai_proposal_create",
            "milai_memory_review",
            "milai_evidence_revoke",
            "milai_namespace_cleanup_submit",
            "milai_note_delete",
        }:
            guidance["requires_user_authorization"] = True
    if when is not None:
        guidance["when"] = when
    if next_arguments is not None:
        guidance["next_arguments"] = next_arguments
    if ordinary:
        guidance.update(optional=True, authorization_granted=False)
        guidance["requires_user_authorization"] = (
            next_tool is not None and next_tool not in _READ_ONLY_TOOL_NAMES
        )
        return {
            **{
                key: item
                for key, item in value.items()
                if key not in {"mcp_guidance", "suggested_next_step"}
            },
            "suggested_next_step": guidance,
        }
    return {**value, "mcp_guidance": guidance}


def _wire_operand_pointer(value: object, ordinal: int) -> dict[str, Any]:
    """Retain typed operand identity while deduplicating its full wire material."""

    if not isinstance(value, dict):
        return {
            "wire_operand_ordinal": ordinal,
            "wire_operand_sha256": _wire_sha256(value),
        }
    retained_keys = (
        "slot",
        "value",
        "unit",
        "evidence_id",
        "evidence_ids",
        "source_evidence_id",
        "source_evidence_ids",
        "source_ref",
        "source_refs",
        "source_turn_ref",
        "source_turn_refs",
        "source_role",
        "session_id",
        "purpose",
        "authority_class",
        "canonical_mutation",
        "requirement_binding",
    )
    return {
        **{key: deepcopy(value[key]) for key in retained_keys if key in value},
        "wire_operand_ordinal": ordinal,
        "wire_operand_sha256": _wire_sha256(value),
    }


def _wire_receipt(value: object) -> dict[str, Any]:
    receipt: dict[str, Any] = {"sha256": _wire_sha256(value)}
    if isinstance(value, (dict, list)):
        receipt["item_count"] = len(value)
    return receipt


def _deduplicate_resolve_proof_trace(value: dict[str, Any]) -> list[str]:
    compacted: list[str] = []
    derived = value.get("derived_result")
    if isinstance(derived, dict):
        trace = derived.get("trace")
        if isinstance(trace, dict):
            slots = trace.get("slots")
            if isinstance(slots, list):
                for slot in slots:
                    if not isinstance(slot, dict) or not isinstance(slot.get("operands"), list):
                        continue
                    slot["operands"] = [
                        _wire_operand_pointer(operand, ordinal)
                        for ordinal, operand in enumerate(slot["operands"])
                    ]
                compacted.append("derived_result.trace.slots.operands")
            applicability = trace.get("applicability")
            if isinstance(applicability, list):
                for item in applicability:
                    if not isinstance(item, dict) or item.get("span") is None:
                        continue
                    item["span"] = {
                        "wire_representation": "SHA256_ONLY_DUPLICATE_OPERAND_SPAN",
                        "sha256": _wire_sha256(item["span"]),
                    }
                compacted.append("derived_result.trace.applicability.span")
    search_trace = value.get("search_trace")
    if isinstance(search_trace, dict):
        receipts: dict[str, Any] = {}
        for key in (
            "acquisition_capability",
            "acquisition_plan",
            "acquisition_probe_dispositions",
            "sufficiency_decisions",
        ):
            if key not in search_trace:
                continue
            receipts[key] = _wire_receipt(search_trace.pop(key))
        if receipts:
            search_trace["mcp_wire_receipts"] = receipts
            compacted.append("search_trace.verbose_diagnostics")
    return compacted


def _compact_resolve_operands(value: dict[str, Any]) -> list[str]:
    derived = value.get("derived_result")
    if not isinstance(derived, dict) or not isinstance(derived.get("operands"), list):
        return []
    derived["operands"] = [
        _wire_operand_pointer(operand, ordinal)
        for ordinal, operand in enumerate(derived["operands"])
    ]
    return ["derived_result.operands"]


def _compact_mapping_diagnostics(
    value: dict[str, Any],
    field: str,
    *,
    retained_keys: frozenset[str],
) -> list[str]:
    """Digest bulky diagnostic branches while retaining decision-bearing fields."""

    raw_mapping = value.get(field)
    if not isinstance(raw_mapping, dict):
        return []
    removable = {
        key: item
        for key, item in raw_mapping.items()
        if key not in retained_keys
        and key != "mcp_wire_receipts"
        and isinstance(item, (dict, list))
    }
    if not removable:
        return []
    receipts = raw_mapping.get("mcp_wire_receipts")
    receipt_mapping = dict(receipts) if isinstance(receipts, dict) else {}
    receipt_mapping["compacted_diagnostics"] = {
        key: _wire_receipt(item) for key, item in sorted(removable.items())
    }
    for key in removable:
        raw_mapping.pop(key, None)
    raw_mapping["mcp_wire_receipts"] = receipt_mapping
    return [f"{field}.compacted_diagnostics"]


def _compact_raw_evidence_items(value: dict[str, Any]) -> list[str]:
    """Keep Raw Evidence identity and scores when Context already carries prose."""

    raw_items = value.get("items")
    if (
        not isinstance(raw_items, list)
        or not raw_items
        or not isinstance(value.get("memory_context"), dict)
        or any(
            not isinstance(item, dict) or item.get("kind") != "EVIDENCE_OBSERVATION"
            for item in raw_items
        )
    ):
        return []
    retained_keys = (
        "kind",
        "canonical",
        "evidence_id",
        "source_ref",
        "relevance_score",
    )
    value["items"] = [
        {
            **{key: deepcopy(item[key]) for key in retained_keys if key in item},
            "wire_item_sha256": _wire_sha256(item),
        }
        for item in raw_items
    ]
    raw_receipts = value.get("mcp_wire_receipts")
    receipts = dict(raw_receipts) if isinstance(raw_receipts, dict) else {}
    receipts["compacted_raw_items"] = {
        **_wire_receipt(raw_items),
        "preserved_fields": list(retained_keys),
        "wire_representation": "CONSUMER_FIELDS_PER_ITEM_PLUS_ITEM_AND_LIST_DIGESTS",
    }
    value["mcp_wire_receipts"] = receipts
    return ["items.raw_evidence_payloads"]


def _compact_context_compile_diagnostics(value: dict[str, Any]) -> list[str]:
    """Digest replayable compiler diagnostics while retaining all gate facts."""

    memory_context = value.get("memory_context")
    if not isinstance(memory_context, dict):
        return []
    compile_trace = memory_context.get("compile_trace")
    if not isinstance(compile_trace, dict):
        return []
    diagnostic_keys = (
        "expansion_trace",
        "omitted_unit_reasons",
        "plan_omitted_units",
        "conditional_activation_thresholds",
        "conditional_unit_order",
    )
    removable = {
        key: compile_trace[key]
        for key in diagnostic_keys
        if key in compile_trace and isinstance(compile_trace[key], (dict, list))
    }
    if not removable:
        return []
    raw_receipts = compile_trace.get("mcp_wire_receipts")
    receipts = dict(raw_receipts) if isinstance(raw_receipts, dict) else {}
    receipts["compacted_diagnostics"] = {
        key: _wire_receipt(item) for key, item in removable.items()
    }
    for key in removable:
        compile_trace.pop(key, None)
    compile_trace["mcp_wire_receipts"] = receipts
    return ["memory_context.compile_trace.compacted_diagnostics"]


def _compact_context_windows(value: dict[str, Any]) -> list[str]:
    """Remove Reader-prose duplication while retaining window topology and lineage."""

    memory_context = value.get("memory_context")
    if not isinstance(memory_context, dict):
        return []
    windows = memory_context.get("windows")
    if (
        not isinstance(windows, list)
        or not windows
        or any(not isinstance(window, dict) for window in windows)
    ):
        return []
    retained_keys = (
        "window_id",
        "session_id",
        "evidence_ids",
        "truncated",
        "expansions",
    )
    memory_context["windows"] = [
        {
            **{key: deepcopy(window[key]) for key in retained_keys if key in window},
        }
        for window in windows
    ]
    compile_trace = memory_context.get("compile_trace")
    if isinstance(compile_trace, dict):
        raw_receipts = compile_trace.get("mcp_wire_receipts")
        receipts = dict(raw_receipts) if isinstance(raw_receipts, dict) else {}
        window_receipt = _wire_receipt(windows)
        window_receipt.update(
            {
                "source_turn_ref_count": sum(
                    len(window["source_turn_refs"])
                    if isinstance(window.get("source_turn_refs"), list)
                    else 0
                    for window in windows
                ),
                "wire_representation": "IDENTITY_SESSION_ADJACENCY_PLUS_AGGREGATE_DIGEST",
            }
        )
        receipts["compacted_windows"] = window_receipt
        compile_trace["mcp_wire_receipts"] = receipts
    return ["memory_context.windows.redundant_presentation"]


def _wire_proof_pointer(
    value: dict[str, Any],
    *,
    retained_keys: tuple[str, ...],
    representation: str,
) -> dict[str, Any]:
    return {
        **{key: deepcopy(value[key]) for key in retained_keys if key in value},
        "wire_representation": representation,
        "wire_proof_sha256": _wire_sha256(value),
    }


def _compact_top_level_resolve_proof(value: dict[str, Any]) -> list[str]:
    """Deduplicate replayable plans/proofs while retaining strict terminal facts."""

    compacted: list[str] = []
    receipts: dict[str, Any] = {}
    memory_query_ir = value.get("memory_query_ir")
    if isinstance(memory_query_ir, dict):
        receipts["memory_query_ir"] = _wire_receipt(memory_query_ir)
        value["memory_query_ir"] = _wire_proof_pointer(
            memory_query_ir,
            retained_keys=(
                "schema_version",
                "mode",
                "answer_shape",
                "completeness",
            ),
            representation="TERMINAL_FACTS_AND_SHA256",
        )
        compacted.append("memory_query_ir.replayable_plan")

    decision_keys = (
        "schema_version",
        "status",
        "covered_slots",
        "missing_slots",
        "stop_reason",
        "reason_code",
        "required_slots",
        "unresolved_reasons",
    )
    sufficiency = value.get("sufficiency_decision")
    if isinstance(sufficiency, dict):
        receipts["sufficiency_decision"] = _wire_receipt(sufficiency)
        value["sufficiency_decision"] = _wire_proof_pointer(
            sufficiency,
            retained_keys=decision_keys,
            representation="STRICT_TERMINAL_FACTS_AND_SHA256",
        )
        compacted.append("sufficiency_decision.replayable_proof")

    search_trace = value.get("search_trace")
    if isinstance(search_trace, dict):
        terminal = search_trace.get("terminal_sufficiency_decision")
        if isinstance(terminal, dict):
            receipts["search_trace.terminal_sufficiency_decision"] = _wire_receipt(terminal)
            search_trace["terminal_sufficiency_decision"] = _wire_proof_pointer(
                terminal,
                retained_keys=decision_keys,
                representation="STRICT_TERMINAL_FACTS_AND_SHA256",
            )
            compacted.append("search_trace.terminal_sufficiency_decision.replayable_proof")

    if receipts:
        raw_receipts = value.get("mcp_wire_receipts")
        wire_receipts = dict(raw_receipts) if isinstance(raw_receipts, dict) else {}
        wire_receipts["compacted_top_level_proof"] = receipts
        value["mcp_wire_receipts"] = wire_receipts
    return compacted


def _compact_derived_operator_trace(value: dict[str, Any]) -> list[str]:
    """Keep operator terminal facts while deduplicating replayable trace rows.

    The top-level derived result remains the authoritative wire material for the
    value, completeness and supporting operands.  ``OperatorTrace`` repeats
    those operands in ``slots`` and repeats every scanned candidate in
    ``applicability``; on bounded scans that diagnostic copy can dominate the
    MCP response even after each span has already become a digest pointer.
    """

    derived = value.get("derived_result")
    if not isinstance(derived, dict):
        return []
    raw_trace = derived.get("trace")
    if not isinstance(raw_trace, dict):
        return []

    slots = raw_trace.get("slots")
    applicability = raw_trace.get("applicability")
    if not isinstance(slots, list) and not isinstance(applicability, list):
        return []

    compact_trace = {
        key: deepcopy(item)
        for key, item in raw_trace.items()
        if key not in {"slots", "applicability", "mcp_wire_receipts"}
    }
    receipts: dict[str, Any] = {}
    if isinstance(slots, list):
        receipts["slots"] = _wire_receipt(slots)
        compact_slots: list[dict[str, Any]] = []
        for ordinal, slot in enumerate(slots):
            if not isinstance(slot, dict):
                compact_slots.append(
                    {
                        "wire_slot_ordinal": ordinal,
                        "wire_slot_sha256": _wire_sha256(slot),
                    }
                )
                continue
            operands = slot.get("operands")
            compact_slots.append(
                {
                    **{
                        key: deepcopy(slot[key])
                        for key in ("name", "status", "unresolved_reason")
                        if key in slot
                    },
                    "operands": [],
                    "wire_operand_count": (len(operands) if isinstance(operands, list) else None),
                    "wire_operands_sha256": _wire_sha256(operands),
                    "wire_slot_ordinal": ordinal,
                }
            )
        compact_trace["slots"] = compact_slots
    if isinstance(applicability, list):
        receipts["applicability"] = _wire_receipt(applicability)
        accepted = sum(
            isinstance(item, dict) and item.get("accepted") is True for item in applicability
        )
        reason_counts: dict[str, int] = {}
        for item in applicability:
            if not isinstance(item, dict):
                reason = "NON_MAPPING"
            else:
                reason = str(item.get("reason", "UNSPECIFIED"))
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        compact_trace["applicability"] = []
        compact_trace["wire_applicability_summary"] = {
            "item_count": len(applicability),
            "accepted_count": accepted,
            "rejected_count": len(applicability) - accepted,
            "reason_counts": dict(sorted(reason_counts.items())),
            "sha256": _wire_sha256(applicability),
            "wire_representation": "SUMMARY_AND_SHA256",
        }

    previous = raw_trace.get("mcp_wire_receipts")
    wire_receipts = dict(previous) if isinstance(previous, dict) else {}
    wire_receipts["compacted_operator_trace"] = {
        "full_trace": _wire_receipt(raw_trace),
        **receipts,
    }
    compact_trace["mcp_wire_receipts"] = wire_receipts
    derived["trace"] = compact_trace
    return ["derived_result.trace.replayable_operator_proof"]


def _wire_field_sizes(value: dict[str, Any]) -> dict[str, int]:
    """Return bounded structural byte diagnostics without payload material."""

    ranked = sorted(
        (
            (
                str(key)[:120],
                len(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()),
            )
            for key, item in value.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return dict(ranked[:32])


def _wire_size_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "top_level_field_bytes": _wire_field_sizes(value),
    }
    memory_context = value.get("memory_context")
    if isinstance(memory_context, dict):
        diagnostics["memory_context_field_bytes"] = _wire_field_sizes(memory_context)
    derived = value.get("derived_result")
    if isinstance(derived, dict):
        diagnostics["derived_result_field_bytes"] = _wire_field_sizes(derived)
        trace = derived.get("trace")
        if isinstance(trace, dict):
            diagnostics["derived_trace_field_bytes"] = _wire_field_sizes(trace)
    return diagnostics


def _bounded_memory_resolve(
    value: dict[str, Any],
    *,
    max_output_bytes: int = _MAX_OUTPUT_BYTES,
) -> dict[str, Any]:
    """Prefer a proof-preserving compact resolve view to an all-or-nothing truncation."""

    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if len(raw) <= max_output_bytes:
        return value
    compact = deepcopy(value)
    compacted_fields = _deduplicate_resolve_proof_trace(compact)
    original_derived = value.get("derived_result")
    compaction = {
        "schema_version": "mcp-resolve-wire-compaction-v0.1",
        "applied": True,
        "original_bytes": len(raw),
        "full_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "operator_result_sha256": (
            _wire_sha256(original_derived) if isinstance(original_derived, dict) else None
        ),
        "retrieval_trace_id": value.get("trace_id"),
        "compacted_fields": compacted_fields,
        "strict_status_preserved": True,
        "strict_completeness_preserved": True,
        "operator_operand_material": "FULL",
        "canonical_mutation": (
            original_derived.get("canonical_mutation")
            if isinstance(original_derived, dict)
            else None
        ),
    }
    compact["mcp_output_compaction"] = compaction
    compaction["compacted_bytes"] = 0
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(_compact_resolve_operands(compact))
    compaction["operator_operand_material"] = "DIGEST_POINTERS"
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(
        _compact_mapping_diagnostics(
            compact,
            "search_trace",
            retained_keys=frozenset(
                {
                    "schema_version",
                    "status",
                    "reason_code",
                    "planner_version",
                    "formation_projection",
                    "terminal_sufficiency_decision",
                }
            ),
        )
    )
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(
        _compact_mapping_diagnostics(
            compact,
            "access_trace",
            retained_keys=frozenset(
                {
                    "schema_version",
                    "runtime_request_id",
                    "retrieval_trace_id",
                    "attempted_stages",
                    "terminal_stage",
                    "stop_reason",
                    "spans",
                    "span_links",
                    "logical_mcp_calls",
                    "automatic_retry_count",
                    "retry_policy_max_retries",
                }
            ),
        )
    )
    compacted_fields.extend(_compact_raw_evidence_items(compact))
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(_compact_context_compile_diagnostics(compact))
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(_compact_context_windows(compact))
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(_compact_top_level_resolve_proof(compact))
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    compacted_fields.extend(_compact_derived_operator_trace(compact))
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    compaction["compacted_bytes"] = len(encoded)
    if len(encoded) <= max_output_bytes:
        return compact
    return {
        "schema_version": "mcp-output-limit-v0.1",
        "status": "TRUNCATED",
        "reason": "MCP_OUTPUT_LIMIT",
        "original_bytes": len(raw),
        "compacted_bytes": len(encoded),
        "full_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "wire_diagnostics": _wire_size_diagnostics(compact),
    }
