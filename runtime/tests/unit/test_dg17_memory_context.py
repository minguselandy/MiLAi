from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from milai.application.memory_context import MemoryContextCompiler
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import ContextBudgetEnvelope


def _request(query: str, *, budget: int = 512) -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query=query,
        budget=MemoryResolveBudget(max_context_tokens=budget),
    )


def _evidence(
    evidence_id: str,
    session: str,
    turn: int,
    content: str,
    *,
    score: float = 1.0,
    speaker: str = "user",
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{session}/turn/{turn}",
        "subject_id": session,
        "observed_at": "2026-08-27T00:00:00+00:00",
        "content": content,
        "speaker": speaker,
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session,
            "turn_id": f"turn-{turn}",
            "turn_ordinal": turn,
            "round_id": f"round-{turn // 2}",
            "round_ordinal": turn // 2,
            "previous_turn_id": f"turn-{turn - 1}" if turn > 0 else None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "relevance_score": score,
    }


def _outcome(items: list[dict[str, Any]], **updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": "HIT",
        "requirement": "SEARCH",
        "items": items,
        "open_issue_ids": [],
        "canonical_position": {
            "canonical_outbox_sequence": 17,
            "evidence_watermark": 17,
            "fts_watermark": 17,
        },
        "interpretation": {"retrieval_intent": "HISTORY"},
        "sufficiency_decision": {
            "status": "COMPLETE",
            "covered_slots": ["ANSWER"],
            "missing_slots": [],
        },
        "derived_result": None,
    }
    value.update(updates)
    return value


def test_mvp_u0_exact_8192_context_budget_is_accepted_and_8193_is_rejected() -> None:
    request = _request("Recall the cobalt code", budget=8_192)
    result = MemoryContextCompiler().compile(
        request,
        _outcome([_evidence("answer", "session-a", 1, "The code is 47.")]),
    )
    envelope = ContextBudgetEnvelope(
        requested_cap=8_192,
        available_memory_tokens=8_192,
        budget_source="CALLER_CAP_ONLY",
    )

    assert request.budget.max_context_tokens == 8_192
    assert result.memory_context.token_budget == 8_192
    assert envelope.available_memory_tokens == 8_192
    with pytest.raises(ValidationError):
        MemoryResolveBudget(max_context_tokens=8_193)
    with pytest.raises(ValidationError):
        ContextBudgetEnvelope(
            requested_cap=8_193,
            available_memory_tokens=8_193,
            budget_source="CALLER_CAP_ONLY",
        )


def test_q2_runtime_ranks_answer_bearing_turn_before_question_paraphrase() -> None:
    result = MemoryContextCompiler().compile(
        _request("How many engineers do I lead?"),
        _outcome(
            [
                _evidence(
                    "question-turn",
                    "main",
                    8,
                    (
                        "I booked lunch for 6 people. The unrelated event agenda "
                        "and venue plan are already complete. We can discuss all of "
                        "those unrelated logistics separately tomorrow. How many "
                        "engineers do I lead?"
                    ),
                ),
                _evidence(
                    "answer-turn", "main", 10, "I lead 4 engineers.", score=0.8
                ),
            ]
        ),
    )

    context = result.memory_context
    assert context.windows[0].evidence_ids == ["answer-turn"]
    assert "I lead 4 engineers." in context.text
    assert context.compile_trace["hidden_model_calls"] == 0


def test_q2_runtime_recovers_speaker_adjacent_source_turn() -> None:
    result = MemoryContextCompiler().compile(
        _request("What is the cobalt code?"),
        _outcome(
            [
                _evidence("question", "session-a", 0, "What is the cobalt code?"),
                _evidence(
                    "answer",
                    "session-a",
                    1,
                    "The cobalt code is 47.",
                    speaker="assistant",
                ),
            ]
        ),
    )

    window = result.memory_context.windows[0]
    assert window.evidence_ids == ["question", "answer"]
    assert window.speakers == ["USER", "ASSISTANT"]
    assert window.expansions[0].trigger == "SAME_ROUND"
    assert window.expansions[0].expanded_evidence_ids == ["question"]


def test_a3_context_does_not_infer_speaker_from_body_prefix() -> None:
    result = MemoryContextCompiler().compile(
        _request("What is the cobalt code?"),
        _outcome(
            [
                {
                    **_evidence("prefix-only", "session-a", 0, "assistant: The code is 47."),
                    "speaker": None,
                    "speaker_source": None,
                }
            ]
        ),
    )

    window = result.memory_context.windows[0]
    assert window.speakers == ["UNKNOWN"]
    assert "assistant: The code is 47." in window.text


