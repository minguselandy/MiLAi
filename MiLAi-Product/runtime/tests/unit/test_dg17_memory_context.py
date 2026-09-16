from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from milai.application import memory_context as context_module
from milai.application.memory_context import MemoryContextCompiler, _order_windows
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.memory_context import MemoryContextWindow
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


def _count_ir(*, member_enumeration: bool) -> dict[str, Any]:
    return {
        "schema_version": "memory-query-ir-v0.2",
        "mode": "COMPOSE",
        "answer_shape": "SCALAR",
        "requirements": [],
        "steps": [
            {
                "kind": "RETRIEVE",
                "constraints": {"operator_family": "COUNT"},
            }
        ],
        "completeness": (
            "ALL_MATCHES_IN_RANGE"
            if member_enumeration
            else "ALL_REQUIRED_BINDINGS"
        ),
    }


@pytest.mark.parametrize("expansion", ["same", "copied", "new_source"])
def test_baseline_views_reuse_only_the_same_owned_item_sequence(expansion: str) -> None:
    compiler = MemoryContextCompiler()
    original_expand = compiler._expand_items
    added = _evidence("added", "session-b", 1, "A newly acquired source.")

    def expand(*args: Any, **kwargs: Any) -> Any:
        items, traces, activation = original_expand(*args, **kwargs)
        if expansion == "copied":
            items = [dict(item) for item in items]
        elif expansion == "new_source":
            items = [*items, added]
        return items, traces, activation

    outcome = _outcome([_evidence("original", "session-a", 1, "The code is 47.")])
    with patch.object(compiler, "_expand_items", expand):
        with patch.object(
            context_module, "_evidence_views", wraps=context_module._evidence_views,
        ) as views:
            result = compiler.compile(_request("Recall the code", budget=2048), outcome)
    assert views.call_count == (1 if expansion == "same" else 2)
    trace = result.memory_context.compile_trace
    assert trace["baseline_candidate_evidence_views"] == 1
    assert trace["candidate_evidence_views"] == (2 if expansion == "new_source" else 1)
    assert outcome["items"][0]["content"] == "The code is 47."


