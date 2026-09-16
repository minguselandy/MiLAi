from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

RetrievalStatus = Literal["HIT", "MISS", "DEGRADED", "ERROR"]


def render_memory_evidence_context(
    raw: Mapping[str, Any],
    *,
    requested_profile: str | None,
    resolved_profile: str,
    include_read_references: bool = False,
) -> dict[str, Any]:
    """Render one governed Runtime result for a reasoning-capable MCP Host.

    The Runtime result remains the source of memory correctness.  This renderer
    deliberately removes Reader decisions, ranking scores and typed completion
    details; it does not reinterpret them as answer sufficiency.
    """

    evidence = _reader_visible_units(raw, include_read_references=include_read_references)
    if include_read_references:
        for unit in evidence:
            unit["read_references"] = [{
                "object_type": "EVIDENCE", "evidence_id": evidence_id,
                "read_tool": "milai_evidence_get", "read_arguments": {"evidence_id": evidence_id},
            } for evidence_id in dict.fromkeys(unit["evidence_ids"])]
            if unit.get("claim_id") is not None:
                unit["read_references"].append({
                    "object_type": "CANONICAL_STATE", "claim_id": unit["claim_id"],
                    "returned_claim_version_id": unit.get("claim_version_id"),
                    "read_tool": "milai_memory_get",
                    "read_arguments": {"claim_id": unit["claim_id"]},
                    "read_semantics": "CURRENT_CANONICAL",
                })
    warnings = _warnings(raw, evidence_present=bool(evidence))
    return {
        "schema_version": "memory-evidence-context-v1",
        "retrieval_status": _retrieval_status(raw, evidence, warnings),
        "context_id": _context_id(raw),
        "snapshot": _snapshot(raw),
        "continuation": _proven_continuation(raw),
        "evidence": evidence,
        "warnings": warnings,
        "profile": {
            "requested": requested_profile,
            "resolved": resolved_profile,
        },
    }


def _reader_visible_units(
    raw: Mapping[str, Any], *, include_read_references: bool = False,
) -> list[dict[str, Any]]:
    # ABSENT/ABSTAINED Runtime contexts contain a bounded control envelope such
    # as ``memory_status=ABSENT``.  That envelope is useful on the Runtime wire,
    # but it is not Evidence and must not turn an empty result into an MCP HIT.
    if raw.get("status") in {"ABSENT", "ABSTAINED"}:
        return []
    context = raw.get("memory_context")
    if isinstance(context, Mapping):
        windows = context.get("windows")
        if isinstance(windows, Sequence) and not isinstance(windows, (str, bytes)):
            rendered = [
                unit
                for ordinal, window in enumerate(windows, start=1)
                if (unit := _window_unit(window, ordinal)) is not None
            ]
            if rendered:
                return rendered
        text = context.get("text")
        if isinstance(text, str) and text.strip():
            evidence_ids = _strings(context.get("selected_evidence_ids"))
            source_turn_refs = _strings(context.get("selected_source_turn_refs"))
            context_id = _context_id(raw)
            digest = _optional_string(context.get("reader_context_digest"))
            return [
                {
                    "id": context_id or f"context:{digest or _sha256(text)}",
                    "alias": "E1",
                    "kind": "EVIDENCE_CONTEXT",
                    "text": text,
                    "evidence_ids": evidence_ids,
                    "source": {
                        "type": "memory_context",
                        "id": context_id or _optional_string(raw.get("trace_id")) or "ephemeral",
                        "turn_refs": source_turn_refs,
                    },
                }
            ]

    items = raw.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    rendered_items: list[dict[str, Any]] = []
    for item in items:
        unit = _item_unit(item, len(rendered_items) + 1,
                          include_read_references=include_read_references)
        if unit is not None:
            rendered_items.append(unit)
    return rendered_items


def _window_unit(value: object, ordinal: int) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    evidence_ids = _strings(value.get("evidence_ids"))
    source_turn_refs = _strings(value.get("source_turn_refs"))
    window_id = _optional_string(value.get("window_id"))
    unit_id = (
        evidence_ids[0]
        if len(evidence_ids) == 1
        else window_id or f"context-window:{_sha256(text)}"
    )
    session_id = _optional_string(value.get("session_id"))
    unit: dict[str, Any] = {
        "id": unit_id,
        "alias": f"E{ordinal}",
        "kind": "EVIDENCE",
        "text": text,
        "evidence_ids": evidence_ids,
        "source": {
            "type": "agent_session" if session_id is not None else "memory_context",
            "id": session_id or window_id or unit_id,
            "turn_refs": source_turn_refs,
        },
    }
    observed_at = _optional_string(value.get("observed_at"))
    if observed_at is not None:
        unit["observed_at"] = observed_at
    return unit


