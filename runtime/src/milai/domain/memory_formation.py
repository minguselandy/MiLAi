"""Typed, raw-preserving contracts for query-independent Memory Formation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationSourceSpanV01,
)
from milai.domain.formation_state import FormationStateChangeSidecarV01
from milai.domain.requirement_state import canonical_sha256

EpisodeBoundaryReason = Literal[
    "CONVERSATION_START",
    "SESSION_CHANGE",
    "TIME_GAP",
    "EXPLICIT_TOPIC_SHIFT",
    "SEMANTIC_TOPIC_SHIFT",
]
ParticipantRole = Literal["user", "assistant"]


class SemanticEpisodeCandidateV01(BaseModel):
    """A noncanonical context projection over complete Raw Evidence turns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["semantic-episode-candidate-v0.1"] = "semantic-episode-candidate-v0.1"
    episode_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_spans: list[FormationSourceSpanV01] = Field(min_length=1, max_length=256)
    participant_roles: list[ParticipantRole] = Field(min_length=1, max_length=256)
    topic_terms: list[str] = Field(default_factory=list, max_length=64)
    boundary_reason: EpisodeBoundaryReason
    source_time_start: datetime
    source_time_end: datetime
    producer_identity: str = Field(min_length=1, max_length=160)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        if len(self.source_spans) != len(self.participant_roles):
            raise ValueError("episode roles must align one-to-one with source spans")
        evidence_ids = [item.evidence_id for item in self.source_spans]
        source_refs = [item.source_ref for item in self.source_spans]
        if len(evidence_ids) != len(set(evidence_ids)) or len(source_refs) != len(set(source_refs)):
            raise ValueError("episode source turns must be unique")
        if any(item.start != 0 or item.end != len(item.text) for item in self.source_spans):
            raise ValueError("episode spans must preserve each complete Raw Evidence turn")
        if self.topic_terms != sorted(set(self.topic_terms)):
            raise ValueError("episode topic terms must be sorted and unique")
        if not _aware(self.source_time_start) or not _aware(self.source_time_end):
            raise ValueError("episode source times must be timezone-aware")
        if self.source_time_end < self.source_time_start:
            raise ValueError("episode source time range is inverted")
        material = self.model_dump(mode="json", exclude={"episode_digest"})
        if self.episode_digest != canonical_sha256(material):
            raise ValueError("semantic episode digest mismatch")
        return self


class MemoryFormationBundleV01(BaseModel):
    """One complete, rebuildable Formation snapshot with a mandatory Raw fallback."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["memory-formation-bundle-v0.1"] = "memory-formation-bundle-v0.1"
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_ids: list[str] = Field(min_length=1, max_length=1024)
    source_watermark: datetime
    coverage_status: Literal["COMPLETE"] = "COMPLETE"
    episode_candidates: list[SemanticEpisodeCandidateV01] = Field(min_length=1, max_length=256)
    semantic_sidecar: FormationArtifactSidecarV01
    state_change_sidecar: FormationStateChangeSidecarV01
    raw_fallback_required: Literal[True] = True
    producer_identity: str = Field(min_length=1, max_length=160)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if not _aware(self.source_watermark):
            raise ValueError("Formation source watermark must be timezone-aware")
        flattened = [
            span.evidence_id for episode in self.episode_candidates for span in episode.source_spans
        ]
        if flattened != self.source_evidence_ids:
            raise ValueError("Formation episodes must preserve source Evidence order")
        if len(flattened) != len(set(flattened)):
            raise ValueError("Formation source Evidence must be covered exactly once")
        episode_digests = [item.episode_digest for item in self.episode_candidates]
        if len(episode_digests) != len(set(episode_digests)):
            raise ValueError("Formation episodes must have unique identities")

        source_roles = {
            span.evidence_id: role
            for episode in self.episode_candidates
            for span, role in zip(episode.source_spans, episode.participant_roles, strict=True)
        }
        artifact_sources = _artifact_source_ids(self.semantic_sidecar, self.state_change_sidecar)
        if not artifact_sources.issubset(set(self.source_evidence_ids)):
            raise ValueError("Formation sub-artifact lineage escapes the source snapshot")
        if any(source_roles[evidence_id] != "user" for evidence_id in artifact_sources):
            raise ValueError("assistant Evidence cannot form user semantic/state artifacts")

        material = self.model_dump(mode="json", exclude={"bundle_digest"})
        if self.bundle_digest != canonical_sha256(material):
            raise ValueError("Memory Formation bundle digest mismatch")
        return self


class MemoryFormationReceiptV01(BaseModel):
    """Deterministic noncanonical receipt for one in-memory Formation build."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["memory-formation-receipt-v0.1"] = "memory-formation-receipt-v0.1"
    receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_watermark: datetime
    source_evidence_ids: list[str] = Field(min_length=1, max_length=1024)
    episode_digests: list[str] = Field(min_length=1, max_length=256)
    semantic_sidecar_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_change_sidecar_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_status: Literal["COMPLETE"] = "COMPLETE"
    raw_fallback_required: Literal[True] = True
    provider_calls: Literal[0] = 0
    reader_calls: Literal[0] = 0
    retrieval_calls: Literal[0] = 0
    database_calls: Literal[0] = 0
    canonical_mutations: Literal[0] = 0
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if not _aware(self.source_watermark):
            raise ValueError("Formation receipt watermark must be timezone-aware")
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("Formation receipt Evidence references must be unique")
        if len(self.episode_digests) != len(set(self.episode_digests)):
            raise ValueError("Formation receipt episode references must be unique")
        material = self.model_dump(mode="json", exclude={"receipt_digest"})
        if self.receipt_digest != canonical_sha256(material):
            raise ValueError("Memory Formation receipt digest mismatch")
        return self


def _artifact_source_ids(
    semantic: FormationArtifactSidecarV01,
    state: FormationStateChangeSidecarV01,
) -> set[str]:
    return {
        *[item.span.evidence_id for item in semantic.entity_candidates],
        *[item.span.evidence_id for item in semantic.event_candidates],
        *[
            anchor.evidence_id
            for item in semantic.event_candidates
            for anchor in item.temporal_anchor_spans
        ],
        *[item.span.evidence_id for item in state.assertions],
        *[item.span.evidence_id for item in state.transitions],
    }


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = [
    "EpisodeBoundaryReason",
    "MemoryFormationBundleV01",
    "MemoryFormationReceiptV01",
    "ParticipantRole",
    "SemanticEpisodeCandidateV01",
]