def test_q2_session_diversity_only_follows_explicit_multi_session_requirement() -> None:
    items = [
        _evidence("a-1", "session-a", 0, "Alpha detail one."),
        _evidence("a-2", "session-a", 2, "Alpha detail two.", score=0.9),
        _evidence("b-1", "session-b", 0, "Alpha detail three.", score=0.8),
    ]

    ordinary = MemoryContextCompiler().compile(
        _request("Recall alpha details", budget=2_048), _outcome(items)
    ).memory_context
    multi = MemoryContextCompiler().compile(
        _request("Compare alpha details across sessions", budget=2_048),
        _outcome(items),
    ).memory_context

    assert [window.session_id for window in ordinary.windows] == [
        "session-a",
        "session-a",
        "session-b",
    ]
    assert [window.session_id for window in multi.windows] == [
        "session-a",
        "session-b",
        "session-a",
    ]
    assert ordinary.compile_trace["session_diversity_objective_enabled"] is False
    assert multi.compile_trace["session_diversity_objective_enabled"] is True


def test_q2_evidence_context_receipt_is_noncanonical_and_dependency_complete() -> None:
    result = MemoryContextCompiler().compile(
        _request("Recall the cobalt code"),
        _outcome(
            [_evidence("answer", "session-a", 1, "The code is 47.", speaker="assistant")]
        ),
    )

    receipt = result.evidence_receipt
    assert receipt is not None
    assert receipt.authority_class == "EVIDENCE_ONLY"
    assert receipt.source_evidence_ids == ["answer"]
    assert receipt.canonical_position == 17
    assert receipt.projection_watermarks == {
        "evidence_watermark": 17,
        "fts_watermark": 17,
    }
    assert receipt.persisted is False
    assert receipt.canonical_mutation is False


def test_q2_mixed_context_receipt_keeps_authority_classes_separate() -> None:
    canonical = {
        "kind": "CANONICAL_STATE",
        "claim_id": "claim-1",
        "claim_version_id": "version-2",
        "payload": {"value": "current"},
    }
    result = MemoryContextCompiler().compile(
        _request("Explain the current state", budget=2_048),
        _outcome(
            [
                canonical,
                _evidence("support", "session-a", 1, "The state is current."),
            ]
        ),
    )

    assert result.memory_context.authority_class == "MIXED"
    assert result.memory_context.claim_versions == ["version-2"]
    assert result.evidence_receipt is not None
    assert result.evidence_receipt.authority_class == "MIXED"
    assert result.evidence_receipt.claim_versions == ["version-2"]


def test_mvp01_legacy_canonical_support_emits_lossless_mixed_receipt() -> None:
    evidence_id = "canonical-support-1"
    result = MemoryContextCompiler().compile(
        _request("What is the current release state?", budget=2_048),
        _outcome(
            [
                {
                    "kind": "CANONICAL_STATE",
                    "claim_id": "claim-release",
                    "claim_version_id": "version-release-3",
                    "evidence_ids": [evidence_id],
                    "payload": {"value": "ready"},
                }
            ]
        ),
    )

    context = result.memory_context
    receipt = result.evidence_receipt
    assert context.authority_class == "MIXED"
    assert context.selected_evidence_ids == [evidence_id]
    assert evidence_id not in context.text
    assert receipt is not None
    assert receipt.authority_class == "MIXED"
    assert receipt.source_evidence_ids == [evidence_id]
    assert receipt.claim_versions == ["version-release-3"]
    assert len(receipt.receipt_mapping) == 1
    assert receipt.receipt_mapping[0].alias == "C1"
    assert receipt.receipt_mapping[0].evidence_ids == [evidence_id]
    assert receipt.receipt_mapping[0].claim_versions == ["version-release-3"]


