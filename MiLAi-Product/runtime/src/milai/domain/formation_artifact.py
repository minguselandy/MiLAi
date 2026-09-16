"""Raw-preserving, noncanonical Formation artifact contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import InterpretationEventTime, InterpretationTimeBasis


class FormationTemporalRelationProposalV01(BaseModel):
    """Untrusted cross-Evidence temporal relation proposed by a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: Literal["AFTER", "BEFORE", "SAME_TIME"]
    amount: int = Field(default=0, ge=0, le=366)
    unit: Literal["DAY", "WEEK", "MONTH"]
    anchor_evidence_id: str = Field(min_length=1)
    anchor_quote: str = Field(min_length=1)
    normalized_from: str = Field(min_length=1)


class FormationModelEventProposalV01(BaseModel):
    """Untrusted quote-grounded event payload; Runtime derives all offsets/time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    grounded_quote: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    primary_subject: str | None = Field(default=None, min_length=1)
    context_participants: list[str] = Field(default_factory=list, max_length=32)
    event_identity_hint: str = Field(min_length=1)
    temporal_relation: FormationTemporalRelationProposalV01 | None = None
    negated: bool = False
    confidence_feature: float | None = Field(default=None, ge=0.0, le=1.0)


class FormationSourceSpanV01(BaseModel):
    """An exact source span; it never replaces its underlying Evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("formation span offsets must exactly cover text")
        return self


class FormationEntityCandidateV01(BaseModel):
    """A rebuildable entity mention/identity hypothesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-entity-candidate-v0.1"] = (
        "formation-entity-candidate-v0.1"
    )
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    span: FormationSourceSpanV01
    identity_key: str = Field(min_length=1)
    mention_type: str = Field(min_length=1)
    producer_identity: str = Field(min_length=1)
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        material = self.model_dump(mode="json", exclude={"artifact_digest"})
        if self.artifact_digest != canonical_sha256(material):
            raise ValueError("formation entity digest mismatch")
        return self


class FormationEventCandidateV01(BaseModel):
    """A source-grounded event occurrence and temporal hypothesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-event-candidate-v0.1"] = (
        "formation-event-candidate-v0.1"
    )
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    span: FormationSourceSpanV01
    event_type: str = Field(min_length=1)
    primary_subject: str | None = Field(default=None, min_length=1)
    context_participants: list[str] = Field(default_factory=list, max_length=32)
    event_identity_key: str = Field(min_length=1)
    occurrence_time: InterpretationEventTime | None = None
    time_basis: InterpretationTimeBasis = "UNRESOLVED"
    temporal_anchor_spans: list[FormationSourceSpanV01] = Field(
        default_factory=list, max_length=4
    )
    negated: bool = False
    confidence_feature: float | None = Field(default=None, ge=0.0, le=1.0)
    producer_identity: str = Field(min_length=1)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.time_basis in {"EXPLICIT_EVENT_TIME", "INFERRED_EVENT_TIME"}:
            if self.occurrence_time is None or self.occurrence_time.start is None:
                raise ValueError("resolved formation event requires occurrence time")
        if self.time_basis in {"UNRESOLVED", "SOURCE_OBSERVED_TIME"}:
            if self.occurrence_time is not None:
                raise ValueError("unresolved/source time cannot masquerade as event time")
        if self.temporal_anchor_spans != sorted(
            self.temporal_anchor_spans,
            key=lambda item: (item.source_ref, item.start, item.end),
        ):
            raise ValueError("formation temporal anchors must be ordered")
        material = self.model_dump(mode="json", exclude={"artifact_digest"})
        if self.artifact_digest != canonical_sha256(material):
            raise ValueError("formation event digest mismatch")
        return self


class FormationArtifactSidecarV01(BaseModel):
    """A query-independent, rebuildable semantic projection over Raw Evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-artifact-sidecar-v0.1"] = (
        "formation-artifact-sidecar-v0.1"
    )
    sidecar_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_candidates: list[FormationEntityCandidateV01] = Field(default_factory=list)
    event_candidates: list[FormationEventCandidateV01] = Field(default_factory=list)
    rejected_model_outputs: list[str] = Field(default_factory=list)
    producer_identities: list[str] = Field(default_factory=list)
    model_calls: int = Field(default=0, ge=0)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_sidecar(self) -> Self:
        if self.entity_candidates != sorted(
            self.entity_candidates,
            key=lambda item: (item.span.source_ref, item.span.start, item.identity_key),
        ):
            raise ValueError("formation entities must be ordered")
        if self.event_candidates != sorted(
            self.event_candidates,
            key=lambda item: (
                item.span.source_ref,
                item.span.start,
                item.event_identity_key,
            ),
        ):
            raise ValueError("formation events must be ordered")
        if self.rejected_model_outputs != sorted(set(self.rejected_model_outputs)):
            raise ValueError("formation rejections must be sorted and unique")
        if self.producer_identities != sorted(set(self.producer_identities)):
            raise ValueError("formation producers must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"sidecar_digest"})
        if self.sidecar_digest != canonical_sha256(material):
            raise ValueError("formation sidecar digest mismatch")
        return self


__all__ = [
    "FormationArtifactSidecarV01",
    "FormationEntityCandidateV01",
    "FormationEventCandidateV01",
    "FormationModelEventProposalV01",
    "FormationSourceSpanV01",
    "FormationTemporalRelationProposalV01",
]
