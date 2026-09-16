"""Query-local contracts for DG-18 bounded residual refinding.

These values can change candidate acquisition only.  They deliberately cannot
represent Evidence acceptance, Sufficiency, authority, or canonical mutation.
"""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.acquisition import AcquisitionRemainingBudget

ResidualSearchAction = Literal[
    "SEARCH_LEXICAL",
    "SEARCH_TEMPORAL",
    "EXPAND_NEIGHBORS",
    "EXPAND_EPISODE",
    "NO_ACTION",
]
ResidualCueAction = Literal[
    "SEARCH_LEXICAL",
    "SEARCH_TEMPORAL",
    "EXPAND_NEIGHBORS",
    "NO_ACTION",
]
ResidualTemporalAxis = Literal[
    "SOURCE_OBSERVED_TIME",
    "EVENT_OCCURRENCE_TIME",
    "NO_CHANGE",
]
ResidualSourcePreference = Literal["USER", "ASSISTANT", "BOTH", "NO_CHANGE"]
ResidualCueProvenance = Literal["QUERY", "OBSERVATION", "PARAPHRASE"]
ResidualRationaleCode = Literal[
    "LEXICAL_MISMATCH",
    "ENTITY_BRIDGE",
    "TEMPORAL_NARROWING",
    "LOCAL_CONTEXT_REQUIRED",
    "EPISODE_CONTEXT_REQUIRED",
    "NO_SAFE_ACTION",
]
ResidualCandidateEligibilityReason = Literal[
    "ELIGIBLE",
    "MALFORMED_CANDIDATE",
    "NON_EVIDENCE_CANDIDATE",
    "CANONICAL_CANDIDATE",
    "PLAN_IDENTITY_UNBOUND",
    "TENANT_MISMATCH",
    "PRINCIPAL_MISMATCH",
    "SCOPE_MISMATCH",
    "PERMISSION_UNKNOWN",
    "PERMISSION_DENIED",
    "RETENTION_BLOCKED",
    "REVOKED_EVIDENCE",
    "AUTHORITY_MISMATCH",
    "SOURCE_TIME_OUT_OF_SCOPE",
    "SYSTEM_TIME_OUT_OF_SCOPE",
    "EVENT_TIME_OUT_OF_SCOPE",
    "HIDDEN_FALLBACK",
]


class ResidualCandidateEligibilityReceipt(BaseModel):
    """Content-free deterministic disposition applied before snippet hydration."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["residual-candidate-eligibility-v0.1"] = (
        "residual-candidate-eligibility-v0.1"
    )
    eligible: bool
    reason_code: ResidualCandidateEligibilityReason
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.eligible != (self.reason_code == "ELIGIBLE"):
            raise ValueError("candidate eligibility and reason must agree")
        return self


class ResidualMissingRequirement(BaseModel):
    """A deterministic requirement description exposed to the controller."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1, max_length=128)
    semantic_description: str = Field(min_length=1, max_length=512)
    known_entities: list[str] = Field(default_factory=list, max_length=32)
    known_predicates: list[str] = Field(default_factory=list, max_length=16)
    temporal_constraint: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_unique_cues(self) -> Self:
        if len(self.known_entities) != len(set(self.known_entities)):
            raise ValueError("missing-requirement entities must be unique")
        if len(self.known_predicates) != len(set(self.known_predicates)):
            raise ValueError("missing-requirement predicates must be unique")
        return self


