"""Opt-in presentation of public schemas and already captured structural errors.

No validation, argument transformation, source selection or retry happens here.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal

Profile = Literal["legacy", "shape_feedback_v1"]
TRIGGER_BODY_GUIDANCE = (
    "trigger_binding metadata proves the actual public turn identity and maintenance "
    "authorization; it does not itself support an assertion. The corresponding actual "
    "Human Source body may still be explicitly selected when it expresses the needed fact. "
    "A question alone does not establish a mentioned prior value. Select actual current or "
    "historical supporting leaves freely; no default source is selected. Prose entailment "
    "remains unchecked; metadata/prefix is not a full read."
)
_MARKER = "[shape_feedback_v1]"
FEEDBACK_UTF8_LIMIT = 4096
_FIELDS = ("content", "scope", "basis", "kind")
_EXPECTED = {
    "type",
    "enum",
    "const",
    "required",
    "additionalProperties",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minProperties",
    "maxProperties",
    "uniqueItems",
}


def profile(value: Any = "legacy") -> Profile:
    if type(value) is not str or value not in {"legacy", "shape_feedback_v1"}:
        raise ValueError("TOOL_SCHEMA_COMMUNICATION_PROFILE_INVALID")
    return value  # type: ignore[return-value]


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def present_catalog(tools: list[dict[str, Any]], setting: Any = "legacy") -> list[dict[str, Any]]:
    """Descriptions are a copy; parameter constraints and original tools stay untouched."""
    if profile(setting) == "legacy":
        return tools
    result = copy.deepcopy(tools)
    for item in result:
        function = item["function"]
        parameters = function.get("parameters", {})
        properties = parameters.get("properties", {})
        if _MARKER in function.get("description", ""):
            continue
        guidance = (
            _MARKER + " arguments contains actual parameter values matching this "
            "tool's public schema. Evidence/authorization metadata is not a substitute "
            "for a parameter value. No correction, source selection or retry is automatic."
        )
        if "field_support" in properties:
            guidance += (
                " field_support is a separate four-field support map, not the values "
                "of content/scope/basis/kind. Each entry is exactly source_refs or "
                "reuse_support_from. Mutations under the direct support contract "
                "require all four entries; the optional schema carrier is not a "
                "source fallback. " + TRIGGER_BODY_GUIDANCE
            )
            function["description"] = function.get("description", "").replace(
                "the actual public turn is a trusted trigger, not evidence.",
                "trigger_binding metadata proves turn identity/authorization; the actual "
                "Human Source body remains selectable support.",
            )
            for key in (*_FIELDS, "semantic_patch", "field_support", "source_refs"):
                if key not in properties:
                    continue
                extra = {
                    "field_support": (
                        "Separate support map for all four fields; never replaces "
                        "their actual values."
                    ),
                    "semantic_patch": (
                        "Actual changed field values; field_support and "
                        "source_refs are siblings, not patch fields."
                    ),
                    "source_refs": (
                        "Explicit real leaf IDs including every used leaf; "
                        "no automatic union or fallback."
                    ),
                }.get(key, "Actual whole field value, not a source_refs/reuse_support_from object.")
                properties[key]["description"] = (
                    properties[key].get("description", "") + " " + extra
                ).strip()
            patch = properties.get("semantic_patch", {}).get("properties", {})
            for field in _FIELDS:
                if field in patch:
                    patch[field]["description"] = (
                        "Actual field value. Changed fields need explicitly selected support; "
                        "support objects belong in sibling field_support."
                    )
        function["description"] = (function.get("description", "") + "\n" + guidance).strip()
    return result


def shape_guidance(tools: list[dict[str, Any]], setting: Any = "legacy") -> str:
    if profile(setting) == "legacy":
        return ""
    examples = []
    for item in tools:
        function = item["function"]
        properties = function.get("parameters", {}).get("properties", {})
        if "field_support" not in properties:
            continue
        values: dict[str, Any] = {}
        value_schema = properties.get("semantic_patch", {}).get("properties", properties)
        for field in _FIELDS:
            if field not in value_schema:
                continue
            schema = value_schema[field]
            values[field] = (
                schema["enum"][0]
                if schema.get("enum")
                else {}
                if field == "scope"
                else "<UNUSABLE_VALUE_PLACEHOLDER>"
            )
        arguments: dict[str, Any] = (
            {"semantic_patch": values} if "semantic_patch" in properties else values
        )
        arguments["field_support"] = {
            field: {"source_refs": ["<UNUSABLE_REAL_LEAF_ID>"]} for field in _FIELDS
        }
        if "source_refs" in properties:
            arguments["source_refs"] = ["<UNUSABLE_REAL_LEAF_ID>"]
        if "candidate_handle" in properties:
            arguments["candidate_handle"] = "<UNUSABLE_ACTUALLY_READ_HANDLE>"
        examples.append({"name": function["name"], "arguments": arguments})
    guidance = (
        "\n" + _MARKER + " Public argument-shape guide: use the actual parameters and "
        "their types/enums, independently of support metadata. All examples contain "
        "UNUSABLE placeholders: never execute/copy them as business values, Sources or "
        "candidate IDs. An example enum is a public allowed value, not a recommendation. "
        "Only parameters declared by the actual tool are illustrated."
    )
    if examples:
        guidance += (
            " Complete value/support shapes: "
            + _json({"calls": examples})
            + " A field support entry may instead be "
            '{"reuse_support_from":"<UNUSABLE_SAME_ACTUALLY_READ_HANDLE>"}'
            " only for an exactly unchanged whole field of that same candidate, "
            "with all original leaves explicitly in outer source_refs. Changed fields "
            "need model-selected real supporting leaves. Missing legacy field maps "
            "permit only explicit legacy_whole_version_set; never inferred subclaims."
        )
    return guidance


def presentation_metadata(tools: list[dict[str, Any]], setting: Any) -> dict[str, Any]:
    selected = profile(setting)
    return {
        "profile": selected,
        "feedback_presentation_policy": {
            "aggregate_utf8_limit": FEEDBACK_UTF8_LIMIT,
            "error_nodes": 8,
            "path_segments": 16,
            "segment_or_expected_utf8_limit": 512,
            "context_depth": 3,
            "omissions": "original identities and immediate parent counts; no inferred correction",
        },
        "original_parameter_schema_sha256": {
            item["function"]["name"]: _sha(item["function"].get("parameters", {})) for item in tools
        },
        "presented_catalog_sha256": _sha(present_catalog(tools, selected)),
        "shape_guidance_sha256": _sha(shape_guidance(tools, selected)),
    }


def freeze_fields(tools: list[dict[str, Any]], setting: Any) -> dict[str, Any]:
    if profile(setting) == "legacy":
        return {}
    return {
        "tool_schema_communication": setting,
        "tool_schema_communication_metadata": presentation_metadata(tools, setting),
        "tool_schema_communication_catalog": present_catalog(tools, setting),
        "tool_schema_communication_guidance": shape_guidance(tools, setting),
    }


def check_frozen(frozen: dict[str, Any]) -> Profile:
    selected = profile(frozen["config"].get("tool_schema_communication", "legacy"))
    if profile(frozen.get("tool_schema_communication", "legacy")) != selected:
        raise ValueError("TOOL_SCHEMA_COMMUNICATION_FREEZE_CHANGED")
    if selected != "legacy" and frozen.get("tool_schema_communication_metadata") != (
        presentation_metadata(frozen["tool_catalog"], selected)
    ):
        raise ValueError("TOOL_SCHEMA_COMMUNICATION_FREEZE_CHANGED")
    if selected != "legacy" and (
        frozen.get("tool_schema_communication_catalog")
        != present_catalog(frozen["tool_catalog"], selected)
        or frozen.get("tool_schema_communication_guidance")
        != shape_guidance(frozen["tool_catalog"], selected)
    ):
        raise ValueError("TOOL_SCHEMA_COMMUNICATION_FREEZE_CHANGED")
    return selected


def _bounded(value: Any) -> Any:
    raw = _json(value).encode()
    if len(raw) > 512:
        return {"omitted": True, "utf8_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return value


def _path(path: Any) -> dict[str, Any]:
    values = list(path)
    segments = []
    for value in values[:16]:
        segments.append(_bounded(value))
    return {
        "segments": segments,
        "omitted_segments": max(0, len(values) - 16),
        "sha256": _sha(values),
    }


def _same_json(left: Any, right: Any) -> bool:
    return _json(left) == _json(right)


def _contains(public: Any, subschema: Any) -> bool:
    if _same_json(public, subschema):
        return True
    if isinstance(public, dict):
        return any(_contains(value, subschema) for value in public.values())
    if isinstance(public, list):
        return any(_contains(value, subschema) for value in public)
    return False


def _fit_feedback(value: dict[str, Any]) -> dict[str, Any]:
    """One aggregate byte cap; omissions are presentation, never validation changes.

    Remove trailing displayed path segments by encoded cost, original-order ties;
    then expected displays, then last displayed error children. Original identity
    hashes and immediate parent/child omission counts remain intact.
    """
    value["feedback_utf8_limit"] = FEEDBACK_UTF8_LIMIT

    def objects(current: Any) -> list[dict[str, Any]]:
        if isinstance(current, dict):
            return [current, *[item for child in current.values() for item in objects(child)]]
        if isinstance(current, list):
            return [item for child in current for item in objects(child)]
        return []

    while len(_json(value).encode()) > FEEDBACK_UTF8_LIMIT:
        nodes = objects(value)
        paths = [node for node in nodes if node.get("segments")]
        if paths:
            path = max(paths, key=lambda node: len(_json(node["segments"][-1]).encode()))
            path["segments"].pop()
            path["omitted_segments"] += 1
            continue
        expectations = [node for node in nodes if "expected" in node]
        if expectations:
            node = max(expectations, key=lambda row: len(_json(row["expected"]).encode()))
            node["expected_display_sha256"] = _sha(node.pop("expected"))
            node["expected_omitted"] = "aggregate_feedback_utf8_budget"
            continue
        parents = [node for node in nodes if node.get("context")]
        if parents:
            parent = parents[-1]
            parent["context"].pop()
            parent["omitted_context_children"] += 1
            continue
        if value.get("errors"):
            value["errors"].pop()
            value["omitted_errors"] += 1
            continue
        raise AssertionError("FEEDBACK_FIXED_METADATA_EXCEEDS_BYTE_LIMIT")
    return value


def jsonschema_feedback(error: Any, public_schema: dict[str, Any]) -> dict[str, Any]:
    """Project original errors only; never run a validator or infer a correct branch."""
    available = [8]

    def project(current: Any, depth: int) -> dict[str, Any]:
        available[0] -= 1
        keyword = current.validator
        result = {
            "path": _path(current.absolute_path),
            "schema_path": _path(current.absolute_schema_path),
            "keyword": _bounded(keyword),
        }
        if (
            keyword in _EXPECTED
            and isinstance(current.schema, dict)
            and _same_json(current.schema.get(keyword), current.validator_value)
            and _contains(public_schema, current.schema)
        ):
            result["expected"] = _bounded(current.validator_value)
        else:
            result["expected_omitted"] = "not_a_bounded_public_schema_constraint"
        children = list(current.context)
        shown = []
        for child in children:
            if available[0] <= 0 or depth >= 3:
                break
            shown.append(project(child, depth + 1))
        if children:
            result["context"] = shown
            result["omitted_context_children"] = len(children) - len(shown)
            result["context_identity_sha256"] = _sha(
                [
                    [list(child.absolute_path), list(child.absolute_schema_path), child.validator]
                    for child in children
                ]
            )
        return result

    return _fit_feedback(
        {
            "origin": "jsonschema",
            "status": "error",
            "tool_executed": False,
            "instance_root": "tool_arguments",
            "public_schema_sha256": _sha(public_schema),
            "error": project(error, 0),
        }
    )


def pydantic_feedback(error: Any) -> dict[str, Any]:
    rows = error.errors(include_url=False, include_context=False, include_input=False)
    errors = [{"loc": _path(row["loc"]), "type": _bounded(row["type"])} for row in rows[:8]]
    return _fit_feedback(
        {
            "origin": "pydantic",
            "status": "error",
            "errors": errors,
            "omitted_errors": max(0, len(rows) - 8),
            "error_identity_sha256": _sha([[list(row["loc"]), row["type"]] for row in rows]),
        }
    )


def feedback_text(value: dict[str, Any]) -> str:
    return _json(value)
