"""Resolve executable retrieval capability from live Runtime facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from milai.domain.acquisition import AcquisitionPlan
from milai.domain.acquisition_capability import (
    AcquisitionCapability,
    AcquisitionCapabilityName,
    AcquisitionCapabilitySet,
    FeasibleAcquisitionAction,
)
from milai.domain.requirement_state import RequirementState, canonical_sha256


class AcquisitionRuntimeCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lexical_enrichment_bound: bool = False
    lexical_enrichment_enabled: bool = False
    evidence_dense_enabled: bool = False
    embedding_projection_dimensions: int = Field(default=16, ge=1)
    adjacent_turns_acquisition_enabled: bool = False
    same_episode_acquisition_enabled: bool = False
    query_time_event_enabled: bool = False


def _default_allowed_capabilities() -> list[AcquisitionCapabilityName]:
    return [
        "FTS_RAW",
        "FTS_ENRICHED",
        "EVIDENCE_DENSE",
        "SOURCE_OBSERVED_RANGE_SCAN",
        "TEMPORAL_EVENT",
        "CANONICAL_STATE",
        "ADJACENT_TURNS",
        "SAME_EPISODE",
    ]


class AcquisitionCapabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(default="deterministic-recovery-policy-v0.1", min_length=1)
    allowed_capabilities: list[AcquisitionCapabilityName] = Field(
        default_factory=_default_allowed_capabilities
    )
    max_extra_passes: Literal[1] = 1
    max_candidates: int = Field(default=64, ge=1, le=2_000)
    max_hydrated_items: int = Field(default=120, ge=1, le=256)


class FeasibleActionValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    reason_code: str = Field(min_length=1)


def resolve_acquisition_capabilities(
    *,
    config: AcquisitionRuntimeCapabilityConfig,
    projection_state: object,
    repository: object,
    policy: AcquisitionCapabilityPolicy,
    generated_at: datetime,
    source_observed_range: Mapping[str, object] | None = None,
    event_occurrence_range: Mapping[str, object] | None = None,
) -> AcquisitionCapabilitySet:
    """Derive capabilities; declared types alone never make an action executable."""

    config_payload = config.model_dump(mode="json")
    projection_payload = _projection_payload(projection_state)
    policy_payload = policy.model_dump(mode="json")
    config_digest = canonical_sha256(config_payload)
    projection_digest = canonical_sha256(projection_payload)
    policy_digest = canonical_sha256(policy_payload)
    evidence_dead_letter = projection_payload.get("evidence_dead_letter") is True

    raw = _capability(
        "FTS_RAW",
        status=(
            "UNAVAILABLE"
            if not callable(getattr(repository, "search_evidence", None)) or evidence_dead_letter
            else "ENABLED"
        ),
        reason=(
            "REPOSITORY_METHOD_UNAVAILABLE"
            if not callable(getattr(repository, "search_evidence", None))
            else "PROJECTION_DEAD_LETTER"
            if evidence_dead_letter
            else "READY"
        ),
    )
    if not config.lexical_enrichment_bound:
        enriched_status, enriched_reason = "DISABLED", "CONFIG_NOT_BOUND"
    elif not config.lexical_enrichment_enabled:
        enriched_status, enriched_reason = "DISABLED", "POLICY_DISABLED"
    elif not raw.executable:
        enriched_status, enriched_reason = "UNAVAILABLE", raw.reason
    else:
        enriched_status, enriched_reason = "ENABLED", "READY"
    enriched = _capability("FTS_ENRICHED", status=enriched_status, reason=enriched_reason)

    dense_method = callable(getattr(repository, "search_evidence_dense", None))
    if not dense_method:
        dense_status, dense_reason = "UNAVAILABLE", "REPOSITORY_METHOD_UNAVAILABLE"
    elif not config.evidence_dense_enabled:
        dense_status, dense_reason = "DISABLED", "POLICY_DISABLED"
    elif config.embedding_projection_dimensions != 128:
        dense_status, dense_reason = "UNAVAILABLE", "PROJECTION_DIMENSION_MISMATCH"
    elif _bounded_range(event_occurrence_range):
        dense_status, dense_reason = "UNAVAILABLE", "EVENT_TIME_FILTER_UNAVAILABLE"
    elif source_observed_range is not None and not executable_closed_open_range(
        source_observed_range
    ):
        dense_status, dense_reason = (
            "UNAVAILABLE",
            "SOURCE_TIME_FILTER_UNAVAILABLE",
        )
    elif evidence_dead_letter:
        dense_status, dense_reason = "UNAVAILABLE", "PROJECTION_DEAD_LETTER"
    else:
        dense_status, dense_reason = "ENABLED", "READY"
    dense = _capability(
        "EVIDENCE_DENSE",
        status=dense_status,
        reason=dense_reason,
        requirements={"projection_dimensions": 128},
    )

    range_method = callable(getattr(repository, "scan_evidence_range", None))
    if not range_method:
        range_status, range_reason = "UNAVAILABLE", "REPOSITORY_METHOD_UNAVAILABLE"
    elif evidence_dead_letter:
        range_status, range_reason = "UNAVAILABLE", "PROJECTION_DEAD_LETTER"
    elif source_observed_range is not None and not executable_closed_open_range(
        source_observed_range
    ):
        range_status, range_reason = (
            "UNAVAILABLE",
            "SOURCE_RANGE_BOUNDARY_UNSUPPORTED",
        )
    elif executable_closed_open_range(source_observed_range):
        range_status, range_reason = "ENABLED", "READY"
    else:
        range_status, range_reason = "CONDITIONAL", "BOUNDED_SOURCE_RANGE_REQUIRED"
    source_range = _capability(
        "SOURCE_OBSERVED_RANGE_SCAN",
        status=range_status,
        reason=range_reason,
        limits={"max_items": 2_000},
    )

    event_method = callable(getattr(repository, "search_evidence_event_range", None))
    event_range_ready = executable_closed_open_range(event_occurrence_range)
    if not config.query_time_event_enabled:
        event_status, event_reason = "DISABLED", "POLICY_DISABLED"
    elif not event_method:
        event_status, event_reason = "UNAVAILABLE", "EVENT_RANGE_METHOD_NOT_READY"
    elif evidence_dead_letter:
        event_status, event_reason = "UNAVAILABLE", "PROJECTION_DEAD_LETTER"
    elif not event_range_ready:
        event_status, event_reason = "CONDITIONAL", "BOUNDED_EVENT_RANGE_REQUIRED"
    else:
        event_status, event_reason = "ENABLED", "QUERY_TIME_EVENT_NORMALIZATION_READY"
    event = _capability(
        "TEMPORAL_EVENT",
        status=event_status,
        reason=event_reason,
        limits={"max_items": 2_000},
        requirements={
            "partition": "FULL_GOVERNED_EVIDENCE_SNAPSHOT_AS_OF",
            "normalization": "QUERY_TIME_EVENT_V1",
        },
    )
    canonical_method = any(
        callable(getattr(repository, name, None))
        for name in ("canonical_search", "l0_candidates", "exact_candidates")
    )
    canonical = _capability(
        "CANONICAL_STATE",
        status="ENABLED" if canonical_method else "UNAVAILABLE",
        reason="READY" if canonical_method else "REPOSITORY_METHOD_UNAVAILABLE",
    )

    adjacency_method = callable(getattr(repository, "hydrate_evidence_adjacency", None))
    adjacency = _capability(
        "ADJACENT_TURNS",
        kind="EXPANSION",
        status=(
            "ENABLED"
            if adjacency_method and config.adjacent_turns_acquisition_enabled
            else "UNAVAILABLE_AS_ACQUISITION"
            if adjacency_method
            else "UNAVAILABLE"
        ),
        reason=(
            "READY"
            if adjacency_method and config.adjacent_turns_acquisition_enabled
            else "CONTEXT_ONLY_IMPLEMENTATION"
            if adjacency_method
            else "REPOSITORY_METHOD_UNAVAILABLE"
        ),
        limits={"max_items": policy.max_hydrated_items},
    )
    episode_method = callable(getattr(repository, "hydrate_evidence_episode", None))
    episode = _capability(
        "SAME_EPISODE",
        kind="EXPANSION",
        status=(
            "ENABLED"
            if episode_method and config.same_episode_acquisition_enabled
            else "UNAVAILABLE"
        ),
        reason=(
            "READY"
            if episode_method and config.same_episode_acquisition_enabled
            else "NOT_IMPLEMENTED"
        ),
        limits={"max_items": policy.max_hydrated_items},
    )
    channels: dict[str, AcquisitionCapability] = {
        str(item.name): item for item in (raw, enriched, dense, source_range, event, canonical)
    }
    expansions: dict[str, AcquisitionCapability] = {
        str(item.name): item for item in (adjacency, episode)
    }
    material: dict[str, Any] = {
        "schema_version": "acquisition-capability-set-v0.1",
        "config_digest": config_digest,
        "projection_snapshot_digest": projection_digest,
        "policy_digest": policy_digest,
        "channels": {key: value.model_dump(mode="json") for key, value in channels.items()},
        "expansions": {key: value.model_dump(mode="json") for key, value in expansions.items()},
    }
    return AcquisitionCapabilitySet(
        capability_digest=canonical_sha256(material),
        config_digest=config_digest,
        projection_snapshot_digest=projection_digest,
        policy_digest=policy_digest,
        generated_at=generated_at,
        channels=channels,
        expansions=expansions,
    )


def feasible_acquisition_actions(
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
    *,
    source_observed_range: Mapping[str, object] | None = None,
    event_occurrence_range: Mapping[str, object] | None = None,
    valid_anchor_available: bool = False,
    remaining_candidates: int | None = None,
    acquisition_plan: AcquisitionPlan | None = None,
    candidate_caps_by_channel: Mapping[AcquisitionCapabilityName, int] | None = None,
) -> list[FeasibleAcquisitionAction]:
    """Intersect capability, policy, requirement applicability, scope, and budget."""

    policy_digest = canonical_sha256(policy.model_dump(mode="json"))
    if capability_set.policy_digest != policy_digest:
        return []
    allowed = set(policy.allowed_capabilities)
    candidate_budget = min(
        policy.max_candidates,
        remaining_candidates if remaining_candidates is not None else policy.max_candidates,
    )
    if candidate_budget < 1:
        return []
    actions: list[FeasibleAcquisitionAction] = []
    for requirement in requirement_state.requirements:
        if requirement.status == "SATISFIED":
            continue
        applicable: list[AcquisitionCapabilityName] = []
        if executable_closed_open_range(source_observed_range):
            applicable.append("SOURCE_OBSERVED_RANGE_SCAN")
        if executable_closed_open_range(event_occurrence_range) and requirement.kind in {
            "EVENT_SLOT",
            "SET_MEMBERS",
            "CARDINALITY",
            "RANGE_COMPLETENESS",
        }:
            applicable.append("TEMPORAL_EVENT")
        applicable.extend(["FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"])
        if valid_anchor_available:
            applicable.append("ADJACENT_TURNS")
        for name in dict.fromkeys(applicable):
            if name not in allowed:
                continue
            if (
                acquisition_plan is not None
                and name in {"FTS_RAW", "FTS_ENRICHED", "EVIDENCE_DENSE"}
                and not any(
                    probe.channel == name
                    and probe.requirement_slot in {None, requirement.requirement_id}
                    for probe in acquisition_plan.probes
                )
            ):
                continue
            capability = _lookup_capability(capability_set, name)
            if capability is None or not capability.executable:
                continue
            if capability.status == "CONDITIONAL" and name == "SOURCE_OBSERVED_RANGE_SCAN":
                if not executable_closed_open_range(source_observed_range):
                    continue
            channel_candidate_budget = candidate_budget
            if candidate_caps_by_channel is not None and name in candidate_caps_by_channel:
                requested_cap = candidate_caps_by_channel[name]
                if (
                    isinstance(requested_cap, bool)
                    or not isinstance(requested_cap, int)
                    or requested_cap < 1
                    or requested_cap > candidate_budget
                ):
                    raise ValueError("INVALID_CHANNEL_CANDIDATE_CAP")
                channel_candidate_budget = requested_cap
            bounded_cost = {
                "acquisition_passes": 1,
                "candidate_count": channel_candidate_budget,
                "model_calls": 0,
            }
            payload = {
                "schema_version": "feasible-acquisition-action-v0.1",
                "capability_id": capability.capability_id,
                "capability_digest": capability_set.capability_digest,
                "target_requirement_id": requirement.requirement_id,
                "requirement_state_digest": requirement_state.state_digest,
                "requirement_state_epoch": requirement_state.state_epoch,
                "policy_digest": policy_digest,
                "channel": name,
                "bounded_cost": bounded_cost,
            }
            actions.append(
                FeasibleAcquisitionAction(
                    action_digest=canonical_sha256(payload),
                    capability_id=capability.capability_id,
                    capability_digest=capability_set.capability_digest,
                    target_requirement_id=requirement.requirement_id,
                    requirement_state_digest=requirement_state.state_digest,
                    requirement_state_epoch=requirement_state.state_epoch,
                    policy_digest=policy_digest,
                    channel=name,
                    bounded_cost=bounded_cost,
                )
            )
    return sorted(
        actions,
        key=lambda item: (item.target_requirement_id, item.channel, item.action_digest),
    )


def validate_feasible_action(
    action: FeasibleAcquisitionAction,
    requirement_state: RequirementState,
    capability_set: AcquisitionCapabilitySet,
    policy: AcquisitionCapabilityPolicy,
) -> FeasibleActionValidation:
    if (
        action.requirement_state_digest != requirement_state.state_digest
        or action.requirement_state_epoch != requirement_state.state_epoch
    ):
        return FeasibleActionValidation(accepted=False, reason_code="STALE_REQUIREMENT_STATE")
    if action.capability_digest != capability_set.capability_digest:
        return FeasibleActionValidation(
            accepted=False, reason_code="ACQUISITION_CAPABILITY_DIGEST_MISMATCH"
        )
    policy_digest = canonical_sha256(policy.model_dump(mode="json"))
    if action.policy_digest != policy_digest or capability_set.policy_digest != policy_digest:
        return FeasibleActionValidation(accepted=False, reason_code="POLICY_DIGEST_MISMATCH")
    target = next(
        (
            item
            for item in requirement_state.requirements
            if item.requirement_id == action.target_requirement_id
        ),
        None,
    )
    if target is None:
        return FeasibleActionValidation(accepted=False, reason_code="REQUIREMENT_UNKNOWN")
    if target.status == "SATISFIED":
        return FeasibleActionValidation(
            accepted=False, reason_code="SATISFIED_REQUIREMENT_NOT_TARGETABLE"
        )
    capability = _lookup_capability(capability_set, action.channel)
    if capability is None or capability.capability_id != action.capability_id:
        return FeasibleActionValidation(accepted=False, reason_code="CAPABILITY_UNKNOWN")
    if not capability.executable:
        return FeasibleActionValidation(accepted=False, reason_code=capability.reason)
    if action.channel not in set(policy.allowed_capabilities):
        return FeasibleActionValidation(accepted=False, reason_code="POLICY_DISALLOWED")
    if action.bounded_cost.get("acquisition_passes") != 1:
        return FeasibleActionValidation(accepted=False, reason_code="ACTION_PASS_BUDGET_INVALID")
    candidate_count = action.bounded_cost.get("candidate_count")
    if candidate_count is None or not 1 <= candidate_count <= policy.max_candidates:
        return FeasibleActionValidation(
            accepted=False, reason_code="ACTION_CANDIDATE_BUDGET_INVALID"
        )
    if action.bounded_cost.get("model_calls") != 0:
        return FeasibleActionValidation(accepted=False, reason_code="ACTION_MODEL_BUDGET_INVALID")
    return FeasibleActionValidation(accepted=True, reason_code="ACTION_FEASIBLE")


def _capability(
    name: AcquisitionCapabilityName,
    *,
    status: str,
    reason: str,
    kind: Literal["CHANNEL", "EXPANSION"] = "CHANNEL",
    limits: Mapping[str, Any] | None = None,
    requirements: Mapping[str, Any] | None = None,
) -> AcquisitionCapability:
    return AcquisitionCapability(
        capability_id=f"{kind.casefold()}:{name}",
        name=name,
        capability_kind=kind,
        status=status,  # type: ignore[arg-type]
        reason=reason,
        limits=dict(limits or {}),
        requirements=dict(requirements or {}),
    )


def _lookup_capability(
    capability_set: AcquisitionCapabilitySet, name: AcquisitionCapabilityName
) -> AcquisitionCapability | None:
    return capability_set.channels.get(name) or capability_set.expansions.get(name)


def _projection_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    fields = (
        "canonical_snapshot_outbox_sequence",
        "fts_watermark",
        "vector_watermark",
        "fts_dead_letter",
        "vector_dead_letter",
        "evidence_watermark",
        "evidence_dead_letter",
    )
    return {name: getattr(value, name) for name in fields if hasattr(value, name)}


def _bounded_range(value: Mapping[str, object] | None) -> bool:
    return bool(
        value is not None
        and value.get("start") is not None
        and value.get("end") is not None
        and value.get("boundary") != "UNBOUNDED"
    )


def executable_closed_open_range(value: Mapping[str, object] | None) -> bool:
    """Return whether a repository closed-open range can be executed exactly."""

    if value is None or value.get("boundary") != "CLOSED_OPEN":
        return False
    raw_start, raw_end = value.get("start"), value.get("end")
    if not isinstance(raw_start, str) or not isinstance(raw_end, str):
        return False
    try:
        start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
    except ValueError:
        return False
    return bool(
        start.tzinfo is not None
        and start.utcoffset() is not None
        and end.tzinfo is not None
        and end.utcoffset() is not None
        and start < end
    )


__all__ = [
    "AcquisitionCapabilityPolicy",
    "AcquisitionRuntimeCapabilityConfig",
    "FeasibleActionValidation",
    "executable_closed_open_range",
    "feasible_acquisition_actions",
    "resolve_acquisition_capabilities",
    "validate_feasible_action",
]
