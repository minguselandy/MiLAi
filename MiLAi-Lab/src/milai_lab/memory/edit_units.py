"""Local text operators over immutable record versions in the existing Store.

The operators preserve unselected structure. They do not decide entailment,
scope applicability, business permission, or whether an edit is justified.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from milai_lab.memory.functional_state import (
    FunctionalRejection,
    body_text,
    issue_fragment_range,
    resolve_fragment,
)


class EditDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NewUnit(EditDTO):
    text: str = Field(min_length=1)
    role: Literal["content", "condition"] = "content"
    evidence: list[str] = Field(min_length=1)


class NewRelation(EditDTO):
    source: int = Field(ge=0)
    relation_type: Literal["modifies", "overrides"]
    target: int = Field(ge=0)
    evidence: list[str] = Field(min_length=1)


class UnitEdit(EditDTO):
    operation: Literal["replace", "insert", "delete", "append", "override", "retract"]
    target_unit: str | None = None
    text: str | None = None
    role: Literal["content", "condition"] = "content"
    evidence: list[str] = Field(min_length=1)
    condition: str | None = None
    shared_conditions: list[str] = Field(default_factory=list)
    attach_to: list[str] = Field(default_factory=list)


class EditProposal(EditDTO):
    action: Literal["create", "rewrite", "edit", "no_change"]
    target_record: str | None = None
    base_revision: int | None = Field(default=None, ge=1)
    units: list[NewUnit] = Field(default_factory=list)
    relations: list[NewRelation] = Field(default_factory=list)
    edits: list[UnitEdit] = Field(default_factory=list)


def new_id(prefix: str) -> str:
    return prefix + "-" + str(uuid.uuid4())


def issue_evidence(service: Any, source_ref: str, start: int, end: int) -> dict[str, Any]:
    """Reuse the service's persisted original-range references, without another store."""
    with service._locked():
        fragment = issue_fragment_range(service, source_ref, start, end)
    return {
        "evidence_id": fragment["fragment_handle"],
        **{key: fragment[key] for key in ("source_ref", "source_revision", "start", "end")},
    }


def source_evidence(service: Any, evidence_ids: list[str]) -> list[dict[str, Any]]:
    """Resolve issued ranges; selecting a source ID cannot widen a delivered range."""
    refs = list(dict.fromkeys(evidence_ids))
    if not refs:
        raise FunctionalRejection("EDIT_EVIDENCE_REQUIRED")
    evidence = []
    for ref in refs:
        try:
            fragment = resolve_fragment(service, ref)
        except FunctionalRejection as exc:
            raise FunctionalRejection("EDIT_SOURCE_UNAVAILABLE") from exc
        evidence.append(
            {
                "evidence_id": ref,
                **{key: fragment[key] for key in ("source_ref", "source_revision", "start", "end")},
            }
        )
    return evidence


def read_revision_evidence(service: Any, version: dict[str, Any]) -> list[dict[str, Any]]:
    """Read only the exact original ranges selected for this committed revision.

    Older local revisions retain their actual witnesses in edit_operations.
    Missing whole-rewrite witnesses are not reconstructed from a source ID.
    """
    handles = version.get("revision_evidence")
    if handles is None:
        handles = [
            handle
            for edit in version.get("edit_operations", [])
            for handle in edit["evidence"]
        ]
    result = []
    for handle in dict.fromkeys(handles):
        fragment = resolve_fragment(service, handle)
        source = service.source(fragment["source_ref"])
        result.append({
            **{key: fragment[key] for key in (
                "source_ref", "source_revision", "start", "end", "content", "role", "observed_at"
            )},
            "occurred_at": source.get("occurred_at"),
            "semantic_support": "unchecked",
        })
    return result


