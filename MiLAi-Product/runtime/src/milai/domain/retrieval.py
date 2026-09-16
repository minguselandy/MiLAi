from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic.json_schema import SkipJsonSchema

from milai.domain.query_execution import QueryExecutionPlanV01
from milai.domain.query_task_contract import QueryTaskContractV01
from milai.domain.semantic_query import MemoryQueryIRV02

RetrievalRoute = Literal["L0", "L1", "L2"]
RetrievalConsistency = Literal["EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"]
RetrievalAuthority = Literal["INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"]
RetrievalLifecycle = Literal["ACTIVE", "SUPERSEDED", "ARCHIVED", "DELETED"]
RetrievalEpistemic = Literal["PROVISIONAL", "VERIFIED", "CHALLENGED", "UNPROVABLE"]
RetrievalFreshness = Literal["CURRENT", "STALE"]
MemoryIntent = Literal["NONE", "CURRENT_STATE", "HISTORY", "CONFLICT", "EXPLANATION"]
EvidenceNeed = Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"]
QueryOperator = Literal[
    "TEMPORAL_BEFORE_AFTER",
    "TEMPORAL_DISTANCE",
    "LATEST_VALID_STATE",
    "COUNT_DISTINCT",
    "SUM_VALUES",
    "COMPARE_EVENTS",
    "DIVIDE_EVIDENCE_VALUES",
    "TEMPORAL_COUNT_DISTINCT",
    "COMPARE_EVENT_IDENTITY",
    "COMPOSE_STATE",
]


def _default_epistemic_statuses() -> list[RetrievalEpistemic]:
    return ["VERIFIED", "PROVISIONAL"]


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    route: RetrievalRoute
    consistency: RetrievalConsistency = "EVENTUAL"
    query: str | None = Field(default=None, min_length=1, max_length=2_000)
    entities: list[str] = Field(default_factory=list, max_length=32)
    memory_types: list[str] = Field(default_factory=list, max_length=16)
    memory_intent: MemoryIntent | None = None
    evidence_need: EvidenceNeed | None = None
    claim_id: UUID | None = None
    subject_id: str | None = Field(default=None, min_length=1, max_length=512)
    predicate: str | None = Field(default=None, min_length=1, max_length=255)
    claim_type: str | None = Field(default=None, min_length=1, max_length=255)
    requested_scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority = "INFORMATIONAL"
    required_lifecycle: RetrievalLifecycle = "ACTIVE"
    accepted_epistemic_statuses: list[RetrievalEpistemic] = Field(
        default_factory=_default_epistemic_statuses, min_length=1
    )
    required_freshness: RetrievalFreshness = "CURRENT"
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reference_time: datetime | None = None
    system_as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    causal_token: str | None = Field(default=None, min_length=16, max_length=512)
    causal_wait_timeout_ms: int = Field(default=250, ge=0, le=2_000)
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def validate_route_shape(self) -> Self:
        identity = (self.subject_id, self.predicate, self.claim_type)
        if self.route == "L0" and self.claim_id is None and not all(identity):
            raise ValueError("L0 requires claim_id or a complete Claim identity")
        if self.route == "L1" and self.query is None:
            raise ValueError("L1 requires query")
        if self.required_authority == "ACTION_SAFE" and not self.requested_scope:
            raise ValueError("ACTION_SAFE retrieval requires a non-empty requested_scope")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset")
        if self.reference_time is not None and (
            self.reference_time.tzinfo is None or self.reference_time.utcoffset() is None
        ):
            raise ValueError("reference_time must include a timezone offset")
        if self.system_as_of.tzinfo is None or self.system_as_of.utcoffset() is None:
            raise ValueError("system_as_of must include a timezone offset")
        if len(set(self.accepted_epistemic_statuses)) != len(self.accepted_epistemic_statuses):
            raise ValueError("accepted_epistemic_statuses cannot contain duplicates")
        if self.consistency == "READ_YOUR_WRITES" and self.causal_token is None:
            raise ValueError("READ_YOUR_WRITES requires a causal_token")
        if self.consistency != "READ_YOUR_WRITES" and self.causal_token is not None:
            raise ValueError("causal_token is only valid for READ_YOUR_WRITES")
        return self


class QueryPlan(BaseModel):
    """Versioned deterministic plan consumed by retrieval and persisted in its trace."""

    model_config = ConfigDict(extra="forbid")

    planner_version: str = "lean-query-plan-v12-dg17-ir-v02"
    intent: Literal["EXACT_CURRENT", "HYBRID_SEARCH"]
    entities: list[str]
    time_constraint: dict[str, JsonValue]
    scope_predicate: dict[str, JsonValue]
    required_authority: RetrievalAuthority
    required_lifecycle: RetrievalLifecycle
    accepted_epistemic_statuses: list[RetrievalEpistemic]
    required_freshness: RetrievalFreshness
    minimum_confidence: float
    require_user_confirmation: bool
    complexity: RetrievalRoute
    consistency_mode: RetrievalConsistency
    minimum_outbox_sequence: int | None
    context_budget: int
    access_intent: Literal["POSSIBLE", "REQUIRED"] | None = None
    candidate_cap: int = Field(default=256, ge=1, le=256)
    deadline_ms: int = Field(default=2_000, ge=1, le=10_000)
    reranker_candidate_cap: int = Field(default=20, ge=0, le=120)
    hard_partitions: list[str] = Field(default_factory=list)
    vector_policy: Literal["LEGACY", "SPARSE_INSUFFICIENCY_ONLY"] = "LEGACY"
    reranker_policy: Literal["LEGACY", "CONDITIONAL_SMALL_SET"] = "LEGACY"
    routes: list[RetrievalRoute]
    operator: QueryOperator | None = None
    operator_arguments: dict[str, JsonValue] = Field(default_factory=dict)
    memory_query_ir: MemoryQueryIRV02 | None = None
    # Internal semantic authority for the query-local read path.  These fields
    # deliberately do not cross the existing public QueryPlan serialization
    # surface while v0.2 remains the compatibility wire representation.
    query_task_contract: SkipJsonSchema[QueryTaskContractV01 | None] = Field(
        default=None,
        exclude=True,
    )
    query_execution_plan: SkipJsonSchema[QueryExecutionPlanV01 | None] = Field(
        default=None,
        exclude=True,
    )
    time_reference: datetime
