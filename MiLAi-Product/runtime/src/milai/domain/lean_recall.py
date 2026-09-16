"""Internal lean recall, requirement-role, and accepted EvidenceSet contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

LeanRecallMode = Literal["LOOKUP", "STRICT"]
EvidenceSourceRole = Literal["user", "assistant", "system", "tool", "unknown"]


class LeanRecallRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=128)
    requirement_role: str = Field(min_length=1, max_length=128)
    source_roles: tuple[str, ...] = ()
    required: bool = True

    @model_validator(mode="after")
    def validate_stable_roles(self) -> Self:
        if self.source_roles != tuple(sorted(set(self.source_roles))):
            raise ValueError("Lean recall source roles must be sorted and unique")
        return self


class LeanRecallPlan(BaseModel):
    """Minimal deterministic adapter over the existing executable QueryIR."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["lean-recall-plan-v0.1"] = "lean-recall-plan-v0.1"
    mode: LeanRecallMode
    operator: str | None = None
    requirements: tuple[LeanRecallRequirement, ...] = ()
    hidden_model_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_requirement_identity(self) -> Self:
        identities = [item.requirement_id for item in self.requirements]
        if len(identities) != len(set(identities)):
            raise ValueError("Lean recall requirement IDs must be unique")
        if self.mode == "LOOKUP" and self.operator is not None:
            raise ValueError("LOOKUP recall cannot carry an operator")
        return self

    @property
    def plan_digest(self) -> str:
        return _canonical_digest(self.model_dump(mode="json"))


class RetrievalOccurrence(BaseModel):
    """One channel/probe occurrence retained after Evidence identity dedup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: str = Field(min_length=1, max_length=64)
    probe_id: str | None = Field(default=None, min_length=1, max_length=160)
    channel_rank: int | None = Field(default=None, ge=1)
    probe_rank: int | None = Field(default=None, ge=1)
    fusion_rank: int | None = Field(default=None, ge=1)
    expansion_origin: str | None = Field(default=None, min_length=1, max_length=64)


class EvidenceSetItem(BaseModel):
    """Exact governed span selected for one or more answer/operator roles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_ids: tuple[str, ...]
    requirement_roles: tuple[str, ...]
    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    source_role: EvidenceSourceRole
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    observed_at: str | None = None
    occurrences: tuple[RetrievalOccurrence, ...] = ()

    @model_validator(mode="after")
    def validate_exact_stable_item(self) -> Self:
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("EvidenceSet offsets must exactly cover its text")
        for name in ("requirement_ids", "requirement_roles"):
            values = getattr(self, name)
            if not values or values != tuple(sorted(set(values))):
                raise ValueError(f"EvidenceSet {name} must be non-empty, sorted, and unique")
        occurrence_order = tuple(
            sorted(
                self.occurrences,
                key=lambda item: (
                    item.channel,
                    item.probe_id or "",
                    item.channel_rank or 0,
                    item.probe_rank or 0,
                    item.fusion_rank or 0,
                ),
            )
        )
        if self.occurrences != occurrence_order:
            raise ValueError("EvidenceSet occurrence lineage must use stable order")
        return self


class EvidenceSet(BaseModel):
    """Requirement-indexed evidence selected after governance and Binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["requirement-evidence-set-v0.1"] = (
        "requirement-evidence-set-v0.1"
    )
    required_requirement_ids: tuple[str, ...] = ()
    items: tuple[EvidenceSetItem, ...] = ()

    @model_validator(mode="after")
    def validate_stable_set(self) -> Self:
        if self.required_requirement_ids != tuple(sorted(set(self.required_requirement_ids))):
            raise ValueError("EvidenceSet required requirements must be sorted and unique")
        ordered = tuple(
            sorted(
                self.items,
                key=lambda item: (
                    item.source_turn_ref,
                    item.start,
                    item.end,
                    item.requirement_ids,
                    item.evidence_id,
                ),
            )
        )
        if self.items != ordered:
            raise ValueError("EvidenceSet items must use stable source order")
        if any(
            not set(item.requirement_ids).issubset(self.required_requirement_ids)
            for item in self.items
        ):
            raise ValueError("EvidenceSet item references an undeclared requirement")
        return self

    @property
    def covered_requirement_ids(self) -> tuple[str, ...]:
        return tuple(sorted({value for item in self.items for value in item.requirement_ids}))

    @property
    def missing_requirement_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.required_requirement_ids).difference(self.covered_requirement_ids))
        )

    @property
    def evidence_set_digest(self) -> str:
        return _canonical_digest(self.model_dump(mode="json"))


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "EvidenceSet",
    "EvidenceSetItem",
    "EvidenceSourceRole",
    "LeanRecallMode",
    "LeanRecallPlan",
    "LeanRecallRequirement",
    "RetrievalOccurrence",
]
