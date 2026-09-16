from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_state import (
    advance_acquisition_state,
    build_acquisition_action,
    initialize_acquisition_state,
    reserve_residual_controller_call,
)
from milai.application.query_planner import QueryPlanner
from milai.application.residual_refinding import (
    MAX_OBSERVATION_SNIPPET_CHARS,
    MAX_RESIDUAL_COMPLETION_TOKENS,
    ResidualHintShadowService,
    ResidualRefindingError,
    build_acquisition_observation,
    evaluate_residual_candidate_eligibility,
    normalize_residual_cue_proposal,
    residual_cue_proposal_output_schema,
    validate_residual_search_hint,
)
from milai.application.semantic_hint import SemanticHintCompletion
from milai.domain.acquisition import AcquisitionResidualPolicy
from milai.domain.residual_refinding import (
    ResidualActivation,
    ResidualAdditionalAcquisition,
    ResidualControllerTrace,
    ResidualCueProposal,
    ResidualDeterministicState,
    ResidualHintTrace,
    ResidualRefindingTrace,
    ResidualSearchHint,
    ResidualTemporalCue,
)
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2026, 8, 27, tzinfo=UTC)


class _Provider:
    def __init__(
        self,
        content: dict[str, object],
        *,
        calls: int = 1,
        retries: int = 0,
    ) -> None:
        self.content = content
        self.provider_calls = calls
        self.retries = retries
        self.messages: Any = None
        self.schema: Any = None
        self.max_tokens: int | None = None

    def complete_structured(  # type: ignore[no-untyped-def]
        self,
        *,
        messages,
        schema_name,
        schema,
        max_completion_tokens,
        seed,
    ) -> SemanticHintCompletion:
        self.messages = messages
        self.schema = schema
        self.max_tokens = max_completion_tokens
        assert schema_name == "residual_cue_proposal_v01"
        assert seed >= 0
        return SemanticHintCompletion(
            content=json.dumps(self.content),
            provider="fake-vllm",
            model="fake-controller",
            prompt_tokens=120,
            completion_tokens=31,
            tokenizer_latency_ms=1.0,
            queue_ms=2.0,
            ttft_ms=3.0,
            decode_ms=4.0,
            total_ms=9.0,
            provider_calls=self.provider_calls,
            automatic_retry_count=self.retries,
        )


def _plan_and_state() -> tuple[Any, Any, list[Any]]:
    query = "Which happened first, the cobalt launch or the amber review?"
    request = RetrievalRequest(route="L1", query=query, as_of=REFERENCE)
    query_plan = QueryPlanner().plan(request, access_intent="REQUIRED")
    plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=30,
        context_tokens=2_048,
        tenant_id="tenant-a",
        principal_id="principal-a",
    ).model_copy(
        update={
            "residual_policy": AcquisitionResidualPolicy(
                allowed=True,
                max_model_calls=1,
                max_extra_passes=1,
            )
        }
    )
    assert query_plan.memory_query_ir is not None
    requirements = list(query_plan.memory_query_ir.requirements)
    initial = initialize_acquisition_state(plan, requirements)
    deterministic = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=initial.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    transition = advance_acquisition_state(initial, deterministic)
    assert transition.outcome == "APPLIED"
    return plan, transition.state, requirements


def _reserve(state: Any, plan: Any) -> Any:
    transition = reserve_residual_controller_call(state, plan)
    assert transition.outcome == "APPLIED"
    return transition.state


def _hint(requirement_id: str) -> dict[str, object]:
    return {
        "schema_version": "residual-search-hint-v0.1",
        "requirement_id": requirement_id,
        "action": "SEARCH_LEXICAL",
        "lexical_cues": {
            "terms": ["deployment"],
            "phrases": ["rolled out"],
            "entity_aliases": [],
            "predicate_rephrasings": ["went live"],
        },
        "temporal_cue": {"axis": "NO_CHANGE"},
        "source_preference": "BOTH",
        "cue_provenance": "OBSERVATION",
        "rationale_code": "LEXICAL_MISMATCH",
    }


def _proposal(requirement_id: str) -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "action": "SEARCH_LEXICAL",
        "cues": ["deployment"],
    }


