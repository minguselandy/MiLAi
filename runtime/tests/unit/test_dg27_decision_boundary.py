from __future__ import annotations

from datetime import UTC, datetime

from milai.application.acquisition import compile_acquisition_plan
from milai.application.decision_boundary import (
    build_provisional_bindings,
    decide_deterministic_boundary,
    decide_semantic_boundary,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.acquisition import CandidateEnvelope
from milai.domain.decision_boundary import (
    EventTimeHypothesisV02,
    GroundedSpanV02,
    SemanticHypothesisV02,
    SemanticInterpretationSetV02,
)
from milai.domain.formation_artifact import (
    FormationEventCandidateV01,
    FormationSourceSpanV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.domain.semantic_query import InterpretationEventTime
from milai.domain.sufficiency import SufficiencyProof

REFERENCE = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _inputs():  # type: ignore[no-untyped-def]
    request = RetrievalRequest(
        route="L1",
        consistency="CANONICAL_REQUIRED",
        query="How many times did I visit Paris in the past 30 days?",
        as_of=REFERENCE,
        reference_time=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request)
    assert query_plan.memory_query_ir is not None
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=request.query or "",
        principal_scope={},
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=2_048,
    )
    content = "user: I visited Paris on August 10, 2026."
    source = {
        "evidence_id": "evidence-paris",
        "source_ref": "memory://session/s-1/turn/0",
        "subject_id": "subject-paris",
        "session_id": "s-1",
        "source_context": {
            "session_id": "s-1",
            "turn_id": "s-1:turn:0",
            "session_ordinal": 0,
            "round_ordinal": 0,
            "turn_ordinal": 0,
            "speaker": "user",
            "adjacent": [],
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": "2026-08-11T00:00:00+00:00",
        "content": content,
        "content_hash": canonical_sha256(content),
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }
    candidate = CandidateEnvelope(
        candidate_id="evidence-paris",
        source_evidence_id="evidence-paris",
        source_turn_ref="memory://session/s-1/turn/0",
        subject_id="subject-paris",
        session_id="s-1",
        turn_id="s-1:turn:0",
        identity_source="STRUCTURED_TURN_METADATA",
        speaker="user",
        speaker_source="STRUCTURED_TURN_METADATA",
        source_observed_at=datetime(2026, 8, 11, tzinfo=UTC),
        matched_probes=["dg27:MATCHING_EVENTS_IN_RANGE:FTS_RAW"],
        matched_slots=["MATCHING_EVENTS_IN_RANGE"],
        channel_ranks={"FTS_RAW": 1},
        channel_scores={"FTS_RAW": 1.0},
        probe_ranks={"dg27:MATCHING_EVENTS_IN_RANGE:FTS_RAW": 1},
        probe_scores={"dg27:MATCHING_EVENTS_IN_RANGE:FTS_RAW": 1.0},
        fusion_rank=1,
        fusion_score=1.0,
        matched_fields=["lexical_text"],
        body_ref="memory://session/s-1/turn/0",
        body_hydrated=True,
    )
    proof = SufficiencyProof(
        bounded_scan_completed=True,
        source_partition_closed=True,
        projection_watermark=7,
        deduplication_completed=True,
    )
    return query_plan.memory_query_ir, acquisition_plan, source, candidate, proof


def test_provisional_ambiguity_has_no_acceptance_or_sufficiency_authority() -> None:
    first = SemanticHypothesisV02(
        hypothesis_id="h-1",
        relation="SUPPORT",
        grounded_spans=[GroundedSpanV02(start=0, end=5, text="Paris")],
        normalized_subjects=["Paris"],
        normalized_predicate="visit",
        normalized_value="visit Paris",
    )
    second = first.model_copy(
        update={"hypothesis_id": "h-2", "normalized_predicate": "plan_visit"}
    )
    interpretation_set = SemanticInterpretationSetV02(
        candidate_id="candidate-1",
        hypotheses=[first, second],
        ambiguity_reasons=["EVENT_STATUS_UNRESOLVED"],
        producer_identity="fixture",
    )

    [binding] = build_provisional_bindings("TARGET", [interpretation_set])

    assert binding.status == "AMBIGUOUS"
    assert binding.accepted is False
    assert binding.satisfies_requirement is False
    assert binding.canonical_mutation is False


def test_proof_without_accepted_binding_never_emits_complete() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    unrelated = "user: I discussed the weather in Paris."
    source = {
        **source,
        "content": unrelated,
        "content_hash": canonical_sha256(unrelated),
    }
    empty = SemanticInterpretationSetV02(
        candidate_id=candidate.candidate_id,
        ambiguity_reasons=["NO_GROUNDED_READING"],
        producer_identity="fixture",
    )

    result = decide_semantic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        interpretation_sets_by_requirement={"MATCHING_EVENTS_IN_RANGE": [empty]},
        completion_proof=proof,
    )

    assert result.decision_count == 1
    assert result.accepted_bindings == []
    assert result.sufficiency_decision.status == "UNSATISFIED"
    assert result.requirement_state.missing_requirement_ids == [
        "MATCHING_EVENTS_IN_RANGE"
    ]
    assert result.operator_ready is False


def test_model_omission_preserves_valid_deterministic_binding() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    empty = SemanticInterpretationSetV02(
        candidate_id=candidate.candidate_id,
        ambiguity_reasons=["MODEL_DID_NOT_FORM_AN_ATOMIC_READING"],
        producer_identity="fixture",
    )

    result = decide_semantic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        interpretation_sets_by_requirement={"MATCHING_EVENTS_IN_RANGE": [empty]},
        completion_proof=proof,
    )

    assert len(result.accepted_bindings) == 1
    assert result.sufficiency_decision.status == "COMPLETE"
    assert result.operator_ready is True


