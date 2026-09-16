from __future__ import annotations

from datetime import datetime
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.memory_state import CanonicalStateAddress
from milai.domain.retrieval import (
    RetrievalAuthority,
    RetrievalConsistency,
    RetrievalFreshness,
)

MemoryResolveStatus = Literal[
    "HIT",
    "PARTIAL",
    "CONTESTED",
    "ABSENT",
    "ABSTAINED",
    "DENIED",
    "UNAVAILABLE",
]
MemoryIntentLevel = Literal["NOT_NEEDED", "POSSIBLE", "REQUIRED"]
MemoryRequirement = Literal["NONE", "EXACT", "SEARCH", "RECONSTRUCT"]
MemoryAvailability = Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"]
MemoryInvocationMode = Literal["EXPLICIT_READ", "PREFETCH_AUTO"]
TaskActionRiskHint = Literal["LOW", "MEDIUM", "HIGH"]


class MemoryResolveBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(default=10, ge=1, le=50)
    max_candidates: int = Field(default=60, ge=4, le=120)
    max_context_tokens: int = Field(default=2_500, ge=128, le=8_192)
    max_latency_ms: int = Field(default=500, ge=25, le=2_000)

    @model_validator(mode="after")
    def validate_candidate_budget(self) -> Self:
        if self.max_candidates < self.max_results:
            raise ValueError("max_candidates cannot be lower than max_results")
        return self


class TaskContextHint(BaseModel):
    """Optional non-authoritative hints; no Task identity or capability is accepted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_ids: list[str] = Field(default_factory=list, max_length=16)
    entities: list[str] = Field(default_factory=list, max_length=32)
    memory_types: list[str] = Field(default_factory=list, max_length=16)
    action_risk: TaskActionRiskHint | None = None

    @model_validator(mode="after")
    def validate_narrowing_values(self) -> Self:
        for name in ("project_ids", "entities", "memory_types"):
            values = getattr(self, name)
            if any(not value for value in values):
                raise ValueError(f"task_context.{name} cannot contain empty values")
            normalized = [value.casefold() for value in values]
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"task_context.{name} cannot contain duplicates")
        return self


class MemoryResolveRequest(BaseModel):
    """M1 query-first read contract owned by the Memory Runtime.

    Task identity is intentionally absent. Optional TaskContext values are
    narrowing hints only. Scope and policy fields are deployment-bound by the
    MCP facade and may only narrow that ceiling.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2_000)
    invocation_mode: MemoryInvocationMode = "EXPLICIT_READ"
    requested_scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority = "INFORMATIONAL"
    required_freshness: RetrievalFreshness = "CURRENT"
    consistency_mode: RetrievalConsistency = "CANONICAL_REQUIRED"
    causal_token: str | None = Field(default=None, min_length=16, max_length=512)
    budget: MemoryResolveBudget = Field(default_factory=MemoryResolveBudget)
    entities: list[str] = Field(default_factory=list, max_length=32)
    memory_types: list[str] = Field(default_factory=list, max_length=16)
    temporal: dict[str, JsonValue] = Field(default_factory=dict)
    reference_time: datetime | None = None
    state_keys: list[CanonicalStateAddress] = Field(default_factory=list, max_length=8)
    claim_ids: list[UUID] = Field(default_factory=list, max_length=8)
    valid_at: datetime | None = None
    known_at: datetime | None = None
    previous_context_id: UUID | None = None
    task_context: TaskContextHint | None = None

    @model_validator(mode="after")
    def validate_exact_hints(self) -> Self:
        if self.state_keys and self.claim_ids:
            raise ValueError("state_keys and claim_ids cannot be combined")
        target_count = len(self.state_keys) + len(self.claim_ids)
        if target_count > 1:
            raise ValueError("M2 exact resolution accepts one canonical target per call")
        for value in (self.valid_at, self.known_at, self.reference_time):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(
                    "valid_at, known_at, and reference_time must include timezone offsets"
                )
        if (self.valid_at is not None or self.known_at is not None) and target_count != 1:
            raise ValueError("valid_at and known_at require one exact canonical target")
        if self.required_authority == "ACTION_SAFE" and not self.requested_scope:
            raise ValueError("ACTION_SAFE memory resolve requires a non-empty requested_scope")
        if self.consistency_mode == "READ_YOUR_WRITES" and self.causal_token is None:
            raise ValueError("READ_YOUR_WRITES requires a causal_token")
        if self.consistency_mode != "READ_YOUR_WRITES" and self.causal_token is not None:
            raise ValueError("causal_token is only valid for READ_YOUR_WRITES")
        task_context = self.task_context
        if task_context is not None:
            project_scope = self.requested_scope.get("project_ids")
            if project_scope is not None and (
                not isinstance(project_scope, list)
                or not all(isinstance(value, str) and value for value in project_scope)
            ):
                raise ValueError(
                    "requested_scope.project_ids must be non-empty strings "
                    "when task_context is used"
                )
            _require_narrowing_overlap(
                "project_ids",
                cast(list[str], project_scope) if isinstance(project_scope, list) else [],
                task_context.project_ids,
            )
            _require_narrowing_overlap("entities", self.entities, task_context.entities)
            _require_narrowing_overlap(
                "memory_types", self.memory_types, task_context.memory_types
            )
        return self


def _require_narrowing_overlap(
    name: str,
    existing: list[str],
    task_values: list[str],
) -> None:
    if not existing or not task_values:
        return
    existing_normalized = {value.casefold() for value in existing}
    if not any(value.casefold() in existing_normalized for value in task_values):
        raise ValueError(f"task_context.{name} conflicts with the deployment-bound request")