def _candidate(content: str, *, readable: bool = True) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "canonical_mutation": False,
        "tenant_id": "tenant-a",
        "principal_id": "principal-a",
        "scope_predicate": {"project_ids": ["milai"]},
        "evidence_id": "evidence-1",
        "source_ref": "memory://session/alpha/turn/4",
        "subject_id": "alpha",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": content,
        "content_hash": "a" * 64,
        "permission_snapshot": {
            "readable": readable,
            "project_ids": ["milai"],
        },
        "retention_state": "READABLE",
        "revoked_at": None,
        "authority_class": "EVIDENCE_ONLY",
        "fallback_used": False,
        "acquisition_candidate": {
            "matched_slots": ["EVENT_1"],
            "channel_ranks": {"FTS_RAW": 1},
        },
    }


def test_r3_observation_is_bounded_gated_and_uses_ephemeral_identity() -> None:
    plan, state, requirements = _plan_and_state()
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[
            _candidate("The rollout used the internal word deployment. " + "x" * 900),
            {**_candidate("revoked text"), "evidence_id": "revoked", "revoked_at": REFERENCE},
            {
                **_candidate("permission denied"),
                "evidence_id": "denied",
                "permission_snapshot": {"readable": False},
            },
        ],
        state=state,
        plan=plan,
    )

    assert len(observation.candidate_summaries) == 1
    summary = observation.candidate_summaries[0]
    assert summary.ephemeral_candidate_ref.startswith("candidate-")
    assert summary.session_ref.startswith("session-")
    assert len(summary.bounded_snippet) <= MAX_OBSERVATION_SNIPPET_CHARS + 2
    assert "evidence-1" not in observation.model_dump_json()
    assert observation.canonical is False
    assert observation.canonical_mutation is False


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"scope_predicate": {"project_ids": ["other"]}}, "SCOPE_MISMATCH"),
        ({"tenant_id": "other-tenant"}, "TENANT_MISMATCH"),
        ({"principal_id": "other-principal"}, "PRINCIPAL_MISMATCH"),
        ({"permission_snapshot": {}}, "PERMISSION_UNKNOWN"),
        ({"revoked_at": REFERENCE.isoformat()}, "REVOKED_EVIDENCE"),
        ({"authority_class": "CANONICAL_STATE"}, "AUTHORITY_MISMATCH"),
        ({"fallback_used": True}, "HIDDEN_FALLBACK"),
    ],
)
def test_r3_candidate_snippet_gate_rejects_adversarial_boundary_drift(
    patch: dict[str, object], reason: str
) -> None:
    plan, state, requirements = _plan_and_state()
    source = {**_candidate("PRIVATE_WRONG_SCOPE_MARKER"), **patch}
    receipt = evaluate_residual_candidate_eligibility(raw=source, plan=plan)
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[source],
        state=state,
        plan=plan,
    )

    assert receipt.eligible is False
    assert receipt.reason_code == reason
    assert observation.candidate_summaries == []
    assert "PRIVATE_WRONG_SCOPE_MARKER" not in observation.model_dump_json()


def test_r3_search_hint_schema_cannot_encode_evidence_answer_or_scope() -> None:
    _plan, state, _requirements = _plan_and_state()
    requirement_id = state.missing_requirement_ids[0]
    for forbidden in (
        {"final_answer": "done"},
        {"evidence_id": "evidence-1"},
        {"scope": {"project_ids": ["other"]}},
        {"complete": True},
    ):
        with pytest.raises(ValidationError):
            ResidualSearchHint.model_validate({**_hint(requirement_id), **forbidden})
    for control_cue in (
        "final answer is cobalt",
        "status COMPLETE",
        "evidence-forged-id",
        "expand authority",
    ):
        payload = _hint(requirement_id)
        payload["lexical_cues"] = {"terms": [control_cue]}
        with pytest.raises(ValidationError, match="forbidden control"):
            ResidualSearchHint.model_validate(payload)


def test_r3_minimal_residual_cue_proposal_is_flat_and_fail_closed() -> None:
    proposal = ResidualCueProposal.model_validate(
        {
            "requirement_id": "TARGET_EVENT",
            "action": "SEARCH_LEXICAL",
            "cues": ["rollout"],
        }
    )
    assert proposal.action == "SEARCH_LEXICAL"
    for invalid in (
        {"requirement_id": "TARGET_EVENT", "action": "EXPAND_EPISODE", "cues": []},
        {"requirement_id": "TARGET_EVENT", "action": "SEARCH_LEXICAL", "cues": []},
        {
            "requirement_id": "TARGET_EVENT",
            "action": "NO_ACTION",
            "cues": ["scope override"],
        },
        {
            "requirement_id": "TARGET_EVENT",
            "action": "NO_ACTION",
            "cues": [],
            "complete": True,
        },
    ):
        with pytest.raises(ValidationError):
            ResidualCueProposal.model_validate(invalid)


