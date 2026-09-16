"""Requirement-aligned, label-free acquisition observation contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.acquisition_capability import AcquisitionCapabilityName
from milai.domain.requirement_state import (
    RequirementDispositionStatus,
    RequirementKind,
    canonical_sha256,
)

AcquisitionFirstLossReason = Literal[
    "COMPLETENESS_PROOF_MISSING",
    "BINDING_POSSIBLE_SEMANTICS_OWNER",
    "CANDIDATES_WITHOUT_COMPATIBLE_BINDING",
    # Retained so previously sealed v0.2 observations remain readable.
    "BINDING_REJECTED_OR_POSSIBLE",
    "CANDIDATES_WITHOUT_ACCEPTED_BINDING",
    "CHANNEL_RETRIEVAL_BOUND_MISS",
    "CAPABILITY_UNAVAILABLE_OR_NOT_RUN",
]


class AcquisitionAttemptObservationV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: str = Field(min_length=1, max_length=160)
    channel: AcquisitionCapabilityName
    status: str = Field(min_length=1, max_length=160)
    reason_code: str = Field(min_length=1, max_length=160)
    raw_candidate_count: int = Field(ge=0)
    selected_candidate_count: int = Field(ge=0)


class AvailableAcquisitionActionV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: AcquisitionCapabilityName


class RequirementAcquisitionObservationV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    kind: RequirementKind
    status: RequirementDispositionStatus
    first_loss_reason: AcquisitionFirstLossReason
    matched_evidence_refs: list[str] = Field(default_factory=list)
    possible_binding_refs: list[str] = Field(default_factory=list)
    rejected_candidate_refs: list[str] = Field(default_factory=list)
    rejection_summary: dict[str, int] = Field(default_factory=dict)
    acquisition_history: list[AcquisitionAttemptObservationV02] = Field(default_factory=list)
    available_actions: list[AvailableAcquisitionActionV02] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_views(self) -> Self:
        for values in (
            self.matched_evidence_refs,
            self.possible_binding_refs,
            self.rejected_candidate_refs,
        ):
            if values != sorted(set(values)):
                raise ValueError("acquisition observation views must be sorted and unique")
        action_ids = [item.action_digest for item in self.available_actions]
        if action_ids != sorted(set(action_ids)):
            raise ValueError("available actions must be deterministically ordered")
        return self


class AcquisitionObservationGlobalV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seen_region_digests: list[str] = Field(default_factory=list)
    exhausted_region_digests: list[str] = Field(default_factory=list)
    repeated_region_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    valid_adjacency_anchor_count: int = Field(default=0, ge=0, le=2)
    remaining_budget: dict[str, int]

    @model_validator(mode="after")
    def validate_global(self) -> Self:
        for values in (self.seen_region_digests, self.exhausted_region_digests):
            if values != sorted(set(values)):
                raise ValueError("observation region digests must be sorted and unique")
            if any(len(value) != 64 for value in values):
                raise ValueError("observation regions require SHA-256 identities")
        if not set(self.exhausted_region_digests).issubset(self.seen_region_digests):
            raise ValueError("an exhausted observation region must have been seen")
        if not self.remaining_budget or any(
            isinstance(value, bool) or value < 0 for value in self.remaining_budget.values()
        ):
            raise ValueError("acquisition observation requires non-negative bounded budget")
        return self


class AcquisitionObservationV02(BaseModel):
    """One immutable product observation over one RequirementState epoch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["acquisition-observation-v0.2"] = "acquisition-observation-v0.2"
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_epoch: int = Field(ge=0)
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: list[RequirementAcquisitionObservationV02] = Field(
        default_factory=list, max_length=16
    )
    global_observation: AcquisitionObservationGlobalV02
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        requirement_ids = [item.requirement_id for item in self.requirements]
        if requirement_ids != sorted(set(requirement_ids)):
            raise ValueError("observation requirements must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"observation_digest"})
        if self.observation_digest != canonical_sha256(material):
            raise ValueError("acquisition observation digest does not match its fields")
        return self


__all__ = [
    "AcquisitionAttemptObservationV02",
    "AcquisitionFirstLossReason",
    "AcquisitionObservationGlobalV02",
    "AcquisitionObservationV02",
    "AvailableAcquisitionActionV02",
    "RequirementAcquisitionObservationV02",
]
