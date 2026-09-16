from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

CapabilityShape = Literal[
    "ENUMERATION",
    "COUNTING",
    "SAME_TYPE_DIFFERENT_INSTANCE",
    "REPEATED_MENTION",
    "CROSS_SESSION_AGGREGATION",
    "UPDATE_COLLECTION",
    "CONTINUATION",
]

CAPABILITY_SHAPES: tuple[CapabilityShape, ...] = (
    "ENUMERATION",
    "COUNTING",
    "SAME_TYPE_DIFFERENT_INSTANCE",
    "REPEATED_MENTION",
    "CROSS_SESSION_AGGREGATION",
    "UPDATE_COLLECTION",
    "CONTINUATION",
)

CandidateOrigin = Literal["PERSISTED_FRONTIER", "RESIDUAL_ACQUISITION"]
DiscoveryDisposition = Literal["DIRECT_ANCHOR", "HYDRATION_ONLY"]


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class InstanceGroup:
    group_id: str
    acceptable_evidence_ids: tuple[str, ...]
    acceptable_turn_refs: tuple[str, ...]
    source_ids: tuple[str, ...]
    session_ids: tuple[str, ...]
    required_for_answer: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> InstanceGroup:
        group_id = _nonempty_string(value.get("group_id"), "group_id")
        evidence_ids = _unique_strings(value.get("acceptable_evidence_ids", []))
        turn_refs = _unique_strings(value.get("acceptable_turn_refs", []))
        source_ids = _unique_strings(value.get("source_ids", []))
        session_ids = _unique_strings(value.get("session_ids", []))
        required = value.get("required_for_answer")
        if not isinstance(required, bool):
            raise ValueError("required_for_answer must be Boolean")
        if required and not evidence_ids and not turn_refs:
            raise ValueError(f"required group {group_id} has no acceptable exact identity")
        return cls(
            group_id=group_id,
            acceptable_evidence_ids=evidence_ids,
            acceptable_turn_refs=turn_refs,
            source_ids=source_ids,
            session_ids=session_ids,
            required_for_answer=required,
        )


