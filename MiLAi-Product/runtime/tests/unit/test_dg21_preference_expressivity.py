from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from milai.application.acquisition import compile_acquisition_plan
from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.preference_composition import synthesize_preference_evidence_view
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_initial_requirement_state
from milai.domain.retrieval import QueryPlan, RetrievalRequest

REFERENCE = datetime(2026, 8, 28, 8, tzinfo=UTC)
SCOPE: dict[str, JsonValue] = {"project_ids": ["dg21"]}


def _plan(query: str) -> QueryPlan:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope=SCOPE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )


def _evidence(
    evidence_id: str,
    content: str,
    turn_ordinal: int,
    *,
    speaker: str = "user",
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "subject_id": "fixture-user",
        "source_ref": f"memory://session/preference/turn/{turn_ordinal}",
        "content": content,
        "observed_at": REFERENCE.isoformat(),
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "retention_state": "READABLE",
        "permission_snapshot": {"readable": True, "project_ids": ["dg21"]},
    }


@pytest.mark.parametrize(
    "query",
    [
        "I'm planning a trip to Denver soon. Any suggestions on what to do there?",
        "I'm visiting Kyoto soon. Any recommendations for me?",
        "I'm thinking of visiting Lisbon; what would fit my preferences?",
        "I intend to return to Oslo. What do I prefer there?",
    ],
)
def test_explicit_current_preference_context_compiles_two_typed_slots(query: str) -> None:
    plan = _plan(query)
    assert plan.memory_query_ir is not None

    requirements = plan.memory_query_ir.requirements
    assert [item.slot_id for item in requirements] == [
        "PREFERENCE_SIGNAL_SET",
        "CURRENT_INTENT",
    ]
    assert [item.interpretation_kind for item in requirements] == [
        "PREFERENCE_SIGNAL",
        "DECISION",
    ]
    assert requirements[0].cardinality.minimum == 1
    assert requirements[0].cardinality.maximum is None
    assert requirements[1].cardinality.minimum == 1
    assert requirements[1].cardinality.maximum == 1
    # Public V02 no longer conflates the query participant with the Evidence
    # speaker.  The internal task contract carries the typed participant.
    assert requirements[1].semantic_roles.experiencer is None
    assert plan.query_task_contract is not None
    [current_intent] = [
        item
        for item in plan.query_task_contract.requirements
        if item.role_key == "CURRENT_INTENT"
    ]
    assert [(item.role, item.identity) for item in current_intent.participants] == [
        ("EXPERIENCER", "QUERY_SUBJECT")
    ]
    assert plan.memory_query_ir.planner_trace.auxiliary_model_calls == 0
    assert "CURRENT_INTENT_EXPLICIT" in plan.memory_query_ir.planner_trace.reason_code


@pytest.mark.parametrize(
    "query",
    [
        "What was my latest preference?",
        "What Denver activities do I prefer?",
        "Any suggestions for museums in Denver?",
        "I was planning a trip to Denver last year. What did I prefer?",
    ],
)
def test_historical_or_underspecified_preference_keeps_single_requirement(
    query: str,
) -> None:
    plan = _plan(query)
    assert plan.memory_query_ir is not None

    assert [item.slot_id for item in plan.memory_query_ir.requirements] == ["PREFERENCE_SIGNAL_SET"]
    assert "CURRENT_INTENT_EXPLICIT" not in plan.memory_query_ir.planner_trace.reason_code


def test_current_intent_is_a_value_slot_and_not_a_list_member_requirement() -> None:
    query = "I'm planning a trip to Denver soon. Any suggestions on what to do there?"
    query_plan = _plan(query)
    assert query_plan.memory_query_ir is not None
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=SCOPE,
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
        enable_enriched=True,
        enable_dense=True,
    )

    state = resolve_initial_requirement_state(
        acquisition_plan,
        query_plan.memory_query_ir.requirements,
        memory_query_ir=query_plan.memory_query_ir,
    )

    assert {item.requirement_id: item.kind for item in state.requirements} == {
        "CURRENT_INTENT": "VALUE_SLOT",
        "PREFERENCE_SIGNAL_SET": "SET_MEMBERS",
    }


def test_historical_signal_cannot_false_satisfy_current_intent() -> None:
    query = "I'm planning a trip to Denver soon. Any suggestions on what to do there?"
    plan = _plan(query)
    assert plan.memory_query_ir is not None
    historical = _evidence(
        "historical",
        "I love Denver's live music scene.",
        4,
    )
    spans = project_evidence_spans([historical])
    _, bindings, audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
    )

    matched = {item.requirement_id for item in bindings if item.status == "MATCH"}
    view = synthesize_preference_evidence_view(plan, [historical])

    assert matched == {"PREFERENCE_SIGNAL_SET"}
    assert audit.materialized_type_mismatch_count == 0
    assert view is not None
    assert view["completeness"]["filled_slots"] == ["PREFERENCE_SIGNAL_SET"]
    assert "CURRENT_INTENT_MISSING" in view["completeness"]["unresolved_reasons"]


def test_explicit_user_intent_binds_independently_and_assistant_intent_does_not() -> None:
    query = "I'm planning a trip to Denver soon. Any suggestions on what to do there?"
    plan = _plan(query)
    assert plan.memory_query_ir is not None
    historical = _evidence(
        "historical",
        "I love Denver's live music scene.",
        4,
    )
    current = _evidence(
        "current",
        "I'm thinking of going back to Denver for another concert.",
        6,
    )
    assistant = _evidence(
        "assistant",
        "I'm planning a trip to Denver soon.",
        7,
        speaker="assistant",
    )

    spans = project_evidence_spans([historical, current, assistant])
    interpretations, bindings, _ = run_type_directed_semantics(
        plan.memory_query_ir.requirements,
        spans,
    )
    span_by_id = {item.span_id: item for item in spans}
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    current_refs = {
        span_by_id[interpretation_by_id[item.interpretation_id].span_id].source_evidence_id
        for item in bindings
        if item.requirement_id == "CURRENT_INTENT" and item.status == "MATCH"
    }
    view = synthesize_preference_evidence_view(plan, [historical, current, assistant])

    assert current_refs == {"current"}
    assert view is not None
    assert view["completeness"]["filled_slots"] == [
        "PREFERENCE_SIGNAL_SET",
        "CURRENT_INTENT",
    ]
    assert view["current_intent_evidence_refs"] == ["current"]
    assert view["canonical"] is False
    assert view["canonical_mutation"] is False


def test_a82_non_preference_lookup_semantics_do_not_regress() -> None:
    plan = _plan("What game did I finally beat last weekend?")
    assert plan.memory_query_ir is not None

    assert infer_operator_family(plan.memory_query_ir) == "LOOKUP"
    assert [item.slot_id for item in plan.memory_query_ir.requirements] == ["LOOKUP_ANSWER"]
    assert all(item.slot_id != "CURRENT_INTENT" for item in plan.memory_query_ir.requirements)
    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_preference_expressivity_does_not_change_public_retrieval_request_schema() -> None:
    fields = set(RetrievalRequest.model_json_schema()["properties"])

    assert "current_intent" not in fields
    assert "preference_requirements" not in fields
