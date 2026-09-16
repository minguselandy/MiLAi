"""Compile one query-local, requirement-complete acquisition plan.

The compiler is deliberately label-free. It consumes only fresh Runtime
state, exact feasible actions, immutable snapshot identities, and bounded
policies. It never calls a repository or Provider and never mutates Memory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from milai.domain.acquisition_capability import (
    AcquisitionCapabilityName,
    FeasibleAcquisitionAction,
)
from milai.domain.requirement_acquisition import (
    AcquisitionActionRole,
    PlannedRequirementAcquisitionActionV01,
    RequirementAcquisitionAggregateBudgetV01,
    RequirementAcquisitionPlanLineageV01,
    RequirementAcquisitionPlanV01,
    RequirementAcquisitionPlanValidationV01,
    RequirementCompleteRetrievalPolicyV01,
    TargetRequirementV01,
    build_requirement_acquisition_plan,
    validate_requirement_acquisition_plan,
)
from milai.domain.requirement_state import RequirementDisposition, RequirementState

RequirementAcquisitionCompilationMode = Literal[
    "R0P_COMPATIBILITY",
    "PROOF_FIRST_MINIMAL",
]

_DISCOVERY_CHANNEL_ORDER: tuple[AcquisitionCapabilityName, ...] = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "TEMPORAL_EVENT",
    "SOURCE_OBSERVED_RANGE_SCAN",
)
_PROOF_CHANNEL_ORDER: tuple[AcquisitionCapabilityName, ...] = (
    "TEMPORAL_EVENT",
    "SOURCE_OBSERVED_RANGE_SCAN",
)
_LOCAL_CHANNELS = frozenset({"ADJACENT_TURNS", "SAME_EPISODE"})
_PROOF_CHANNELS = frozenset(_PROOF_CHANNEL_ORDER)

# Narrower pre-treatment ceiling approved by the DG-25 review gate. The
# versioned domain policy retains its historic <=3 reader shape.
DG25_REVIEWED_MAX_ACTIONS = 2


class RequirementAcquisitionCompilationV01(BaseModel):
    """Auditable output of the deterministic compiler and validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-acquisition-compilation-v0.1"] = (
        "requirement-acquisition-compilation-v0.1"
    )
    mode: RequirementAcquisitionCompilationMode
    plan: RequirementAcquisitionPlanV01
    validation: RequirementAcquisitionPlanValidationV01
    baseline_action_digest: str | None = None
    selected_action_digests: list[str]
    residual_action_digests: list[str]
    repository_calls: Literal[0] = 0
    provider_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    label_inputs_consumed: Literal[0] = 0
    canonical_mutation: Literal[False] = False