def test_mvp_u0_exact_16384_context_budget_is_accepted_and_16385_is_rejected() -> None:
    request = _request("Recall the cobalt code", budget=16_384)
    result = MemoryContextCompiler().compile(
        request,
        _outcome([_evidence("answer", "session-a", 1, "The code is 47.")]),
    )
    envelope = ContextBudgetEnvelope(
        requested_cap=16_384,
        available_memory_tokens=16_384,
        budget_source="CALLER_CAP_ONLY",
    )

    assert request.budget.max_context_tokens == 16_384
    assert result.memory_context.token_budget == 16_384
    assert envelope.available_memory_tokens == 16_384
    with pytest.raises(ValidationError):
        MemoryResolveBudget(max_context_tokens=16_385)
    with pytest.raises(ValidationError):
        ContextBudgetEnvelope(
            requested_cap=16_385,
            available_memory_tokens=16_385,
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


def test_product10_legacy_context_trace_publishes_candidate_and_omission_identity() -> None:
    result = MemoryContextCompiler().compile(
        _request("Recall the cobalt code", budget=128),
        _outcome(
            [
                _evidence(
                    "answer",
                    "session-a",
                    1,
                    "The cobalt code is 47." + (" supporting detail" * 40),
                ),
                _evidence(
                    "distractor",
                    "session-b",
                    1,
                    "A separate itinerary detail." + (" unrelated detail" * 40),
                    score=0.1,
                ),
            ]
        ),
    )

    trace = result.memory_context.compile_trace
    candidates = trace["candidate_window_trace"]
    selected = trace["selected_unit_ids"]
    omitted = trace["omitted_unit_reasons"]

    assert len(candidates) == 2
    assert selected
    assert omitted
    assert set(selected).isdisjoint(omitted)
    assert all("text" not in candidate for candidate in candidates)
    assert trace["budget_envelope"]["available_memory_tokens"] == 128
    assert len(trace["reader_evidence_plan_digest"]) == 64


def test_product10_instance_preserving_admission_retains_same_pool_identity_fallback() -> None:
    repeated = "The project update is unchanged." + (" supporting detail" * 18)
    all_candidates = [
        _evidence(f"evidence-{index}", f"session-{index}", 0, repeated)
        for index in range(6)
    ]
    result = MemoryContextCompiler(
        instance_preserving_admission_enabled=True
    ).compile(
        _request("Recall project updates across sessions", budget=256),
        _outcome(
            all_candidates[:3],
            _reader_evidence_boundary="GOVERNANCE_ADMITTED_SOFT_RANKED",
            _instance_preserving_candidate_items=all_candidates,
        ),
    )

    trace = result.memory_context.compile_trace
    candidate_ids = {
        evidence_id
        for window in trace["candidate_window_trace"]
        for evidence_id in window["evidence_ids"]
    }
    selected = set(result.memory_context.selected_evidence_ids)

    assert candidate_ids == {f"evidence-{index}" for index in range(6)}
    assert selected
    assert selected < candidate_ids
    assert trace["instance_preserving_admission_enabled"] is True
    assert trace["baseline_candidate_evidence_views"] == 3
    assert trace["candidate_evidence_views"] == 6
    assert trace["whole_unit_admission"] is True
    assert trace["recall_workspace_trace"]["all_candidate_ids_retained"] is True
    assert trace["recall_workspace_trace"]["hard_filter_applied"] is False


def test_count_member_context_does_not_treat_numbered_advice_as_the_answer() -> None:
    result = MemoryContextCompiler().compile(
        _request("How many items do I need to pick up or return?", budget=2_048),
        _outcome(
            [
                _evidence(
                    "numbered-advice",
                    "advice",
                    0,
                    "1. Check the store receipt. 2. Review the return policy.",
                    score=1.0,
                    speaker="assistant",
                ),
                _evidence(
                    "pickup-member",
                    "pickup",
                    0,
                    "I still need to pick up the repaired jacket.",
                    score=0.9,
                ),
                _evidence(
                    "return-member",
                    "return",
                    0,
                    "I need to return the duplicate package.",
                    score=0.8,
                ),
                _evidence(
                    "same-session-followup",
                    "pickup",
                    2,
                    "The pickup reminder is still active.",
                    score=0.7,
                ),
            ],
            memory_query_ir=_count_ir(member_enumeration=True),
        ),
    )

    context = result.memory_context
    assert all(window.answer_signal is False for window in context.windows)
    assert context.compile_trace["session_diversity_objective_enabled"] is False


def test_scalar_count_fact_keeps_numeric_answer_signal() -> None:
    result = MemoryContextCompiler().compile(
        _request("How many engineers do I currently lead?", budget=2_048),
        _outcome(
            [
                _evidence(
                    "question-paraphrase",
                    "question",
                    0,
                    "How many engineers do I currently lead?",
                    score=1.0,
                ),
                _evidence(
                    "scalar-answer",
                    "answer",
                    0,
                    "I currently lead 4 engineers.",
                    score=0.8,
                ),
            ],
            memory_query_ir=_count_ir(member_enumeration=False),
        ),
    )

    assert result.memory_context.windows[0].evidence_ids == ["scalar-answer"]
    assert result.memory_context.windows[0].answer_signal is True


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


def test_product07_pairs_session_head_landmark_with_query_anchor() -> None:
    landmark = _evidence(
        "session-head",
        "aquarium-session",
        0,
        "The aquarium has ten neon tetras and five gouramis.",
        score=0.0,
    )
    landmark["context_expansion"] = {
        "trigger": "ADJACENT_ROUND",
        "source_evidence_id": "walk-parent",
        "round_distance": 1,
    }
    result = MemoryContextCompiler(query_preserving_union_enabled=True).compile(
        _request("How many fish are in both aquariums?", budget=2_048),
        _outcome(
            [
                _evidence(
                    "query-anchor",
                    "aquarium-session",
                    8,
                    "New decorations provide hiding places for the fish.",
                ),
                landmark,
                _evidence(
                    "other-session",
                    "other",
                    0,
                    "The other aquarium contains one betta fish.",
                ),
            ]
        ),
    )

    aquarium = next(
        window
        for window in result.memory_context.windows
        if window.session_id == "aquarium-session"
    )
    assert aquarium.evidence_ids == ["session-head", "query-anchor"]


def test_product07_same_pool_selector_promotes_uncovered_query_target() -> None:
    items = [
        _evidence(
            "parents",
            "parents-session",
            0,
            "My parents are 55 and 58 years of age.",
            score=1.0,
        ),
        *[
            _evidence(
                f"age-distractor-{index}",
                f"distractor-{index}",
                0,
                ("The age of parents in this unrelated survey is 40 years. " * 16).strip(),
                score=0.9 - index / 100,
            )
            for index in range(4)
        ],
        _evidence(
            "grandparents",
            "grandparents-session",
            0,
            ("My grandparents include grandma at 75 and grandpa at 78. " * 8).strip(),
            score=0.4,
        ),
    ]
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material={},
    )
    baseline = MemoryContextCompiler(
        budget_stable_enabled=True,
        query_preserving_union_enabled=True,
    ).compile(
        _request("What is the average age of my parents and grandparents?", budget=512),
        _outcome(items),
        decision_snapshot=snapshot,
    )
    treatment = MemoryContextCompiler(
        budget_stable_enabled=True,
        query_preserving_union_enabled=True,
        evidence_set_selection_enabled=True,
    ).compile(
        _request("What is the average age of my parents and grandparents?", budget=512),
        _outcome(items),
        decision_snapshot=snapshot,
    )

    baseline_candidates = {
        evidence_id
        for row in baseline.memory_context.compile_trace["candidate_window_trace"]
        for evidence_id in row["evidence_ids"]
    }
    treatment_trace = treatment.memory_context.compile_trace
    treatment_candidates = {
        evidence_id
        for row in treatment_trace["candidate_window_trace"]
        for evidence_id in row["evidence_ids"]
    }
    assert baseline_candidates == treatment_candidates
    baseline_order = [
        evidence_id
        for row in baseline.memory_context.compile_trace["candidate_window_trace"]
        for evidence_id in row["evidence_ids"]
    ]
    treatment_order = [
        evidence_id
        for row in treatment_trace["candidate_window_trace"]
        for evidence_id in row["evidence_ids"]
    ]
    unit_ids = {
        row["evidence_ids"][0]: f"evidence:{row['window_id']}"
        for row in treatment_trace["candidate_window_trace"]
    }
    baseline_conditional = baseline.memory_context.compile_trace[
        "conditional_unit_order"
    ]
    treatment_conditional = treatment_trace["conditional_unit_order"]
    assert baseline_order == treatment_order
    assert baseline_order.index("grandparents") > 1
    assert baseline_conditional.index(unit_ids["grandparents"]) > 1
    assert treatment_conditional[:2] == [
        unit_ids["parents"],
        unit_ids["grandparents"],
    ]
    assert treatment_trace["recall_workspace_trace"]["hard_filter_applied"] is False
    assert treatment_trace["recall_workspace_trace"]["all_candidate_ids_retained"] is True
    assert treatment_trace["recall_workspace_trace"]["identity_set_preserved"] is True
    assert (
        treatment_trace["recall_workspace_trace"]["input_identity_digest"]
        == treatment_trace["recall_workspace_trace"]["output_identity_digest"]
    ) is True
    assert (
        treatment_trace["recall_workspace_trace"]["input_order_digest"]
        == treatment_trace["recall_workspace_trace"]["output_order_digest"]
    ) is False


