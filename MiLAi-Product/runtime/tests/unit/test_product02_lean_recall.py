from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.lean_recall import compile_lean_recall_plan, lean_decision_mode
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_resolve import MemoryQueryInterpreter, _access_outcome
from milai.application.query_operators import execute_binding_backed_query_operator
from milai.application.query_planner import QueryPlanner
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.application.retrieval import _use_acquisition_composition
from milai.domain.lean_recall import EvidenceSet, EvidenceSetItem, LeanRecallMode
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    AcceptedBindingSpan,
    ContextBudgetEnvelope,
    DecisionSnapshot,
    ReaderEvidencePolicy,
)
from milai.domain.retrieval import QueryPlan, RetrievalRequest

REFERENCE = datetime(2026, 9, 2, tzinfo=UTC)


def _query_plan(query: str) -> QueryPlan:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            reference_time=REFERENCE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )


def _source(evidence_id: str, content: str, *, turn: int) -> dict[str, Any]:
    session_id = f"session-{evidence_id}"
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{session_id}/turn/{turn}",
        "subject_id": "fixture-user",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"turn-{turn}",
            "turn_ordinal": turn,
            "round_id": f"round-{turn}",
            "round_ordinal": turn,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
    }


def _accepted_span(
    evidence_id: str,
    requirement_id: str,
    text: str,
    *,
    source_ref: str,
) -> AcceptedBindingSpan:
    return AcceptedBindingSpan(
        requirement_ids=(requirement_id,),
        evidence_id=evidence_id,
        source_turn_ref=source_ref,
        session_id=source_ref.split("/")[2],
        speaker="user",
        start=0,
        end=len(text),
        text=text,
        observed_at=REFERENCE.isoformat(),
    )


def _evidence_set_item(
    span: AcceptedBindingSpan,
    requirement_role: str,
) -> EvidenceSetItem:
    return EvidenceSetItem(
        requirement_ids=span.requirement_ids,
        requirement_roles=(requirement_role,),
        evidence_id=span.evidence_id,
        source_turn_ref=span.source_turn_ref,
        session_id=span.session_id,
        source_role=span.speaker,
        start=span.start,
        end=span.end,
        text=span.text,
        observed_at=span.observed_at,
    )


def _snapshot(
    spans: list[AcceptedBindingSpan],
    evidence_set: EvidenceSet,
    *,
    accepted_evidence_ids: list[str] | None = None,
    lean_recall_mode: LeanRecallMode = "STRICT",
) -> DecisionSnapshot:
    return build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material={},
        lean_recall_mode=lean_recall_mode,
        lean_recall_plan_material={"mode": lean_recall_mode},
        evidence_set=evidence_set,
        accepted_evidence_ids=(
            accepted_evidence_ids
            if accepted_evidence_ids is not None
            else [span.evidence_id for span in spans]
        ),
        accepted_binding_spans=spans,
        required_requirement_ids=evidence_set.required_requirement_ids,
    )


def test_lean_recall_plan_separates_lookup_from_strict_operator_roles() -> None:
    lookup = compile_lean_recall_plan(
        _query_plan("What color is my bicycle lock?")
    )
    strict = compile_lean_recall_plan(
        _query_plan("How much did I pay per coffee mug for my coworkers?")
    )

    assert lookup.mode == "LOOKUP"
    assert lookup.operator is None
    assert {item.requirement_role for item in lookup.requirements} == {"ANSWER"}
    assert lean_decision_mode(_query_plan("What color is my bicycle lock?")) == (
        "ORDINARY_RECALL"
    )
    assert strict.mode == "STRICT"
    assert strict.operator == "DIVIDE_EVIDENCE_VALUES"
    assert {item.requirement_role for item in strict.requirements} == {
        "OPERAND_A",
        "OPERAND_B",
    }
    assert lean_decision_mode(
        _query_plan("How much did I pay per coffee mug for my coworkers?")
    ) == "STRICT_OPERATOR"


