"""DG-25 query-local requirement-complete acquisition plan contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.acquisition_capability import (
    AcquisitionCapabilityName,
    FeasibleAcquisitionAction,
)
from milai.domain.requirement_state import (
    RequirementDispositionStatus,
    RequirementKind,
    RequirementState,
    canonical_sha256,
)

AcquisitionActionRole = Literal[
    "EVIDENCE_DISCOVERY",
    "PROOF_CLOSURE",
    "LOCAL_EXPANSION",
]


class RequirementCompleteRetrievalPolicyV01(BaseModel):
    """Candidate-only limits; construction can never enable the candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-complete-retrieval-policy-v0.1"] = (
        "requirement-complete-retrieval-policy-v0.1"
    )
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_enabled: Literal[False] = False
    max_extra_state_passes_per_query: Literal[1] = 1
    max_actions_per_plan: int = Field(default=3, ge=1, le=3)
    max_additional_repository_calls_per_query: int = Field(default=2, ge=1, le=3)
    max_target_requirements: int = Field(default=3, ge=1, le=3)
    max_candidate_pool_per_query: int = Field(default=64, ge=1, le=64)
    max_hydrated_candidates_per_query: int = Field(default=120, ge=1, le=120)
    max_reader_evidence_items: int = Field(default=8, ge=1, le=8)
    preserve_baseline_action_budget: Literal[True] = True
    allow_unverified_dense_cutoff: Literal[False] = False
    allow_case_id: Literal[False] = False
    allow_gold_inputs: Literal[False] = False
    allow_time_axis_substitution: Literal[False] = False
    require_proof_action_for_all_matches: Literal[True] = True
    require_role_reservation: Literal[True] = True
    use_rank_based_cross_channel_fusion: Literal[True] = True
    compare_raw_scores_across_channels: Literal[False] = False
    range_scan_max_items: int = Field(default=2_000, ge=1, le=2_000)
    local_anchor_radius: int = Field(default=2, ge=1, le=2)
    model_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        material = self.model_dump(mode="json", exclude={"policy_digest"})
        if self.policy_digest != canonical_sha256(material):
            raise ValueError("requirement-complete policy digest mismatch")
        return self


def default_requirement_complete_retrieval_policy() -> RequirementCompleteRetrievalPolicyV01:
    provisional = RequirementCompleteRetrievalPolicyV01.model_construct(policy_digest="0" * 64)
    material = provisional.model_dump(mode="json", exclude={"policy_digest"})
    return RequirementCompleteRetrievalPolicyV01(
        policy_digest=canonical_sha256(material),
        **material,
    )


class RequirementAcquisitionPlanLineageV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_epoch: int = Field(ge=0)
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    access_snapshot_identity: str = Field(pattern=r"^[0-9a-f]{64}$")


class TargetRequirementV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    kind: RequirementKind
    status: RequirementDispositionStatus
    missing_evidence_roles: list[str] = Field(default_factory=list, max_length=16)
    proof_obligations: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        for values in (self.missing_evidence_roles, self.proof_obligations):
            if values != sorted(set(values)):
                raise ValueError("target requirement roles and proofs must be sorted and unique")
        if self.status == "SATISFIED":
            raise ValueError("satisfied requirement cannot enter an acquisition plan")
        return self


