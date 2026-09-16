from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_state import (
    advance_acquisition_state,
    build_acquisition_action,
    initialize_acquisition_state,
)
from milai.application.query_planner import QueryPlanner
from milai.domain import AcquisitionState, RetrievalRequest, SufficiencyDecision


def _state():  # type: ignore[no-untyped-def]
    reference = datetime(2026, 8, 28, tzinfo=UTC)
    query = "How much did I pay per ceramic mug?"
    query_plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query=query,
            requested_scope={"project_ids": ["milai"]},
            as_of=reference,
            system_as_of=reference,
        )
    )
    assert query_plan.memory_query_ir is not None
    plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope={"project_ids": ["milai"]},
        authority_floor="INFORMATIONAL",
        candidate_limit=12,
        context_tokens=512,
    )
    return plan, initialize_acquisition_state(
        plan,
        query_plan.memory_query_ir.requirements,
        memory_query_ir=query_plan.memory_query_ir,
    )


def test_acquisition_state_rejects_independent_missing_or_satisfied_writes() -> None:
    _plan, state = _state()
    payload = state.model_dump(mode="json")
    payload["missing_requirement_ids"] = []
    payload["satisfied_requirement_ids"] = state.required_requirement_ids
    with pytest.raises(ValidationError, match="derived from RequirementState"):
        AcquisitionState.model_validate(payload)


def test_transition_does_not_trust_sufficiency_compatibility_fields_as_binding() -> None:
    plan, state = _state()
    action = build_acquisition_action(
        action_kind="DETERMINISTIC_PASS",
        pass_index=0,
        requirement_ids=state.missing_requirement_ids,
        probe_ids=[item.probe_id for item in plan.probes],
    )
    transition = advance_acquisition_state(
        state,
        action,
        sufficiency_decision=SufficiencyDecision(
            status="COMPLETE",
            covered_slots=state.required_requirement_ids,
            stop_reason="REQUIREMENT_SATISFIED",
        ),
    )
    assert transition.outcome == "APPLIED"
    assert transition.state.satisfied_requirement_ids == []
    assert transition.state.missing_requirement_ids == state.required_requirement_ids
    assert transition.state.requirement_state.state_epoch == state.requirement_state.state_epoch
