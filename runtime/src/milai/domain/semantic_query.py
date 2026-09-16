"""DG-17 v0.2 semantic-query and evidence interpretation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SemanticRoute = Literal["STATE", "EVIDENCE", "COMPOSE", "AMBIGUOUS"]
SemanticOperatorFamily = Literal[
    "LOOKUP",
    "TEMPORAL_FILTER",
    "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE",
    "COUNT",
    "SUM",
    "AVERAGE",
    "DIVIDE",
    "COMPARE",
    "MULTI_JOIN",
    "WHY_CHANGE",
    "EVENT_IDENTITY_COMPARE",
    "COMPOSE_STATE",
]
MemoryAnswerShape = Literal[
    "SCALAR",
    "LIST",
    "STATE",
    "TIMELINE",
    "EXPLANATION",
    "SUMMARY",
]
MemoryPlanStepKind = Literal[
    "RETRIEVE",
    "FILTER",
    "EXPAND_NEIGHBOR",
    "EXPAND_EPISODE",
    "TEMPORAL_SCAN",
    "BIND_SLOT",
    "JOIN",
    "DEDUPLICATE",
    "REDUCE",
    "COMPARE",
]
MemoryCompletenessV02 = Literal[
    "TOP_K_ACCEPTABLE",
    "ALL_REQUIRED_BINDINGS",
    "ALL_MATCHES_IN_RANGE",
    "COMPLETE_VERSION_CHAIN",
    "SUPPORT_THRESHOLD",
    "UNSTRUCTURED_EVIDENCE_ALLOWED",
]
InterpretationKind = Literal[
    "EVENT",
    "QUANTITY",
    "STATE_OBSERVATION",
    "PREFERENCE_SIGNAL",
    "DECISION",
    "RELATION",
]
InterpretationTimeBasis = Literal[
    "EXPLICIT_EVENT_TIME",
    "INFERRED_EVENT_TIME",
    "SOURCE_OBSERVED_TIME",
    "UNRESOLVED",
]
CompatibilityStatus = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
EvidenceSourceSpeaker = Literal["USER", "ASSISTANT", "SYSTEM", "TOOL"]
EvidenceSourceProvenance = Literal[
    "EXPLICIT_QUERY",
    "TYPED_HINT",
    "SEMANTIC_PARSER",
    "NONE",
]


class QueryCueSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end <= self.start:
            raise ValueError("cue span end must be greater than start")
        if len(self.text) != self.end - self.start:
            raise ValueError("cue span length must equal end-start")
        return self


class SemanticQueryHint(BaseModel):
    """Untrusted, non-executable semantic hint; it carries no authority."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["semantic-query-hint-v0.1"] = "semantic-query-hint-v0.1"
    route: SemanticRoute
    operator_family: SemanticOperatorFamily
    cue_spans: list[QueryCueSpan] = Field(default_factory=list, max_length=16)
    temporal_spans: list[QueryCueSpan] = Field(default_factory=list, max_length=8)
    requires_complete_set: bool = False
    ambiguities: list[str] = Field(default_factory=list, max_length=16)


class SemanticHintTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_ms: float = Field(ge=0.0)
    ttft_ms: float = Field(ge=0.0)
    decode_ms: float = Field(ge=0.0)
    total_ms: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_ms + 1e-6 < self.queue_ms + self.ttft_ms + self.decode_ms:
            raise ValueError("semantic hint total_ms is below measured components")
        return self


class SemanticHintReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["semantic-hint-receipt-v0.1"] = "semantic-hint-receipt-v0.1"
    hint: SemanticQueryHint
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0, le=96)
    tokenizer_latency_ms: float = Field(ge=0.0)
    timing: SemanticHintTiming
    automatic_retry_count: Literal[0] = 0
    auxiliary_model_calls: Literal[1] = 1


class NormalizedTemporalConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_time: datetime
    start: datetime | None = None
    end: datetime | None = None
    boundary: Literal["CLOSED_OPEN", "CLOSED_CLOSED", "POINT", "UNBOUNDED"]
    time_axis: Literal["EVENT_TIME", "SOURCE_OBSERVED_TIME"] = "EVENT_TIME"
    precision: Literal["DAY", "HOUR", "MINUTE"] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    normalized_from: list[QueryCueSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        for value in (self.reference_time, self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("temporal values must include timezone offsets")
        if self.boundary == "POINT":
            if self.start is None or self.end is None or self.start != self.end:
                raise ValueError("POINT requires equal start and end")
            if (self.precision is None) != (self.timezone is None):
                raise ValueError("POINT precision and timezone must be declared together")
        elif self.boundary == "UNBOUNDED":
            if self.start is not None or self.end is not None:
                raise ValueError("UNBOUNDED cannot carry absolute bounds")
        elif self.start is None or self.end is None or self.start >= self.end:
            raise ValueError("bounded temporal interval requires start < end")
        return self


class RequirementCardinalityV02(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: int = Field(default=1, ge=0)
    maximum: int | None = Field(default=1, ge=1)
    distinct: bool = False

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum cardinality cannot be below minimum")
        return self


class RequirementSemanticRolesV02(BaseModel):
    """Event participants; these are not Evidence source-speaker constraints."""

    model_config = ConfigDict(extra="forbid")

    actor: str | None = Field(default=None, min_length=1, max_length=256)
    experiencer: str | None = Field(default=None, min_length=1, max_length=256)
    beneficiary: str | None = Field(default=None, min_length=1, max_length=256)


class EvidenceSourcePolicyV02(BaseModel):
    """Per-requirement source semantics emitted by the planner/parser boundary."""

    model_config = ConfigDict(extra="forbid")

    preferred_speakers: list[EvidenceSourceSpeaker] = Field(default_factory=list, max_length=4)
    allowed_speakers: list[EvidenceSourceSpeaker] | None = Field(
        default=None, min_length=1, max_length=4
    )
    provenance: EvidenceSourceProvenance = "NONE"

    @model_validator(mode="after")
    def validate_source_semantics(self) -> Self:
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


class EvidenceRequirementV02(BaseModel):
    """Query-local interpretation constraint; never persisted as Memory truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-requirement-v0.2"] = "evidence-requirement-v0.2"
    slot_id: str = Field(min_length=1, max_length=128)
    interpretation_kind: InterpretationKind
    entity_constraints: list[str] = Field(default_factory=list, max_length=32)
    predicate_constraints: list[str] = Field(default_factory=list, max_length=16)
    temporal_constraints: NormalizedTemporalConstraint | None = None
    semantic_roles: RequirementSemanticRolesV02 = Field(default_factory=RequirementSemanticRolesV02)
    evidence_source: EvidenceSourcePolicyV02 = Field(default_factory=EvidenceSourcePolicyV02)
    value_type: (
        Literal[
            "STRING",
            "NUMBER",
            "DATE",
            "DATETIME",
            "DURATION",
            "BOOLEAN",
            "ENTITY",
            "ANY",
        ]
        | None
    ) = None
    cardinality: RequirementCardinalityV02 = Field(default_factory=RequirementCardinalityV02)
    join_key: str | None = Field(default=None, min_length=1, max_length=128)
    required: bool = True


class LexicalCueSetV01(BaseModel):
    """Planner-owned lexical surfaces; no semantic synonym authority."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["lexical-cue-set-v0.1"] = "lexical-cue-set-v0.1"
    requirement_slot: str = Field(min_length=1, max_length=128)
    surface_terms: list[str] = Field(default_factory=list, max_length=64)
    morphological_variants: list[str] = Field(default_factory=list, max_length=64)
    entity_aliases: list[str] = Field(default_factory=list, max_length=32)
    relation_cues: list[str] = Field(default_factory=list, max_length=32)
    language_tags: list[str] = Field(default_factory=list, max_length=8)
    provenance: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_cues(self) -> Self:
        groups = (
            self.surface_terms,
            self.morphological_variants,
            self.entity_aliases,
            self.relation_cues,
            self.language_tags,
            self.provenance,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("LexicalCueSet fields must contain unique values")
        return self


class MemoryQueryConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_spans: list[QueryCueSpan] = Field(default_factory=list, max_length=32)
    state_addresses: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=16)
    temporal_expressions: list[QueryCueSpan] = Field(default_factory=list, max_length=16)
    normalized_temporal: NormalizedTemporalConstraint | None = None
    scope: dict[str, JsonValue] | None = None


class MemoryQueryStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryPlanStepKind
    inputs: list[str] = Field(default_factory=list, max_length=32)
    outputs: list[str] = Field(default_factory=list, max_length=32)
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    budget: dict[str, JsonValue] = Field(default_factory=dict)


class MemoryPlannerTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["DETERMINISTIC", "SEMANTIC_REPAIR", "AMBIGUOUS"]
    compiler_version: str = Field(min_length=1)
    hint_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    auxiliary_model_calls: int = Field(ge=0, le=1)
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source == "SEMANTIC_REPAIR":
            if self.hint_digest is None or self.auxiliary_model_calls != 1:
                raise ValueError("SEMANTIC_REPAIR requires one receipted hint")
        elif self.hint_digest is not None or self.auxiliary_model_calls != 0:
            raise ValueError("non-model plan cannot carry a hint/model call")
        return self


class MemoryQueryIRV02(BaseModel):
    """The only executable semantic plan owned by deterministic Runtime synthesis."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["memory-query-ir-v0.2"] = "memory-query-ir-v0.2"
    mode: SemanticRoute
    answer_shape: MemoryAnswerShape
    constraints: MemoryQueryConstraints = Field(default_factory=MemoryQueryConstraints)
    requirements: list[EvidenceRequirementV02] = Field(default_factory=list, max_length=16)
    lexical_cues: list[LexicalCueSetV01] = Field(default_factory=list, max_length=16)
    steps: list[MemoryQueryStep] = Field(default_factory=list, max_length=32)
    completeness: MemoryCompletenessV02
    planner_trace: MemoryPlannerTrace

    @model_validator(mode="after")
    def validate_executable_shape(self) -> Self:
        if self.mode == "AMBIGUOUS":
            if self.steps or self.planner_trace.source != "AMBIGUOUS":
                raise ValueError("AMBIGUOUS IR cannot carry executable steps")
        elif not self.steps:
            raise ValueError("executable MemoryQueryIR requires at least one step")
        required_ids = {item.slot_id for item in self.requirements if item.required}
        cue_slots = [item.requirement_slot for item in self.lexical_cues]
        if len(cue_slots) != len(set(cue_slots)) or not set(cue_slots).issubset(
            {item.slot_id for item in self.requirements}
        ):
            raise ValueError("lexical cue sets must uniquely address requirements")
        bound_ids = {
            output for step in self.steps if step.kind == "BIND_SLOT" for output in step.outputs
        }
        if self.completeness in {
            "ALL_REQUIRED_BINDINGS",
            "ALL_MATCHES_IN_RANGE",
            "SUPPORT_THRESHOLD",
        } and not required_ids.issubset(bound_ids):
            raise ValueError("completeness-required IR must bind every required slot")
        operator_families = {
            value
            for step in self.steps
            if isinstance((value := step.constraints.get("operator_family")), str) and value
        }
        if self.mode != "AMBIGUOUS" and len(operator_families) != 1:
            raise ValueError("executable MemoryQueryIR requires one operator family owner")
        operator_family = next(iter(operator_families), None)
        target_event = next(
            (
                requirement
                for requirement in self.requirements
                if requirement.required and requirement.slot_id == "TARGET_EVENT"
            ),
            None,
        )
        if target_event is not None and operator_family != "TEMPORAL_FILTER":
            raise ValueError("TARGET_EVENT cannot collapse to a non-temporal operator")
        if operator_family == "TEMPORAL_FILTER" and not any(
            requirement.required and requirement.interpretation_kind == "EVENT"
            for requirement in self.requirements
        ):
            raise ValueError("TEMPORAL_FILTER requires a typed event binding")
        if operator_family in {"TEMPORAL_ORDER", "TEMPORAL_DISTANCE"}:
            required_events = [
                requirement
                for requirement in self.requirements
                if requirement.required and requirement.interpretation_kind == "EVENT"
            ]
            reference_distance = (
                operator_family == "TEMPORAL_DISTANCE"
                and len(required_events) == 1
                and required_events[0].slot_id == "REFERENCE_EVENT"
                and "distance_mode:from_reference" in required_events[0].predicate_constraints
            )
            if len(required_events) < 2 and not reference_distance:
                raise ValueError(f"{operator_family} requires at least two typed event bindings")
        return self


class EvidenceSpan(BaseModel):
    """Exact source pointer with no semantic interpretation or slot role."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-span-v0.2"] = "evidence-span-v0.2"
    span_id: str = Field(min_length=1)
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
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_timestamp: datetime | None = None
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end <= self.start or len(self.text) != self.end - self.start:
            raise ValueError("EvidenceSpan offsets must exactly cover text")
        if self.source_timestamp is not None and (
            self.source_timestamp.tzinfo is None or self.source_timestamp.utcoffset() is None
        ):
            raise ValueError("source_timestamp must include timezone offset")
        return self


class InterpretationEventTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime | None = None
    end: datetime | None = None
    normalized_from: str | None = None
    anchor_provenance: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        for value in (self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("event time must include timezone offset")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("event start cannot exceed end")
        return self


class EvidenceInterpretationCandidate(BaseModel):
    """Fallible meaning candidate; it is neither a slot binding nor Memory truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-interpretation-v0.1"] = "evidence-interpretation-v0.1"
    interpretation_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    kind: InterpretationKind
    value: JsonValue | None = None
    unit: str | None = None
    entities: list[str] = Field(default_factory=list, max_length=32)
    predicate: str | None = None
    event_time: InterpretationEventTime | None = None
    time_basis: InterpretationTimeBasis = "UNRESOLVED"
    extractor_identity: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rebuildable: Literal[True] = True
    canonical: Literal[False] = False
    canonical_mutation: Literal[False] = False

    @model_validator(mode="after")
    def validate_time_basis(self) -> Self:
        if self.time_basis in {"EXPLICIT_EVENT_TIME", "INFERRED_EVENT_TIME"}:
            if self.event_time is None or self.event_time.start is None:
                raise ValueError("resolved event-time basis requires event_time")
        if self.time_basis == "SOURCE_OBSERVED_TIME" and self.event_time is not None:
            raise ValueError("source time fallback must not masquerade as event_time")
        return self


class BindingCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CompatibilityStatus
    entity: CompatibilityStatus
    predicate: CompatibilityStatus = "NOT_APPLICABLE"
    source: CompatibilityStatus = "NOT_APPLICABLE"
    role: CompatibilityStatus = "NOT_APPLICABLE"
    unit: CompatibilityStatus
    temporal: CompatibilityStatus
    episode: CompatibilityStatus


class NonTemporalApplicability(BaseModel):
    """Auditable applicability before temporal resolution and final Binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["non-temporal-applicability-v0.1"] = "non-temporal-applicability-v0.1"
    requirement_id: str = Field(min_length=1)
    interpretation_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    type: CompatibilityStatus
    entity: CompatibilityStatus
    predicate: CompatibilityStatus
    source: CompatibilityStatus
    role: CompatibilityStatus
    status: Literal["MATCH", "POSSIBLE", "REJECTED"]
    reason_code: str = Field(min_length=1)
    exact_source_span_verified: Literal[True] = True
    canonical_mutation: Literal[False] = False


class RequirementBinding(BaseModel):
    """Deterministic query-local validation of one interpretation for one slot."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["requirement-binding-v0.1", "requirement-binding-v0.2"] = (
        "requirement-binding-v0.1"
    )
    requirement_id: str = Field(min_length=1)
    interpretation_id: str = Field(min_length=1)
    status: Literal["MATCH", "POSSIBLE", "REJECTED"]
    compatibility: BindingCompatibility
    reason_code: str = Field(min_length=1)
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    canonical_mutation: Literal[False] = False


class TypeDirectedSemanticAudit(BaseModel):
    """Cost/safety counters for requirement-directed interpretation and Binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["type-directed-semantic-audit-v0.1"] = (
        "type-directed-semantic-audit-v0.1"
    )
    allowed_interpretation_kinds: list[InterpretationKind]
    span_count: int = Field(ge=0)
    suppressed_interpretation_count: int = Field(ge=0)
    materialized_interpretation_count: int = Field(ge=0)
    legacy_binding_evaluation_count: int = Field(ge=0)
    binding_evaluation_count: int = Field(ge=0)
    type_pruned_before_binding_count: int = Field(ge=0)
    materialized_type_mismatch_count: Literal[0] = 0
    exact_source_span_failure_count: Literal[0] = 0

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.binding_evaluation_count + self.type_pruned_before_binding_count != (
            self.legacy_binding_evaluation_count
        ):
            raise ValueError("type-directed Binding accounting is incomplete")
        if self.allowed_interpretation_kinds != sorted(set(self.allowed_interpretation_kinds)):
            raise ValueError("allowed interpretation kinds must be sorted and unique")
        return self


def validate_query_hint_spans(query: str, hint: SemanticQueryHint) -> None:
    """Reject non-exact or out-of-range model cues at the trust boundary."""

    for span in [*hint.cue_spans, *hint.temporal_spans]:
        if span.end > len(query) or query[span.start : span.end] != span.text:
            raise ValueError("SEMANTIC_HINT_CUE_SPAN_MISMATCH")


__all__ = [
    "BindingCompatibility",
    "EvidenceInterpretationCandidate",
    "EvidenceRequirementV02",
    "EvidenceSourcePolicyV02",
    "EvidenceSourceProvenance",
    "EvidenceSourceSpeaker",
    "EvidenceSpan",
    "InterpretationEventTime",
    "InterpretationKind",
    "LexicalCueSetV01",
    "MemoryPlannerTrace",
    "MemoryQueryConstraints",
    "MemoryQueryIRV02",
    "MemoryQueryStep",
    "NonTemporalApplicability",
    "NormalizedTemporalConstraint",
    "QueryCueSpan",
    "RequirementBinding",
    "RequirementCardinalityV02",
    "RequirementSemanticRolesV02",
    "SemanticHintReceipt",
    "SemanticHintTiming",
    "SemanticQueryHint",
    "TypeDirectedSemanticAudit",
    "validate_query_hint_spans",
]
