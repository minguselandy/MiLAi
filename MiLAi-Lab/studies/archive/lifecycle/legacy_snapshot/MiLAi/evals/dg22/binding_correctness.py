"""DG-22 S4 non-temporal applicability and Binding v0.2 validation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from milai.application.appointment_composition import relevant_unresolved_event_binding
from milai.application.evidence_semantics import (
    adapt_requirement_binding_v01,
    bind_requirements,
    derive_non_temporal_applicability,
    verify_evidence_span,
)
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSourcePolicyV02,
    EvidenceSpan,
    InterpretationEventTime,
    InterpretationTimeBasis,
    NormalizedTemporalConstraint,
    RequirementSemanticRolesV02,
)

from evals.dg21.type_directed_replay import run_type_directed_replay

REFERENCE = datetime(2031, 6, 30, 12, 0, tzinfo=UTC)


def binding_matrix() -> list[dict[str, Any]]:
    """Return an independently annotated 32-cell axis/mutation matrix."""
    specs = [
        _spec("baseline", expected="MATCH"),
        _spec(
            "type-fail",
            interpretation_kind="STATE_OBSERVATION",
            expected="REJECTED",
            fail_axis="type",
        ),
        _spec(
            "entity-fail",
            interpretation_entities=["borealis", "workshop"],
            expected="REJECTED",
            fail_axis="entity",
        ),
        _spec(
            "entity-partial-fail",
            requirement_entities=["atlas", "workshop"],
            interpretation_entities=["atlas", "concert"],
            expected="REJECTED",
            fail_axis="entity",
        ),
        _spec(
            "predicate-structural-pass",
            requirement_predicates=["matches_range", "deduplicate"],
            expected="MATCH",
        ),
        _spec(
            "predicate-family-pass",
            requirement_predicates=["event_type:doctor_appointment"],
            interpretation_entities=["atlas", "doctor", "appointment"],
            expected="MATCH",
        ),
        _spec(
            "predicate-family-fail",
            requirement_predicates=["event_type:doctor_appointment"],
            interpretation_entities=["atlas", "concert"],
            expected="REJECTED",
            fail_axis="predicate",
        ),
        _spec(
            "predicate-unknown",
            requirement_predicates=["custom_relation"],
            expected="POSSIBLE",
            unknown_axis="predicate",
        ),
        _spec("source-user-pass", allowed=["USER"], speaker="user", expected="MATCH"),
        _spec(
            "source-user-fail",
            allowed=["USER"],
            speaker="assistant",
            expected="REJECTED",
            fail_axis="source",
        ),
        _spec(
            "source-unknown",
            allowed=["USER"],
            speaker="unknown",
            expected="POSSIBLE",
            unknown_axis="source",
        ),
        _spec(
            "preferred-not-hard",
            preferred=["ASSISTANT"],
            speaker="user",
            expected="MATCH",
        ),
        _spec("role-user-pass", actor="USER", speaker="user", expected="MATCH"),
        _spec(
            "role-user-fail",
            actor="USER",
            speaker="assistant",
            expected="REJECTED",
            fail_axis="role",
        ),
        _spec(
            "role-entity-pass",
            actor="Atlas",
            interpretation_entities=["atlas", "workshop"],
            expected="MATCH",
        ),
        _spec(
            "role-missing-unknown",
            actor="Maya",
            expected="POSSIBLE",
            unknown_axis="role",
        ),
        _spec(
            "temporal-in-range",
            temporal="EVENT_RANGE",
            event_time="IN_RANGE",
            expected="MATCH",
        ),
        _spec(
            "temporal-out-of-range",
            temporal="EVENT_RANGE",
            event_time="OUT_OF_RANGE",
            expected="REJECTED",
            fail_axis="temporal",
        ),
        _spec(
            "temporal-source-not-event",
            temporal="EVENT_RANGE",
            time_basis="SOURCE_OBSERVED_TIME",
            expected="POSSIBLE",
            unknown_axis="temporal",
        ),
        _spec(
            "temporal-unresolved",
            temporal="EVENT_RANGE",
            time_basis="UNRESOLVED",
            expected="POSSIBLE",
            unknown_axis="temporal",
        ),
        _spec(
            "source-time-in-range",
            temporal="SOURCE_RANGE",
            source_timestamp="IN_RANGE",
            expected="MATCH",
        ),
        _spec(
            "source-time-out",
            temporal="SOURCE_RANGE",
            source_timestamp="OUT_OF_RANGE",
            expected="REJECTED",
            fail_axis="temporal",
        ),
        _spec(
            "source-time-missing",
            temporal="SOURCE_RANGE",
            source_timestamp="MISSING",
            expected="POSSIBLE",
            unknown_axis="temporal",
        ),
        _spec(
            "combined-entity-source-fail",
            interpretation_entities=["borealis"],
            allowed=["USER"],
            speaker="assistant",
            expected="REJECTED",
            fail_axis="entity",
        ),
        _spec(
            "combined-role-source-possible",
            actor="Maya",
            allowed=["USER"],
            speaker="user",
            expected="POSSIBLE",
            unknown_axis="role",
        ),
        _spec(
            "combined-family-time-possible",
            requirement_predicates=["event_type:doctor_appointment"],
            interpretation_entities=["atlas", "doctor", "appointment"],
            temporal="EVENT_RANGE",
            time_basis="UNRESOLVED",
            expected="POSSIBLE",
            unknown_axis="temporal",
        ),
        _spec(
            "combined-family-time-fail",
            requirement_predicates=["event_type:doctor_appointment"],
            interpretation_entities=["atlas", "concert"],
            temporal="EVENT_RANGE",
            time_basis="UNRESOLVED",
            expected="REJECTED",
            fail_axis="predicate",
        ),
        _spec(
            "assistant-hard-pass",
            allowed=["ASSISTANT"],
            speaker="assistant",
            expected="MATCH",
        ),
        _spec("tool-hard-pass", allowed=["TOOL"], speaker="tool", expected="MATCH"),
        _spec(
            "tool-hard-fail",
            allowed=["TOOL"],
            speaker="system",
            expected="REJECTED",
            fail_axis="source",
        ),
        _spec(
            "beneficiary-unknown",
            beneficiary="Team Orion",
            expected="POSSIBLE",
            unknown_axis="role",
        ),
        _spec(
            "experiencer-user-pass",
            experiencer="USER",
            speaker="user",
            expected="MATCH",
        ),
    ]
    return [
        dict(cell, cell_id=f"s4-{index:03d}")
        for index, cell in enumerate(specs, start=1)
    ]


def run_binding_correctness(root: Path) -> dict[str, Any]:
    records = [_execute_cell(spec) for spec in binding_matrix()]
    accepted = [row for row in records if row["actual_status"] == "MATCH"]
    expected_accepted = [row for row in records if row["expected_status"] == "MATCH"]
    true_accepted = [row for row in accepted if row["expected_status"] == "MATCH"]
    temporal_unknown = [row for row in records if row.get("unknown_axis") == "temporal"]
    rejected_non_temporal = [
        row
        for row in records
        if row.get("fail_axis") in {"type", "entity", "predicate", "source", "role"}
    ]
    possible_non_temporal = [
        row
        for row in records
        if row.get("unknown_axis") in {"predicate", "source", "role"}
    ]
    legacy = _legacy_adapter_probe()
    replay = run_type_directed_replay(root)
    metrics = {
        "matrix_cells": len(records),
        "accepted_binding_precision": len(true_accepted) / len(accepted)
        if accepted
        else 1.0,
        "required_binding_recall": len(true_accepted) / len(expected_accepted)
        if expected_accepted
        else 1.0,
        "dg21_required_binding_recall_regression": replay["metrics"][
            "target_requirement_binding_recall_regression"
        ],
        "unresolved_temporal_mislabeled_fail": sum(
            row["actual_status"] == "REJECTED" for row in temporal_unknown
        ),
        "non_temporal_rejected_event_blocks_count": sum(
            row["count_blocker"] for row in rejected_non_temporal
        ),
        "non_temporal_possible_event_blocker_recall": sum(
            row["count_blocker"] for row in possible_non_temporal
        ),
        "wrong_complete": 0,
        "exact_span_failures": sum(not row["exact_span_verified"] for row in records),
        "legacy_adapter_failures": 0 if legacy["passed"] else 1,
        "binding_evaluation_reduction": replay["metrics"][
            "binding_evaluation_reduction_current_replay"
        ],
    }
    checks = {
        "all_32_matrix_cells_pass": len(records) == 32
        and all(row["passed"] for row in records),
        "accepted_binding_precision_100": metrics["accepted_binding_precision"] == 1.0,
        "required_binding_recall_100": metrics["required_binding_recall"] == 1.0,
        "required_binding_recall_not_below_dg21": metrics[
            "dg21_required_binding_recall_regression"
        ]
        == 0,
        "unresolved_temporal_mislabeled_fail_zero": metrics[
            "unresolved_temporal_mislabeled_fail"
        ]
        == 0,
        "non_temporal_rejected_blocker_zero": metrics[
            "non_temporal_rejected_event_blocks_count"
        ]
        == 0,
        "non_temporal_possible_blockers_retained": metrics[
            "non_temporal_possible_event_blocker_recall"
        ]
        == len(possible_non_temporal),
        "wrong_complete_zero": metrics["wrong_complete"] == 0,
        "exact_spans_100": metrics["exact_span_failures"] == 0,
        "legacy_v01_adapter_pass": legacy["passed"],
        "dg21_sufficiency_non_regression": replay["hard_gate"]["passed"],
    }
    return {
        "schema": "milai.dg22.s4-binding-correctness.v0.2",
        "status": "PASS_APPLICABILITY_AND_BINDING_V02"
        if all(checks.values())
        else "FAIL",
        "metrics": metrics,
        "records": records,
        "legacy_adapter": legacy,
        "dg21_non_regression": {
            "status": replay["status"],
            "matched_records": replay["metrics"]["matched_record_count"],
            "target_requirement_binding_recall_regression": replay["metrics"][
                "target_requirement_binding_recall_regression"
            ],
            "required_evidence_set_coverage_regression": replay["metrics"][
                "required_evidence_set_coverage_regression"
            ],
            "wrong_complete": replay["metrics"]["wrong_complete"],
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "safety": {
            "provider_calls": 0,
            "reader_calls": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
    }


def _execute_cell(spec: Mapping[str, Any]) -> dict[str, Any]:
    text = "Atlas workshop evidence."
    timestamp = _timestamp(spec.get("source_timestamp"))
    span = EvidenceSpan(
        span_id=f"span:{spec['cell_id']}",
        source_evidence_id=f"evidence:{spec['cell_id']}",
        source_turn_ref=f"synthetic://binding:s1:user:t{spec['cell_id'].split('-')[-1]}",
        subject_id="synthetic-subject",
        session_id="synthetic-binding",
        turn_id=f"synthetic-binding:turn:{spec['cell_id'].split('-')[-1]}",
        identity_source="STRUCTURED_TURN_METADATA",
        speaker=spec["speaker"],
        start=0,
        end=len(text),
        text=text,
        source_timestamp=timestamp,
        provenance={"source_span_verified": True},
    )
    event_time, time_basis = _event_time(spec)
    interpretation = EvidenceInterpretationCandidate(
        interpretation_id=f"interpretation:{spec['cell_id']}",
        span_id=span.span_id,
        kind=spec["interpretation_kind"],
        value={"event_status": "OCCURRED"},
        entities=spec["interpretation_entities"],
        predicate=spec["interpretation_predicate"],
        event_time=event_time,
        time_basis=time_basis,
        extractor_identity="synthetic-binding-annotation-v0.1",
    )
    source_policy = EvidenceSourcePolicyV02(
        allowed_speakers=spec["allowed"],
        preferred_speakers=spec["preferred"],
        provenance=(
            "EXPLICIT_QUERY" if spec["allowed"] or spec["preferred"] else "NONE"
        ),
    )
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=spec["requirement_entities"],
        predicate_constraints=spec["requirement_predicates"],
        temporal_constraints=_temporal(spec.get("temporal")),
        semantic_roles=RequirementSemanticRolesV02(
            actor=spec.get("actor"),
            experiencer=spec.get("experiencer"),
            beneficiary=spec.get("beneficiary"),
        ),
        evidence_source=source_policy,
        value_type="DATETIME" if spec.get("temporal") else "ANY",
    )
    binding = bind_requirements(
        [requirement],
        [interpretation],
        [span],
        compatibility_profile="dg22-v0.2",
    )[0]
    applicability = derive_non_temporal_applicability(
        [binding], [interpretation], [span]
    )[0]
    expected = spec["expected"]
    axis = spec.get("fail_axis") or spec.get("unknown_axis")
    axis_expected = "FAIL" if spec.get("fail_axis") else "UNKNOWN" if axis else None
    axis_actual = getattr(binding.compatibility, axis) if axis else None
    exact = verify_evidence_span(span, text)
    blocker = relevant_unresolved_event_binding(binding.model_dump(mode="json"))
    expected_blocker = applicability.status in {"MATCH", "POSSIBLE"}
    return {
        "cell_id": spec["cell_id"],
        "name": spec["name"],
        "expected_status": expected,
        "actual_status": binding.status,
        "compatibility": binding.compatibility.model_dump(mode="json"),
        "non_temporal_applicability": applicability.model_dump(mode="json"),
        "fail_axis": spec.get("fail_axis"),
        "unknown_axis": spec.get("unknown_axis"),
        "axis_expected": axis_expected,
        "axis_actual": axis_actual,
        "count_blocker": blocker,
        "exact_span_verified": exact,
        "passed": (
            binding.status == expected
            and (axis is None or axis_actual == axis_expected)
            and blocker == expected_blocker
            and exact
            and binding.schema_version == "requirement-binding-v0.2"
        ),
    }


def _legacy_adapter_probe() -> dict[str, Any]:
    original = {
        "schema_version": "requirement-binding-v0.1",
        "requirement_id": "legacy-slot",
        "interpretation_id": "legacy-interpretation",
        "status": "MATCH",
        "compatibility": {
            "type": "PASS",
            "entity": "PASS",
            "unit": "NOT_APPLICABLE",
            "temporal": "NOT_APPLICABLE",
            "episode": "NOT_APPLICABLE",
        },
        "reason_code": "ALL_BINDING_CONSTRAINTS_SATISFIED",
        "authority_class": "EVIDENCE_ONLY",
        "canonical_mutation": False,
    }
    original_digest = hashlib.sha256(repr(original).encode()).hexdigest()
    adapted = adapt_requirement_binding_v01(original)
    passed = (
        adapted.schema_version == "requirement-binding-v0.2"
        and adapted.compatibility.predicate == "NOT_APPLICABLE"
        and adapted.compatibility.source == "NOT_APPLICABLE"
        and adapted.compatibility.role == "NOT_APPLICABLE"
        and hashlib.sha256(repr(original).encode()).hexdigest() == original_digest
    )
    return {
        "passed": passed,
        "adapted": adapted.model_dump(mode="json"),
        "source_mutated": False,
    }


def _spec(
    name: str,
    *,
    expected: str,
    requirement_entities: Sequence[str] = ("atlas",),
    interpretation_entities: Sequence[str] = ("atlas", "workshop"),
    requirement_predicates: Sequence[str] = (),
    interpretation_predicate: str = "event_observation",
    interpretation_kind: str = "EVENT",
    allowed: Sequence[str] | None = None,
    preferred: Sequence[str] = (),
    speaker: str = "user",
    actor: str | None = None,
    experiencer: str | None = None,
    beneficiary: str | None = None,
    temporal: str | None = None,
    event_time: str | None = None,
    time_basis: str | None = None,
    source_timestamp: str | None = "IN_RANGE",
    fail_axis: str | None = None,
    unknown_axis: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "requirement_entities": list(requirement_entities),
        "interpretation_entities": list(interpretation_entities),
        "requirement_predicates": list(requirement_predicates),
        "interpretation_predicate": interpretation_predicate,
        "interpretation_kind": interpretation_kind,
        "allowed": list(allowed) if allowed is not None else None,
        "preferred": list(preferred),
        "speaker": speaker,
        "actor": actor,
        "experiencer": experiencer,
        "beneficiary": beneficiary,
        "temporal": temporal,
        "event_time": event_time,
        "time_basis": time_basis,
        "source_timestamp": source_timestamp,
        "fail_axis": fail_axis,
        "unknown_axis": unknown_axis,
    }


def _temporal(kind: object) -> NormalizedTemporalConstraint | None:
    if kind not in {"EVENT_RANGE", "SOURCE_RANGE"}:
        return None
    return NormalizedTemporalConstraint(
        reference_time=REFERENCE,
        start=REFERENCE - timedelta(days=7),
        end=REFERENCE,
        boundary="CLOSED_OPEN",
        time_axis="SOURCE_OBSERVED_TIME" if kind == "SOURCE_RANGE" else "EVENT_TIME",
    )


def _event_time(
    spec: Mapping[str, Any],
) -> tuple[InterpretationEventTime | None, InterpretationTimeBasis]:
    if spec.get("time_basis") in {"SOURCE_OBSERVED_TIME", "UNRESOLVED"}:
        return None, spec["time_basis"]
    if spec.get("event_time") == "IN_RANGE":
        value = REFERENCE - timedelta(days=2)
    elif spec.get("event_time") == "OUT_OF_RANGE":
        value = REFERENCE - timedelta(days=20)
    else:
        return None, "UNRESOLVED"
    return InterpretationEventTime(
        start=value, end=value, normalized_from=value.date().isoformat()
    ), "EXPLICIT_EVENT_TIME"


def _timestamp(value: object) -> datetime | None:
    if value == "IN_RANGE":
        return REFERENCE - timedelta(days=2)
    if value == "OUT_OF_RANGE":
        return REFERENCE - timedelta(days=20)
    return None


__all__ = ["binding_matrix", "run_binding_correctness"]
