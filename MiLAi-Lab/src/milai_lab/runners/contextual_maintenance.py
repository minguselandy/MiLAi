"""A turn's explicit maintenance receipt, checked against delivered observations and writes."""

from __future__ import annotations

import copy
from typing import Any

from milai_lab.runners.contextual_session import HostSession

MAINTENANCE_PROTOCOL = "turn-maintenance-v2"
SEMANTIC_MAINTENANCE_PROTOCOL = "turn-maintenance-v3"

SEMANTIC_FINAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "maintenance": {
            "type": "object",
            "properties": {
                "decision": {"enum": ["processed", "not_selected", "pending"]},
                "remaining": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"ref": {"type": "string"},
                                   "reason": {"type": "string", "minLength": 1}},
                    "required": ["ref", "reason"], "additionalProperties": False,
                }},
            },
            "required": ["decision", "remaining"], "additionalProperties": False,
        },
        "answer": {"type": "string"},
    },
    "required": ["maintenance", "answer"], "additionalProperties": False,
}

SEMANTIC_FINISH_TOOL: dict[str, Any] = {
    "type": "function", "function": {
        "name": "finish_turn",
        "description": "Finish with a concise semantic maintenance decision. processed means all "
        "required review and persistence are actually complete; not_selected means no "
        "durable change was selected; pending lists unfinished maintenance in this turn "
        "or an unsettled operation by delivered ref. Waiting for a future customer reply "
        "or external business decision can be stated in the answer after current-turn "
        "maintenance is processed; it is not itself unfinished memory maintenance. "
        "Actual writes, read ranges and business outcomes are checked by the program.",
        "parameters": SEMANTIC_FINAL_SCHEMA,
    },
}

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


def observe(
    session: HostSession, ref: str, projected: dict[str, Any], role: str, *,
    required_review_ranges: tuple[tuple[int, int], ...] = (),
    persistence_required: bool = False,
) -> None:
    """Register an actual new event; repeated intake does not create another obligation."""
    known = session.maintenance.setdefault("observed", [])
    if ref in known:
        if session.maintenance.get("protocol") == SEMANTIC_MAINTENANCE_PROTOCOL:
            item = session.maintenance.get("pending", {}).get(ref)
            if item is not None:
                item["required_review_ranges"] = [list(span) for span in
                    dict.fromkeys([*(tuple(span) for span in item.get(
                        "required_review_ranges", [])), *required_review_ranges])]
                item["persistence_required"] |= persistence_required
        return
    known.append(ref)
    rows = projected.get("materials", [])
    row: dict[str, Any] = next((item for item in rows if item.get("kind") == "source"), {})
    alias = row.get("ref", f"unavailable:{len(known)}")
    # A truncated source may contain additional changes. Acknowledge it as pending
    # until it has actually been expanded, rather than claiming to review hidden text.
    pending_item: dict[str, Any] = {"ref": alias, "role": role}
    if session.maintenance.get("protocol") == SEMANTIC_MAINTENANCE_PROTOCOL:
        pending_item.update(required_review_ranges=[list(span) for span in required_review_ranges],
                            persistence_required=persistence_required,
                            turn_id=session.turn_id)
    session.maintenance.setdefault("pending", {})[ref] = pending_item


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
        writes = session.maintenance.setdefault("writes", [])
        if session.maintenance.get("protocol") == SEMANTIC_MAINTENANCE_PROTOCOL:
            writes.append({"ref": ref, "turn_id": session.turn_id,
                           "operation_id": receipt.operation_id})
        else:
            writes.append(ref)


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


def _missing_ranges(
    required: list[list[int]], delivered: set[tuple[int, int]],
) -> list[list[int]]:
    """Subtract actual delivered body spans from trusted required spans."""
    missing = []
    for start, end in required:
        cursor = start
        for lower, upper in sorted(delivered):
            if upper <= cursor or lower >= end:
                continue
            if lower > cursor:
                missing.append([cursor, min(lower, end)])
            cursor = max(cursor, min(upper, end))
            if cursor == end:
                break
        if cursor < end:
            missing.append([cursor, end])
    return missing


def _current_durable_support(session: HostSession) -> set[str]:
    memory = session.memory
    assert memory is not None
    supported: set[str] = set()
    for handle, card in memory.workspace.cards.items():
        if memory.details[handle].persistence == "durable" and not card.retired:
            supported.update(card.source_refs)
    return supported