def validate_state(state: dict[str, Any], service: Any | None = None) -> None:
    """Validate representation references at the service's commit boundary."""
    if (
        not isinstance(state, dict)
        or state.get("representation") not in {"plain_v1", "conditioned_v1"}
        or not isinstance(state.get("units"), list)
        or not isinstance(state.get("relations"), list)
    ):
        raise FunctionalRejection("EDIT_STATE_INVALID")
    units = state["units"]
    by_id = {}
    for unit in units:
        if (
            not isinstance(unit, dict)
            or not isinstance(unit.get("unit_id"), str)
            or not unit["unit_id"]
            or unit["unit_id"] in by_id
            or unit.get("role") not in {"content", "condition"}
            or not isinstance(unit.get("text"), str)
            or not unit["text"].strip()
        ):
            raise FunctionalRejection("EDIT_UNIT_INVALID")
        by_id[unit["unit_id"]] = unit
    conditioned = state["representation"] == "conditioned_v1"
    if not conditioned and (state["relations"] or any(u["role"] != "content" for u in units)):
        raise FunctionalRejection("EDIT_PLAIN_REPRESENTATION_REQUIRED")
    relation_ids = set()
    override_sources = set()
    for relation in state["relations"]:
        if (
            not isinstance(relation, dict)
            or not isinstance(relation.get("relation_id"), str)
            or relation["relation_id"] in relation_ids
            or relation.get("source_unit") not in by_id
            or relation.get("target_unit") not in by_id
            or relation["source_unit"] == relation["target_unit"]
        ):
            raise FunctionalRejection("EDIT_RELATION_INVALID")
        relation_ids.add(relation["relation_id"])
        source, target = by_id[relation["source_unit"]], by_id[relation["target_unit"]]
        if relation.get("relation_type") == "modifies":
            if source["role"] != "condition" or target["role"] != "content":
                raise FunctionalRejection("EDIT_CONDITION_TARGET_INVALID")
        elif relation.get("relation_type") == "overrides":
            if source["role"] != target["role"] or target["role"] != "content":
                raise FunctionalRejection("EDIT_OVERRIDE_TARGET_INVALID")
            override_sources.add(source["unit_id"])
        else:
            raise FunctionalRejection("EDIT_RELATION_TYPE_INVALID")
    for relation in state["relations"]:
        if relation["relation_type"] == "overrides":
            if relation["target_unit"] in override_sources:
                raise FunctionalRejection("EDIT_MULTILEVEL_OVERRIDE_UNSUPPORTED")
            if not any(
                r["relation_type"] == "modifies" and r["target_unit"] == relation["source_unit"]
                for r in state["relations"]
            ):
                raise FunctionalRejection("EDIT_OVERRIDE_SCOPE_REQUIRED")
    for item in [*units, *state["relations"]]:
        evidence = item.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence:
            raise FunctionalRejection("EDIT_EVIDENCE_REQUIRED")
        if service is not None:
            for ref in evidence:
                if not isinstance(ref, dict):
                    raise FunctionalRejection("EDIT_EVIDENCE_REFERENCE_INVALID")
                source = service.source(ref.get("source_ref"))
                if (
                    source is None
                    or source.get("source_revision", 1) != ref.get("source_revision")
                    or type(ref.get("start")) is not int
                    or type(ref.get("end")) is not int
                    or not 0 <= ref["start"] <= ref["end"] <= len(body_text(source))
                ):
                    raise FunctionalRejection("EDIT_EVIDENCE_REFERENCE_INVALID")
                if "evidence_id" in ref:
                    issued = source_evidence(service, [ref["evidence_id"]])[0]
                    if any(
                        issued[key] != ref[key]
                        for key in ("source_ref", "source_revision", "start", "end")
                    ):
                        raise FunctionalRejection("EDIT_EVIDENCE_REFERENCE_INVALID")


def form_state(
    proposal: EditProposal,
    service: Any,
    *,
    conditioned: bool,
) -> dict[str, Any]:
    units = [
        {
            "unit_id": new_id("unit"),
            "text": unit.text,
            "role": unit.role,
            "evidence_refs": source_evidence(service, unit.evidence),
        }
        for unit in proposal.units
    ]
    relations = []
    for relation in proposal.relations:
        if max(relation.source, relation.target) >= len(units):
            raise FunctionalRejection("EDIT_FORMATION_RELATION_INDEX_INVALID")
        relations.append(
            {
                "relation_id": new_id("relation"),
                "source_unit": units[relation.source]["unit_id"],
                "relation_type": relation.relation_type,
                "target_unit": units[relation.target]["unit_id"],
                "evidence_refs": source_evidence(service, relation.evidence),
            }
        )
    if not units:
        raise FunctionalRejection("EDIT_FORMATION_UNITS_REQUIRED")
    return {
        "representation": "conditioned_v1" if conditioned else "plain_v1",
        "units": units,
        "relations": relations,
    }


