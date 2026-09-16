from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_state import (
    acquisition_state_trace_summary,
    advance_acquisition_state,
    build_acquisition_action,
    build_acquisition_region,
    build_acquisition_window,
    build_evidence_reference_note,
    initialize_acquisition_state,
)
from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.query_planner import QueryPlanner
from milai.domain import (
    AcquisitionBudgetUse,
    AcquisitionResidualPolicy,
    CandidateEnvelope,
    RetrievalRequest,
    SufficiencyDecision,
)

REFERENCE = datetime(2026, 8, 27, 12, tzinfo=UTC)
QUERY = "How much did I pay per ceramic mug?"


def _source(*, revoked: bool = False) -> dict[str, object]:
    return {
        "evidence_id": "private-evidence-47",
        "source_ref": "memory://session/private-session/turn/0",
        "subject_id": "private-subject",
        "source_context": {
            "session_id": "private-session",
            "turn_id": "private-session:turn:0",
            "session_ordinal": 0,
            "round_ordinal": 0,
            "turn_ordinal": 0,
            "speaker": "user",
            "adjacent": [],
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": (REFERENCE + timedelta(seconds=1)).isoformat(),
        "content": "I paid $60 for 5 ceramic mugs in the cobalt workshop.",
        "content_hash": "content-hash",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": REFERENCE.isoformat() if revoked else None,
    }


def _plan(*, residual: bool = False):  # type: ignore[no-untyped-def]
    query_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=QUERY,
            requested_scope={"project_ids": ["milai"]},
        )
    )
    plan = compile_acquisition_plan(
        query_plan,
        query=QUERY,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    if residual:
        plan = plan.model_copy(
            update={
                "residual_policy": AcquisitionResidualPolicy(
                    allowed=True,
                    max_model_calls=1,
                    max_extra_passes=1,
                )
            }
        )
    return plan, query_plan.memory_query_ir


def _semantic_material():  # type: ignore[no-untyped-def]
    source = _source()
    plan, query_ir = _plan()
    assert query_ir is not None
    requirements = [value for value in query_ir.requirements if value.required]
    spans = project_evidence_spans([source])
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(requirements, interpretations, spans)
    return source, plan, requirements, spans, interpretations, bindings


def _matched_note(requirement_id: str):  # type: ignore[no-untyped-def]
    source, _plan_value, _requirements, spans, interpretations, bindings = (
        _semantic_material()
    )
    binding = next(
        value
        for value in bindings
        if value.requirement_id == requirement_id and value.status == "MATCH"
    )
    interpretation = next(
        value
        for value in interpretations
        if value.interpretation_id == binding.interpretation_id
    )
    span = next(value for value in spans if value.span_id == interpretation.span_id)
    return source, span, interpretation, binding, build_evidence_reference_note(
        source, span, interpretation, binding
    )


def _candidate() -> CandidateEnvelope:
    return CandidateEnvelope(
        candidate_id="private-evidence-47",
        source_evidence_id="private-evidence-47",
        source_turn_ref="memory://session/private-session/turn/0",
        subject_id="private-subject",
        session_id="private-session",
        turn_id="private-session:turn:0",
        identity_source="STRUCTURED_TURN_METADATA",
        speaker="user",
        speaker_source="STRUCTURED_TURN_METADATA",
        source_observed_at=REFERENCE,
        matched_probes=["slot:TOTAL_PRICE:fts-raw", "slot:ITEM_COUNT:fts-raw"],
        matched_slots=["TOTAL_PRICE", "ITEM_COUNT"],
        channel_ranks={"FTS_RAW": 1},
        channel_scores={"FTS_RAW": 1.0},
        probe_ranks={"slot:TOTAL_PRICE:fts-raw": 1},
        probe_scores={"slot:TOTAL_PRICE:fts-raw": 1.0},
        fusion_rank=1,
        fusion_score=1.0,
        matched_fields=["lexical_text"],
        body_ref="memory://session/private-session/turn/0",
        body_hydrated=True,
    )


def test_r2_initial_state_is_turn_local_noncanonical_and_allocates_zero_model_calls() -> None:
    plan, query_ir = _plan()
    assert query_ir is not None

    state = initialize_acquisition_state(plan, query_ir.requirements)

    assert state.schema_version == "acquisition-state-v0.1"
    assert state.lifetime == "MEMORY_RESOLVE"
    assert state.canonical is False
    assert state.canonical_mutation is False
    assert state.satisfied_requirement_ids == []
    assert set(state.missing_requirement_ids) == {"TOTAL_PRICE", "ITEM_COUNT"}
    assert state.remaining_budget.model_calls == 0
    assert state.remaining_budget.acquisition_passes == 0
    assert all(
        not value.covered_by_sufficiency
        for value in state.per_requirement_coverage.values()
    )


def test_r2_evidence_reference_note_is_source_exact_and_not_free_text_evidence() -> None:
    source, span, interpretation, binding, note = _matched_note("TOTAL_PRICE")

    assert note.evidence_id == source["evidence_id"]
    assert note.source_turn_ref == source["source_ref"]
    assert note.quote_span.start == span.start
    assert note.quote_span.end == span.end
    assert note.quote_span.quote_sha256 == hashlib.sha256(span.text.encode()).hexdigest()
    assert note.interpretation_ref == interpretation.interpretation_id
    assert note.requirement_id == binding.requirement_id
    assert note.canonical is False
    assert note.canonical_mutation is False
    assert "I paid $60" not in json.dumps(note.model_dump(mode="json"))


def test_r2_note_builder_rejects_binding_mismatch_and_ineligible_source() -> None:
    source, span, interpretation, binding, _note = _matched_note("TOTAL_PRICE")

    with pytest.raises(ValueError, match="BINDING_INTERPRETATION_MISMATCH"):
        build_evidence_reference_note(
            source,
            span,
            interpretation,
            binding.model_copy(update={"interpretation_id": "different-interpretation"}),
        )
    with pytest.raises(ValueError, match="SOURCE_NOT_ELIGIBLE"):
        build_evidence_reference_note(
            {**source, "revoked_at": REFERENCE.isoformat()},
            span,
            interpretation,
            binding,
        )
    for missing_gate in ("permission_snapshot", "retention_state"):
        source_with_unknown_gate = dict(source)
        del source_with_unknown_gate[missing_gate]
        with pytest.raises(ValueError, match="SOURCE_NOT_ELIGIBLE"):
            build_evidence_reference_note(
                source_with_unknown_gate,
                span,
                interpretation,
                binding,
            )
    for source_patch, reason in (
        ({"subject_id": "forged-subject"}, "SUBJECT_MISMATCH"),
        (
            {
                "source_context": {
                    **source["source_context"],
                    "session_id": "forged-session",
                }
            },
            "SESSION_MISMATCH",
        ),
        (
            {
                "source_context": {
                    **source["source_context"],
                    "turn_id": "forged-turn",
                }
            },
            "TURN_MISMATCH",
        ),
        ({"speaker": "assistant"}, "SPEAKER_MISMATCH"),
        (
            {"observed_at": (REFERENCE - timedelta(days=1)).isoformat()},
            "SOURCE_TIME_MISMATCH",
        ),
    ):
        with pytest.raises(ValueError, match=reason):
            build_evidence_reference_note(
                {**source, **source_patch},
                span,
                interpretation,
                binding,
            )


def test_r2_reference_note_digest_binds_all_semantic_provenance() -> None:
    _source_value, _span, _interpretation, _binding, note = _matched_note("TOTAL_PRICE")

    for patch in (
        {"observed_terms": ["forged"]},
        {"source_observed_time": REFERENCE - timedelta(days=1)},
        {"event_time": {"start": REFERENCE.isoformat()}},
        {"note_reason": "FORGED_REASON"},
    ):
        with pytest.raises(ValueError, match="digest does not match"):
            type(note).model_validate({**note.model_dump(mode="json"), **patch})


def test_r2_transition_uses_binding_and_sufficiency_without_redefining_either() -> None:
    source, plan, requirements, _spans, _interpretations, bindings = _semantic_material()
    state = initialize_acquisition_state(plan, requirements)
    _source_value, _span, _interpretation, _binding, note = _matched_note("TOTAL_PRICE")
    action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    window = build_acquisition_window(
        session_id=str(source["subject_id"]), turn_start=0, turn_end_exclusive=1
    )
    region = build_acquisition_region(window, action, state.missing_requirement_ids)
    decision = SufficiencyDecision(
        status="PARTIAL",
        covered_slots=["TOTAL_PRICE"],
        missing_slots=["ITEM_COUNT"],
        stop_reason="SEARCH_SPACE_EXHAUSTED",
    )

    transition = advance_acquisition_state(
        state,
        action,
        candidates=[_candidate()],
        bindings=bindings,
        notes=[note],
        windows=[window],
        inspected_regions=[region],
        sufficiency_decision=decision,
        budget_use=AcquisitionBudgetUse(candidate_count=1, context_tokens=10, latency_ms=3.5),
    )

    assert transition.outcome == "APPLIED"
    assert transition.state.satisfied_requirement_ids == ["TOTAL_PRICE"]
    assert transition.state.missing_requirement_ids == ["ITEM_COUNT"]
    price = transition.state.per_requirement_coverage["TOTAL_PRICE"]
    assert price.covered_by_sufficiency is True
    assert price.accepted_evidence_refs == ["private-evidence-47"]
    assert note.interpretation_ref in price.matched_interpretation_refs
    assert transition.state.remaining_budget.candidate_count == 11
    assert transition.state.remaining_budget.context_tokens == 502
    assert transition.state.remaining_budget.latency_ms == plan.budget.latency_ms - 3.5


def test_r2_repeated_action_and_window_are_typed_noop_transitions() -> None:
    plan, query_ir = _plan(residual=True)
    assert query_ir is not None
    state = initialize_acquisition_state(plan, query_ir.requirements)
    first_action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
    )
    window = build_acquisition_window(
        session_id="private-session", turn_start=0, turn_end_exclusive=1
    )
    first = advance_acquisition_state(state, first_action, windows=[window])
    assert first.outcome == "APPLIED"

    repeated_action = advance_acquisition_state(first.state, first_action)
    assert repeated_action.outcome == "REPEATED_ACTION"
    assert repeated_action.state == first.state

    second_action = build_acquisition_action(
        action_kind="RESIDUAL_PASS",
        pass_index=1,
        requirement_ids=first.state.missing_requirement_ids,
    )
    repeated_window = advance_acquisition_state(
        first.state,
        second_action,
        windows=[window],
        budget_use=AcquisitionBudgetUse(acquisition_passes=1),
    )
    assert repeated_window.outcome == "REPEATED_WINDOW"
    assert repeated_window.repeated_window_count == 1
    assert repeated_window.state == first.state


