from __future__ import annotations

from milai.application.quantity_composition import (
    compose_divide_evidence_values,
    composition_evidence_queries,
    prioritize_composition_evidence,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import QueryPlan, RetrievalRequest


def _plan() -> QueryPlan:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How much did I spend on each coffee mug for my coworkers?",
        )
    )


def test_q1_detects_minimal_divide_query_spec_without_case_identity() -> None:
    plan = _plan()

    assert plan.operator == "DIVIDE_EVIDENCE_VALUES"
    assert plan.operator_arguments["required_slots"] == ["TOTAL_PRICE", "ITEM_COUNT"]
    assert plan.operator_arguments["entity_terms"] == ["coffee", "mug"]
    assert composition_evidence_queries(plan) == (
        "coffee mug spent paid cost price total",
        "coffee mug purchased bought ordered count number",
    )
    assert "0100672e" not in plan.model_dump_json()


def test_q1_composes_verified_quantity_spans_without_conflating_source_speaker() -> None:
    plan = _plan()
    evidence = [
        {
            "evidence_id": "price-evidence",
            "subject_id": "fixture-user",
            "source_ref": "memory://session/36/turn/0",
            "content": (
                "I once spent $60 on some coffee mugs for my coworkers, and they loved them."
            ),
            "speaker": "assistant",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "count-evidence",
            "subject_id": "fixture-user",
            "source_ref": "memory://session/45/turn/0",
            "content": ("I purchased 5 coffee mugs with funny quotes for my coworkers."),
            "speaker": "tool",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "assistant-noise",
            "subject_id": "fixture-user",
            "source_ref": "memory://session/45/turn/1",
            "content": "assistant: You could buy 10 coffee mugs for $40.",
        },
    ]

    result = compose_divide_evidence_values(plan, evidence)

    assert result is not None
    assert result["status"] == "COMPLETE"
    assert result["value"] == 12
    assert result["unit"] == "USD_PER_ITEM"
    assert result["display_value"] == "$12 per item"
    assert result["completeness"]["filled_slots"] == ["TOTAL_PRICE", "ITEM_COUNT"]
    assert result["evidence_refs"] == ["price-evidence", "count-evidence"]
    assert result["source_turn_refs"] == [
        "memory://session/36/turn/0",
        "memory://session/45/turn/0",
    ]
    assert result["hidden_model_calls"] == 0
    assert result["canonical_mutation"] is False
    assert [item["source_role"] for item in result["operands"]] == [
        "assistant",
        "tool",
    ]
    prioritized = prioritize_composition_evidence(evidence, result)
    assert [item["evidence_id"] for item in prioritized[:2]] == [
        "price-evidence",
        "count-evidence",
    ]


def test_q1_abstains_when_one_required_slot_is_missing_or_ambiguous() -> None:
    plan = _plan()
    missing = compose_divide_evidence_values(
        plan,
        [
            {
                "evidence_id": "count-evidence",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/45/turn/0",
                "content": "user: I purchased 5 coffee mugs for my coworkers.",
            }
        ],
    )
    ambiguous = compose_divide_evidence_values(
        plan,
        [
            {
                "evidence_id": "price-a",
                "subject_id": "fixture-user",
                "source_ref": "memory://a",
                "content": "user: I spent $60 on coffee mugs.",
            },
            {
                "evidence_id": "price-b",
                "subject_id": "fixture-user",
                "source_ref": "memory://b",
                "content": "user: I spent $70 on coffee mugs.",
            },
            {
                "evidence_id": "count",
                "subject_id": "fixture-user",
                "source_ref": "memory://c",
                "content": "user: I purchased 5 coffee mugs.",
            },
        ],
    )

    assert missing is not None and missing["status"] == "PARTIAL"
    assert missing["reason"] == "REQUIRED_SLOT_MISSING"
    assert missing["value"] is None
    assert ambiguous is not None and ambiguous["status"] == "PARTIAL"
    assert ambiguous["reason"] == "OPERAND_AMBIGUOUS"