class PlannedRequirementAcquisitionActionV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_requirement_id: str = Field(min_length=1, max_length=128)
    action_role: AcquisitionActionRole
    capability_id: str = Field(min_length=1, max_length=160)
    channel: AcquisitionCapabilityName
    candidate_cap: int = Field(ge=1, le=256)
    repository_calls: Literal[1] = 1
    bounded_cost: dict[str, int]
    reason_code: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if set(self.bounded_cost) != {
            "acquisition_passes",
            "candidate_count",
            "model_calls",
        }:
            raise ValueError("planned action bounded cost keys are not canonical")
        if any(isinstance(value, bool) or value < 0 for value in self.bounded_cost.values()):
            raise ValueError("planned action bounded costs must be non-negative integers")
        if self.bounded_cost["acquisition_passes"] != 1:
            raise ValueError("each planned action belongs to the one acquisition pass")
        if self.bounded_cost["candidate_count"] != self.candidate_cap:
            raise ValueError("planned candidate cap must equal the feasible bounded cost")
        if self.bounded_cost["model_calls"] != 0:
            raise ValueError("DG-25 planned actions cannot allocate model calls")
        if self.action_role == "PROOF_CLOSURE" and self.channel not in {
            "TEMPORAL_EVENT",
            "SOURCE_OBSERVED_RANGE_SCAN",
        }:
            raise ValueError("proof closure requires a bounded range capability")
        if self.action_role == "LOCAL_EXPANSION" and self.channel not in {
            "ADJACENT_TURNS",
            "SAME_EPISODE",
        }:
            raise ValueError("local expansion requires an expansion capability")
        if self.action_role == "EVIDENCE_DISCOVERY" and self.channel in {
            "ADJACENT_TURNS",
            "SAME_EPISODE",
        }:
            raise ValueError("expansion capabilities must be explicitly classified")
        return self


class RequirementAcquisitionAggregateBudgetV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    extra_state_passes: Literal[1] = 1
    max_repository_calls: int = Field(ge=1, le=3)
    planned_repository_calls: int = Field(ge=1, le=3)
    max_hydrated_candidates: int = Field(ge=1, le=120)
    planned_candidate_cap_sum: int = Field(ge=1, le=768)
    model_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0

    @model_validator(mode="after")
    def validate_budget(self) -> Self:
        if self.planned_repository_calls > self.max_repository_calls:
            raise ValueError("planned repository calls exceed the aggregate budget")
        if self.planned_candidate_cap_sum > self.max_hydrated_candidates:
            raise ValueError("planned candidate caps exceed the hydration budget")
        return self


class RequirementAcquisitionExecutionContractV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    one_full_recompute: Literal[True] = True
    product_official_executor_only: Literal[True] = True
    canonical_mutation: Literal[False] = False