class ResidualCandidateSummary(BaseModel):
    """Bounded, non-persistent observation over one already-gated candidate."""

    model_config = ConfigDict(extra="forbid")

    ephemeral_candidate_ref: str = Field(pattern=r"^candidate-[0-9a-f]{16}$")
    session_ref: str = Field(pattern=r"^session-[0-9a-f]{16}$")
    speaker: Literal["USER", "ASSISTANT", "SYSTEM", "TOOL", "UNKNOWN"]
    source_observed_time: AwareDatetime | None = None
    event_time: dict[str, object] | None = None
    bounded_snippet: str = Field(min_length=1, max_length=600)
    matched_terms: list[str] = Field(default_factory=list, max_length=32)
    matched_channels: list[str] = Field(default_factory=list, max_length=8)
    possible_requirement_ids: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_unique_metadata(self) -> Self:
        groups = (
            self.matched_terms,
            self.matched_channels,
            self.possible_requirement_ids,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("residual candidate metadata must be unique")
        return self


class AcquisitionObservation(BaseModel):
    """The only bounded product observation visible to a residual controller."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-observation-v0.1"] = (
        "acquisition-observation-v0.1"
    )
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_excerpt: str = Field(min_length=1, max_length=600)
    missing_requirements: list[ResidualMissingRequirement] = Field(
        min_length=1, max_length=16
    )
    candidate_summaries: list[ResidualCandidateSummary] = Field(
        default_factory=list, max_length=12
    )
    prior_action_digests: list[str] = Field(default_factory=list, max_length=2)
    exhausted_region_digests: list[str] = Field(default_factory=list, max_length=256)
    remaining_budget: AcquisitionRemainingBudget
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation_identity(self) -> Self:
        requirement_ids = [item.requirement_id for item in self.missing_requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("observation requirements must be unique")
        ephemeral = [item.ephemeral_candidate_ref for item in self.candidate_summaries]
        if len(ephemeral) != len(set(ephemeral)):
            raise ValueError("observation candidate references must be unique")
        for values, label in (
            (self.prior_action_digests, "prior actions"),
            (self.exhausted_region_digests, "exhausted regions"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"observation {label} must be unique")
            if any(
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in values
            ):
                raise ValueError(f"observation {label} must be SHA-256 digests")
        return self


class ResidualLexicalCues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: list[str] = Field(default_factory=list, max_length=8)
    phrases: list[str] = Field(default_factory=list, max_length=4)
    entity_aliases: list[str] = Field(default_factory=list, max_length=4)
    predicate_rephrasings: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_cues(self) -> Self:
        groups = (self.terms, self.phrases, self.entity_aliases, self.predicate_rephrasings)
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("residual lexical cues must be unique")
        if any(
            not value.strip() or len(value) > 128
            for values in groups
            for value in values
        ):
            raise ValueError("residual lexical cue is empty or too long")
        forbidden_control = re.compile(
            r"(?:\bfinal\s+answer\b|\bdeclare(?:d)?\s+complete\b|"
            r"\bstatus\s*[:=]?\s*complete\b|\bevidence[-_:][a-z0-9]|"
            r"\bclaim[-_:][a-z0-9]|\bcanonical\s+mutation\b|"
            r"\b(?:change|expand|override)\s+(?:scope|authority|permission|principal|tenant)\b)",
            re.IGNORECASE,
        )
        if any(
            forbidden_control.search(value)
            for values in groups
            for value in values
        ):
            raise ValueError("residual lexical cue contains a forbidden control assertion")
        return self

    @property
    def populated(self) -> bool:
        return any((self.terms, self.phrases, self.entity_aliases, self.predicate_rephrasings))


class ResidualTemporalCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: ResidualTemporalAxis = "NO_CHANGE"
    expression: str | None = Field(default=None, min_length=1, max_length=128)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("residual temporal interval start cannot exceed end")
        if self.axis == "NO_CHANGE" and any(
            value is not None for value in (self.expression, self.start, self.end)
        ):
            raise ValueError("NO_CHANGE temporal cue cannot carry an interval")
        if self.axis != "NO_CHANGE" and self.start is None and self.end is None:
            raise ValueError("temporal search requires a normalized bound")
        return self


class ResidualSearchHint(BaseModel):
    """Untrusted controller proposal; validation still belongs to Runtime."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["residual-search-hint-v0.1"] = "residual-search-hint-v0.1"
    requirement_id: str = Field(min_length=1, max_length=128)
    action: ResidualSearchAction
    lexical_cues: ResidualLexicalCues = Field(default_factory=ResidualLexicalCues)
    temporal_cue: ResidualTemporalCue = Field(default_factory=ResidualTemporalCue)
    source_preference: ResidualSourcePreference = "NO_CHANGE"
    cue_provenance: ResidualCueProvenance
    rationale_code: ResidualRationaleCode

    @model_validator(mode="after")
    def validate_action_shape(self) -> Self:
        if self.action == "SEARCH_LEXICAL":
            if not self.lexical_cues.populated or self.temporal_cue.axis != "NO_CHANGE":
                raise ValueError("lexical search requires only bounded lexical cues")
        elif self.action == "SEARCH_TEMPORAL":
            if self.temporal_cue.axis == "NO_CHANGE" or self.lexical_cues.populated:
                raise ValueError("temporal search requires only a normalized temporal cue")
        elif self.action in {"EXPAND_NEIGHBORS", "EXPAND_EPISODE"}:
            if self.lexical_cues.populated or self.temporal_cue.axis != "NO_CHANGE":
                raise ValueError("structural expansion cannot smuggle search cues")
        elif self.action == "NO_ACTION":
            if (
                self.lexical_cues.populated
                or self.temporal_cue.axis != "NO_CHANGE"
                or self.source_preference != "NO_CHANGE"
                or self.rationale_code != "NO_SAFE_ACTION"
            ):
                raise ValueError("NO_ACTION must be empty and explicitly safe")
        if self.rationale_code == "NO_SAFE_ACTION" and self.action != "NO_ACTION":
            raise ValueError("NO_SAFE_ACTION rationale requires NO_ACTION")
        return self


class ResidualCueProposal(BaseModel):
    """Minimal provider wire contract; Runtime derives all control metadata."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1, max_length=128)
    action: ResidualCueAction
    cues: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_wire_shape(self) -> Self:
        if len(self.cues) != len(set(self.cues)):
            raise ValueError("residual proposal cues must be unique")
        if any(not cue.strip() or len(cue) > 128 for cue in self.cues):
            raise ValueError("residual proposal cue is empty or too long")
        forbidden_control = re.compile(
            r"(?:\bfinal\s+answer\b|\bdeclare(?:d)?\s+complete\b|"
            r"\bstatus\s*[:=]?\s*complete\b|\bevidence[-_:][a-z0-9]|"
            r"\bclaim[-_:][a-z0-9]|\bcanonical\s+mutation\b|"
            r"\b(?:change|expand|override)\s+"
            r"(?:scope|authority|permission|principal|tenant)\b)",
            re.IGNORECASE,
        )
        if any(forbidden_control.search(cue) for cue in self.cues):
            raise ValueError("residual proposal cue contains a forbidden control assertion")
        if self.action == "SEARCH_LEXICAL" and not self.cues:
            raise ValueError("lexical proposal requires at least one cue")
        if self.action == "SEARCH_TEMPORAL" and len(self.cues) > 1:
            raise ValueError("temporal proposal accepts at most one expression cue")
        if self.action in {"EXPAND_NEIGHBORS", "NO_ACTION"} and self.cues:
            raise ValueError("structural or no-action proposal cannot carry cues")
        return self


class ResidualControllerTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_ms: float = Field(ge=0.0)
    ttft_ms: float = Field(ge=0.0)
    decode_ms: float = Field(ge=0.0)
    total_ms: float = Field(ge=0.0)


class ResidualControllerReceipt(BaseModel):
    """Receipted one-call shadow result; never an acquisition decision by itself."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["residual-controller-receipt-v0.1"] = (
        "residual-controller-receipt-v0.1"
    )
    hint: ResidualSearchHint
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    tokenizer_latency_ms: float = Field(ge=0.0)
    timing: ResidualControllerTiming
    model_call_count: Literal[1] = 1
    automatic_retry_count: Literal[0] = 0
    product_result_changed: Literal[False] = False
    canonical_mutation: Literal[False] = False