def test_product08_soft_window_does_not_force_an_oversized_landmark() -> None:
    items = [
        _evidence(
            "oversized-landmark",
            "shared-session",
            0,
            ("Unrelated background material. " * 2_000).strip(),
        ),
        _evidence(
            "compact-anchor",
            "shared-session",
            4,
            "The compact governed observation contains the requested cobalt code 47.",
        ),
    ]
    snapshot = build_decision_snapshot(
        source_snapshot_material={},
        query_ir_material={},
        acquisition_plan_material={},
        candidate_snapshot_material={},
        gate_material={},
        binding_material={},
        requirement_state_material={},
        sufficiency_material={},
        operator_result_material={},
    )
    outcome = _outcome(items)
    outcome["_reader_evidence_boundary"] = "GOVERNANCE_ADMITTED_SOFT_RANKED"

    result = MemoryContextCompiler(
        budget_stable_enabled=True,
        query_preserving_union_enabled=True,
    ).compile(
        _request("Recall the cobalt code", budget=512),
        outcome,
        decision_snapshot=snapshot,
    )

    compact_window = next(
        row
        for row in result.memory_context.compile_trace["candidate_window_trace"]
        if "compact-anchor" in row["evidence_ids"]
    )
    assert compact_window["evidence_ids"] == ["compact-anchor"]
    assert "compact-anchor" in result.memory_context.selected_evidence_ids


def test_product08_soft_order_bounds_session_first_diversity() -> None:
    def window(window_id: str, session_id: str, source_rank: int) -> MemoryContextWindow:
        return MemoryContextWindow(
            window_id=window_id,
            session_id=session_id,
            evidence_ids=[window_id],
            source_turn_refs=[f"memory://{window_id}"],
            speakers=["USER"],
            text="compact evidence unit",
            source_rank=source_rank,
            query_overlap=0,
            answer_signal=False,
            requirement_priority=False,
        )

    ordered = _order_windows(
        [
            window("a-first", "session-a", 1),
            window("a-second", "session-a", 2),
            window("b-first", "session-b", 3),
            window("c-first", "session-c", 4),
            window("d-first", "session-d", 5),
            window("e-first", "session-e", 6),
        ],
        multi_session_required=True,
        token_efficient=True,
    )

    assert [item.window_id for item in ordered] == [
        "a-first",
        "b-first",
        "c-first",
        "d-first",
        "a-second",
        "e-first",
    ]


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


