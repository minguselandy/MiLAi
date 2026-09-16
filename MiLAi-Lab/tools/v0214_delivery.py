"""Generic Host decisions and delivery checks; no inference of business truth."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import StrEnum

from jsonschema import Draft202012Validator

from prepare_v0213_cases import normalize_schema
from v0213_host_policy import delivery_schema


class Readiness(StrEnum):
    READY = "READY"
    NEEDS_SOURCE = "NEEDS_SOURCE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class DeliveryCheck:
    structurally_valid: bool
    readiness: Readiness
    errors: tuple[str, ...]
    first_intent: dict | None
    complete_plan: list[dict]
    semantic_correct: bool | None = None
    external_executed: bool = False


def readiness_schema(business_tools: list[dict], original: dict) -> dict:
    """Public assessment precedes the constrained action; it is not a hidden reasoning trace."""
    branches = []
    for branch in delivery_schema(business_tools, original)["anyOf"]:
        action = branch["properties"]["action"]["const"]
        readiness = {"tools": "NEEDS_SOURCE", "business": "READY",
                     "abstain": "NEEDS_CLARIFICATION"}[action]
        states = [readiness, "BLOCKED"] if action == "abstain" else [readiness]
        for status in states:
            branches.append({"type": "object", "properties": {
                "assessment": {"type": "object", "properties": {
                    "basis": {"type": "string", "maxLength": 500},
                    "readiness": {"const": status},
                    "requested_business_operations": {"type": "integer", "minimum": 0,
                                                       "maximum": 6}},
                    "required": ["basis", "readiness", "requested_business_operations"],
                    "additionalProperties": False},
                "delivery": deepcopy(branch)}, "required": ["assessment", "delivery"],
                "additionalProperties": False})
    return {"anyOf": branches}


def check_host_delivery(envelope: dict, business_tools: list[dict], *,
                        current_inputs: dict | None = None) -> DeliveryCheck:
    """Check the model's public assessment/action contract; never choose missing values."""
    assessment, action = envelope["assessment"], envelope["delivery"]
    check = check_delivery(action, business_tools, current_inputs=current_inputs)
    status = assessment["readiness"]
    expected = {"tools": "NEEDS_SOURCE", "business": "READY",
                "abstain": "NEEDS_CLARIFICATION"}.get(action.get("action"))
    errors = list(check.errors)
    if type(assessment["requested_business_operations"]) is not int:
        errors.append("REQUESTED_OPERATION_COUNT_TYPE")
    if status != expected and not (status == "BLOCKED" and action["action"] == "abstain"):
        errors.append("ASSESSMENT_ACTION_CONFLICT")
    if action["action"] == "business" and len(action["calls"]) != assessment[
            "requested_business_operations"]:
        errors.append("REQUESTED_OPERATION_COUNT_CONFLICT")
    return replace(check, structurally_valid=check.structurally_valid and not errors,
                   readiness=Readiness.BLOCKED if status == "BLOCKED" else check.readiness,
                   errors=tuple(errors))


def check_delivery(candidate: dict, business_tools: list[dict], *,
                   current_inputs: dict | None = None) -> DeliveryCheck:
    """Current explicit field bindings override stale arguments, without filling missing values."""
    action = candidate.get("action")
    calls = candidate.get("calls", [])
    if action in ("clarify", "abstain"):
        answer = candidate.get("answer")
        valid = calls == [] and isinstance(answer, str) and bool(answer.strip())
        return DeliveryCheck(valid, Readiness.NEEDS_CLARIFICATION,
                             () if valid else ("CLARIFICATION_REQUIRES_QUESTION_AND_NO_CALLS",),
                             None, [])
    if action == "tools":
        return DeliveryCheck(False, Readiness.NEEDS_SOURCE, (), None, [])
    errors, plan = [], []
    catalog = {item["name"]: item for item in business_tools}
    if action != "business" or not isinstance(calls, list) or not calls:
        return DeliveryCheck(False, Readiness.NEEDS_CLARIFICATION,
                             ("NONEMPTY_BUSINESS_PLAN_REQUIRED",), None, [])
    for call in calls:
        if (not isinstance(call, dict) or not isinstance(call.get("arguments"), dict)
                or not isinstance(call.get("name"), str)):
            errors.append("MALFORMED_CALL")
            continue
        tool = catalog.get(call.get("name"))
        if tool is None:
            errors.append("UNKNOWN_BUSINESS_TOOL")
            continue
        arguments = call.get("arguments", {})
        schema = normalize_schema(tool["parameters"])
        schema["additionalProperties"] = False
        errors.extend(error.message for error in Draft202012Validator(schema).iter_errors(
            arguments))
        # Explicit Host field bindings are not defaults and are never synthesized from history.
        for field, value in (current_inputs or {}).items():
            if field in schema.get("properties", {}) and (
                    field not in arguments or json.dumps(arguments[field], sort_keys=True)
                    != json.dumps(value, sort_keys=True)):
                errors.append(f"CURRENT_USER_INPUT_CONFLICT:{field}")
        plan.append(call)
    return DeliveryCheck(not errors, Readiness.READY if not errors
                         else Readiness.NEEDS_CLARIFICATION, tuple(errors),
                         plan[0] if plan else None, plan)