def semantic_frontier(
    session: HostSession, *, business_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Program evidence for one turn; optional unread material stays explicit."""
    session.refresh_visibility()
    memory = session.memory
    assert memory is not None
    coverage = []
    for exact, item in session.maintenance.get("pending", {}).items():
        delivered = memory.visible_source_ranges.get(exact, set())
        required = item.get("required_review_ranges", [])
        total = len(memory.sources[exact].content)
        visible_alias = next((alias for alias, binding in reversed(list(
            session.visible_bindings.items())) if binding.kind == "source"
            and binding.exact_ref == exact and binding.spans), None)
        row: dict[str, Any] = {
            "ref": visible_alias or "undelivered", "role": item["role"],
            "total_chars": total,
            "delivered_ranges": [list(span) for span in sorted(delivered)],
            "unreviewed_ranges": _missing_ranges([[0, total]], delivered),
            "unreviewed_required_ranges": _missing_ranges(required, delivered),
        }
        if item.get("persistence_required"):
            row["persistence_required"] = True
        coverage.append(row)
    writes = [item for item in session.maintenance.get("writes", [])
              if isinstance(item, dict) and item.get("turn_id") == session.turn_id]
    committed_changes = []
    for item in writes:
        alias = next((short for short, binding in reversed(list(
            session.visible_bindings.items())) if binding.kind == "interpretation"
            and binding.exact_ref == item["ref"]), None)
        committed_changes.append({
            "record_ref": alias,
            "operation_id": item["operation_id"],
            "delivery": "visible" if alias is not None else "not_delivered",
        })
    unsettled = session.maintenance.get("unsettled_operations", {})
    return {
        "protocol": SEMANTIC_MAINTENANCE_PROTOCOL,
        "review_coverage": coverage,
        "committed_changes": committed_changes,
        "business_outcomes": business_outcomes or [],
        "unsettled_operations": [
            {"operation_id": operation_id, "completion": item["completion"],
             "pending_count": len(item["pending"])}
            for operation_id, item in unsettled.items()
        ],
    }


def semantic_finish_tool(session: HostSession) -> dict[str, Any]:
    tool = copy.deepcopy(SEMANTIC_FINISH_TOOL)
    refs = [item["ref"] for item in semantic_frontier(session)["review_coverage"]
            if item["ref"] != "undelivered"]
    refs += [alias for alias, binding in session.visible_bindings.items()
             if binding.kind == "interpretation"]
    remaining = tool["function"]["parameters"]["properties"]["maintenance"][
        "properties"]["remaining"]
    if refs:
        remaining["items"]["properties"]["ref"] = {"enum": list(dict.fromkeys(refs))}
    else:
        remaining["maxItems"] = 0
    return tool


def semantic_finish(
    session: HostSession, decision: dict[str, Any], *,
    business_outcomes: list[dict[str, Any]] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Accept semantic selection only when actual review, writes and outcomes permit it."""
    if session.maintenance.get("protocol") != SEMANTIC_MAINTENANCE_PROTOCOL:
        raise ValueError("MAINTENANCE_PROTOCOL_MISMATCH")
    frontier = semantic_frontier(session, business_outcomes=business_outcomes)
    choice = decision["decision"]
    remaining = decision["remaining"]
    valid_refs = {alias for alias, binding in session.visible_bindings.items()
                  if binding.kind in {"source", "interpretation"}}
    if any(item["ref"] not in valid_refs or not item["reason"].strip()
           for item in remaining):
        raise ValueError("MAINTENANCE_REMAINING_REF_NOT_DELIVERED")
    if choice == "not_selected" and frontier["committed_changes"]:
        raise ValueError("MAINTENANCE_NOT_SELECTED_AFTER_COMMITTED_WRITE")
    if choice != "pending" and remaining:
        raise ValueError("MAINTENANCE_REMAINING_CONFLICTS_WITH_DECISION")
    missing_review = [item["ref"] for item in frontier["review_coverage"]
                      if item["unreviewed_required_ranges"]]
    support = _current_durable_support(session)
    missing_persistence = [item["ref"] for exact, item in session.maintenance.get(
        "pending", {}).items() if item.get("persistence_required") and exact not in support]
    if choice != "pending":
        if missing_review:
            raise ValueError("MAINTENANCE_REQUIRED_REVIEW_MISSING: " + ", ".join(missing_review))
        if missing_persistence:
            raise ValueError("MAINTENANCE_REQUIRED_PERSISTENCE_MISSING: "
                             + ", ".join(missing_persistence))
    operations = frontier["unsettled_operations"]
    if choice == "pending" and not (remaining or missing_review or missing_persistence or
                                    operations):
        raise ValueError("MAINTENANCE_PENDING_WITHOUT_REMAINING")
    status = "pending" if choice == "pending" or operations else "complete"
    result = {
        **frontier, "status": status, "semantic_decision": choice,
        "remaining": copy.deepcopy(remaining),
        "missing_required_review": missing_review,
        "missing_required_persistence": missing_persistence,
    }
    if commit:
        if status == "complete":
            session.maintenance["pending"] = {}
        session.maintenance["last_review"] = result
    return result
