from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    matched_bindings_by_slot,
    project_evidence_spans,
    run_type_directed_semantics,
    verify_evidence_span,
)
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    InterpretationEventTime,
    MemoryPlannerTrace,
    MemoryQueryConstraints,
    MemoryQueryIRV02,
    MemoryQueryStep,
    NormalizedTemporalConstraint,
    QueryCueSpan,
    SemanticQueryHint,
    validate_query_hint_spans,
)

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)


def _source(
    evidence_id: str,
    content: str,
    *,
    observed_at: datetime = REFERENCE,
    speaker: str = "user",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "subject_id": evidence_id,
        "observed_at": observed_at.isoformat(),
        "captured_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
    }


def _quantity_requirements() -> list[EvidenceRequirementV02]:
    return [
        EvidenceRequirementV02(
            slot_id="TOTAL_PRICE",
            interpretation_kind="QUANTITY",
            entity_constraints=["mugs"],
            predicate_constraints=["money", "total"],
            value_type="NUMBER",
            join_key="purchase",
        ),
        EvidenceRequirementV02(
            slot_id="ITEM_COUNT",
            interpretation_kind="QUANTITY",
            entity_constraints=["mugs"],
            predicate_constraints=["integer_count", "count"],
            value_type="NUMBER",
            join_key="purchase",
        ),
    ]


def test_q3a_semantic_hint_is_non_executable_and_requires_exact_query_spans() -> None:
    query = "How many events happened last week?"
    start = query.index("last week")
    hint = SemanticQueryHint(
        route="COMPOSE",
        operator_family="COUNT",
        cue_spans=[QueryCueSpan(start=0, end=8, text="How many")],
        temporal_spans=[QueryCueSpan(start=start, end=start + len("last week"), text="last week")],
        requires_complete_set=True,
    )

    validate_query_hint_spans(query, hint)
    tampered = hint.model_copy(
        update={
            "cue_spans": [QueryCueSpan(start=0, end=8, text="Not real")],
        }
    )
    with pytest.raises(ValueError, match="SEMANTIC_HINT_CUE_SPAN_MISMATCH"):
        validate_query_hint_spans(query, tampered)
    with pytest.raises(ValidationError, match="final_answer"):
        SemanticQueryHint.model_validate(
            {
                **hint.model_dump(),
                "final_answer": "seven",
            }
        )


def test_sentence_projection_preserves_abbreviated_proper_name_as_one_exact_span() -> None:
    content = "I attended Sunday mass at St. Mary's Church on March 19th. It was peaceful."

    spans = project_evidence_spans([_source("abbreviation", content)])

    assert [item.text for item in spans] == [
        "I attended Sunday mass at St. Mary's Church on March 19th.",
        "It was peaceful.",
    ]
    assert all(verify_evidence_span(item, content) for item in spans)


def test_same_deictic_phrase_is_soft_only_for_single_answer_lookup() -> None:
    requirement = EvidenceRequirementV02(
        slot_id="LOOKUP_ANSWER",
        interpretation_kind="EVENT",
        entity_constraints=["bake"],
        predicate_constraints=["answer_bearing"],
        temporal_constraints=NormalizedTemporalConstraint(
            reference_time=datetime(2023, 4, 3, tzinfo=UTC),
            start=datetime(2023, 4, 1, tzinfo=UTC),
            end=datetime(2023, 4, 3, tzinfo=UTC),
            boundary="CLOSED_OPEN",
            normalized_from=[QueryCueSpan(start=18, end=30, text="last weekend")],
        ),
    )
    spans = project_evidence_spans(
        [
            _source(
                "deictic",
                "I baked a tart last weekend.",
                observed_at=datetime(2023, 3, 31, tzinfo=UTC),
            )
        ]
    )

    _interpretations, bindings, _audit = run_type_directed_semantics(
        [requirement], spans, compatibility_profile="dg22-v0.2"
    )

    assert any(
        item.status == "MATCH" and item.compatibility.temporal == "PASS"
        for item in bindings
    )
    mismatched = requirement.model_copy(
        update={
            "temporal_constraints": requirement.temporal_constraints.model_copy(
                update={
                    "normalized_from": [QueryCueSpan(start=0, end=9, text="yesterday")]
                }
            )
        }
    )
    _interpretations, mismatched_bindings, _audit = run_type_directed_semantics(
        [mismatched], spans, compatibility_profile="dg22-v0.2"
    )
    assert not any(item.status == "MATCH" for item in mismatched_bindings)


