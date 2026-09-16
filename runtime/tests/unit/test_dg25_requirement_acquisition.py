from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_acquisition import (
    RequirementAcquisitionPlanCompiler,
)
from milai.application.requirement_state import resolve_initial_requirement_state
from milai.domain.acquisition import AcquisitionPlan
from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.requirement_acquisition import (
    RequirementCompleteRetrievalPolicyV01,
    default_requirement_complete_retrieval_policy,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))
QUERY = "How many babies were born to friends and family in the last few months?"
SNAPSHOT = "8" * 64
ACCESS_SNAPSHOT = "9" * 64


class _Repository:
    def __init__(self) -> None:
        self.raw_calls = 0
        self.event_calls = 0

    def search_evidence(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        self.raw_calls += 1
        return [
            _evidence(
                "raw-discovery",
                "My cousin said the family was preparing for a new baby.",
                observed_at="2023-02-01T09:00:00+00:00",
            )
        ]

    def search_evidence_event_range(
        self,
        _context: SessionContext,
        _requested_scope: dict[str, object],
        event_range_start: datetime,
        event_range_end: datetime,
        _as_of: datetime,
        max_items: int,
    ) -> dict[str, object]:
        self.event_calls += 1
        return {
            "status": "COMPLETE",
            "scan_axis": "SOURCE_OBSERVED_TIME",
            "source_snapshot_axis": "SOURCE_OBSERVED_TIME",
            "partition_kind": "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF",
            "source_snapshot_end": (REFERENCE + timedelta(microseconds=1)).isoformat(),
            "event_range_start": event_range_start.isoformat(),
            "event_range_end": event_range_end.isoformat(),
            "event_range_boundary": "CLOSED_OPEN",
            "event_normalization_owner": "DETERMINISTIC_RUNTIME",
            "event_normalization_version": "query-time-event-v1",
            "source_partition_closed": True,
            "projection_watermark_covered": True,
            "projection_watermark": 91,
            "target_watermark": 91,
            "source_count": 1,
            "projected_count": 1,
            "returned_count": 1,
            "max_items": max_items,
            "dead_letter_gap": False,
            "unreadable_evidence_count": 0,
            "items": [
                _evidence(
                    "event-proof",
                    "My friend Maya welcomed a baby on January 5th.",
                    observed_at=REFERENCE.isoformat(),
                )
            ],
        }

    def scan_evidence_range(self) -> None:
        pass

    def exact_candidates(self) -> None:
        pass


def _evidence(
    evidence_id: str,
    content: str,
    *,
    observed_at: str,
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "canonical_mutation": False,
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{evidence_id}/turn/0",
        "subject_id": evidence_id,
        "observed_at": observed_at,
        "captured_at": observed_at,
        "content": content,
        "content_hash": canonical_sha256(content),
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
        "relevance_score": 1.0,
    }


def _inputs() -> tuple[
    _Repository,
    RetrievalRequest,
    Any,
    AcquisitionPlan,
    AcquisitionCapabilityPolicy,
    Any,
    Any,
    FeasibleAcquisitionAction,
    FeasibleAcquisitionAction,
]:
    request = RetrievalRequest(
        route="L1",
        query=QUERY,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=512)
    query_ir = query_plan.memory_query_ir
    assert query_ir is not None
    target_id = query_ir.requirements[0].slot_id
    full_plan = compile_acquisition_plan(
        query_plan,
        query=QUERY,
        principal_scope=request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=8,
        context_tokens=512,
    )
    target_probe = next(
        item
        for item in full_plan.probes
        if item.channel == "FTS_RAW" and item.requirement_slot == target_id
    )
    acquisition_plan = full_plan.model_copy(
        update={
            "probes": [target_probe],
            "fusion": full_plan.fusion.model_copy(
                update={
                    "per_slot_quota": {
                        target_id: full_plan.fusion.per_slot_quota[target_id]
                    }
                }
            ),
        }
    )
    event_range = acquisition_plan.global_constraints.event_occurrence_range
    assert event_range is not None
    repository = _Repository()
    capability_policy = AcquisitionCapabilityPolicy(max_candidates=64)
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(query_time_event_enabled=True),
        projection_state=ProjectionState(91, 91, 91, False, False, 91, False),
        repository=repository,
        policy=capability_policy,
        generated_at=REFERENCE,
        event_occurrence_range=event_range,
    )
    state = resolve_initial_requirement_state(
        acquisition_plan,
        query_ir.requirements,
        acquisition_capability_digest=capabilities.capability_digest,
        memory_query_ir=query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        capabilities,
        capability_policy,
        event_occurrence_range=event_range,
        remaining_candidates=64,
        acquisition_plan=acquisition_plan,
        candidate_caps_by_channel={"FTS_RAW": 8, "TEMPORAL_EVENT": 8},
    )
    raw_action = next(
        item
        for item in actions
        if item.channel == "FTS_RAW" and item.target_requirement_id == target_id
    )
    proof_action = next(
        item
        for item in actions
        if item.channel == "TEMPORAL_EVENT"
        and item.target_requirement_id == target_id
    )
    return (
        repository,
        request,
        query_plan,
        acquisition_plan,
        capability_policy,
        capabilities,
        state,
        raw_action,
        proof_action,
    )


