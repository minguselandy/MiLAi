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
) -> dict[str, Any]:
    state = copy.deepcopy(old)
    units, relations = state["units"], state["relations"]
    original_ids = {unit["unit_id"] for unit in units}
    targeted = set()
    for edit in edits:
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
            scoped = {
                "unit_id": new_id("unit"),
                "text": edit.text,
                "role": "content",
                "evidence_refs": evidence,
            }
            scope = {
                "unit_id": new_id("unit"),
                "text": edit.condition,
                "role": "condition",
                "evidence_refs": evidence,
            }
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
        inserted = {
            "unit_id": new_id("unit"),
            "text": edit.text,
            "role": edit.role,
            "evidence_refs": evidence,
        }
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
    if state["representation"] == "plain_v1":
        return "\n".join(unit["text"] for unit in state["units"])
    units = {unit["unit_id"]: unit for unit in state["units"]}
    overrides = {
        r["source_unit"]: r["target_unit"]
        for r in state["relations"]
        if r["relation_type"] == "overrides"
    }
    modified = {r["source_unit"] for r in state["relations"] if r["relation_type"] == "modifies"}
    lines = []
    for unit in state["units"]:
        unit_id = unit["unit_id"]
        if unit["role"] == "condition":
            if unit_id not in modified:
                lines.append("Unbound condition (applicability unresolved): " + unit["text"])
            continue
        prefix = (
            "Scoped override of " + overrides[unit_id] + ": "
            if unit_id in overrides
            else "General content (outside explicit override scopes): "
            if unit_id in overrides.values()
            else "Content: "
        )
        lines.append(unit_id + " — " + prefix + unit["text"])
        conditions = [
            units[r["source_unit"]]["text"]
            for r in state["relations"]
            if r["relation_type"] == "modifies" and r["target_unit"] == unit_id
        ]
        if conditions:
            lines.append("  Applies under: " + "; ".join(conditions))
    return "\n".join(lines)
