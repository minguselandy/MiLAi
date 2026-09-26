"""Small v18 proposition delta contract; semantic truth remains the Host's task."""

from __future__ import annotations

from typing import Any


class DecisionDeltaError(ValueError):
    """A decision delta cannot be committed or used to authorize tool dispatch."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


SUPPORT_ROLES = frozenset({
    "supports_value", "constrains_applicability", "records_execution", "contextual",
})
COMPLETED_OUTCOMES = frozenset({"retained", "changed"})


def generation_delta_schema() -> dict[str, Any]:
    """Exact structural branches shared by the decoder and runtime contract."""
    scope = {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "item": {"type": "string"},
            "action_type": {"type": "string"},
            "critical_parameters": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject", "item", "action_type", "critical_parameters"],
        "additionalProperties": False,
    }
    adoption = {
        "type": "array", "maxItems": 8,
        "items": {"type": "object", "properties": {
            "ref": {"type": "string"},
            "support_role": {"enum": sorted(SUPPORT_ROLES)},
        }, "required": ["ref", "support_role"], "additionalProperties": False},
    }
    completion = {
        "proposition": {"type": "string"},
        "action_scope": scope,
        "adopted_evidence": adoption,
        "unresolved_gap": {"type": ["string", "null"]},
        "recheck_outcome": {"enum": sorted(COMPLETED_OUTCOMES)},
    }
    return {"oneOf": [
        {"type": "null"},
        {"type": "object", "properties": {
            "op": {"const": "set"}, **completion,
            "recheck_outcome": {"enum": ["retained", "changed", "unresolved", None]},
            "status": {"enum": ["active", "deferred"]},
        }, "required": ["op", "proposition", "action_scope", "adopted_evidence",
                        "unresolved_gap", "recheck_outcome", "status"],
            "additionalProperties": False},
        {"type": "object", "properties": {"op": {"const": "clear"}},
         "required": ["op"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "clear"}, "clear_reason": {"const": "task_ended"},
        }, "required": ["op", "clear_reason"], "additionalProperties": False},
        {"type": "object", "properties": {
            "op": {"const": "clear"},
            "clear_reason": {"const": "recheck_completed"},
            **completion,
        }, "required": ["op", "clear_reason", "proposition", "action_scope",
                        "adopted_evidence", "unresolved_gap", "recheck_outcome"],
            "additionalProperties": False},
    ]}


def _nonempty(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionDeltaError(code)
    return value.strip()


def _content(value: dict[str, Any]) -> dict[str, Any]:
    proposition = _nonempty(value["proposition"], "DECISION_PROPOSITION_EMPTY")
    action_scope = value["action_scope"]
    if not isinstance(action_scope, dict) or set(action_scope) != {
        "subject", "item", "action_type", "critical_parameters",
    }:
        raise DecisionDeltaError("DECISION_ACTION_SCOPE_INVALID")
    parameters = action_scope["critical_parameters"]
    if (not isinstance(parameters, list)
            or any(not isinstance(part, str) or not part.strip() for part in parameters)):
        raise DecisionDeltaError("DECISION_CRITICAL_PARAMETERS_INVALID")
    clean_parameters = [part.strip() for part in parameters]
    if len(set(clean_parameters)) != len(clean_parameters):
        raise DecisionDeltaError("DECISION_CRITICAL_PARAMETERS_INVALID")
    scope: dict[str, Any] = {
        field: _nonempty(action_scope[field], "DECISION_ACTION_SCOPE_INVALID")
        for field in ("subject", "item", "action_type")
    }
    scope["critical_parameters"] = clean_parameters
    refs = value["adopted_evidence"]
    if not isinstance(refs, list) or len(refs) > 8:
        raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
    adopted = []
    for item in refs:
        if (not isinstance(item, dict) or set(item) != {"ref", "support_role"}
                or not isinstance(item["ref"], str) or not item["ref"].strip()
                or not isinstance(item["support_role"], str)
                or item["support_role"] not in SUPPORT_ROLES):
            raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
        adopted.append({"ref": item["ref"], "support_role": item["support_role"]})
    if len({item["ref"] for item in adopted}) != len(adopted):
        raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
    gap = value["unresolved_gap"]
    if gap is not None and not isinstance(gap, str):
        raise DecisionDeltaError("DECISION_GAP_INVALID")
    return {
        "proposition": proposition, "action_scope": scope,
        "adopted_evidence": adopted,
        "unresolved_gap": gap.strip() if isinstance(gap, str) else None,
    }


def validate_delta(value: Any) -> dict[str, Any] | None:
    """Validate structural meaning without judging the proposition's truth."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DecisionDeltaError("DECISION_DELTA_INVALID")
    if value == {"op": "clear"}:
        return value
    if value == {"op": "clear", "clear_reason": "task_ended"}:
        return value
    if value.get("op") == "clear" and set(value) == {
        "op", "clear_reason", "proposition", "action_scope", "adopted_evidence",
        "unresolved_gap", "recheck_outcome",
    } and value["clear_reason"] == "recheck_completed":
        if value["recheck_outcome"] not in COMPLETED_OUTCOMES:
            raise DecisionDeltaError("DECISION_RECHECK_OUTCOME_INVALID")
        return {"op": "clear", "clear_reason": "recheck_completed",
                **_content(value), "recheck_outcome": value["recheck_outcome"]}
    if value.get("op") != "set" or set(value) != {
        "op", "proposition", "action_scope", "adopted_evidence",
        "unresolved_gap", "status", "recheck_outcome",
    }:
        raise DecisionDeltaError("DECISION_DELTA_INVALID")
    if value["status"] not in ("active", "deferred"):
        raise DecisionDeltaError("DECISION_STATUS_INVALID")
    if value["recheck_outcome"] not in (None, "retained", "changed", "unresolved"):
        raise DecisionDeltaError("DECISION_RECHECK_OUTCOME_INVALID")
    return {"op": "set", **_content(value), "status": value["status"],
            "recheck_outcome": value["recheck_outcome"]}
