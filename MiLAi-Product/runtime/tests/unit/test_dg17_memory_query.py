from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_ir_compat import (
    infer_operator_family,
    translate_memory_query_ir_v01,
    v01_translation_digest,
)

REFERENCE = datetime(2023, 3, 27, 23, 35, tzinfo=UTC)


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("Which espresso machine did I get 10 days ago?", "TEMPORAL_FILTER"),
        (
            "I mentioned cooking something for my friend a couple of days ago. What was it?",
            "TEMPORAL_FILTER",
        ),
        (
            "How many days had passed between Holi and the Sunday mass at St. Mary's?",
            "TEMPORAL_DISTANCE",
        ),
        (
            "How many days before the team meeting did I attend the communication workshop?",
            "TEMPORAL_DISTANCE",
        ),
        (
            "How many babies were born to friends and family in the last few months?",
            "COUNT",
        ),
        ("How many times did I bake something in the past two weeks?", "COUNT"),
        ("Who did I meet first, Mark and Sarah or Tom?", "TEMPORAL_ORDER"),
        ("What game did I finally beat last weekend?", "LOOKUP"),
    ],
)
def test_q3a_current_query_shapes_compile_to_compositional_v02(query: str, family: str) -> None:
    ir = MemoryQueryCompiler().compile(query, reference_time=REFERENCE)

    assert ir.schema_version == "memory-query-ir-v0.2"
    assert infer_operator_family(ir) == family
    assert ir.planner_trace.source == "DETERMINISTIC"
    assert ir.planner_trace.auxiliary_model_calls == 0
    assert ir.requirements
    assert all(requirement.required for requirement in ir.requirements)
    bound = {output for step in ir.steps if step.kind == "BIND_SLOT" for output in step.outputs}
    assert {requirement.slot_id for requirement in ir.requirements} <= bound


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("How many times did I repair a bicycle in the past two weeks?", "COUNT"),
        (
            "Which happened earlier, planting the cedar tree or painting the shed?",
            "TEMPORAL_ORDER",
        ),
        (
            "What is the elapsed time in days from the robotics demo to the choir concert?",
            "TEMPORAL_DISTANCE",
        ),
        ("How much did I pay per ceramic planter?", "DIVIDE"),
    ],
)
def test_q3a_plan_generalizes_to_unseen_entity_event_and_paraphrase(
    query: str, family: str
) -> None:
    ir = MemoryQueryCompiler().compile(query, reference_time=REFERENCE)

    assert infer_operator_family(ir) == family
    assert ir.constraints.cue_spans
    assert all(requirement.entity_constraints for requirement in ir.requirements)


@pytest.mark.parametrize(
    "query",
    [
        "What is the phone number of my dentist?",
        "Which serial number did I record for the camera?",
        "What tracking number did the assistant share earlier?",
    ],
)
def test_identifier_number_queries_remain_scalar_lookups(query: str) -> None:
    ir = MemoryQueryCompiler().compile(query, reference_time=REFERENCE)

    assert infer_operator_family(ir) == "LOOKUP"
    assert ir.completeness == "TOP_K_ACCEPTABLE"
    assert [requirement.slot_id for requirement in ir.requirements] == ["LOOKUP_ANSWER"]


@pytest.mark.parametrize(
    "query",
    [
        "What is the number of parcels waiting for collection?",
        "Tell me the total number of appointments in March.",
        "How many garments still need collection?",
    ],
)
def test_collection_cardinality_phrases_remain_counts(query: str) -> None:
    ir = MemoryQueryCompiler().compile(query, reference_time=REFERENCE)

    assert infer_operator_family(ir) == "COUNT"
    assert ir.completeness == "ALL_MATCHES_IN_RANGE"


def test_q3a_relative_point_and_range_are_distinct_normalized_constraints() -> None:
    point = MemoryQueryCompiler().compile(
        "What appliance did I buy 10 days ago?", reference_time=REFERENCE
    )
    bounded = MemoryQueryCompiler().compile(
        "How many times did I bake in the past two weeks?", reference_time=REFERENCE
    )
    point_time = point.constraints.normalized_temporal
    bounded_time = bounded.constraints.normalized_temporal

    assert point_time is not None and point_time.boundary == "POINT"
    assert point_time.start == point_time.end == REFERENCE - timedelta(days=10)
    assert bounded_time is not None and bounded_time.boundary == "CLOSED_OPEN"
    assert bounded_time.start == REFERENCE - timedelta(days=14)
    assert bounded_time.end == REFERENCE
    assert bounded.completeness == "ALL_MATCHES_IN_RANGE"


def test_q3a_relative_point_preserves_typed_operator_and_requirement_identity() -> None:
    compiler = MemoryQueryCompiler()
    query = "What appliance did I buy 10 days ago?"

    legacy = compiler.compile_v01(query, reference_time=REFERENCE)
    translated = translate_memory_query_ir_v01(legacy, query=query)
    product = compiler.compile(query, reference_time=REFERENCE)

    for query_ir in (translated, product):
        assert infer_operator_family(query_ir) == "TEMPORAL_FILTER"
        assert [requirement.slot_id for requirement in query_ir.requirements] == [
            "TARGET_EVENT"
        ]
        assert query_ir.requirements[0].interpretation_kind == "EVENT"
        assert query_ir.requirements[0].temporal_constraints is not None


def test_q3a_unknown_operator_falls_back_to_reader_recall_without_guessing() -> None:
    ir = MemoryQueryCompiler().compile(
        "What was the average percentage across every memory?",
        reference_time=REFERENCE,
    )

    assert ir.mode == "EVIDENCE"
    assert ir.steps
    assert ir.requirements
    assert ir.planner_trace.source == "DETERMINISTIC"
    assert ir.planner_trace.auxiliary_model_calls == 0


def test_q4_since_when_distance_keeps_both_event_anchors() -> None:
    ir = MemoryQueryCompiler().compile(
        "How many days had passed since I started ukulele lessons when I serviced my guitar?",
        reference_time=REFERENCE,
    )

    assert infer_operator_family(ir) == "TEMPORAL_DISTANCE"
    assert [requirement.slot_id for requirement in ir.requirements] == [
        "EVENT_1",
        "EVENT_2",
    ]


def test_q3a_v01_translation_remains_receiptable_but_not_product_authority() -> None:
    compiler = MemoryQueryCompiler()
    query = "How much did I pay per ceramic planter?"
    legacy = compiler.compile_v01(query, reference_time=REFERENCE)
    translated = translate_memory_query_ir_v01(legacy, query=query)
    product = compiler.compile(query, reference_time=REFERENCE)
    contract = compiler.compile_contract(query, reference_time=REFERENCE)

    assert legacy.schema_version == "memory-query-ir-v0.1"
    assert translated.schema_version == product.schema_version == "memory-query-ir-v0.2"
    assert infer_operator_family(translated) == infer_operator_family(product) == "DIVIDE"
    assert translated != product
    assert contract.operation is not None and contract.operation.value == "DIVIDE"
    assert len(v01_translation_digest(legacy, translated)) == 64
    assert translated.planner_trace.reason_code.startswith("V01_COMPAT:")
    assert product.planner_trace.reason_code.startswith("QUERY_TASK_CONTRACT:")