def apply_local(
    old: dict[str, Any],
    edits: list[UnitEdit],
    service: Any,
    *,
    conditioned: bool,
    assertions: list[dict[str, Any] | None] | None = None,
    mark_exceptions: bool = False,
) -> dict[str, Any]:
    state = copy.deepcopy(old)
    units, relations = state["units"], state["relations"]
    original_ids = {unit["unit_id"] for unit in units}
    targeted = set()
    if assertions is not None and len(assertions) != len(edits):
        raise FunctionalRejection("EDIT_ASSERTION_COMPILATION_INVALID")
    for edit_index, edit in enumerate(edits):
        assertion = assertions[edit_index] if assertions is not None else None
        if edit.operation not in (
            {"replace", "append", "override", "retract"}
            if conditioned
            else {"replace", "insert", "delete"}
        ):
            raise FunctionalRejection("EDIT_OPERATION_NOT_AVAILABLE_IN_ARM")
        by_id = {unit["unit_id"]: unit for unit in units}
        target = by_id.get(edit.target_unit)
        needs_target = edit.operation in {"replace", "delete", "retract", "override"}
        if (needs_target and target is None) or (
            edit.target_unit is not None and edit.target_unit not in original_ids
        ):
            raise FunctionalRejection("EDIT_TARGET_NOT_IN_BASE_REVISION")
        if edit.operation in {"replace", "delete", "retract"}:
            if edit.target_unit in targeted:
                raise FunctionalRejection("EDIT_OVERLAPPING_TARGET")
            targeted.add(edit.target_unit)
        evidence = source_evidence(service, edit.evidence)
        if edit.operation in {"delete", "retract"}:
            if edit.text is not None or edit.condition is not None:
                raise FunctionalRejection("EDIT_RETRACTION_HAS_NEW_TEXT")
            units[:] = [unit for unit in units if unit["unit_id"] != edit.target_unit]
            relations[:] = [
                r for r in relations if edit.target_unit not in {r["source_unit"], r["target_unit"]}
            ]
            continue
        if not isinstance(edit.text, str) or not edit.text.strip():
            raise FunctionalRejection("EDIT_NEW_TEXT_REQUIRED")
        if edit.operation == "replace":
            assert target is not None
            target.update(text=edit.text, evidence_refs=evidence)
            if assertions is not None:
                target["assertion"] = copy.deepcopy(assertion)
            continue
        if edit.operation == "override":
            assert target is not None
            if (
                target["role"] != "content"
                or not isinstance(edit.condition, str)
                or not edit.condition.strip()
            ):
                raise FunctionalRejection("EDIT_EXPLICIT_OVERRIDE_SCOPE_REQUIRED")
            # All generated IDs are issued by the service side, never model hashes.
            scoped: dict[str, Any] = {
                "unit_id": new_id("unit"),
                "text": edit.text,
                "role": "content",
                "evidence_refs": evidence,
            }
            scope: dict[str, Any] = {
                "unit_id": new_id("unit"),
                "text": edit.condition,
                "role": "condition",
                "evidence_refs": evidence,
            }
            if mark_exceptions:
                scoped["local_exception"] = True
            if assertions is not None:
                scoped["assertion"] = copy.deepcopy(assertion)
                scope["assertion"] = copy.deepcopy(assertion)
            units.extend([scoped, scope])
            relations.extend(
                [
                    {
                        "relation_id": new_id("relation"),
                        "source_unit": scope["unit_id"],
                        "relation_type": "modifies",
                        "target_unit": scoped["unit_id"],
                        "evidence_refs": evidence,
                    },
                    {
                        "relation_id": new_id("relation"),
                        "source_unit": scoped["unit_id"],
                        "relation_type": "overrides",
                        "target_unit": target["unit_id"],
                        "evidence_refs": evidence,
                    },
                ]
            )
            for condition_id in edit.shared_conditions:
                condition = by_id.get(condition_id)
                if condition is None or condition["role"] != "condition":
                    raise FunctionalRejection("EDIT_SHARED_CONDITION_INVALID")
                # Reusing an already evidenced condition does not reinterpret its text.
                relations.append(
                    {
                        "relation_id": new_id("relation"),
                        "source_unit": condition_id,
                        "relation_type": "modifies",
                        "target_unit": scoped["unit_id"],
                        "evidence_refs": evidence,
                    }
                )
            continue
        inserted: dict[str, Any] = {
            "unit_id": new_id("unit"),
            "text": edit.text,
            "role": edit.role,
            "evidence_refs": evidence,
        }
        if assertions is not None:
            inserted["assertion"] = copy.deepcopy(assertion)
        if edit.operation == "insert" and target is not None:
            units.insert(units.index(target) + 1, inserted)
        else:
            units.append(inserted)
        for target_id in edit.attach_to:
            if (
                inserted["role"] != "condition"
                or target_id not in original_ids
                or by_id[target_id]["role"] != "content"
            ):
                raise FunctionalRejection("EDIT_APPEND_CONDITION_TARGET_INVALID")
            relations.append(
                {
                    "relation_id": new_id("relation"),
                    "source_unit": inserted["unit_id"],
                    "relation_type": "modifies",
                    "target_unit": target_id,
                    "evidence_refs": evidence,
                }
            )
    return state


