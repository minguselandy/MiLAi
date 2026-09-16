"""Build acquisition observations and select one bounded deterministic action."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from milai.application.accuracy_acquisition import (
    AccuracyAcquisitionExecutor,
    AccuracyChannel,
    compile_accuracy_action_decision,
    default_accuracy_acquisition_policy,
)
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    feasible_acquisition_actions,
    validate_feasible_action,
)
from milai.application.acquisition_execution_policy import (
    apply_execution_selection_to_plan,
    select_acquisition_execution_profile,
)
from milai.application.evidence_acquisition import (
    AcquisitionProbeDisposition,
    EvidenceAcquisitionExecution,
    EvidenceAcquisitionExecutionRef,
    EvidenceAcquisitionExecutor,
    EvidenceAcquisitionMode,
    materialize_acquisition_execution,
)
from milai.application.requirement_state import resolve_requirement_state
from milai.domain.acquisition import AcquisitionPlan
from milai.domain.acquisition_capability import (
    AcquisitionCapabilityName,
    AcquisitionCapabilitySet,
    FeasibleAcquisitionAction,
)
from milai.domain.acquisition_execution_policy import (
    AcquisitionExecutionPolicy,
    AcquisitionExecutionSelection,
)
from milai.domain.acquisition_observation import (
    AcquisitionAttemptObservationV02,
    AcquisitionFirstLossReason,
    AcquisitionObservationGlobalV02,
    AcquisitionObservationV02,
    AvailableAcquisitionActionV02,
    RequirementAcquisitionObservationV02,
)
from milai.domain.deterministic_recovery import (
    DeterministicRecoveryDecision,
    DeterministicRecoveryReason,
)
from milai.domain.requirement_state import (
    RequirementDisposition,
    RequirementState,
    canonical_sha256,
)
from milai.domain.retrieval import QueryPlan, RetrievalRequest
from milai.persistence import SessionContext

_CHANNEL_ORDER: tuple[AcquisitionCapabilityName, ...] = (
    "TEMPORAL_EVENT",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
    "FTS_RAW",
)
_TARGET_STATUS_ORDER = {
    "MISSING": 0,
    "UNDER_COVERED": 1,
    "UNRESOLVED": 2,
    "CONTESTED": 3,
    "COMPLETENESS_PROOF_MISSING": 4,
}


class DeterministicRecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_requirement_state: RequirementState
    feasible_actions: list[FeasibleAcquisitionAction]
    observation: AcquisitionObservationV02
    decision: DeterministicRecoveryDecision
    effective_acquisition_plan: AcquisitionPlan
    extra_pass_count: Literal[0, 1]
    final_execution: EvidenceAcquisitionExecution | None = None
    execution_selection: AcquisitionExecutionSelection | None = None
    superseded_execution_selection: AcquisitionExecutionSelection | None = None
    effective_acquisition_plan_digest: str | None = None
    accuracy_decision: dict[str, Any] | None = None
    accuracy_execution: dict[str, Any] | None = None
    provider_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    canonical_mutation: Literal[False] = False


class CapabilityConstrainedRecoveryService:
    """Reusable one-pass policy shared by product and no-mutation shadow paths."""

    def __init__(self, executor: EvidenceAcquisitionExecutor) -> None:
        self._executor = executor

    def recover(
        self,
        *,
        context: SessionContext,
        request: RetrievalRequest,
        query_plan: QueryPlan,
        recovery_plan: AcquisitionPlan,
        capability_set: AcquisitionCapabilitySet,
        policy: AcquisitionCapabilityPolicy,
        baseline_execution: EvidenceAcquisitionExecution,
        mode: EvidenceAcquisitionMode,
        type_directed_semantics: bool = False,
        execution_policy: AcquisitionExecutionPolicy | None = None,
        accuracy_executor: AccuracyAcquisitionExecutor | None = None,
    ) -> DeterministicRecoveryResult:
        query_ir = query_plan.memory_query_ir
        if query_ir is None:
            raise ValueError("deterministic recovery requires MemoryQueryIR")
        state = resolve_requirement_state(
            plan=recovery_plan,
            requirements=query_ir.requirements,
            acquisition_capability_digest=capability_set.capability_digest,
            candidates=baseline_execution.candidates,
            spans=baseline_execution.spans,
            interpretations=baseline_execution.interpretations,
            bindings=baseline_execution.bindings,
            sufficiency_decision=baseline_execution.sufficiency_decision,
            state_epoch=0,
            memory_query_ir=query_ir,
        )
        candidate_budget = min(policy.max_candidates, recovery_plan.fusion.global_cap)
        valid_adjacency_anchor_count = (
            _structured_adjacency_anchor_count(baseline_execution.results)
            if execution_policy is not None
            else min(2, len(baseline_execution.candidates))
        )
        actions = feasible_acquisition_actions(
            state,
            capability_set,
            policy,
            source_observed_range=(recovery_plan.global_constraints.source_observed_range),
            event_occurrence_range=(recovery_plan.global_constraints.event_occurrence_range),
            valid_anchor_available=(valid_adjacency_anchor_count > 0),
            remaining_candidates=candidate_budget,
            acquisition_plan=recovery_plan,
        )
        region_digests = [
            hashlib.sha256(candidate.source_turn_ref.rsplit(":t", 1)[0].encode()).hexdigest()
            for candidate in baseline_execution.candidates
        ]
        observation = build_acquisition_observation_v02(
            requirement_state=state,
            capability_set=capability_set,
            policy=policy,
            probe_dispositions=baseline_execution.probe_dispositions,
            feasible_actions=actions,
            remaining_budget={
                "acquisition_passes": policy.max_extra_passes,
                "candidate_count": candidate_budget,
                "model_calls": 0,
            },
            seen_region_digests=region_digests,
            valid_adjacency_anchor_count=valid_adjacency_anchor_count,
        )
        execution_selection = (
            select_acquisition_execution_profile(
                policy=execution_policy,
                query_ir=query_ir,
                requirement_state=state,
                sufficiency=baseline_execution.sufficiency_decision,
                capability_set=capability_set,
                remaining_budget={
                    "acquisition_passes": policy.max_extra_passes,
                    "candidate_count": candidate_budget,
                },
                observation=observation,
            )
            if execution_policy is not None
            else None
        )
        if execution_selection is None:
            decision = select_deterministic_recovery_action(
                requirement_state=state,
                capability_set=capability_set,
                policy=policy,
                observation=observation,
                feasible_actions=actions,
            )
            action = decision.selected_action
            effective_plan = recovery_plan
        else:
            action = _selected_execution_action(
                execution_selection,
                actions,
                requirement_state=state,
                capability_set=capability_set,
                policy=policy,
            )
            decision = _decision(
                requirement_state=state,
                capability_set=capability_set,
                policy_digest=canonical_sha256(policy.model_dump(mode="json")),
                observation=observation,
                action=action,
                reason=_execution_selection_reason(execution_selection, action),
            )
            effective_plan = (
                apply_execution_selection_to_plan(recovery_plan, execution_selection)
                if action is not None
                else recovery_plan
            )
        legacy_execution_selection = execution_selection
        accuracy_policy = default_accuracy_acquisition_policy()
        accuracy_decision = (
            compile_accuracy_action_decision(
                query_ir,
                state.missing_requirement_ids,
                executable_channels=_executable_accuracy_channels(capability_set, policy),
                requirement_state_digest=state.state_digest,
                acquisition_capability_digest=capability_set.capability_digest,
                semantics_owner_requirement_ids=[
                    item.requirement_id
                    for item in observation.requirements
                    if item.first_loss_reason == "BINDING_POSSIBLE_SEMANTICS_OWNER"
                ],
                policy=accuracy_policy,
            )
            if accuracy_executor is not None
            else None
        )
        superseded_execution_selection: AcquisitionExecutionSelection | None = None
        accuracy_action: FeasibleAcquisitionAction | None = None
        if accuracy_decision is not None and accuracy_decision["status"] == "EXECUTE_ONE_PASS":
            bundle = accuracy_decision["bundle"]
            accuracy_action = _accuracy_feasible_action(
                bundle.channel,
                bundle.target_requirement_ids[0],
                requirement_state=state,
                capability_set=capability_set,
                policy=policy,
            )
            superseded_execution_selection = legacy_execution_selection
            execution_selection = None
            action = accuracy_action
            effective_plan = recovery_plan
            decision = _decision(
                requirement_state=state,
                capability_set=capability_set,
                policy_digest=canonical_sha256(policy.model_dump(mode="json")),
                observation=observation,
                action=action,
                reason=_selected_reason(action.channel),
            )
        accuracy_execution: dict[str, Any] | None = None
        final_execution: EvidenceAcquisitionExecutionRef | None
        if accuracy_action is not None and accuracy_executor is not None:
            assert accuracy_decision is not None
            bundle = accuracy_decision["bundle"]
            accuracy_execution = accuracy_executor.execute(
                query_ir,
                bundle,
                current_requirement_state_digest=state.state_digest,
                current_acquisition_capability_digest=capability_set.capability_digest,
                policy=accuracy_policy,
            )
            selected = [
                {
                    key: value
                    for key, value in item.items()
                    if key != "accuracy_local_score"
                }
                for item in accuracy_execution["selected_evidence"]
                if isinstance(item, Mapping)
            ]
            baseline_bound = _bounded_bound_results(
                query_ir,
                baseline_execution,
                exclude_requirement_ids=(
                    accuracy_execution["first_reserve_requirement_ids"]
                ),
            )
            fusion_results = (
                _deduplicate_results([*selected, *baseline_bound])
                if selected
                else list(baseline_execution.results)
            )
            final_execution = self._executor.compile_existing_results(
                request=request,
                query_plan=query_plan,
                acquisition_plan=effective_plan,
                capability_set=capability_set,
                mode=mode,
                state_epoch=state.state_epoch + 1,
                results=fusion_results,
                action_digest=accuracy_action.action_digest,
                probe_dispositions=baseline_execution.probe_dispositions,
                probe_candidate_traces=baseline_execution.probe_candidate_traces,
                type_directed_semantics=type_directed_semantics,
            )
        else:
            final_execution = (
                self._executor.execute(
                    context=context,
                    request=request,
                    query_plan=query_plan,
                    acquisition_plan=effective_plan,
                    capability_set=capability_set,
                    policy=policy,
                    mode=mode,
                    state_epoch=state.state_epoch + 1,
                    action=action,
                    current_requirement_state=state,
                    existing_results=baseline_execution.results,
                    type_directed_semantics=type_directed_semantics,
                    execution_selection=execution_selection,
                )
                if action is not None
                else None
            )
        extra_pass_count: Literal[0, 1] = 1 if final_execution is not None else 0
        return DeterministicRecoveryResult(
            initial_requirement_state=state,
            feasible_actions=actions,
            observation=observation,
            decision=decision,
            final_execution=(
                materialize_acquisition_execution(final_execution)
                if final_execution is not None else None
            ),
            execution_selection=execution_selection,
            superseded_execution_selection=superseded_execution_selection,
            effective_acquisition_plan=effective_plan,
            effective_acquisition_plan_digest=canonical_sha256(
                effective_plan.model_dump(mode="json")
            ),
            accuracy_decision=_accuracy_decision_summary(accuracy_decision),
            accuracy_execution=accuracy_execution,
            extra_pass_count=extra_pass_count,
        )


def _executable_accuracy_channels(
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
) -> list[AccuracyChannel]:
    allowed = set(policy.allowed_capabilities)
    return [
        cast(AccuracyChannel, name)
        for name in ("FTS_ENRICHED", "EVIDENCE_DENSE", "FTS_RAW")
        if name in allowed and capability_set.channels[name].executable
    ]


def _accuracy_feasible_action(
    channel: AccuracyChannel,
    target_requirement_id: str,
    *,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
) -> FeasibleAcquisitionAction:
    capability = capability_set.channels[channel]
    payload: dict[str, Any] = {
        "schema_version": "feasible-acquisition-action-v0.1",
        "capability_id": capability.capability_id,
        "capability_digest": capability_set.capability_digest,
        "target_requirement_id": target_requirement_id,
        "requirement_state_digest": requirement_state.state_digest,
        "requirement_state_epoch": requirement_state.state_epoch,
        "policy_digest": canonical_sha256(policy.model_dump(mode="json")),
        "channel": channel,
        "bounded_cost": {
            "acquisition_passes": 1,
            "candidate_count": min(policy.max_candidates, policy.max_hydrated_items),
            "model_calls": 0,
        },
    }
    action = FeasibleAcquisitionAction(
        action_digest=canonical_sha256(payload),
        **payload,
    )
    validation = validate_feasible_action(action, requirement_state, capability_set, policy)
    if not validation.accepted:
        raise ValueError(validation.reason_code)
    return action


def _accuracy_decision_summary(decision: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    bundle = decision.get("bundle")
    return {
        "status": decision["status"],
        "reason_code": decision["reason_code"],
        "bundle": bundle.model_dump(mode="json") if bundle is not None else None,
        "extra_passes": decision["extra_passes"],
        "provider_controller_calls": decision["provider_controller_calls"],
        "automatic_retries": decision["automatic_retries"],
    }


def _bounded_bound_results(
    query_ir: Any,
    execution: EvidenceAcquisitionExecution,
    *,
    exclude_requirement_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Retain only Binding-backed baseline evidence within typed cardinality.

    Accuracy-selected evidence owns any requirement for which it reserved a
    match.  Other requirements retain their earliest governed provenance roots;
    exhaustive distinct requirements retain all bound evidence for their
    downstream identity-aware reducer.
    """

    excluded = set(exclude_requirement_ids)
    interpretation_by_id = {
        item.interpretation_id: item for item in execution.interpretations
    }
    span_by_id = {item.span_id: item for item in execution.spans}
    result_by_evidence_id = {
        str(item["evidence_id"]): dict(item)
        for item in execution.results
        if isinstance(item.get("evidence_id"), str)
    }
    evidence_by_requirement: dict[str, set[str]] = {}
    for binding in execution.bindings:
        if binding.status != "MATCH" or binding.requirement_id in excluded:
            continue
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        span = span_by_id.get(interpretation.span_id) if interpretation is not None else None
        if span is not None and span.source_evidence_id in result_by_evidence_id:
            evidence_by_requirement.setdefault(binding.requirement_id, set()).add(
                span.source_evidence_id
            )
    retained: set[str] = set()
    for requirement in query_ir.requirements:
        values = evidence_by_requirement.get(requirement.slot_id, set())
        ordered = sorted(
            values,
            key=lambda evidence_id: _result_provenance_order(
                result_by_evidence_id[evidence_id]
            ),
        )
        maximum = requirement.cardinality.maximum
        retained.update(ordered if maximum is None else ordered[:maximum])
    return [
        dict(item)
        for item in execution.results
        if isinstance(item.get("evidence_id"), str)
        and str(item["evidence_id"]) in retained
    ]