def _item_unit(
    value: object, ordinal: int, *, include_read_references: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    evidence_id = _optional_string(value.get("evidence_id"))
    claim_version_id = _optional_string(value.get("claim_version_id"))
    claim_id = _optional_string(value.get("claim_id"))
    content = value.get("content")
    if isinstance(content, str) and content.strip():
        text = content
        kind = "EVIDENCE"
        source_type = "evidence_record"
        unit_id = evidence_id or f"evidence:{_sha256(text)}"
    else:
        payload = value.get("payload")
        if payload is None:
            return None
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        kind = "CANONICAL_STATE"
        source_type = "canonical_state"
        unit_id = claim_version_id or claim_id or f"canonical:{_sha256(text)}"
    source_ref = _optional_string(value.get("source_ref"))
    evidence_ids = [evidence_id] if evidence_id is not None else _strings(value.get("evidence_ids"))
    unit: dict[str, Any] = {
        "id": unit_id,
        "alias": f"E{ordinal}",
        "kind": kind,
        "text": text,
        "evidence_ids": evidence_ids,
        "source": {
            "type": source_type,
            "id": source_ref or claim_version_id or claim_id or unit_id,
            "turn_refs": [source_ref] if source_ref is not None else [],
        },
    }
    observed_at = _optional_string(value.get("observed_at"))
    if observed_at is not None:
        unit["observed_at"] = observed_at
    validity = {
        key: cast(str, value[key])
        for key in ("valid_from", "valid_to")
        if isinstance(value.get(key), str) and value[key]
    }
    if validity:
        unit["validity"] = validity
    if include_read_references and kind == "CANONICAL_STATE" and claim_id is not None:
        unit["claim_id"] = claim_id
        unit["claim_version_id"] = claim_version_id
    return unit


def _retrieval_status(
    raw: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, str]],
) -> RetrievalStatus:
    runtime_status = raw.get("status")
    availability = raw.get("availability")
    warning_codes = {warning["code"] for warning in warnings}
    if runtime_status in {"DENIED", "UNAVAILABLE"} or availability == "UNAVAILABLE":
        return "ERROR"
    if evidence:
        if warning_codes & {"CANONICAL_CONTESTED", "RETRIEVAL_DEGRADED"}:
            return "DEGRADED"
        return "HIT"
    if runtime_status == "CONTESTED" or availability == "DEGRADED":
        return "DEGRADED"
    return "MISS"


def _warnings(
    raw: Mapping[str, Any], *, evidence_present: bool
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    status = raw.get("status")
    availability = raw.get("availability")
    if status == "DENIED":
        warnings.append(
            {
                "code": "ACCESS_DENIED",
                "message": "Memory access was denied by the Runtime policy boundary.",
            }
        )
    elif status == "UNAVAILABLE" or availability == "UNAVAILABLE":
        warnings.append(
            {
                "code": "MEMORY_UNAVAILABLE",
                "message": "The governed memory Runtime was unavailable.",
            }
        )
    if status == "CONTESTED" or bool(raw.get("open_issue_ids")):
        warnings.append(
            {
                "code": "CANONICAL_CONTESTED",
                "message": (
                    "The Runtime reports unresolved memory state; do not treat it as current fact."
                ),
            }
        )
    degraded = raw.get("degraded_components")
    if (
        availability == "DEGRADED"
        or (
            isinstance(degraded, Sequence)
            and not isinstance(degraded, (str, bytes))
            and bool(degraded)
        )
    ):
        warnings.append(
            {
                "code": "RETRIEVAL_DEGRADED",
                "message": (
                    "The returned memory context was limited by the context budget."
                    if degraded in (["context_budget"], ("context_budget",))
                    else "Retrieval component problems or limits reduced the available result."
                ),
            }
        )
    if status in {"HIT", "PARTIAL"} and not evidence_present:
        warnings.append(
            {
                "code": "CONTEXT_NOT_RENDERED",
                "message": "The Runtime returned a memory result without Host-visible evidence.",
            }
        )
    return _deduplicate_warnings(warnings)


def _snapshot(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    position = raw.get("canonical_position")
    if isinstance(position, int) and not isinstance(position, bool) and position >= 0:
        result["canonical_position"] = position
    elif isinstance(position, Mapping):
        canonical = position.get("canonical_outbox_sequence")
        if isinstance(canonical, int) and not isinstance(canonical, bool) and canonical >= 0:
            result["canonical_position"] = canonical
    as_of = _optional_string(raw.get("resolved_as_of"))
    if as_of is not None:
        result["as_of"] = as_of
    return result or None


def _proven_continuation(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    continuation = raw.get("continuation")
    if not isinstance(continuation, Mapping):
        return None
    available = continuation.get("available")
    reason = _optional_string(continuation.get("reason"))
    if not isinstance(available, bool) or reason is None:
        return None
    return {"available": available, "reason": reason}


def _context_id(raw: Mapping[str, Any]) -> str | None:
    direct = _optional_string(raw.get("context_id"))
    if direct is not None:
        return direct
    receipt = raw.get("context_receipt")
    if not isinstance(receipt, Mapping):
        return None
    return _optional_string(receipt.get("context_id")) or _optional_string(
        receipt.get("context_capsule_id")
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _deduplicate_warnings(values: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return list({item["code"]: item for item in values}.values())
