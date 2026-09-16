from __future__ import annotations

from datetime import UTC, datetime

from milai.application.appointment_composition import compose_evidence_range_count
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)


def _plan():  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many babies were born to friends and family in the last few months?",
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )


def _scan(*, status: str = "COMPLETE") -> dict[str, object]:
    return {
        "status": status,
        "scan_axis": "EVENT_OCCURRENCE_TIME",
        "source_partition_closed": True,
        "projection_watermark_covered": status == "COMPLETE",
        "projection_watermark": 44,
        "target_watermark": 44,
        "source_count": 7,
        "projected_count": 7,
        "unreadable_evidence_count": 0,
        "items": [
            {
                "evidence_id": "maya-birth",
                "source_ref": "memory://session/s1/turn/0",
                "subject_id": "s1",
                "observed_at": "2023-01-06T09:00:00+00:00",
                "captured_at": "2023-01-06T09:00:01+00:00",
                "content": "My friend Maya welcomed a baby on January 5th.",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "maya-birth-duplicate",
                "source_ref": "memory://session/s2/turn/0",
                "subject_id": "s2",
                "observed_at": "2023-01-07T09:00:00+00:00",
                "captured_at": "2023-01-07T09:00:01+00:00",
                "content": "My friend Maya welcomed a baby on January 5th.",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "leo-birth",
                "source_ref": "memory://session/s3/turn/0",
                "subject_id": "s3",
                "observed_at": "2023-02-03T09:00:00+00:00",
                "captured_at": "2023-02-03T09:00:01+00:00",
                "content": "Leo's baby was born on February 2nd.",
                "speaker": "assistant",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "future-birth",
                "source_ref": "memory://session/s4/turn/0",
                "subject_id": "s4",
                "observed_at": "2023-03-01T09:00:00+00:00",
                "content": "Kim will welcome a baby on March 20th.",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "old-birth",
                "source_ref": "memory://session/s5/turn/0",
                "subject_id": "s5",
                "observed_at": "2023-01-02T09:00:00+00:00",
                "content": "Nora's baby was born on November 1st, 2022.",
                "speaker": "user",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "assistant-noise",
                "source_ref": "memory://session/s6/turn/1",
                "subject_id": "s6",
                "observed_at": "2023-02-04T09:00:00+00:00",
                "content": "Kim will welcome a baby on February 3rd.",
                "speaker": "assistant",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
            {
                "evidence_id": "irrelevant",
                "source_ref": "memory://session/s7/turn/0",
                "subject_id": "s7",
                "observed_at": "2023-02-04T09:00:00+00:00",
                "content": "My family met for dinner on February 3rd.",
                "speaker": "tool",
                "speaker_source": "STRUCTURED_TURN_METADATA",
            },
        ],
    }


def test_q4_generic_range_count_deduplicates_and_proves_closed_domain() -> None:
    result = compose_evidence_range_count(_plan(), _scan())

    assert result is not None
    assert result["status"] == "COMPLETE"
    assert result["value"] == 2
    assert result["unit"] == "EVENTS"
    assert "leo-birth" in result["evidence_refs"]
    assert len({"maya-birth", "maya-birth-duplicate"}.intersection(result["evidence_refs"])) == 1
    assert result["count_trace"]["accepted_events"] == 3
    assert result["count_trace"]["deduplicated_events"] == 2
    assert result["count_trace"]["excluded_planned"] == 2
    assert result["count_trace"]["excluded_out_of_range"] == 1
    assert result["completeness"]["bounded_scan_complete"] is True
    assert result["completeness"]["source_partition_closed"] is True
    assert result["top_k_used_as_completeness"] is False
    assert result["hidden_model_calls"] == 0
    assert result["canonical_mutation"] is False
    operand = result["operands"][0]
    assert operand["event_at"].startswith("2023-01-05")
    assert operand["source_timestamp"][:10] in {"2023-01-06", "2023-01-07"}
    assert operand["system_timestamp"][:10] in {"2023-01-06", "2023-01-07"}
    assert operand["interpretation"]["canonical"] is False
    assert operand["requirement_binding"]["authority_class"] == "EVIDENCE_ONLY"
    assert operand["requirement_binding"]["status"] == "MATCH"
    leo = next(item for item in result["operands"] if item["evidence_id"] == "leo-birth")
    assert leo["interpretation"]["value"]["event_status"] == "OCCURRED"


def test_q4_incomplete_projection_cannot_return_a_complete_scalar() -> None:
    result = compose_evidence_range_count(_plan(), _scan(status="PARTIAL"))

    assert result is not None
    assert result["status"] == "PARTIAL"
    assert result["value"] is None
    assert result["reason"] == "PROJECTION_GAP"
    assert result["completeness"]["bounded_scan_complete"] is False
    assert "leo-birth" in result["evidence_refs"]
    assert len(
        {"maya-birth", "maya-birth-duplicate"}.intersection(result["evidence_refs"])
    ) == 1
    assert len(result["operands"]) == 2
    assert result["completeness"]["filled_slots"] == []


def test_partial_count_collapses_same_episode_paraphrases_to_original_turn() -> None:
    scan = _scan(status="PARTIAL")
    scan["source_count"] = 2
    scan["projected_count"] = 2
    scan["items"] = [
        {
            "evidence_id": "maya-original",
            "source_ref": "memory://session/maya/t0",
            "subject_id": "maya-session",
            "observed_at": "2023-01-06T09:00:00+00:00",
            "captured_at": "2023-01-06T09:00:01+00:00",
            "content": "My friend Maya welcomed a baby on January 5th.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "maya-paraphrase",
            "source_ref": "memory://session/maya/t2",
            "subject_id": "maya-session",
            "observed_at": "2023-01-06T09:00:00+00:00",
            "captured_at": "2023-01-06T09:00:02+00:00",
            "content": "My friend Maya had a newborn baby on January 5th.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
    ]

    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None and result["status"] == "PARTIAL"
    assert result["evidence_refs"] == ["maya-original"]
    assert result["count_trace"]["accepted_events"] == 2
    assert result["count_trace"]["deduplicated_events"] == 1


def test_episode_identity_prefers_compact_source_session_over_subject_fallback() -> None:
    scan = _scan(status="PARTIAL")
    scan["source_count"] = 2
    scan["projected_count"] = 2
    scan["items"] = [
        {
            "evidence_id": "max-original",
            "source_ref": "case:s23:session-rachel:t0",
            "subject_id": "turn-subject-original",
            "observed_at": "2023-03-20T09:00:00+00:00",
            "content": "My cousin Rachel welcomed a baby boy named Max on March 5th.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "max-restatement",
            "source_ref": "case:s23:session-rachel:t6",
            "subject_id": "turn-subject-restatement",
            "observed_at": "2023-03-20T09:00:00+00:00",
            "content": "My cousin Rachel had a baby boy named Max on March 5th.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
    ]

    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None and result["status"] == "PARTIAL"
    assert result["evidence_refs"] == ["max-original"]
    assert result["count_trace"]["deduplicated_events"] == 1


def test_query_qualified_source_refs_prefer_the_earliest_duplicate_turn() -> None:
    scan = _scan(status="PARTIAL")
    scan["source_count"] = 2
    scan["projected_count"] = 2
    common = {
        "subject_id": "projection-owned-subject",
        "observed_at": "2023-05-13T09:18:00+00:00",
        "captured_at": "2023-05-13T09:18:01+00:00",
    }
    scan["items"] = [
        {
            **common,
            "evidence_id": "max-original",
            "source_ref": (
                "longmemeval://case/case-a/session/23/session-rachel/turn/0"
                "?event_id=original"
            ),
            "content": (
                "I am considering a gift. My cousin Rachel just had a baby boy "
                "named Max in March."
            ),
        },
        {
            **common,
            "evidence_id": "max-restatement",
            "source_ref": (
                "longmemeval://case/case-a/session/23/session-rachel/turn/6"
                "?event_id=restatement"
            ),
            "content": "Rachel had a baby boy named Max in March.",
        },
    ]

    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None and result["status"] == "PARTIAL"
    assert result["evidence_refs"] == ["max-original"]
    assert result["count_trace"]["deduplicated_events"] == 1


def test_a5_source_observed_scan_cannot_prove_an_event_occurrence_count() -> None:
    scan = _scan()
    scan["scan_axis"] = "SOURCE_OBSERVED_TIME"
    # An event may occur inside the target interval but only be reported after
    # that source-observed interval.  A complete observed-time scan of the
    # target dates therefore cannot establish a complete event domain.
    scan["items"] = []
    scan["source_count"] = 0
    scan["projected_count"] = 0

    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None
    assert result["status"] == "PARTIAL"
    assert result["value"] is None
    assert result["reason"] == "EVENT_TIME_DOMAIN_UNPROVEN"
    assert result["completeness"]["query_temporal_axis"] == ("EVENT_OCCURRENCE_TIME")
    assert result["completeness"]["scan_temporal_axis"] == ("SOURCE_OBSERVED_TIME")
    assert result["completeness"]["temporal_domain_coverage"] == "UNPROVEN"


def test_a5_source_observed_query_executes_against_source_timestamps() -> None:
    plan = _plan()
    query_ir = plan.memory_query_ir
    assert query_ir is not None
    temporal = query_ir.constraints.normalized_temporal
    assert temporal is not None
    source_temporal = temporal.model_copy(update={"time_axis": "SOURCE_OBSERVED_TIME"})
    requirements = [
        requirement.model_copy(update={"temporal_constraints": source_temporal})
        for requirement in query_ir.requirements
    ]
    source_ir = query_ir.model_copy(
        update={
            "constraints": query_ir.constraints.model_copy(
                update={"normalized_temporal": source_temporal}
            ),
            "requirements": requirements,
        }
    )
    source_plan = plan.model_copy(
        update={
            "memory_query_ir": source_ir,
            "operator_arguments": {
                **plan.operator_arguments,
                "time_axis": "SOURCE_OBSERVED_TIME",
            },
        }
    )
    scan = _scan()
    scan["scan_axis"] = "SOURCE_OBSERVED_TIME"
    scan["items"] = [
        {
            "evidence_id": "reported-in-range",
            "source_ref": "memory://session/source-axis/turn/0",
            "subject_id": "source-axis",
            "observed_at": "2023-01-15T09:00:00+00:00",
            "captured_at": "2023-01-15T09:00:01+00:00",
            "content": "Maya welcomed a baby on November 1st, 2022.",
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        }
    ]
    scan["source_count"] = 1
    scan["projected_count"] = 1

    result = compose_evidence_range_count(source_plan, scan)

    assert result is not None
    assert result["status"] == "COMPLETE"
    assert result["value"] == 1
    assert result["operands"][0]["event_at"].startswith("2023-01-15")
    assert result["operands"][0]["event_time_basis"] == "SOURCE_OBSERVED_TIME"
    assert result["completeness"]["query_temporal_axis"] == ("SOURCE_OBSERVED_TIME")
    assert result["completeness"]["deduplication_proven"] is True


def test_q4_range_count_removes_count_and_temporal_cues_from_event_entity() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many times did I bake something in the past two weeks?",
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )

    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.requirements[0].entity_constraints == ["bake"]


def test_q5_distinct_named_twins_have_independent_event_identities() -> None:
    scan = _scan()
    scan["items"] = [
        {
            "evidence_id": "twins",
            "source_ref": "memory://session/twins/turn/0",
            "subject_id": "twins",
            "observed_at": "2023-03-02T09:00:00+00:00",
            "content": "The twins, Ava and Lily, were born in February.",
            "speaker": "assistant",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        }
    ]
    scan["source_count"] = 1
    scan["projected_count"] = 1
    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None and result["status"] == "COMPLETE"
    assert result["value"] == 2
    assert result["count_trace"]["deduplicated_events"] == 2
    assert len({item["dedup_key"] for item in result["operands"]}) == 2


def test_q5_complete_scan_with_relevant_undated_event_stays_partial() -> None:
    scan = _scan()
    scan["items"] = [
        {
            "evidence_id": "undated",
            "source_ref": "memory://session/undated/turn/0",
            "subject_id": "undated",
            "observed_at": "2023-03-02T09:00:00+00:00",
            "content": "My friend welcomed a baby named Rowan.",
            "speaker": "tool",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        }
    ]
    result = compose_evidence_range_count(_plan(), scan)

    assert result is not None and result["status"] == "PARTIAL"
    assert result["reason"] == "EVENT_TIME_UNRESOLVED"
    assert result["value"] is None
