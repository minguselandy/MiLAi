from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.requirement_state import RequirementState

AcquisitionChannel = Literal[
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
    "CANONICAL_STATE",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
]
AcquisitionSourceSpeaker = Literal["USER", "ASSISTANT", "SYSTEM", "TOOL"]
AcquisitionSourceProvenance = Literal[
    "EXPLICIT_QUERY",
    "TYPED_HINT",
    "SEMANTIC_PARSER",
    "NONE",
]
AcquisitionTemporalAxis = Literal[
    "SOURCE_OBSERVED_TIME",
    "EVENT_OCCURRENCE_TIME",
    "BOTH",
    "NONE",
]
AcquisitionExpansionPolicy = Literal[
    "NONE",
    "ADJACENT_TURNS",
    "SAME_EPISODE",
    "SAME_SESSION",
]


class AcquisitionGlobalConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_scope: dict[str, JsonValue] = Field(default_factory=dict)
    semantic_scope: dict[str, JsonValue] = Field(default_factory=dict)
    tenant_identity_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    principal_identity_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_floor: str = Field(min_length=1)
    valid_as_of: datetime
    system_as_of: datetime
    source_observed_range: dict[str, JsonValue] | None = None
    event_occurrence_range: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_time_boundary(self) -> Self:
        for value in (self.valid_as_of, self.system_as_of):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("acquisition as-of boundaries require timezone offsets")
        return self


class AcquisitionSemanticSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str | None = Field(default=None, min_length=1, max_length=256)
    experiencer: str | None = Field(default=None, min_length=1, max_length=256)
    beneficiary: str | None = Field(default=None, min_length=1, max_length=256)


class AcquisitionEvidenceSourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_speakers: list[AcquisitionSourceSpeaker] = Field(default_factory=list, max_length=4)
    allowed_speakers: list[AcquisitionSourceSpeaker] | None = Field(
        default=None, min_length=1, max_length=4
    )
    provenance: AcquisitionSourceProvenance = "NONE"

    @model_validator(mode="after")
    def validate_source_policy(self) -> Self:
        if len(self.preferred_speakers) != len(set(self.preferred_speakers)):
            raise ValueError("preferred source speakers must be unique")
        if self.allowed_speakers is not None:
            if len(self.allowed_speakers) != len(set(self.allowed_speakers)):
                raise ValueError("allowed source speakers must be unique")
            if self.provenance != "EXPLICIT_QUERY":
                raise ValueError(
                    "hard source-speaker constraints require explicit-query provenance"
                )
            if not set(self.preferred_speakers).issubset(self.allowed_speakers):
                raise ValueError("preferred source speakers must be allowed")
        if self.provenance == "NONE" and self.preferred_speakers:
            raise ValueError("source preference requires typed provenance")
        return self


class AcquisitionProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(min_length=1, max_length=160)
    requirement_slot: str | None = Field(default=None, min_length=1, max_length=128)
    channel: AcquisitionChannel
    semantic_subject: AcquisitionSemanticSubject = Field(default_factory=AcquisitionSemanticSubject)
    evidence_source_policy: AcquisitionEvidenceSourcePolicy = Field(
        default_factory=AcquisitionEvidenceSourcePolicy
    )
    lexical_terms: list[str] = Field(default_factory=list, max_length=64)
    phrases: list[str] = Field(default_factory=list, max_length=16)
    dense_query_text: str | None = Field(default=None, min_length=1, max_length=2_000)
    predicate_family: str | None = Field(default=None, min_length=1, max_length=128)
    entities: list[str] = Field(default_factory=list, max_length=32)
    temporal_axis: AcquisitionTemporalAxis
    candidate_limit: int = Field(ge=1, le=256)
    expansion_policy: AcquisitionExpansionPolicy

    @model_validator(mode="after")
    def validate_search_cue(self) -> Self:
        if self.channel in {"FTS_RAW", "FTS_ENRICHED"} and not (self.lexical_terms or self.phrases):
            raise ValueError("FTS acquisition probe requires a lexical cue")
        if self.channel == "EVIDENCE_DENSE" and self.dense_query_text is None:
            raise ValueError("Evidence-dense acquisition requires an immutable query text")
        if self.channel != "EVIDENCE_DENSE" and self.dense_query_text is not None:
            raise ValueError("dense query text is exclusive to Evidence-dense probes")
        return self


class AcquisitionFusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_identity: str = Field(min_length=1)
    rrf_k: int = Field(default=60, ge=1, le=10_000)
    per_slot_quota: dict[str, int] = Field(default_factory=dict)
    global_cap: int = Field(ge=1, le=256)


class AcquisitionResidualPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool = False
    max_model_calls: int = Field(default=0, ge=0, le=1)
    max_extra_passes: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_disabled_shape(self) -> Self:
        if not self.allowed and (self.max_model_calls != 0 or self.max_extra_passes != 0):
            raise ValueError("disabled residual policy cannot allocate calls or passes")
        return self


class AcquisitionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latency_ms: int = Field(ge=1, le=10_000)
    candidate_count: int = Field(ge=1, le=256)
    hydrate_count: int = Field(ge=1, le=256)
    context_tokens: int = Field(ge=1, le=32_000)


class AcquisitionPlan(BaseModel):
    """Internal executable acquisition contract compiled from MemoryQueryIR."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-plan-v0.1"] = "acquisition-plan-v0.1"
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    global_constraints: AcquisitionGlobalConstraints
    probes: list[AcquisitionProbe] = Field(min_length=1, max_length=32)
    fusion: AcquisitionFusion
    residual_policy: AcquisitionResidualPolicy = Field(default_factory=AcquisitionResidualPolicy)
    budget: AcquisitionBudget

    @model_validator(mode="after")
    def validate_slot_dispositions(self) -> Self:
        probe_ids = [probe.probe_id for probe in self.probes]
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("acquisition probe IDs must be unique")
        slot_probes = {
            probe.requirement_slot for probe in self.probes if probe.requirement_slot is not None
        }
        if slot_probes != set(self.fusion.per_slot_quota):
            raise ValueError("every slot probe requires one explicit fusion quota")
        if any(value < 1 for value in self.fusion.per_slot_quota.values()):
            raise ValueError("per-slot acquisition quota must be positive")
        if self.fusion.global_cap != self.budget.candidate_count:
            raise ValueError("fusion cap and acquisition candidate budget must match")
        return self


class CandidateEnvelope(BaseModel):
    """Acquisition identity and provenance retained before interpretation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["candidate-envelope-v0.2"] = "candidate-envelope-v0.2"
    candidate_id: str = Field(min_length=1)
    source_evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    identity_source: Literal[
        "STRUCTURED_TURN_METADATA",
        "AUTHORITATIVE_BACKFILL",
        "UNKNOWN",
    ]
    speaker: Literal["user", "assistant", "system", "tool", "unknown"]
    speaker_source: Literal[
        "STRUCTURED_TURN_METADATA",
        "AUTHORITATIVE_BACKFILL",
        "UNKNOWN",
    ]
    source_observed_at: datetime | None = None
    event_occurrence_interval: dict[str, JsonValue] | None = None
    matched_probes: list[str] = Field(default_factory=list)
    matched_slots: list[str] = Field(default_factory=list)
    channel_ranks: dict[str, int] = Field(default_factory=dict)
    channel_scores: dict[str, float] = Field(default_factory=dict)
    probe_ranks: dict[str, int] = Field(default_factory=dict)
    probe_scores: dict[str, float] = Field(default_factory=dict)
    fusion_rank: int = Field(ge=1)
    fusion_score: float = Field(ge=0)
    expansion_origin: str | None = None
    matched_fields: list[str] = Field(default_factory=list)
    body_ref: str = Field(min_length=1)
    body_hydrated: bool


class AcquisitionRemainingBudget(BaseModel):
    """Unspent work that may still be used inside one ``memory.resolve`` call."""

    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(ge=0, le=1)
    acquisition_passes: int = Field(ge=0, le=1)
    candidate_count: int = Field(ge=0, le=256)
    context_tokens: int = Field(ge=0, le=32_000)
    latency_ms: float = Field(ge=0.0, le=10_000.0)


class AcquisitionBudgetUse(BaseModel):
    """Explicit cost charged by one query-local state transition."""

    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(default=0, ge=0, le=1)
    acquisition_passes: int = Field(default=0, ge=0, le=1)
    candidate_count: int = Field(default=0, ge=0, le=256)
    context_tokens: int = Field(default=0, ge=0, le=32_000)
    latency_ms: float = Field(default=0.0, ge=0.0, le=10_000.0)


