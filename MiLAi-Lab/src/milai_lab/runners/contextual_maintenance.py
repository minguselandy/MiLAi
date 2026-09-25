"""A turn's explicit maintenance receipt, checked against delivered observations and writes."""

from __future__ import annotations

import copy
import re
from typing import Any

from milai_lab.runners.contextual_session import HostSession

MAINTENANCE_PROTOCOL = "turn-maintenance-v2"
SEMANTIC_MAINTENANCE_PROTOCOL = "turn-maintenance-v3"
REPAIR_MAINTENANCE_PROTOCOL = "turn-maintenance-v4"
FRONTIER_MAINTENANCE_PROTOCOL = "turn-maintenance-v5"

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

REPAIR_FINAL_SCHEMA: dict[str, Any] = copy.deepcopy(SEMANTIC_FINAL_SCHEMA)
REPAIR_FINAL_SCHEMA["properties"]["maintenance"]["properties"]["abandoned_attempts"] = {
    "type": "array", "items": {
        "type": "object", "properties": {
            "operation_id": {"type": "string"},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["operation_id", "reason"], "additionalProperties": False,
    },
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

REPAIR_FINISH_TOOL: dict[str, Any] = copy.deepcopy(SEMANTIC_FINISH_TOOL)
REPAIR_FINISH_TOOL["function"]["parameters"] = REPAIR_FINAL_SCHEMA
REPAIR_FINISH_TOOL["function"]["description"] += (
    " Failed memory_save attempts must be repaired by a committed write using repair_of, "
    "explicitly abandoned with a reason if optional, or left pending. Before processed, "
    "compare the actual business outcome with the current durable record for the same "
    "matter: an agreed or pending plan does not record completed execution. Revise that "
    "record when its status changes; zero-write processed is valid if it already states "
    "the outcome or no durable update is warranted. Receipt checks do not certify this "
    "semantic comparison."
)

FRONTIER_FINAL_SCHEMA: dict[str, Any] = copy.deepcopy(REPAIR_FINAL_SCHEMA)
_frontier_maintenance = FRONTIER_FINAL_SCHEMA["properties"]["maintenance"]
_frontier_maintenance["properties"]["dispositions"] = {
    "type": "array", "items": {
        "type": "object", "properties": {
            "refs": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "future_use": {"enum": ["task_local", "cross_turn", "durable", "none"]},
            "reason": {"type": "string", "minLength": 1},
            "represented_by": {"type": "string"},
        },
        "required": ["refs", "future_use", "reason"], "additionalProperties": False,
    },
}
_frontier_maintenance["required"].append("dispositions")
FRONTIER_FINAL_SCHEMA["properties"]["completed_action_refs"] = {
    "type": "array", "items": {"type": "string"},
}
FRONTIER_FINAL_SCHEMA["properties"]["pending_actions"] = {
    "type": "array", "items": {
        "type": "object", "properties": {
            "action": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["action", "reason"], "additionalProperties": False,
    },
}
FRONTIER_FINAL_SCHEMA["required"].extend(["completed_action_refs", "pending_actions"])
FRONTIER_FINISH_TOOL: dict[str, Any] = copy.deepcopy(REPAIR_FINISH_TOOL)
FRONTIER_FINISH_TOOL["function"]["parameters"] = FRONTIER_FINAL_SCHEMA
FRONTIER_FINISH_TOOL["function"]["description"] = (
    "Finish with dispositions for unhandled delivered observations, real completed action "
    "refs, proposed pending business actions, and the answer. For future_use, ask whether "
    "this matter would still matter after this reply and session; a format limit for this "
    "reply does not shorten a separate future commitment in the same observation. A saved "
    "source relation is a write fact, not proof that every meaning was handled. Task writes "
    "are unavailable in a new session; explicit task-only or do-not-save limits still apply, "
    "and task_local/none cannot override a trusted persistence requirement. "
    "cross_turn/durable requires a current durable record actually read or "
    "pending maintenance. completed_action_refs cite delivered succeeded internal journal "
    "actions, not external business receipt IDs; use external IDs only from delivered tool "
    "output. A query or message proves only that action, not another business completion. "
    "The answer itself must fulfill current content and format instructions; maintenance "
    "dispositions do not perform the request. Failed writes still need repair_of, reasoned "
    "abandonment, or pending."
)

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
        if session.maintenance.get("protocol") in {
            SEMANTIC_MAINTENANCE_PROTOCOL, REPAIR_MAINTENANCE_PROTOCOL,
            FRONTIER_MAINTENANCE_PROTOCOL,
        }:
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
    if session.maintenance.get("protocol") in {
        SEMANTIC_MAINTENANCE_PROTOCOL, REPAIR_MAINTENANCE_PROTOCOL,
        FRONTIER_MAINTENANCE_PROTOCOL,
    }:
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
        if session.maintenance.get("protocol") in {
            SEMANTIC_MAINTENANCE_PROTOCOL, REPAIR_MAINTENANCE_PROTOCOL,
            FRONTIER_MAINTENANCE_PROTOCOL,
        }:
            writes.append({"ref": ref, "turn_id": session.turn_id,
                           "operation_id": receipt.operation_id})
        else:
            writes.append(ref)


def failed_write(
    session: HostSession, operation_id: str, arguments: dict[str, Any], error: str,
) -> None:
    """Retain only the locator and public cause of one unresolved write attempt."""
    if session.maintenance.get("protocol") not in {
        REPAIR_MAINTENANCE_PROTOCOL, FRONTIER_MAINTENANCE_PROTOCOL,
    }:
        return
    attempts = session.maintenance.setdefault("failed_attempts", {})
    repair_of = arguments.get("repair_of")
    if not isinstance(repair_of, str) or repair_of not in attempts:
        repair_of = None
    alias = arguments.get("target_ref")
    binding = session.visible_bindings.get(alias) if isinstance(alias, str) else None
    target = binding.exact_ref if binding is not None else None
    prior = attempts.get(repair_of, {}) if repair_of is not None else {}
    if (prior.get("target_ref") and target and session.memory is not None
            and session.memory._handle(prior["target_ref"]) != session.memory._handle(target)):
        repair_of = None
        prior = {}
    field = next((part for part in ("source_delta.remove", "source_refs", "target_ref",
                                    "content_patch", "dependencies", "about_ref")
                  if part in error), "write")
    code = error if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", error) else (
        "INVALID_WRITE_PROPOSAL"
    )
    for body_code, body_field in (
        ("PERSISTENT_BODY_CONTAINS_EPHEMERAL_HANDLE", "content"),
        ("LITERAL_USE_NOT_GROUNDED", "literal_uses"),
    ):
        if body_code in error:
            code, field = body_code, body_field
            break
    if code == "ABOUT_SOURCE_NOT_CITED":
        field = "source_delta.remove" if arguments.get("basis_mode") == "delta" else "source_refs"
    attempts[repair_of or operation_id] = {
        "operation_id": repair_of or operation_id,
        "last_operation_id": operation_id,
        "target_ref": prior.get("target_ref") or target,
        "field": field,
        "error": code,
        "turn_id": session.turn_id,
    }


def repaired_write(session: HostSession, repair_of: str | None) -> None:
    if (session.maintenance.get("protocol") in {
            REPAIR_MAINTENANCE_PROTOCOL, FRONTIER_MAINTENANCE_PROTOCOL,
        }
            and repair_of is not None):
        session.maintenance.setdefault("failed_attempts", {}).pop(repair_of, None)


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


def _write_facts(
    session: HostSession, writes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Project actual current writes, without treating a citation as full semantic coverage."""
    memory = session.memory
    assert memory is not None
    facts: list[dict[str, Any]] = []
    durable_supported: set[str] = set()
    aliases = {binding.exact_ref: alias for alias, binding in
               session.visible_bindings.items() if binding.kind in {"source", "interpretation"}}
    for item in writes:
        ref = item["ref"]
        record = memory.read(ref, include_sources=False, _visible=False)
        card = memory.workspace.cards.get(memory._handle(ref))
        if record.get("status") != "CURRENT" or card is None or card.retired:
            continue
        sources = record.get("source_refs", [])
        if record.get("persistence") == "durable":
            durable_supported.update(sources)
        facts.append({
            "record_ref": aliases.get(ref), "operation_id": item["operation_id"],
            "persistence": record.get("persistence"),
            "future_session_available": record.get("persistence") == "durable",
            "source_refs": [aliases[source] for source in sources if source in aliases],
            "source_count": len(sources),
        })
    return facts, durable_supported


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
    frontier = {
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
    protocol = session.maintenance.get("protocol")
    if protocol in {REPAIR_MAINTENANCE_PROTOCOL, FRONTIER_MAINTENANCE_PROTOCOL}:
        frontier["protocol"] = protocol
        frontier["failed_attempts"] = [
            {"operation_id": key, "target_ref": next((alias for alias, binding in
              session.visible_bindings.items() if binding.kind == "interpretation"
              and binding.exact_ref == item.get("target_ref")), "undelivered"),
             "field": item["field"], "error": item["error"]}
            for key, item in session.maintenance.get("failed_attempts", {}).items()
        ]
    if protocol == FRONTIER_MAINTENANCE_PROTOCOL:
        write_facts, durable_sources = _write_facts(session, writes)
        dispositions = session.maintenance.get("dispositions", {})
        frontier["write_facts"] = write_facts
        frontier["unhandled_candidates"] = [
            {"ref": row["ref"], "role": row["role"],
             "unreviewed_ranges": row["unreviewed_ranges"]}
            for exact, row in zip(session.maintenance.get("pending", {}), coverage,
                                  strict=True)
            if row["ref"] != "undelivered" and exact not in durable_sources
            and exact not in dispositions
        ]
        frontier["execution_facts"] = frontier.pop("business_outcomes")
    return frontier


def semantic_finish_tool(
    session: HostSession, *, business_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    protocol = session.maintenance.get("protocol")
    frontier_mode = protocol == FRONTIER_MAINTENANCE_PROTOCOL
    repair = protocol in {REPAIR_MAINTENANCE_PROTOCOL, FRONTIER_MAINTENANCE_PROTOCOL}
    tool = copy.deepcopy(FRONTIER_FINISH_TOOL if frontier_mode else
                         REPAIR_FINISH_TOOL if repair else SEMANTIC_FINISH_TOOL)
    frontier = semantic_frontier(session, business_outcomes=business_outcomes)
    refs = [item["ref"] for item in frontier["review_coverage"]
            if item["ref"] != "undelivered"]
    refs += [alias for alias, binding in session.visible_bindings.items()
             if binding.kind == "interpretation"]
    remaining = tool["function"]["parameters"]["properties"]["maintenance"][
        "properties"]["remaining"]
    if refs:
        remaining["items"]["properties"]["ref"] = {"enum": list(dict.fromkeys(refs))}
    else:
        remaining["maxItems"] = 0
    if repair:
        abandoned = tool["function"]["parameters"]["properties"]["maintenance"][
            "properties"]["abandoned_attempts"]
        ids = list(session.maintenance.get("failed_attempts", {}))
        if ids:
            abandoned["items"]["properties"]["operation_id"] = {"enum": ids}
        else:
            abandoned["maxItems"] = 0
    if frontier_mode:
        dispositions = tool["function"]["parameters"]["properties"]["maintenance"][
            "properties"]["dispositions"]
        candidate_refs = [item["ref"] for item in frontier["unhandled_candidates"]]
        if candidate_refs:
            dispositions["items"]["properties"]["refs"]["items"] = {
                "enum": candidate_refs,
            }
        else:
            dispositions["maxItems"] = 0
        completed = tool["function"]["parameters"]["properties"]["completed_action_refs"]
        successful = [item["call_id"] for item in frontier["execution_facts"]
                      if item["status"] == "succeeded" and item.get("delivered")]
        if successful:
            completed["items"] = {"enum": successful}
        else:
            completed["maxItems"] = 0
    return tool


def semantic_finish(
    session: HostSession, decision: dict[str, Any], *,
    business_outcomes: list[dict[str, Any]] | None = None,
    completed_action_refs: list[str] | None = None,
    pending_actions: list[dict[str, str]] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Accept semantic selection only when actual review, writes and outcomes permit it."""
    protocol = session.maintenance.get("protocol")
    frontier_mode = protocol == FRONTIER_MAINTENANCE_PROTOCOL
    repair = protocol in {REPAIR_MAINTENANCE_PROTOCOL, FRONTIER_MAINTENANCE_PROTOCOL}
    if session.maintenance.get("protocol") not in {
        SEMANTIC_MAINTENANCE_PROTOCOL, REPAIR_MAINTENANCE_PROTOCOL,
        FRONTIER_MAINTENANCE_PROTOCOL,
    }:
        raise ValueError("MAINTENANCE_PROTOCOL_MISMATCH")
    frontier = semantic_frontier(session, business_outcomes=business_outcomes)
    choice = decision["decision"]
    remaining = decision["remaining"]
    abandoned = decision.get("abandoned_attempts", []) if repair else []
    attempts = session.maintenance.get("failed_attempts", {}) if repair else {}
    abandon_ids = [item["operation_id"] for item in abandoned]
    if (len(set(abandon_ids)) != len(abandon_ids)
            or any(key not in attempts or not item["reason"].strip()
                   for key, item in zip(abandon_ids, abandoned, strict=True))):
        raise ValueError("MAINTENANCE_ABANDONED_ATTEMPT_INVALID")
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
    unresolved = sorted(set(attempts) - set(abandon_ids))
    if choice != "pending" and unresolved:
        raise ValueError("MAINTENANCE_FAILED_WRITES_UNRESOLVED: " + ", ".join(unresolved))
    new_dispositions: dict[str, dict[str, Any]] = {}
    if frontier_mode:
        completed = completed_action_refs or []
        pending_business = pending_actions or []
        eligible = {item["call_id"] for item in frontier["execution_facts"]
                    if item["status"] == "succeeded" and item.get("delivered")}
        if len(completed) != len(set(completed)) or not set(completed) <= eligible:
            raise ValueError("COMPLETED_ACTION_REF_NOT_DELIVERED_SUCCEEDED")
        if any(not item.get("action", "").strip() or not item.get("reason", "").strip()
               for item in pending_business):
            raise ValueError("PENDING_ACTION_REASON_REQUIRED")
        candidates = {item["ref"] for item in frontier["unhandled_candidates"]}
        remaining_refs = {item["ref"] for item in remaining}
        pending_by_alias = {row["ref"]: exact for exact, row in zip(
            session.maintenance.get("pending", {}), frontier["review_coverage"], strict=True
        )}
        for item in decision["dispositions"]:
            refs = item["refs"]
            future_use = item["future_use"]
            if (not refs or len(set(refs)) != len(refs) or not item["reason"].strip()
                    or future_use not in {"task_local", "cross_turn", "durable", "none"}):
                raise ValueError("FRONTIER_DISPOSITION_INVALID")
            for alias in refs:
                if alias not in candidates or alias in new_dispositions or alias in remaining_refs:
                    raise ValueError("FRONTIER_DISPOSITION_REF_INVALID")
                exact = pending_by_alias[alias]
                if (future_use in {"task_local", "none"}
                        and session.maintenance["pending"][exact].get("persistence_required")):
                    raise ValueError("FRONTIER_REQUIRED_PERSISTENCE_CONFLICT")
                represented = item.get("represented_by")
                represented_exact = None
                if represented is not None:
                    binding = session.visible_bindings.get(represented)
                    if binding is None or binding.kind != "interpretation":
                        raise ValueError("FRONTIER_REPRESENTED_RECORD_NOT_DELIVERED")
                    assert session.memory is not None
                    record = session.memory.read(binding.exact_ref, include_sources=False,
                                                 _visible=False)
                    spans = session.visible_body_spans(represented)
                    end = 0
                    for lower, upper in sorted(spans):
                        if lower <= end:
                            end = max(end, upper)
                    card = session.memory.workspace.cards.get(
                        session.memory._handle(binding.exact_ref))
                    if (record.get("status") != "CURRENT" or
                            record.get("persistence") != "durable" or card is None
                            or card.retired or end < len(record["text"])):
                        raise ValueError("FRONTIER_REPRESENTED_RECORD_NOT_CURRENT_DURABLE")
                    represented_exact = binding.exact_ref
                if future_use in {"cross_turn", "durable"} and represented_exact is None:
                    raise ValueError("FRONTIER_DURABLE_CHANGE_NOT_COMMITTED")
                if future_use in {"task_local", "none"} and represented_exact is not None:
                    raise ValueError("FRONTIER_DISPOSITION_INVALID")
                new_dispositions[alias] = {
                    "future_use": future_use, "reason": item["reason"],
                    "represented_by": represented_exact,
                }
        left = candidates - set(new_dispositions) - (remaining_refs if choice == "pending"
                                                      else set())
        if left:
            raise ValueError("FRONTIER_CANDIDATES_UNRESOLVED: " + ", ".join(sorted(left)))
        if choice == "pending" and not remaining and not (missing_review or
                    missing_persistence or operations or unresolved):
            raise ValueError("MAINTENANCE_PENDING_WITHOUT_REMAINING")
    if choice == "pending" and not (remaining or missing_review or missing_persistence or
                                    operations or unresolved):
        raise ValueError("MAINTENANCE_PENDING_WITHOUT_REMAINING")
    status = "pending" if choice == "pending" or operations else "complete"
    result = {
        **frontier, "status": status, "semantic_decision": choice,
        "remaining": copy.deepcopy(remaining),
        "missing_required_review": missing_review,
        "missing_required_persistence": missing_persistence,
    }
    if repair:
        result["failed_attempts"] = [item for item in frontier["failed_attempts"]
                                     if item["operation_id"] in unresolved]
        result["abandoned_attempts"] = copy.deepcopy(abandoned)
        result["unresolved_failed_attempts"] = unresolved
    if frontier_mode:
        result["dispositions"] = copy.deepcopy(decision["dispositions"])
        result["completed_action_refs"] = list(completed_action_refs or [])
        result["pending_actions"] = copy.deepcopy(pending_actions or [])
        result["unhandled_candidates"] = [item for item in frontier["unhandled_candidates"]
                                          if item["ref"] not in new_dispositions]
    if commit:
        for key in abandon_ids:
            session.maintenance.setdefault("failed_attempts", {}).pop(key, None)
        if abandoned:
            session.maintenance.setdefault("abandoned_attempts", []).extend(
                copy.deepcopy(abandoned)
            )
        if frontier_mode:
            pending_by_alias = {row["ref"]: exact for exact, row in zip(
                session.maintenance.get("pending", {}), frontier["review_coverage"], strict=True
            )}
            stored = session.maintenance.setdefault("dispositions", {})
            for alias, item in new_dispositions.items():
                stored[pending_by_alias[alias]] = item
        if status == "complete":
            session.maintenance["pending"] = {}
            if frontier_mode:
                session.maintenance["dispositions"] = {}
        session.maintenance["last_review"] = result
    return result
