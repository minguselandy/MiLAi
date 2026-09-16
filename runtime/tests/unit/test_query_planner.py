from __future__ import annotations

from datetime import UTC, datetime

from milai.application.query_ir_compat import infer_operator_family
from milai.application.query_planner import QueryPlanner
from milai.domain import RetrievalRequest


def test_query_planner_emits_versioned_safe_l1_plan_without_raw_query() -> None:
    request = RetrievalRequest.model_validate(
        {
            "route": "L1",
            "query": "sensitive synthetic query",
            "requested_scope": {"project_ids": ["milai"]},
            "consistency": "READ_YOUR_WRITES",
            "causal_token": "opaque-test-token",
        }
    )
    plan = QueryPlanner().plan(request, minimum_outbox_sequence=42)
    encoded = plan.model_dump_json()
    assert plan.planner_version == "lean-query-plan-v12-dg17-ir-v02"
    assert plan.minimum_outbox_sequence == 42
    assert "minimum_commit_seq" not in plan.model_dump()
    assert plan.routes == ["L1"]
    assert plan.intent == "HYBRID_SEARCH"
    assert plan.required_lifecycle == "ACTIVE"
    assert plan.accepted_epistemic_statuses == ["VERIFIED", "PROVISIONAL"]
    assert plan.required_freshness == "CURRENT"
    assert "sensitive synthetic query" not in encoded
    assert "opaque-test-token" not in encoded
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.schema_version == "memory-query-ir-v0.2"


def test_query_planner_keeps_snapshot_cutoff_out_of_temporal_query_semantics() -> None:
    reference = datetime(2023, 1, 13, 12, tzinfo=UTC)
    snapshot = datetime(2023, 1, 13, 23, 36, tzinfo=UTC)
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="Which event happened a week ago?",
            as_of=snapshot,
            reference_time=reference,
            system_as_of=snapshot,
        )
    )

    assert plan.time_reference == reference
    assert plan.time_constraint == {
        "valid_as_of": snapshot.isoformat(),
        "query_reference_time": reference.isoformat(),
        "system_as_of": snapshot.isoformat(),
    }
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.constraints.normalized_temporal is not None
    assert plan.memory_query_ir.constraints.normalized_temporal.reference_time == reference


def test_l0_exact_state_uses_canonical_gate_without_latest_state_operator() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L0",
            claim_id="11111111-1111-4111-8111-111111111111",
            requested_scope={"project_ids": ["milai"]},
        )
    )

    assert plan.operator is None
    assert plan.operator_arguments == {}
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.requirements[0].slot_id == "EXACT_STATE"
    assert plan.memory_query_ir.steps[0].constraints["exact_address"] is True


def test_elapsed_duration_fact_lookup_does_not_invoke_two_event_operator() -> None:
    request = RetrievalRequest.model_validate(
        {
            "route": "L1",
            "query": "How long did it take me to assemble the IKEA bookshelf?",
            "requested_scope": {"project_ids": ["milai"]},
        }
    )
    plan = QueryPlanner().plan(request)
    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_amount_lookup_with_last_weekday_preserves_retrieved_evidence() -> None:
    request = RetrievalRequest.model_validate(
        {
            "route": "L1",
            "query": "How much cashback did I earn at SaveMart last Thursday?",
            "requested_scope": {"project_ids": ["milai"]},
        }
    )
    plan = QueryPlanner().plan(request)
    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_fact_qualifiers_and_incomplete_aggregations_fall_back_to_recall() -> None:
    queries = [
        "Who did I meet with during lunch last Tuesday?",
        "What game did I finally beat last weekend?",
        "What percentage of packed shoes did I wear on my last trip?",
        (
            "What is the order of the three sports events I participated in, "
            "from earliest to latest?"
        ),
        "How many hours do I work in a typical week during peak campaign seasons?",
        "How many years older am I than when I graduated from college?",
        "How much more did I pay after the initial quote?",
        "Where did Rachel move to after her recent relocation?",
        "What was my last name before I changed it?",
    ]

    for query in queries:
        plan = QueryPlanner().plan(RetrievalRequest(route="L1", query=query))
        assert plan.operator is None, query
        assert plan.operator_arguments == {}, query


def test_operator_routes_carry_complete_typed_slot_schema() -> None:
    queries = [
        "How many bikes do I own?",
        "What is the total amount?",
        "What is the difference between the first and second values?",
        "How many days passed between the first event and the second event?",
    ]

    for query in queries:
        plan = QueryPlanner().plan(RetrievalRequest(route="L1", query=query))
        assert plan.operator is not None, query
        assert plan.operator_arguments["slot_schema_version"] == "typed-operator-v1"
        assert plan.operator_arguments["route_reason"]
        assert plan.operator_arguments["operand_type"]


def test_preference_is_characterized_without_promoting_a_legacy_executor() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(route="L1", query="What was my latest preference?")
    )

    assert plan.memory_query_ir is not None
    assert infer_operator_family(plan.memory_query_ir) == "PREFERENCE_RESOLVE"
    assert plan.operator is None
    assert plan.operator_arguments == {}


def test_binary_event_order_requires_two_confident_typed_anchors() -> None:
    routed = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=(
                "Which event happened first, my participation in the "
                "#PlankChallenge or my post about vegan chili recipe?"
            ),
        )
    )
    ambiguous = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="Who became a parent first, Rachel or Alex?",
        )
    )

    assert routed.operator == "TEMPORAL_BEFORE_AFTER"
    assert routed.operator_arguments["target_mode"] == "binary_ordering"
    assert routed.operator_arguments["ordering"] == "earliest"
    anchors = routed.operator_arguments["event_anchor_terms"]
    assert "plankchallenge" in anchors[0]
    assert {"chili", "post", "recipe", "vegan"} <= set(anchors[1])
    assert ambiguous.operator is None
    assert ambiguous.operator_arguments == {}
    assert ambiguous.memory_query_ir is not None
    assert ambiguous.memory_query_ir.mode == "AMBIGUOUS"