class AcquisitionAction(BaseModel):
    """Digest-addressed acquisition work; it carries no Evidence authority."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-action-v0.1"] = "acquisition-action-v0.1"
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_kind: Literal[
        "DETERMINISTIC_PASS",
        "EXPAND_NEIGHBORS",
        "EXPAND_EPISODE",
        "RESIDUAL_PASS",
    ]
    pass_index: int = Field(ge=0, le=1)
    requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    probe_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_unique_references(self) -> Self:
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("acquisition action requirement IDs must be unique")
        if len(self.probe_ids) != len(set(self.probe_ids)):
            raise ValueError("acquisition action probe IDs must be unique")
        if self.requirement_ids != sorted(self.requirement_ids):
            raise ValueError("acquisition action requirement IDs must be sorted")
        if self.probe_ids != sorted(self.probe_ids):
            raise ValueError("acquisition action probe IDs must be sorted")
        if self.action_kind == "DETERMINISTIC_PASS" and self.pass_index != 0:
            raise ValueError("deterministic acquisition must be pass zero")
        if self.action_kind != "DETERMINISTIC_PASS" and self.pass_index != 1:
            raise ValueError("residual acquisition work must be pass one")
        expected = _identity_digest(
            {
                "schema_version": self.schema_version,
                "action_kind": self.action_kind,
                "pass_index": self.pass_index,
                "requirement_ids": self.requirement_ids,
                "probe_ids": self.probe_ids,
            }
        )
        if self.action_digest != expected:
            raise ValueError("acquisition action digest does not match its fields")
        return self


class AcquisitionWindowInterval(BaseModel):
    """One inspected turn interval; identity deliberately excludes requirement IDs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-window-v0.1"] = "acquisition-window-v0.1"
    window_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: str = Field(min_length=1)
    turn_start: int = Field(ge=0)
    turn_end_exclusive: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.turn_end_exclusive <= self.turn_start:
            raise ValueError("acquisition window requires start < end")
        expected = _identity_digest(
            {
                "schema_version": self.schema_version,
                "session_id": self.session_id,
                "turn_start": self.turn_start,
                "turn_end_exclusive": self.turn_end_exclusive,
            }
        )
        if self.window_digest != expected:
            raise ValueError("acquisition window digest does not match its fields")
        return self


class AcquisitionRegion(BaseModel):
    """Requirement-aware inspection state for a bounded session region."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-region-v0.1"] = "acquisition-region-v0.1"
    region_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    window_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_ids: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> Self:
        if len(self.requirement_ids) != len(set(self.requirement_ids)):
            raise ValueError("acquisition region requirement IDs must be unique")
        if self.requirement_ids != sorted(self.requirement_ids):
            raise ValueError("acquisition region requirement IDs must be sorted")
        expected = _identity_digest(
            {
                "schema_version": self.schema_version,
                "window_digest": self.window_digest,
                "action_digest": self.action_digest,
                "requirement_ids": self.requirement_ids,
            }
        )
        if self.region_digest != expected:
            raise ValueError("acquisition region digest does not match its fields")
        return self


class EvidenceQuoteSpanRef(BaseModel):
    """Source-exact quote pointer without copying private Evidence text."""

    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Evidence quote span requires start < end")
        return self


class EvidenceReferenceNote(BaseModel):
    """Runtime-built query-local reference; never a replacement for Evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-reference-note-v0.2"] = (
        "evidence-reference-note-v0.2"
    )
    note_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_id: str = Field(min_length=1, max_length=128)
    evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    identity_source: Literal[
        "STRUCTURED_TURN_METADATA",
        "AUTHORITATIVE_BACKFILL",
        "UNKNOWN",
    ]
    quote_span: EvidenceQuoteSpanRef
    interpretation_ref: str = Field(min_length=1)
    observed_terms: list[str] = Field(default_factory=list, max_length=32)
    source_observed_time: datetime | None = None
    event_time: dict[str, JsonValue] | None = None
    note_reason: str = Field(min_length=1, max_length=128)
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_reference_note(self) -> Self:
        if len(self.observed_terms) != len(set(self.observed_terms)):
            raise ValueError("Evidence reference observed terms must be unique")
        if self.source_observed_time is not None and (
            self.source_observed_time.tzinfo is None
            or self.source_observed_time.utcoffset() is None
        ):
            raise ValueError("Evidence reference source time must include timezone offset")
        expected = _identity_digest(
            {
                "schema_version": self.schema_version,
                "requirement_id": self.requirement_id,
                "evidence_id": self.evidence_id,
                "source_turn_ref": self.source_turn_ref,
                "subject_id": self.subject_id,
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "identity_source": self.identity_source,
                "span_id": self.quote_span.span_id,
                "start": self.quote_span.start,
                "end": self.quote_span.end,
                "quote_sha256": self.quote_span.quote_sha256,
                "interpretation_ref": self.interpretation_ref,
                "observed_terms": self.observed_terms,
                "source_observed_time": (
                    self.source_observed_time.isoformat()
                    if self.source_observed_time is not None
                    else None
                ),
                "event_time": self.event_time,
                "note_reason": self.note_reason,
                "authority_class": self.authority_class,
                "canonical": self.canonical,
                "canonical_mutation": self.canonical_mutation,
            }
        )
        if self.note_id != expected:
            raise ValueError("Evidence reference note digest does not match its fields")
        return self