def test_exact_formation_event_replaces_weaker_unresolved_local_reading() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    content = "user: I visited Paris."
    source = {
        **source,
        "content": content,
        "content_hash": canonical_sha256(content),
    }
    baseline = decide_deterministic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        completion_proof=proof,
    )
    quote = "I visited Paris"
    span = FormationSourceSpanV01(
        evidence_id="evidence-paris",
        source_ref="memory://session/s-1/turn/0",
        start=content.index(quote),
        end=content.index(quote) + len(quote),
        text=quote,
    )
    provisional = FormationEventCandidateV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        event_type="visit",
        primary_subject="Paris",
        context_participants=[],
        event_identity_key="event:visit-paris-2026-08-10",
        occurrence_time=InterpretationEventTime(
            start=datetime(2026, 8, 10, tzinfo=UTC),
            end=datetime(2026, 8, 10, tzinfo=UTC),
            normalized_from="formation-time anchor",
        ),
        time_basis="INFERRED_EVENT_TIME",
        temporal_anchor_spans=[],
        producer_identity="fixture-formation-v0.1",
        provenance={"source_time_substitution": False},
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    formed = FormationEventCandidateV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )

    treatment = decide_deterministic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        completion_proof=proof,
        formation_events=[formed],
    )

    assert baseline.accepted_bindings == []
    assert baseline.operator_ready is False
    assert len(treatment.accepted_bindings) == 1
    assert treatment.sufficiency_decision.status == "COMPLETE"
    assert treatment.operator_ready is True


