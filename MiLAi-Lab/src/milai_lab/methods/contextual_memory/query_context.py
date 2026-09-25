"""Task-scoped condition evidence and deterministic, non-semantic scope matching."""

from __future__ import annotations

from datetime import date
from typing import Any

from milai_lab.methods.contextual_memory.write_contract import (
    CONDITION_DEFINITIONS,
    validate_conditions,
    validate_date,
)


def _iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def task_context(
    task_id: str, question: str, conditions: dict[str, str] | None = None,
    valid_at: str = "",
) -> dict[str, Any]:
    evidence = []
    validate_conditions(conditions)
    for key, value in (conditions or {}).items():
        evidence.append({
            "key": key, "value": value, "basis": "task_input",
            "basis_ref": f"task:{task_id}", "inferred": False,
        })
    validate_date(valid_at, "task_valid_at")
    return {
        "task_id": task_id, "question": question,
        "task_valid_at": valid_at, "condition_evidence": evidence,
    }


def project_query(
    query: str, *, task_context: dict[str, Any], state: Any,
    explicit_filters: dict[str, str], focus: str = "default", gap: str = "",
    anchor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Use the actual search request and declared filters, not State prose as a query."""
    if focus == "critical_gap":
        if query or not gap.strip():
            raise ValueError("CRITICAL_GAP_REQUIRES_EMPTY_QUERY_AND_ACTIVE_GAP")
        scope = anchor or {}
        effective_query = " ".join(part for part in (
            gap.strip(), scope.get("item", "").strip(),
        ) if part)
        origin = "critical_gap"
    elif focus == "default":
        effective_query = query or str(task_context.get("question", ""))
        origin = "tool_argument" if query else "task_input"
    else:
        raise ValueError("UNKNOWN_SEARCH_FOCUS")
    sources: dict[str, Any] = {"query": origin, "focus_origin": focus}
    filters: dict[str, str] = {}
    for key in ("valid_at", "known_at", "date_from", "date_to", "session_id"):
        value = explicit_filters.get(key, "")
        if value:
            sources[key] = "tool_argument"
        elif key == "valid_at" and task_context.get("task_valid_at"):
            value = str(task_context["task_valid_at"])
            sources[key] = "task_input"
        filters[key] = value
    declared = {item["key"] for item in task_context.get("condition_evidence", [])}
    sources["conditions"] = {
        "task_or_visible_evidence": sorted(declared),
        "state_unverified": sorted(set(state.conditions) - declared),
    }
    if state.valid_at and not filters["valid_at"]:
        sources["state_valid_at"] = "unverified_not_applied"
    if state.known_at and not filters["known_at"]:
        sources["state_known_at"] = "unverified_not_applied"
    return {"effective_query": effective_query, "filters": filters, "sources": sources}


def accept_evidence(
    context: dict[str, Any], proposed: list[dict[str, str]], *,
    known_keys: set[str], source_text: dict[str, list[str]], seen: set[str],
) -> dict[str, Any]:
    """Check provenance and exact visibility; never certify the asserted meaning."""
    added: list[dict[str, Any]] = []
    for item in proposed:
        key, value, basis = item["key"], item["value"], item["basis"]
        if not key or not value or key not in known_keys or key not in CONDITION_DEFINITIONS:
            raise ValueError("UNKNOWN_OR_EMPTY_CONDITION_KEY")
        quote = item.get("quote", "")
        basis_ref = item.get("basis_ref", "")
        reason = item.get("reason", "")
        if basis == "visible_question":
            if not quote or quote not in context["question"] or basis_ref:
                raise ValueError("CONDITION_QUESTION_QUOTE_NOT_VISIBLE")
        elif basis == "visible_source":
            if (basis_ref not in seen or basis_ref not in source_text
                    or not quote or not any(quote in page for page in source_text[basis_ref])):
                raise ValueError("CONDITION_SOURCE_QUOTE_NOT_VISIBLE")
        elif basis == "inference":
            if not reason:
                raise ValueError("CONDITION_INFERENCE_REQUIRES_REASON")
            if basis_ref and basis_ref not in seen:
                raise ValueError("CONDITION_INFERENCE_SOURCE_NOT_VISIBLE")
        else:
            raise ValueError("UNKNOWN_CONDITION_BASIS")
        added.append({
            "key": key, "value": value, "basis": basis, "basis_ref": basis_ref,
            "quote": quote, "reason": reason, "inferred": basis == "inference",
        })
    result = {**context, "condition_evidence": list(context["condition_evidence"])}
    for item in added:
        if item not in result["condition_evidence"]:
            result["condition_evidence"].append(item)
    return result


def scope_result(
    required: dict[str, str], valid_from: str, valid_until: str,
    context: dict[str, Any], active_conditions: dict[str, str], valid_at: str,
) -> dict[str, Any]:
    """Match exact declared values; absence and conflict remain pending."""
    observations: dict[str, list[dict[str, Any]]] = {}
    for item in context.get("condition_evidence", []):
        observations.setdefault(item["key"], []).append(item)
    # State prose and unanchored condition values are working hypotheses.
    # The existing condition_evidence path carries their visible basis when available.
    reasons: list[dict[str, Any]] = []
    mismatch = False
    pending = False
    for key, wanted in required.items():
        if key not in CONDITION_DEFINITIONS:
            pending = True
            reasons.append({
                "kind": "condition", "key": key, "expected": wanted,
                "observed_values": [], "verdict": "UNKNOWN_DEFINITION", "evidence": [],
            })
            continue
        evidence = observations.get(key, [])
        values = sorted({item["value"] for item in evidence})
        if not values:
            verdict = "UNKNOWN"
            pending = True
        elif len(values) > 1:
            verdict = "CONFLICT"
            pending = True
        elif values[0] != wanted:
            verdict = "MISMATCH"
            mismatch = True
        else:
            verdict = "MATCH"
        reasons.append({
            "kind": "condition", "key": key, "expected": wanted,
            "observed_values": values, "verdict": verdict, "evidence": evidence,
        })
    if valid_from or valid_until:
        actual = _iso_date(valid_at)
        lower = _iso_date(valid_from)
        upper = _iso_date(valid_until)
        unresolved = [
            field for field, raw, parsed in (
                ("valid_at", valid_at, actual),
                ("valid_from", valid_from, lower),
                ("valid_until", valid_until, upper),
            ) if (field == "valid_at" or raw) and parsed is None
        ]
        if actual is None:
            verdict = "UNKNOWN"
            pending = True
        elif ((lower is not None and actual < lower)
              or (upper is not None and actual >= upper)):
            verdict = "MISMATCH"
            mismatch = True
        elif unresolved:
            verdict = "UNKNOWN"
            pending = True
        else:
            verdict = "MATCH"
        reason: dict[str, Any] = {
            "kind": "valid_at", "expected_from": valid_from,
            "expected_until": valid_until, "actual": valid_at, "verdict": verdict,
        }
        if unresolved:
            reason["unresolved_boundaries"] = unresolved
        reasons.append(reason)
    return {
        "status": "UNUSABLE" if mismatch else "PENDING" if pending else "USABLE",
        "reasons": reasons,
        "structured_scope": "DECLARED" if required or valid_from or valid_until else "UNDECLARED",
    }
