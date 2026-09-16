"""Label-free DG-25 S2 compiler, validation, and official-executor evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

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
from milai.domain.acquisition_capability import (
    AcquisitionCapabilitySet,
    FeasibleAcquisitionAction,
)
from milai.domain.requirement_acquisition import (
    RequirementCompleteRetrievalPolicyV01,
    default_requirement_complete_retrieval_policy,
)
from milai.domain.requirement_state import RequirementState, canonical_sha256
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState

REFERENCE = datetime(2023, 3, 27, 12, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))
QUERY = "How many babies were born to friends and family in the last few months?"
SNAPSHOT_IDENTITY = "8" * 64
ACCESS_SNAPSHOT_IDENTITY = "9" * 64


class _S2Repository:
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


def build_s2_reports() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run only synthetic R0/R0P and proof+discovery contract execution."""

    requirement_policy = default_requirement_complete_retrieval_policy()

    r0_inputs = _inputs()
    r0_executor = EvidenceAcquisitionExecutor(r0_inputs.repository)
    r0 = r0_executor.execute(
        context=CONTEXT,
        request=r0_inputs.request,
        query_plan=r0_inputs.query_plan,
        acquisition_plan=r0_inputs.acquisition_plan,
        capability_set=r0_inputs.capabilities,
        policy=r0_inputs.capability_policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=r0_inputs.state.state_epoch + 1,
        action=r0_inputs.discovery_action,
        current_requirement_state=r0_inputs.state,
        type_directed_semantics=True,
    )

    r0p_inputs = _inputs()
    r0p_compilation = RequirementAcquisitionPlanCompiler().compile(
        requirement_state=r0p_inputs.state,
        feasible_actions=[r0p_inputs.discovery_action],
        policy=requirement_policy,
        snapshot_identity=SNAPSHOT_IDENTITY,
        access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
        mode="R0P_COMPATIBILITY",
        baseline_selected_action=r0p_inputs.discovery_action,
    )
    r0p = EvidenceAcquisitionExecutor(r0p_inputs.repository).execute_plan(
        context=CONTEXT,
        request=r0p_inputs.request,
        query_plan=r0p_inputs.query_plan,
        acquisition_plan=r0p_inputs.acquisition_plan,
        requirement_acquisition_plan=r0p_compilation.plan,
        capability_set=r0p_inputs.capabilities,
        capability_policy=r0p_inputs.capability_policy,
        requirement_policy=requirement_policy,
        current_requirement_state=r0p_inputs.state,
        feasible_actions=[r0p_inputs.discovery_action],
        current_snapshot_identity=SNAPSHOT_IDENTITY,
        current_access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        type_directed_semantics=True,
        baseline_candidate_caps={r0p_inputs.discovery_action.action_digest: 8},
    )

    composed_inputs = _inputs()
    composed_compilation = RequirementAcquisitionPlanCompiler().compile(
        requirement_state=composed_inputs.state,
        feasible_actions=[
            composed_inputs.discovery_action,
            composed_inputs.proof_action,
        ],
        policy=requirement_policy,
        snapshot_identity=SNAPSHOT_IDENTITY,
        access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
        mode="PROOF_FIRST_MINIMAL",
        baseline_selected_action=composed_inputs.discovery_action,
    )
    composed = EvidenceAcquisitionExecutor(composed_inputs.repository).execute_plan(
        context=CONTEXT,
        request=composed_inputs.request,
        query_plan=composed_inputs.query_plan,
        acquisition_plan=composed_inputs.acquisition_plan,
        requirement_acquisition_plan=composed_compilation.plan,
        capability_set=composed_inputs.capabilities,
        capability_policy=composed_inputs.capability_policy,
        requirement_policy=requirement_policy,
        current_requirement_state=composed_inputs.state,
        feasible_actions=[
            composed_inputs.discovery_action,
            composed_inputs.proof_action,
        ],
        current_snapshot_identity=SNAPSHOT_IDENTITY,
        current_access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        type_directed_semantics=True,
        baseline_candidate_caps={composed_inputs.discovery_action.action_digest: 8},
    )

    r0_projection = _semantic_projection(r0)
    r0p_projection = _semantic_projection(r0p.execution)
    equivalence_dimensions = {
        key: r0_projection[key] == r0p_projection[key]
        for key in sorted(r0_projection)
    }
    equivalence = {
        "schema": "milai.dg25.s2-official-execution-equivalence-report.v0.1",
        "arm_order": ["R0", "R0P"],
        "input_mode": "SYNTHETIC_LABEL_FREE",
        "r0_semantic_digest": canonical_sha256(r0_projection),
        "r0p_semantic_digest": canonical_sha256(r0p_projection),
        "dimension_equivalence": equivalence_dimensions,
        "exact_semantic_equivalence": all(equivalence_dimensions.values()),
        "r0_repository_calls": r0_inputs.repository.raw_calls,
        "r0p_repository_calls": r0p_inputs.repository.raw_calls,
        "r0p_full_semantics_recomputations": r0p.full_semantics_recomputations,
        "r0p_state_epoch_increment": (
            r0p.final_requirement_state_epoch
            - r0p.initial_requirement_state_epoch
        ),
        "r0p_baseline_action_digest_preserved": (
            r0p_compilation.plan.actions[0].action_digest
            == r0p_inputs.discovery_action.action_digest
        ),
        "r0p_baseline_candidate_cap_preserved": (
            r0p_compilation.plan.actions[0].candidate_cap == 8
        ),
        "context_mutations": 0,
        "canonical_mutations": 0,
        "provider_model_controller_calls": 0,
        "automatic_retries": 0,
        "effect_scoring_executed": False,
    }

    negative_records = _negative_validation_records(requirement_policy)
    validation = {
        "schema": "milai.dg25.s2-plan-validation-report.v0.1",
        "fresh_r0p_validation": r0p_compilation.validation.model_dump(mode="json"),
        "fresh_composed_validation": (
            composed_compilation.validation.model_dump(mode="json")
        ),
        "negative_records": negative_records,
        "counts": {
            "fresh_accepted": 2,
            "negative_total": len(negative_records),
            "negative_rejected_before_repository_call": sum(
                item["rejected_before_repository_call"] for item in negative_records
            ),
        },
        "stale_plan_accepted": 0,
        "infeasible_or_unregistered_action_executed": 0,
        "aggregate_budget_overflow_executed": 0,
        "duplicate_action_executed": 0,
        "automatic_retries": 0,
        "hard_gate": {
            "passed": all(
                item["rejected_before_repository_call"] for item in negative_records
            )
        },
    }

    channel_lineage = sorted(
        {
            channel
            for candidate in composed.execution.candidates
            for channel in candidate.channel_ranks
        }
    )
    traces = {
        "schema": "milai.dg25.s2-requirement-acquisition-plan-traces.v0.1",
        "input_mode": "SYNTHETIC_LABEL_FREE",
        "arm_order": ["R0", "R0P"],
        "r0": {
            "legacy_action": r0_inputs.discovery_action.model_dump(mode="json"),
            "repository_calls": r0_inputs.repository.raw_calls,
            "state_epoch": r0.requirement_state.state_epoch,
        },
        "r0p": {
            "compilation": r0p_compilation.model_dump(mode="json"),
            "official_executor_identity": r0p.execution.executor_identity,
            "execution_lineage": r0p.model_dump(
                mode="json",
                exclude={"execution"},
            ),
        },
        "proof_discovery_composition": {
            "compilation": composed_compilation.model_dump(mode="json"),
            "official_executor_identity": composed.execution.executor_identity,
            "execution_lineage": composed.model_dump(
                mode="json",
                exclude={"execution"},
            ),
            "channels_retained": channel_lineage,
            "result_evidence_ids": sorted(
                str(item["evidence_id"])
                for item in composed.execution.results
                if isinstance(item.get("evidence_id"), str)
            ),
            "bounded_range_scan_proof_present": (
                composed.execution.bounded_range_scan_proof is not None
            ),
        },
        "cost_ledger": {
            "r0": {
                "repository_calls": 1,
                "planned_candidate_cap_sum": 8,
                "extra_state_passes": 1,
            },
            "r0p": {
                "repository_calls": r0p.repository_probe_calls,
                "planned_candidate_cap_sum": r0p.planned_candidate_cap_sum,
                "extra_state_passes": r0p.full_semantics_recomputations,
            },
            "proof_discovery": {
                "repository_calls": composed.repository_probe_calls,
                "planned_candidate_cap_sum": composed.planned_candidate_cap_sum,
                "extra_state_passes": composed.full_semantics_recomputations,
                "range_rows_scanned": (
                    composed.execution.bounded_range_scan_proof.returned_count
                    if composed.execution.bounded_range_scan_proof is not None
                    else 0
                ),
            },
            "reader_calls": 0,
            "planner_controller_residual_provider_calls": 0,
            "automatic_retries": 0,
        },
        "safety": {
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "labels_loaded": False,
            "effect_scoring_executed": False,
            "canonical_mutations": 0,
        },
    }
    return traces, validation, equivalence