def test_exact_model_hypothesis_is_still_runtime_validated_before_acceptance() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    content = str(source["content"])
    quote = "I visited Paris on August 10, 2026"
    start = content.index(quote)
    hypothesis = SemanticHypothesisV02(
        hypothesis_id="h-paris",
        relation="SUPPORT",
        grounded_spans=[
            GroundedSpanV02(start=start, end=start + len(quote), text=quote)
        ],
        normalized_subjects=["visit", "paris"],
        normalized_predicate="visit",
        normalized_value="visited Paris",
        event_time_hypothesis=EventTimeHypothesisV02(
            start=datetime(2026, 8, 10, tzinfo=UTC),
            end=datetime(2026, 8, 10, tzinfo=UTC),
            time_basis="EXPLICIT_EVENT_TIME",
            normalized_from="August 10, 2026",
        ),
        confidence_feature=0.8,
    )
    interpretation_set = SemanticInterpretationSetV02(
        candidate_id=candidate.candidate_id,
        hypotheses=[hypothesis],
        producer_identity="fixture",
    )

    result = decide_semantic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        interpretation_sets_by_requirement={
            "MATCHING_EVENTS_IN_RANGE": [interpretation_set]
        },
        completion_proof=proof,
    )

    assert len(result.accepted_bindings) == 1
    assert result.sufficiency_decision.status == "COMPLETE"
    assert result.requirement_state.missing_requirement_ids == []
    assert result.operator_ready is True


def test_unresolved_possible_member_keeps_closed_set_incomplete() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    content = str(source["content"])
    quote = "I visited Paris on August 10, 2026"
    start = content.index(quote)
    resolved = SemanticHypothesisV02(
        hypothesis_id="h-paris-resolved",
        relation="SUPPORT",
        grounded_spans=[
            GroundedSpanV02(start=start, end=start + len(quote), text=quote)
        ],
        normalized_subjects=["visit", "paris"],
        normalized_predicate="visit",
        normalized_value="visited Paris",
        event_time_hypothesis=EventTimeHypothesisV02(
            start=datetime(2026, 8, 10, tzinfo=UTC),
            end=datetime(2026, 8, 10, tzinfo=UTC),
            time_basis="EXPLICIT_EVENT_TIME",
            normalized_from="August 10, 2026",
        ),
    )
    unresolved = resolved.model_copy(
        update={
            "hypothesis_id": "h-paris-unresolved",
            "event_time_hypothesis": EventTimeHypothesisV02(
                time_basis="UNRESOLVED",
                normalized_from="August 10, 2026",
            ),
        }
    )
    interpretation_set = SemanticInterpretationSetV02(
        candidate_id=candidate.candidate_id,
        hypotheses=[resolved, unresolved],
        producer_identity="fixture",
    )

    result = decide_semantic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        interpretation_sets_by_requirement={
            "MATCHING_EVENTS_IN_RANGE": [interpretation_set]
        },
        completion_proof=proof,
    )

    [requirement] = result.requirement_state.requirements
    assert len(result.accepted_bindings) == 1
    assert requirement.possible_binding_refs
    assert requirement.status == "UNRESOLVED"
    assert result.sufficiency_decision.status == "UNSATISFIED"
    assert result.operator_ready is False


def test_non_exact_model_span_is_rejected_without_erasing_valid_baseline() -> None:
    query_ir, plan, source, candidate, proof = _inputs()
    hypothesis = SemanticHypothesisV02(
        hypothesis_id="h-bad-offset",
        relation="SUPPORT",
        grounded_spans=[GroundedSpanV02(start=0, end=5, text="Paris")],
        normalized_subjects=["paris"],
        normalized_predicate="visit",
    )
    interpretation_set = SemanticInterpretationSetV02(
        candidate_id=candidate.candidate_id,
        hypotheses=[hypothesis],
        producer_identity="fixture",
    )

    result = decide_semantic_boundary(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest="a" * 64,
        candidates=[candidate],
        source_records=[source],
        interpretation_sets_by_requirement={
            "MATCHING_EVENTS_IN_RANGE": [interpretation_set]
        },
        completion_proof=proof,
    )

    assert result.rejected_hypotheses == {
        "h-bad-offset": "GROUNDED_SPAN_NOT_SOURCE_EXACT"
    }
    assert len(result.accepted_bindings) == 1
    assert result.sufficiency_decision.status == "COMPLETE"
    assert result.operator_ready is True
