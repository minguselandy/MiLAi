"""Raw-preserving, noncanonical event-identity sidecar contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import canonical_sha256


class FormationEventIdentityClusterV01(BaseModel):
    """One query-local identity hypothesis over source-grounded Evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-event-identity-cluster-v0.1"] = (
        "formation-event-identity-cluster-v0.1"
    )
    cluster_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_id: str = Field(min_length=1, max_length=128)
    identity_key: str = Field(min_length=1)
    representative_evidence_id: str = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    interpretation_ids: list[str] = Field(min_length=1)
    occurrence_time_key: str | None = None
    identity_policy_version: Literal["formation-event-identity-v0.1"] = (
        "formation-event-identity-v0.1"
    )
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        for values in (self.source_evidence_ids, self.interpretation_ids):
            if values != sorted(set(values)):
                raise ValueError("formation identity references must be sorted and unique")
        if self.representative_evidence_id not in self.source_evidence_ids:
            raise ValueError("identity representative must be one of its source Evidence")
        material = self.model_dump(mode="json", exclude={"cluster_digest"})
        if self.cluster_digest != canonical_sha256(material):
            raise ValueError("formation event identity digest mismatch")
        return self


class FormationEventIdentitySidecarV01(BaseModel):
    """Rebuildable identity projection; never Canonical State."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["formation-event-identity-sidecar-v0.1"] = (
        "formation-event-identity-sidecar-v0.1"
    )
    sidecar_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    clusters: list[FormationEventIdentityClusterV01] = Field(default_factory=list)
    duplicate_evidence_count: int = Field(ge=0)
    unresolved_interpretation_ids: list[str] = Field(default_factory=list)
    persisted: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_sidecar(self) -> Self:
        if self.clusters != sorted(
            self.clusters,
            key=lambda item: (item.requirement_id, item.identity_key),
        ):
            raise ValueError("formation identity clusters must be ordered")
        if self.unresolved_interpretation_ids != sorted(
            set(self.unresolved_interpretation_ids)
        ):
            raise ValueError("unresolved identity references must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"sidecar_digest"})
        if self.sidecar_digest != canonical_sha256(material):
            raise ValueError("formation event identity sidecar digest mismatch")
        return self


__all__ = [
    "FormationEventIdentityClusterV01",
    "FormationEventIdentitySidecarV01",
]
