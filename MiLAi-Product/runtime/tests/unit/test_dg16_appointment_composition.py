from __future__ import annotations

from datetime import UTC, datetime

from milai.application.appointment_composition import (
    compose_appointment_count,
    prioritize_temporal_evidence,
    temporal_range,
)
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import QueryPlan, RetrievalRequest


def _plan() -> QueryPlan:
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many doctor's appointments did I have in March?",
            as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
            system_as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
        )
    )


def _scan(*, status: str = "COMPLETE") -> dict[str, object]:
    return {
        "status": status,
        "scan_axis": "EVENT_OCCURRENCE_TIME",
        "source_partition_closed": status == "COMPLETE",
        "projection_watermark_covered": status == "COMPLETE",
        "projection_watermark": 91,
        "target_watermark": 91,
        "source_count": 6,
        "projected_count": 6,
        "unreadable_evidence_count": 0,
        "items": [
            {
                "evidence_id": "march-3",
                "source_ref": "memory://session/1/turn/0",
                "content": (
                    "user: I finally went to see my primary care physician, "
                    "Dr. Smith, on March 3rd."
                ),
            },
            {
                "evidence_id": "march-20",
                "source_ref": "memory://session/2/turn/0",
                "content": (
                    "user: I recently had a follow-up appointment with my "
                    "orthopedic surgeon, Dr. Thompson, on March 20th."
                ),
            },
            {
                "evidence_id": "planned-april",
                "source_ref": "memory://session/3/turn/0",
                "content": ("user: I have an EMG test scheduled with my neurologist on April 1st."),
            },
            {
                "evidence_id": "cancelled-march",
                "source_ref": "memory://session/4/turn/0",
                "content": (
                    "user: I cancelled my doctor's appointment with Dr. Green on March 8th."
                ),
            },
            {
                "evidence_id": "march-3-duplicate",
                "source_ref": "memory://session/5/turn/0",
                "content": (
                    "user: I finally went to see my primary care physician, "
                    "Dr. Smith, on March 3rd."
                ),
            },
            {
                "evidence_id": "assistant-noise",
                "source_ref": "memory://session/6/turn/1",
                "content": ("assistant: You had an appointment with Dr. Noise on March 9th."),
            },
        ],
    }


def test_q2_plans_an_exact_closed_open_month_range_without_case_identity() -> None:
    plan = _plan()

    assert plan.operator == "TEMPORAL_COUNT_DISTINCT"
    assert temporal_range(plan) == (
        datetime(2023, 3, 1, tzinfo=UTC),
        datetime(2023, 4, 1, tzinfo=UTC),
    )
    assert plan.operator_arguments["completeness"] == "ALL_MATCHES_IN_RANGE"
    assert "case_id" not in plan.model_dump_json()


def test_q2_counts_distinct_attended_events_from_a_complete_bounded_scan() -> None:
    scan = _scan()
    result = compose_appointment_count(_plan(), scan)

    assert result is not None
    assert result["status"] == "COMPLETE"
    assert result["value"] == 2
    assert result["unit"] == "APPOINTMENTS"
    assert result["evidence_refs"] == ["march-3", "march-20"]
    assert result["count_trace"]["accepted_events"] == 3
    assert result["count_trace"]["deduplicated_events"] == 2
    assert result["count_trace"]["excluded_planned"] == 1
    assert result["count_trace"]["excluded_cancelled"] == 1
    assert result["count_trace"]["excluded_out_of_range"] == 1
    assert result["completeness"]["bounded_scan_complete"] is True
    assert result["top_k_used_as_completeness"] is False
    assert result["hidden_model_calls"] == 0
    assert result["canonical_mutation"] is False
    prioritized = prioritize_temporal_evidence(scan, result)
    assert [item["evidence_id"] for item in prioritized[:2]] == [
        "march-3",
        "march-20",
    ]


def test_q2_abstains_when_the_range_projection_is_not_complete() -> None:
    scan = _scan(status="PARTIAL")
    result = compose_appointment_count(_plan(), scan)

    assert result is not None
    assert result["status"] == "PARTIAL"
    assert result["reason"] == "PROJECTION_GAP"
    assert result["value"] is None
    assert result["completeness"]["bounded_scan_complete"] is False
    assert result["evidence_refs"] == ["march-3", "march-20"]
    assert len(result["operands"]) == 2