def render_state(state: dict[str, Any]) -> str:
    """One renderer shared by B2/M; explicit scoped alternatives guide the common Reader."""

    def assertion_text(unit: dict[str, Any]) -> str:
        assertion = unit.get("assertion")
        if not assertion:
            return ""
        return str(
            " [Assertion: "
            + assertion["kind"]
            + "; speaker="
            + assertion["role"]
            + ("; occurred_at=" + assertion["occurred_at"] if assertion.get("occurred_at") else "")
            + "]"
        )

    matter = (
        ["Matter: " + state["matter_description"]]
        if state.get("matter_description") and state["units"]
        else []
    )
    if state["representation"] == "plain_v1":
        return "\n".join(
            [*matter, *(unit["text"] + assertion_text(unit) for unit in state["units"])]
        )
    units = {unit["unit_id"]: unit for unit in state["units"]}
    overrides = {
        r["source_unit"]: r["target_unit"]
        for r in state["relations"]
        if r["relation_type"] == "overrides"
    }
    modified = {r["source_unit"] for r in state["relations"] if r["relation_type"] == "modifies"}
    lines = matter
    for unit in state["units"]:
        unit_id = unit["unit_id"]
        if unit["role"] == "condition":
            if unit_id not in modified:
                lines.append(
                    "Unbound condition (applicability unresolved): "
                    + unit["text"]
                    + assertion_text(unit)
                )
            continue
        prefix = (
            "Scoped override of " + overrides[unit_id] + ": "
            if unit_id in overrides
            else "General content (outside explicit override scopes): "
            if unit_id in overrides.values()
            else "Content: "
        )
        lines.append(unit_id + " — " + prefix + unit["text"] + assertion_text(unit))
        conditions = [
            units[r["source_unit"]]["text"] + assertion_text(units[r["source_unit"]])
            for r in state["relations"]
            if r["relation_type"] == "modifies" and r["target_unit"] == unit_id
        ]
        if conditions:
            lines.append("  Applies under: " + "; ".join(conditions))
    return "\n".join(lines)


# This directory is the single source for the opt-in writer interface. The v1 DTO
# remains unchanged so archived callers retain their exact public contract.
ARM_OPERATIONS: dict[str, tuple[str, ...]] = {
    "B0": (),
    "B1": ("replace", "insert", "delete"),
    "B2": (),
    "M": ("replace", "append", "override", "retract"),
}
OPERATION_INSTRUCTIONS = {
    "replace": "replace changes only target_unit text/support; it retains that unit's role. ",
    "insert": "insert follows target_unit, or appends when target_unit is omitted or null. ",
    "delete": "delete removes target_unit; cancellation does not assert its opposite. ",
    "append": "append adds a unit; a condition explicitly lists content targets in attach_to. ",
    "override": "override needs condition text; shared_conditions explicitly selects retained "
    "conditions, never automatically copying them to a new subject. ",
    "retract": "retract removes target_unit and incident relations, preserving other scopes. ",
}


