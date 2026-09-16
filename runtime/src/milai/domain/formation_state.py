"""Raw-preserving, noncanonical state/change Formation contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import InterpretationEventTime


class FormationStateAssertionV01(BaseModel):
    """A source-grounded state hypothesis, never a Canonical Claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-state-assertion-v0.1"] = (
        "formation-state-assertion-v0.1"
    )
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    span: FormationSourceSpanV01
    subject_identity: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    value: JsonValue
    modality: Literal["ASSERTED", "PREFERENCE", "INTENT", "TEMPORARY"]
    valid_time: InterpretationEventTime | None = None
    producer_identity: str = Field(min_length=1)
    promotion_disposition: Literal["QUERY_LOCAL_ONLY", "GOVERNED_REVIEW_REQUIRED"]
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        material = self.model_dump(mode="json", exclude={"artifact_digest"})
        if self.artifact_digest != canonical_sha256(material):
            raise ValueError("formation state assertion digest mismatch")
        return self


class FormationStateTransitionV01(BaseModel):
    """A source-grounded change hypothesis requiring governed promotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-state-transition-v0.1"] = (
        "formation-state-transition-v0.1"
    )
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    span: FormationSourceSpanV01
    subject_identity: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    relation: Literal[
        "ESTABLISHES",
        "UPDATES",
        "CORRECTS",
        "REVOKES",
        "TEMPORARILY_CONSTRAINS",
    ]
    previous_value: JsonValue | None = None
    new_value: JsonValue | None = None
    resulting_assertion_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid_time: InterpretationEventTime | None = None
    producer_identity: str = Field(min_length=1)
    promotion_disposition: Literal["GOVERNED_REVIEW_REQUIRED"] = (
        "GOVERNED_REVIEW_REQUIRED"
    )
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        material = self.model_dump(mode="json", exclude={"artifact_digest"})
        if self.artifact_digest != canonical_sha256(material):
            raise ValueError("formation state transition digest mismatch")
        return self


class FormationStateChangeSidecarV01(BaseModel):
    """Rebuildable state/change artifacts over one Raw Evidence snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-state-change-sidecar-v0.1"] = (
        "formation-state-change-sidecar-v0.1"
    )
    sidecar_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertions: list[FormationStateAssertionV01] = Field(default_factory=list)
    transitions: list[FormationStateTransitionV01] = Field(default_factory=list)
    producer_identities: list[str] = Field(default_factory=list)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_sidecar(self) -> Self:
        if self.assertions != sorted(
            self.assertions,
            key=lambda item: (item.span.source_ref, item.span.start, item.predicate),
        ):
            raise ValueError("formation assertions must be ordered")
        if self.transitions != sorted(
            self.transitions,
            key=lambda item: (item.span.source_ref, item.span.start, item.relation),
        ):
            raise ValueError("formation transitions must be ordered")
        if self.producer_identities != sorted(set(self.producer_identities)):
            raise ValueError("formation state producers must be unique and ordered")
        material = self.model_dump(mode="json", exclude={"sidecar_digest"})
        if self.sidecar_digest != canonical_sha256(material):
            raise ValueError("formation state sidecar digest mismatch")
        return self


__all__ = [
    "FormationStateAssertionV01",
    "FormationStateChangeSidecarV01",
    "FormationStateTransitionV01",
]