def test_latest_canonical_state_selection_remains_an_ordinary_lookup() -> None:
    plan = _query_plan("What is the current release status?")

    compiled = compile_lean_recall_plan(plan)

    assert plan.operator == "LATEST_VALID_STATE"
    assert compiled.mode == "LOOKUP"
    assert compiled.operator is None
    assert {item.requirement_role for item in compiled.requirements} == {"ANSWER"}
    assert lean_decision_mode(plan) == "ORDINARY_RECALL"
    assert _use_acquisition_composition(
        plan,
        {
            "status": "ABSTAINED",
            "operator": "LATEST_VALID_STATE",
            "reason": "STATE_VALUE_MISSING",
        },
    ) is False


def test_strict_operator_still_prefers_accepted_evidence_composition() -> None:
    plan = _query_plan("How much did I pay per coffee mug for my coworkers?")

    assert _use_acquisition_composition(
        plan,
        {
            "status": "COMPLETE",
            "operator": "DIVIDE_EVIDENCE_VALUES",
            "value": 12,
        },
    ) is True


def test_temporal_distance_when_clause_requires_two_distinct_event_roles() -> None:
    plan = _query_plan(
        "How many days ago did I launch my website when I signed a contract "
        "with my first client?"
    )

    assert plan.memory_query_ir is not None
    assert plan.operator == "TEMPORAL_DISTANCE"
    assert plan.operator_arguments["distance_mode"] == "between_events"
    assert plan.memory_query_ir.planner_trace.reason_code.endswith(
        "TWO_EVENT_TEMPORAL_DISTANCE"
    )
    assert [item.slot_id for item in plan.memory_query_ir.requirements] == [
        "EVENT_1",
        "EVENT_2",
    ]
    assert plan.memory_query_ir.requirements[0].entity_constraints == [
        "launch",
        "website",
    ]
    assert plan.memory_query_ir.requirements[1].entity_constraints == [
        "signed",
        "contract",
        "first",
        "client",
    ]


def test_strict_temporal_distance_rejects_entity_only_event_distractor() -> None:
    plan = _query_plan(
        "How many days ago did I launch my website when I signed a contract "
        "with my first client?"
    )
    assert plan.memory_query_ir is not None
    requirements = [
        item.model_copy(update={"temporal_constraints": None})
        for item in plan.memory_query_ir.requirements
    ]
    launched = _source(
        "launched",
        "Today I launched the redesigned portfolio website.",
        turn=1,
    )
    campaign = _source(
        "campaign",
        '2023-03-01,2023-03-24,"website - uk, ireland",active,20,Daily',
        turn=2,
    )
    signed = _source(
        "signed",
        "Today I signed a contract with the first design client.",
        turn=3,
    )
    spans = project_evidence_spans([launched, campaign, signed])
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(
        requirements,
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )
    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    span_by_id = {item.span_id: item for item in spans}
    matched_by_role = {
        requirement.slot_id: {
            span_by_id[interpretation_by_id[item.interpretation_id].span_id].source_evidence_id
            for item in bindings
            if item.requirement_id == requirement.slot_id and item.status == "MATCH"
        }
        for requirement in requirements
    }

    assert matched_by_role == {
        "EVENT_1": {"launched"},
        "EVENT_2": {"signed"},
    }


def test_strict_relative_event_requires_specific_sports_anchor() -> None:
    plan = _query_plan(
        "I mentioned participating in a sports event two weeks ago. "
        "What was the event?"
    )
    assert plan.memory_query_ir is not None
    requirement = plan.memory_query_ir.requirements[0].model_copy(
        update={"temporal_constraints": None}
    )
    correct = _source(
        "sports-event",
        "Today I will participate in the community's annual charity sports event.",
        turn=1,
    )
    wrong = _source(
        "generic-event",
        "Highlight networking opportunities gained by participating in your event.",
        turn=2,
    )
    spans = project_evidence_spans([correct, wrong])
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(
        [requirement],
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )
    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    span_by_id = {item.span_id: item for item in spans}
    matched = {
        span_by_id[interpretation_by_id[item.interpretation_id].span_id].source_evidence_id
        for item in bindings
        if item.status == "MATCH"
    }

    assert matched == {"sports-event"}