class RequirementAcquisitionPlanCompiler:
    """Select at most two exact feasible actions and bind them to one state."""

    def compile(
        self,
        *,
        requirement_state: RequirementState,
        feasible_actions: Sequence[FeasibleAcquisitionAction],
        policy: RequirementCompleteRetrievalPolicyV01,
        snapshot_identity: str,
        access_snapshot_identity: str,
        mode: RequirementAcquisitionCompilationMode,
        baseline_selected_action: FeasibleAcquisitionAction | None = None,
        missing_evidence_roles: Mapping[str, Sequence[str]] | None = None,
        proof_obligations: Mapping[str, Sequence[str]] | None = None,
    ) -> RequirementAcquisitionCompilationV01:
        available = _exact_action_index(feasible_actions)
        baseline = _registered_baseline(baseline_selected_action, available)
        selected = _select_actions(
            requirement_state=requirement_state,
            feasible_actions=list(available.values()),
            mode=mode,
            baseline=baseline,
        )
        if not selected:
            raise ValueError("NO_FEASIBLE_REQUIREMENT_ACQUISITION_ACTION")
        max_actions = min(policy.max_actions_per_plan, DG25_REVIEWED_MAX_ACTIONS)
        if len(selected) > max_actions:
            raise ValueError("DG25_REVIEWED_ACTION_BUDGET_EXCEEDED")

        action_policy_digests = {item.policy_digest for item in selected}
        if len(action_policy_digests) != 1:
            raise ValueError("MIXED_ACTION_POLICY_DIGESTS")
        if {item.capability_digest for item in selected} != {
            requirement_state.acquisition_capability_digest
        }:
            raise ValueError("ACTION_CAPABILITY_STATE_MISMATCH")

        selected_target_ids = sorted({item.target_requirement_id for item in selected})
        state_by_id = {
            item.requirement_id: item for item in requirement_state.requirements
        }
        targets = [
            _target_contract(
                state_by_id[target_id],
                selected,
                missing_evidence_roles=missing_evidence_roles,
                proof_obligations=proof_obligations,
            )
            for target_id in selected_target_ids
            if target_id in state_by_id
        ]
        if len(targets) != len(selected_target_ids):
            raise ValueError("SELECTED_ACTION_TARGET_UNKNOWN")

        planned_actions = sorted(
            [
                _planned_action(item, state_by_id[item.target_requirement_id])
                for item in selected
            ],
            key=lambda item: (
                item.target_requirement_id,
                _role_order(item.action_role),
                item.channel,
                item.action_digest,
            ),
        )
        candidate_sum = sum(item.candidate_cap for item in planned_actions)
        if candidate_sum > policy.max_hydrated_candidates_per_query:
            raise ValueError("DG25_HYDRATION_BUDGET_EXCEEDED")
        lineage = RequirementAcquisitionPlanLineageV01(
            query_ir_digest=requirement_state.query_ir_digest,
            requirement_state_digest=requirement_state.state_digest,
            requirement_state_epoch=requirement_state.state_epoch,
            acquisition_capability_digest=(
                requirement_state.acquisition_capability_digest
            ),
            selection_policy_digest=policy.policy_digest,
            policy_digest=next(iter(action_policy_digests)),
            snapshot_identity=snapshot_identity,
            access_snapshot_identity=access_snapshot_identity,
        )
        plan = build_requirement_acquisition_plan(
            lineage=lineage,
            target_requirements=targets,
            actions=planned_actions,
            aggregate_budget=RequirementAcquisitionAggregateBudgetV01(
                max_repository_calls=min(
                    policy.max_additional_repository_calls_per_query,
                    DG25_REVIEWED_MAX_ACTIONS,
                ),
                planned_repository_calls=len(planned_actions),
                max_hydrated_candidates=(
                    policy.max_hydrated_candidates_per_query
                ),
                planned_candidate_cap_sum=candidate_sum,
            ),
        )
        baseline_caps = (
            {baseline.action_digest: baseline.bounded_cost["candidate_count"]}
            if baseline is not None
            else None
        )
        validation = validate_requirement_acquisition_plan(
            plan,
            requirement_state=requirement_state,
            feasible_actions=list(available.values()),
            policy=policy,
            current_snapshot_identity=snapshot_identity,
            current_access_snapshot_identity=access_snapshot_identity,
            baseline_candidate_caps=baseline_caps,
        )
        if not validation.accepted:
            raise ValueError(
                "COMPILED_REQUIREMENT_ACQUISITION_PLAN_INVALID:"
                + ",".join(validation.reason_codes)
            )
        selected_digests = sorted(item.action_digest for item in selected)
        return RequirementAcquisitionCompilationV01(
            mode=mode,
            plan=plan,
            validation=validation,
            baseline_action_digest=(
                baseline.action_digest if baseline is not None else None
            ),
            selected_action_digests=selected_digests,
            residual_action_digests=sorted(set(available) - set(selected_digests)),
        )


def _exact_action_index(
    feasible_actions: Sequence[FeasibleAcquisitionAction],
) -> dict[str, FeasibleAcquisitionAction]:
    values: dict[str, FeasibleAcquisitionAction] = {}
    for action in feasible_actions:
        if action.action_digest in values:
            raise ValueError("DUPLICATE_FEASIBLE_ACTION_DIGEST")
        values[action.action_digest] = action
    return values


def _registered_baseline(
    baseline: FeasibleAcquisitionAction | None,
    available: Mapping[str, FeasibleAcquisitionAction],
) -> FeasibleAcquisitionAction | None:
    if baseline is None:
        return None
    registered = available.get(baseline.action_digest)
    if registered != baseline:
        raise ValueError("BASELINE_ACTION_NOT_EXACT_FEASIBLE_MEMBER")
    return registered


def _select_actions(
    *,
    requirement_state: RequirementState,
    feasible_actions: Sequence[FeasibleAcquisitionAction],
    mode: RequirementAcquisitionCompilationMode,
    baseline: FeasibleAcquisitionAction | None,
) -> list[FeasibleAcquisitionAction]:
    if mode == "R0P_COMPATIBILITY":
        if baseline is None:
            raise ValueError("R0P_BASELINE_ACTION_REQUIRED")
        return [baseline]

    state_by_id = {
        item.requirement_id: item for item in requirement_state.requirements
    }
    proof_candidates = [
        item
        for item in feasible_actions
        if item.channel in _PROOF_CHANNELS
        and _proof_needed(state_by_id.get(item.target_requirement_id))
    ]
    proof = min(proof_candidates, key=_proof_action_key) if proof_candidates else None

    selected: list[FeasibleAcquisitionAction] = []
    if baseline is not None:
        selected.append(baseline)
    else:
        discovery_candidates = [
            item
            for item in feasible_actions
            if item.channel not in _LOCAL_CHANNELS
            and not (
                item.channel in _PROOF_CHANNELS
                and _proof_needed(state_by_id.get(item.target_requirement_id))
            )
        ]
        if discovery_candidates:
            selected.append(min(discovery_candidates, key=_discovery_action_key))
        elif proof is not None:
            selected.append(proof)

    if proof is not None and proof.action_digest not in {
        item.action_digest for item in selected
    }:
        selected.append(proof)
    if not selected:
        local_candidates = [
            item for item in feasible_actions if item.channel in _LOCAL_CHANNELS
        ]
        if local_candidates:
            selected.append(min(local_candidates, key=_local_action_key))
    return selected[:DG25_REVIEWED_MAX_ACTIONS]


