"""Local text operators over immutable record versions in the existing Store.

The operators preserve unselected structure. They do not decide entailment,
scope applicability, business permission, or whether an edit is justified.
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
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
            **({"calendar_context": source["calendar_context"]}
               if "calendar_context" in source else {}),
            "semantic_support": "unchecked",
        })
    return result


def read_revision_scope(
    service: Any, record_id: str, version: dict[str, Any]
) -> list[dict[str, Any]]:
    """Show previous override roles only for literally retained current units.

    Read one existing predecessor, not the full history. Removed facts are not
    delivered or reconstructed, and prior scope handles remain historical.
    """
    state = version.get("edit_state")
    if not state or version["revision"] <= 1:
        return []
    previous = service.read(record_id, version["revision"] - 1)
    if not previous["ok"]:
        return []
    prior = previous["value"].get("edit_state")
    if not prior:
        return []
    result = []
    for old in prior["units"]:
        overrides = [
            edge for edge in prior["relations"]
            if edge["relation_type"] == "overrides" and edge["target_unit"] == old["unit_id"]
        ]
        if not overrides:
            continue
        kept = [
            unit for unit in state["units"]
            if {k: v for k, v in unit.items() if k != "unit_id"}
            == {k: v for k, v in old.items() if k != "unit_id"}
        ]
        if len(kept) != 1:
            continue
        for unit in kept:
            result.append({
                "current_unit_id": unit["unit_id"],
                "previous_revision": previous["value"]["revision"],
                "previous_role": "general_rule_outside_explicit_override_scopes",
                "previous_scope_units": list(dict.fromkeys(
                    edge["source_unit"] for edge in prior["relations"]
                    if edge["relation_type"] == "modifies"
                    and any(
                        edge["target_unit"] == override["source_unit"] for override in overrides
                    )
                )),
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


@dataclass(frozen=True)
class _DeclaredTime:
    value: datetime
    precision: str
    calendar_context: str | None

    @property
    def timezone_known(self) -> bool:
        return self.value.utcoffset() is not None

    def describe(self) -> dict[str, Any]:
        return {
            "value": self.value.date().isoformat() if self.precision == "day"
            else self.value.isoformat(timespec={
                "hour": "hours", "minute": "minutes", "second": "seconds",
            }.get(self.precision, "auto")),
            "precision": self.precision,
            "timezone_known": self.timezone_known,
            "calendar_context": self.calendar_context,
        }


def _declared_time(
    value: str | None, *, calendar_context: str | None = None
) -> _DeclaredTime | None:
    """Parse stated calendar values, preserving precision and absent timezone.

    A date's internal lower boundary is not an event instant. Effective day
    limits bound the day; an event or query expressed as a date covers the day.
    Calendar context is a framework declaration, never inferred from the text.
    """
    if value is None:
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        pass
    else:
        return _DeclaredTime(datetime.combine(day, time()), "day", calendar_context or None)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        english = re.fullmatch(
            r"([A-Za-z]+) (\d{1,2}), (\d{4})(?:, (\d{2}):(\d{2}):(\d{2}))?", value
        )
        months = (
            "January", "February", "March", "April", "May", "June", "July", "August",
            "September", "October", "November", "December",
        )
        if english is None:
            return None
        month = next((i for i, name in enumerate(months, 1)
                      if english[1].lower() in {name.lower(), name[:3].lower()}), None)
        if month is None:
            return None
        try:
            parsed = datetime(int(english[3]), month, int(english[2]),
                              int(english[4]) if english[4] is not None else 0,
                              int(english[5]) if english[5] is not None else 0,
                              int(english[6]) if english[6] is not None else 0)
        except ValueError:
            return None
        precision = "second" if english[4] is not None else "day"
    else:
        clock = re.search(r"[Tt ](\d{2}(?::?\d{2}){0,2})([.,]\d+)?", value)
        precision = "subsecond" if clock and clock[2] else {
            2: "hour", 4: "minute", 6: "second"
        }.get(len(clock[1].replace(":", "")) if clock else 6, "second")
    return _DeclaredTime(parsed, precision, calendar_context or None)


def _comparison_basis(left: _DeclaredTime, right: _DeclaredTime) -> str | None:
    if left.timezone_known and right.timezone_known:
        return "absolute_offsets"
    if (not left.timezone_known and not right.timezone_known
            and left.calendar_context is not None
            and left.calendar_context == right.calendar_context):
        return "shared_floating_calendar"
    return None


def _clock_value(value: _DeclaredTime) -> datetime:
    return value.value.astimezone(UTC) if value.timezone_known else value.value


def _time_order(
    left: _DeclaredTime | None, right: _DeclaredTime | None
) -> tuple[int | None, str | None]:
    """Order only with explicit offsets or a shared declared nominal coordinate."""
    if left is None or right is None:
        return None, None
    basis = _comparison_basis(left, right)
    if basis is None:
        return None, None
    a, b = _clock_value(left), _clock_value(right)
    if left.precision == "day" or right.precision == "day":
        a_end = a + timedelta(days=1) if left.precision == "day" else a
        b_end = b + timedelta(days=1) if right.precision == "day" else b
        if a < b and a_end <= b:
            return -1, basis
        if a > b and a >= b_end:
            return 1, basis
        return None, basis
    return (a > b) - (a < b), basis


def _combined_limit(values: list[_DeclaredTime], *, latest: bool) -> _DeclaredTime | None:
    if not values or any(_comparison_basis(values[0], item) is None for item in values[1:]):
        return None
    return (max if latest else min)(values, key=_clock_value)


def validate_applicability(
    applicability: dict[str, Any], *, calendar_context: str | None = None
) -> None:
    """Validate generated semantic dates once, when decoding the public proposal."""
    times = {}
    for key in ("event_at", "effective_from", "effective_until"):
        if key in applicability:
            times[key] = _declared_time(applicability[key], calendar_context=calendar_context)
            if times[key] is None:
                raise FunctionalRejection("EDIT_EXPLICIT_TIME_REQUIRED")
    start, end = times.get("effective_from"), times.get("effective_until")
    if (start is not None and end is not None and _comparison_basis(start, end) is not None
            and _clock_value(start) >= _clock_value(end)):
        raise FunctionalRejection("EDIT_EFFECTIVE_INTERVAL_INVALID")


def evidence_status(assertion: dict[str, Any]) -> str:
    """Classify explicitly selected evidence links, never source existence or truth."""
    links = assertion.get("evidence_links") or {}
    supporting, opposing = bool(links.get("supports")), bool(links.get("opposes"))
    return "both" if supporting and opposing else "supported" if supporting else (
        "opposed" if opposing else "insufficient"
    )


def _temporal_view(
    unit: dict[str, Any],
    conditions: list[dict[str, Any]],
    query_time: str | None,
    version_time: str | None,
    query_calendar_context: str | None,
) -> dict[str, Any]:
    assertion = unit.get("assertion") or {}
    applicability = assertion.get("applicability") or {}
    limits = []
    starts: list[_DeclaredTime] = []
    ends: list[_DeclaredTime] = []
    unresolved_limit = False
    for item in [unit, *conditions]:
        origin = item.get("assertion") or {}
        declared = origin.get("applicability") or {}
        context = origin.get("calendar_context")
        start, end = declared.get("effective_from"), declared.get("effective_until")
        parsed_start = _declared_time(start, calendar_context=context)
        parsed_end = _declared_time(end, calendar_context=context)
        if start is not None or end is not None:
            limits.append({
                "unit_id": item["unit_id"], "from": start, "until": end,
                "calendar_context": context,
                "from_time": parsed_start.describe() if parsed_start else None,
                "until_time": parsed_end.describe() if parsed_end else None,
            })
            unresolved_limit |= ((start is not None and parsed_start is None)
                                 or (end is not None and parsed_end is None))
        if parsed_start is not None:
            starts.append(parsed_start)
        if parsed_end is not None:
            ends.append(parsed_end)
    start_at = _combined_limit(starts, latest=True)
    end_at = _combined_limit(ends, latest=False)
    queried_at = _declared_time(query_time, calendar_context=query_calendar_context)
    basis = None
    if any(_comparison_basis(start, end) is not None
           and _clock_value(start) >= _clock_value(end) for start in starts for end in ends):
        status = "inconsistent_explicit_limits"
    elif query_time is None:
        status = "query_time_unspecified"
    elif queried_at is None:
        status = "query_time_unresolved"
    elif unresolved_limit:
        status = "explicit_time_unresolved"
    elif any(_comparison_basis(queried_at, bound) is None for bound in [*starts, *ends]):
        status = "time_context_unresolved"
    elif starts or ends:
        basis = _comparison_basis(queried_at, (starts or ends)[0])
        lower = _clock_value(queried_at)
        upper = lower + timedelta(days=1) if queried_at.precision == "day" else lower
        if any((upper <= _clock_value(start) if queried_at.precision == "day"
                else lower < _clock_value(start)) for start in starts):
            status = "before_explicit_start"
        elif any(lower >= _clock_value(end) for end in ends):
            status = "expired"
        elif (any(lower < _clock_value(start) for start in starts)
              or any(upper > _clock_value(end) for end in ends)):
            status = "query_time_precision_unresolved"
        else:
            status = "within_explicit_limits"
    else:
        status = "effective_limits_unspecified"
    reported_at = assertion.get("occurred_at")
    context = assertion.get("calendar_context")
    reported = _declared_time(reported_at, calendar_context=context)
    event_at = _declared_time(applicability.get("event_at"), calendar_context=context)
    effective_from = _declared_time(applicability.get("effective_from"), calendar_context=context)
    retrospective, retrospective_basis = _time_order(event_at or effective_from, reported)
    after_query, reported_basis = _time_order(reported, queried_at)
    parsed_times = {
        "reported_at": reported,
        "captured_at": _declared_time(assertion.get("observed_at")),
        "event_at": event_at,
        "effective_from": effective_from,
        "effective_until": _declared_time(applicability.get("effective_until"),
                                           calendar_context=context),
        "version_time": _declared_time(version_time),
        "query_time": queried_at,
    }
    return {
        "reported_at": reported_at,
        "captured_at": assertion.get("observed_at"),
        "event_at": applicability.get("event_at"),
        "effective_from": applicability.get("effective_from"),
        "effective_until": applicability.get("effective_until"),
        "bound_effective_limits": limits,
        "combined_effective_from": start_at.describe()["value"] if start_at else None,
        "combined_effective_until": end_at.describe()["value"] if end_at else None,
        "version_time": version_time,
        "query_time": query_time,
        "query_calendar_context": query_calendar_context,
        "time_values": {key: parsed.describe() for key, parsed in parsed_times.items()
                        if parsed is not None},
        "status": status,
        "interval_convention": "[from, until); date limits bound the declared day, without UTC",
        "comparison_basis": {"effective_limits": basis, "retrospective": retrospective_basis,
                             "reported_after_query": reported_basis},
        "retrospective": retrospective < 0 if retrospective is not None else None,
        "reported_after_query": after_query > 0 if after_query is not None else None,
    }


def read_applicability(
    state: dict[str, Any],
    *,
    query_time: str | None = None,
    version_time: str | None = None,
    query_calendar_context: str | None = None,
    include_temporal: bool = False,
) -> dict[str, dict[str, Any]]:
    """Project actual relations and explicit limits, without resolving natural scope.

    A report clock never supplies a missing onset. An explicit retrospective event
    remains available for a descriptive past answer. Temporal eligibility is not
    truth, scope satisfaction or evidence availability at that historical time.
    The caller supplies an already-visible current or historical record version.
    """
    units = {unit["unit_id"]: unit for unit in state["units"]}
    conditions: dict[str, list[str]] = {key: [] for key in units}
    overrides: dict[str, list[str]] = {key: [] for key in units}
    exceptions: dict[str, list[str]] = {key: [] for key in units}
    attached_conditions = set()
    for edge in state["relations"]:
        source, target = edge["source_unit"], edge["target_unit"]
        if edge["relation_type"] == "modifies":
            conditions[target].append(source)
            attached_conditions.add(source)
        elif edge["relation_type"] == "overrides":
            overrides[source].append(target)
            exceptions[target].append(source)

    def statement(key: str) -> dict[str, Any]:
        unit = units[key]
        return {
            "unit_id": key, "text": unit["text"],
            **({"assertion": copy.deepcopy(unit["assertion"])} if "assertion" in unit else {}),
        }

    project_time = include_temporal or query_time is not None or version_time is not None or any(
        "applicability" in (unit.get("assertion") or {}) for unit in units.values()
    )

    def qualified(key: str) -> dict[str, Any]:
        unit = units[key]
        bound = [units[c] for c in conditions[key]]
        result = {**statement(key), "applies_under": [statement(c) for c in conditions[key]]}
        if project_time:
            declared = (unit.get("assertion") or {}).get("applicability") or {}
            result.update(
                temporal=_temporal_view(unit, bound, query_time, version_time,
                                        query_calendar_context),
                declared_scope=declared.get("scope"),
                scope_status="requires_source_interpretation" if bound or declared.get("scope")
                else "not_declared",
                quantity_scope=declared.get("quantity_scope", "unspecified"),
                semantic_support="unchecked",
            )
            if "evidence_links" in (unit.get("assertion") or {}):
                result["evidence_status"] = evidence_status(unit["assertion"])
            if declared.get("quantity_scope") == "overall":
                result["member_quantities"] = "not_implied_by_overall_total"
        return result

    result = {}
    for key, unit in units.items():
        if unit["role"] == "condition":
            result[key] = {**(qualified(key) if project_time else statement(key)),
                           "kind": "bound_condition"
                           if key in attached_conditions else "unbound_condition"}
            continue
        is_exception = bool(overrides[key] or unit.get("local_exception"))
        result[key] = {
            **qualified(key),
            "kind": "scoped_exception" if is_exception else
                    "general_rule" if exceptions[key] else "assertion",
            "general_rules": [qualified(target) for target in overrides[key]],
            "exceptions": [qualified(target) for target in exceptions[key]],
        }
        if is_exception:
            result[key]["general_rule_status"] = "stored" if overrides[key] else "not_stored"
    return result


def render_revision_view(
    state: dict[str, Any],
    *,
    query_time: str | None = None,
    version_time: str | None = None,
    query_calendar_context: str | None = None,
) -> dict[str, Any]:
    """One deterministic current/history view for ordinary Host and benchmark readers.

    No newest-report winner is chosen among separate scopes. Even a time-eligible
    explicit override requires its actual conditions; cancellation only removes
    edges and cannot alter an expired general rule's independently stored limit.
    """
    projected = read_applicability(
        state, query_time=query_time, version_time=version_time,
        query_calendar_context=query_calendar_context, include_temporal=True,
    )
    units = {unit["unit_id"]: unit for unit in state["units"]}
    ineligible = {"expired", "before_explicit_start", "inconsistent_explicit_limits"}
    relations = []
    for edge in state["relations"]:
        statuses = [
            projected[key].get("temporal", {}).get("status", "effective_limits_unspecified")
            for key in (edge["source_unit"], edge["target_unit"])
        ]
        relations.append({
            **copy.deepcopy(edge),
            "applicability": "time_ineligible" if any(s in ineligible for s in statuses)
            else "requires_source_interpretation",
        })
    common_conditions = [
        key for key, unit in units.items() if unit["role"] == "condition" and len({
            edge["target_unit"] for edge in state["relations"]
            if edge["relation_type"] == "modifies" and edge["source_unit"] == key
        }) > 1
    ]
    # Every actual unit appears once. Relations and scope lists point to it;
    # different source roles are retained once in the source table rather than
    # repeatedly copying a whole assertion into every attached condition view.
    source_table = {}
    compact_units = []
    for item in projected.values():
        compact = copy.deepcopy(item)
        for field in ("applies_under", "general_rules", "exceptions"):
            if field in compact:
                compact[field] = [statement["unit_id"] for statement in compact[field]]
        assertion = compact.get("assertion") or {}
        sources = [assertion] if "source_ref" in assertion else []
        for linked in assertion.get("evidence_links", {}).values():
            sources.extend(linked)
        for source in sources:
            source_table[source["source_ref"]] = {
                key: source.get(key) for key in (
                    "source_revision", "role", "occurred_at", "observed_at"
                )
            }
            if "calendar_context" in source:
                source_table[source["source_ref"]]["calendar_context"] = source["calendar_context"]
            clocks = {
                "reported_at": _declared_time(source.get("occurred_at"),
                                               calendar_context=source.get("calendar_context")),
                "captured_at": _declared_time(source.get("observed_at")),
            }
            source_table[source["source_ref"]]["time_values"] = {
                key: parsed.describe() for key, parsed in clocks.items() if parsed is not None
            }
        # Shared clock descriptions appear once; semantic event/limit precision
        # stays on the unit. Raw legacy temporal fields retain their public shape.
        clocks = compact["temporal"]["time_values"]
        for key in ("query_time", "version_time", *(
            ("reported_at", "captured_at") if "source_ref" in assertion else ()
        )):
            clocks.pop(key, None)
        if not clocks:
            compact["temporal"].pop("time_values")
        if "evidence_links" in assertion:
            assertion["evidence_links"] = {
                stance: [{key: ref[key] for key in
                          ("evidence_id", "source_ref", "source_revision", "start", "end")}
                         for ref in linked]
                for stance, linked in assertion["evidence_links"].items()
            }
        compact_units.append(compact)
    clocks = {"query_time": _declared_time(query_time, calendar_context=query_calendar_context),
              "version_time": _declared_time(version_time)}
    return {
        "representation": state["representation"],
        "matter": state.get("matter_description"),
        "query_time": query_time,
        "query_calendar_context": query_calendar_context,
        "calendar_context_semantics": "nominal_coordinate_only; does_not_establish_timezone",
        "version_time": version_time,
        "time_values": {key: parsed.describe() for key, parsed in clocks.items()
                        if parsed is not None},
        "units": compact_units,
        "source_table": source_table,
        "relations": relations,
        "common_conditions": common_conditions,
        "historical_units": [
            key for key, item in projected.items()
            if item.get("temporal", {}).get("status") == "expired"
        ],
        "future_units": [
            key for key, item in projected.items()
            if item.get("temporal", {}).get("status") == "before_explicit_start"
        ],
        "unresolved_units": [
            key for key, item in projected.items()
            if item["kind"] == "unbound_condition"
            or item.get("general_rule_status") == "not_stored"
            or item.get("scope_status") == "requires_source_interpretation"
            or item.get("temporal", {}).get("status") in {
                "effective_limits_unspecified", "query_time_unresolved", "query_time_unspecified",
                "inconsistent_explicit_limits",
                "time_context_unresolved", "query_time_precision_unresolved",
                "explicit_time_unresolved",
            }
        ],
        "selection_policy": "actual_relations_and_explicit_limits; no last_report_wins",
        "completion_status": "not_inferred_from_time",
        "semantic_support": "unchecked",
    }


def render_state(
    state: dict[str, Any],
    *,
    query_time: str | None = None,
    version_time: str | None = None,
    query_calendar_context: str | None = None,
) -> str:
    """One renderer shared by B2/M; explicit scoped alternatives guide the common Reader."""

    def assertion_text(unit: dict[str, Any]) -> str:
        assertion = unit.get("assertion")
        if not assertion:
            return ""
        declared = assertion.get("applicability") or {}
        semantic = "".join(
            "; " + key + "=" + str(declared[key]) for key in
            ("event_at", "effective_from", "effective_until", "scope", "quantity_scope")
            if key in declared
        )
        if "evidence_links" in assertion:
            semantic += "; evidence_status=" + evidence_status(assertion)
        return str(
            " [Assertion: "
            + assertion["kind"]
            + "; speaker="
            + assertion["role"]
            + ("; occurred_at=" + assertion["occurred_at"] if assertion.get("occurred_at") else "")
            + semantic + "]"
        )

    applicability = read_applicability(
        state, query_time=query_time, version_time=version_time,
        query_calendar_context=query_calendar_context,
    )

    def temporal_text(unit: dict[str, Any]) -> str:
        if query_time is None:
            return ""
        item = applicability[unit["unit_id"]]
        status = item["temporal"]["status"]
        return " [Time: " + str(status) + "; scope remains evidence-dependent]"

    matter = (
        ["Matter: " + state["matter_description"]]
        if state.get("matter_description") and state["units"]
        else []
    )
    if state["representation"] == "plain_v1":
        return "\n".join(
            [*matter, *(unit["text"] + assertion_text(unit) + temporal_text(unit)
                       for unit in state["units"])]
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
            else "Scoped exception (general rule not stored): "
            if unit.get("local_exception")
            else "General content (outside explicit override scopes): "
            if unit_id in overrides.values()
            else "Content: "
        )
        lines.append(
            unit_id + " — " + prefix + unit["text"] + assertion_text(unit) + temporal_text(unit)
        )
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
        if not view:
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
                if not view:
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
        {k: copy.deepcopy(v) for k, v in by_key[key].items() if view or k != "role"}
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
    """Group actual rules while preserving aliases and service-owned unit roles."""
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


def writer_proposal_schema(
    arm: str, *, allow_create: bool = True, for_generation: bool = False
) -> dict[str, Any]:
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
                if for_generation:
                    # Preserve old decoding/rejection; constrain only new output
                    # to the content/condition operation the executor accepts.
                    fields["role"] = {"const": "content"}
                    fields["attach_to"] = {"type": "array", "maxItems": 0}
                    edits.append(obj(fields, required))
                    fields = {**fields, "role": {"const": "condition"}, "attach_to": refs("u")}
                    required = [*required, "role"]
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
                if "calendar_context" in row:
                    attributes[-1]["calendar_context"] = row["calendar_context"]
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
                    if (
                        features.get("temporal_scope") and assertion
                        and "applicability" in assertion
                    ):
                        public_units[-1]["assertion"]["applicability"] = copy.deepcopy(
                            assertion["applicability"]
                        )
                    if (features.get("temporal_scope") and assertion
                            and "evidence_links" in assertion):
                        public_units[-1]["assertion"]["evidence_status"] = evidence_status(
                            assertion
                        )
                        public_units[-1]["assertion"]["evidence_links"] = {
                            stance: [{"source": source_id(ref),
                                      "range": [ref["start"], ref["end"]]}
                                     for ref in linked]
                            for stance, linked in assertion["evidence_links"].items()
                        }

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
        if features and features.get("temporal_scope"):
            public_record["version_time"] = record.get("version_time")
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