def test_mvp01_atomic_canonical_support_preserves_per_alias_lineage() -> None:
    items = [
        {
            "kind": "CANONICAL_STATE",
            "claim_id": "claim-alpha",
            "claim_version_id": "version-alpha",
            "evidence_ids": ["evidence-alpha"],
            "source_turn_refs": ["memory://session/alpha/turn/2"],
            "payload": {"value": "alpha"},
        },
        {
            "kind": "CANONICAL_STATE",
            "claim_id": "claim-beta",
            "claim_version_id": "version-beta",
            "source_evidence_ids": ["evidence-beta"],
            "source_ref": "memory://session/beta/turn/4",
            "payload": {"value": "beta"},
        },
    ]
    result = MemoryContextCompiler(budget_stable_enabled=True).compile(
        _request("Compare the current alpha and beta states", budget=2_048),
        _outcome(items),
    )

    context = result.memory_context
    receipt = result.evidence_receipt
    assert context.authority_class == "MIXED"
    assert set(context.selected_evidence_ids) == {
        "evidence-alpha",
        "evidence-beta",
    }
    assert set(context.selected_source_turn_refs) == {
        "memory://session/alpha/turn/2",
        "memory://session/beta/turn/4",
    }
    assert receipt is not None
    mappings_by_claim = {
        mapping.claim_versions[0]: mapping
        for mapping in receipt.receipt_mapping
        if mapping.claim_versions
    }
    assert mappings_by_claim["version-alpha"].evidence_ids == ["evidence-alpha"]
    assert mappings_by_claim["version-alpha"].source_turn_refs == ["memory://session/alpha/turn/2"]
    assert mappings_by_claim["version-beta"].evidence_ids == ["evidence-beta"]
    assert mappings_by_claim["version-beta"].source_turn_refs == ["memory://session/beta/turn/4"]
    assert {mapping.alias for mapping in mappings_by_claim.values()} == {"C1", "C2"}


def test_mvp01_canonical_without_explicit_support_does_not_fabricate_receipt() -> None:
    result = MemoryContextCompiler().compile(
        _request("What is the current release state?", budget=2_048),
        _outcome(
            [
                {
                    "kind": "CANONICAL_STATE",
                    "claim_id": "claim-release",
                    "claim_version_id": "version-release-3",
                    "payload": {"value": "ready"},
                }
            ]
        ),
    )

    assert result.memory_context.authority_class == "CANONICAL_STATE"
    assert result.memory_context.selected_evidence_ids == []
    assert result.memory_context.selected_source_turn_refs == []
    assert result.evidence_receipt is None


def test_q1r_reingest_uuid_changes_do_not_change_reader_context_bytes() -> None:
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    first = MemoryContextCompiler().compile(
        _request("Recall the cobalt code"),
        _outcome(
            [_evidence(first_id, "session-a", 1, "The code is 47.", speaker="assistant")]
        ),
    )
    second = MemoryContextCompiler().compile(
        _request("Recall the cobalt code"),
        _outcome(
            [_evidence(second_id, "session-a", 1, "The code is 47.", speaker="assistant")]
        ),
    )

    assert first.memory_context.text == second.memory_context.text
    assert first.memory_context.semantic_context_digest == (
        second.memory_context.semantic_context_digest
    )
    assert first.memory_context.reader_context_digest == (
        second.memory_context.reader_context_digest
    )
    assert first.memory_context.reader_context_digest == hashlib.sha256(
        first.memory_context.text.encode()
    ).hexdigest()
    assert first_id not in first.memory_context.text
    assert second_id not in second.memory_context.text
    assert "memory://session/session-a/turn/1" not in first.memory_context.text
    assert "[E1 EVIDENCE WINDOW" in first.memory_context.text

    first_receipt = first.evidence_receipt
    second_receipt = second.evidence_receipt
    assert first_receipt is not None and second_receipt is not None
    assert first_receipt.source_evidence_ids == [first_id]
    assert second_receipt.source_evidence_ids == [second_id]
    assert first_receipt.receipt_mapping[0].alias == "E1"
    assert first_receipt.receipt_mapping[0].evidence_ids == [first_id]
    assert second_receipt.receipt_mapping[0].evidence_ids == [second_id]


def test_reingest_operational_timestamp_does_not_change_reader_context() -> None:
    def derived(system_timestamp: str) -> dict[str, Any]:
        return {
            "canonical_mutation": False,
            "kind": "PREFERENCE_EVIDENCE_VIEW",
            "status": "PARTIAL",
            "value": [
                {
                    "source_timestamp": "2023-05-27T14:23:00+00:00",
                    "span": {
                        "text": "I enjoy live music.",
                        "provenance": {
                            "source_span_verified": True,
                            "system_timestamp": system_timestamp,
                        },
                    },
                }
            ],
        }

    first = MemoryContextCompiler().compile(
        _request("What music do I enjoy?"),
        _outcome([], derived_result=derived("2026-08-28T14:57:05+00:00")),
    )
    second = MemoryContextCompiler().compile(
        _request("What music do I enjoy?"),
        _outcome([], derived_result=derived("2026-08-28T15:19:53+00:00")),
    )

    assert first.memory_context.text == second.memory_context.text
    assert first.memory_context.semantic_context_digest == (
        second.memory_context.semantic_context_digest
    )
    assert first.memory_context.reader_context_digest == (
        second.memory_context.reader_context_digest
    )
    assert "system_timestamp" not in first.memory_context.text


