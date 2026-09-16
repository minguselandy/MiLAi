"""Query-local, digest-addressed per-requirement diagnostic state.

RequirementState is deliberately derived state.  It cannot authorize a stop,
write canonical Memory, or replace the owning SufficiencyDecision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RequirementKind = Literal[
    "VALUE_SLOT",
    "EVENT_SLOT",
    "SET_MEMBERS",
    "CARDINALITY",
    "RANGE_COMPLETENESS",
    "VERSION_CHAIN",
    "CONFLICT_SIDE",
    "PROVENANCE",
]
RequirementDispositionStatus = Literal[
    "SATISFIED",
    "MISSING",
    "UNDER_COVERED",
    "COMPLETENESS_PROOF_MISSING",
    "CONTESTED",
    "UNRESOLVED",
]
RequirementProofStatus = Literal[
    "SATISFIED",
    "NOT_REQUIRED",
    "MISSING",
    "CONTESTED",
    "UNRESOLVED",
]


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RequirementCardinalityState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: int = Field(ge=0)
    maximum: int | None = Field(default=None, ge=1)
    distinct: bool = False

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("requirement-state maximum cannot be below minimum")
        return self


class RejectedCandidateDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str = Field(min_length=1)
    binding_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1, max_length=160)


class RequirementDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    kind: RequirementKind
    status: RequirementDispositionStatus
    required_cardinality: RequirementCardinalityState
    observed_cardinality: int = Field(ge=0)
    proof_status: RequirementProofStatus
    accepted_binding_refs: list[str] = Field(default_factory=list)
    possible_binding_refs: list[str] = Field(default_factory=list)
    rejected_binding_refs: list[str] = Field(default_factory=list)
    accepted_evidence_refs: list[str] = Field(default_factory=list)
    rejected_candidates: list[RejectedCandidateDisposition] = Field(default_factory=list)
    rejection_summary: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        reference_groups = (
            self.accepted_binding_refs,
            self.possible_binding_refs,
            self.rejected_binding_refs,
            self.accepted_evidence_refs,
        )
        if any(values != sorted(set(values)) for values in reference_groups):
            raise ValueError("RequirementState references must be sorted and unique")
        rejected = sorted(
            self.rejected_candidates,
            key=lambda item: (item.candidate_ref, item.binding_ref, item.reason_code),
        )
        if self.rejected_candidates != rejected:
            raise ValueError("rejected candidates must be deterministically ordered")
        summary: dict[str, int] = {}
        for item in self.rejected_candidates:
            summary[item.reason_code] = summary.get(item.reason_code, 0) + 1
        if self.rejection_summary != dict(sorted(summary.items())):
            raise ValueError("rejection summary must be derived from rejected candidates")
        if self.observed_cardinality != len(self.accepted_evidence_refs):
            raise ValueError("observed cardinality must equal unique accepted Evidence")
        if self.status == "SATISFIED":
            if self.observed_cardinality < self.required_cardinality.minimum:
                raise ValueError("satisfied requirement is below required cardinality")
            if self.proof_status not in {"SATISFIED", "NOT_REQUIRED"}:
                raise ValueError("satisfied requirement lacks its required proof")
            if (
                self.required_cardinality.maximum is not None
                and self.observed_cardinality > self.required_cardinality.maximum
            ):
                raise ValueError("satisfied requirement exceeds maximum cardinality")
            if self.kind in {
                "SET_MEMBERS",
                "CARDINALITY",
                "RANGE_COMPLETENESS",
            } and self.possible_binding_refs:
                raise ValueError(
                    "closed-set requirement cannot be satisfied with unresolved members"
                )
        return self


class RequirementState(BaseModel):
    """One immutable view derived from a single candidate/binding/proof snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-state-v0.1"] = "requirement-state-v0.1"
    state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sufficiency_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sufficiency_policy_version: str = Field(min_length=1, max_length=160)
    state_epoch: int = Field(ge=0)
    requirements: list[RequirementDisposition] = Field(default_factory=list, max_length=16)
    lifetime: Literal["MEMORY_RESOLVE"] = "MEMORY_RESOLVE"
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @property
    def satisfied_requirement_ids(self) -> list[str]:
        return [
            item.requirement_id for item in self.requirements if item.status == "SATISFIED"
        ]

    @property
    def missing_requirement_ids(self) -> list[str]:
        return [
            item.requirement_id for item in self.requirements if item.status != "SATISFIED"
        ]

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        requirement_ids = [item.requirement_id for item in self.requirements]
        if requirement_ids != sorted(set(requirement_ids)):
            raise ValueError("RequirementState requirements must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"state_digest"})
        if self.state_digest != canonical_sha256(material):
            raise ValueError("RequirementState digest does not match its fields")
        return self


__all__ = [
    "RejectedCandidateDisposition",
    "RequirementCardinalityState",
    "RequirementDisposition",
    "RequirementDispositionStatus",
    "RequirementKind",
    "RequirementProofStatus",
    "RequirementState",
    "canonical_sha256",
]
