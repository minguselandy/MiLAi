from __future__ import annotations

from datetime import UTC, datetime

from milai.application.appointment_composition import compose_appointment_count
from milai.application.quantity_composition import compose_divide_evidence_values
from milai.application.query_planner import QueryPlanner
from milai.domain.evidence_composition import (
    EvidenceCompositionResult,
    query_spec_from_plan,
)
from milai.domain.retrieval import RetrievalRequest


def test_q3_same_v01_contract_expresses_both_focal_operators() -> None:
    quantity_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How much did I spend on each coffee mug for my coworkers?",
        )
    )
    temporal_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many doctor's appointments did I go to in March?",
            as_of=datetime(2023, 3, 27, tzinfo=UTC),
        )
    )

    quantity_spec = query_spec_from_plan(quantity_plan)
    temporal_spec = query_spec_from_plan(temporal_plan)

    assert quantity_spec is not None and temporal_spec is not None
    assert quantity_spec.schema_version == temporal_spec.schema_version == ("query-spec-v0.1")
    assert quantity_spec.required_slots == ["TOTAL_PRICE", "ITEM_COUNT"]
    assert temporal_spec.required_slots == ["MATCHING_EVENTS_IN_RANGE"]
    assert quantity_spec.evidence_policy.provenance_required is True
    assert temporal_spec.evidence_policy.provenance_required is True


def test_q3_both_composers_emit_valid_shared_results_and_operator_traces() -> None:
    quantity_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How much did I spend on each coffee mug for my coworkers?",
        )
    )
    quantity_raw = compose_divide_evidence_values(
        quantity_plan,
        [
            {
                "evidence_id": "price",
                "subject_id": "fixture-user",
                "source_ref": "memory://price",
                "content": "user: I spent $60 on coffee mugs.",
            },
            {
                "evidence_id": "count",
                "subject_id": "fixture-user",
                "source_ref": "memory://count",
                "content": "user: I bought 5 coffee mugs.",
            },
        ],
    )
    temporal_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many doctor's appointments did I go to in March?",
            as_of=datetime(2023, 3, 27, tzinfo=UTC),
        )
    )
    temporal_raw = compose_appointment_count(
        temporal_plan,
        {
            "status": "COMPLETE",
            "scan_axis": "EVENT_OCCURRENCE_TIME",
            "source_partition_closed": True,
            "projection_watermark_covered": True,
            "projection_watermark": 7,
            "target_watermark": 7,
            "source_count": 1,
            "projected_count": 1,
            "unreadable_evidence_count": 0,
            "items": [
                {
                    "evidence_id": "appointment",
                    "subject_id": "fixture-user",
                    "source_ref": "memory://appointment",
                    "content": ("user: I went to see my doctor, Dr. Smith, on March 3rd."),
                }
            ],
        },
    )

    assert quantity_raw is not None and temporal_raw is not None
    quantity = EvidenceCompositionResult.model_validate(quantity_raw)
    temporal = EvidenceCompositionResult.model_validate(temporal_raw)
    assert quantity.result == 12
    assert temporal.result == 1
    assert quantity.trace.query_spec.operator == quantity.operator
    assert temporal.trace.query_spec.operator == temporal.operator
    assert quantity.trace.retrieval_attempts == 2
    assert temporal.trace.retrieval_attempts == 1
    assert quantity.trace.hidden_model_calls == temporal.trace.hidden_model_calls == 0
    assert quantity.trace.canonical_mutation is temporal.trace.canonical_mutation is False
    assert quantity.trace.top_k_used_as_completeness is False
    assert temporal.trace.top_k_used_as_completeness is False