def test_r2_pass_order_and_required_budget_charges_are_fail_closed() -> None:
    plan, query_ir = _plan(residual=True)
    assert query_ir is not None
    initial = initialize_acquisition_state(plan, query_ir.requirements)
    residual = build_acquisition_action(
        action_kind="RESIDUAL_PASS",
        pass_index=1,
        requirement_ids=initial.missing_requirement_ids,
    )
    out_of_order = advance_acquisition_state(
        initial,
        residual,
        budget_use=AcquisitionBudgetUse(acquisition_passes=1),
    )
    assert out_of_order.reason_code == "RESIDUAL_PASS_ORDER_OR_COST_INVALID"
    deterministic = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
    )
    first = advance_acquisition_state(initial, deterministic)
    uncharged = advance_acquisition_state(first.state, residual)
    assert uncharged.reason_code == "RESIDUAL_PASS_ORDER_OR_COST_INVALID"
    assert uncharged.state == first.state


def test_r2_same_session_different_missing_slot_and_region_remain_searchable() -> None:
    plan, query_ir = _plan(residual=True)
    assert query_ir is not None
    initial = initialize_acquisition_state(plan, query_ir.requirements)
    first_action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
    )
    first_window = build_acquisition_window(
        session_id="shared-session", turn_start=0, turn_end_exclusive=1
    )
    first_region = build_acquisition_region(first_window, first_action, ["TOTAL_PRICE"])
    first = advance_acquisition_state(
        initial,
        first_action,
        windows=[first_window],
        inspected_regions=[first_region],
        exhausted_regions=[first_region],
        sufficiency_decision=SufficiencyDecision(
            status="PARTIAL",
            covered_slots=["TOTAL_PRICE"],
            missing_slots=["ITEM_COUNT"],
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
    )
    assert first.outcome == "APPLIED"

    second_action = build_acquisition_action(
        action_kind="RESIDUAL_PASS",
        pass_index=1,
        requirement_ids=["ITEM_COUNT"],
    )
    second_window = build_acquisition_window(
        session_id="shared-session", turn_start=3, turn_end_exclusive=5
    )
    second_region = build_acquisition_region(second_window, second_action, ["ITEM_COUNT"])
    second = advance_acquisition_state(
        first.state,
        second_action,
        windows=[second_window],
        inspected_regions=[second_region],
        budget_use=AcquisitionBudgetUse(acquisition_passes=1),
    )

    assert second.outcome == "APPLIED"
    assert len(second.state.seen_window_intervals) == 2
    assert second.state.seen_window_intervals[0].session_id == (
        second.state.seen_window_intervals[1].session_id
    )
    assert second.state.remaining_budget.acquisition_passes == 0


def test_r2_budget_block_is_fail_closed_and_trace_summary_omits_private_material() -> None:
    source, plan, requirements, _spans, _interpretations, bindings = _semantic_material()
    state = initialize_acquisition_state(plan, requirements)
    _source_value, _span, _interpretation, _binding, note = _matched_note("TOTAL_PRICE")
    action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
    )
    applied = advance_acquisition_state(
        state,
        action,
        candidates=[_candidate()],
        bindings=bindings,
        notes=[note],
        seen_anchor_ids=[str(source["evidence_id"])],
    )
    assert applied.outcome == "APPLIED"

    summary = acquisition_state_trace_summary(applied.state)
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    assert "private-evidence-47" not in encoded
    assert "private-session" not in encoded
    assert "cobalt workshop" not in encoded
    assert "I paid $60" not in encoded
    assert summary["canonical"] is False
    assert summary["canonical_mutation"] is False

    blocked = advance_acquisition_state(
        state,
        action,
        budget_use=AcquisitionBudgetUse(
            candidate_count=plan.budget.candidate_count + 1
        ),
    )
    assert blocked.outcome == "BUDGET_BLOCKED"
    assert blocked.state == state
