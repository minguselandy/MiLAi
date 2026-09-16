from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from milai.application.decision_engine import DEFAULT_DECISION_ENGINE
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.lookup_readiness import classify_lookup_relation
from milai.application.query_operators import execute_binding_backed_query_operator
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2026, 9, 1, tzinfo=UTC)


def _source(
    content: str,
    *,
    speaker: str = "user",
    evidence_id: str = "lookup-evidence",
    session_id: str = "lookup",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{session_id}/turn/0",
        "subject_id": "lookup-subject",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"{session_id}:turn:0",
            "turn_ordinal": 0,
            "round_id": f"{session_id}:round:0",
            "round_ordinal": 0,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
    }


def _lookup_bindings(
    query: str,
    content: str,
    *,
    speaker: str = "user",
) -> tuple[Any, ...]:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            reference_time=REFERENCE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )
    assert plan.memory_query_ir is not None
    spans = project_evidence_spans([_source(content, speaker=speaker)])
    interpretations, bindings, audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    return plan, spans, interpretations, bindings, audit


def test_non_temporal_lookup_uses_grounded_state_relation() -> None:
    plan, spans, interpretations, bindings, audit = _lookup_bindings(
        "What color is my bicycle lock?",
        "My bicycle lock is cobalt blue.",
    )

    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.requirements[0].interpretation_kind == "STATE_OBSERVATION"
    [binding] = [item for item in bindings if item.status == "MATCH"]
    interpretation = next(
        item for item in interpretations if item.interpretation_id == binding.interpretation_id
    )
    span = next(item for item in spans if item.span_id == interpretation.span_id)
    assert span.text == "My bicycle lock is cobalt blue."
    assert binding.compatibility.model_dump() == {
        "type": "PASS",
        "entity": "PASS",
        "predicate": "PASS",
        "source": "NOT_APPLICABLE",
        "role": "NOT_APPLICABLE",
        "unit": "NOT_APPLICABLE",
        "temporal": "NOT_APPLICABLE",
        "episode": "NOT_APPLICABLE",
    }
    assert audit.exact_source_span_failure_count == 0


def test_lookup_relation_negative_controls_never_bind() -> None:
    false_sources = (
        "What color is my bicycle lock?",
        "I want to make my bicycle lock cobalt blue.",
        "My bicycle helmet is cobalt blue.",
    )

    for content in false_sources:
        _plan, _spans, _interpretations, bindings, _audit = _lookup_bindings(
            "What color is my bicycle lock?",
            content,
        )
        assert not any(item.status == "MATCH" for item in bindings)

    assert classify_lookup_relation(false_sources[0]) == "QUESTION_PARAPHRASE"
    assert classify_lookup_relation(false_sources[1]) == "NON_ASSERTIVE_INTENTION"


def test_chinese_question_paraphrase_is_not_an_asserted_relation() -> None:
    assert classify_lookup_relation("我的自行车锁是什么颜色。") == "QUESTION_PARAPHRASE"


def test_unknown_source_identity_cannot_have_semantic_effect() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="What color is my bicycle lock?",
            reference_time=REFERENCE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )
    assert plan.memory_query_ir is not None
    unstructured = _source("My bicycle lock is cobalt blue.")
    unstructured.pop("source_context")
    unstructured.pop("source_context_source")
    spans = project_evidence_spans([unstructured])
    _interpretations, bindings, _audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )

    assert not any(item.status == "MATCH" for item in bindings)
    assert any(item.compatibility.source == "UNKNOWN" for item in bindings)


def test_lookup_source_role_is_independent_from_relation_match() -> None:
    _plan, _spans, _interpretations, bindings, _audit = _lookup_bindings(
        "What color is my bicycle lock?",
        "My bicycle lock is cobalt blue.",
        speaker="assistant",
    )

    # A participant mentioned by the fact and the speaker who records it are
    # independent.  When the query has no source-role constraint, a grounded
    # assistant statement may support the lookup without pretending that the
    # assistant is the participant.
    assert any(item.status == "MATCH" for item in bindings)
    assert all(item.compatibility.role == "NOT_APPLICABLE" for item in bindings)