class ResidualHintValidation(BaseModel):
    """Runtime policy disposition, separate from the model receipt."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ACCEPTED", "REJECTED", "NO_ACTION"]
    reason_code: str = Field(min_length=1, max_length=128)
    requirement_id: str = Field(min_length=1, max_length=128)
    action: ResidualSearchAction
    source_preference_is_soft: Literal[True] = True
    inherited_scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    inherited_authority_floor: str = Field(min_length=1)
    canonical_mutation: Literal[False] = False


class ResidualActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    activated: bool
    reason: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_activation(self) -> Self:
        if self.activated and not self.eligible:
            raise ValueError("an ineligible residual path cannot be activated")
        return self


class ResidualDeterministicState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    coverage: dict[str, JsonValue] = Field(default_factory=dict)
    operator_ready: bool
    sufficiency_status: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_missing_requirements(self) -> Self:
        if len(self.missing_requirement_ids) != len(set(self.missing_requirement_ids)):
            raise ValueError("residual trace missing requirements must be unique")
        return self


class ResidualControllerTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_identity: str | None = Field(default=None, min_length=1, max_length=512)
    prompt_schema: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_schema_valid: bool | None = None
    model_call_count: int = Field(ge=0, le=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    automatic_retry_count: Literal[0] = 0

    @model_validator(mode="after")
    def validate_call_shape(self) -> Self:
        if self.model_call_count == 0 and any(
            value is not None
            for value in (
                self.provider_identity,
                self.prompt_schema,
                self.output_schema_valid,
            )
        ):
            raise ValueError("zero-call controller trace cannot claim provider output")
        if self.model_call_count == 0 and any(
            (self.input_tokens, self.output_tokens, self.latency_ms)
        ):
            raise ValueError("zero-call controller trace cannot report model cost")
        if self.model_call_count == 1 and (
            self.provider_identity is None
            or self.prompt_schema is None
            or self.output_schema_valid is None
        ):
            raise ValueError("executed controller trace requires complete identity")
        return self


class ResidualHintTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ResidualSearchAction | None = None
    requirement_id: str | None = Field(default=None, min_length=1, max_length=128)
    cue_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validation_status: Literal["NOT_PROPOSED", "ACCEPTED", "REJECTED", "NO_ACTION"]
    rejection_reason: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        proposed = self.validation_status != "NOT_PROPOSED"
        if proposed != (self.action is not None and self.requirement_id is not None):
            raise ValueError("hint trace proposal identity is incomplete")
        if self.validation_status == "REJECTED" and self.rejection_reason is None:
            raise ValueError("rejected hint trace requires a reason")
        if self.validation_status != "REJECTED" and self.rejection_reason is not None:
            raise ValueError("only a rejected hint can carry a rejection reason")
        return self


class ResidualAdditionalAcquisition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempted: bool
    channel: str | None = Field(default=None, min_length=1, max_length=64)
    candidate_count: int = Field(default=0, ge=0, le=256)
    new_candidate_count: int = Field(default=0, ge=0, le=256)
    repeated_region_count: int = Field(default=0, ge=0, le=256)
    latency_ms: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.new_candidate_count > self.candidate_count:
            raise ValueError("new residual candidates cannot exceed all candidates")
        if not self.attempted and (
            self.channel is not None
            or self.candidate_count
            or self.new_candidate_count
            or self.repeated_region_count
            or self.latency_ms
        ):
            raise ValueError("unattempted acquisition cannot report work")
        if self.attempted and self.channel is None:
            raise ValueError("attempted acquisition requires a channel")
        return self


class ResidualRefindingTrace(BaseModel):
    """Bounded nested AccessTrace view with no prompt or Evidence body fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["residual-refinding-trace-v0.1"] = (
        "residual-refinding-trace-v0.1"
    )
    activation: ResidualActivation
    deterministic_before: ResidualDeterministicState
    controller: ResidualControllerTrace
    hint: ResidualHintTrace
    additional_acquisition: ResidualAdditionalAcquisition
    deterministic_after: ResidualDeterministicState
    terminal_reason: str = Field(min_length=1, max_length=128)
    product_result_changed: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_trace_lifecycle(self) -> Self:
        if not self.activation.activated and (
            self.controller.model_call_count != 0
            or self.additional_acquisition.attempted
        ):
            raise ValueError("inactive residual trace cannot report controller/search work")
        if self.activation.activated and self.controller.model_call_count != 1:
            raise ValueError("activated residual trace requires exactly one controller call")
        if self.controller.model_call_count == 0 and self.hint.validation_status != "NOT_PROPOSED":
            raise ValueError("zero-call residual trace cannot contain a proposed hint")
        if self.controller.model_call_count == 1:
            output_valid = self.controller.output_schema_valid is True
            proposed = self.hint.validation_status != "NOT_PROPOSED"
            if output_valid != proposed:
                raise ValueError("controller schema disposition and hint trace disagree")
        if self.additional_acquisition.attempted and (
            self.hint.validation_status != "ACCEPTED"
            or self.hint.action in {None, "NO_ACTION"}
        ):
            raise ValueError("additional acquisition requires one accepted actionable hint")
        if not self.activation.eligible and self.deterministic_before.missing_requirement_ids:
            if self.activation.reason == "ALREADY_COMPLETE":
                raise ValueError("already-complete trace cannot have missing requirements")
        return self


__all__ = [
    "AcquisitionObservation",
    "ResidualActivation",
    "ResidualAdditionalAcquisition",
    "ResidualCandidateEligibilityReason",
    "ResidualCandidateEligibilityReceipt",
    "ResidualCandidateSummary",
    "ResidualControllerReceipt",
    "ResidualControllerTiming",
    "ResidualControllerTrace",
    "ResidualCueAction",
    "ResidualCueProposal",
    "ResidualCueProvenance",
    "ResidualDeterministicState",
    "ResidualHintTrace",
    "ResidualHintValidation",
    "ResidualLexicalCues",
    "ResidualMissingRequirement",
    "ResidualRationaleCode",
    "ResidualRefindingTrace",
    "ResidualSearchAction",
    "ResidualSearchHint",
    "ResidualSourcePreference",
    "ResidualTemporalAxis",
    "ResidualTemporalCue",
]
