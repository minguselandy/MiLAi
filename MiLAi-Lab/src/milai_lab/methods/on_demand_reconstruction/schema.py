"""The small response extension used only by the ODR arm."""

from __future__ import annotations

from typing import Any

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]


class ReconstructionError(ValueError):
    """A response cannot be bound to evidence in its own request."""


RECONSTRUCTION_SCHEMA: dict[str, Any] = {
    "oneOf": [
        {"type": "null"},
        {"type": "object", "properties": {
            "proposition": {"type": "string", "minLength": 1, "maxLength": 512},
            "action_scope": {"type": "object", "properties": {
                "subject": {"type": "string", "maxLength": 160},
                "item": {"type": "string", "maxLength": 160},
                "action_type": {"type": "string", "maxLength": 160},
                "critical_parameters": {"type": "array", "items": {
                    "type": "string", "maxLength": 160}, "maxItems": 8},
            }, "required": ["subject", "item", "action_type", "critical_parameters"],
                "additionalProperties": False},
            "evidence_used": {"type": "array", "items": {
                "type": "object", "properties": {
                    "ref": {"type": "string", "minLength": 1},
                    "support_role": {"enum": ["supports_value", "constrains_applicability",
                                              "records_execution", "contextual"]},
                }, "required": ["ref", "support_role"], "additionalProperties": False},
                "maxItems": 12},
            "unresolved_gap": {"type": ["string", "null"], "maxLength": 512},
        }, "required": ["proposition", "action_scope", "evidence_used",
                        "unresolved_gap"], "additionalProperties": False},
    ],
}


def odr_action_schema(base: dict[str, Any]) -> dict[str, Any]:
    branches = []
    for branch in base["oneOf"]:
        branch = dict(branch)
        branch["properties"] = {"reconstruction": RECONSTRUCTION_SCHEMA,
                                **branch["properties"]}
        branch["required"] = ["reconstruction", *branch["required"]]
        branches.append(branch)
    return {"oneOf": branches}


def validate_reconstruction(value: Any) -> None:
    try:
        validate(value, RECONSTRUCTION_SCHEMA)
    except ValidationError as error:
        raise ReconstructionError("ODR_RECONSTRUCTION_SCHEMA_INVALID") from error


ODR_PROTOCOL = (
    "In the same JSON answer or calls, include reconstruction: null unless a current "
    "judgment could change a meaningful action or critical parameter. Otherwise give "
    "a concrete proposition, action_scope (subject, item, action_type, "
    "critical_parameters), evidence_used [{ref,support_role}], and unresolved_gap "
    "(question or null). Use only e0/e1/... evidence actually available in this request. "
    "A superseded memory may be contextual but cannot support a current value. "
    "A revision notice does not include the new body. Ordinary tools remain available. "
    "No separate reconstruction call is needed."
)
