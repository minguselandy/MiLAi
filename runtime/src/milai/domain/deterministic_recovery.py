"""Typed output of the deterministic capability-constrained recovery policy."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.acquisition_capability import FeasibleAcquisitionAction
from milai.domain.requirement_state import canonical_sha256

DeterministicRecoveryReason = Literal[
    "SELECTED_TEMPORAL_EVENT",
    "SELECTED_SOURCE_RANGE_PROOF",
    "SELECTED_FTS_ENRICHED",
    "SELECTED_EVIDENCE_DENSE",
    "SELECTED_ADJACENT_TURNS",
    "SELECTED_SAME_EPISODE",
    "SELECTED_FTS_RAW_NOT_PREVIOUSLY_EXECUTED",
    "COMPLETE",
    "NO_TARGETABLE_REQUIREMENT",
    "CAPABILITY_REQUIRED_UNAVAILABLE",
    "SOURCE_POINT_BUCKET_UNPROVEN",
    "SEMANTICS_OWNER",
    "DETERMINISTIC_COMPLETE",
    "COMPLETENESS_PROOF_CHANNEL_UNAVAILABLE",
    "NO_NONREPEATED_FEASIBLE_ACTION",
    "BUDGET_EXHAUSTED",
]


class DeterministicRecoveryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deterministic-recovery-decision-v0.1"] = (
        "deterministic-recovery-decision-v0.1"
    )
    decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_epoch: int = Field(ge=0)
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: DeterministicRecoveryReason
    selected_action: FeasibleAcquisitionAction | None = None
    extra_passes_authorized: Literal[0, 1]
    provider_calls_authorized: Literal[0] = 0
    automatic_retries_authorized: Literal[0] = 0
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if (self.selected_action is None) != (self.extra_passes_authorized == 0):
            raise ValueError("selected deterministic action requires exactly one pass")
        if self.selected_action is not None and (
            self.selected_action.requirement_state_digest != self.requirement_state_digest
            or self.selected_action.requirement_state_epoch != self.requirement_state_epoch
            or self.selected_action.capability_digest != self.acquisition_capability_digest
            or self.selected_action.policy_digest != self.policy_digest
        ):
            raise ValueError("deterministic decision/action identity mismatch")
        material = self.model_dump(mode="json", exclude={"decision_digest"})
        if self.decision_digest != canonical_sha256(material):
            raise ValueError("deterministic recovery decision digest mismatch")
        return self


__all__ = ["DeterministicRecoveryDecision", "DeterministicRecoveryReason"]