def test_raw_prose_bindings_never_authorize_a_strict_operator() -> None:
    plan = _query_plan("How much did I pay per coffee mug for my coworkers?")
    assert plan.memory_query_ir is not None
    assert plan.query_execution_plan is not None
    price = _source(
        "price",
        "I spent $60 on coffee mugs for my coworkers.",
        turn=1,
    )
    count = _source(
        "count",
        "I purchased exactly 5 coffee mugs for my coworkers.",
        turn=2,
    )
    distractor = _source(
        "unbound-noise",
        "A different team spent $6000 on 2 unrelated machines.",
        turn=3,
    )
    results = [distractor, price, count]
    spans = project_evidence_spans(results)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(
        plan.memory_query_ir.requirements,
        interpretations,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    accepted_bindings = [
        binding
        for binding in bindings
        if (
            binding.status == "MATCH"
            and span_by_id[
                interpretation_by_id[binding.interpretation_id].span_id
            ].source_evidence_id
            != "unbound-noise"
        )
    ]
    assert {item.requirement_id for item in accepted_bindings} == set(
        plan.query_execution_plan.completion.required_role_keys
    )

    result = execute_binding_backed_query_operator(
        plan,
        results,
        spans,
        interpretations,
        accepted_bindings,
    )

    assert result is not None
    assert result["status"] == "ABSTAINED"
    assert "operand_authority" not in result
    assert result["accepted_input_evidence_ids"] == []


def test_strict_reader_boundary_excludes_governed_but_unbound_noise() -> None:
    text = "The accepted value is 47."
    span = _accepted_span(
        "answer-support",
        "OPERAND_A",
        text,
        source_ref="memory://strict/turn/1",
    )
    evidence_set = EvidenceSet(
        required_requirement_ids=("OPERAND_A",),
        items=(_evidence_set_item(span, "OPERAND_A"),),
    )
    snapshot = _snapshot(
        [span],
        evidence_set,
        accepted_evidence_ids=["answer-support", "unbound-noise"],
    )
    interpretation = MemoryQueryInterpreter().interpret(
        "What is the accepted value?"
    )
    body = {
        "results": [
            {"kind": "EVIDENCE_OBSERVATION", "evidence_id": "answer-support"},
            {"kind": "EVIDENCE_OBSERVATION", "evidence_id": "unbound-noise"},
        ],
        "query_plan": {"planner_version": "query-planner-v0.2"},
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": False,
        "fallback_used": False,
    }

    outcome = _access_outcome(
        body,
        interpretation,
        decision_snapshot=snapshot,
        reader_evidence_policy=ReaderEvidencePolicy.GOVERNANCE_ADMITTED_SOFT_RANKED,
    )

    assert [item["evidence_id"] for item in outcome["items"]] == [
        "answer-support"
    ]
    assert outcome["accepted_binding_evidence_refs"] == ["answer-support"]
    assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"


def test_product08_completed_strict_informational_read_keeps_governed_context() -> None:
    query = "How much did I pay per ceramic planter?"
    plan = _query_plan(query)
    assert compile_lean_recall_plan(plan).mode == "STRICT"
    text = "I paid $60 for six ceramic planters."
    source_ref = "memory://strict/session-a/turn/1"
    span = _accepted_span(
        "answer-support",
        "TOTAL_PRICE",
        text,
        source_ref=source_ref,
    )
    evidence_set = EvidenceSet(
        required_requirement_ids=("ITEM_COUNT", "TOTAL_PRICE"),
        items=(_evidence_set_item(span, "OPERAND_A"),),
    )
    snapshot = _snapshot([span], evidence_set)
    serialized_plan = plan.model_dump(mode="json")
    serialized_plan["planner_version"] = (
        "query-planner-v0.2+formation-semantic-replay-v0.2"
    )
    body = {
        "results": [
            _source("answer-support", text, turn=1),
            _source("governed-unbound", "A related purchase was discussed.", turn=2),
        ],
        "query_plan": serialized_plan,
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": False,
        "fallback_used": False,
    }

    outcome = _access_outcome(
        body,
        MemoryQueryInterpreter().interpret(query),
        decision_snapshot=snapshot,
        informational_soft_admission_v0_2_enabled=True,
    )

    assert [item["evidence_id"] for item in outcome["items"]] == [
        "answer-support",
        "governed-unbound",
    ]
    assert outcome["accepted_binding_evidence_refs"] == ["answer-support"]
    assert outcome["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )


def test_product08_soft_admission_remains_fail_closed_at_hard_boundaries() -> None:
    query = "How many pending errands are recorded?"
    plan = _query_plan(query)
    snapshot = _snapshot(
        [],
        EvidenceSet(required_requirement_ids=("MATCHING_EVENTS_IN_RANGE",)),
    )
    base = {
        "results": [_source("candidate-only", "I need to collect a watch.", turn=1)],
        "query_plan": plan.model_dump(mode="json"),
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": True,
        "fallback_used": False,
    }
    blocked = (
        {**base, "open_issue_ids": ["issue-1"]},
        {**base, "degraded_components": ["projection_unavailable"]},
        {**base, "abstention_reason": "ACCESS_DENIED"},
        {**base, "abstention_reason": "CANONICAL_UNAVAILABLE"},
    )

    for body in blocked:
        outcome = _access_outcome(
            body,
            MemoryQueryInterpreter().interpret(query),
            decision_snapshot=snapshot,
            informational_soft_admission_v0_2_enabled=True,
        )
        assert outcome["items"] == []
        assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"


def test_incomplete_strict_informational_read_keeps_governed_partial_context() -> None:
    snapshot = _snapshot(
        [],
        EvidenceSet(required_requirement_ids=("MATCHING_EVENTS_IN_RANGE",)),
    )
    query = "How many pending errands are recorded?"
    plan = _query_plan(query)
    assert plan.memory_query_ir is not None
    serialized_plan = plan.model_dump(mode="json")
    assert isinstance(serialized_plan["memory_query_ir"], dict)
    serialized_plan["memory_query_ir"]["mode"] = "AMBIGUOUS"
    body = {
        "results": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "pending-errand",
                "source_ref": "memory://strict/turn/1",
                "content": "user: I still need to collect the repaired watch.",
            }
        ],
        "query_plan": serialized_plan,
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": True,
        "abstention_reason": "SUFFICIENCY_UNBOUNDED_QUERY_AMBIGUOUS",
        "fallback_used": False,
    }

    outcome = _access_outcome(
        body,
        MemoryQueryInterpreter().interpret(query),
        decision_snapshot=snapshot,
        informational_soft_admission_v0_2_enabled=True,
    )

    assert outcome["status"] == "PARTIAL"
    assert outcome["abstention_reason"] == "SUFFICIENCY_UNBOUNDED_QUERY_AMBIGUOUS"
    assert outcome["accepted_binding_evidence_refs"] == []
    assert [item["evidence_id"] for item in outcome["items"]] == ["pending-errand"]
    assert outcome["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )


def test_incomplete_strict_action_safe_read_remains_decision_accepted_only() -> None:
    snapshot = _snapshot(
        [],
        EvidenceSet(required_requirement_ids=("MATCHING_EVENTS_IN_RANGE",)),
    )
    query = "How many pending errands are recorded?"
    plan = _query_plan(query).model_copy(update={"required_authority": "ACTION_SAFE"})
    body = {
        "results": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "pending-errand",
                "source_ref": "memory://strict/turn/1",
                "content": "user: I still need to collect the repaired watch.",
            }
        ],
        "query_plan": plan.model_dump(mode="json"),
        "progressive_l1": {
            "terminal_sufficiency_decision": {
                "status": "UNBOUNDED",
                "missing_slots": ["MATCHING_EVENTS_IN_RANGE"],
            }
        },
        "open_issue_ids": [],
        "degraded_components": [],
        "abstained": True,
        "abstention_reason": "SUFFICIENCY_UNBOUNDED_QUERY_AMBIGUOUS",
        "fallback_used": False,
    }

    outcome = _access_outcome(
        body,
        MemoryQueryInterpreter().interpret(query),
        decision_snapshot=snapshot,
        informational_soft_admission_v0_2_enabled=True,
    )

    assert outcome["status"] == "ABSTAINED"
    assert outcome["items"] == []
    assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"


