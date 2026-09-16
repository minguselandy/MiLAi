from __future__ import annotations

from datetime import UTC, datetime

from milai.application.evidence_semantics import (
    project_evidence_spans,
    run_type_directed_semantics,
)
from milai.application.quantity_composition import compose_divide_evidence_values
from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_operators import (
    execute_binding_backed_query_operator,
    execute_query_operator,
)
from milai.application.query_planner import QueryPlanner
from milai.application.sufficiency import decide_sufficiency
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)


def _request(query: str) -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query=query,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )


def _evidence(
    evidence_id: str,
    content: str,
    *,
    observed_at: str = "2023-03-01T09:00:00+00:00",
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "evidence_ids": [evidence_id],
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "subject_id": evidence_id,
        "observed_at": observed_at,
        "captured_at": "2023-03-01T09:00:01+00:00",
        "content": content,
        "authority": "EVIDENCE_ONLY",
        "canonical": False,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
    }


def test_q4_temporal_order_executes_over_unseen_events_and_is_order_stable() -> None:
    request = _request("Which happened earlier, planting the cedar tree or painting the shed?")
    plan = QueryPlanner().plan(request)
    inputs = [
        _evidence(
            "tree",
            "user: Planting the cedar tree happened on January 10th.",
        ),
        _evidence(
            "shed",
            "user: Painting the shed happened on February 3rd.",
        ),
    ]

    forward = execute_query_operator(plan, inputs)
    reverse = execute_query_operator(plan, list(reversed(inputs)))

    assert plan.memory_query_ir is not None
    assert infer_operator_family(plan.memory_query_ir) == "TEMPORAL_ORDER"
    assert forward is not None and reverse is not None
    assert forward["status"] == reverse["status"] == "OK"
    assert forward["value"] == reverse["value"]
    assert "cedar tree" in forward["value"]["selected"].casefold()
    assert forward["completeness"] == {
        "required_slots": ["EVENT_1", "EVENT_2"],
        "filled_slots": ["EVENT_1", "EVENT_2"],
        "unresolved_reasons": [],
    }
    assert forward["operands"][0]["authority_class"] == "EVIDENCE_ONLY"
    assert forward["operands"][0]["source_timestamp"].startswith("2023-03-01")
    assert forward["operands"][0]["derived_time"].startswith("2023-01-10")
    assert forward["operands"][0]["system_timestamp"].startswith("2023-03-01")


def test_q4_temporal_distance_supports_paraphrase_and_two_events_in_one_turn() -> None:
    request = _request(
        "What is the elapsed time in days from the robotics demo to the choir concert?"
    )
    plan = QueryPlanner().plan(request)
    result = execute_query_operator(
        plan,
        [
            _evidence(
                "two-events",
                (
                    "user: The robotics demo was on January 10th. "
                    "The choir concert was on February 3rd."
                ),
            )
        ],
    )

    assert plan.operator == "TEMPORAL_DISTANCE"
    assert plan.operator_arguments["route_reason"] == ("MEMORY_QUERY_IR_V02_TEMPORAL_DISTANCE")
    assert result is not None
    assert result["status"] == "OK"
    assert result["value"] == 24
    assert result["unit"] == "days"
    assert len(result["operands"]) == 2
    assert {operand["time_basis"] for operand in result["operands"]} == {"EXPLICIT_CALENDAR_DATE"}


def test_binding_backed_distance_uses_typed_slots_instead_of_reparsing_full_turns() -> None:
    plan = QueryPlanner().plan(
        _request(
            "How many days before the team meeting I was preparing for did I attend "
            "the workshop on 'Effective Communication in the Workplace'?"
        )
    )
    workshop = _evidence(
        "workshop",
        (
            "user: I'm preparing for an upcoming meeting with my team. "
            "I recently attended a workshop on Effective Communication in the "
            "Workplace on January 10th."
        ),
        observed_at="2023-01-13T01:02:00+00:00",
    )
    meeting = _evidence(
        "meeting",
        "user: I am preparing for my upcoming team meeting on January 17th.",
        observed_at="2023-01-13T13:59:00+00:00",
    )
    results = [workshop, meeting]
    spans = project_evidence_spans(results)
    interpretations, bindings, _audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,  # type: ignore[union-attr]
        spans,
        compatibility_profile="dg22-v0.2",
    )

    preparing_span_ids = {
        span.span_id for span in spans if "upcoming meeting with my team" in span.text
    }
    assert preparing_span_ids
    assert any(
        binding.requirement_id == "EVENT_2"
        and binding.status == "REJECTED"
        and binding.reason_code == "PREDICATE_INCOMPATIBLE"
        and next(
            item.span_id
            for item in interpretations
            if item.interpretation_id == binding.interpretation_id
        )
        in preparing_span_ids
        for binding in bindings
    )

    result = execute_binding_backed_query_operator(
        plan,
        results,
        spans,
        interpretations,
        bindings,
    )

    assert result is not None and result["status"] == "OK"
    assert result["value"] == 7
    assert [item["source_ref"] for item in result["operands"]] == [
        "memory://session/workshop/turn/0",
        "memory://session/meeting/turn/0",
    ]
    assert "workshop" in result["operands"][0]["source_span"].casefold()
    assert "January 17th" in result["operands"][1]["source_span"]