class RequirementAcquisitionCoverage(BaseModel):
    """Descriptive Binding coverage; it is not a Sufficiency decision."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1, max_length=128)
    required_minimum: int = Field(ge=0)
    candidate_refs: list[str] = Field(default_factory=list)
    matched_interpretation_refs: list[str] = Field(default_factory=list)
    possible_interpretation_refs: list[str] = Field(default_factory=list)
    rejected_interpretation_refs: list[str] = Field(default_factory=list)
    accepted_evidence_refs: list[str] = Field(default_factory=list)
    covered_by_sufficiency: bool = False

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        reference_groups = (
            self.candidate_refs,
            self.matched_interpretation_refs,
            self.possible_interpretation_refs,
            self.rejected_interpretation_refs,
            self.accepted_evidence_refs,
        )
        if any(len(values) != len(set(values)) for values in reference_groups):
            raise ValueError("acquisition coverage references must be unique")
        if not set(self.accepted_evidence_refs).issubset(self.candidate_refs):
            raise ValueError("accepted Evidence must remain in the requirement candidate set")
        return self


def _identity_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AcquisitionState(BaseModel):
    """Cross-pass state scoped to one resolve call, never reusable Memory truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-state-v0.1"] = "acquisition-state-v0.1"
    query_ir_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_state: RequirementState
    required_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    missing_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    satisfied_requirement_ids: list[str] = Field(default_factory=list, max_length=16)
    prior_actions: list[AcquisitionAction] = Field(default_factory=list, max_length=2)
    residual_model_call_count: int = Field(default=0, ge=0, le=1)
    seen_anchor_ids: list[str] = Field(default_factory=list, max_length=256)
    seen_window_intervals: list[AcquisitionWindowInterval] = Field(
        default_factory=list, max_length=256
    )
    inspected_regions: list[AcquisitionRegion] = Field(default_factory=list, max_length=256)
    exhausted_regions: list[AcquisitionRegion] = Field(default_factory=list, max_length=256)
    accepted_evidence_refs: list[EvidenceReferenceNote] = Field(
        default_factory=list, max_length=256
    )
    per_requirement_candidate_refs: dict[str, list[str]] = Field(default_factory=dict)
    per_requirement_coverage: dict[str, RequirementAcquisitionCoverage] = Field(
        default_factory=dict
    )
    remaining_budget: AcquisitionRemainingBudget
    lifetime: Literal["MEMORY_RESOLVE"] = "MEMORY_RESOLVE"
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_query_local_state(self) -> Self:
        required = self.required_requirement_ids
        missing = self.missing_requirement_ids
        satisfied = self.satisfied_requirement_ids
        if any(len(values) != len(set(values)) for values in (required, missing, satisfied)):
            raise ValueError("AcquisitionState requirement IDs must be unique")
        if set(missing).intersection(satisfied):
            raise ValueError("missing and satisfied requirements must be disjoint")
        if set(missing).union(satisfied) != set(required):
            raise ValueError("missing and satisfied requirements must partition required IDs")
        state_required = [
            item.requirement_id for item in self.requirement_state.requirements
        ]
        if required != state_required:
            raise ValueError("AcquisitionState requirements must match RequirementState")
        if missing != self.requirement_state.missing_requirement_ids:
            raise ValueError("missing requirements must be derived from RequirementState")
        if satisfied != self.requirement_state.satisfied_requirement_ids:
            raise ValueError("satisfied requirements must be derived from RequirementState")
        if self.query_ir_digest != self.requirement_state.query_ir_digest:
            raise ValueError("AcquisitionState query identity must match RequirementState")
        if self.acquisition_plan_digest != self.requirement_state.acquisition_plan_digest:
            raise ValueError("AcquisitionState plan identity must match RequirementState")
        if set(self.per_requirement_candidate_refs) != set(required):
            raise ValueError("candidate coverage must address every required requirement")
        if set(self.per_requirement_coverage) != set(required):
            raise ValueError("typed coverage must address every required requirement")
        for requirement_id in required:
            candidate_refs = self.per_requirement_candidate_refs[requirement_id]
            coverage = self.per_requirement_coverage[requirement_id]
            if len(candidate_refs) != len(set(candidate_refs)):
                raise ValueError("per-requirement candidate references must be unique")
            if coverage.requirement_id != requirement_id:
                raise ValueError("coverage requirement identity mismatch")
            if coverage.candidate_refs != candidate_refs:
                raise ValueError("candidate reference views must remain identical")
            if coverage.covered_by_sufficiency != (requirement_id in satisfied):
                raise ValueError("coverage cannot redefine the Sufficiency disposition")
        if len(self.prior_actions) != len({item.action_digest for item in self.prior_actions}):
            raise ValueError("prior acquisition actions must be unique")
        if self.residual_model_call_count and (
            not self.prior_actions
            or self.prior_actions[0].action_kind != "DETERMINISTIC_PASS"
        ):
            raise ValueError("residual controller call requires deterministic pass zero")
        if len(self.seen_anchor_ids) != len(set(self.seen_anchor_ids)):
            raise ValueError("seen anchors must be unique")
        if len(self.seen_window_intervals) != len(
            {item.window_digest for item in self.seen_window_intervals}
        ):
            raise ValueError("seen windows must be unique")
        if len(self.inspected_regions) != len(
            {item.region_digest for item in self.inspected_regions}
        ):
            raise ValueError("inspected regions must be unique")
        if len(self.exhausted_regions) != len(
            {item.region_digest for item in self.exhausted_regions}
        ):
            raise ValueError("exhausted regions must be unique")
        inspected = {item.region_digest for item in self.inspected_regions}
        if not {item.region_digest for item in self.exhausted_regions}.issubset(inspected):
            raise ValueError("an exhausted region must first be inspected")
        if len(self.accepted_evidence_refs) != len(
            {item.note_id for item in self.accepted_evidence_refs}
        ):
            raise ValueError("accepted Evidence reference notes must be unique")
        for note in self.accepted_evidence_refs:
            if note.requirement_id not in required:
                raise ValueError("Evidence reference note addresses an unknown requirement")
            coverage = self.per_requirement_coverage[note.requirement_id]
            if note.evidence_id not in coverage.accepted_evidence_refs:
                raise ValueError("Evidence reference note is absent from typed coverage")
        return self


__all__ = [
    "AcquisitionAction",
    "AcquisitionBudget",
    "AcquisitionBudgetUse",
    "AcquisitionChannel",
    "AcquisitionEvidenceSourcePolicy",
    "AcquisitionExpansionPolicy",
    "AcquisitionFusion",
    "AcquisitionGlobalConstraints",
    "AcquisitionPlan",
    "AcquisitionProbe",
    "AcquisitionRegion",
    "AcquisitionRemainingBudget",
    "AcquisitionResidualPolicy",
    "AcquisitionSemanticSubject",
    "AcquisitionSourceProvenance",
    "AcquisitionSourceSpeaker",
    "AcquisitionState",
    "AcquisitionTemporalAxis",
    "AcquisitionWindowInterval",
    "CandidateEnvelope",
    "EvidenceQuoteSpanRef",
    "EvidenceReferenceNote",
    "RequirementAcquisitionCoverage",
]
