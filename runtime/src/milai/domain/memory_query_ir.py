from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MemoryQueryClass = Literal[
    "STATE",
    "EPISODIC",
    "TEMPORAL",
    "AGGREGATION",
    "PREFERENCE",
    "EXPLANATION",
]
MemoryAnswerType = Literal["SCALAR", "LIST", "STATE", "TIMELINE", "EXPLANATION"]
MemoryQueryOperator = Literal[
    "LOOKUP",
    "STATE_AT_TIME",
    "TEMPORAL_FILTER",
    "TEMPORAL_ORDER",
    "TEMPORAL_DISTANCE",
    "COUNT_DISTINCT",
    "SUM_VALUES",
    "DIVIDE_VALUES",
    "COMPARE_VALUES",
    "MULTI_EVIDENCE_JOIN",
    "PREFERENCE_RESOLVE",
    "VERSION_DIFF",
]
MemoryCompleteness = Literal[
    "TOP_K_ACCEPTABLE",
    "ALL_REQUIRED_SLOTS",
    "ALL_MATCHES_IN_RANGE",
    "COMPLETE_VERSION_CHAIN",
    "SUPPORT_THRESHOLD",
]
EvidenceAtomType = Literal[
    "EVENT",
    "QUANTITY",
    "STATE_OBSERVATION",
    "PREFERENCE_SIGNAL",
    "DECISION",
    "RELATION",
]
EvidenceValueType = Literal[
    "STRING",
    "NUMBER",
    "DATE",
    "DATETIME",
    "DURATION",
    "BOOLEAN",
    "ENTITY",
    "ANY",
]


class TemporalConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_time: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    boundary: Literal["CLOSED_OPEN", "CLOSED_CLOSED", "POINT", "UNBOUNDED"] | None = None
    normalized_from: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        for value in (self.reference_time, self.start, self.end):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("temporal values must include timezone offsets")
        if self.boundary == "POINT":
            if self.start is None or self.end is None or self.start != self.end:
                raise ValueError("POINT temporal constraint requires equal start and end")
        elif self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("temporal start must be lower than end")
        return self


class RequirementCardinality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: int = Field(default=1, ge=1)
    maximum: int | None = Field(default=1, ge=1)
    distinct: bool = False

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum cardinality cannot be below minimum")
        return self


class EvidenceRequirement(BaseModel):
    """Query-conditioned slot; never persisted as canonical truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-requirement-v0.1"] = (
        "evidence-requirement-v0.1"
    )
    slot_id: str = Field(min_length=1, max_length=128)
    atom_type: EvidenceAtomType
    entity_constraints: list[str] = Field(default_factory=list, max_length=32)
    predicate_constraints: list[str] = Field(default_factory=list, max_length=16)
    temporal_constraints: TemporalConstraint | None = None
    value_type: EvidenceValueType | None = None
    cardinality: RequirementCardinality = Field(default_factory=RequirementCardinality)
    join_key: str | None = Field(default=None, min_length=1, max_length=128)
    required: bool = True


class QueryParserTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["DETERMINISTIC", "STRUCTURED_MODEL", "AMBIGUOUS"]
    version: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    hidden_model_calls: int = Field(default=0, ge=0)
    reason_code: str = Field(min_length=1)


class MemoryQueryIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["memory-query-ir-v0.1"] = "memory-query-ir-v0.1"
    query_class: MemoryQueryClass
    answer_type: MemoryAnswerType
    operator: MemoryQueryOperator
    entities: list[str] = Field(default_factory=list, max_length=32)
    predicates: list[str] = Field(default_factory=list, max_length=16)
    temporal: TemporalConstraint = Field(default_factory=TemporalConstraint)
    requirements: list[EvidenceRequirement] = Field(default_factory=list, max_length=16)
    completeness: MemoryCompleteness
    parser: QueryParserTrace


class EvidenceTextSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end <= self.start:
            raise ValueError("text span end must be greater than start")
        return self


class EvidenceEventTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime | None = None
    end: datetime | None = None
    normalized_from: str | None = None
    resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidenceAtom(BaseModel):
    """Rebuildable non-canonical semantic projection of an Evidence span."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evidence-atom-v0.1"] = "evidence-atom-v0.1"
    atom_id: str = Field(min_length=1)
    source_evidence_id: str = Field(min_length=1)
    source_turn_ref: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    speaker: str = Field(min_length=1)
    text_span: EvidenceTextSpan
    atom_type: EvidenceAtomType
    entities: list[str] = Field(default_factory=list)
    predicate: str | None = None
    value: JsonValue | None = None
    unit: str | None = None
    event_time: EvidenceEventTime = Field(default_factory=EvidenceEventTime)
    source_timestamp: datetime | None = None
    extractor_identity: str = "deterministic-evidence-atom-v0.1"
    projection_epoch: str = "query-time-v0.1"
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    rebuildable: Literal[True] = True
    canonical: Literal[False] = False
    authority_class: Literal["EVIDENCE_ONLY"] = "EVIDENCE_ONLY"
    canonical_mutation: Literal[False] = False