def test_binding_backed_event_rejects_metalinguistic_restatement_as_proof() -> None:
    plan = QueryPlanner().plan(
        _request(
            "How many days had passed between the Hindu festival of Holi and the "
            "Sunday mass at St. Mary's Church?"
        )
    )
    original = _evidence(
        "holi-original",
        "user: I attended the Hindu festival of Holi on February 26th.",
    )
    restatement = _evidence(
        "holi-restatement",
        (
            "user: I noticed that you mentioned attending the Hindu festival of Holi "
            "on February 26th."
        ),
        observed_at="2023-03-20T09:00:00+00:00",
    )
    mass = _evidence(
        "mass",
        "user: I attended Sunday mass at St. Mary's Church on March 19th.",
    )
    results = [restatement, mass, original]
    spans = project_evidence_spans(results)
    interpretations, bindings, _audit = run_type_directed_semantics(
        plan.memory_query_ir.requirements,  # type: ignore[union-attr]
        spans,
        compatibility_profile="dg22-v0.2",
    )
    span_by_interpretation = {
        item.interpretation_id: next(span for span in spans if span.span_id == item.span_id)
        for item in interpretations
    }

    assert any(
        binding.requirement_id == "EVENT_1"
        and binding.status == "REJECTED"
        and span_by_interpretation[binding.interpretation_id].source_evidence_id
        == "holi-restatement"
        for binding in bindings
    )
    result = execute_binding_backed_query_operator(
        plan,
        results,
        spans,
        interpretations,
        bindings,
    )

    assert result is not None and result["value"] == 21
    assert [item["source_ref"] for item in result["operands"]] == [
        "memory://session/holi-original/turn/0",
        "memory://session/mass/turn/0",
    ]


def test_q4_removing_a_required_event_forces_typed_abstention() -> None:
    request = _request("Which happened earlier, planting the cedar tree or painting the shed?")
    plan = QueryPlanner().plan(request)
    results = [_evidence("tree", "user: Planting the cedar tree was on January 10th.")]
    derived = execute_query_operator(plan, results)
    decision, reason = decide_sufficiency(
        request,
        plan,
        results,
        [],
        derived,
        stage="FINAL",
    )

    assert derived is not None
    assert derived["status"] == "ABSTAINED"
    assert derived["reason"] == "OPERAND_MISSING"
    assert decision.status == "UNSATISFIED"
    assert decision.missing_slots == ["EVENT_1", "EVENT_2"]
    assert reason == "OPERAND_MISSING"


def test_q4_raw_evidence_source_time_cannot_supply_missing_event_time() -> None:
    plan = QueryPlanner().plan(
        _request("Which happened earlier, planting the cedar tree or painting the shed?")
    )
    derived = execute_query_operator(
        plan,
        [
            _evidence("tree", "user: I planted the cedar tree."),
            _evidence("shed", "user: I painted the shed."),
        ],
    )

    assert derived is not None
    assert derived["status"] == "ABSTAINED"
    assert derived["reason"] == "OPERAND_MISSING"


def test_q4_relative_raw_evidence_uses_source_time_as_anchor_not_event_time() -> None:
    plan = QueryPlanner().plan(
        _request("Which happened earlier, meeting Ana or painting the shed?")
    )
    inputs = [
        _evidence(
            "ana",
            "user: I met Ana a few months ago.",
            observed_at="2023-05-28T12:00:00+00:00",
        ),
        _evidence(
            "shed",
            "user: I painted the shed yesterday.",
            observed_at="2023-05-28T12:00:00+00:00",
        ),
    ]

    forward = execute_query_operator(plan, inputs)
    reverse = execute_query_operator(plan, list(reversed(inputs)))

    assert forward is not None and reverse is not None
    assert forward["status"] == reverse["status"] == "OK"
    assert forward["value"] == reverse["value"]
    assert "ana" in forward["value"]["selected"].casefold()
    assert {item["time_basis"] for item in forward["operands"]} == {
        "RELATIVE_TO_SOURCE_OBSERVED_TIME"
    }
    assert all(item["authority_class"] == "EVIDENCE_ONLY" for item in forward["operands"])


def test_q4_mention_time_query_explicitly_uses_source_observed_axis() -> None:
    request = _request(
        "I mentioned cooking something for my friend a couple of days ago. What was it?"
    )
    plan = QueryPlanner().plan(request)
    derived = execute_query_operator(
        plan,
        [
            _evidence(
                "cake",
                "user: I baked a chocolate cake for my friend last weekend.",
                observed_at="2023-03-25T12:00:00+00:00",
            )
        ],
    )

    assert plan.memory_query_ir is not None
    temporal = plan.memory_query_ir.constraints.normalized_temporal
    assert temporal is not None and temporal.time_axis == "SOURCE_OBSERVED_TIME"
    assert plan.operator_arguments["time_axis"] == "SOURCE_OBSERVED_TIME"
    assert derived is not None and derived["status"] == "OK"
    assert "chocolate cake" in derived["value"]["selected"]
    assert derived["operands"][0]["time_axis"] == "SOURCE_OBSERVED_TIME"
    assert derived["operands"][0]["time_basis"] == "SOURCE_OBSERVED_TIME"


def test_q3_divide_paraphrase_reaches_existing_deterministic_composer() -> None:
    plan = QueryPlanner().plan(_request("How much did I pay per ceramic planter?"))
    result = compose_divide_evidence_values(
        plan,
        [
            _evidence("price", "user: I paid $30 for ceramic planters."),
            _evidence("count", "user: I bought 3 ceramic planters."),
        ],
    )

    assert plan.operator == "DIVIDE_EVIDENCE_VALUES"
    assert result is not None
    assert result["status"] == "COMPLETE"
    assert result["value"] == 10
    assert result["hidden_model_calls"] == 0
    assert result["canonical_mutation"] is False
