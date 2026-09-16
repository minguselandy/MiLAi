"""Internal DG-23 decision, Reader plan, and presentation-budget contracts.

These objects are deliberately not part of the MCP request/response models.
They separate immutable semantic decisions from local Reader presentation.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.lean_recall import EvidenceSet, LeanRecallMode

Digest = str
ReaderEvidenceUnitKind = Literal[
    "STATUS",
    "DERIVED_RESULT",
    "REQUIRED_BINDING",
    "CONFLICT_SIDE",
    "OPEN_ISSUE",
    "PROVENANCE",
]
ReaderReadiness = Literal["READY", "BUDGET_INFEASIBLE"]
BudgetSource = Literal["EXACT_READER_ENVELOPE", "CALLER_CAP_ONLY"]


class ReaderEvidencePolicy(StrEnum):
    """Single owner for the Reader presentation boundary after governance."""

    GOVERNANCE_ADMITTED_SOFT_RANKED = "GOVERNANCE_ADMITTED_SOFT_RANKED"
    DECISION_ACCEPTED_ONLY = "DECISION_ACCEPTED_ONLY"


class AcceptedBindingSpan(BaseModel):
    """Exact, governed source span accepted by semantic Binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_ids: tuple[str, ...] = ()
    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    speaker: Literal["user", "assistant", "system", "tool", "unknown"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    observed_at: str | None = None

    @model_validator(mode="after")
    def validate_exact_span(self) -> Self:
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("accepted Binding span offsets must exactly cover text")
        if self.requirement_ids != tuple(sorted(set(self.requirement_ids))):
            raise ValueError("accepted Binding requirement IDs must be sorted and unique")
        return self


class DecisionFacts(BaseModel):
    """Validated decision facts, independent of derived material digests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lean_recall_mode: LeanRecallMode
    evidence_set: EvidenceSet
    accepted_evidence_ids: tuple[str, ...] = ()
    accepted_binding_spans: tuple[AcceptedBindingSpan, ...] = ()
    rejected_evidence_summary: dict[str, int] = Field(default_factory=dict)
    required_requirement_ids: tuple[str, ...] = ()
    unresolved_requirement_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_deterministic_collections(self) -> Self:
        for name in (
            "accepted_evidence_ids",
            "required_requirement_ids",
            "unresolved_requirement_ids",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be sorted and unique")
        if self.rejected_evidence_summary != dict(
            sorted(self.rejected_evidence_summary.items())
        ):
            raise ValueError("rejected_evidence_summary must be key-sorted")
        if any(value < 0 for value in self.rejected_evidence_summary.values()):
            raise ValueError("rejected evidence counts cannot be negative")
        binding_span_order = tuple(
            sorted(
                self.accepted_binding_spans,
                key=lambda item: (
                    item.source_turn_ref,
                    item.start,
                    item.end,
                    item.requirement_ids,
                    item.evidence_id,
                ),
            )
        )
        if self.accepted_binding_spans != binding_span_order:
            raise ValueError("accepted Binding spans must use stable source order")
        if not {
            item.evidence_id for item in self.accepted_binding_spans
        }.issubset(self.accepted_evidence_ids):
            raise ValueError("accepted Binding spans must reference accepted Evidence")
        if not {item.evidence_id for item in self.evidence_set.items}.issubset(
            self.accepted_evidence_ids
        ):
            raise ValueError("EvidenceSet items must reference accepted Evidence")
        if self.evidence_set.required_requirement_ids != self.required_requirement_ids:
            raise ValueError("EvidenceSet and decision requirement universes must match")
        if not set(self.unresolved_requirement_ids).issubset(
            self.required_requirement_ids
        ):
            raise ValueError("unresolved requirements must be required")
        return self


class DecisionSnapshot(DecisionFacts):
    """Complete immutable decision with the original serialized digest contract."""

    schema_version: Literal["decision-snapshot-v0.1"] = "decision-snapshot-v0.1"
    source_snapshot_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    query_ir_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_snapshot_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    gate_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    binding_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    sufficiency_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    operator_result_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    lean_recall_plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def snapshot_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class ReaderEvidenceUnit(BaseModel):
    """One whole, stable Reader-visible semantic unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str = Field(min_length=1)
    kind: ReaderEvidenceUnitKind
    requirement_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_turn_refs: tuple[str, ...] = ()
    text: str = Field(min_length=1)
    exact_span: bool = True
    atomic: Literal[True] = True
    estimated_tokens: int = Field(ge=1)
    incremental_requirement_gain: tuple[str, ...] = ()
    rejection_diagnostic_gain: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_stable_references(self) -> Self:
        for name in (
            "requirement_ids",
            "evidence_ids",
            "source_turn_refs",
            "incremental_requirement_gain",
            "rejection_diagnostic_gain",
        ):
            values = getattr(self, name)
            if values != tuple(dict.fromkeys(values)):
                raise ValueError(f"{name} cannot contain duplicates")
        return self


class OmittedReaderEvidenceUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ReaderEvidencePlan(BaseModel):
    """Budget-free ordering and semantic closure for Reader evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reader-evidence-plan-v0.1"] = (
        "reader-evidence-plan-v0.1"
    )
    plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    decision_snapshot_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: str = Field(min_length=1)
    stable_order_version: str = Field(min_length=1)
    protected_units: tuple[ReaderEvidenceUnit, ...] = ()
    conditional_units: tuple[ReaderEvidenceUnit, ...] = ()
    omitted_units: tuple[OmittedReaderEvidenceUnit, ...] = ()

    @model_validator(mode="after")
    def validate_plan_identity(self) -> Self:
        units = (*self.protected_units, *self.conditional_units)
        unit_ids = [unit.unit_id for unit in units]
        omitted_ids = [unit.unit_id for unit in self.omitted_units]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("ReaderEvidencePlan unit IDs must be unique")
        if set(unit_ids).intersection(omitted_ids):
            raise ValueError("selected and omitted unit identities must be disjoint")
        material = self.model_dump(mode="json", exclude={"plan_digest"})
        if self.plan_digest != canonical_digest(material):
            raise ValueError("ReaderEvidencePlan digest does not match its material")
        return self


class ContextBudgetEnvelope(BaseModel):
    """Exact Reader-boundary budget; it cannot enter a decision digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["context-budget-envelope-v0.1"] = (
        "context-budget-envelope-v0.1"
    )
    requested_cap: int = Field(ge=0, le=16_384)
    model_context_limit: int | None = Field(default=None, ge=1)
    fixed_system_prompt_tokens: int = Field(default=0, ge=0)
    query_tokens: int = Field(default=0, ge=0)
    answer_reserve_tokens: int = Field(default=0, ge=0)
    safety_margin_tokens: int = Field(default=0, ge=0)
    available_memory_tokens: int = Field(ge=0, le=16_384)
    reader_tokenizer_identity: str | None = None
    budget_source: BudgetSource

    @model_validator(mode="after")
    def validate_available_budget(self) -> Self:
        if self.budget_source == "CALLER_CAP_ONLY":
            if self.model_context_limit is not None or self.reader_tokenizer_identity is not None:
                raise ValueError("caller-only budget cannot claim Reader boundary identity")
            expected = self.requested_cap
        else:
            if self.model_context_limit is None or not self.reader_tokenizer_identity:
                raise ValueError("exact Reader envelope requires model and tokenizer identity")
            remaining = self.model_context_limit - (
                self.fixed_system_prompt_tokens
                + self.query_tokens
                + self.answer_reserve_tokens
                + self.safety_margin_tokens
            )
            expected = min(self.requested_cap, max(0, remaining))
        if self.available_memory_tokens != expected:
            raise ValueError("available_memory_tokens does not match the budget equation")
        return self


class ReaderEvidenceRender(BaseModel):
    """One local whole-unit render of an immutable ReaderEvidencePlan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reader-evidence-render-v0.1"] = (
        "reader-evidence-render-v0.1"
    )
    plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    envelope: ContextBudgetEnvelope
    readiness: ReaderReadiness
    selected_unit_ids: tuple[str, ...] = ()
    omitted_unit_reasons: dict[str, str] = Field(default_factory=dict)
    text: str
    reader_context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    exact_tokens: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    protected_closure_tokens: int = Field(ge=0)
    semantic_saturated: bool = False


def canonical_digest(value: JsonValue | object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "AcceptedBindingSpan",
    "BudgetSource",
    "ContextBudgetEnvelope",
    "DecisionFacts",
    "DecisionSnapshot",
    "OmittedReaderEvidenceUnit",
    "ReaderEvidencePlan",
    "ReaderEvidenceRender",
    "ReaderEvidenceUnit",
    "ReaderEvidenceUnitKind",
    "ReaderReadiness",
    "canonical_digest",
]