def test_q5_one_span_can_fill_two_roles_only_through_distinct_bindings() -> None:
    result = compose_divide_evidence_values(
        _plan(),
        [
            {
                "evidence_id": "purchase",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/purchase/turn/0",
                "content": "user: I paid $60 for 5 coffee mugs for my coworkers.",
            }
        ],
    )

    assert result is not None and result["status"] == "COMPLETE"
    assert result["value"] == 12
    price, count = result["operands"]
    assert price["evidence_span"]["span_id"] == count["evidence_span"]["span_id"]
    assert (
        price["interpretation"]["interpretation_id"] != count["interpretation"]["interpretation_id"]
    )
    assert price["requirement_binding"]["requirement_id"] == "TOTAL_PRICE"
    assert count["requirement_binding"]["requirement_id"] == "ITEM_COUNT"
    assert price["requirement_binding"]["status"] == "MATCH"
    assert count["requirement_binding"]["status"] == "MATCH"


def test_q5_cross_session_join_is_order_stable_and_validates_purpose() -> None:
    evidence = [
        {
            "evidence_id": "price",
            "subject_id": "fixture-user",
            "source_ref": "memory://session/price/turn/0",
            "content": "user: I spent $60 on coffee mugs for my coworkers.",
        },
        {
            "evidence_id": "count",
            "subject_id": "fixture-user",
            "source_ref": "memory://session/count/turn/0",
            "content": "user: I bought 5 coffee mugs for my coworkers.",
        },
    ]

    forward = compose_divide_evidence_values(_plan(), evidence)
    reverse = compose_divide_evidence_values(_plan(), list(reversed(evidence)))

    assert forward is not None and reverse is not None
    assert forward["status"] == reverse["status"] == "COMPLETE"
    assert forward["value"] == reverse["value"] == 12
    assert forward["operands"] == reverse["operands"]
    assert forward["trace"]["join"].startswith("SAME_ENTITY_PURPOSE_VALIDATED")

    incompatible = [
        evidence[0],
        {
            **evidence[1],
            "content": "user: I bought 5 coffee mugs for my family.",
        },
    ]
    rejected = compose_divide_evidence_values(_plan(), incompatible)
    assert rejected is not None and rejected["status"] == "PARTIAL"
    assert rejected["reason"] == "JOIN_PURPOSE_INCOMPATIBLE"


def test_q5_irrelevant_or_duplicate_sources_cannot_fabricate_completeness() -> None:
    irrelevant = compose_divide_evidence_values(
        _plan(),
        [
            {
                "evidence_id": "price",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/price/turn/0",
                "content": "user: I spent $60 on coffee mugs.",
            },
            {
                "evidence_id": "wrong-entity",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/wrong/turn/0",
                "content": "user: I bought 5 ceramic plates.",
            },
        ],
    )
    duplicate_transactions = compose_divide_evidence_values(
        _plan(),
        [
            {
                "evidence_id": "price-a",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/a/turn/0",
                "content": "user: I spent $60 on coffee mugs.",
            },
            {
                "evidence_id": "price-b",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/b/turn/0",
                "content": "user: I spent $60 on coffee mugs.",
            },
            {
                "evidence_id": "count",
                "subject_id": "fixture-user",
                "source_ref": "memory://session/c/turn/0",
                "content": "user: I bought 5 coffee mugs.",
            },
        ],
    )

    assert irrelevant is not None and irrelevant["status"] == "PARTIAL"
    assert irrelevant["reason"] == "REQUIRED_SLOT_MISSING"
    assert irrelevant["completeness"]["filled_slots"] == ["TOTAL_PRICE"]
    assert duplicate_transactions is not None
    assert duplicate_transactions["status"] == "PARTIAL"
    assert duplicate_transactions["reason"] == "OPERAND_AMBIGUOUS"
