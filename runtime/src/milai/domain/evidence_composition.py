"""DG-16 v0.1 contracts for query-conditioned Raw Evidence composition."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue

from milai.domain.retrieval import QueryPlan

CompositionOperator = Literal[
    "DIVIDE_EVIDENCE_VALUES",
    "TEMPORAL_COUNT_DISTINCT",
]
CompositionStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "ABSENT",
    "CONTESTED",
    "DENIED",
    "UNAVAILABLE",
]
SlotName = Literal["TOTAL_PRICE", "ITEM_COUNT", "MATCHING_EVENTS_IN_RANGE"]


class TemporalRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    boundary: Literal["CLOSED_OPEN"] = "CLOSED_OPEN"


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_roles: list[Literal["user", "assistant"]]
    adjacency_hops: int = Field(ge=0, le=2)
    provenance_required: Literal[True] = True


class QuerySpec(BaseModel):
    """Only the two operator shapes exercised by the focal verticals."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["query-spec-v0.1"] = "query-spec-v0.1"
    answer_type: Literal["SCALAR"] = "SCALAR"
    operator: CompositionOperator
    entities: list[str]
    predicates: list[str]
    temporal_range: TemporalRange | None = None
    required_slots: list[SlotName]
    completeness: Literal["ALL_MATCHES_IN_RANGE", "ALL_REQUIRED_SLOTS"]
    evidence_policy: EvidencePolicy


class EvidenceSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SlotName
    status: Literal["FILLED", "MISSING", "AMBIGUOUS", "INCOMPLETE"]
    operands: list[dict[str, JsonValue]] = Field(default_factory=list)
    unresolved_reason: str | None = None


class EvidenceApplicabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_turn_ref: str
    slot: SlotName
    accepted: bool
    reason: str
    span: str | dict[str, JsonValue] | None = None


class OperatorTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_spec: QuerySpec
    slots: list[EvidenceSlot]
    applicability: list[EvidenceApplicabilityResult]
    retrieval_attempts: int = Field(ge=0)
    expansion: list[str]
    join: str
    terminal_reason: str
    top_k_used_as_completeness: Literal[False] = False
    hidden_model_calls: Literal[0] = 0
    canonical_mutation: Literal[False] = False


class CompositionCompleteness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_slots: list[SlotName]
    filled_slots: list[SlotName]
    bounded_scan_complete: bool
    temporal_range_resolved: bool | None = None
    source_partition_closed: bool | None = None
    projection_watermark_covered: bool | None = None
    projection_position: int | None = None
    target_position: int | None = None
    query_temporal_axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"] | None = None
    scan_temporal_axis: Literal["SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"] | None = None
    temporal_domain_coverage: Literal["EXACT_AXIS_RANGE", "UNPROVEN"] | None = None
    deduplication_proven: bool | None = None
    unresolved_reasons: list[str]


class EvidenceCompositionResult(BaseModel):
    """Turn-local result. It is explicitly non-canonical and never persisted as truth."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["EVIDENCE_COMPOSITION_RESULT"] = "EVIDENCE_COMPOSITION_RESULT"
    status: CompositionStatus
    operator: CompositionOperator
    result: JsonValue | None = Field(
        default=None,
        validation_alias=AliasChoices("result", "value"),
        serialization_alias="value",
    )
    unit: str | None
    display_value: str | None = None
    reason: str | None = None
    route_reason: str | None = None
    slot_schema_version: str | None = None
    operands: list[dict[str, JsonValue]]
    evidence_refs: list[str]
    source_turn_refs: list[str]
    completeness: CompositionCompleteness
    trace: OperatorTrace
    entity_compatibility: str | None = None
    unit_compatibility: str | None = None
    count_trace: dict[str, JsonValue] | None = None
    top_k_used_as_completeness: Literal[False] = False
    hidden_model_calls: Literal[0] = 0
    canonical_mutation: Literal[False] = False

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def query_spec_from_plan(plan: QueryPlan) -> QuerySpec | None:
    """Project the existing internal QueryPlan into the frozen v0.1 contract."""

    if plan.operator not in {
        "DIVIDE_EVIDENCE_VALUES",
        "TEMPORAL_COUNT_DISTINCT",
    }:
        return None
    arguments = plan.operator_arguments
    required_raw = arguments.get("required_slots")
    if not isinstance(required_raw, list) or not all(
        value in {"TOTAL_PRICE", "ITEM_COUNT", "MATCHING_EVENTS_IN_RANGE"} for value in required_raw
    ):
        return None
    required_slots = cast(list[SlotName], required_raw)
    completeness = arguments.get("completeness")
    if completeness not in {"ALL_MATCHES_IN_RANGE", "ALL_REQUIRED_SLOTS"}:
        return None
    temporal_raw = arguments.get("temporal_range")
    temporal = None
    if temporal_raw is not None:
        if not isinstance(temporal_raw, dict):
            return None
        try:
            temporal = TemporalRange.model_validate(temporal_raw)
        except ValueError:
            return None
    entity_terms = arguments.get("entity_terms")
    entities = (
        [" ".join(cast(list[str], entity_terms))]
        if isinstance(entity_terms, list)
        and entity_terms
        and all(isinstance(value, str) and value for value in entity_terms)
        else []
    )
    predicates = [str(arguments["event_type"])] if "event_type" in arguments else []
    return QuerySpec(
        operator=cast(CompositionOperator, plan.operator),
        entities=entities,
        predicates=predicates,
        temporal_range=temporal,
        required_slots=required_slots,
        completeness=cast(Literal["ALL_MATCHES_IN_RANGE", "ALL_REQUIRED_SLOTS"], completeness),
        evidence_policy=EvidencePolicy(
            source_roles=["user"], adjacency_hops=0, provenance_required=True
        ),
    )


__all__ = [
    "CompositionCompleteness",
    "EvidenceApplicabilityResult",
    "EvidenceCompositionResult",
    "EvidencePolicy",
    "EvidenceSlot",
    "OperatorTrace",
    "QuerySpec",
    "TemporalRange",
    "query_spec_from_plan",
]