def test_exhaustive_event_binding_rejects_secondary_calendar_indexes() -> None:
    requirement = EvidenceRequirementV02(
        slot_id="EVENT_SET",
        interpretation_kind="EVENT",
        entity_constraints=["twins"],
        cardinality={"minimum": 1, "maximum": None, "distinct": True},
    )
    spans = project_evidence_spans(
        [
            _source("primary", "We welcomed twins, Ava and Mia, on March 2."),
            _source(
                "index",
                "I will add the day we welcomed the twins to the birthday calendar.",
            ),
        ]
    )

    interpretations, bindings, _audit = run_type_directed_semantics(
        [requirement], spans, compatibility_profile="dg22-v0.2"
    )
    span_by_interpretation = {
        item.interpretation_id: next(span for span in spans if span.span_id == item.span_id)
        for item in interpretations
    }
    status_by_evidence = {
        span_by_interpretation[item.interpretation_id].source_evidence_id: item
        for item in bindings
    }

    assert status_by_evidence["primary"].status == "MATCH"
    assert status_by_evidence["primary"].compatibility.episode == "PASS"
    assert status_by_evidence["index"].status == "REJECTED"
    assert status_by_evidence["index"].compatibility.episode == "FAIL"


def test_q3a_v02_ir_requires_explicit_bind_steps_for_complete_queries() -> None:
    requirement = _quantity_requirements()[0]
    with pytest.raises(ValidationError, match="bind every required slot"):
        MemoryQueryIRV02(
            mode="COMPOSE",
            answer_shape="SCALAR",
            constraints=MemoryQueryConstraints(),
            requirements=[requirement],
            steps=[
                MemoryQueryStep(
                    kind="RETRIEVE",
                    outputs=["candidates"],
                    constraints={"operator_family": "DIVIDE"},
                )
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            planner_trace=MemoryPlannerTrace(
                source="DETERMINISTIC",
                compiler_version="test",
                auxiliary_model_calls=0,
                reason_code="TEST",
            ),
        )


def test_q3a_target_event_cannot_collapse_to_lookup_answer() -> None:
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        temporal_constraints=NormalizedTemporalConstraint(
            reference_time=REFERENCE,
            start=REFERENCE - timedelta(days=10),
            end=REFERENCE - timedelta(days=10),
            boundary="POINT",
        ),
        value_type="STRING",
    )

    with pytest.raises(ValidationError, match="TARGET_EVENT cannot collapse"):
        MemoryQueryIRV02(
            mode="COMPOSE",
            answer_shape="STATE",
            requirements=[requirement],
            steps=[
                MemoryQueryStep(
                    kind="RETRIEVE",
                    outputs=["candidates"],
                    constraints={"operator_family": "LOOKUP"},
                ),
                MemoryQueryStep(
                    kind="BIND_SLOT",
                    inputs=["candidates"],
                    outputs=["TARGET_EVENT"],
                ),
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            planner_trace=MemoryPlannerTrace(
                source="DETERMINISTIC",
                compiler_version="test",
                auxiliary_model_calls=0,
                reason_code="COLLAPSED_TARGET_EVENT",
            ),
        )


def test_q3a_one_span_has_multiple_interpretations_without_cross_binding() -> None:
    source = _source("purchase", "user: I paid $60 for 5 mugs.")
    spans = project_evidence_spans([source])
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(_quantity_requirements(), interpretations, spans)
    matched = matched_bindings_by_slot(bindings)

    assert len(spans) == 1
    assert verify_evidence_span(spans[0], str(source["content"]))
    quantities = [item for item in interpretations if item.kind == "QUANTITY"]
    assert {(item.value, item.unit) for item in quantities} == {
        (60, "USD"),
        (5, "COUNT"),
    }
    assert len(matched["TOTAL_PRICE"]) == 1
    assert len(matched["ITEM_COUNT"]) == 1
    by_id = {item.interpretation_id: item for item in interpretations}
    assert by_id[matched["TOTAL_PRICE"][0]].unit == "USD"
    assert by_id[matched["ITEM_COUNT"][0]].unit == "COUNT"
    assert sum(binding.status == "REJECTED" for binding in bindings) >= 2
    assert all(binding.canonical_mutation is False for binding in bindings)


def test_q3a_adjacent_turn_operands_remain_independent_bindable_sources() -> None:
    sources = [
        _source("price", "user: I paid $60 for the mugs."),
        _source("count", "assistant: That purchase contained 5 mugs."),
    ]
    spans = project_evidence_spans(sources)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(_quantity_requirements(), interpretations, spans)
    matched = matched_bindings_by_slot(bindings)
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {span.span_id: span for span in spans}

    assert len(matched["TOTAL_PRICE"]) == len(matched["ITEM_COUNT"]) == 1
    price_span = span_by_id[interpretation_by_id[matched["TOTAL_PRICE"][0]].span_id]
    count_span = span_by_id[interpretation_by_id[matched["ITEM_COUNT"][0]].span_id]
    assert price_span.source_evidence_id == "price"
    assert count_span.source_evidence_id == "count"


def test_q3a_one_span_two_entities_only_role_and_time_compatible_event_binds() -> None:
    span = project_evidence_spans(
        [
            _source(
                "purchase-events",
                "user: I bought a toaster on March 3rd and a blender on March 12th.",
            )
        ]
    )[0]
    interpretations = [
        EvidenceInterpretationCandidate(
            interpretation_id="event-toaster-march-3",
            span_id=span.span_id,
            kind="EVENT",
            value="bought toaster",
            entities=["toaster"],
            predicate="purchase",
            event_time=InterpretationEventTime(
                start=datetime(2023, 3, 3, tzinfo=UTC),
                end=datetime(2023, 3, 3, tzinfo=UTC),
            ),
            time_basis="EXPLICIT_EVENT_TIME",
            extractor_identity="typed-contract-fixture",
        ),
        EvidenceInterpretationCandidate(
            interpretation_id="event-blender-march-12",
            span_id=span.span_id,
            kind="EVENT",
            value="bought blender",
            entities=["blender"],
            predicate="purchase",
            event_time=InterpretationEventTime(
                start=datetime(2023, 3, 12, tzinfo=UTC),
                end=datetime(2023, 3, 12, tzinfo=UTC),
            ),
            time_basis="EXPLICIT_EVENT_TIME",
            extractor_identity="typed-contract-fixture",
        ),
    ]
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=["toaster"],
        temporal_constraints=NormalizedTemporalConstraint(
            reference_time=REFERENCE,
            start=datetime(2023, 3, 3, tzinfo=UTC),
            end=datetime(2023, 3, 3, tzinfo=UTC),
            boundary="POINT",
        ),
        value_type="STRING",
    )

    bindings = bind_requirements([requirement], interpretations, [span])

    assert [binding.interpretation_id for binding in bindings if binding.status == "MATCH"] == [
        "event-toaster-march-3"
    ]
    rejected = next(
        binding
        for binding in bindings
        if binding.interpretation_id == "event-blender-march-12"
    )
    assert rejected.status == "REJECTED"
    assert rejected.compatibility.entity == "FAIL"
    assert rejected.compatibility.temporal == "FAIL"


