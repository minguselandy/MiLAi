from __future__ import annotations

from milai.application.retrieval import (
    _apply_context_budget,
    _diversify_evidence_by_subject,
)
from milai.persistence.retrieval_repository import evidence_query_terms


def test_evidence_query_ignores_the_memory_invocation_wrapper() -> None:
    assert evidence_query_terms(
        "Recall previous history evidence: How long was the asylum application?"
    ) == ["long", "asylum", "application"]


def test_evidence_diversity_prefers_anchors_then_round_robins_sessions() -> None:
    items = [
        {
            "evidence_id": "a-old",
            "subject_id": "session-a",
            "source_ref": "a:0",
            "observed_at": "2026-01-01T00:00:00Z",
            "relevance_score": 2.0,
            "anchor_match": False,
            "content": "assistant: alpha beta with a long explanation",
        },
        {
            "evidence_id": "a-anchor",
            "subject_id": "session-a",
            "source_ref": "a:1",
            "observed_at": "2026-01-02T00:00:00Z",
            "relevance_score": 2.0,
            "anchor_match": True,
            "content": "user: alpha beta",
        },
        {
            "evidence_id": "b-anchor",
            "subject_id": "session-b",
            "source_ref": "b:1",
            "observed_at": "2026-01-03T00:00:00Z",
            "relevance_score": 1.0,
            "anchor_match": True,
            "content": "user: alpha",
        },
        {
            "evidence_id": "b-old",
            "subject_id": "session-b",
            "source_ref": "b:0",
            "observed_at": "2026-01-01T00:00:00Z",
            "relevance_score": 1.0,
            "anchor_match": False,
            "content": "assistant: beta",
        },
    ]

    diversified = _diversify_evidence_by_subject(items, "find alpha and beta")

    assert [item["evidence_id"] for item in diversified] == [
        "a-anchor",
        "b-anchor",
        "a-old",
        "b-old",
    ]


def test_context_budget_skips_one_oversized_raw_evidence_item() -> None:
    oversized = {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": "too-large",
        "content": "assistant: " + "long " * 200,
    }
    usable = {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": "usable",
        "content": "user: compact answer",
    }
    progress = {"context_budget_truncated": False}
    degraded: set[str] = set()

    _accepted, _rejected, selected, _issues = _apply_context_budget(
        ([], [], [oversized, usable], []),
        256,
        progress,
        degraded,
    )

    assert [item["evidence_id"] for item in selected] == ["usable"]
    assert progress["context_budget_truncated"] is True
    assert degraded == {"context_budget"}


def test_quantity_answer_signal_beats_a_question_paraphrase_in_one_session() -> None:
    items = [
        {
            "evidence_id": "question",
            "subject_id": "session-a",
            "source_ref": "a:0",
            "observed_at": "2026-01-01T00:00:00Z",
            "relevance_score": 2.0,
            "anchor_match": True,
            "content": (
                "user: I booked lunch for 6 people. "
                "The unrelated event agenda and venue plan are already complete. "
                "We can discuss those logistics separately tomorrow. "
                "How many engineers do I lead in my new role?"
            ),
        },
        {
            "evidence_id": "answer",
            "subject_id": "session-a",
            "source_ref": "a:1",
            "observed_at": "2026-01-02T00:00:00Z",
            "relevance_score": 2.0,
            "anchor_match": True,
            "content": "user: I lead 4 engineers in my new role.",
        },
    ]

    diversified = _diversify_evidence_by_subject(
        items, "How many engineers do I lead in my new role?"
    )

    assert [item["evidence_id"] for item in diversified] == ["answer", "question"]