class RequirementAcquisitionPlanV01(BaseModel):
    """One digest-bound batch compiled from one fresh RequirementState."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-acquisition-plan-v0.1"] = (
        "requirement-acquisition-plan-v0.1"
    )
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lineage: RequirementAcquisitionPlanLineageV01
    target_requirements: list[TargetRequirementV01] = Field(min_length=1, max_length=3)
    actions: list[PlannedRequirementAcquisitionActionV01] = Field(min_length=1, max_length=3)
    aggregate_budget: RequirementAcquisitionAggregateBudgetV01
    execution_contract: RequirementAcquisitionExecutionContractV01 = Field(
        default_factory=RequirementAcquisitionExecutionContractV01
    )

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        target_ids = [item.requirement_id for item in self.target_requirements]
        if target_ids != sorted(set(target_ids)):
            raise ValueError("plan target requirements must be sorted and unique")
        action_digests = [item.action_digest for item in self.actions]
        if len(action_digests) != len(set(action_digests)):
            raise ValueError("plan action digests must be unique")
        action_order = sorted(
            self.actions,
            key=lambda item: (
                item.target_requirement_id,
                _action_role_order(item.action_role),
                item.channel,
                item.action_digest,
            ),
        )
        if self.actions != action_order:
            raise ValueError("plan actions must be deterministically ordered")
        if not all(item.target_requirement_id in target_ids for item in self.actions):
            raise ValueError("every action must target a declared requirement")
        target_by_id = {item.requirement_id: item for item in self.target_requirements}
        for action in self.actions:
            target = target_by_id[action.target_requirement_id]
            if action.action_role == "PROOF_CLOSURE" and not target.proof_obligations:
                raise ValueError("proof action requires a declared proof obligation")
        for target in self.target_requirements:
            requires_range_proof = target.kind == "RANGE_COMPLETENESS" or (
                "ALL_MATCHES_IN_RANGE" in target.proof_obligations
            )
            if requires_range_proof and not any(
                action.target_requirement_id == target.requirement_id
                and action.action_role == "PROOF_CLOSURE"
                for action in self.actions
            ):
                raise ValueError("ALL_MATCHES_IN_RANGE requires a proof-closing action")
        if self.aggregate_budget.planned_repository_calls != sum(
            item.repository_calls for item in self.actions
        ):
            raise ValueError("aggregate repository call count does not match actions")
        if self.aggregate_budget.planned_candidate_cap_sum != sum(
            item.candidate_cap for item in self.actions
        ):
            raise ValueError("aggregate candidate cap does not match actions")
        material = self.model_dump(mode="json", exclude={"plan_digest"})
        if self.plan_digest != canonical_sha256(material):
            raise ValueError("requirement acquisition plan digest mismatch")
        return self


class RequirementAcquisitionPlanValidationV01(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-acquisition-plan-validation-v0.1"] = (
        "requirement-acquisition-plan-validation-v0.1"
    )
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: bool
    reason_codes: list[str] = Field(min_length=1)
    validated_action_digests: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.reason_codes != sorted(set(self.reason_codes)):
            raise ValueError("plan validation reasons must be sorted and unique")
        if self.validated_action_digests != sorted(set(self.validated_action_digests)):
            raise ValueError("validated action digests must be sorted and unique")
        if self.accepted != (self.reason_codes == ["PLAN_FEASIBLE"]):
            raise ValueError("plan acceptance and reason codes disagree")
        return self


def validate_requirement_acquisition_plan(
    plan: RequirementAcquisitionPlanV01,
    *,
    requirement_state: RequirementState,
    feasible_actions: Sequence[FeasibleAcquisitionAction],
    policy: RequirementCompleteRetrievalPolicyV01,
    current_snapshot_identity: str,
    current_access_snapshot_identity: str,
    baseline_candidate_caps: Mapping[str, int] | None = None,
) -> RequirementAcquisitionPlanValidationV01:
    """Validate freshness, exact feasible membership, proof, and aggregate cost."""

    reasons: set[str] = set()
    lineage = plan.lineage
    if (
        lineage.query_ir_digest != requirement_state.query_ir_digest
        or lineage.requirement_state_digest != requirement_state.state_digest
        or lineage.requirement_state_epoch != requirement_state.state_epoch
    ):
        reasons.add("STALE_REQUIREMENT_STATE")
    if lineage.acquisition_capability_digest != requirement_state.acquisition_capability_digest:
        reasons.add("ACQUISITION_CAPABILITY_DIGEST_MISMATCH")
    if lineage.selection_policy_digest != policy.policy_digest:
        reasons.add("SELECTION_POLICY_DIGEST_MISMATCH")
    if lineage.snapshot_identity != current_snapshot_identity:
        reasons.add("SNAPSHOT_IDENTITY_MISMATCH")
    if lineage.access_snapshot_identity != current_access_snapshot_identity:
        reasons.add("ACCESS_SNAPSHOT_IDENTITY_MISMATCH")

    state_by_id = {item.requirement_id: item for item in requirement_state.requirements}
    for target in plan.target_requirements:
        state_target = state_by_id.get(target.requirement_id)
        if state_target is None:
            reasons.add("REQUIREMENT_UNKNOWN")
        elif state_target.status == "SATISFIED":
            reasons.add("SATISFIED_REQUIREMENT_NOT_TARGETABLE")
        elif target.status != state_target.status or target.kind != state_target.kind:
            reasons.add("REQUIREMENT_DISPOSITION_MISMATCH")

    feasible_by_digest = {item.action_digest: item for item in feasible_actions}
    validated: list[str] = []
    for action in plan.actions:
        feasible = feasible_by_digest.get(action.action_digest)
        if feasible is None:
            reasons.add("UNREGISTERED_ACTION")
            continue
        exact = {
            "target_requirement_id": action.target_requirement_id,
            "capability_id": action.capability_id,
            "channel": action.channel,
            "candidate_cap": action.candidate_cap,
            "bounded_cost": action.bounded_cost,
        }
        expected = {
            "target_requirement_id": feasible.target_requirement_id,
            "capability_id": feasible.capability_id,
            "channel": feasible.channel,
            "candidate_cap": feasible.bounded_cost.get("candidate_count"),
            "bounded_cost": feasible.bounded_cost,
        }
        if exact != expected:
            reasons.add("ACTION_NOT_EXACT_FEASIBLE_MEMBER")
            continue
        if (
            feasible.requirement_state_digest != lineage.requirement_state_digest
            or feasible.requirement_state_epoch != lineage.requirement_state_epoch
        ):
            reasons.add("STALE_ACTION")
            continue
        if (
            feasible.capability_digest != lineage.acquisition_capability_digest
            or feasible.policy_digest != lineage.policy_digest
        ):
            reasons.add("ACTION_LINEAGE_MISMATCH")
            continue
        validated.append(action.action_digest)

    baseline_caps = dict(baseline_candidate_caps or {})
    plan_by_digest = {item.action_digest: item for item in plan.actions}
    for digest, cap in baseline_caps.items():
        baseline_action = plan_by_digest.get(digest)
        if baseline_action is None:
            reasons.add("BASELINE_ACTION_MISSING")
        elif baseline_action.candidate_cap != cap:
            reasons.add("BASELINE_ACTION_CAP_CHANGED")

    if len(plan.actions) > policy.max_actions_per_plan:
        reasons.add("ACTION_COUNT_BUDGET_EXCEEDED")
    if len(plan.target_requirements) > policy.max_target_requirements:
        reasons.add("TARGET_REQUIREMENT_BUDGET_EXCEEDED")
    if (
        plan.aggregate_budget.max_repository_calls
        > policy.max_additional_repository_calls_per_query
        or plan.aggregate_budget.planned_repository_calls
        > policy.max_additional_repository_calls_per_query
    ):
        reasons.add("REPOSITORY_CALL_BUDGET_EXCEEDED")
    if (
        plan.aggregate_budget.max_hydrated_candidates > policy.max_hydrated_candidates_per_query
        or plan.aggregate_budget.planned_candidate_cap_sum
        > policy.max_hydrated_candidates_per_query
    ):
        reasons.add("HYDRATION_BUDGET_EXCEEDED")

    reason_codes = sorted(reasons) if reasons else ["PLAN_FEASIBLE"]
    return RequirementAcquisitionPlanValidationV01(
        plan_digest=plan.plan_digest,
        accepted=not reasons,
        reason_codes=reason_codes,
        validated_action_digests=sorted(validated),
    )


def build_requirement_acquisition_plan(
    *,
    lineage: RequirementAcquisitionPlanLineageV01,
    target_requirements: Sequence[TargetRequirementV01],
    actions: Sequence[PlannedRequirementAcquisitionActionV01],
    aggregate_budget: RequirementAcquisitionAggregateBudgetV01,
) -> RequirementAcquisitionPlanV01:
    target_list = list(target_requirements)
    action_list = list(actions)
    execution_contract = RequirementAcquisitionExecutionContractV01()
    material = {
        "schema_version": "requirement-acquisition-plan-v0.1",
        "lineage": lineage.model_dump(mode="json"),
        "target_requirements": [item.model_dump(mode="json") for item in target_list],
        "actions": [item.model_dump(mode="json") for item in action_list],
        "aggregate_budget": aggregate_budget.model_dump(mode="json"),
        "execution_contract": execution_contract.model_dump(mode="json"),
    }
    return RequirementAcquisitionPlanV01(
        schema_version="requirement-acquisition-plan-v0.1",
        plan_digest=canonical_sha256(material),
        lineage=lineage,
        target_requirements=target_list,
        actions=action_list,
        aggregate_budget=aggregate_budget,
        execution_contract=execution_contract,
    )


def _action_role_order(value: AcquisitionActionRole) -> int:
    return {
        "EVIDENCE_DISCOVERY": 0,
        "PROOF_CLOSURE": 1,
        "LOCAL_EXPANSION": 2,
    }[value]


__all__ = [
    "AcquisitionActionRole",
    "PlannedRequirementAcquisitionActionV01",
    "RequirementAcquisitionAggregateBudgetV01",
    "RequirementAcquisitionExecutionContractV01",
    "RequirementAcquisitionPlanLineageV01",
    "RequirementAcquisitionPlanV01",
    "RequirementAcquisitionPlanValidationV01",
    "RequirementCompleteRetrievalPolicyV01",
    "TargetRequirementV01",
    "build_requirement_acquisition_plan",
    "default_requirement_complete_retrieval_policy",
    "validate_requirement_acquisition_plan",
]
