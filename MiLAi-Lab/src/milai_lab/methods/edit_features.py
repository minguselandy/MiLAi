"""Opt-in contracts over the existing four edit arms, without model execution."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from milai_lab.memory.edit_units import writer_proposal_schema
from milai_lab.memory.functional_state import FunctionalRejection


@dataclass(frozen=True)
class EditFeatures:
    matter_organization: bool = False
    semantic_operations: bool = False
    bound_references: bool = False
    single_record_changes: bool = False
    source_metadata: bool = False

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> EditFeatures:
        known = asdict(cls())
        if set(settings) - set(known) or any(type(v) is not bool for v in settings.values()):
            raise ValueError("EDIT_FEATURE_SETTINGS_INVALID")
        return cls(**settings)

    @property
    def enabled(self) -> bool:
        return any(asdict(self).values())

    def settings(self) -> dict[str, bool]:
        return asdict(self)


def _object(fields: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": required,
    }


def feature_proposal_schema(
    arm: str,
    features: EditFeatures,
    mapping: dict[str, Any],
    *,
    allow_create: bool,
    target: str | None = None,
) -> dict[str, Any]:
    schema = copy.deepcopy(writer_proposal_schema(arm, allow_create=allow_create))
    refs = {
        "r": list(mapping.get("records", {})),
        "u": [
            key
            for key, unit in mapping.get("units", {}).items()
            if target is None or unit["record"] == target
        ],
        "e": list(mapping.get("evidence", {})),
        "h": [
            key
            for key, support in mapping.get("support", {}).items()
            if target is None or support["record"] == target
        ],
    }

    def reference(prefix: str, values: list[str] | None = None) -> dict[str, Any]:
        candidates = refs[prefix] if values is None else values
        return {"type": "string", "enum": candidates} if candidates else {"type": "string"}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            items = value.get("items", {})
            if isinstance(items, dict) and value.get("type") == "array":
                for prefix in refs:
                    if items.get("pattern") == "^" + prefix + "[1-9][0-9]*$" and not refs[prefix]:
                        value["maxItems"] = 0
            pattern = value.get("pattern", "")
            for prefix in refs:
                if pattern == "^" + prefix + "[1-9][0-9]*$" and features.bound_references:
                    value.clear()
                    value.update(reference(prefix))
                    break
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    variants = schema["oneOf"]
    variants[:] = [
        v
        for v in variants
        if (v["properties"]["action"]["const"] == "create" and bool(refs["e"]))
        or (v["properties"]["action"]["const"] != "create" and bool(refs["r"]))
    ]
    for variant in variants:
        action = variant["properties"]["action"]["const"]
        if action == "create" and features.matter_organization:
            variant["properties"]["matter"] = {"type": "string", "minLength": 1}
            variant["required"].append("matter")
        if action == "rewrite" and features.enabled:
            variant["properties"]["units"]["minItems"] = 1
            variant["properties"].pop("withdrawal_evidence")
    if not refs["e"] and not refs["h"]:
        variants[:] = [
            v for v in variants if v["properties"]["action"]["const"] not in {"create", "rewrite"}
        ]
    if arm in {"B0", "B2"} and features.enabled and refs["r"] and refs["e"]:
        variants.insert(
            -1,
            _object(
                {
                    "action": {"const": "retract_record"},
                    "target": reference("r"),
                    "evidence": {"type": "array", "minItems": 1, "items": reference("e")},
                },
                ["action", "target", "evidence"],
            ),
        )
    if arm == "M" and features.semantic_operations and refs["r"]:
        by_unit = mapping.get("units", {})
        content = [alias for alias in refs["u"] if by_unit[alias]["role"] == "content"]
        conditions = [alias for alias in refs["u"] if by_unit[alias]["role"] == "condition"]
        exceptions = [
            alias
            for alias in content
            if by_unit[alias].get("local_exception")
            or any(
                relation["relation_type"] == "overrides"
                and relation["source_unit"] == by_unit[alias]["unit_id"]
                for relation in mapping["records"][by_unit[alias]["record"]]["edit_state"][
                    "relations"
                ]
            )
        ]
        general = [alias for alias in content if alias not in exceptions]
        ops = []
        for operation, candidates in (
            ("change_value", content),
            ("add_exception", general),
            ("remove_exception", exceptions),
            ("change_condition", conditions),
        ):
            if not candidates or (
                not refs["e"] and operation in {"add_exception", "remove_exception"}
            ):
                continue
            fields: dict[str, Any] = {
                "operation": {"const": operation},
                "target_unit": reference("u", candidates),
                "evidence": {"type": "array", "minItems": 1, "items": reference("e")},
            }
            required = ["operation", "target_unit", "evidence"]
            if operation != "remove_exception":
                fields["text"] = {"type": "string", "minLength": 1}
                required.append("text")
            if operation in {"change_value", "change_condition"}:
                fields["evidence"]["minItems"] = 0
                fields["keep_support"] = {"type": "array", "items": reference("h")}
            if operation == "add_exception":
                fields["condition"] = {"type": "string", "minLength": 1}
                fields["shared_conditions"] = {"type": "array", "items": reference("u", conditions)}
                if not conditions:
                    fields["shared_conditions"]["maxItems"] = 0
                required.append("condition")
            ops.append(_object(fields, required))
        # append/retract remain available for ordinary new units / general removal;
        # their unchanged v2 forms compile through the same legacy UnitEdit path.
        edit = next(v for v in variants if v["properties"]["action"]["const"] == "edit")
        old = edit["properties"]["edits"]["items"]["oneOf"]
        ops.extend(
            v
            for v in old
            if v["properties"]["operation"]["const"] in {"append", "retract"}
            and refs["e"]
            and (v["properties"]["operation"]["const"] == "append" or refs["u"])
        )
        edit["properties"]["edits"]["items"] = {"oneOf": ops}
        if not ops:
            variants.remove(edit)
    else:
        for variant in list(variants):
            if "edits" not in variant["properties"]:
                continue
            ops = variant["properties"]["edits"]["items"]["oneOf"]
            ops[:] = [
                op
                for op in ops
                if (
                    (refs["u"] or "target_unit" not in op["required"])
                    and (refs["e"] or op["properties"]["operation"]["const"] == "replace")
                )
            ]
            if not refs["u"]:
                for op in ops:
                    if "target_unit" in op["properties"]:
                        op["properties"]["target_unit"] = {"type": "null"}
            if not ops:
                variants.remove(variant)
    if features.source_metadata:
        assertion = {
            "oneOf": [
                _object(
                    {
                        "source": reference("e"),
                        "kind": {"enum": ["reported", "inferred", "observed", "uncertain"]},
                    },
                    ["source", "kind"],
                ),
                _object({"keep": reference("h")}, ["keep"]),
            ]
        }
        assertion["oneOf"] = [
            v
            for v in assertion["oneOf"]
            if ("source" in v["properties"] and refs["e"])
            or ("keep" in v["properties"] and refs["h"])
        ]
        for variant in variants:
            fields = variant["properties"]
            if "units" in fields:
                item = fields["units"]["items"]
                item["properties"]["assertion"] = copy.deepcopy(assertion)
                item["required"].append("assertion")
                if fields["action"]["const"] == "create":
                    item["properties"]["assertion"] = next(
                        v for v in assertion["oneOf"] if "source" in v["properties"]
                    )
            if "edits" in fields:
                for item in fields["edits"]["items"]["oneOf"]:
                    if "text" in item["properties"]:
                        item["properties"]["assertion"] = copy.deepcopy(assertion)
                        if item["properties"]["operation"]["const"] not in {
                            "replace",
                            "change_value",
                            "change_condition",
                        }:
                            item["properties"]["assertion"] = next(
                                v for v in assertion["oneOf"] if "source" in v["properties"]
                            )
                        item["required"].append("assertion")
    return (
        schema if variants else {"type": "object", "properties": {}, "additionalProperties": False}
    )


def feature_envelope_schema(
    arm: str,
    features: EditFeatures,
    mapping: dict[str, Any],
    *,
    allow_create: bool,
) -> dict[str, Any]:
    full = feature_proposal_schema(arm, features, mapping, allow_create=allow_create)
    if not features.single_record_changes:
        return _object(
            {
                "proposals": {
                    "type": "array",
                    "minItems": 0,
                    "items": full if "oneOf" in full else False,
                    **({"maxItems": 0} if "oneOf" not in full else {}),
                }
            },
            ["proposals"],
        )
    create = [v for v in full.get("oneOf", []) if v["properties"]["action"]["const"] == "create"]
    containers = {}
    for target in mapping.get("records", {}):
        variants = feature_proposal_schema(
            arm, features, mapping, allow_create=False, target=target
        )["oneOf"]
        for variant in variants:
            variant["properties"].pop("target", None)
            variant["required"] = [name for name in variant["required"] if name != "target"]
        containers[target] = {"oneOf": variants}
    return _object(
        {
            "creates": {
                "type": "array",
                "items": create[0] if create else False,
                **({"maxItems": 0} if not create else {}),
            },
            "records": _object(containers, []),
        },
        ["creates", "records"],
    )


def compile_semantic_operations(
    proposal: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    """Structural compilation only. The model chooses meaning and applicability."""
    result = copy.deepcopy(proposal)
    if result["action"] == "retract_record":
        return {
            "action": "rewrite",
            "target": result["target"],
            "units": [],
            "withdrawal_evidence": result["evidence"],
        }
    edits = []
    for item in result.get("edits", []):
        operation = item["operation"]
        if operation in {"change_value", "change_condition"}:
            item["operation"] = "replace"
        elif operation == "add_exception":
            item["operation"] = "override"
        elif operation == "remove_exception":
            selected = mapping["units"][item["target_unit"]]
            state = mapping["records"][selected["record"]]["edit_state"]
            unit_id = selected["unit_id"]
            if not selected.get("local_exception") and not any(
                r["relation_type"] == "overrides" and r["source_unit"] == unit_id
                for r in state["relations"]
            ):
                raise FunctionalRejection("EDIT_SELECTED_UNIT_IS_NOT_EXCEPTION")
            item["operation"] = "retract"
            edits.append(item)
            # Only condition nodes whose ALL incident edges attach to this exact
            # exception can leave with it. Shared conditions and general rules stay.
            for alias, unit in mapping["units"].items():
                if unit["record"] != selected["record"] or unit["role"] != "condition":
                    continue
                incident = [
                    r
                    for r in state["relations"]
                    if unit["unit_id"] in {r["source_unit"], r["target_unit"]}
                ]
                if incident and all(
                    r["relation_type"] == "modifies"
                    and r["source_unit"] == unit["unit_id"]
                    and r["target_unit"] == unit_id
                    for r in incident
                ):
                    edits.append(
                        {
                            "operation": "retract",
                            "target_unit": alias,
                            "evidence": copy.deepcopy(item["evidence"]),
                        }
                    )
            continue
        edits.append(item)
    if "edits" in result:
        result["edits"] = edits
    return result


def decorate_state(
    state: dict[str, Any],
    metadata: dict[str, Any] | None,
    *,
    old: dict[str, Any] | None = None,
    edits: list[Any] | None = None,
) -> None:
    """Persist explicitly selected metadata on the same immutable state/version."""
    if metadata is None:
        return
    if "matter_description" in metadata:
        state["matter_description"] = metadata["matter_description"]
    elif old and "matter_description" in old:
        state["matter_description"] = copy.deepcopy(old["matter_description"])
    if "unit_assertions" in metadata and edits is None:
        for unit, assertion in zip(state["units"], metadata["unit_assertions"], strict=True):
            unit["assertion"] = copy.deepcopy(assertion)
    if edits is None:
        by_id = {unit["unit_id"]: unit for unit in state["units"]}
        for relation in state["relations"]:
            if relation["relation_type"] == "overrides":
                by_id[relation["source_unit"]]["local_exception"] = True
        for unit, flag in zip(
            state["units"], metadata.get("unit_exception_flags", []), strict=False
        ):
            if flag:
                unit["local_exception"] = True