def test_mvp01_budget_stable_trace_separates_raw_admitted_and_reader_visible() -> None:
    result = MemoryContextCompiler(
        budget_stable_enabled=True,
        exact_token_counter=len,
        exact_tokenizer_identity="character-counter-test-v1",
    ).compile(
        _request("请回忆钴蓝代码", budget=2_048),
        _outcome(
            [
                _evidence(
                    "answer",
                    "session-a",
                    1,
                    "钴蓝代码是 47。",
                    speaker="assistant",
                )
            ],
            trace_id="retrieval-trace-1",
        ),
    )

    context = result.memory_context
    raw = context.compile_trace["raw_retrieval_trace"]
    admitted = context.compile_trace["admitted_evidence_trace"]
    visible = context.compile_trace["reader_visible_trace"]
    assert isinstance(raw, dict)
    assert raw["trace_pointer"] == "retrieval-trace-1"
    assert raw["candidate_count"] == 1
    assert raw["semantic_effect_eligible"] is True
    assert isinstance(admitted, dict)
    assert admitted["selected_evidence_ids"] == ["answer"]
    assert admitted["whole_unit_admission"] is True
    assert admitted["atomic_unit_truncation_count"] == 0
    assert isinstance(visible, dict)
    assert visible["serialization_replay_equivalent"] is True
    assert visible["reader_context_sha256"] == context.reader_context_digest
    assert visible["exact_context_tokens"] == len(context.text)
    assert visible["reader_call_count"] == 0

    rendered_units = visible["rendered_units"]
    assert isinstance(rendered_units, list)
    assert rendered_units
    encoded = context.text.encode("utf-8")
    for unit in rendered_units:
        assert isinstance(unit, dict)
        char_offset = unit["serialized_char_offset"]
        byte_offset = unit["serialized_utf8_byte_offset"]
        assert isinstance(char_offset, dict)
        assert isinstance(byte_offset, dict)
        char_text = context.text[char_offset["start"] : char_offset["end"]]
        byte_text = encoded[byte_offset["start"] : byte_offset["end"]].decode()
        assert char_text == byte_text
        assert hashlib.sha256(byte_text.encode()).hexdigest() == unit[
            "serialized_unit_sha256"
        ]
        assert unit["memory_token_start"] == char_offset["start"]
        assert unit["memory_token_end"] == char_offset["end"]


def test_mvp01_unknown_identity_is_not_semantic_effect_eligible() -> None:
    legacy = _evidence("legacy", "session-a", 1, "The code is 47.")
    legacy.pop("source_context")
    legacy.pop("source_context_source")
    result = MemoryContextCompiler(budget_stable_enabled=True).compile(
        _request("Recall the code", budget=512),
        _outcome([legacy]),
    )

    raw = result.memory_context.compile_trace["raw_retrieval_trace"]
    assert isinstance(raw, dict)
    assert raw["semantic_effect_eligible"] is False
    candidates = raw["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["identity_source"] == "UNKNOWN"


def test_mvp01_budget_infeasible_terminal_has_exact_reader_visible_trace() -> None:
    result = MemoryContextCompiler(budget_stable_enabled=True).compile(
        _request("Recall the oversized protected result", budget=128),
        _outcome(
            [],
            derived_result={
                "status": "COMPLETE",
                "kind": "OPERATOR_RESULT",
                "operator": "LOOKUP",
                "display_value": "large-" * 2_000,
                "evidence_refs": [],
                "source_turn_refs": [],
                "completeness": {"status": "COMPLETE"},
                "canonical_mutation": False,
                "canonical": False,
                "authority_class": "EVIDENCE_ONLY",
            },
        ),
    )

    context = result.memory_context
    visible = context.compile_trace["reader_visible_trace"]
    assert context.compile_trace["reader_readiness"] == "BUDGET_INFEASIBLE"
    assert isinstance(visible, dict)
    assert visible["rendered_units"] == []
    parts = visible["serialization_parts"]
    assert isinstance(parts, list)
    assert len(parts) == 5
    replay = "\n\n".join(
        context.text[
            part["serialized_char_offset"]["start"] : part[
                "serialized_char_offset"
            ]["end"]
        ]
        for part in parts
    )
    assert replay == context.text
    assert visible["serialization_replay_equivalent"] is True
    assert visible["serialization_replay_sha256"] == context.reader_context_digest