def test_r3_provider_wire_schema_uses_only_conformed_flat_subset() -> None:
    schema = residual_cue_proposal_output_schema()
    serialized = json.dumps(schema, sort_keys=True)

    assert set(schema["properties"]) == {"requirement_id", "action", "cues"}
    assert schema["required"] == ["requirement_id", "action", "cues"]
    assert schema["additionalProperties"] is False
    assert all(key not in serialized for key in ("uniqueItems", "oneOf", "anyOf"))
    assert "EXPAND_EPISODE" not in serialized


def test_r3_shadow_receipts_exactly_one_call_and_never_changes_product() -> None:
    plan, state, requirements = _plan_and_state()
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[_candidate("The cobalt deployment rolled out quietly.")],
        state=state,
        plan=plan,
    )
    provider = _Provider(_proposal(state.missing_requirement_ids[0]))
    reserved = _reserve(state, plan)
    receipt = ResidualHintShadowService(provider).generate(
        run_id="dg18-r3-test",
        case_id="unseen-entities",
        observation=observation,
        state=reserved,
        plan=plan,
    )
    validation = validate_residual_search_hint(
        hint=receipt.hint,
        state=reserved,
        plan=plan,
    )

    assert provider.max_tokens == MAX_RESIDUAL_COMPLETION_TOKENS
    assert receipt.model_call_count == 1
    assert receipt.automatic_retry_count == 0
    assert receipt.product_result_changed is False
    assert receipt.canonical_mutation is False
    assert validation.status == "ACCEPTED"
    assert validation.source_preference_is_soft is True
    payload = json.loads(provider.messages[1]["content"])
    assert "gold_answer" not in payload
    assert "expected_output" not in payload
    assert "final_answer" not in json.dumps(provider.schema)
    assert set(provider.schema["properties"]["action"]["enum"]) == {
        "SEARCH_LEXICAL",
        "SEARCH_TEMPORAL",
        "EXPAND_NEIGHBORS",
        "NO_ACTION",
    }
    assert provider.schema["additionalProperties"] is False
    assert receipt.hint.cue_provenance == "OBSERVATION"
    assert receipt.hint.rationale_code == "ENTITY_BRIDGE"
    assert receipt.hint.source_preference == "NO_CHANGE"

    with pytest.raises(ResidualRefindingError, match="ALREADY_USED"):
        service = ResidualHintShadowService(provider)
        service.generate(
            run_id="dg18-r3-repeat",
            case_id="repeat",
            observation=observation,
            state=reserved,
            plan=plan,
        )
        service.generate(
            run_id="dg18-r3-repeat",
            case_id="repeat",
            observation=observation,
            state=reserved,
            plan=plan,
        )


@pytest.mark.parametrize("budget_field", ["candidate_count", "context_tokens", "latency_ms"])
def test_r3_controller_reservation_requires_all_remaining_budgets(
    budget_field: str,
) -> None:
    plan, state, _requirements = _plan_and_state()
    remaining = state.remaining_budget.model_copy(update={budget_field: 0})
    exhausted = state.model_copy(update={"remaining_budget": remaining})
    transition = reserve_residual_controller_call(exhausted, plan)

    assert transition.outcome == "BUDGET_BLOCKED"
    assert transition.reason_code == "RESIDUAL_CONTROLLER_BUDGET_EXHAUSTED"
    assert transition.state == exhausted


@pytest.mark.parametrize(("calls", "retries"), [(2, 0), (1, 1)])
def test_r3_call_ceiling_or_retry_violation_is_typed(calls: int, retries: int) -> None:
    plan, state, requirements = _plan_and_state()
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[_candidate("The cobalt deployment rolled out quietly.")],
        state=state,
        plan=plan,
    )
    service = ResidualHintShadowService(
        _Provider(_proposal(state.missing_requirement_ids[0]), calls=calls, retries=retries)
    )
    reserved = _reserve(state, plan)

    with pytest.raises(ResidualRefindingError, match="CALL_CEILING"):
        service.generate(
            run_id="dg18-r3-test",
            case_id="call-ceiling",
            observation=observation,
            state=reserved,
            plan=plan,
        )