def validate_source_fixture(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != "milai-product11-opened-dev-v0.1":
        raise ValueError("Product-11 source fixture schema is invalid")
    if value.get("classification") != "OPENED_DEVELOPMENT_ONLY":
        raise ValueError("Product-11 source fixture is not opened-development-only")
    if value.get("formal_source") is not False:
        raise ValueError("Product-11 source fixture must explicitly reject Formal provenance")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError("Product-11 source fixture must contain exactly 24 cases")
    case_ids: list[str] = []
    turn_refs: set[str] = set()
    capability_counts: Counter[str] = Counter()
    stratum_counts: Counter[str] = Counter()
    forbidden = {
        "reference_answer",
        "expected_answer",
        "gold_quote",
        "instance_groups",
        "acceptable_evidence_ids",
        "acceptable_turn_refs",
    }
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("Product-11 source fixture case is not an object")
        if forbidden.intersection(_recursive_keys(raw_case)):
            raise ValueError("Product-11 source fixture contains scorer-only labels")
        case_id = _nonempty_string(raw_case.get("case_id"), "case_id")
        case_ids.append(case_id)
        _nonempty_string(raw_case.get("question"), "question")
        shapes = _capability_shapes(raw_case.get("capability_shapes"), case_id=case_id)
        capability_counts.update(shapes)
        stratum = _nonempty_string(raw_case.get("intended_stratum"), "intended_stratum")
        if stratum not in {"CONTINUATION", "INTRA_SOURCE", "CONTROL"}:
            raise ValueError(f"case {case_id} has an invalid intended stratum")
        stratum_counts[stratum] += 1
        sessions = raw_case.get("sessions")
        if not isinstance(sessions, list) or not sessions:
            raise ValueError(f"case {case_id} has no sessions")
        for session in sessions:
            if not isinstance(session, Mapping):
                raise ValueError(f"case {case_id} session is not an object")
            _nonempty_string(session.get("source_id"), "source_id")
            _nonempty_string(session.get("session_id"), "session_id")
            turns = session.get("turns")
            if not isinstance(turns, list) or not turns:
                raise ValueError(f"case {case_id} has an empty session")
            for turn in turns:
                if not isinstance(turn, Mapping):
                    raise ValueError(f"case {case_id} turn is not an object")
                turn_ref = _nonempty_string(turn.get("turn_ref"), "turn_ref")
                _nonempty_string(turn.get("text"), "text")
                if turn_ref in turn_refs:
                    raise ValueError(f"turn ref {turn_ref} is not globally unique")
                turn_refs.add(turn_ref)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Product-11 source fixture case IDs are not unique")
    missing_shapes = {
        shape: capability_counts[shape]
        for shape in CAPABILITY_SHAPES
        if capability_counts[shape] < 3
    }
    if missing_shapes:
        raise ValueError(f"Product-11 capability coverage is insufficient: {missing_shapes}")
    missing_strata = {
        stratum: stratum_counts[stratum]
        for stratum in ("CONTINUATION", "INTRA_SOURCE", "CONTROL")
        if stratum_counts[stratum] < 8
    }
    if missing_strata:
        raise ValueError(f"Product-11 intended strata are insufficient: {missing_strata}")
    return {
        "case_count": len(case_ids),
        "case_order_sha256": canonical_sha256(case_ids),
        "capability_counts": dict(sorted(capability_counts.items())),
        "intended_stratum_counts": dict(sorted(stratum_counts.items())),
        "turn_ref_count": len(turn_refs),
    }


def validate_human_seal(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    require_opportunity_gate: bool = True,
) -> dict[str, Any]:
    fixture_summary = validate_source_fixture(fixture)
    if len(rows) != 25:
        raise ValueError("Product-11 human seal requires one manifest and 24 case rows")
    header = rows[0]
    if (
        header.get("record_type") != "manifest"
        or header.get("schema_version") != "milai-product11-human-instance-groups-v0.1"
        or header.get("human_adjudication_status") != "COMPLETE"
        or header.get("model_assisted_proxy") is not False
        or header.get("formal_files_accessed") is not False
        or header.get("formal_cases_scored") != 0
    ):
        raise ValueError("Product-11 human seal manifest is invalid")
    fixture_cases = fixture["cases"]
    fixture_case_ids = [str(case["case_id"]) for case in fixture_cases]
    label_case_ids = [_nonempty_string(row.get("case_id"), "case_id") for row in rows[1:]]
    if label_case_ids != fixture_case_ids:
        raise ValueError("Product-11 human seal case order does not match source fixture")
    continuation_opportunities = 0
    intra_source_opportunities = 0
    controls = 0
    capability_counts: Counter[str] = Counter()
    group_count = 0
    for source_case, row in zip(fixture_cases, rows[1:], strict=True):
        case_id = str(source_case["case_id"])
        if row.get("human_adjudication_status") != "COMPLETE":
            raise ValueError(f"case {case_id} is not human-adjudication COMPLETE")
        if row.get("model_assisted_proxy") is not False:
            raise ValueError(f"case {case_id} still has model-assisted proxy status")
        annotator = _human_attestation(row.get("annotator"), role="annotator")
        reviewer = _human_attestation(row.get("reviewer"), role="reviewer")
        if annotator == reviewer:
            raise ValueError(f"case {case_id} annotator and reviewer are not independent")
        groups = _validate_groups(row, source_case=source_case)
        group_count += len([group for group in groups if group.required_for_answer])
        shapes = _capability_shapes(row.get("capability_shapes"), case_id=case_id)
        if tuple(shapes) != tuple(source_case["capability_shapes"]):
            raise ValueError(f"case {case_id} capability shapes drifted from the source fixture")
        capability_counts.update(shapes)
        continuation = row.get("continuation_opportunity")
        intra_source = row.get("intra_source_opportunity")
        control = row.get("control_or_already_complete")
        if not all(isinstance(value, bool) for value in (continuation, intra_source, control)):
            raise ValueError(f"case {case_id} opportunity fields must be Boolean")
        continuation_opportunities += bool(continuation)
        intra_source_opportunities += bool(intra_source)
        controls += bool(control)
    opportunity_gate_passed = (
        continuation_opportunities >= 8
        and intra_source_opportunities >= 8
        and controls >= 8
    )
    if require_opportunity_gate and not opportunity_gate_passed:
        raise ValueError("Product-11 human-sealed opportunity/control counts are insufficient")
    missing_shapes = {
        shape: capability_counts[shape]
        for shape in CAPABILITY_SHAPES
        if capability_counts[shape] < 3
    }
    if missing_shapes:
        raise ValueError(
            f"Product-11 human seal capability coverage is insufficient: {missing_shapes}"
        )
    return {
        **fixture_summary,
        "group_count": group_count,
        "continuation_opportunity_count": continuation_opportunities,
        "intra_source_opportunity_count": intra_source_opportunities,
        "control_or_already_complete_count": controls,
        "human_adjudication_complete_count": 24,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "opportunity_gate_passed": opportunity_gate_passed,
        "status": (
            "PASS_PRODUCT11_X0_HUMAN_SEAL"
            if opportunity_gate_passed
            else "COMPLETE_PRODUCT11_HUMAN_ADJUDICATION_OPPORTUNITY_INSUFFICIENT"
        ),
    }


def distinct_instance_coverage(
    groups: Sequence[InstanceGroup],
    *,
    visible_evidence_ids: Sequence[str],
    visible_turn_refs: Sequence[str],
) -> dict[str, int | float]:
    required = [group for group in groups if group.required_for_answer]
    if not required:
        raise ValueError("DistinctInstanceCoverage requires required groups")
    evidence = set(visible_evidence_ids)
    turns = set(visible_turn_refs)
    numerator = sum(
        bool(evidence.intersection(group.acceptable_evidence_ids))
        or bool(turns.intersection(group.acceptable_turn_refs))
        for group in required
    )
    return {
        "numerator": numerator,
        "denominator": len(required),
        "value": numerator / len(required),
    }


def direct_acquisition_coverage(
    groups: Sequence[InstanceGroup],
    *,
    direct_evidence_ids: Sequence[str],
    direct_turn_refs: Sequence[str],
) -> dict[str, int | float]:
    return distinct_instance_coverage(
        groups,
        visible_evidence_ids=direct_evidence_ids,
        visible_turn_refs=direct_turn_refs,
    )


def duplicate_instance_rate(
    groups: Sequence[InstanceGroup],
    *,
    visible_evidence_ids: Sequence[str],
    visible_turn_refs: Sequence[str],
) -> dict[str, int | float | bool | None]:
    evidence = set(visible_evidence_ids)
    turns = set(visible_turn_refs)
    counts = [
        len(evidence.intersection(group.acceptable_evidence_ids))
        + len(turns.intersection(group.acceptable_turn_refs))
        for group in groups
        if group.required_for_answer
    ]
    denominator = sum(counts)
    numerator = sum(max(0, count - 1) for count in counts)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "empty_eligible_set": denominator == 0,
    }


