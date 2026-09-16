from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any, cast

from milai.application.retrieval import _rank_evidence_turns

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/0042_dg17_turn_first_evidence_search.py"
)


def test_a1_turn_rank_is_independent_of_session_grouping() -> None:
    evidence = [
        {
            "evidence_id": "session-a-noise",
            "subject_id": "session-a",
            "source_ref": "memory://session-a/turn-1",
            "content": "user: unrelated filler",
            "relevance_score": 0.95,
        },
        {
            "evidence_id": "session-b-answer",
            "subject_id": "session-b",
            "source_ref": "memory://session-b/turn-0",
            "content": "user: unique target answer",
            "relevance_score": 0.7,
            "anchor_match": True,
        },
        {
            "evidence_id": "session-a-anchor",
            "subject_id": "session-a",
            "source_ref": "memory://session-a/turn-0",
            "content": "user: unique target",
            "relevance_score": 1.0,
            "anchor_match": True,
        },
    ]

    ranked = _rank_evidence_turns(evidence, "unique target answer")

    assert [item["evidence_id"] for item in ranked] == [
        "session-b-answer",
        "session-a-anchor",
        "session-a-noise",
    ]


def test_a1_migration_has_operational_session_first_rollback() -> None:
    namespace = runpy.run_path(str(MIGRATION))
    turn_first = cast(Any, namespace["_turn_first_candidates"])()
    rollback = cast(Any, namespace["_session_first_candidates"])()

    assert "row_number() OVER" in turn_first
    assert "session_scores" not in turn_first
    assert "live.search_vector @@" in turn_first
    assert "'turn_rank'" in turn_first
    assert "'candidate_unit', 'TURN'" in turn_first
    assert "'acquisition_channel', 'FTS_RAW'" in turn_first
    assert "session_scores AS MATERIALIZED" in rollback
    assert "JOIN session_scores" in rollback


def test_a3_structured_speaker_does_not_change_unconfigured_ranking() -> None:
    evidence = [
        {
            "evidence_id": "user-counterexample",
            "source_ref": "memory://session-u/turn-0",
            "content": "user: collect the package from the shop",
            "relevance_score": 0.8,
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "assistant-answer",
            "source_ref": "memory://session-a/turn-0",
            "content": "assistant: collect the package from the shop",
            "relevance_score": 0.76,
            "speaker": "assistant",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
    ]

    ranked = _rank_evidence_turns(evidence, "recommend tea afternoon")

    assert [item["evidence_id"] for item in ranked] == [
        "user-counterexample",
        "assistant-answer",
    ]
    assert len(ranked) == 2


def test_a3_no_query_global_user_boost() -> None:
    evidence = [
        {
            "evidence_id": "assistant-higher-score",
            "source_ref": "memory://session-a/turn-0",
            "content": "assistant: project meeting happened Tuesday",
            "relevance_score": 0.9,
        },
        {
            "evidence_id": "user-lower-score",
            "source_ref": "memory://session-u/turn-0",
            "content": "user: project meeting happened Tuesday",
            "relevance_score": 0.8,
        },
    ]

    ranked = _rank_evidence_turns(evidence, "project meeting Tuesday")

    assert [item["evidence_id"] for item in ranked] == [
        "assistant-higher-score",
        "user-lower-score",
    ]


def test_a3_typed_source_preference_is_a_soft_rank_prior() -> None:
    evidence = [
        {
            "evidence_id": "assistant-same-topic",
            "source_ref": "memory://session-a/turn-0",
            "content": "assistant: remember to collect the package from the shop",
            "relevance_score": 0.9,
            "speaker": "assistant",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "user-answer-bearing",
            "source_ref": "memory://session-u/turn-0",
            "content": "user: I still need to collect the package from the shop",
            "relevance_score": 0.8,
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
    ]

    ranked = _rank_evidence_turns(
        evidence,
        "collect the package from the shop",
        preferred_speakers=("USER",),
    )

    assert [item["evidence_id"] for item in ranked] == [
        "user-answer-bearing",
        "assistant-same-topic",
    ]
    assert len(ranked) == 2


def test_a3_assistant_source_preference_preserves_assistant_answers() -> None:
    evidence = [
        {
            "evidence_id": "user-repeated-question",
            "source_ref": "memory://session-u/turn-0",
            "content": "user: support contact is listed here",
            "relevance_score": 0.91,
            "speaker": "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
        {
            "evidence_id": "assistant-answer",
            "source_ref": "memory://session-a/turn-0",
            "content": "assistant: support contact is listed here",
            "relevance_score": 0.86,
            "speaker": "assistant",
            "speaker_source": "STRUCTURED_TURN_METADATA",
        },
    ]

    ranked = _rank_evidence_turns(
        evidence,
        "support contact listed here",
        preferred_speakers=("ASSISTANT",),
    )

    assert [item["evidence_id"] for item in ranked] == [
        "assistant-answer",
        "user-repeated-question",
    ]