def _result_provenance_order(item: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("captured_at") or item.get("observed_at") or ""),
        str(item.get("source_ref") or item.get("evidence_id") or ""),
    )


def _deduplicate_results(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        evidence_id = value.get("evidence_id")
        source_ref = value.get("source_ref")
        if isinstance(evidence_id, str) and evidence_id:
            identity = ("evidence_id", evidence_id)
        elif isinstance(source_ref, str) and source_ref:
            identity = ("source_ref", source_ref)
        else:
            continue
        selected.setdefault(identity, dict(value))
    return list(selected.values())


def build_acquisition_observation_v02(
    *,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
    probe_dispositions: Sequence[AcquisitionProbeDisposition],
    feasible_actions: Sequence[FeasibleAcquisitionAction],
    remaining_budget: Mapping[str, int],
    seen_region_digests: Sequence[str] = (),
    exhausted_region_digests: Sequence[str] = (),
    valid_adjacency_anchor_count: int = 0,
) -> AcquisitionObservationV02:
    """Project label-free Runtime state into the sole deterministic policy input."""

    policy_digest = canonical_sha256(policy.model_dump(mode="json"))
    if requirement_state.acquisition_capability_digest != capability_set.capability_digest:
        raise ValueError("observation RequirementState/capability identity mismatch")
    if capability_set.policy_digest != policy_digest:
        raise ValueError("observation capability/policy identity mismatch")
    valid_actions: dict[str, list[FeasibleAcquisitionAction]] = {}
    for action in feasible_actions:
        validation = validate_feasible_action(action, requirement_state, capability_set, policy)
        if not validation.accepted:
            raise ValueError(f"observation contains infeasible action: {validation.reason_code}")
        valid_actions.setdefault(action.target_requirement_id, []).append(action)
    requirements = [
        _requirement_observation(
            disposition,
            probe_dispositions=probe_dispositions,
            actions=valid_actions.get(disposition.requirement_id, []),
        )
        for disposition in requirement_state.requirements
        if disposition.status != "SATISFIED"
    ]
    raw_seen = list(seen_region_digests)
    seen = sorted(set(raw_seen))
    exhausted = sorted(set(exhausted_region_digests))
    repeated = (len(raw_seen) - len(seen)) / len(raw_seen) if raw_seen else 0.0
    material: dict[str, Any] = {
        "schema_version": "acquisition-observation-v0.2",
        "requirement_state_digest": requirement_state.state_digest,
        "requirement_state_epoch": requirement_state.state_epoch,
        "acquisition_capability_digest": capability_set.capability_digest,
        "policy_digest": policy_digest,
        "requirements": [item.model_dump(mode="json") for item in requirements],
        "global_observation": AcquisitionObservationGlobalV02(
            seen_region_digests=seen,
            exhausted_region_digests=exhausted,
            repeated_region_rate=repeated,
            valid_adjacency_anchor_count=valid_adjacency_anchor_count,
            remaining_budget=dict(remaining_budget),
        ).model_dump(mode="json"),
        "canonical": False,
        "canonical_mutation": False,
    }
    return AcquisitionObservationV02(
        observation_digest=canonical_sha256(material),
        **material,
    )


def select_deterministic_recovery_action(
    *,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
    observation: AcquisitionObservationV02,
    feasible_actions: Sequence[FeasibleAcquisitionAction],
) -> DeterministicRecoveryDecision:
    """Select no more than one non-repeated action with no Provider authority."""

    policy_digest = canonical_sha256(policy.model_dump(mode="json"))
    if (
        observation.requirement_state_digest != requirement_state.state_digest
        or observation.requirement_state_epoch != requirement_state.state_epoch
        or observation.acquisition_capability_digest != capability_set.capability_digest
        or observation.policy_digest != policy_digest
    ):
        raise ValueError("deterministic policy input identity mismatch")
    observed_ids = [item.requirement_id for item in observation.requirements]
    if observed_ids != requirement_state.missing_requirement_ids:
        raise ValueError("deterministic policy observation target set drifted")
    if not observed_ids:
        return _decision(
            requirement_state=requirement_state,
            capability_set=capability_set,
            policy_digest=policy_digest,
            observation=observation,
            action=None,
            reason="DETERMINISTIC_COMPLETE",
        )
    budget = observation.global_observation.remaining_budget
    if budget.get("acquisition_passes", 0) < 1 or budget.get("candidate_count", 0) < 1:
        return _decision(
            requirement_state=requirement_state,
            capability_set=capability_set,
            policy_digest=policy_digest,
            observation=observation,
            action=None,
            reason="BUDGET_EXHAUSTED",
        )
    actions_by_requirement: dict[
        str, dict[AcquisitionCapabilityName, FeasibleAcquisitionAction]
    ] = {}
    advertised = {
        item.requirement_id: {value.action_digest for value in item.available_actions}
        for item in observation.requirements
    }
    for action in feasible_actions:
        validation = validate_feasible_action(action, requirement_state, capability_set, policy)
        if not validation.accepted:
            continue
        if action.action_digest not in advertised.get(action.target_requirement_id, set()):
            continue
        actions_by_requirement.setdefault(action.target_requirement_id, {})[action.channel] = action
    ordered_requirements = sorted(
        observation.requirements,
        key=lambda item: (_TARGET_STATUS_ORDER[item.status], item.requirement_id),
    )
    proof_only_seen = False
    for requirement in ordered_requirements:
        available = actions_by_requirement.get(requirement.requirement_id, {})
        if requirement.status == "COMPLETENESS_PROOF_MISSING" or requirement.kind in {
            "RANGE_COMPLETENESS",
            "CARDINALITY",
            "SET_MEMBERS",
        }:
            proof_only_seen = True
            selected = available.get("SOURCE_OBSERVED_RANGE_SCAN")
            if selected is not None and not _already_executed(
                requirement, "SOURCE_OBSERVED_RANGE_SCAN"
            ):
                return _decision(
                    requirement_state=requirement_state,
                    capability_set=capability_set,
                    policy_digest=policy_digest,
                    observation=observation,
                    action=selected,
                    reason="SELECTED_SOURCE_RANGE_PROOF",
                )
            continue
        for channel in _CHANNEL_ORDER:
            selected = available.get(channel)
            if selected is None or _already_executed(requirement, channel):
                continue
            return _decision(
                requirement_state=requirement_state,
                capability_set=capability_set,
                policy_digest=policy_digest,
                observation=observation,
                action=selected,
                reason=_selected_reason(channel),
            )
    return _decision(
        requirement_state=requirement_state,
        capability_set=capability_set,
        policy_digest=policy_digest,
        observation=observation,
        action=None,
        reason=(
            "COMPLETENESS_PROOF_CHANNEL_UNAVAILABLE"
            if proof_only_seen
            else "NO_NONREPEATED_FEASIBLE_ACTION"
        ),
    )


def _selected_execution_action(
    selection: AcquisitionExecutionSelection,
    actions: Sequence[FeasibleAcquisitionAction],
    *,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
) -> FeasibleAcquisitionAction | None:
    if selection.terminal_disposition != "ACTIONABLE":
        return None
    if selection.target_requirement_id is None or selection.selected_channel is None:
        raise ValueError("ACTIONABLE_EXECUTION_SELECTION_MISSING_TARGET_OR_CHANNEL")
    candidate = next(
        (
            item
            for item in actions
            if item.target_requirement_id == selection.target_requirement_id
            and item.channel == selection.selected_channel
        ),
        None,
    )
    if candidate is None:
        raise ValueError("EXECUTION_SELECTION_HAS_NO_FEASIBLE_ACTION")
    payload: dict[str, Any] = candidate.model_dump(mode="json", exclude={"action_digest"})
    payload["bounded_cost"] = {
        "acquisition_passes": selection.effective_budget.acquisition_passes,
        # FeasibleAcquisitionAction has one item-count field.  Repository scan
        # ceilings remain channel-owned; an action may hydrate only the smaller
        # execution-policy/capability allowance into semantic work and context.
        "candidate_count": min(
            selection.effective_budget.hydrate_count,
            policy.max_hydrated_items,
        ),
        "model_calls": 0,
    }
    action = FeasibleAcquisitionAction(
        action_digest=canonical_sha256(payload),
        **payload,
    )
    validation = validate_feasible_action(
        action,
        requirement_state,
        capability_set,
        policy,
    )
    if not validation.accepted:
        raise ValueError(validation.reason_code)
    return action


def _execution_selection_reason(
    selection: AcquisitionExecutionSelection,
    action: FeasibleAcquisitionAction | None,
) -> DeterministicRecoveryReason:
    if action is not None:
        return _selected_reason(action.channel)
    terminal: dict[str, DeterministicRecoveryReason] = {
        "COMPLETE": "COMPLETE",
        "NO_TARGETABLE_REQUIREMENT": "NO_TARGETABLE_REQUIREMENT",
        "CAPABILITY_REQUIRED_UNAVAILABLE": "CAPABILITY_REQUIRED_UNAVAILABLE",
        "SOURCE_POINT_BUCKET_UNPROVEN": "SOURCE_POINT_BUCKET_UNPROVEN",
        "SEMANTICS_OWNER": "SEMANTICS_OWNER",
        "BUDGET_EXHAUSTED": "BUDGET_EXHAUSTED",
    }
    reason = terminal.get(selection.terminal_disposition)
    if reason is None:
        raise ValueError("UNKNOWN_EXECUTION_SELECTION_TERMINAL")
    return reason


def _structured_adjacency_anchor_count(
    results: Sequence[Mapping[str, Any]],
) -> int:
    count = 0
    for item in results:
        context = item.get("source_context")
        if (
            isinstance(item.get("evidence_id"), str)
            and item.get("source_context_source") == "STRUCTURED_TURN_METADATA"
            and isinstance(context, Mapping)
            and isinstance(context.get("session_id"), str)
            and isinstance(context.get("round_ordinal"), int)
        ):
            count += 1
    return min(2, count)


def _requirement_observation(
    disposition: RequirementDisposition,
    *,
    probe_dispositions: Sequence[AcquisitionProbeDisposition],
    actions: Sequence[FeasibleAcquisitionAction],
) -> RequirementAcquisitionObservationV02:
    history = sorted(
        (
            AcquisitionAttemptObservationV02(
                probe_id=item.probe_id,
                channel=item.channel,
                status=item.status,
                reason_code=item.reason_code,
                raw_candidate_count=item.raw_candidate_count,
                selected_candidate_count=item.selected_candidate_count,
            )
            for item in probe_dispositions
            if item.requirement_id in {None, disposition.requirement_id}
        ),
        key=lambda item: (item.channel, item.probe_id),
    )
    available = sorted(
        (
            AvailableAcquisitionActionV02(
                action_digest=item.action_digest,
                channel=item.channel,
            )
            for item in actions
        ),
        key=lambda item: item.action_digest,
    )
    return RequirementAcquisitionObservationV02(
        requirement_id=disposition.requirement_id,
        kind=disposition.kind,
        status=disposition.status,
        first_loss_reason=_first_loss(disposition, history),
        matched_evidence_refs=disposition.accepted_evidence_refs,
        possible_binding_refs=disposition.possible_binding_refs,
        rejected_candidate_refs=sorted(
            {item.candidate_ref for item in disposition.rejected_candidates}
        ),
        rejection_summary=disposition.rejection_summary,
        acquisition_history=history,
        available_actions=available,
    )


def _first_loss(
    disposition: RequirementDisposition,
    history: Sequence[AcquisitionAttemptObservationV02],
) -> AcquisitionFirstLossReason:
    if disposition.status == "COMPLETENESS_PROOF_MISSING":
        return "COMPLETENESS_PROOF_MISSING"
    # A POSSIBLE binding is an interpretation already present that only the
    # semantics owner can resolve. Rejected bindings prove the opposite: the
    # observed candidates are not compatible evidence for this requirement and
    # therefore must not suppress a bounded acquisition action.
    if disposition.possible_binding_refs:
        return "BINDING_POSSIBLE_SEMANTICS_OWNER"
    if disposition.rejected_binding_refs:
        return "CANDIDATES_WITHOUT_COMPATIBLE_BINDING"
    executed = [item for item in history if item.status == "EXECUTED"]
    if any(item.raw_candidate_count for item in executed):
        return "CANDIDATES_WITHOUT_COMPATIBLE_BINDING"
    if executed:
        return "CHANNEL_RETRIEVAL_BOUND_MISS"
    return "CAPABILITY_UNAVAILABLE_OR_NOT_RUN"


def _already_executed(
    requirement: RequirementAcquisitionObservationV02,
    channel: AcquisitionCapabilityName,
) -> bool:
    return any(
        item.channel == channel and item.status == "EXECUTED"
        for item in requirement.acquisition_history
    )


def _selected_reason(channel: AcquisitionCapabilityName) -> DeterministicRecoveryReason:
    values: dict[AcquisitionCapabilityName, DeterministicRecoveryReason] = {
        "TEMPORAL_EVENT": "SELECTED_TEMPORAL_EVENT",
        "FTS_ENRICHED": "SELECTED_FTS_ENRICHED",
        "EVIDENCE_DENSE": "SELECTED_EVIDENCE_DENSE",
        "ADJACENT_TURNS": "SELECTED_ADJACENT_TURNS",
        "SAME_EPISODE": "SELECTED_SAME_EPISODE",
        "FTS_RAW": "SELECTED_FTS_RAW_NOT_PREVIOUSLY_EXECUTED",
        "SOURCE_OBSERVED_RANGE_SCAN": "SELECTED_SOURCE_RANGE_PROOF",
        "CANONICAL_STATE": "NO_NONREPEATED_FEASIBLE_ACTION",
    }
    return values[channel]


def _decision(
    *,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy_digest: str,
    observation: AcquisitionObservationV02,
    action: FeasibleAcquisitionAction | None,
    reason: DeterministicRecoveryReason,
) -> DeterministicRecoveryDecision:
    material: dict[str, Any] = {
        "schema_version": "deterministic-recovery-decision-v0.1",
        "requirement_state_digest": requirement_state.state_digest,
        "requirement_state_epoch": requirement_state.state_epoch,
        "acquisition_capability_digest": capability_set.capability_digest,
        "policy_digest": policy_digest,
        "observation_digest": observation.observation_digest,
        "reason_code": reason,
        "selected_action": action.model_dump(mode="json") if action is not None else None,
        "extra_passes_authorized": 1 if action is not None else 0,
        "provider_calls_authorized": 0,
        "automatic_retries_authorized": 0,
        "canonical_mutation": False,
    }
    return DeterministicRecoveryDecision(
        decision_digest=canonical_sha256(material),
        **material,
    )


__all__ = [
    "CapabilityConstrainedRecoveryService",
    "DeterministicRecoveryResult",
    "build_acquisition_observation_v02",
    "select_deterministic_recovery_action",
]
