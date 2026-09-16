"""Typed query-local retrieval capability and feasible-action contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.requirement_state import canonical_sha256

AcquisitionCapabilityName = Literal[
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
    "CANONICAL_STATE",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
]
AcquisitionCapabilityStatus = Literal[
    "ENABLED",
    "CONDITIONAL",
    "DISABLED",
    "UNAVAILABLE",
    "UNAVAILABLE_AS_ACQUISITION",
]


class AcquisitionCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str = Field(min_length=1, max_length=160)
    name: AcquisitionCapabilityName
    capability_kind: Literal["CHANNEL", "EXPANSION"]
    status: AcquisitionCapabilityStatus
    reason: str = Field(min_length=1, max_length=160)
    limits: dict[str, JsonValue] = Field(default_factory=dict)
    requirements: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def executable(self) -> bool:
        return self.status in {"ENABLED", "CONDITIONAL"}

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected_kind = (
            "EXPANSION" if self.name in {"ADJACENT_TURNS", "SAME_EPISODE"} else "CHANNEL"
        )
        if self.capability_kind != expected_kind:
            raise ValueError("acquisition capability kind/name mismatch")
        if self.capability_id != f"{self.capability_kind.casefold()}:{self.name}":
            raise ValueError("acquisition capability identity mismatch")
        return self


class AcquisitionCapabilitySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["acquisition-capability-set-v0.1"] = (
        "acquisition-capability-set-v0.1"
    )
    capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    channels: dict[str, AcquisitionCapability]
    expansions: dict[str, AcquisitionCapability]

    def capability(self, name: AcquisitionCapabilityName) -> AcquisitionCapability:
        collection = (
            self.expansions
            if name in {"ADJACENT_TURNS", "SAME_EPISODE"}
            else self.channels
        )
        return collection[name]

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("capability generation time requires a timezone offset")
        expected_channels = {
            "FTS_RAW",
            "FTS_ENRICHED",
            "EVIDENCE_DENSE",
            "SOURCE_OBSERVED_RANGE_SCAN",
            "TEMPORAL_EVENT",
            "CANONICAL_STATE",
        }
        if set(self.channels) != expected_channels:
            raise ValueError("capability set must disposition every declared channel")
        if set(self.expansions) != {"ADJACENT_TURNS", "SAME_EPISODE"}:
            raise ValueError("capability set must disposition every declared expansion")
        for name, item in [*self.channels.items(), *self.expansions.items()]:
            if name != item.name:
                raise ValueError("capability map key/name mismatch")
        material = self.model_dump(
            mode="json", exclude={"capability_digest", "generated_at"}
        )
        if self.capability_digest != canonical_sha256(material):
            raise ValueError("acquisition capability digest does not match its fields")
        return self


class FeasibleAcquisitionAction(BaseModel):
    """A bounded action accepted by the recovery executor, never by a Provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["feasible-acquisition-action-v0.1"] = (
        "feasible-acquisition-action-v0.1"
    )
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_id: str = Field(min_length=1, max_length=160)
    capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_requirement_id: str = Field(min_length=1, max_length=128)
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_epoch: int = Field(ge=0)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: AcquisitionCapabilityName
    bounded_cost: dict[str, int]

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if not self.bounded_cost or any(value < 0 for value in self.bounded_cost.values()):
            raise ValueError("feasible action requires a non-negative bounded cost")
        material = self.model_dump(mode="json", exclude={"action_digest"})
        if self.action_digest != canonical_sha256(material):
            raise ValueError("feasible action digest does not match its fields")
        return self


__all__ = [
    "AcquisitionCapability",
    "AcquisitionCapabilityName",
    "AcquisitionCapabilitySet",
    "AcquisitionCapabilityStatus",
    "FeasibleAcquisitionAction",
]