def test_q3a_source_time_is_not_accepted_as_event_time_without_proof() -> None:
    bounded = NormalizedTemporalConstraint(
        reference_time=REFERENCE,
        start=REFERENCE - timedelta(days=7),
        end=REFERENCE,
        boundary="CLOSED_OPEN",
    )
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=["workshop"],
        temporal_constraints=bounded,
        value_type="DATETIME",
    )
    spans = project_evidence_spans([_source("undated", "user: I attended the workshop.")])
    interpretations = interpret_evidence_spans(spans)
    event = next(item for item in interpretations if item.kind == "EVENT")
    binding = next(
        item
        for item in bind_requirements([requirement], interpretations, spans)
        if item.interpretation_id == event.interpretation_id
    )

    assert event.time_basis == "SOURCE_OBSERVED_TIME"
    assert event.event_time is None
    assert binding.status == "REJECTED"
    assert binding.compatibility.temporal == "FAIL"
    assert binding.reason_code == "TEMPORAL_INCOMPATIBLE"


def test_target_event_rejects_weak_assistant_closing_without_friend_entity() -> None:
    sources = [
        _source("closing", "Take care, and happy cooking!", speaker="assistant"),
        _source(
            "cake",
            "I just baked a chocolate cake for my friend's birthday party.",
        ),
    ]
    spans = project_evidence_spans(sources)
    interpretations = interpret_evidence_spans(spans)
    requirement = EvidenceRequirementV02(
        slot_id="TARGET_EVENT",
        interpretation_kind="EVENT",
        entity_constraints=["mentioned", "cooking", "friend"],
        predicate_constraints=["event_at_time"],
        temporal_constraints=NormalizedTemporalConstraint(
            reference_time=REFERENCE,
            start=REFERENCE,
            end=REFERENCE,
            boundary="POINT",
            time_axis="SOURCE_OBSERVED_TIME",
        ),
        value_type="STRING",
    )

    bindings = bind_requirements([requirement], interpretations, spans)
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation
        for interpretation in interpretations
    }
    matched_texts = {
        span_by_id[interpretation_by_id[binding.interpretation_id].span_id].text
        for binding in bindings
        if binding.status == "MATCH"
    }

    assert matched_texts == {
        "I just baked a chocolate cake for my friend's birthday party."
    }