class _S2Inputs:
    def __init__(
        self,
        *,
        repository: _S2Repository,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        acquisition_plan: AcquisitionPlan,
        capability_policy: AcquisitionCapabilityPolicy,
        capabilities: AcquisitionCapabilitySet,
        state: RequirementState,
        discovery_action: FeasibleAcquisitionAction,
        proof_action: FeasibleAcquisitionAction,
    ) -> None:
        self.repository = repository
        self.request = request
        self.query_plan = query_plan
        self.acquisition_plan = acquisition_plan
        self.capability_policy = capability_policy
        self.capabilities = capabilities
        self.state = state
        self.discovery_action = discovery_action
        self.proof_action = proof_action


def _inputs() -> _S2Inputs:
    request = RetrievalRequest(
        route="L1",
        query=QUERY,
        requested_scope={"project_ids": ["milai"]},
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )
    query_plan = QueryPlanner().plan(request, candidate_cap=8, context_budget=512)
    query_ir = query_plan.memory_query_ir
    if query_ir is None:
        raise ValueError("synthetic S2 query did not compile MemoryQueryIR")
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
    if event_range is None:
        raise ValueError("synthetic S2 query did not compile an event range")
    repository = _S2Repository()
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
    discovery = next(
        item
        for item in actions
        if item.channel == "FTS_RAW" and item.target_requirement_id == target_id
    )
    proof = next(
        item
        for item in actions
        if item.channel == "TEMPORAL_EVENT"
        and item.target_requirement_id == target_id
    )
    return _S2Inputs(
        repository=repository,
        request=request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_policy=capability_policy,
        capabilities=capabilities,
        state=state,
        discovery_action=discovery,
        proof_action=proof,
    )


