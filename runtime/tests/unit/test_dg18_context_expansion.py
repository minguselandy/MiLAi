from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from milai.application.memory_context import MemoryContextCompiler
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.persistence import SessionContext

CONTEXT = SessionContext(
    UUID("11111111-1111-4111-8111-111111111111"),
    UUID("22222222-2222-4222-8222-222222222222"),
)


def _source_context(turn: int, round_ordinal: int) -> dict[str, object]:
    return {
        "session_id": "session-a",
        "turn_id": f"turn-{turn}",
        "turn_ordinal": turn,
        "round_id": f"round-{round_ordinal}",
        "round_ordinal": round_ordinal,
        "previous_turn_id": f"turn-{turn - 1}" if turn > 0 else None,
        "next_turn_id": None,
    }


def _with_session(item: dict[str, Any], session_id: str) -> dict[str, Any]:
    value = dict(item)
    context = dict(value["source_context"])
    context.update(
        {
            "session_id": session_id,
            "turn_id": f"{session_id}:turn:{context['turn_ordinal']}",
            "round_id": f"{session_id}:round:{context['round_ordinal']}",
            "previous_turn_id": None,
        }
    )
    value["source_context"] = context
    return value


def _item(
    evidence_id: str,
    *,
    turn: int,
    round_ordinal: int,
    speaker: str,
    content: str,
    expansion: dict[str, object] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"opaque://{evidence_id}",
        "subject_id": "not-used-as-structured-session",
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": _source_context(turn, round_ordinal),
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "observed_at": "2026-08-27T00:00:00+00:00",
        "content": content,
        "relevance_score": 1.0,
    }
    if expansion is not None:
        value["context_expansion"] = expansion
    return value


class _AdjacencyReader:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def hydrate_evidence_adjacency(
        self,
        _context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "anchor_evidence_ids": anchor_evidence_ids,
                "requested_scope": requested_scope,
                "as_of": as_of,
                "max_items": max_items,
            }
        )
        return self.rows


def _outcome(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "HIT",
        "items": items,
        "open_issue_ids": [],
        "derived_result": None,
        "sufficiency_decision": {"status": "PARTIAL", "missing_slots": ["ANSWER"]},
    }


def test_r1b_compiler_hydrates_same_round_then_adjacent_and_deduplicates_overlap() -> None:
    same = _item(
        "same",
        turn=1,
        round_ordinal=0,
        speaker="assistant",
        content="The cobalt code is 47.",
        expansion={"trigger": "SAME_ROUND", "source_evidence_id": "anchor"},
    )
    adjacent = _item(
        "adjacent",
        turn=2,
        round_ordinal=1,
        speaker="user",
        content="The next round discusses storage.",
        expansion={"trigger": "ADJACENT_ROUND", "source_evidence_id": "anchor"},
    )
    reader = _AdjacencyReader([same, adjacent, dict(same)])
    request = MemoryResolveRequest(
        query="What is the cobalt code?",
        requested_scope={"project_ids": ["milai"]},
        reference_time=datetime(2026, 8, 27, 1, tzinfo=UTC),
    )

    result = MemoryContextCompiler(reader).compile(
        request,
        _outcome(
            [
                _item(
                    "anchor",
                    turn=0,
                    round_ordinal=0,
                    speaker="user",
                    content="What is the cobalt code?",
                )
            ]
        ),
        session_context=CONTEXT,
    )

    assert len(reader.calls) == 1
    assert reader.calls[0]["anchor_evidence_ids"] == ["anchor"]
    assert reader.calls[0]["requested_scope"] == {"project_ids": ["milai"]}
    assert reader.calls[0]["max_items"] == 5
    context = result.memory_context
    assert context.windows[0].evidence_ids == ["anchor", "same"]
    assert sum("same" in window.evidence_ids for window in context.windows) == 1
    assert [entry["trigger"] for entry in context.compile_trace["expansion_trace"]] == [
        "SAME_ROUND",
        "ADJACENT_ROUND",
    ]
    assert context.compile_trace["hydrated_evidence_count"] == 2
    assert context.compile_trace["expansion_activation"] == {
        "eligible": True,
        "activated": True,
        "reason": "MISSING_REQUIREMENTS",
        "signals": ["MISSING_REQUIREMENTS"],
        "missing_slots": ["ANSWER"],
        "structured_anchor_count": 1,
    }
    policy = context.compile_trace["expansion_policy"]
    assert policy["legacy_source_ref_parsing"] is False
    assert policy["sequence"] == ["SAME_ROUND", "ADJACENT_ROUND"]


