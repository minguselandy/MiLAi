"""Opt-in contracts over the existing four edit arms, without model execution."""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from milai_lab.memory.edit_units import compile_clause_proposal, writer_proposal_schema
from milai_lab.memory.functional_state import FunctionalRejection


@dataclass(frozen=True)
class EditFeatures:
    matter_organization: bool = False
    semantic_operations: bool = False
    bound_references: bool = False
    single_record_changes: bool = False
    source_metadata: bool = False
    temporal_scope: bool = False

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> EditFeatures:
        known = asdict(cls())
        if set(settings) - set(known) or any(type(v) is not bool for v in settings.values()):
            raise ValueError("EDIT_FEATURE_SETTINGS_INVALID")
        return cls(**settings)

    def __post_init__(self) -> None:
        if self.temporal_scope and not self.source_metadata:
            raise ValueError("EDIT_TEMPORAL_SCOPE_REQUIRES_SOURCE_METADATA")

    @property
    def enabled(self) -> bool:
        return any(asdict(self).values())

    def settings(self) -> dict[str, bool]:
        settings = asdict(self)
        # Existing frozen writer maps keep their original five-feature shape.
        if not self.temporal_scope:
            settings.pop("temporal_scope")
        return settings


def _object(fields: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": required,
    }


def compact_prompt_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Share repeated sub-schemas in the Writer's explanatory schema only.

    The original bound schema still controls generation and decoding. Referencing
    an identical sub-schema through $defs preserves every constraint and annotation.
    Existing schemas with definitions retain their original reference locations.
    """
    if "$defs" in schema:
        return copy.deepcopy(schema)
    counts: Counter[str] = Counter()
    originals: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}

    def key(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    mapping_fields = ("properties", "patternProperties", "dependentSchemas")
    single_fields = ("items", "additionalProperties", "contains", "propertyNames", "not",
                     "if", "then", "else")
    sequence_fields = ("oneOf", "anyOf", "allOf", "prefixItems")
    schema_fields = {*mapping_fields, *single_fields, *sequence_fields}

    def collect(value: Any) -> None:
        if not isinstance(value, dict):
            return
        candidate = key(value)
        counts[candidate] += 1
        originals.setdefault(candidate, value)
        # This pass only counts; its former projected tree was discarded.
        for field in mapping_fields:
            if field in value:
                for child in value[field].values():
                    collect(child)
        for field in single_fields:
            if field in value:
                collect(value[field])
        for field in sequence_fields:
            if field in value:
                for child in value[field]:
                    collect(child)

    def project(value: Any, *, definition: bool = False) -> Any:
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        candidate = key(value)
        if candidate in names and not definition:
            return {"$ref": "#/$defs/" + names[candidate]}
        # Preserve key order and independent data without first copying schema
        # subtrees that the recursive projection immediately replaces.
        result = copy.deepcopy({
            field: None if field in schema_fields else child for field, child in value.items()
        })
        # Only schema positions are traversed: enum/const/default values are data.
        for field in mapping_fields:
            if field in value:
                result[field] = {
                    name: project(child) for name, child in value[field].items()
                }
        for field in single_fields:
            if field in value:
                result[field] = project(value[field])
        for field in sequence_fields:
            if field in value:
                result[field] = [project(child) for child in value[field]]
        return result

    collect(schema)
    for candidate, count in counts.items():
        name = f"shared_{len(names)}"
        reference = {"$ref": "#/$defs/" + name}
        overhead = count * len(key(reference)) + len(name) + 4
        if count > 1 and (count - 1) * len(candidate) > overhead:
            names[candidate] = name
    result: dict[str, Any] = project(schema)
    if names:
        result["$defs"] = {
            name: project(originals[candidate], definition=True)
            for candidate, name in names.items()
        }
    return (
        result
        if len(key(result)) < len(key(schema))
        else copy.deepcopy(schema)
    )


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
            variant["properties"]["revision_evidence"] = {
                "type": "array",
                "minItems": 1,
                "items": reference("e"),
            }
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
                fields["shared_conditions"] = {
                    "type": "array",
                    "items": reference("u", conditions),
                    "description": "Explicitly selected existing condition units in this record. "
                    "A content clause is not a condition, even if its text describes a limit.",
                }
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
        if features.temporal_scope:
            # These are semantic selections from the named current evidence, not
            # service-owned speaker, source, version or capture metadata.
            assertion["oneOf"][0]["properties"]["applicability"] = _object(
                {
                    key: {"type": "string", "minLength": 1}
                    for key in ("event_at", "effective_from", "effective_until", "scope")
                }
                | {"quantity_scope": {"enum": ["overall", "per_member"]}},
                [],
            )
            assertion["oneOf"][0]["properties"]["evidence_links"] = _object(
                {
                    stance: {"type": "array", "items": reference("e")}
                    for stance in ("supports", "opposes")
                },
                [],
            )
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
    for variant in variants:
        fields = variant["properties"]
        if "units" not in fields:
            continue
        unit = fields.pop("units")
        clause = copy.deepcopy(unit["items"])
        clause["properties"].pop("role")
        if fields["action"]["const"] == "rewrite":
            prior_contents = [
                alias for alias in refs["u"] if mapping["units"][alias]["role"] == "content"
            ]
            if prior_contents:
                clause["properties"]["from_unit"] = reference("u", prior_contents)
        fields["clauses"] = {**unit, "items": clause}
        variant["required"] = ["clauses" if key == "units" else key for key in variant["required"]]
        if arm not in {"B2", "M"}:
            continue
        relation = fields.pop("relations")["items"]
        binding = _object(
            {
                key: value
                for key, value in relation["properties"].items()
                if key not in {"source", "target", "relation_type"}
            },
            ["evidence"],
        )
        binding["description"] = "Evidence for applying this condition to the containing clause."
        condition = copy.deepcopy(clause)
        condition["properties"].pop("from_unit", None)
        if fields["action"]["const"] == "rewrite":
            prior_conditions = [
                alias for alias in refs["u"] if mapping["units"][alias]["role"] == "condition"
            ]
            if prior_conditions:
                condition["properties"]["from_unit"] = reference("u", prior_conditions)
        condition["properties"]["binding"] = copy.deepcopy(binding)
        condition["required"].append("binding")
        clause["properties"]["conditions"] = {
            "type": "array",
            "description": "Independently revisable prerequisites, limits and scopes applying "
            "to this clause. Declare each with its own support and binding; reuse an earlier "
            "declaration when the same condition applies to another clause.",
            "items": {
                "oneOf": [
                    condition,
                    _object(
                        {
                            "reuse": {"type": "integer", "minimum": 0},
                            "binding": copy.deepcopy(binding),
                        },
                        ["reuse", "binding"],
                    ),
                ]
            },
        }
        clause["required"].append("conditions")
        clause["properties"]["overrides"] = {
            "type": "array",
            "items": _object(
                {
                    "target": {"type": "integer", "minimum": 0},
                    **copy.deepcopy(binding["properties"]),
                },
                ["target", "evidence"],
            ),
        }
        if fields["action"]["const"] == "rewrite":
            orphan_support = []
            for alias in refs["h"]:
                support = mapping["support"][alias]
                selected = mapping["units"].get(support.get("unit"))
                if selected is None or selected["role"] != "condition":
                    continue
                state = mapping["records"][selected["record"]]["edit_state"]
                if not any(
                    edge["relation_type"] == "modifies"
                    and edge["source_unit"] == selected["unit_id"]
                    for edge in state["relations"]
                ):
                    orphan_support.append(alias)
            orphan = copy.deepcopy(condition)
            orphan["properties"].pop("binding")
            orphan["required"].remove("binding")
            orphan["properties"]["evidence"]["maxItems"] = 0
            orphan["properties"]["keep_support"] = {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": reference("h", orphan_support),
            }
            orphan["required"].append("keep_support")
            if features.source_metadata:
                orphan["properties"]["assertion"] = _object(
                    {"keep": reference("h", orphan_support)}, ["keep"]
                )
            fields["unresolved_conditions"] = {
                "type": "array",
                "items": orphan,
                **({"maxItems": 0} if not orphan_support else {}),
            }
        scoped = copy.deepcopy(clause)
        scoped["properties"]["conditions"]["minItems"] = 1
        scoped["properties"]["overrides"]["minItems"] = 1
        scoped["required"].append("overrides")
        clause["properties"]["overrides"]["maxItems"] = 0
        # An override must bind an actual scope to this clause. Ordinary claims
        # may stay unqualified; declared/reused conditions share the same path.
        fields["clauses"]["items"] = {"oneOf": [clause, scoped]}
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
                "description": "New matters only. Omit when there are none.",
                "default": [],
                "items": create[0] if create else False,
                **({"maxItems": 0} if not create else {}),
            },
            "records": {
                **_object(containers, []),
                "description": "Existing matters keyed by their explicit delivered r alias. "
                "Omit when there are no existing-matter changes.",
                "default": {},
            },
        },
        [],
    )


def compile_semantic_operations(
    proposal: dict[str, Any], mapping: dict[str, Any]
) -> dict[str, Any]:
    """Structural compilation only. The model chooses meaning and applicability."""
    result = compile_clause_proposal(proposal)
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
