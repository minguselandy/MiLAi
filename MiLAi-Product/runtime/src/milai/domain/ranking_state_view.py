"""Permission-trimmed semantic view for fixed-pool candidate ranking.

The view is derived, query-local, and non-authoritative.  Identity fields bind
the view to Runtime state but are deliberately absent from model text.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import (
    RequirementCardinalityState,
    RequirementDispositionStatus,
    RequirementKind,
    RequirementProofStatus,
    RequirementState,
    canonical_sha256,
)


class RankingStateViewV01(BaseModel):
    """One immutable semantic projection of one Requirement disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "ranking-state-view-v0.1"
    query_operator: str = Field(min_length=1, max_length=80)
    target_requirement_id: str = Field(min_length=1, max_length=128)
    target_requirement_kind: RequirementKind
    target_requirement_status: RequirementDispositionStatus
    missing_evidence_roles: list[str] = Field(default_factory=list, max_length=16)
    required_cardinality: RequirementCardinalityState
    observed_cardinality: int = Field(ge=0)
    proof_status: RequirementProofStatus
    rejection_summary: dict[str, int] = Field(default_factory=dict)
    permission_trimmed_anchors: list[str] = Field(default_factory=list, max_length=32)
    selection_cutoff_k: int = Field(ge=1, le=256)

    state_epoch: int = Field(ge=0)
    requirement_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_pool_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical: bool = False
    canonical_mutation: bool = False

    @model_validator(mode="after")
    def validate_view(self) -> Self:
        for values, label in (
            (self.missing_evidence_roles, "missing evidence roles"),
            (self.permission_trimmed_anchors, "permission-trimmed anchors"),
        ):
            if values != sorted(set(values)) or any(not value for value in values):
                raise ValueError(f"{label} must be non-empty, sorted, and unique")
        if list(self.rejection_summary) != sorted(self.rejection_summary):
            raise ValueError("rejection summary keys must be sorted")
        if any(value <= 0 for value in self.rejection_summary.values()):
            raise ValueError("rejection summary counts must be positive")
        if self.canonical or self.canonical_mutation:
            raise ValueError("RankingStateView cannot be canonical or mutate Canonical state")
        material = self.model_dump(mode="json", exclude={"view_digest"})
        if self.view_digest != canonical_sha256(material):
            raise ValueError("RankingStateView digest does not match its fields")
        return self

    def semantic_material(self) -> dict[str, object]:
        """Return only fields authorized for model-visible serialization."""

        return {
            "query_operator": self.query_operator,
            "target_requirement_id": self.target_requirement_id,
            "target_requirement_kind": self.target_requirement_kind,
            "target_requirement_status": self.target_requirement_status,
            "missing_evidence_roles": list(self.missing_evidence_roles),
            "required_cardinality": self.required_cardinality.model_dump(mode="json"),
            "observed_cardinality": self.observed_cardinality,
            "proof_status": self.proof_status,
            "rejection_summary": dict(self.rejection_summary),
            "permission_trimmed_anchors": list(self.permission_trimmed_anchors),
            "selection_cutoff_k": self.selection_cutoff_k,
        }

    def render(self, query: str, *, shuffled: bool = False) -> str:
        """Render the frozen DG-26 correct or within-view shuffled template."""

        if not query:
            raise ValueError("ranking query must be non-empty")
        missing = _list_value(self.missing_evidence_roles)
        anchors = _list_value(self.permission_trimmed_anchors)
        cardinality = _cardinality_value(self.required_cardinality)
        observed = str(self.observed_cardinality)
        operator: str = self.query_operator
        kind: str = self.target_requirement_kind
        status: str = self.target_requirement_status
        proof: str = self.proof_status
        if shuffled:
            operator, kind = kind, operator
            status, proof = proof, status
            missing, anchors = anchors, missing
            cardinality, observed = observed, cardinality
        return "\n".join(
            (
                f"query={query}",
                "[ranking_state_view_v0.1]",
                f"operator={operator}",
                f"target_requirement_id={self.target_requirement_id}",
                f"target_requirement_kind={kind}",
                f"target_requirement_status={status}",
                f"missing_evidence_roles={missing}",
                f"required_cardinality={cardinality}",
                f"observed_cardinality={observed}",
                f"proof_status={proof}",
                f"rejection_summary={_summary_value(self.rejection_summary)}",
                f"permission_trimmed_anchors={anchors}",
                f"selection_cutoff_k={self.selection_cutoff_k}",
            )
        )


def build_ranking_state_view(
    *,
    requirement_state: RequirementState,
    requirement_id: str,
    query_operator: str | None,
    permission_trimmed_anchors: list[str],
    candidate_pool_digest: str,
    selection_cutoff_k: int,
) -> RankingStateViewV01:
    """Project one validated RequirementState disposition into a model view."""

    disposition = next(
        (
            item
            for item in requirement_state.requirements
            if item.requirement_id == requirement_id
        ),
        None,
    )
    if disposition is None:
        raise ValueError("RankingStateView target requirement is absent")
    material: dict[str, object] = {
        "schema_version": "ranking-state-view-v0.1",
        "query_operator": query_operator or "UNSPECIFIED",
        "target_requirement_id": requirement_id,
        "target_requirement_kind": disposition.kind,
        "target_requirement_status": disposition.status,
        "missing_evidence_roles": (
            [] if disposition.status == "SATISFIED" else [requirement_id]
        ),
        "required_cardinality": disposition.required_cardinality.model_dump(mode="json"),
        "observed_cardinality": disposition.observed_cardinality,
        "proof_status": disposition.proof_status,
        "rejection_summary": dict(sorted(disposition.rejection_summary.items())),
        "permission_trimmed_anchors": sorted(set(permission_trimmed_anchors)),
        "selection_cutoff_k": selection_cutoff_k,
        "state_epoch": requirement_state.state_epoch,
        "requirement_state_digest": requirement_state.state_digest,
        "candidate_pool_digest": candidate_pool_digest,
        "canonical": False,
        "canonical_mutation": False,
    }
    return RankingStateViewV01.model_validate(
        {**material, "view_digest": canonical_sha256(material)}
    )


def _list_value(values: list[str]) -> str:
    return ",".join(values) if values else "NONE"


def _cardinality_value(value: RequirementCardinalityState) -> str:
    maximum = str(value.maximum) if value.maximum is not None else "UNBOUNDED"
    return f"{value.minimum}:{maximum}:{str(value.distinct).lower()}"


def _summary_value(value: dict[str, int]) -> str:
    return ",".join(f"{key}={count}" for key, count in value.items()) or "NONE"


__all__ = ["RankingStateViewV01", "build_ranking_state_view"]
