"""Versioned DG-21 execution policy and selector output contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.acquisition_capability import AcquisitionCapabilityName
from milai.domain.requirement_state import canonical_sha256

AcquisitionExecutionProfileName = Literal[
    "complete_fast_path",
    "semantic_slot",
    "source_time_point",
    "event_time_point",
    "event_range_enumeration",
    "preference_local",
]
AcquisitionExecutionTerminalDisposition = Literal[
    "ACTIONABLE",
    "COMPLETE",
    "NO_TARGETABLE_REQUIREMENT",
    "CAPABILITY_REQUIRED_UNAVAILABLE",
    "SOURCE_POINT_BUCKET_UNPROVEN",
    "SEMANTICS_OWNER",
    "BUDGET_EXHAUSTED",
]


class AcquisitionExecutionGlobalGuards(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_extra_passes: Literal[1] = 1
    provider_calls: Literal[0] = 0
    automatic_retries: Literal[0] = 0
    stale_state: Literal["REJECT"] = "REJECT"
    stale_capability: Literal["REJECT"] = "REJECT"
    stale_policy: Literal["REJECT"] = "REJECT"
    exclude_seen_regions: Literal[True] = True
    formal_holdout_allowed: Literal[False] = False


class CompleteFastPathProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    acquisition_passes: Literal[0] = 0


class SemanticSlotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_candidate_cap: int = Field(default=8, ge=1, le=256)
    targeted_only: Literal[True] = True
    include_global_probe: Literal[False] = False
    dense_candidate_cap: int = Field(default=12, ge=1, le=256)
    adjacent_radius: int = Field(default=2, ge=1, le=2)
    adjacent_max_anchors: int = Field(default=2, ge=1, le=2)
    adjacent_max_items: int = Field(default=4, ge=1, le=4)


class SourceTimePointProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    require_precision: Literal["DAY"] = "DAY"
    supported_precisions: tuple[Literal["DAY", "HOUR", "MINUTE"], ...] = (
        "DAY",
        "HOUR",
        "MINUTE",
    )
    require_timezone: Literal[True] = True
    compile_to_closed_open_bucket: Literal[True] = True
    scan_max_items: int = Field(default=128, ge=1, le=2_000)


class EventTimePointProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_capability: Literal["TEMPORAL_EVENT"] = "TEMPORAL_EVENT"
    unavailable: Literal["EVENT_PROJECTION_UNAVAILABLE"] = (
        "EVENT_PROJECTION_UNAVAILABLE"
    )
    fail_fast: Literal[True] = True
    page_size: int = Field(default=64, ge=1, le=256)
    max_items: int = Field(default=256, ge=1, le=2_000)


class EventRangeEnumerationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_capability: Literal["TEMPORAL_EVENT"] = "TEMPORAL_EVENT"
    page_size: int = Field(default=64, ge=1, le=256)
    max_items: int = Field(default=2_000, ge=1, le=2_000)
    require_partition_closed: Literal[True] = True
    require_projection_watermark: Literal[True] = True
    require_deduplication_complete: Literal[True] = True
    context_pack_after_proof: Literal[True] = True
    context_evidence_cap: int = Field(default=8, ge=1, le=64)


class PreferenceLocalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    require_runtime_requirements: tuple[
        Literal["PREFERENCE_SIGNAL_SET"], Literal["CURRENT_INTENT"]
    ] = ("PREFERENCE_SIGNAL_SET", "CURRENT_INTENT")
    adjacent_radius: int = Field(default=2, ge=1, le=2)
    adjacent_max_anchors: int = Field(default=2, ge=1, le=2)
    adjacent_max_items: int = Field(default=4, ge=1, le=4)


class TypeDirectedInterpretationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_kinds_from_requirements: Literal[True] = True
    bind_type_compatible_only: Literal[True] = True
    materialize_type_mismatch: Literal[False] = False
    emit_pruned_count: Literal[True] = True
    exact_source_span_required: Literal[True] = True


class AcquisitionExecutionProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    complete_fast_path: CompleteFastPathProfile = Field(
        default_factory=CompleteFastPathProfile
    )
    semantic_slot: SemanticSlotProfile = Field(default_factory=SemanticSlotProfile)
    source_time_point: SourceTimePointProfile = Field(
        default_factory=SourceTimePointProfile
    )
    event_time_point: EventTimePointProfile = Field(
        default_factory=EventTimePointProfile
    )
    event_range_enumeration: EventRangeEnumerationProfile = Field(
        default_factory=EventRangeEnumerationProfile
    )
    preference_local: PreferenceLocalProfile = Field(
        default_factory=PreferenceLocalProfile
    )


class AcquisitionExecutionPolicy(BaseModel):
    """Digest-addressed policy; unknown versions and keys fail closed at load."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["acquisition-execution-policy-v0.2"] = (
        "acquisition-execution-policy-v0.2"
    )
    policy_version: Literal["dg21-opened-dev-v0.1"] = "dg21-opened-dev-v0.1"
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    default_enabled: Literal[False] = False
    global_guards: AcquisitionExecutionGlobalGuards = Field(
        default_factory=AcquisitionExecutionGlobalGuards
    )
    profiles: AcquisitionExecutionProfiles = Field(
        default_factory=AcquisitionExecutionProfiles
    )
    interpretation: TypeDirectedInterpretationPolicy = Field(
        default_factory=TypeDirectedInterpretationPolicy
    )

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        material = self.model_dump(mode="json", exclude={"policy_digest"})
        if self.policy_digest != canonical_sha256(material):
            raise ValueError("acquisition execution policy digest mismatch")
        return self


class AcquisitionExecutionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    acquisition_passes: int = Field(ge=0, le=1)
    candidate_count: int = Field(ge=0, le=2_000)
    hydrate_count: int = Field(ge=0, le=2_000)
    context_evidence_count: int = Field(ge=0, le=64)


class AcquisitionExecutionSelection(BaseModel):
    """Content-free selector decision bound to the exact allowed input state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["acquisition-execution-selection-v0.2"] = (
        "acquisition-execution-selection-v0.2"
    )
    selection_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=160)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selector_inputs_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_profile: AcquisitionExecutionProfileName | None = None
    target_requirement_id: str | None = Field(default=None, min_length=1, max_length=128)
    selected_channel: AcquisitionCapabilityName | None = None
    terminal_disposition: AcquisitionExecutionTerminalDisposition
    reason_code: str = Field(min_length=1, max_length=160)
    declared_budget: AcquisitionExecutionBudget
    effective_budget: AcquisitionExecutionBudget
    budget_clamp_owner: Literal["PROFILE", "REMAINING_BUDGET", "TERMINAL"]
    budget_clamp_reason: str = Field(min_length=1, max_length=160)
    targeted_only: bool
    include_global_probe: bool
    provider_calls_authorized: Literal[0] = 0
    automatic_retries_authorized: Literal[0] = 0
    formal_holdout_consumed: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.effective_budget.candidate_count > self.declared_budget.candidate_count:
            raise ValueError("effective candidate budget exceeds declared profile budget")
        if self.effective_budget.hydrate_count > self.declared_budget.hydrate_count:
            raise ValueError("effective hydration budget exceeds declared profile budget")
        if self.terminal_disposition != "ACTIONABLE" and (
            self.selected_channel is not None
            or self.effective_budget.acquisition_passes != 0
        ):
            raise ValueError("terminal selection cannot authorize acquisition work")
        material = self.model_dump(mode="json", exclude={"selection_digest"})
        if self.selection_digest != canonical_sha256(material):
            raise ValueError("acquisition execution selection digest mismatch")
        return self


__all__ = [
    "AcquisitionExecutionBudget",
    "AcquisitionExecutionGlobalGuards",
    "AcquisitionExecutionPolicy",
    "AcquisitionExecutionProfileName",
    "AcquisitionExecutionProfiles",
    "AcquisitionExecutionSelection",
    "AcquisitionExecutionTerminalDisposition",
    "CompleteFastPathProfile",
    "EventRangeEnumerationProfile",
    "EventTimePointProfile",
    "PreferenceLocalProfile",
    "SemanticSlotProfile",
    "SourceTimePointProfile",
    "TypeDirectedInterpretationPolicy",
]

