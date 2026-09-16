"""Typed noncanonical contracts for MD-02 boundary and product shadow work."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import canonical_sha256

BoundaryDecisionV02 = Literal["CONTINUE", "SPLIT"]
ShadowFreshnessStatus = Literal["CURRENT", "STALE", "INELIGIBLE"]
ShadowDisposition = Literal[
    "OBSERVED",
    "STALE_REJECTED",
    "PERMISSION_REJECTED",
    "RAW_FALLBACK",
]


class BoundaryContinuationSignalsV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dialogue_pair_continuity: bool
    correction_or_update_relation: bool
    entity_continuity: bool
    event_or_state_continuity: bool
    lexical_cohesion: bool


class BoundarySplitSignalsV02(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_change: bool
    explicit_topic_shift: bool
    subject_or_event_change: bool
    incompatible_predicate_context: bool
    time_gap_without_continuity: bool


class BoundaryEvidenceV02(BaseModel):
    """Query-independent evidence for one deterministic episode boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["boundary-evidence-v0.2"] = "boundary-evidence-v0.2"
    boundary_evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_episode_source_ids: list[str] = Field(min_length=1, max_length=256)
    current_source_id: str = Field(min_length=1)
    continuation_signals: BoundaryContinuationSignalsV02
    split_signals: BoundarySplitSignalsV02
    decision: BoundaryDecisionV02
    reason_code: str = Field(min_length=1, max_length=160)
    producer_identity: str = Field(min_length=1, max_length=160)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.previous_episode_source_ids != list(
            dict.fromkeys(self.previous_episode_source_ids)
        ):
            raise ValueError("previous episode source IDs must be unique and ordered")
        if self.current_source_id in self.previous_episode_source_ids:
            raise ValueError("current source cannot already belong to previous episode")
        if self.decision == "CONTINUE" and not any(
            self.continuation_signals.model_dump().values()
        ):
            raise ValueError("continuation requires at least one grounded signal")
        if self.decision == "SPLIT" and not any(self.split_signals.model_dump().values()):
            raise ValueError("split requires at least one grounded signal")
        material = self.model_dump(mode="json", exclude={"boundary_evidence_digest"})
        if self.boundary_evidence_digest != canonical_sha256(material):
            raise ValueError("boundary evidence digest mismatch")
        return self


class SemanticEpisodeShadowObservationV01(BaseModel):
    """Observation-only trace that cannot alter official read behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["semantic-episode-shadow-observation-v0.1"] = (
        "semantic-episode-shadow-observation-v0.1"
    )
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_identity: str = Field(min_length=1, max_length=256)
    baseline_behavior_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_watermark: datetime
    bundle_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    episode_digests: list[str] = Field(default_factory=list, max_length=256)
    raw_anchor_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    shadow_context_evidence_ids: list[str] = Field(default_factory=list, max_length=1024)
    freshness_status: ShadowFreshnessStatus
    disposition: ShadowDisposition
    rejection_reason: str | None = Field(default=None, max_length=160)
    raw_fallback_used: bool
    additional_official_acquisition_calls: Literal[0] = 0
    additional_reader_calls: Literal[0] = 0
    additional_provider_calls: Literal[0] = 0
    additional_model_calls: Literal[0] = 0
    database_writes: Literal[0] = 0
    canonical_mutations: Literal[0] = 0
    default_feature_flag: Literal["OFF"] = "OFF"
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.source_watermark.tzinfo is None or self.source_watermark.utcoffset() is None:
            raise ValueError("shadow source watermark must be timezone-aware")
        if self.episode_digests != list(dict.fromkeys(self.episode_digests)):
            raise ValueError("shadow episode digests must be unique and ordered")
        if self.shadow_context_evidence_ids != list(
            dict.fromkeys(self.shadow_context_evidence_ids)
        ):
            raise ValueError("shadow context Evidence IDs must be unique and ordered")
        if self.disposition == "OBSERVED":
            if self.freshness_status != "CURRENT" or self.bundle_digest is None:
                raise ValueError("observed shadow requires one current bundle")
            if self.raw_fallback_used:
                raise ValueError("current observed shadow cannot claim Raw fallback")
        elif not self.raw_fallback_used:
            raise ValueError("unusable shadow must continue through Raw fallback")
        material = self.model_dump(mode="json", exclude={"observation_digest"})
        if self.observation_digest != canonical_sha256(material):
            raise ValueError("shadow observation digest mismatch")
        return self


__all__ = [
    "BoundaryContinuationSignalsV02",
    "BoundaryDecisionV02",
    "BoundaryEvidenceV02",
    "BoundarySplitSignalsV02",
    "SemanticEpisodeShadowObservationV01",
    "ShadowDisposition",
    "ShadowFreshnessStatus",
]