def test_r1b_legacy_source_ref_does_not_create_structured_adjacency() -> None:
    reader = _AdjacencyReader([])
    legacy = _item(
        "legacy",
        turn=0,
        round_ordinal=0,
        speaker="user",
        content="assistant: prefix text is not metadata.",
    )
    legacy.pop("source_context")
    legacy.pop("source_context_source")
    legacy["source_ref"] = "memory://session/legacy/turn/0"

    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="Recall legacy history"),
        _outcome([legacy]),
        session_context=CONTEXT,
    )

    assert reader.calls == []
    assert result.memory_context.windows[0].speakers == ["USER"]
    assert result.memory_context.windows[0].expansions == []
    assert result.memory_context.compile_trace["expansion_activation"]["reason"] == (
        "NO_STRUCTURED_EVIDENCE_ANCHOR"
    )


def test_r1b_compiler_rejects_cross_source_session_adjacency() -> None:
    cross_session = _with_session(
        _item(
            "cross-session",
            turn=1,
            round_ordinal=0,
            speaker="assistant",
            content="This belongs to a different real session.",
            expansion={"trigger": "SAME_ROUND", "source_evidence_id": "anchor"},
        ),
        "session-b",
    )
    reader = _AdjacencyReader([cross_session])

    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="What happened in the same conversation?"),
        _outcome(
            [
                _item(
                    "anchor",
                    turn=0,
                    round_ordinal=0,
                    speaker="user",
                    content="This belongs to session A.",
                )
            ]
        ),
        session_context=CONTEXT,
    )

    assert "cross-session" not in result.memory_context.selected_evidence_ids
    assert "different real session" not in result.memory_context.text
    assert result.memory_context.compile_trace["expansion_trace"] == []


def test_r1b_complete_simple_lookup_performs_zero_hydration() -> None:
    reader = _AdjacencyReader([])
    outcome = _outcome(
        [
            _item(
                "answer",
                turn=0,
                round_ordinal=0,
                speaker="assistant",
                content="The cobalt code is 47.",
            )
        ]
    )
    outcome["sufficiency_decision"] = {
        "status": "COMPLETE",
        "covered_slots": ["LOOKUP_ANSWER"],
        "missing_slots": [],
    }

    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="What is the cobalt code?"),
        outcome,
        session_context=CONTEXT,
    )

    assert reader.calls == []
    assert result.memory_context.compile_trace["expansion_activation"] == {
        "eligible": True,
        "activated": False,
        "reason": "ALREADY_COMPLETE",
        "signals": [],
        "missing_slots": [],
        "structured_anchor_count": 1,
    }


def test_decision_accepted_only_boundary_forbids_neighbor_hydration() -> None:
    reader = _AdjacencyReader(
        [
            _item(
                "assistant-neighbor",
                turn=1,
                round_ordinal=0,
                speaker="assistant",
                content="Could the accepted event mean something else?",
                expansion={
                    "trigger": "SAME_ROUND",
                    "source_evidence_id": "accepted-user-turn",
                },
            )
        ]
    )
    outcome = _outcome(
        [
            _item(
                "accepted-user-turn",
                turn=0,
                round_ordinal=0,
                speaker="user",
                content="I attended the Atlas workshop on February 3, 2026.",
            )
        ]
    )
    outcome["_reader_evidence_boundary"] = "DECISION_ACCEPTED_ONLY"

    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="Were those the same event across sessions?"),
        outcome,
        session_context=CONTEXT,
    )

    assert reader.calls == []
    assert result.memory_context.selected_evidence_ids == ["accepted-user-turn"]
    assert "assistant-neighbor" not in result.memory_context.text
    assert result.memory_context.compile_trace["expansion_activation"]["reason"] == (
        "DECISION_ACCEPTED_ONLY"
    )


def test_r1b_explicit_local_context_query_can_activate_after_complete_lookup() -> None:
    reader = _AdjacencyReader([])
    outcome = _outcome(
        [
            _item(
                "answer",
                turn=0,
                round_ordinal=0,
                speaker="user",
                content="I gave the cobalt code.",
            )
        ]
    )
    outcome["sufficiency_decision"] = {
        "status": "COMPLETE",
        "covered_slots": ["LOOKUP_ANSWER"],
        "missing_slots": [],
    }

    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="What did you reply in the same conversation?"),
        outcome,
        session_context=CONTEXT,
    )

    assert len(reader.calls) == 1
    activation = result.memory_context.compile_trace["expansion_activation"]
    assert activation["activated"] is True
    assert activation["reason"] == "EXPLICIT_LOCAL_CONTEXT_QUERY"


def test_r1b_exact_canonical_context_performs_zero_hydration() -> None:
    reader = _AdjacencyReader([])
    result = MemoryContextCompiler(reader).compile(
        MemoryResolveRequest(query="Read current status"),
        {
            "status": "HIT",
            "items": [
                {
                    "kind": "CANONICAL_STATE",
                    "claim_id": "claim-1",
                    "claim_version_id": "version-1",
                    "payload": {"value": "current"},
                }
            ],
            "derived_result": None,
        },
        session_context=CONTEXT,
    )

    assert reader.calls == []
    assert result.memory_context.authority_class == "CANONICAL_STATE"