def _restricted_requirement_policy() -> RequirementCompleteRetrievalPolicyV01:
    source = default_requirement_complete_retrieval_policy()
    material = source.model_dump(mode="json", exclude={"policy_digest"})
    material["max_additional_repository_calls_per_query"] = 1
    return RequirementCompleteRetrievalPolicyV01(
        policy_digest=canonical_sha256(material),
        **material,
    )


def _semantic_projection(value: Any) -> dict[str, object]:
    return {
        "results": value.results,
        "candidates": value.candidates,
        "spans": value.spans,
        "interpretations": value.interpretations,
        "bindings": value.bindings,
        "requirement_state": value.requirement_state,
        "sufficiency_decision": value.sufficiency_decision,
        "sufficiency_reason": value.sufficiency_reason,
        "derived_result": value.derived_result,
        "bounded_range_scan_proof": value.bounded_range_scan_proof,
        "candidate_requirement_attribution": value.candidate_requirement_attribution,
    }


def test_r0p_one_action_plan_is_semantically_identical_to_r0() -> None:
    (
        repository,
        request,
        query_plan,
        acquisition_plan,
        capability_policy,
        capabilities,
        state,
        raw_action,
        _proof_action,
    ) = _inputs()
    requirement_policy = default_requirement_complete_retrieval_policy()
    compilation = RequirementAcquisitionPlanCompiler().compile(
        requirement_state=state,
        feasible_actions=[raw_action],
        policy=requirement_policy,
        snapshot_identity=SNAPSHOT,
        access_snapshot_identity=ACCESS_SNAPSHOT,
        mode="R0P_COMPATIBILITY",
        baseline_selected_action=raw_action,
    )
    executor = EvidenceAcquisitionExecutor(repository)
    legacy = executor.execute(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        policy=capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=state.state_epoch + 1,
        action=raw_action,
        current_requirement_state=state,
        type_directed_semantics=True,
    )
    wrapped = executor.execute_plan(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        requirement_acquisition_plan=compilation.plan,
        capability_set=capabilities,
        capability_policy=capability_policy,
        requirement_policy=requirement_policy,
        current_requirement_state=state,
        feasible_actions=[raw_action],
        current_snapshot_identity=SNAPSHOT,
        current_access_snapshot_identity=ACCESS_SNAPSHOT,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        type_directed_semantics=True,
        baseline_candidate_caps={raw_action.action_digest: 8},
    )

    assert _semantic_projection(wrapped.execution) == _semantic_projection(legacy)
    assert wrapped.repository_probe_calls == 1
    assert wrapped.full_semantics_recomputations == 1
    assert wrapped.initial_requirement_state_epoch == state.state_epoch
    assert wrapped.final_requirement_state_epoch == state.state_epoch + 1
    assert compilation.repository_calls == compilation.provider_calls == 0
    assert compilation.label_inputs_consumed == 0
    assert repository.raw_calls == 2