def test_r3_proposal_validation_failure_retains_sanitized_field_diagnostic() -> None:
    plan, state, requirements = _plan_and_state()
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[],
        state=state,
        plan=plan,
    )
    reserved = _reserve(state, plan)
    service = ResidualHintShadowService(
        _Provider(
            {
                "requirement_id": state.missing_requirement_ids[0],
                "action": "SEARCH_LEXICAL",
                "cues": [],
            }
        )
    )

    with pytest.raises(ResidualRefindingError) as raised:
        service.generate(
            run_id="dg18-r3-test",
            case_id="invalid-proposal",
            observation=observation,
            state=reserved,
            plan=plan,
        )

    assert raised.value.code == "RESIDUAL_CUE_PROPOSAL_SCHEMA_INVALID"
    assert raised.value.validation_field_path == "$"
    assert raised.value.validation_error_type == "value_error"
    assert "Which happened first" not in str(raised.value)


def test_r3_runtime_rejects_nonmissing_requirement_and_preserves_constraints() -> None:
    plan, state, _requirements = _plan_and_state()
    state = _reserve(state, plan)
    hint = ResidualSearchHint.model_validate(_hint("NOT_A_MISSING_REQUIREMENT"))
    validation = validate_residual_search_hint(hint=hint, state=state, plan=plan)

    assert validation.status == "REJECTED"
    assert validation.reason_code == "REQUIREMENT_NOT_MISSING"
    assert validation.inherited_authority_floor == "INFORMATIONAL"
    assert len(validation.inherited_scope_digest) == 64
    assert validation.canonical_mutation is False


def test_r3_runtime_rejects_temporal_scope_expansion_and_accepts_narrowing() -> None:
    plan, _state, requirements = _plan_and_state()
    inherited_start = REFERENCE - timedelta(days=10)
    inherited_end = REFERENCE
    plan = plan.model_copy(
        update={
            "global_constraints": plan.global_constraints.model_copy(
                update={
                    "source_observed_range": {
                        "start": inherited_start.isoformat(),
                        "end": inherited_end.isoformat(),
                    }
                }
            )
        }
    )
    state = initialize_acquisition_state(plan, requirements)
    deterministic = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    state = advance_acquisition_state(state, deterministic).state
    state = _reserve(state, plan)

    def temporal_hint(start: datetime, end: datetime) -> ResidualSearchHint:
        return ResidualSearchHint(
            requirement_id=state.missing_requirement_ids[0],
            action="SEARCH_TEMPORAL",
            temporal_cue=ResidualTemporalCue(
                axis="SOURCE_OBSERVED_TIME", start=start, end=end
            ),
            cue_provenance="QUERY",
            rationale_code="TEMPORAL_NARROWING",
        )

    expanded = validate_residual_search_hint(
        hint=temporal_hint(inherited_start - timedelta(seconds=1), inherited_end),
        state=state,
        plan=plan,
    )
    narrowed = validate_residual_search_hint(
        hint=temporal_hint(
            inherited_start + timedelta(days=1), inherited_end - timedelta(days=1)
        ),
        state=state,
        plan=plan,
    )

    assert expanded.status == "REJECTED"
    assert expanded.reason_code == "TEMPORAL_SCOPE_EXPANSION_REJECTED"
    assert narrowed.status == "ACCEPTED"


def test_r3_temporal_proposal_inherits_runtime_bound_and_not_provider_control() -> None:
    plan, state, requirements = _plan_and_state()
    inherited_start = REFERENCE - timedelta(days=10)
    inherited_end = REFERENCE
    plan = plan.model_copy(
        update={
            "global_constraints": plan.global_constraints.model_copy(
                update={
                    "source_observed_range": {
                        "start": inherited_start.isoformat(),
                        "end": inherited_end.isoformat(),
                    }
                }
            )
        }
    )
    state = initialize_acquisition_state(plan, requirements)
    deterministic = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in plan.probes],
    )
    state = advance_acquisition_state(state, deterministic).state
    observation = build_acquisition_observation(
        query="Which happened first, the cobalt launch or the amber review?",
        requirements=requirements,
        candidates=[],
        state=state,
        plan=plan,
    )
    hint = normalize_residual_cue_proposal(
        proposal=ResidualCueProposal(
            requirement_id=state.missing_requirement_ids[0],
            action="SEARCH_TEMPORAL",
            cues=["during the release window"],
        ),
        observation=observation,
        plan=plan,
    )

    assert hint.temporal_cue.axis == "SOURCE_OBSERVED_TIME"
    assert hint.temporal_cue.start == inherited_start
    assert hint.temporal_cue.end == inherited_end
    assert hint.temporal_cue.expression == "during the release window"
    assert hint.rationale_code == "TEMPORAL_NARROWING"