def test_q3a_explicit_event_time_stays_distinct_from_source_and_system_time() -> None:
    source = _source(
        "dated",
        "user: I attended the workshop on March 3rd.",
        observed_at=datetime(2023, 3, 5, 9, tzinfo=UTC),
    )
    span = project_evidence_spans([source])[0]
    event = next(item for item in interpret_evidence_spans([span]) if item.kind == "EVENT")

    assert event.event_time is not None
    assert event.event_time.start == datetime(2023, 3, 3, tzinfo=UTC)
    assert span.source_timestamp == datetime(2023, 3, 5, 9, tzinfo=UTC)
    assert span.provenance["system_timestamp"] == "2023-03-05T09:00:01+00:00"
    assert event.time_basis == "EXPLICIT_EVENT_TIME"


def test_unrepresentable_historical_span_falls_back_to_source_time() -> None:
    source = _source(
        "ancient-history",
        "user: I visited ruins that were built around 4000 years ago.",
        observed_at=datetime(2023, 6, 1, tzinfo=UTC),
    )
    span = project_evidence_spans([source])[0]

    event = next(
        item for item in interpret_evidence_spans([span]) if item.kind == "EVENT"
    )

    assert event.event_time is None
    assert event.time_basis == "SOURCE_OBSERVED_TIME"


def test_local_anchor_does_not_cross_sentences_inside_one_turn() -> None:
    source = _source(
        "two-events",
        (
            "user: I am preparing for an upcoming team meeting. "
            "I attended a communication workshop on January 10th."
        ),
        observed_at=datetime(2023, 1, 13, 9, tzinfo=UTC),
    )
    spans = project_evidence_spans([source])
    interpretations = interpret_evidence_spans(
        spans,
        allowed_kinds={"EVENT"},
        resolve_local_anchors=True,
    )
    span_by_id = {span.span_id: span for span in spans}
    meeting = next(
        item
        for item in interpretations
        if "team meeting" in span_by_id[item.span_id].text
    )
    workshop = next(
        item
        for item in interpretations
        if "communication workshop" in span_by_id[item.span_id].text
    )

    assert meeting.event_time is None
    assert meeting.time_basis == "SOURCE_OBSERVED_TIME"
    assert workshop.event_time is not None
    assert workshop.time_basis == "EXPLICIT_EVENT_TIME"


def test_local_anchor_crosses_same_turn_sentences_for_the_same_event_family() -> None:
    source = _source(
        "same-event",
        (
            "user: I am preparing for an upcoming team meeting. "
            "The team meeting is on January 17th."
        ),
        observed_at=datetime(2023, 1, 13, 9, tzinfo=UTC),
    )
    spans = project_evidence_spans([source])
    interpretations = interpret_evidence_spans(
        spans,
        allowed_kinds={"EVENT"},
        resolve_local_anchors=True,
    )
    span_by_id = {span.span_id: span for span in spans}
    preparing = next(
        item
        for item in interpretations
        if "preparing" in span_by_id[item.span_id].text
    )

    assert preparing.event_time is not None
    assert preparing.event_time.start == datetime(2023, 1, 17, tzinfo=UTC)
    assert preparing.time_basis == "INFERRED_EVENT_TIME"


@pytest.mark.parametrize(
    ("content", "expected_start", "expected_end"),
    [
        (
            "user: I baked a cake last weekend.",
            datetime(2023, 3, 25, tzinfo=UTC),
            datetime(2023, 3, 27, tzinfo=UTC),
        ),
        (
            "user: I met Tom a few months ago.",
            datetime(2022, 12, 27, 12, tzinfo=UTC),
            datetime(2022, 12, 27, 12, tzinfo=UTC),
        ),
        (
            "user: I made bread last Saturday.",
            datetime(2023, 3, 25, tzinfo=UTC),
            datetime(2023, 3, 26, tzinfo=UTC),
        ),
        (
            "user: Ava and Lily were born in March.",
            datetime(2023, 3, 1, tzinfo=UTC),
            datetime(2023, 4, 1, tzinfo=UTC),
        ),
    ],
)
def test_q4_relative_event_time_is_inferred_only_from_an_explicit_phrase(
    content: str,
    expected_start: datetime,
    expected_end: datetime,
) -> None:
    span = project_evidence_spans([_source("relative", content)])[0]
    event = next(item for item in interpret_evidence_spans([span]) if item.kind == "EVENT")

    assert event.event_time is not None
    assert event.event_time.start == expected_start
    assert event.event_time.end == expected_end
    assert event.time_basis == "INFERRED_EVENT_TIME"
