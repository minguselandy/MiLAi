"""A turn's explicit maintenance receipt, checked against delivered observations and writes."""

from __future__ import annotations

import copy
from typing import Any

from milai_lab.runners.contextual_session import HostSession

MAINTENANCE_PROTOCOL = "turn-maintenance-v2"

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "sources": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "decision": {"enum": ["saved", "no_change", "pending"]},
            "record_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact mN handles of already committed current records, "
                "never proposed memory text.",
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["sources", "decision", "record_refs", "reason"],
        "additionalProperties": False,
    },
}

FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"memory_review": REVIEW_SCHEMA, "answer": {"type": "string"}},
    "required": ["memory_review", "answer"],
    "additionalProperties": False,
}

FINISH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish_turn",
        "description": "Finish this turn with an answer and the maintenance decision for each new "
        "observation. Save or revise supported future-use matters before finishing. "
        "No change is valid for routine or already represented information. "
        "Pending means memory maintenance is unfinished; do not claim it was saved.",
        "parameters": FINAL_SCHEMA,
    },
}


def observe(session: HostSession, ref: str, projected: dict[str, Any], role: str) -> None:
    """Register an actual new event; repeated intake does not create another obligation."""
    known = session.maintenance.setdefault("observed", [])
    if ref in known:
        return
    known.append(ref)
    rows = projected.get("materials", [])
    row: dict[str, Any] = next((item for item in rows if item.get("kind") == "source"), {})
    alias = row.get("ref", f"unavailable:{len(known)}")
    # A truncated source may contain additional changes. Acknowledge it as pending
    # until it has actually been expanded, rather than claiming to review hidden text.
    session.maintenance.setdefault("pending", {})[ref] = {"ref": alias, "role": role}


def committed(session: HostSession, receipt: Any, internal: dict[str, Any]) -> None:
    operations = session.maintenance.setdefault("unsettled_operations", {})
    if receipt.completion in {"partial_failure", "pending"}:
        operations[receipt.operation_id] = {
            "completion": receipt.completion,
            "pending": list(receipt.pending),
        }
    elif receipt.ok:
        operations.pop(receipt.operation_id, None)
    if not receipt.ok or receipt.decision != "COMMITTED":
        return
    record = internal.get("record", {})
    ref = record.get("ref")
    if ref and ref in receipt.memory_changes:
        session.maintenance.setdefault("writes", []).append(ref)


def pending_materials(session: HostSession) -> list[dict[str, Any]]:
    pending = session.maintenance.get("pending", {})
    support: dict[str, list[str]] = {ref: [] for ref in pending}
    if session.memory is not None:
        seen: set[str] = set()
        for alias, binding in reversed(list(session.visible_bindings.items())):
            if (binding.kind != "interpretation" or binding.exact_ref in seen or
                    binding.exact_ref not in session.maintenance.get("writes", [])):
                continue
            record = session.memory.read(binding.exact_ref, include_sources=False, _visible=False)
            if record.get("status") != "CURRENT" or record.get("persistence") != "durable":
                continue
            seen.add(binding.exact_ref)
            for ref in record.get("source_refs", []):
                if ref in support:
                    support[ref].append(alias)
    return [{**item, "committed_record_refs": support[ref]} for ref, item in pending.items()]


def finish_tool(session: HostSession) -> dict[str, Any]:
    """Constrain the receipt to available handles; do not expose a fictitious write path."""
    tool = copy.deepcopy(FINISH_TOOL)
    review = tool["function"]["parameters"]["properties"]["memory_review"]
    sources = [item["ref"] for item in pending_materials(session)]
    if not sources:
        review["maxItems"] = 0
        return tool
    properties = review["items"]["properties"]
    properties["sources"]["items"] = {"enum": sources}
    records = []
    if session.memory is not None:
        for alias, binding in session.visible_bindings.items():
            if (binding.kind == "interpretation" and
                    binding.exact_ref in session.maintenance.get("writes", [])):
                record = session.memory.read(binding.exact_ref, include_sources=False,
                                             _visible=False)
                if record.get("status") == "CURRENT" and record.get("persistence") == "durable":
                    records.append(alias)
    if records:
        properties["record_refs"]["items"] = {"enum": records}
    else:
        properties["record_refs"]["maxItems"] = 0
        properties["decision"]["enum"] = ["no_change", "pending"]
    return tool


def finish(session: HostSession, review: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate completeness and real durable writes; semantic decisions remain the Host's."""
    memory, view = session.memory, session.material_view
    if memory is None or view is None:
        raise ValueError("MAINTENANCE_REQUIRES_MEMORY")
    session.refresh_visibility()
    pending = session.maintenance.get("pending", {})
    by_alias = {item["ref"]: ref for ref, item in pending.items()}
    covered: set[str] = set()
    unsettled: set[str] = set()
    for item in review:
        if not item["reason"].strip():
            raise ValueError("MAINTENANCE_REASON_REQUIRED")
        sources = item["sources"]
        if not sources or len(set(sources)) != len(sources):
            raise ValueError("MAINTENANCE_SOURCE_LIST_INVALID")
        if any(alias not in by_alias or alias in covered for alias in sources):
            raise ValueError("MAINTENANCE_SOURCE_UNKNOWN_OR_DUPLICATED")
        covered.update(sources)
        if item["decision"] == "pending":
            unsettled.update(sources)
            continue
        for alias in sources:
            ref = by_alias[alias]
            length = len(memory.sources[ref].content)
            spans = sorted(memory.visible_source_ranges.get(ref, set()))
            end = 0
            for lower, upper in spans:
                if lower <= end:
                    end = max(end, upper)
            if end < length:
                raise ValueError("MAINTENANCE_SOURCE_NOT_FULLY_DELIVERED")
        if item["decision"] == "saved":
            if not item["record_refs"]:
                raise ValueError("MAINTENANCE_SAVED_WITHOUT_RECORD")
            supported: set[str] = set()
            for alias in item["record_refs"]:
                if alias not in session.visible_bindings:
                    raise ValueError("MAINTENANCE_RECORD_NOT_DELIVERED")
                binding = view.binding(alias)
                ref = binding.exact_ref
                if binding.kind != "interpretation" or ref not in session.maintenance.get(
                    "writes", []
                ):
                    raise ValueError("MAINTENANCE_RECORD_NOT_COMMITTED")
                record = memory.read(ref, include_sources=False, _visible=False)
                if record.get("status") != "CURRENT" or record.get("persistence") != "durable":
                    raise ValueError("MAINTENANCE_RECORD_NOT_CURRENT_DURABLE")
                supported.update(record.get("source_refs", []))
            missing = [alias for alias in sources if by_alias[alias] not in supported]
            if missing:
                raise ValueError(
                    "MAINTENANCE_SAVED_WITHOUT_SOURCE_SUPPORT: sources "
                    f"{missing} are not cited by records {item['record_refs']}. "
                    "If these sources support the saved claim, revise its complete source_refs; "
                    "otherwise review these sources separately as no_change or pending."
                )
        elif item["decision"] != "no_change":
            raise ValueError("MAINTENANCE_UNKNOWN_DECISION")
    if covered != set(by_alias):
        raise ValueError("MAINTENANCE_OBSERVATIONS_NOT_REVIEWED")
    session.maintenance["pending"] = {
        ref: item for ref, item in pending.items() if item["ref"] in unsettled
    }
    operations = session.maintenance.get("unsettled_operations", {})
    result = {
        "protocol": MAINTENANCE_PROTOCOL,
        "status": "pending" if unsettled or operations else "complete",
        "review": review,
        "unsettled_operations": operations,
    }
    session.maintenance["last_review"] = result
    return result