def _target_contract(
    disposition: RequirementDisposition,
    selected_actions: Sequence[FeasibleAcquisitionAction],
    *,
    missing_evidence_roles: Mapping[str, Sequence[str]] | None,
    proof_obligations: Mapping[str, Sequence[str]] | None,
) -> TargetRequirementV01:
    actions = [
        item
        for item in selected_actions
        if item.target_requirement_id == disposition.requirement_id
    ]
    explicit_roles = (missing_evidence_roles or {}).get(disposition.requirement_id)
    roles = (
        list(explicit_roles)
        if explicit_roles is not None
        else _default_missing_roles(disposition)
    )
    explicit_proofs = (proof_obligations or {}).get(disposition.requirement_id)
    proofs = (
        list(explicit_proofs)
        if explicit_proofs is not None
        else (
            ["ALL_MATCHES_IN_RANGE"]
            if _proof_needed(disposition)
            and any(item.channel in _PROOF_CHANNELS for item in actions)
            else []
        )
    )
    return TargetRequirementV01(
        requirement_id=disposition.requirement_id,
        kind=disposition.kind,
        status=disposition.status,
        missing_evidence_roles=sorted(set(roles)),
        proof_obligations=sorted(set(proofs)),
    )


def _planned_action(
    action: FeasibleAcquisitionAction,
    disposition: RequirementDisposition,
) -> PlannedRequirementAcquisitionActionV01:
    role = _action_role(action, disposition)
    return PlannedRequirementAcquisitionActionV01(
        action_digest=action.action_digest,
        target_requirement_id=action.target_requirement_id,
        action_role=role,
        capability_id=action.capability_id,
        channel=action.channel,
        candidate_cap=action.bounded_cost["candidate_count"],
        bounded_cost=action.bounded_cost,
        reason_code=_action_reason(role, disposition),
    )


def _action_role(
    action: FeasibleAcquisitionAction,
    disposition: RequirementDisposition,
) -> AcquisitionActionRole:
    if action.channel in _LOCAL_CHANNELS:
        return "LOCAL_EXPANSION"
    if action.channel in _PROOF_CHANNELS and _proof_needed(disposition):
        return "PROOF_CLOSURE"
    return "EVIDENCE_DISCOVERY"


def _action_reason(
    role: AcquisitionActionRole,
    disposition: RequirementDisposition,
) -> str:
    if role == "PROOF_CLOSURE":
        return "ALL_MATCHES_IN_RANGE_REQUIRES_PROOF"
    if role == "LOCAL_EXPANSION":
        return "MISSING_ROLE_HAS_GOVERNED_LOCAL_ANCHOR"
    return f"REQUIREMENT_{disposition.status}_NEEDS_EVIDENCE"


def _proof_needed(disposition: RequirementDisposition | None) -> bool:
    return bool(
        disposition is not None
        and (
            disposition.kind == "RANGE_COMPLETENESS"
            or disposition.status == "COMPLETENESS_PROOF_MISSING"
            or disposition.proof_status not in {"SATISFIED", "NOT_REQUIRED"}
        )
    )


def _default_missing_roles(disposition: RequirementDisposition) -> list[str]:
    if disposition.status == "COMPLETENESS_PROOF_MISSING":
        return []
    if disposition.status == "UNDER_COVERED":
        return ["ADDITIONAL_DISTINCT_EVIDENCE"]
    return ["REQUIREMENT_MATCH"]


def _proof_action_key(
    action: FeasibleAcquisitionAction,
) -> tuple[int, str, str]:
    return (
        _PROOF_CHANNEL_ORDER.index(action.channel),
        action.target_requirement_id,
        action.action_digest,
    )


def _discovery_action_key(
    action: FeasibleAcquisitionAction,
) -> tuple[int, str, str]:
    return (
        _DISCOVERY_CHANNEL_ORDER.index(action.channel),
        action.target_requirement_id,
        action.action_digest,
    )


def _local_action_key(
    action: FeasibleAcquisitionAction,
) -> tuple[str, str, str]:
    return (action.channel, action.target_requirement_id, action.action_digest)


def _role_order(role: AcquisitionActionRole) -> int:
    return {
        "EVIDENCE_DISCOVERY": 0,
        "PROOF_CLOSURE": 1,
        "LOCAL_EXPANSION": 2,
    }[role]


__all__ = [
    "DG25_REVIEWED_MAX_ACTIONS",
    "RequirementAcquisitionCompilationMode",
    "RequirementAcquisitionCompilationV01",
    "RequirementAcquisitionPlanCompiler",
]
