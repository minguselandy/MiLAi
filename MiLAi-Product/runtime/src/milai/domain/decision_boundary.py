"""Typed noncanonical contracts for the DG-27 final decision boundary.

The objects in this module are query-local.  They cannot write canonical
memory, raise Evidence authority, or let an interpretation model declare a
requirement complete.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from milai.domain.requirement_state import RequirementState
from milai.domain.sufficiency import SufficiencyDecision

SemanticRelationV02 = Literal[
    "SUPPORT",
    "CONTRADICT",
    "UPDATE",
    "CONTEXT_ONLY",
    "IRRELEVANT",
]
ProvisionalBindingStatusV01 = Literal[
    "POSSIBLE",
    "AMBIGUOUS",
    "CONTRADICTORY",
    "IRRELEVANT",
]


class GroundedSpanV02(BaseModel):
    """Exact Python ``[start, end)`` pointer into one candidate render."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_width(self) -> Self:
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("grounded span offsets must exactly cover text")
        return self


class EventTimeHypothesisV02(BaseModel):
    """Advisory event-time hypothesis; source time remains a distinct axis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime | None = None
    end: datetime | None = None
    time_basis: Literal[
        "EXPLICIT_EVENT_TIME",
        "INFERRED_EVENT_TIME",
        "SOURCE_OBSERVED_TIME",
        "UNRESOLVED",
    ] = "UNRESOLVED"
    normalized_from: str | None = None

    @model_validator(mode="after")
    def validate_time_axes(self) -> Self:
        for value in (self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("event-time values must include a timezone offset")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("event-time start cannot exceed end")
        if self.time_basis in {"EXPLICIT_EVENT_TIME", "INFERRED_EVENT_TIME"}:
            if self.start is None:
                raise ValueError("resolved event time requires a start")
        elif self.start is not None or self.end is not None:
            raise ValueError("unresolved/source time cannot masquerade as event time")
        return self


class SemanticHypothesisV02(BaseModel):
    """One fallible meaning hypothesis grounded in a frozen candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hypothesis_id: str = Field(min_length=1)
    relation: SemanticRelationV02
    grounded_spans: list[GroundedSpanV02] = Field(default_factory=list, max_length=3)
    normalized_subjects: list[str] = Field(default_factory=list, max_length=16)
    normalized_predicate: str | None = None
    normalized_value: str | None = None
    normalized_unit: str | None = None
    event_time_hypothesis: EventTimeHypothesisV02 | None = None
    confidence_feature: float | None = Field(default=None, ge=0.0, le=1.0)
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_grounding_shape(self) -> Self:
        if self.relation in {"SUPPORT", "CONTRADICT", "UPDATE", "CONTEXT_ONLY"}:
            if not self.grounded_spans:
                raise ValueError("semantic relation requires at least one grounded span")
        if self.relation == "IRRELEVANT" and self.grounded_spans:
            raise ValueError("irrelevant hypothesis cannot claim a grounded semantic span")
        return self


class SemanticInterpretationSetV02(BaseModel):
    """Zero to three coexisting hypotheses for one admitted candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["semantic-interpretation-set-v0.2"] = (
        "semantic-interpretation-set-v0.2"
    )
    candidate_id: str = Field(min_length=1)
    hypotheses: list[SemanticHypothesisV02] = Field(default_factory=list, max_length=3)
    ambiguity_reasons: list[str] = Field(default_factory=list, max_length=8)
    producer_identity: str = Field(min_length=1)
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_hypothesis_identity(self) -> Self:
        identities = [item.hypothesis_id for item in self.hypotheses]
        if len(identities) != len(set(identities)):
            raise ValueError("semantic hypothesis identities must be unique")
        return self


class ProvisionalBindingV01(BaseModel):
    """Workspace-only relation that never satisfies Sufficiency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["provisional-binding-v0.1"] = "provisional-binding-v0.1"
    candidate_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    status: ProvisionalBindingStatusV01
    supporting_interpretation_ids: list[str] = Field(default_factory=list)
    unresolved_checks: list[str] = Field(default_factory=list)
    accepted: Literal[False] = False
    satisfies_requirement: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if self.supporting_interpretation_ids != sorted(
            set(self.supporting_interpretation_ids)
        ):
            raise ValueError("provisional interpretation references must be sorted and unique")
        if self.unresolved_checks != sorted(set(self.unresolved_checks)):
            raise ValueError("unresolved checks must be sorted and unique")
        if self.status == "IRRELEVANT" and self.supporting_interpretation_ids:
            raise ValueError("irrelevant provisional binding cannot carry support")
        return self


class AcceptedBindingV02(BaseModel):
    """Final query-local binding emitted only by ``DecisionBoundaryV02``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["accepted-binding-v0.2"] = "accepted-binding-v0.2"
    accepted_binding_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    interpretation_id: str = Field(min_length=1)
    grounded_span_ids: list[str] = Field(min_length=1)
    validation_profile: Literal["decision-boundary-v0.2"] = "decision-boundary-v0.2"
    source_span_verified: Literal[True] = True
    gate_valid: Literal[True] = True
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False


class DecisionBoundaryResultV02(BaseModel):
    """One immutable final Binding/RequirementState/Sufficiency decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["decision-boundary-result-v0.2"] = (
        "decision-boundary-result-v0.2"
    )
    decision_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_count: Literal[1] = 1
    provisional_bindings: list[ProvisionalBindingV01] = Field(default_factory=list)
    accepted_bindings: list[AcceptedBindingV02] = Field(default_factory=list)
    rejected_hypotheses: dict[str, str] = Field(default_factory=dict)
    requirement_state: RequirementState
    sufficiency_decision: SufficiencyDecision
    operator_ready: bool
    model_completion_authority: Literal[False] = False
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_final_ownership(self) -> Self:
        accepted_requirements = sorted(
            {item.requirement_id for item in self.accepted_bindings}
        )
        if self.operator_ready != (
            self.sufficiency_decision.status == "COMPLETE"
            and not self.requirement_state.missing_requirement_ids
        ):
            raise ValueError("operator readiness must be owned by final requirement state")
        if self.sufficiency_decision.status == "COMPLETE":
            required = sorted(
                item.requirement_id for item in self.requirement_state.requirements
            )
            if accepted_requirements != required:
                raise ValueError("COMPLETE requires an AcceptedBinding for every requirement")
        return self


__all__ = [
    "AcceptedBindingV02",
    "DecisionBoundaryResultV02",
    "EventTimeHypothesisV02",
    "GroundedSpanV02",
    "ProvisionalBindingStatusV01",
    "ProvisionalBindingV01",
    "SemanticHypothesisV02",
    "SemanticInterpretationSetV02",
    "SemanticRelationV02",
]
