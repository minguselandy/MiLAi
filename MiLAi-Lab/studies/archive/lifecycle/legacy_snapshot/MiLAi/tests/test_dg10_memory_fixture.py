from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from scripts import dg10_memory_fixture as fixture


class Counter:
    def count(self, text: str) -> int:
        return len(text.split())


class Gateway:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.sessions: list[fixture.CorpusSession] = []
        self.last_query: str | None = None

    def create_evidence(
        self,
        *,
        case_id: str,
        session: fixture.CorpusSession,
        scope: Mapping[str, Any],
    ) -> str:
        assert scope["project_ids"] == ["dg10-eval"]
        self.events.append(("EVIDENCE", session.session_id))
        self.sessions.append(session)
        return f"evidence-{case_id}-{session.session_id}"

    def create_proposal(
        self,
        *,
        case_id: str,
        session: fixture.CorpusSession,
        evidence_id: str,
        scope: Mapping[str, Any],
    ) -> str:
        del case_id, evidence_id, scope
        self.events.append(("PROPOSAL", session.session_id))
        return f"proposal-{session.session_id}"

    def approve_proposal(self, *, proposal_id: str) -> Mapping[str, str]:
        session_id = proposal_id.removeprefix("proposal-")
        self.events.append(("DECISION", session_id))
        return {
            "decision_id": f"decision-{session_id}",
            "claim_id": f"claim-{session_id}",
            "claim_version_id": f"version-{session_id}",
        }

    def project(self) -> int:
        return len(self.sessions)

    def recall(
        self,
        *,
        case_id: str,
        query: str,
        scope: Mapping[str, Any],
        limit: int,
    ) -> fixture.RecallResult:
        del case_id, scope
        self.last_query = query
        results = tuple(
            {
                "session_id": session.session_id,
                "evidence_id": f"evidence-{session.session_id}",
                "memory_text": session.render(),
            }
            for session in self.sessions[:limit]
        )
        return fixture.RecallResult(
            request_id="mcp-native-recall-1",
            query=query,
            consistency="CANONICAL_REQUIRED",
            canonical_gate=True,
            results=results,
            abstained=False,
        )

    def cleanup_case(self, *, case_id: str) -> Mapping[str, Any]:
        del case_id
        self.sessions.clear()
        return {
            "canonical_rows_remaining": 0,
            "projection_rows_remaining": 0,
            "blob_bytes_remaining": 0,
            "status": "PASS_NO_EVALUATION_DATA_REMAINS",
        }


def _row() -> dict[str, object]:
    return {
        "question_id": "case-1",
        "question": "What is the latest project state?",
        "haystack_session_ids": ["session-a", "session-b"],
        "haystack_dates": ["2026-08-20", "2026-08-21"],
        "haystack_sessions": [
            [{"role": "user", "content": "The project is blocked."}],
            [
                {"role": "user", "content": "The blocker is resolved."},
                {"role": "assistant", "content": "I will use the latest state."},
            ],
        ],
        "answer": "resolved",
        "answer_session_ids": ["session-b"],
    }


def test_full_session_corpus_preserves_session_time_speaker_and_content() -> None:
    sessions = fixture.build_longmemeval_corpus(_row())
    assert len(sessions) == 2
    assert sessions[1].session_id == "session-b"
    assert sessions[1].observed_at == "2026-08-21"
    assert sessions[1].turns[0].speaker == "user"
    assert "blocker is resolved" in sessions[1].render()


def test_every_session_uses_evidence_proposal_decision_before_recall() -> None:
    gateway = Gateway()
    sessions = fixture.build_longmemeval_corpus(_row())
    receipt = fixture.ingest_full_session_corpus(
        gateway=gateway,
        case_id="case-1",
        sessions=sessions,
        scope={"project_ids": ["dg10-eval"]},
    )
    assert receipt.full_session_corpus is True
    assert receipt.bypassed_governance is False
    assert gateway.events == [
        ("EVIDENCE", "session-a"),
        ("PROPOSAL", "session-a"),
        ("DECISION", "session-a"),
        ("EVIDENCE", "session-b"),
        ("PROPOSAL", "session-b"),
        ("DECISION", "session-b"),
    ]


def test_recall_uses_original_question_without_marker_or_naive_ranking() -> None:
    gateway = Gateway()
    receipt = fixture.ingest_full_session_corpus(
        gateway=gateway,
        case_id="case-1",
        sessions=fixture.build_longmemeval_corpus(_row()),
        scope={"project_ids": ["dg10-eval"]},
    )
    provider = fixture.GovernedMemoryProvider(
        gateway=gateway,
        receipt=receipt,
        token_counter=Counter(),
    )
    question = "What is the latest project state?"
    context = provider.retrieve(case_id="case-1", question=question)
    assert gateway.last_query == question
    assert context.query_equals_original_question is True
    assert context.artificial_marker is False
    assert context.shared_naive_ranking is False
    assert context.ranking_source == "MILAI_RUNTIME_CANONICAL_GATE"


def test_incomplete_governance_and_cleanup_residue_fail_closed() -> None:
    class BadGateway(Gateway):
        def approve_proposal(self, *, proposal_id: str) -> Mapping[str, str]:
            del proposal_id
            return {"decision_id": "decision-only"}

    with pytest.raises(fixture.FixtureError, match="Decision"):
        fixture.ingest_full_session_corpus(
            gateway=BadGateway(),
            case_id="case-1",
            sessions=fixture.build_longmemeval_corpus(_row()),
            scope={"project_ids": ["dg10-eval"]},
        )

    class ResidueGateway(Gateway):
        def cleanup_case(self, *, case_id: str) -> Mapping[str, Any]:
            del case_id
            return {
                "canonical_rows_remaining": 1,
                "projection_rows_remaining": 0,
                "blob_bytes_remaining": 0,
                "status": "RESIDUE",
            }

    with pytest.raises(fixture.FixtureError, match="cleanup"):
        fixture.safe_cleanup(ResidueGateway(), case_id="case-1")


def test_retrieval_metrics_report_recall_precision_and_mrr_at_required_k() -> None:
    metrics = fixture.retrieval_metrics(
        ["irrelevant", "session-b", "session-c"],
        ["session-b", "session-c"],
    )
    assert metrics == {
        "recall_at_1": 0.0,
        "precision_at_1": 0.0,
        "recall_at_3": 1.0,
        "precision_at_3": 2 / 3,
        "recall_at_5": 1.0,
        "precision_at_5": 0.4,
        "mrr": 0.5,
    }


def test_retrieval_metrics_reject_duplicate_rank_inflation() -> None:
    with pytest.raises(fixture.FixtureError, match="duplicated"):
        fixture.retrieval_metrics(
            ["session-b", "session-b"],
            ["session-b"],
        )


def test_synthetic_contract_covers_update_temporal_issue_revoke_and_unavailable() -> None:
    report = fixture.synthetic_fixture_report()
    assert report["fixture_count"] == 5
    assert report["marker_allowed"] is False
    assert report["shared_naive_ranking_allowed"] is False
