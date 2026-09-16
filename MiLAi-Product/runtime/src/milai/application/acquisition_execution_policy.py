"""Load, summarize, and select DG-21 acquisition execution profiles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import ValidationError

from milai.domain.acquisition import AcquisitionPlan
from milai.domain.acquisition_capability import (
    AcquisitionCapabilityName,
    AcquisitionCapabilitySet,
)
from milai.domain.acquisition_execution_policy import (
    AcquisitionExecutionBudget,
    AcquisitionExecutionPolicy,
    AcquisitionExecutionProfileName,
    AcquisitionExecutionSelection,
    AcquisitionExecutionTerminalDisposition,
)
from milai.domain.acquisition_observation import AcquisitionObservationV02
from milai.domain.requirement_state import RequirementDisposition, RequirementState
from milai.domain.semantic_query import MemoryQueryIRV02, NormalizedTemporalConstraint
from milai.domain.sufficiency import SufficiencyDecision


class AcquisitionExecutionPolicyError(ValueError):
    """A policy is unknown, malformed, stale, or unsafe."""


def default_acquisition_execution_policy() -> AcquisitionExecutionPolicy:
    provisional = AcquisitionExecutionPolicy.model_construct(
        policy_digest="0" * 64,
    )
    payload = provisional.model_dump(mode="json", exclude={"policy_digest"})
    from milai.domain.requirement_state import canonical_sha256

    return AcquisitionExecutionPolicy(
        policy_digest=canonical_sha256(payload),
        **payload,
    )


def load_acquisition_execution_policy(
    payload: Mapping[str, Any] | None = None,
) -> AcquisitionExecutionPolicy:
    """Load the sole supported v0.2 policy; extra keys and versions fail closed."""

    if payload is None:
        return default_acquisition_execution_policy()
    if payload.get("schema_version") != "acquisition-execution-policy-v0.2":
        raise AcquisitionExecutionPolicyError("UNKNOWN_ACQUISITION_POLICY_SCHEMA")
    if payload.get("policy_version") != "dg21-opened-dev-v0.1":
        raise AcquisitionExecutionPolicyError("UNKNOWN_ACQUISITION_POLICY_VERSION")
    try:
        return AcquisitionExecutionPolicy.model_validate(dict(payload))
    except ValidationError as exc:
        raise AcquisitionExecutionPolicyError("INVALID_ACQUISITION_EXECUTION_POLICY") from exc


def acquisition_execution_policy_safe_summary(
    policy: AcquisitionExecutionPolicy,
) -> dict[str, Any]:
    """Return operational identity and limits without query or Evidence content."""

    return {
        "schema_version": policy.schema_version,
        "policy_version": policy.policy_version,
        "policy_digest": policy.policy_digest,
        "default_enabled": policy.default_enabled,
        "max_extra_passes": policy.global_guards.max_extra_passes,
        "provider_calls": policy.global_guards.provider_calls,
        "automatic_retries": policy.global_guards.automatic_retries,
        "exclude_seen_regions": policy.global_guards.exclude_seen_regions,
        "profile_names": sorted(type(policy.profiles).model_fields),
        "candidate_caps": {
            "semantic_baseline": policy.profiles.semantic_slot.baseline_candidate_cap,
            "semantic_dense": policy.profiles.semantic_slot.dense_candidate_cap,
            "source_time_point": policy.profiles.source_time_point.scan_max_items,
            "event_time_point": policy.profiles.event_time_point.max_items,
            "event_range": policy.profiles.event_range_enumeration.max_items,
            "preference_adjacency": policy.profiles.preference_local.adjacent_max_items,
        },
    }


def recovery_plan_candidate_cap(
    policy: AcquisitionExecutionPolicy,
    query_ir: MemoryQueryIRV02,
) -> int:
    """Return the generic plan ceiling, separate from channel scan budgets.

    AcquisitionPlan candidates are hydrated search candidates and are bounded by
    its 256-item contract.  Repository range scans retain their larger typed
    profile limits and are enforced by the channel executor.
    """

    temporal = query_ir.constraints.normalized_temporal
    if (
        temporal is not None
        and temporal.time_axis == "SOURCE_OBSERVED_TIME"
        and temporal.boundary == "POINT"
    ):
        return policy.profiles.source_time_point.scan_max_items
    if any(item.slot_id == "CURRENT_INTENT" for item in query_ir.requirements):
        return policy.profiles.preference_local.adjacent_max_items
    if temporal is not None and temporal.time_axis == "EVENT_TIME":
        if query_ir.completeness == "ALL_MATCHES_IN_RANGE" or any(
            item.cardinality.maximum is None or item.cardinality.distinct
            for item in query_ir.requirements
        ):
            return min(256, policy.profiles.event_range_enumeration.max_items)
        return policy.profiles.event_time_point.max_items
    return max(
        policy.profiles.semantic_slot.baseline_candidate_cap,
        policy.profiles.semantic_slot.dense_candidate_cap,
    )


def apply_execution_selection_to_plan(
    plan: AcquisitionPlan,
    selection: AcquisitionExecutionSelection,
) -> AcquisitionPlan:
    """Clamp every executable plan counter to the digest-bound effective budget."""

    if selection.terminal_disposition != "ACTIONABLE":
        raise AcquisitionExecutionPolicyError("TERMINAL_SELECTION_HAS_NO_EXECUTABLE_PLAN")
    candidate_count = selection.effective_budget.candidate_count
    hydrate_count = selection.effective_budget.hydrate_count
    if candidate_count < 1 or hydrate_count < 1:
        raise AcquisitionExecutionPolicyError("ACTIONABLE_SELECTION_HAS_ZERO_BUDGET")
    probes = [
        probe.model_copy(update={"candidate_limit": min(probe.candidate_limit, candidate_count)})
        for probe in plan.probes
    ]
    quotas = {key: min(value, candidate_count) for key, value in plan.fusion.per_slot_quota.items()}
    return plan.model_copy(
        update={
            "probes": probes,
            "fusion": plan.fusion.model_copy(
                update={"per_slot_quota": quotas, "global_cap": candidate_count}
            ),
            "budget": plan.budget.model_copy(
                update={
                    "candidate_count": candidate_count,
                    "hydrate_count": hydrate_count,
                }
            ),
        }
    )


def select_acquisition_execution_profile(
    *,
    policy: AcquisitionExecutionPolicy,
    query_ir: MemoryQueryIRV02,
    requirement_state: RequirementState,
    sufficiency: SufficiencyDecision,
    capability_set: AcquisitionCapabilitySet,
    remaining_budget: Mapping[str, int],
    observation: AcquisitionObservationV02 | None = None,
) -> AcquisitionExecutionSelection:
    """Select from typed Runtime facts only; dataset/scorer inputs are impossible here."""

    if requirement_state.acquisition_capability_digest != capability_set.capability_digest:
        raise AcquisitionExecutionPolicyError("STALE_ACQUISITION_CAPABILITY")
    if observation is not None and (
        observation.requirement_state_digest != requirement_state.state_digest
        or observation.requirement_state_epoch != requirement_state.state_epoch
        or observation.acquisition_capability_digest != capability_set.capability_digest
    ):
        raise AcquisitionExecutionPolicyError("STALE_SELECTOR_INPUT")
    input_material = {
        "query_ir": query_ir.model_dump(mode="json"),
        "requirement_state_digest": requirement_state.state_digest,
        "requirement_state_epoch": requirement_state.state_epoch,
        "sufficiency": sufficiency.model_dump(mode="json"),
        "capability_digest": capability_set.capability_digest,
        "capability_status": {
            **{
                key: {"status": value.status, "reason": value.reason}
                for key, value in capability_set.channels.items()
            },
            **{
                key: {"status": value.status, "reason": value.reason}
                for key, value in capability_set.expansions.items()
            },
        },
        "remaining_budget": dict(sorted(remaining_budget.items())),
        "observation_digest": (observation.observation_digest if observation is not None else None),
    }
    from milai.domain.requirement_state import canonical_sha256

    selector_inputs_digest = canonical_sha256(input_material)
    missing = [item for item in requirement_state.requirements if item.status != "SATISFIED"]
    if sufficiency.complete and not missing:
        return _selection(
            policy=policy,
            inputs_digest=selector_inputs_digest,
            profile="complete_fast_path",
            target=None,
            channel=None,
            terminal="COMPLETE",
            reason="SUFFICIENCY_COMPLETE_ZERO_WORK",
            declared=_budget(0, 0, 0),
            remaining_budget=remaining_budget,
        )
    if not missing:
        return _selection(
            policy=policy,
            inputs_digest=selector_inputs_digest,
            profile=None,
            target=None,
            channel=None,
            terminal="NO_TARGETABLE_REQUIREMENT",
            reason="SUFFICIENCY_INCOMPLETE_WITHOUT_TARGET",
            declared=_budget(0, 0, 0),
            remaining_budget=remaining_budget,
        )
    target = _target_requirement(missing, observation)
    first_loss = _first_loss(target.requirement_id, observation)
    temporal = _temporal_constraint(query_ir, target.requirement_id)
    profile, channel, terminal, reason, declared = _route(
        policy,
        query_ir,
        target,
        temporal,
        first_loss,
        capability_set,
        observation,
    )
    return _selection(
        policy=policy,
        inputs_digest=selector_inputs_digest,
        profile=profile,
        target=target.requirement_id,
        channel=channel,
        terminal=terminal,
        reason=reason,
        declared=declared,
        remaining_budget=remaining_budget,
    )


def _route(
    policy: AcquisitionExecutionPolicy,
    query_ir: MemoryQueryIRV02,
    target: RequirementDisposition,
    temporal: NormalizedTemporalConstraint | None,
    first_loss: str | None,
    capabilities: AcquisitionCapabilitySet,
    observation: AcquisitionObservationV02 | None,
) -> tuple[
    AcquisitionExecutionProfileName,
    AcquisitionCapabilityName | None,
    AcquisitionExecutionTerminalDisposition,
    str,
    AcquisitionExecutionBudget,
]:
    if first_loss in {
        "BINDING_POSSIBLE_SEMANTICS_OWNER",
        # Backward-compatible handling for previously sealed v0.2 observations.
        "BINDING_REJECTED_OR_POSSIBLE",
    }:
        return (
            "semantic_slot",
            None,
            "SEMANTICS_OWNER",
            "ANSWER_CANDIDATE_PRESENT_SEMANTICS_OWNER",
            _budget(0, 0, 0),
        )
    if target.requirement_id == "CURRENT_INTENT":
        preference_profile = policy.profiles.preference_local
        if _available(
            capabilities,
            "ADJACENT_TURNS",
            target.requirement_id,
            observation,
        ) and _valid_anchor(observation):
            return (
                "preference_local",
                "ADJACENT_TURNS",
                "ACTIONABLE",
                "CURRENT_INTENT_LOCAL_ANCHOR",
                _budget(
                    1,
                    preference_profile.adjacent_max_items,
                    preference_profile.adjacent_max_items,
                ),
            )
        return (
            "preference_local",
            None,
            "CAPABILITY_REQUIRED_UNAVAILABLE",
            "CURRENT_INTENT_ADJACENCY_UNAVAILABLE",
            _budget(0, 0, 0),
        )
    if temporal is not None and temporal.time_axis == "SOURCE_OBSERVED_TIME":
        source_profile = policy.profiles.source_time_point
        if temporal.boundary == "POINT" and (
            temporal.precision not in set(source_profile.supported_precisions)
            or not temporal.timezone
        ):
            return (
                "source_time_point",
                None,
                "SOURCE_POINT_BUCKET_UNPROVEN",
                "SOURCE_POINT_PRECISION_OR_TIMEZONE_MISSING",
                _budget(0, 0, 0),
            )
        if not _available(
            capabilities,
            "SOURCE_OBSERVED_RANGE_SCAN",
            target.requirement_id,
            observation,
        ):
            return (
                "source_time_point",
                None,
                "CAPABILITY_REQUIRED_UNAVAILABLE",
                "SOURCE_RANGE_SCAN_UNAVAILABLE",
                _budget(0, 0, 0),
            )
        return (
            "source_time_point",
            "SOURCE_OBSERVED_RANGE_SCAN",
            "ACTIONABLE",
            "PRECISION_PRESERVING_SOURCE_BUCKET",
            _budget(1, source_profile.scan_max_items, source_profile.scan_max_items),
        )
    if temporal is not None and temporal.time_axis == "EVENT_TIME":
        is_enumeration = (
            target.kind
            in {
                "CARDINALITY",
                "RANGE_COMPLETENESS",
                "SET_MEMBERS",
            }
            or query_ir.completeness == "ALL_MATCHES_IN_RANGE"
        )
        if not _available(
            capabilities,
            "TEMPORAL_EVENT",
            target.requirement_id,
            observation,
        ):
            return (
                "event_range_enumeration" if is_enumeration else "event_time_point",
                None,
                "CAPABILITY_REQUIRED_UNAVAILABLE",
                "EVENT_PROJECTION_UNAVAILABLE",
                _budget(0, 0, 0),
            )
        if is_enumeration:
            range_profile = policy.profiles.event_range_enumeration
            return (
                "event_range_enumeration",
                "TEMPORAL_EVENT",
                "ACTIONABLE",
                "EVENT_RANGE_PROOF_REQUIRED",
                _budget(1, range_profile.max_items, range_profile.max_items),
            )
        point_profile = policy.profiles.event_time_point
        return (
            "event_time_point",
            "TEMPORAL_EVENT",
            "ACTIONABLE",
            "EVENT_TIME_FILTER_REQUIRED",
            _budget(1, point_profile.max_items, point_profile.max_items),
        )
    semantic = policy.profiles.semantic_slot
    if _valid_target_anchor(observation, target.requirement_id) and _available(
        capabilities,
        "ADJACENT_TURNS",
        target.requirement_id,
        observation,
    ):
        return (
            "semantic_slot",
            "ADJACENT_TURNS",
            "ACTIONABLE",
            "VALID_LOCAL_ANCHOR",
            _budget(1, semantic.adjacent_max_items, semantic.adjacent_max_items),
        )
    if (
        _available(
            capabilities,
            "FTS_ENRICHED",
            target.requirement_id,
            observation,
        )
        and first_loss == "CHANNEL_RETRIEVAL_BOUND_MISS"
    ):
        return (
            "semantic_slot",
            "FTS_ENRICHED",
            "ACTIONABLE",
            "LEXICAL_CHANNEL_MISS",
            _budget(1, semantic.baseline_candidate_cap, semantic.baseline_candidate_cap),
        )
    if _available(
        capabilities,
        "EVIDENCE_DENSE",
        target.requirement_id,
        observation,
    ):
        return (
            "semantic_slot",
            "EVIDENCE_DENSE",
            "ACTIONABLE",
            "SEMANTIC_CHANNEL_MISS",
            _budget(1, semantic.dense_candidate_cap, semantic.dense_candidate_cap),
        )
    if _available(
        capabilities,
        "FTS_RAW",
        target.requirement_id,
        observation,
    ):
        return (
            "semantic_slot",
            "FTS_RAW",
            "ACTIONABLE",
            "UNEXECUTED_TARGET_FTS_RAW",
            _budget(1, semantic.baseline_candidate_cap, semantic.baseline_candidate_cap),
        )
    return (
        "semantic_slot",
        None,
        "CAPABILITY_REQUIRED_UNAVAILABLE",
        "NO_EXECUTABLE_SEMANTIC_CHANNEL",
        _budget(0, 0, 0),
    )


def _selection(
    *,
    policy: AcquisitionExecutionPolicy,
    inputs_digest: str,
    profile: AcquisitionExecutionProfileName | None,
    target: str | None,
    channel: AcquisitionCapabilityName | None,
    terminal: AcquisitionExecutionTerminalDisposition,
    reason: str,
    declared: AcquisitionExecutionBudget,
    remaining_budget: Mapping[str, int],
) -> AcquisitionExecutionSelection:
    remaining_candidates = max(0, int(remaining_budget.get("candidate_count", 0)))
    remaining_passes = max(0, int(remaining_budget.get("acquisition_passes", 0)))
    actionable = terminal == "ACTIONABLE" and remaining_candidates > 0 and remaining_passes > 0
    if terminal == "ACTIONABLE" and not actionable:
        terminal = "BUDGET_EXHAUSTED"
        reason = "PROFILE_BUDGET_UNAVAILABLE"
        channel = None
    effective_candidates = min(declared.candidate_count, remaining_candidates) if actionable else 0
    effective = AcquisitionExecutionBudget(
        acquisition_passes=1 if actionable else 0,
        candidate_count=effective_candidates,
        hydrate_count=min(declared.hydrate_count, effective_candidates),
        context_evidence_count=(
            min(declared.context_evidence_count, effective_candidates) if actionable else 0
        ),
    )
    if not actionable:
        clamp_owner: Literal["PROFILE", "REMAINING_BUDGET", "TERMINAL"] = "TERMINAL"
        clamp_reason: str = terminal
    elif effective_candidates < declared.candidate_count:
        clamp_owner = "REMAINING_BUDGET"
        clamp_reason = "REMAINING_CANDIDATE_BUDGET"
    else:
        clamp_owner = "PROFILE"
        clamp_reason = "PROFILE_IS_EFFECTIVE_BUDGET_OWNER"
    semantic_profile = policy.profiles.semantic_slot
    material: dict[str, Any] = {
        "schema_version": "acquisition-execution-selection-v0.2",
        "policy_version": policy.policy_version,
        "policy_digest": policy.policy_digest,
        "selector_inputs_digest": inputs_digest,
        "selected_profile": profile,
        "target_requirement_id": target,
        "selected_channel": channel,
        "terminal_disposition": terminal,
        "reason_code": reason,
        "declared_budget": declared.model_dump(mode="json"),
        "effective_budget": effective.model_dump(mode="json"),
        "budget_clamp_owner": clamp_owner,
        "budget_clamp_reason": clamp_reason,
        "targeted_only": bool(profile and semantic_profile.targeted_only),
        "include_global_probe": False,
        "provider_calls_authorized": 0,
        "automatic_retries_authorized": 0,
        "formal_holdout_consumed": False,
        "canonical_mutation": False,
    }
    from milai.domain.requirement_state import canonical_sha256

    return AcquisitionExecutionSelection(
        selection_digest=canonical_sha256(material),
        **material,
    )


def _budget(passes: Literal[0, 1], candidates: int, hydrated: int) -> AcquisitionExecutionBudget:
    return AcquisitionExecutionBudget(
        acquisition_passes=passes,
        candidate_count=candidates,
        hydrate_count=hydrated,
        context_evidence_count=min(8, hydrated),
    )


def _target_requirement(
    missing: list[RequirementDisposition],
    observation: AcquisitionObservationV02 | None,
) -> RequirementDisposition:
    observed = (
        {item.requirement_id: item.first_loss_reason for item in observation.requirements}
        if observation is not None
        else {}
    )
    order = {
        "MISSING": 0,
        "UNDER_COVERED": 1,
        "UNRESOLVED": 2,
        "CONTESTED": 3,
        "COMPLETENESS_PROOF_MISSING": 4,
    }
    return min(
        missing,
        key=lambda item: (
            0 if item.requirement_id in observed else 1,
            order[item.status],
            item.requirement_id,
        ),
    )


def _first_loss(requirement_id: str, observation: AcquisitionObservationV02 | None) -> str | None:
    if observation is None:
        return None
    return next(
        (
            item.first_loss_reason
            for item in observation.requirements
            if item.requirement_id == requirement_id
        ),
        None,
    )


def _temporal_constraint(
    query_ir: MemoryQueryIRV02, requirement_id: str
) -> NormalizedTemporalConstraint | None:
    requirement = next(
        (item for item in query_ir.requirements if item.slot_id == requirement_id),
        None,
    )
    return (
        requirement.temporal_constraints
        if requirement is not None and requirement.temporal_constraints is not None
        else query_ir.constraints.normalized_temporal
    )


def _executable(capabilities: AcquisitionCapabilitySet, name: AcquisitionCapabilityName) -> bool:
    try:
        return capabilities.capability(name).executable
    except KeyError:
        return False


def _available(
    capabilities: AcquisitionCapabilitySet,
    name: AcquisitionCapabilityName,
    requirement_id: str,
    observation: AcquisitionObservationV02 | None,
) -> bool:
    if not _executable(capabilities, name):
        return False
    if observation is None:
        return True
    return not any(
        requirement.requirement_id == requirement_id
        and any(
            attempt.channel == name and attempt.status == "EXECUTED"
            for attempt in requirement.acquisition_history
        )
        for requirement in observation.requirements
    )


def _valid_anchor(observation: AcquisitionObservationV02 | None) -> bool:
    return bool(
        observation is not None and observation.global_observation.valid_adjacency_anchor_count > 0
    )


def _valid_target_anchor(
    observation: AcquisitionObservationV02 | None,
    requirement_id: str,
) -> bool:
    """Require both a structured anchor and target-local accepted evidence.

    A globally structured turn is not by itself evidence that adjacency is the
    right channel for an arbitrary missing slot.  Target-local accepted evidence
    makes adjacency a bounded expansion of an under-covered requirement instead
    of a generic replacement for semantic retrieval.
    """

    if observation is None or not _valid_anchor(observation):
        return False
    return any(
        item.requirement_id == requirement_id and bool(item.matched_evidence_refs)
        for item in observation.requirements
    )


__all__ = [
    "AcquisitionExecutionPolicyError",
    "acquisition_execution_policy_safe_summary",
    "apply_execution_selection_to_plan",
    "default_acquisition_execution_policy",
    "load_acquisition_execution_policy",
    "recovery_plan_candidate_cap",
    "select_acquisition_execution_profile",
]