def _group_clauses(
    units: list[dict[str, Any]], relations: list[dict[str, Any]], *, view: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group only explicit edges; declare each shared condition body once."""
    keys = [unit["id"] if view else index for index, unit in enumerate(units)]
    by_key = dict(zip(keys, units, strict=True))
    contents = [key for key in keys if by_key[key].get("role", "content") == "content"]
    declared: dict[Any, int] = {}
    clauses = []
    for key in contents:
        clause = copy.deepcopy(by_key[key])
        clause.pop("role", None)
        if view or any(unit.get("role") == "condition" for unit in units) or relations:
            clause["conditions"] = []
        for relation in relations:
            if relation["target"] != key or relation["relation_type"] != "modifies":
                continue
            source = relation["source"]
            binding = {
                k: copy.deepcopy(v)
                for k, v in relation.items()
                if k not in {"source", "target", "relation_type"}
            }
            if source in declared:
                condition = {"reuse": source if view else declared[source]}
            else:
                declared[source] = len(declared)
                condition = copy.deepcopy(by_key[source])
                condition.pop("role", None)
            condition["binding"] = binding
            clause.setdefault("conditions", []).append(condition)
        overrides = []
        for relation in relations:
            if relation["source"] == key and relation["relation_type"] == "overrides":
                overrides.append(
                    {
                        "target": relation["target"]
                        if view
                        else contents.index(relation["target"]),
                        **{
                            k: copy.deepcopy(v)
                            for k, v in relation.items()
                            if k not in {"source", "target", "relation_type"}
                        },
                    }
                )
        if overrides:
            clause["overrides"] = overrides
        clauses.append(clause)
    unresolved = [
        {k: copy.deepcopy(v) for k, v in by_key[key].items() if k != "role"}
        for key in keys
        if by_key[key].get("role") == "condition" and key not in declared
    ]
    return clauses, unresolved


def clause_proposal(proposal: dict[str, Any], *, conditioned: bool) -> dict[str, Any]:
    """Serialize an explicit flat proposal into the opt-in clause contract."""
    result = copy.deepcopy(proposal)
    if result.get("action") not in {"create", "rewrite"} or "units" not in result:
        return result
    clauses, unresolved = _group_clauses(
        result.pop("units"), result.pop("relations", []), view=False
    )
    if conditioned:
        for clause in clauses:
            clause.setdefault("conditions", [])
    else:
        for clause in clauses:
            clause.pop("conditions", None)
    result["clauses"] = clauses
    if unresolved:
        result["unresolved_conditions"] = unresolved
    return result


def compile_clause_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Expand declared bindings, without selecting supports or reading old bodies."""
    result = copy.deepcopy(proposal)
    if "clauses" not in result:
        return result
    clauses = result.pop("clauses")
    units: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    declarations: list[int] = []
    content_indexes: list[int] = []
    relation_groups: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    for clause in clauses:
        declared_links: list[dict[str, Any]] = []
        reused_links: list[dict[str, Any]] = []
        content_index = len(units)
        content_indexes.append(content_index)
        units.append(
            {k: v for k, v in clause.items() if k not in {"conditions", "overrides"}}
            | {"role": "content"}
        )
        for condition in clause.get("conditions", []):
            if "reuse" in condition:
                reuse = condition["reuse"]
                if type(reuse) is not int or not 0 <= reuse < len(declarations):
                    raise FunctionalRejection("EDIT_DECLARED_CONDITION_UNAVAILABLE")
                source_index = declarations[reuse]
            else:
                source_index = len(units)
                declarations.append(source_index)
                units.append(
                    {k: v for k, v in condition.items() if k != "binding"} | {"role": "condition"}
                )
            link = {
                "source": source_index,
                "target": content_index,
                "relation_type": "modifies",
                **condition["binding"],
            }
            (reused_links if "reuse" in condition else declared_links).append(link)
        relation_groups.append((declared_links, reused_links))
    for clause, source_index, (declared_links, reused_links) in zip(
        clauses, content_indexes, relation_groups, strict=True
    ):
        relations.extend(declared_links)
        for override in clause.get("overrides", []):
            target = override["target"]
            if type(target) is not int or not 0 <= target < len(content_indexes):
                raise FunctionalRejection("EDIT_FORMATION_RELATION_INDEX_INVALID")
            relations.append(
                {
                    "source": source_index,
                    "target": content_indexes[target],
                    "relation_type": "overrides",
                    **{k: v for k, v in override.items() if k != "target"},
                }
            )
        relations.extend(reused_links)
    units.extend({**unit, "role": "condition"} for unit in result.pop("unresolved_conditions", []))
    result.update(units=units, relations=relations)
    return result


def clause_record_view(record: dict[str, Any]) -> None:
    """Replace flat public state with actual grouped rules, preserving aliases."""
    state = record.get("edit_state", record)
    if not state or "units" not in state:
        return
    units = state.pop("units")
    if any(unit.get("role") == "legacy_unstructured" for unit in units):
        state["clauses"] = units
        state.pop("relations", None)
        return
    clauses, unresolved = _group_clauses(units, state.pop("relations", []), view=True)
    if record["representation"] == "plain_v1":
        for clause in clauses:
            clause.pop("conditions", None)
    state["clauses"] = clauses
    if unresolved:
        state["unresolved_conditions"] = unresolved


def writer_proposal_schema(arm: str, *, allow_create: bool = True) -> dict[str, Any]:
    """Thin legal proposals: no model-issued persistent IDs or revisions."""
    if arm not in ARM_OPERATIONS:
        raise ValueError("EDIT_ARM_INVALID")
    conditioned = arm in {"B2", "M"}

    def obj(fields: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": fields,
            "required": required,
            "additionalProperties": False,
        }

    def ref(prefix: str) -> dict[str, Any]:
        return {"type": "string", "pattern": "^" + prefix + "[1-9][0-9]*$"}

    def refs(prefix: str, minimum: int = 0) -> dict[str, Any]:
        return {"type": "array", "items": ref(prefix), "minItems": minimum}

    text = {"type": "string", "minLength": 1}
    support = {"evidence": refs("e"), "keep_support": refs("h")}
    role = {"type": "string", "enum": ["content", "condition"] if conditioned else ["content"]}

    def units(create: bool) -> dict[str, Any]:
        fields = {"text": text, "role": role, **support}
        if create:
            fields.pop("keep_support")
            fields["evidence"] = refs("e", 1)
        return {
            "type": "array",
            "items": obj(fields, ["text", "evidence"]),
            "minItems": 1 if create else 0,
        }

    def relations(create: bool) -> dict[str, Any]:
        index = {"type": "integer", "minimum": 0}
        fields = {
            "source": index,
            "target": index,
            "relation_type": {"enum": ["modifies", "overrides"], "type": "string"},
            **support,
        }
        if create:
            fields.pop("keep_support")
            fields["evidence"] = refs("e", 1)
        return {
            "type": "array",
            "items": obj(fields, ["source", "target", "relation_type", "evidence"]),
        }

    def state_fields(create: bool) -> dict[str, Any]:
        fields = {"units": units(create)}
        if conditioned:
            fields["relations"] = relations(create)
        return fields

    variants = []
    if allow_create:
        variants.append(
            obj({"action": {"const": "create"}, **state_fields(True)}, ["action", "units"])
        )
    if not ARM_OPERATIONS[arm]:
        fields = {
            "action": {"const": "rewrite"},
            "target": ref("r"),
            **state_fields(False),
            "withdrawal_evidence": refs("e", 1),
        }
        variants.append(obj(fields, ["action", "target", "units"]))
    else:
        edits = []
        for operation in ARM_OPERATIONS[arm]:
            fields = {"operation": {"const": operation}, "evidence": refs("e", 1)}
            required = ["operation", "evidence"]
            if operation in {"replace", "delete", "retract", "override"}:
                fields["target_unit"] = ref("u")
                required.append("target_unit")
            elif operation == "insert":
                fields["target_unit"] = {"anyOf": [ref("u"), {"type": "null"}]}
            if operation not in {"delete", "retract"}:
                fields["text"] = text
                required.append("text")
            if operation == "replace":
                fields.update(support)
            if operation in {"insert", "append"}:
                fields["role"] = role
            if operation == "append":
                fields["attach_to"] = refs("u")
            if operation == "override":
                fields["condition"] = text
                fields["shared_conditions"] = refs("u")
                required.append("condition")
            edits.append(obj(fields, required))
        variants.append(
            obj(
                {
                    "action": {"const": "edit"},
                    "target": ref("r"),
                    "edits": {"type": "array", "minItems": 1, "items": {"oneOf": edits}},
                },
                ["action", "target", "edits"],
            )
        )
    variants.append(obj({"action": {"const": "no_change"}, "target": ref("r")}, ["action"]))
    return {"oneOf": variants}


def writer_projection(
    delivery: dict[str, Any],
    profile: str,
    arm: str,
    *,
    allow_create: bool,
    features: dict[str, bool] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure projection for request budgeting, including old immutable snapshots.

    No Store reads, source resolution, fresh delivery claims, or persistence occur
    here. Only EditMemory.writer_view can turn this draft into an executable map.
    """
    records: dict[str, Any] = {}
    units: dict[str, Any] = {}
    fresh: dict[str, Any] = {}
    prior: dict[str, Any] = {}
    sources: dict[tuple[str, int], str] = {}
    attributes = []
    public_evidence = []
    public_records: list[dict[str, Any]] = []
    public_support = []
    delivered = [
        (row, "current") for row in delivery.get("sources", [])
    ] + [(row, "redelivered_support") for row in delivery.get("redelivered_sources", [])]
    classify_delivery = "redelivered_sources" in delivery
    delivery_kinds: dict[tuple[str, int], list[str]] = {}
    if classify_delivery:
        for row, kind in delivered:
            kinds = delivery_kinds.setdefault((row["source_ref"], row["source_revision"]), [])
            if kind not in kinds:
                kinds.append(kind)
    source_rows = {row["source_ref"]: row for row, _ in delivered}
    if features and features.get("source_metadata"):
        source_rows.update(
            {row["source_ref"]: row for row in delivery.get("source_attributes", [])}
        )
    delivered_sources = {row["source_ref"] for row, _ in delivered}

    def source_id(ref: dict[str, Any]) -> str:
        key = (ref["source_ref"], ref["source_revision"])
        if key not in sources:
            alias = "s" + str(len(sources) + 1)
            sources[key] = alias
            row = source_rows.get(key[0], {})
            attributes.append(
                {
                    "id": alias,
                    "role": row.get("role", "not_redelivered"),
                    "observed_at": row.get("observed_at"),
                    "source_revision": key[1],
                }
            )
            if "timestamp" in row:
                attributes[-1]["timestamp"] = copy.deepcopy(row["timestamp"])
            if features and features.get("source_metadata"):
                attributes[-1]["role"] = row.get("role", "unknown")
                attributes[-1]["body_delivered"] = key[0] in delivered_sources
                attributes[-1]["occurred_at"] = row.get("occurred_at")
            if classify_delivery:
                attributes[-1]["delivery_kinds"] = delivery_kinds.get(key, []).copy()
                attributes[-1]["body_delivered"] = bool(attributes[-1]["delivery_kinds"])
                attributes[-1]["occurred_at"] = row.get("occurred_at")
        return sources[key]

    for source, kind in delivered:
        alias = "e" + str(len(fresh) + 1)
        fresh[alias] = copy.deepcopy(source)
        public_evidence.append(
            {
                "id": alias,
                "source": source_id(source),
                "range": [source["start"], source["end"]],
                "text": source["text"],
            }
        )
        if classify_delivery:
            fresh[alias]["delivery_kind"] = kind
            public_evidence[-1]["delivery_kind"] = kind
    for record in delivery.get("records", []):
        record_alias = "r" + str(len(records) + 1)
        records[record_alias] = copy.deepcopy(record)
        state = record.get("edit_state")
        public_units, public_relations = [], []
        by_id = {}
        if state:
            for unit in state["units"]:
                alias = "u" + str(len(units) + 1)
                by_id[unit["unit_id"]] = alias
                units[alias] = {"record": record_alias, **copy.deepcopy(unit)}
                public_units.append({"id": alias, "role": unit["role"], "text": unit["text"]})
                if features and unit.get("local_exception"):
                    public_units[-1]["local_exception"] = True
                if features and features.get("source_metadata"):
                    assertion = unit.get("assertion")
                    public_units[-1]["assertion"] = (
                        {"kind": assertion["kind"], "source": source_id(assertion)}
                        if assertion and "source_ref" in assertion
                        else {"kind": "legacy_unspecified", "source": None}
                    )

            def support_id(
                item: dict[str, Any], binding: dict[str, Any], record_alias: str = record_alias
            ) -> str:
                alias = "h" + str(len(prior) + 1)
                refs = copy.deepcopy(item["evidence_refs"])
                prior[alias] = {"record": record_alias, "evidence_refs": refs, **binding}
                public_support.append(
                    {
                        "id": alias,
                        "use": "EXISTING_SUPPORT_ONLY",
                        "record": record_alias,
                        **binding,
                        "ranges": [
                            {"source": source_id(ref), "range": [ref["start"], ref["end"]]}
                            for ref in refs
                        ],
                    }
                )
                return alias

            for item, public in zip(state["units"], public_units, strict=True):
                public["support"] = [support_id(item, {"unit": public["id"]})]
            for relation in state["relations"]:
                binding = {
                    "source": by_id[relation["source_unit"]],
                    "target": by_id[relation["target_unit"]],
                    "relation_type": relation["relation_type"],
                }
                public_relations.append({**binding, "support": [support_id(relation, binding)]})
        else:
            # Legacy records stay readable; no invented unit formation or support.
            public_units = [{"text": record["content"], "role": "legacy_unstructured"}]
        public_record = {
            "id": record_alias,
            "representation": state["representation"] if state else "legacy_unstructured",
            "units": public_units,
            "relations": public_relations,
        }
        if "scope" in record:
            public_record["scope"] = copy.deepcopy(record["scope"])
        if features and features.get("matter_organization"):
            public_record["matter"] = state.get("matter_description") if state else None
        if profile == "I1":
            # Preserve v1's repeated text view, but remove persistent identifiers.
            repeated = (
                {
                    "representation": state["representation"],
                    "units": public_units,
                    "relations": public_relations,
                }
                if state
                else None
            )
            if state and state["representation"] == "conditioned_v1":
                renderable = copy.deepcopy(state)
                for unit in renderable["units"]:
                    unit["unit_id"] = by_id[unit["unit_id"]]
                for relation in renderable["relations"]:
                    relation["source_unit"] = by_id[relation["source_unit"]]
                    relation["target_unit"] = by_id[relation["target_unit"]]
                content = render_state(renderable)
            else:
                content = record["content"]
            public_record["content"] = content
            public_record["edit_state"] = repeated
            public_record.pop("units")
            public_record.pop("relations")
        public_records.append(public_record)
    # The opt-in matter workflow starts with the actual dialogue; old matters
    # follow as revision targets. Keep the information, aliases and default view.
    material = (
        {"evidence": public_evidence, "records": public_records}
        if features and any(features.values())
        else {"records": public_records, "evidence": public_evidence}
    )
    packet = {
        "interface_version": profile,
        "arm": arm,
        "allow_create": allow_create,
        **material,
        "historical_support": public_support,
        "source_table": attributes,
    }
    if profile == "I1":
        # I1 retains v1's repeated support metadata as well as its two text
        # views. I2 factors these exact attributes into one global table.
        by_source = {attribute["id"]: attribute for attribute in attributes}
        by_support = {support["id"]: support for support in public_support}

        def repeated_refs(support_ids: list[str]) -> list[dict[str, Any]]:
            return [
                {
                    "support": support_id,
                    **span,
                    **{
                        key: value
                        for key, value in by_source[span["source"]].items()
                        if key != "id"
                    },
                    "body_delivered": False,
                }
                for support_id in support_ids
                for span in by_support[support_id]["ranges"]
            ]

        for public_record in public_records:
            repeated = public_record["edit_state"]
            if repeated:
                for item in [*repeated["units"], *repeated["relations"]]:
                    item["evidence_refs"] = repeated_refs(item["support"])
        packet["historical_evidence"] = repeated_refs(list(by_support))
        for evidence in public_evidence:
            evidence.update(
                {key: value for key, value in by_source[evidence["source"]].items() if key != "id"}
            )
            evidence["body_delivered"] = True
    if features and any(features.values()):
        for public_record in public_records:
            clause_record_view(public_record)
    draft = {
        "arm": arm,
        "interface_version": profile,
        "allow_create": allow_create,
        "records": records,
        "units": units,
        "evidence": fresh,
        "support": prior,
    }
    if features and any(features.values()):
        packet["edit_features"] = copy.deepcopy(features)
        draft["edit_features"] = copy.deepcopy(features)
    return packet, draft