def test_proof_and_discovery_actions_compose_before_one_recompute() -> None:
    (
        repository,
        request,
        query_plan,
        acquisition_plan,
        capability_policy,
        capabilities,
        state,
        raw_action,
        proof_action,
    ) = _inputs()
    requirement_policy = default_requirement_complete_retrieval_policy()
    compilation = RequirementAcquisitionPlanCompiler().compile(
        requirement_state=state,
        feasible_actions=[raw_action, proof_action],
        policy=requirement_policy,
        snapshot_identity=SNAPSHOT,
        access_snapshot_identity=ACCESS_SNAPSHOT,
        mode="PROOF_FIRST_MINIMAL",
        baseline_selected_action=raw_action,
    )

    result = EvidenceAcquisitionExecutor(repository).execute_plan(
        context=CONTEXT,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        requirement_acquisition_plan=compilation.plan,
        capability_set=capabilities,
        capability_policy=capability_policy,
        requirement_policy=requirement_policy,
        current_requirement_state=state,
        feasible_actions=[raw_action, proof_action],
        current_snapshot_identity=SNAPSHOT,
        current_access_snapshot_identity=ACCESS_SNAPSHOT,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        type_directed_semantics=True,
        baseline_candidate_caps={raw_action.action_digest: 8},
    )

    assert [item.action_role for item in compilation.plan.actions] == [
        "EVIDENCE_DISCOVERY",
        "PROOF_CLOSURE",
    ]
    assert result.repository_probe_calls == 2
    assert result.planned_candidate_cap_sum == 16
    assert result.full_semantics_recomputations == 1
    assert repository.raw_calls == repository.event_calls == 1
    assert {item["evidence_id"] for item in result.execution.results} == {
        "event-proof",
        "raw-discovery",
    }
    assert result.execution.bounded_range_scan_proof is not None
    assert result.execution.bounded_range_scan_proof.scan_closure.scan_axis == (
        "EVENT_OCCURRENCE_TIME"
    )
    assert result.execution.requirement_state.state_epoch == state.state_epoch + 1
    assert result.execution.canonical_mutation is False


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("stale", "SNAPSHOT_IDENTITY_MISMATCH"),
        ("unregistered", "UNREGISTERED_ACTION"),
        ("budget", "REPOSITORY_CALL_BUDGET_EXCEEDED"),
    ],
)
def test_invalid_whole_plan_fails_before_any_repository_call(
    failure: str,
    reason: str,
) -> None:
    (
        repository,
        request,
        query_plan,
        acquisition_plan,
        capability_policy,
        capabilities,
        state,
        raw_action,
        proof_action,
    ) = _inputs()
    requirement_policy = default_requirement_complete_retrieval_policy()
    compilation = RequirementAcquisitionPlanCompiler().compile(
        requirement_state=state,
        feasible_actions=[raw_action, proof_action],
        policy=requirement_policy,
        snapshot_identity=SNAPSHOT,
        access_snapshot_identity=ACCESS_SNAPSHOT,
        mode="PROOF_FIRST_MINIMAL",
        baseline_selected_action=raw_action,
    )
    current_snapshot = "7" * 64 if failure == "stale" else SNAPSHOT
    current_actions = [raw_action] if failure == "unregistered" else [raw_action, proof_action]
    current_policy = (
        _restricted_requirement_policy() if failure == "budget" else requirement_policy
    )

    with pytest.raises(ValueError, match=reason):
        EvidenceAcquisitionExecutor(repository).execute_plan(
            context=CONTEXT,
            request=request,
            query_plan=query_plan,
            acquisition_plan=acquisition_plan,
            requirement_acquisition_plan=compilation.plan,
            capability_set=capabilities,
            capability_policy=capability_policy,
            requirement_policy=current_policy,
            current_requirement_state=state,
            feasible_actions=current_actions,
            current_snapshot_identity=current_snapshot,
            current_access_snapshot_identity=ACCESS_SNAPSHOT,
            mode="SHADOW_NO_CONTEXT_MUTATION",
            baseline_candidate_caps={raw_action.action_digest: 8},
        )

    assert repository.raw_calls == repository.event_calls == 0


def test_compiler_source_has_no_eval_or_label_aware_runtime_inputs() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src/milai/application/requirement_acquisition.py"
    ).read_text(encoding="utf-8")

    assert "from evals" not in source
    assert "import evals" not in source
    assert "case_id" not in source
    assert "gold_" not in source
    assert "ReaderAnswer" not in source
    assert "Provider" not in "\n".join(
        line for line in source.splitlines() if line.startswith(("from ", "import "))
    )