def test_r3_runtime_rejects_unplanned_structural_expansion_and_plan_swap() -> None:
    plan, state, requirements = _plan_and_state()
    state = _reserve(state, plan)
    hint = ResidualSearchHint(
        requirement_id=state.missing_requirement_ids[0],
        action="EXPAND_NEIGHBORS",
        cue_provenance="OBSERVATION",
        rationale_code="LOCAL_CONTEXT_REQUIRED",
    )

    unplanned = validate_residual_search_hint(hint=hint, state=state, plan=plan)
    swapped_plan = plan.model_copy(
        update={
            "probes": [
                probe.model_copy(update={"expansion_policy": "ADJACENT_TURNS"})
                for probe in plan.probes
            ]
        }
    )
    swapped = validate_residual_search_hint(
        hint=hint,
        state=state,
        plan=swapped_plan,
    )
    matching_state = initialize_acquisition_state(swapped_plan, requirements)
    matching_action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=matching_state.missing_requirement_ids,
        probe_ids=[probe.probe_id for probe in swapped_plan.probes],
    )
    matching_state = advance_acquisition_state(matching_state, matching_action).state
    matching_state = _reserve(matching_state, swapped_plan)
    planned = validate_residual_search_hint(
        hint=hint.model_copy(
            update={"requirement_id": matching_state.missing_requirement_ids[0]}
        ),
        state=matching_state,
        plan=swapped_plan,
    )

    assert unplanned.reason_code == "NEIGHBOR_EXPANSION_NOT_PLANNED"
    assert swapped.reason_code == "ACQUISITION_PLAN_IDENTITY_MISMATCH"
    assert planned.status == "ACCEPTED"


def test_r3_trace_represents_already_complete_with_zero_hidden_work() -> None:
    complete = ResidualDeterministicState(
        missing_requirement_ids=[],
        coverage={"TARGET_EVENT": True},
        operator_ready=True,
        sufficiency_status="COMPLETE",
    )
    trace = ResidualRefindingTrace(
        activation=ResidualActivation(
            eligible=False,
            activated=False,
            reason="ALREADY_COMPLETE",
        ),
        deterministic_before=complete,
        controller=ResidualControllerTrace(model_call_count=0),
        hint=ResidualHintTrace(validation_status="NOT_PROPOSED"),
        additional_acquisition=ResidualAdditionalAcquisition(attempted=False),
        deterministic_after=complete,
        terminal_reason="DETERMINISTIC_COMPLETE",
    )

    assert trace.controller.model_call_count == 0
    assert trace.additional_acquisition.attempted is False
    assert trace.product_result_changed is False
    serialized = trace.model_dump_json()
    assert "messages" not in serialized
    assert "question_excerpt" not in serialized
    assert "bounded_snippet" not in serialized
    assert "Evidence body" not in serialized


def test_r3_trace_rejects_work_claimed_by_an_inactive_path() -> None:
    partial = ResidualDeterministicState(
        missing_requirement_ids=["TARGET_EVENT"],
        coverage={"TARGET_EVENT": False},
        operator_ready=False,
        sufficiency_status="UNSATISFIED",
    )
    with pytest.raises(ValidationError, match="inactive residual trace"):
        ResidualRefindingTrace(
            activation=ResidualActivation(
                eligible=True,
                activated=False,
                reason="SHADOW_DISABLED",
            ),
            deterministic_before=partial,
            controller=ResidualControllerTrace(
                provider_identity="provider/model",
                prompt_schema="a" * 64,
                output_schema_valid=True,
                model_call_count=1,
            ),
            hint=ResidualHintTrace(
                action="NO_ACTION",
                requirement_id="TARGET_EVENT",
                validation_status="NO_ACTION",
            ),
            additional_acquisition=ResidualAdditionalAcquisition(attempted=False),
            deterministic_after=partial,
            terminal_reason="SHADOW_DISABLED",
        )


def test_r3_trace_cannot_encode_a_changed_product_result() -> None:
    partial = ResidualDeterministicState(
        missing_requirement_ids=["TARGET_EVENT"],
        coverage={"TARGET_EVENT": False},
        operator_ready=False,
        sufficiency_status="UNSATISFIED",
    )
    with pytest.raises(ValidationError):
        ResidualRefindingTrace.model_validate(
            {
                "activation": {
                    "eligible": False,
                    "activated": False,
                    "reason": "SHADOW_DISABLED",
                },
                "deterministic_before": partial.model_dump(mode="json"),
                "controller": {"model_call_count": 0},
                "hint": {"validation_status": "NOT_PROPOSED"},
                "additional_acquisition": {"attempted": False},
                "deterministic_after": partial.model_dump(mode="json"),
                "terminal_reason": "SHADOW_DISABLED",
                "product_result_changed": True,
            }
        )