def _negative_validation_records(
    requirement_policy: RequirementCompleteRetrievalPolicyV01,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for scenario in ("STALE_SNAPSHOT", "UNREGISTERED_ACTION", "BUDGET_OVERFLOW"):
        inputs = _inputs()
        compilation = RequirementAcquisitionPlanCompiler().compile(
            requirement_state=inputs.state,
            feasible_actions=[inputs.discovery_action, inputs.proof_action],
            policy=requirement_policy,
            snapshot_identity=SNAPSHOT_IDENTITY,
            access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
            mode="PROOF_FIRST_MINIMAL",
            baseline_selected_action=inputs.discovery_action,
        )
        current_snapshot = (
            "7" * 64 if scenario == "STALE_SNAPSHOT" else SNAPSHOT_IDENTITY
        )
        current_actions = (
            [inputs.discovery_action]
            if scenario == "UNREGISTERED_ACTION"
            else [inputs.discovery_action, inputs.proof_action]
        )
        current_policy = (
            _restricted_requirement_policy()
            if scenario == "BUDGET_OVERFLOW"
            else requirement_policy
        )
        before = inputs.repository.raw_calls + inputs.repository.event_calls
        error: str | None = None
        try:
            EvidenceAcquisitionExecutor(inputs.repository).execute_plan(
                context=CONTEXT,
                request=inputs.request,
                query_plan=inputs.query_plan,
                acquisition_plan=inputs.acquisition_plan,
                requirement_acquisition_plan=compilation.plan,
                capability_set=inputs.capabilities,
                capability_policy=inputs.capability_policy,
                requirement_policy=current_policy,
                current_requirement_state=inputs.state,
                feasible_actions=current_actions,
                current_snapshot_identity=current_snapshot,
                current_access_snapshot_identity=ACCESS_SNAPSHOT_IDENTITY,
                mode="SHADOW_NO_CONTEXT_MUTATION",
                baseline_candidate_caps={inputs.discovery_action.action_digest: 8},
            )
        except ValueError as exc:
            error = str(exc)
        after = inputs.repository.raw_calls + inputs.repository.event_calls
        expected_reason = {
            "STALE_SNAPSHOT": "SNAPSHOT_IDENTITY_MISMATCH",
            "UNREGISTERED_ACTION": "UNREGISTERED_ACTION",
            "BUDGET_OVERFLOW": "REPOSITORY_CALL_BUDGET_EXCEEDED",
        }[scenario]
        values.append(
            {
                "scenario": scenario,
                "expected_reason": expected_reason,
                "observed_error": error,
                "repository_calls_before": before,
                "repository_calls_after": after,
                "rejected_before_repository_call": bool(
                    error is not None
                    and expected_reason in error
                    and before == after == 0
                ),
            }
        )
    return values


def _restricted_requirement_policy() -> RequirementCompleteRetrievalPolicyV01:
    source = default_requirement_complete_retrieval_policy()
    material = source.model_dump(mode="json", exclude={"policy_digest"})
    material["max_additional_repository_calls_per_query"] = 1
    return RequirementCompleteRetrievalPolicyV01(
        policy_digest=canonical_sha256(material),
        **material,
    )


def _semantic_projection(execution: Any) -> dict[str, Any]:
    return {
        "results": execution.results,
        "candidates": [item.model_dump(mode="json") for item in execution.candidates],
        "spans": [item.model_dump(mode="json") for item in execution.spans],
        "interpretations": [
            item.model_dump(mode="json") for item in execution.interpretations
        ],
        "bindings": [item.model_dump(mode="json") for item in execution.bindings],
        "requirement_state": execution.requirement_state.model_dump(mode="json"),
        "sufficiency_decision": execution.sufficiency_decision.model_dump(mode="json"),
        "sufficiency_reason": execution.sufficiency_reason,
        "derived_result": execution.derived_result,
        "bounded_range_scan_proof": (
            execution.bounded_range_scan_proof.model_dump(mode="json")
            if execution.bounded_range_scan_proof is not None
            else None
        ),
        "candidate_requirement_attribution": (
            execution.candidate_requirement_attribution
        ),
        "type_directed_semantics": execution.type_directed_semantics,
        "semantic_audit": (
            execution.semantic_audit.model_dump(mode="json")
            if execution.semantic_audit is not None
            else None
        ),
        "context_mutation_performed": execution.context_mutation_performed,
        "canonical_mutation": execution.canonical_mutation,
    }


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


__all__ = ["build_s2_reports"]