def test_q1r_alias_mapping_round_trips_derived_window_and_canonical_provenance() -> None:
    evidence_id = "33333333-3333-4333-8333-333333333333"
    source_ref = "memory://session/session-a/turn/1"
    result = MemoryContextCompiler().compile(
        _request("Explain the derived current value", budget=2_048),
        _outcome(
            [
                {
                    "kind": "CANONICAL_STATE",
                    "claim_id": "44444444-4444-4444-8444-444444444444",
                    "claim_version_id": "55555555-5555-4555-8555-555555555555",
                    "payload": {"value": "current"},
                },
                _evidence(
                    evidence_id,
                    "session-a",
                    1,
                    "assistant: The derived current value is 47.",
                ),
            ],
            derived_result={
                "status": "COMPLETE",
                "kind": "OPERATOR_RESULT",
                "operator": "LOOKUP",
                "display_value": "47",
                "evidence_refs": [evidence_id],
                "source_turn_refs": [source_ref],
                "completeness": {"status": "COMPLETE"},
                "canonical_mutation": False,
                "canonical": False,
                "authority_class": "EVIDENCE_ONLY",
            },
        ),
    )

    context = result.memory_context
    receipt = result.evidence_receipt
    assert receipt is not None
    assert "[D1 DERIVED OPERATOR RESULT" in context.text
    assert "[C1 CANONICAL STATE" in context.text
    assert "[E1 EVIDENCE WINDOW" in context.text
    assert evidence_id not in context.text
    assert source_ref not in context.text
    assert "44444444-4444-4444-8444-444444444444" not in context.text
    assert "55555555-5555-4555-8555-555555555555" not in context.text

    mapped_evidence = {
        value
        for mapping in receipt.receipt_mapping
        for value in mapping.evidence_ids
    }
    mapped_sources = {
        value
        for mapping in receipt.receipt_mapping
        for value in mapping.source_turn_refs
    }
    mapped_claims = {
        value
        for mapping in receipt.receipt_mapping
        for value in mapping.claim_versions
    }
    assert mapped_evidence == set(receipt.source_evidence_ids) == {evidence_id}
    assert mapped_sources == set(context.selected_source_turn_refs) == {source_ref}
    assert mapped_claims == set(receipt.claim_versions) == {
        "55555555-5555-4555-8555-555555555555"
    }
    assert receipt.semantic_context_digest == context.semantic_context_digest
    assert receipt.reader_context_digest == context.reader_context_digest


def test_mvp01_budget_stable_receipt_assigns_each_evidence_to_one_alias() -> None:
    answer_id = "bicycle-answer"
    answer_ref = "memory://session/bicycle/turn/1"
    result = MemoryContextCompiler(budget_stable_enabled=True).compile(
        _request("What is the current bicycle lock reminder?", budget=2_048),
        _outcome(
            [
                _evidence(
                    "bicycle-question",
                    "bicycle",
                    0,
                    "I changed the bicycle reminder from cedar to maple.",
                ),
                _evidence(
                    answer_id,
                    "bicycle",
                    1,
                    "The current bicycle reminder is maple.",
                    speaker="assistant",
                ),
            ],
            status="ABSTAINED",
            evidence_refs=["bicycle-question", answer_id],
            derived_result={
                "status": "OK",
                "kind": "DERIVED_QUERY_RESULT",
                "operator": "LATEST_VALID_STATE",
                "value": "The current bicycle reminder is maple.",
                "operands": [
                    {
                        "authority_class": "EVIDENCE_ONLY",
                        "evidence_ids": [answer_id],
                        "source_ref": answer_ref,
                    }
                ],
                "completeness": {
                    "required_slots": ["CURRENT_STATE"],
                    "filled_slots": ["CURRENT_STATE"],
                    "unresolved_reasons": [],
                },
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        ),
    )

    context = result.memory_context
    receipt = result.evidence_receipt
    assert receipt is not None
    mapping_ids = [
        evidence_id
        for mapping in receipt.receipt_mapping
        for evidence_id in mapping.evidence_ids
    ]
    mapping_refs = [
        source_ref
        for mapping in receipt.receipt_mapping
        for source_ref in mapping.source_turn_refs
    ]
    assert mapping_ids == context.selected_evidence_ids
    assert mapping_refs == context.selected_source_turn_refs
    assert len(mapping_ids) == len(set(mapping_ids))
    assert len(mapping_refs) == len(set(mapping_refs))
    derived = next(mapping for mapping in receipt.receipt_mapping if mapping.alias == "D1")
    assert derived.evidence_ids == [answer_id]
    assert derived.source_turn_refs == [answer_ref]
    assert all(
        answer_id not in mapping.evidence_ids
        for mapping in receipt.receipt_mapping
        if mapping.alias.startswith("E")
    )
