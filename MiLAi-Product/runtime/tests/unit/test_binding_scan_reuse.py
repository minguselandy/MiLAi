from typing import Literal

import pytest

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.semantic_query import EvidenceRequirementV02, EvidenceSpan


def _spans(text: str = "Alice lives in Paris.") -> list[EvidenceSpan]:
    return project_evidence_spans([
        {
            "evidence_id": str(index), "subject_id": str(index),
            "source_ref": f"memory://session/{index}/turn/0",
            "source_context": {"session_id": str(index), "turn_id": f"{index}:turn:0"},
            "source_context_source": "STRUCTURED_TURN_METADATA",
            "speaker": speaker, "speaker_source": "STRUCTURED_TURN_METADATA",
            "content": text, "observed_at": observed,
            "permission_snapshot": {"readable": True}, "retention_state": "READABLE",
        }
        for index, (speaker, observed) in enumerate([
            ("user", "2026-09-05T12:00:00+00:00"),
            ("assistant", "2026-09-06T12:00:00+00:00"),
            ("unknown", None),
        ])
    ])


def _requirement(**changes: object) -> EvidenceRequirementV02:
    return EvidenceRequirementV02.model_validate({
        "slot_id": "lookup", "interpretation_kind": "STATE_OBSERVATION",
        "entity_constraints": ["Alice"], "predicate_constraints": ["answer_bearing"],
        **changes,
    })


@pytest.mark.parametrize("profile", ["legacy-v0.1", "dg22-v0.2"])
@pytest.mark.parametrize("typed", [False, True])
def test_binding_batch_matches_independent_pairs(
    profile: Literal["legacy-v0.1", "dg22-v0.2"], typed: bool
) -> None:
    spans = _spans("Alice bought 7 mugs yesterday. Who bought mugs? I prefer tea.")
    interpretations = interpret_evidence_spans(spans)
    requirements = [
        _requirement(), _requirement(entity_constraints=["Bob"]),
        _requirement(entity_constraints=[], predicate_constraints=["current_state"]),
        _requirement(interpretation_kind="EVENT", predicate_constraints=["event_time"]),
        _requirement(interpretation_kind="QUANTITY", predicate_constraints=["count"]),
    ]
    actual = bind_requirements(requirements, interpretations, spans,
                               compatibility_profile=profile, type_compatible_only=typed)
    expected = [
        binding for requirement in requirements for interpretation in interpretations
        for binding in bind_requirements([requirement], [interpretation], spans,
                                         compatibility_profile=profile, type_compatible_only=typed)
    ]
    assert actual == sorted(expected, key=lambda b: (
        b.requirement_id, b.status != "MATCH", b.interpretation_id
    ))


def test_same_text_keeps_source_role_and_temporal_checks_separate() -> None:
    spans = _spans()
    interpretations = interpret_evidence_spans(spans)
    requirement = _requirement(
        evidence_source={"allowed_speakers": ["USER"], "provenance": "EXPLICIT_QUERY"},
        semantic_roles={"actor": "USER"},
        temporal_constraints={
            "reference_time": "2026-09-07T00:00:00+00:00",
            "start": "2026-09-05T00:00:00+00:00", "end": "2026-09-05T00:00:00+00:00",
            "boundary": "POINT", "time_axis": "SOURCE_OBSERVED_TIME",
        },
    )
    by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {span.span_id: span for span in spans}
    values = bind_requirements([requirement], interpretations, spans,
                               compatibility_profile="dg22-v0.2")
    states = {span_by_id[by_id[b.interpretation_id].span_id].speaker: b for b in values}
    assert states["user"].status == "MATCH"
    assert states["assistant"].status == "REJECTED"
    assert states["assistant"].compatibility.source == "FAIL"
    assert states["assistant"].compatibility.role == "FAIL"
    assert states["assistant"].compatibility.temporal == "FAIL"
    assert states["unknown"].status == "POSSIBLE"
    assert states["unknown"].compatibility.source == "UNKNOWN"
    assert states["unknown"].compatibility.temporal == "UNKNOWN"
    states["user"].compatibility.predicate = "FAIL"
    assert states["assistant"].compatibility.predicate == "PASS"


def test_later_call_observes_changed_requirement_and_relation_text() -> None:
    spans = _spans()
    requirement = _requirement()
    interpretations = interpret_evidence_spans(spans)
    first = bind_requirements([requirement], interpretations, spans,
                              compatibility_profile="dg22-v0.2")
    assert all(item.status == "MATCH" for item in first)
    requirement.entity_constraints[:] = ["Bob"]
    second = bind_requirements([requirement], interpretations, spans,
                               compatibility_profile="dg22-v0.2")
    assert all(item.compatibility.entity == "FAIL" for item in second)
    changed = _spans("Does Alice live in Paris?")
    third = bind_requirements([_requirement()], interpret_evidence_spans(changed), changed,
                              compatibility_profile="dg22-v0.2")
    assert all(item.compatibility.predicate == "FAIL" for item in third)