def test_role_free_lookup_can_bind_an_assistant_answer() -> None:
    _plan, _spans, _interpretations, bindings, _audit = _lookup_bindings(
        "What is the cobalt code?",
        "The cobalt code is 47.",
        speaker="assistant",
    )

    assert any(item.status == "MATCH" for item in bindings)


def test_temporal_lookup_retains_strict_event_semantics() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="What game did I finally beat last weekend?",
            reference_time=REFERENCE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )

    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.requirements[0].interpretation_kind == "EVENT"


def test_operator_complete_without_a_validated_binding_is_wrong_complete_zero() -> None:
    request = RetrievalRequest(
        route="L1",
        query="What is the cobalt code?",
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    plan = QueryPlanner().plan(request)
    result = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(_source("The cobalt code is 47."),),
        canonical_results=(),
        spans=(),
        interpretations=(),
        bindings=(),
        operator_result={"status": "COMPLETE", "value": "47"},
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert result.sufficiency_decision.complete is False
    assert result.reason_code != "GROUNDED_OPERATOR_COMPLETE"


def test_operator_status_cannot_promote_a_grounded_lookup_binding() -> None:
    query = "What color is my bicycle lock?"
    content = "My bicycle lock is cobalt blue."
    request = RetrievalRequest(
        route="L1",
        query=query,
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    plan, spans, interpretations, bindings, _audit = _lookup_bindings(query, content)
    result = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(_source(content),),
        canonical_results=({**_source(content), "kind": "EVIDENCE_OBSERVATION"},),
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        operator_result={"status": "COMPLETE", "value": "cobalt blue"},
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert any(item.status == "MATCH" for item in bindings)
    assert result.sufficiency_decision.complete is False
    assert result.reason_code == "OPERATOR_ACCEPTED_BINDING_INCOMPLETE"


def test_raw_binding_interpretation_cannot_authorize_temporal_operator() -> None:
    query = (
        "How many days had passed between the workshop on Effective Communication "
        "in the Workplace and the upcoming meeting with my team?"
    )
    request = RetrievalRequest(
        route="L1",
        query=query,
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    plan = QueryPlanner().plan(request)
    sources = [
        _source(
            "I attended the workshop on Effective Communication in the Workplace "
            "on January 10th.",
            evidence_id="workshop",
            session_id="workshop",
        ),
        _source(
            "My upcoming meeting with the team is on January 17th.",
            evidence_id="meeting",
            session_id="meeting",
        ),
    ]
    assert plan.memory_query_ir is not None
    spans = project_evidence_spans(sources)
    interpretations, bindings, _audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    operator_result = execute_binding_backed_query_operator(
        plan,
        sources,
        spans,
        interpretations,
        bindings,
    )
    result = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=tuple(sources),
        canonical_results=tuple(sources),
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        operator_result=operator_result,
        temporal_proof=None,
        request=request,
        plan=plan,
        mode="STRICT_OPERATOR",
    )

    assert operator_result is not None and operator_result["status"] == "ABSTAINED"
    assert operator_result["accepted_input_evidence_ids"] == []
    assert result.sufficiency_decision.complete is False


def test_grounded_raw_lookup_binding_is_source_ready_not_answer_complete() -> None:
    query = "What color is my bicycle lock?"
    content = "My bicycle lock is cobalt blue."
    request = RetrievalRequest(
        route="L1",
        query=query,
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    plan, spans, interpretations, bindings, _audit = _lookup_bindings(query, content)
    result = DEFAULT_DECISION_ENGINE.decide(
        plan.memory_query_ir,
        governed_candidates=(_source(content),),
        canonical_results=({**_source(content), "kind": "EVIDENCE_OBSERVATION"},),
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        operator_result=None,
        temporal_proof=None,
        request=request,
        plan=plan,
    )

    assert any(item.status == "MATCH" for item in bindings)
    assert result.sufficiency_decision.status == "PARTIAL"
    assert result.reason_code == "EVIDENCE_LOOKUP_CANDIDATE_ONLY"