def continuation_instance_gain(
    groups: Sequence[InstanceGroup],
    *,
    call1_evidence_ids: Sequence[str],
    call1_turn_refs: Sequence[str],
    call2_evidence_ids: Sequence[str],
    call2_turn_refs: Sequence[str],
) -> float:
    before = distinct_instance_coverage(
        groups,
        visible_evidence_ids=call1_evidence_ids,
        visible_turn_refs=call1_turn_refs,
    )
    after = distinct_instance_coverage(
        groups,
        visible_evidence_ids=tuple(dict.fromkeys((*call1_evidence_ids, *call2_evidence_ids))),
        visible_turn_refs=tuple(dict.fromkeys((*call1_turn_refs, *call2_turn_refs))),
    )
    return float(after["value"]) - float(before["value"])


def classify_x0_opportunity(
    groups: Sequence[InstanceGroup],
    *,
    visible_evidence_ids: Sequence[str],
    visible_turn_refs: Sequence[str],
    direct_evidence_ids: Sequence[str],
    direct_turn_refs: Sequence[str],
    frontier_evidence_ids: Sequence[str],
    frontier_turn_refs: Sequence[str],
    selected_coarse_source_ids: Sequence[str],
    selected_coarse_session_ids: Sequence[str],
) -> dict[str, bool]:
    """Apply the frozen Product-11 treatment-blind opportunity definitions."""

    required = [group for group in groups if group.required_for_answer]
    visible = distinct_instance_coverage(
        required,
        visible_evidence_ids=visible_evidence_ids,
        visible_turn_refs=visible_turn_refs,
    )
    direct_evidence = set(direct_evidence_ids)
    direct_turns = set(direct_turn_refs)
    frontier_evidence = set(frontier_evidence_ids)
    frontier_turns = set(frontier_turn_refs)
    coarse_sources = set(selected_coarse_source_ids)
    coarse_sessions = set(selected_coarse_session_ids)
    continuation = float(visible["value"]) < 1.0 and any(
        bool(frontier_evidence.intersection(group.acceptable_evidence_ids))
        or bool(frontier_turns.intersection(group.acceptable_turn_refs))
        for group in required
    )
    intra_source = any(
        not (
            direct_evidence.intersection(group.acceptable_evidence_ids)
            or direct_turns.intersection(group.acceptable_turn_refs)
        )
        and (
            bool(coarse_sources.intersection(group.source_ids))
            or bool(coarse_sessions.intersection(group.session_ids))
        )
        for group in required
    )
    return {
        "continuation_opportunity": continuation,
        "intra_source_opportunity": intra_source,
        "control_or_already_complete": float(visible["value"]) == 1.0,
    }