def test_lookup_reader_boundary_uses_the_minimal_grounded_evidence_set() -> None:
    text = "My bicycle lock is teal."
    span = _accepted_span(
        "lookup-answer",
        "LOOKUP_ANSWER",
        text,
        source_ref="memory://lookup/turn/1",
    )
    evidence_set = EvidenceSet(
        required_requirement_ids=("LOOKUP_ANSWER",),
        items=(_evidence_set_item(span, "ANSWER"),),
    )
    snapshot = _snapshot(
        [span],
        evidence_set,
        accepted_evidence_ids=["lookup-answer", "related-but-unbound"],
        lean_recall_mode="LOOKUP",
    )
    outcome = _access_outcome(
        {
            "results": [
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": "lookup-answer",
                    "source_ref": "memory://lookup/turn/1",
                },
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": "related-but-unbound",
                    "source_ref": "memory://lookup/turn/2",
                },
            ],
            "query_plan": {"planner_version": "query-planner-v0.2"},
            "open_issue_ids": [],
            "degraded_components": [],
            "abstained": False,
            "fallback_used": False,
        },
        MemoryQueryInterpreter().interpret("What color is my bicycle lock?"),
        decision_snapshot=snapshot,
        reader_evidence_policy=ReaderEvidencePolicy.DECISION_ACCEPTED_ONLY,
    )

    assert [item["evidence_id"] for item in outcome["items"]] == ["lookup-answer"]
    assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"

    acquisition_only = _access_outcome(
        {
            "results": [
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": "lookup-answer",
                    "source_ref": "memory://lookup/turn/1",
                },
                {
                    "kind": "EVIDENCE_OBSERVATION",
                    "evidence_id": "related-but-unbound",
                    "source_ref": "memory://lookup/turn/2",
                },
            ],
            "query_plan": {"planner_version": "query-planner-v0.2"},
            "open_issue_ids": [],
            "degraded_components": [],
            "abstained": False,
            "fallback_used": False,
        },
        MemoryQueryInterpreter().interpret("What color is my bicycle lock?"),
        decision_snapshot=snapshot,
        reader_evidence_policy=ReaderEvidencePolicy.GOVERNANCE_ADMITTED_SOFT_RANKED,
    )
    assert [item["evidence_id"] for item in acquisition_only["items"]] == [
        "lookup-answer",
        "related-but-unbound",
    ]
    assert acquisition_only["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )
    compiled = MemoryContextCompiler(budget_stable_enabled=True).compile(
        MemoryResolveRequest(query="What color is my bicycle lock?"),
        acquisition_only,
        decision_snapshot=snapshot,
    )
    trace = compiled.memory_context.compile_trace
    assert trace["acquired_candidate_trace"]["candidate_count"] == 2
    assert trace["bound_evidence_trace"]["item_count"] == 1
    assert trace["raw_retrieval_trace"] == trace["acquired_candidate_trace"]
    assert trace["reader_visible_trace"]["serialization_replay_equivalent"] is True


def test_lookup_reader_boundary_does_not_fall_back_when_evidence_set_is_empty() -> None:
    snapshot = _snapshot(
        [],
        EvidenceSet(required_requirement_ids=("LOOKUP_ANSWER",)),
        accepted_evidence_ids=["candidate-only"],
        lean_recall_mode="LOOKUP",
    )

    outcome = _access_outcome(
        {
            "results": [
                {"kind": "EVIDENCE_OBSERVATION", "evidence_id": "candidate-only"}
            ],
            "query_plan": {"planner_version": "query-planner-v0.2"},
            "open_issue_ids": [],
            "degraded_components": [],
            "abstained": False,
            "fallback_used": False,
        },
        MemoryQueryInterpreter().interpret("What color is my bicycle lock?"),
        decision_snapshot=snapshot,
        reader_evidence_policy=ReaderEvidencePolicy.DECISION_ACCEPTED_ONLY,
    )

    assert outcome["items"] == []
    assert outcome["evidence_refs"] == []
    assert outcome["accepted_binding_evidence_refs"] == []
    assert outcome["_reader_evidence_boundary"] == "DECISION_ACCEPTED_ONLY"

    default_outcome = _access_outcome(
        {
            "results": [
                {"kind": "EVIDENCE_OBSERVATION", "evidence_id": "candidate-only"}
            ],
            "query_plan": {"planner_version": "query-planner-v0.2"},
            "open_issue_ids": [],
            "degraded_components": [],
            "abstained": False,
            "fallback_used": False,
        },
        MemoryQueryInterpreter().interpret("What color is my bicycle lock?"),
        decision_snapshot=snapshot,
    )
    assert [item["evidence_id"] for item in default_outcome["items"]] == [
        "candidate-only"
    ]
    assert default_outcome["_reader_evidence_boundary"] == (
        "GOVERNANCE_ADMITTED_SOFT_RANKED"
    )


def test_ordinary_lookup_binds_asserted_relation_but_rejects_question_and_role_noise() -> None:
    plan = _query_plan(
        "What was the amount I was pre-approved for when I got my mortgage "
        "from Wells Fargo?"
    )
    assert plan.memory_query_ir is not None
    asserted = _source(
        "asserted-answer",
        "I got pre-approved for $350,000 from Wells Fargo.",
        turn=1,
    )
    question_only = _source(
        "question-only",
        "Remember when I got pre-approved for $400,000 from Wells Fargo?",
        turn=2,
    )
    assistant_echo = {
        **_source(
            "assistant-echo",
            "You got pre-approved for $999,000 from Wells Fargo.",
            turn=3,
        ),
        "speaker": "assistant",
    }
    spans = project_evidence_spans([asserted, question_only, assistant_echo])
    interpretations = interpret_evidence_spans(spans)

    bindings = bind_requirements(
        plan.memory_query_ir.requirements,
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )

    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    span_by_id = {item.span_id: item for item in spans}
    matched_evidence_ids = {
        span_by_id[interpretation_by_id[binding.interpretation_id].span_id].source_evidence_id
        for binding in bindings
        if binding.status == "MATCH"
    }
    # Semantic participant and Evidence speaker are independent.  With no
    # explicit source restriction, both the user's assertion and an assistant
    # paraphrase can ground the user's mortgage fact; question-only text cannot.
    assert matched_evidence_ids == {"asserted-answer", "assistant-echo"}


def test_strict_reader_suppresses_an_unauthorized_completion_mapping() -> None:
    text = "The accepted value is 47."
    span = _accepted_span(
        "answer-support",
        "OPERAND_A",
        text,
        source_ref="memory://strict/turn/1",
    )
    evidence_set = EvidenceSet(
        required_requirement_ids=("OPERAND_A",),
        items=(_evidence_set_item(span, "OPERAND_A"),),
    )
    snapshot = _snapshot([span], evidence_set)
    outcome = _access_outcome(
        {
            "results": [
                {"kind": "EVIDENCE_OBSERVATION", "evidence_id": "answer-support"}
            ],
            "query_plan": {"planner_version": "query-planner-v0.2"},
            "derived_result": {
                "status": "COMPLETE",
                "kind": "DERIVED_QUERY_RESULT",
                "operator": "SUM_VALUES",
                "value": 999,
                "operands": [{"evidence_id": "unbound-noise"}],
            },
            "open_issue_ids": [],
            "degraded_components": [],
            "abstained": False,
            "fallback_used": False,
        },
        MemoryQueryInterpreter().interpret("What is the accepted value?"),
        decision_snapshot=snapshot,
    )

    assert outcome["derived_result"] is None
    assert [item["evidence_id"] for item in outcome["items"]] == ["answer-support"]


def test_context_orders_one_atomic_span_per_role_before_same_role_depth() -> None:
    span_a1 = _accepted_span(
        "a-1",
        "OPERAND_A",
        "First A operand.",
        source_ref="memory://a/turn/1",
    )
    span_a2 = _accepted_span(
        "a-2",
        "OPERAND_A",
        "Additional A provenance.",
        source_ref="memory://a/turn/2",
    )
    span_b1 = _accepted_span(
        "b-1",
        "OPERAND_B",
        "First B operand.",
        source_ref="memory://z/turn/1",
    )
    spans = [span_a1, span_a2, span_b1]
    evidence_set = EvidenceSet(
        required_requirement_ids=("OPERAND_A", "OPERAND_B"),
        items=tuple(
            _evidence_set_item(
                span,
                "OPERAND_A" if span.requirement_ids == ("OPERAND_A",) else "OPERAND_B",
            )
            for span in spans
        ),
    )
    snapshot = _snapshot(spans, evidence_set)
    request = MemoryResolveRequest(
        query="Compare the two operands",
        budget=MemoryResolveBudget(max_context_tokens=512),
    )
    compiler = MemoryContextCompiler()
    planned = compiler.plan(
        request,
        {
            "status": "HIT",
            "items": [],
            "open_issue_ids": [],
            "sufficiency_decision": {
                "status": "COMPLETE",
                "covered_slots": ["OPERAND_A", "OPERAND_B"],
                "missing_slots": [],
            },
            "derived_result": None,
            "_reader_evidence_boundary": "DECISION_ACCEPTED_ONLY",
        },
        decision_snapshot=snapshot,
    )

    protected_bindings = [
        unit
        for unit in planned.reader_evidence_plan.protected_units
        if unit.unit_id.startswith("binding:")
    ]
    conditional_bindings = [
        unit
        for unit in planned.reader_evidence_plan.conditional_units
        if unit.unit_id.startswith("binding:")
    ]
    assert [unit.requirement_ids for unit in protected_bindings] == [
        ("OPERAND_A",),
        ("OPERAND_B",),
    ]
    assert len(conditional_bindings) == 1
    assert conditional_bindings[0].requirement_ids == ("OPERAND_A",)
    assert all(unit.atomic is True for unit in [*protected_bindings, *conditional_bindings])
    rendered = compiler.render(
        planned,
        ContextBudgetEnvelope(
            requested_cap=512,
            available_memory_tokens=512,
            budget_source="CALLER_CAP_ONLY",
        ),
    )
    lifecycle = rendered.memory_context.compile_trace["evidence_lifecycle_trace"]
    assert isinstance(lifecycle, dict)
    lifecycle_items = lifecycle["items"]
    assert isinstance(lifecycle_items, list)
    assert all(isinstance(item, dict) for item in lifecycle_items)
    assert lifecycle["schema_version"] == "evidence-lifecycle-trace-v0.1"
    assert {item["evidence_id"] for item in lifecycle_items} == {
        "a-1",
        "a-2",
        "b-1",
    }
    assert all(item["bound"] is True for item in lifecycle_items)
    assert all(item["reader_visible"] is True for item in lifecycle_items)
    assert all(item["serialized_ranges"] for item in lifecycle_items)
