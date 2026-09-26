"""Small, explicit Host delta contract. Semantic quality remains the Host's task."""

from __future__ import annotations

from typing import Any


class DecisionDeltaError(ValueError):
    """A decision delta cannot be committed or used to authorize tool dispatch."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_delta(value: Any) -> dict[str, Any] | None:
    """Normalize only the declared structure, without guessing semantic content."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DecisionDeltaError("DECISION_DELTA_INVALID")
    if value == {"op": "clear"}:
        return value
    if value.get("op") != "set" or set(value) != {
        "op", "decision", "scope", "adopted_evidence", "critical_gap", "status",
    }:
        raise DecisionDeltaError("DECISION_DELTA_INVALID")
    decision = value["decision"]
    scope = value["scope"]
    refs = value["adopted_evidence"]
    gap = value["critical_gap"]
    if not isinstance(decision, str) or not decision.strip():
        raise DecisionDeltaError("DECISION_DECISION_EMPTY")
    if (not isinstance(scope, dict) or set(scope) != {"subject", "item", "context"}
            or any(not isinstance(part, str) for part in scope.values())):
        raise DecisionDeltaError("DECISION_SCOPE_INVALID")
    if (not isinstance(refs, list) or len(refs) > 8
            or any(not isinstance(ref, str) for ref in refs)
            or len(set(refs)) != len(refs)):
        raise DecisionDeltaError("DECISION_EVIDENCE_INVALID")
    if gap is not None and not isinstance(gap, str):
        raise DecisionDeltaError("DECISION_GAP_INVALID")
    if value["status"] not in {"active", "deferred"}:
        raise DecisionDeltaError("DECISION_STATUS_INVALID")
    return {
        "op": "set", "decision": decision.strip(),
        "scope": {key: scope[key].strip() for key in ("subject", "item", "context")},
        "adopted_evidence": refs,
        "critical_gap": gap.strip() if isinstance(gap, str) else None,
        "status": value["status"],
    }