def validate_x0_opportunity_assignments(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    trace_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute human-row opportunity flags from the immutable treatment-blind A0 trace."""

    derived = derive_x0_opportunity_assignments(fixture, rows, trace_rows)
    raw_assignments = derived.get("case_assignments")
    if not isinstance(raw_assignments, Mapping):
        raise ValueError("Product-11 opportunity derivation returned invalid assignments")
    label_by_id = {str(row.get("case_id")): row for row in rows[1:]}
    counts: Counter[str] = Counter()
    for raw_case_id, observed in raw_assignments.items():
        case_id = str(raw_case_id)
        if not isinstance(observed, Mapping):
            raise ValueError(f"case {case_id} opportunity assignment is invalid")
        label = label_by_id[case_id]
        for key, value in observed.items():
            if not isinstance(key, str) or not isinstance(value, bool):
                raise ValueError(f"case {case_id} opportunity assignment is invalid")
            if label.get(key) is not value:
                raise ValueError(f"case {case_id} {key} disagrees with frozen A0 trace")
            counts[key] += 1 if value else 0
    return {
        "continuation_opportunity_count": counts["continuation_opportunity"],
        "intra_source_opportunity_count": counts["intra_source_opportunity"],
        "control_or_already_complete_count": counts["control_or_already_complete"],
        "opportunity_assignments_match_a0_trace": True,
    }


def derive_x0_opportunity_assignments(
    fixture: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    trace_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive per-case X0 opportunity fields without trusting human-entered flags."""

    if len(rows) != 25 or len(trace_rows) != 24:
        raise ValueError("Product-11 opportunity validation requires 24 label and trace cases")
    fixture_cases = fixture.get("cases")
    if not isinstance(fixture_cases, list) or len(fixture_cases) != 24:
        raise ValueError("Product-11 opportunity fixture is invalid")
    label_by_id = {str(row.get("case_id")): row for row in rows[1:]}
    trace_by_id = {str(row.get("case_id")): row for row in trace_rows}
    case_ids = [str(case["case_id"]) for case in fixture_cases]
    if list(label_by_id) != case_ids or list(trace_by_id) != case_ids:
        raise ValueError("Product-11 opportunity validation case order drifted")
    assignments: dict[str, dict[str, bool]] = {}
    for source_case in fixture_cases:
        case_id = str(source_case["case_id"])
        label = label_by_id[case_id]
        trace = trace_by_id[case_id]
        if trace.get("status") != "TRACE_COMPLETE":
            raise ValueError(f"case {case_id} A0 trace is incomplete")
        groups = _validate_groups(label, source_case=source_case)
        identity_sets = trace.get("identity_sets")
        if not isinstance(identity_sets, Mapping):
            raise ValueError(f"case {case_id} A0 identity sets are absent")
        visible_evidence = _unique_strings(identity_sets.get("rendered_evidence_ids", []))
        visible_turns = _unique_strings(identity_sets.get("rendered_turn_refs", []))
        direct_evidence = _unique_strings(identity_sets.get("post_identity_evidence_ids", []))
        direct_turns = _unique_strings(identity_sets.get("post_identity_turn_refs", []))
        raw_evidence = _unique_strings(identity_sets.get("raw_evidence_ids", []))
        raw_turns = _unique_strings(identity_sets.get("raw_turn_refs", []))
        frontier_evidence = tuple(sorted(set(raw_evidence).difference(visible_evidence)))
        frontier_turns = tuple(sorted(set(raw_turns).difference(visible_turns)))
        ref_to_scope = {
            str(turn["turn_ref"]): (str(session["source_id"]), str(session["session_id"]))
            for session in source_case["sessions"]
            for turn in session["turns"]
        }
        coarse_refs = set(direct_turns).union(visible_turns)
        coarse_sources = tuple(
            sorted({ref_to_scope[ref][0] for ref in coarse_refs if ref in ref_to_scope})
        )
        coarse_sessions = tuple(
            sorted({ref_to_scope[ref][1] for ref in coarse_refs if ref in ref_to_scope})
        )
        observed = classify_x0_opportunity(
            groups,
            visible_evidence_ids=visible_evidence,
            visible_turn_refs=visible_turns,
            direct_evidence_ids=direct_evidence,
            direct_turn_refs=direct_turns,
            frontier_evidence_ids=frontier_evidence,
            frontier_turn_refs=frontier_turns,
            selected_coarse_source_ids=coarse_sources,
            selected_coarse_session_ids=coarse_sessions,
        )
        assignments[case_id] = observed
    return {
        "case_assignments": assignments,
        "derivation_source": "FROZEN_A0_TRACE",
    }


def validate_a0_trace_seal(trace_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate the label-blind Product-11 A0 trace boundary."""

    snapshots = {str(row.get("source_snapshot_as_of")) for row in trace_rows}
    if len(trace_rows) != 24 or len(snapshots) != 1:
        raise ValueError("Product-11 A0 trace seal is incomplete or snapshot-divergent")
    case_ids: list[str] = []
    for row in trace_rows:
        case_id = _nonempty_string(row.get("case_id"), "case_id")
        case_ids.append(case_id)
        invariants = row.get("invariants")
        if (
            row.get("schema_version") != "milai-product11-x0-a0-case-trace-v0.1"
            or row.get("status") != "TRACE_COMPLETE"
            or not isinstance(invariants, Mapping)
            or invariants.get("labels_loaded") is not False
            or invariants.get("label_fields_present") is not False
            or invariants.get("canonical_mutation") is not False
            or invariants.get("cross_namespace_source_count") != 0
        ):
            raise ValueError("Product-11 A0 trace seal invariant failed")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Product-11 A0 trace case IDs are not unique")
    return {
        "case_count": len(case_ids),
        "case_order_sha256": canonical_sha256(case_ids),
        "source_snapshot_as_of": next(iter(snapshots)),
        "labels_loaded": False,
        "canonical_mutation": False,
    }


def _validate_groups(
    value: Mapping[str, Any], *, source_case: Mapping[str, Any]
) -> tuple[InstanceGroup, ...]:
    raw_groups = value.get("instance_groups")
    case_id = str(source_case["case_id"])
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError(f"case {case_id} has no instance groups")
    groups = tuple(
        InstanceGroup.from_mapping(group) for group in raw_groups if isinstance(group, Mapping)
    )
    if len(groups) != len(raw_groups) or len({group.group_id for group in groups}) != len(groups):
        raise ValueError(f"case {case_id} has invalid group cardinality")
    valid_turn_refs = {
        str(turn["turn_ref"]) for session in source_case["sessions"] for turn in session["turns"]
    }
    valid_sources = {str(session["source_id"]) for session in source_case["sessions"]}
    valid_sessions = {str(session["session_id"]) for session in source_case["sessions"]}
    seen_evidence: set[str] = set()
    seen_turns: set[str] = set()
    for group in groups:
        if not set(group.acceptable_turn_refs).issubset(valid_turn_refs):
            raise ValueError(f"case {case_id} group references a turn outside the source fixture")
        if not set(group.source_ids).issubset(valid_sources):
            raise ValueError(f"case {case_id} group references an unknown source")
        if not set(group.session_ids).issubset(valid_sessions):
            raise ValueError(f"case {case_id} group references an unknown session")
        if not group.required_for_answer:
            continue
        if seen_evidence.intersection(group.acceptable_evidence_ids):
            raise ValueError(f"case {case_id} has cross-group Evidence overlap")
        if seen_turns.intersection(group.acceptable_turn_refs):
            raise ValueError(f"case {case_id} has cross-group turn overlap")
        seen_evidence.update(group.acceptable_evidence_ids)
        seen_turns.update(group.acceptable_turn_refs)
    return groups


def _capability_shapes(value: object, *, case_id: str) -> tuple[str, ...]:
    shapes = _unique_strings(value)
    if not shapes or any(shape not in CAPABILITY_SHAPES for shape in shapes):
        raise ValueError(f"case {case_id} has invalid capability shapes")
    return shapes


def _human_attestation(value: object, *, role: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"{role} attestation is absent")
    if value.get("kind") != "HUMAN":
        raise ValueError(f"{role} must attest as HUMAN")
    identity = _nonempty_string(value.get("id"), f"{role}.id")
    _nonempty_string(value.get("signed_at"), f"{role}.signed_at")
    _nonempty_string(value.get("attestation"), f"{role}.attestation")
    return identity


def _unique_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("expected a list of non-empty strings")
    items = tuple(value)
    if len(items) != len(set(items)):
        raise ValueError("string identities must be unique")
    return items


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value}.union(
            *(_recursive_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value)) if value else set()
    return set()


__all__ = [
    "CAPABILITY_SHAPES",
    "CandidateOrigin",
    "DiscoveryDisposition",
    "InstanceGroup",
    "canonical_sha256",
    "continuation_instance_gain",
    "direct_acquisition_coverage",
    "distinct_instance_coverage",
    "duplicate_instance_rate",
    "validate_human_seal",
    "validate_source_fixture",
]
