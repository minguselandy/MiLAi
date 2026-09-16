from __future__ import annotations

import hashlib
import json
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.retrieval import RetrievalAuthority, RetrievalConsistency

PrepareContextEvent = Literal[
    "TASK_START",
    "GOAL_CHANGED",
    "EXPLICIT_MEMORY_REQUEST",
    "KNOWN_OBJECT",
    "TOOL_RESULT",
    "MEMORY_AFFECTING_TOOL_RESULT",
    "MODEL_RETRY",
    "CANONICAL_POSITION_CHANGED",
    "ACTION_PROPOSED",
]


class StateKeyRef(BaseModel):
    """A Host locator hint that must always be revalidated against canonical state."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal["state-key-ref-v1"] = "state-key-ref-v1"
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=255)
    claim_type: str = Field(min_length=1, max_length=255)
    claim_id: UUID | None = None
    relevant_open_issue_ids: list[UUID] = Field(default_factory=list, max_length=256)
    canonical_position_seen: int | None = Field(default=None, ge=0)


class MemoryNeedSignature(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal["memory-need-v1"] = "memory-need-v1"
    scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority
    consistency_floor: RetrievalConsistency
    claim_ids: list[UUID] = Field(default_factory=list, max_length=256)
    state_keys: list[StateKeyRef] = Field(default_factory=list, max_length=64)
    open_issue_ids: list[UUID] = Field(default_factory=list, max_length=256)
    temporal_need: Literal["CURRENT", "HISTORICAL", "AS_OF"]
    evidence_need: Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"]
    intent_class: Literal["NONE", "CURRENT_STATE", "HISTORY", "CONFLICT", "EXPLANATION"]

    @property
    def signature_id(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return "need:" + hashlib.sha256(encoded).hexdigest()


class PrepareContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_prepare_context_calls: int = Field(default=4, ge=1, le=64)
    max_full_recall_calls: int = Field(default=2, ge=1, le=32)
    max_delta_refreshes: int = Field(default=2, ge=0, le=32)
    max_memory_tokens_injected: int = Field(default=1_600, ge=1, le=32_768)
    max_validation_calls: int = Field(default=16, ge=1, le=128)
    memory_deadline_ms: int = Field(default=250, ge=25, le=10_000)


class PrepareContextRequest(BaseModel):
    """Host-owned composite refresh input; model-visible callers cannot waive validation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    query: str = Field(default="", max_length=2_000)
    active_goal: str = Field(min_length=1, max_length=2_000)
    session_id: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=256)
    profile_id: str = Field(min_length=1, max_length=128)
    task_epoch: str = Field(min_length=1, max_length=256)
    event: PrepareContextEvent
    requested_route: Literal["NONE", "CACHE", "L0", "L1"] = "L1"
    need_signature_id: str | None = Field(default=None, min_length=8, max_length=256)
    memory_need_signature: MemoryNeedSignature | None = None
    state_key_ref: StateKeyRef | None = None
    requested_scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority = "INFORMATIONAL"
    consistency: RetrievalConsistency = "CANONICAL_REQUIRED"
    limit: int = Field(default=3, ge=1, le=20)
    constraints: list[str] = Field(default_factory=list, max_length=64)
    byte_budget: int = Field(default=16_384, ge=256, le=1_000_000)
    memory_token_budget: int = Field(default=512, ge=1, le=1_600)
    slot_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    compiler_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    router_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: PrepareContextBudget = Field(default_factory=PrepareContextBudget)
    previous_validation_token: str | None = Field(default=None, min_length=32, max_length=8_192)
    known_claim_id: UUID | None = None
    action_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_event_contract(self) -> Self:
        refresh_events = {
            "TASK_START",
            "GOAL_CHANGED",
            "EXPLICIT_MEMORY_REQUEST",
            "MEMORY_AFFECTING_TOOL_RESULT",
            "CANONICAL_POSITION_CHANGED",
            "ACTION_PROPOSED",
        }
        if self.event in refresh_events and not self.query:
            raise ValueError("refresh events require a query")
        if (
            self.event == "KNOWN_OBJECT"
            and self.known_claim_id is None
            and self.state_key_ref is None
        ):
            raise ValueError("KNOWN_OBJECT requires known_claim_id or state_key_ref")
        if self.event == "ACTION_PROPOSED":
            if self.required_authority != "ACTION_SAFE":
                raise ValueError("ACTION_PROPOSED requires ACTION_SAFE authority")
            if self.consistency != "CANONICAL_REQUIRED" or not self.requested_scope:
                raise ValueError(
                    "ACTION_PROPOSED requires CANONICAL_REQUIRED and a non-empty scope"
                )
            if self.action_digest is None:
                raise ValueError("ACTION_PROPOSED requires an action_digest")
        elif self.action_digest is not None:
            raise ValueError("action_digest is only valid for ACTION_PROPOSED")
        if self.consistency == "READ_YOUR_WRITES":
            raise ValueError("composite prepare_context does not accept unbound causal tokens")
        if self.memory_need_signature is not None:
            if self.need_signature_id != self.memory_need_signature.signature_id:
                raise ValueError("need signature identity does not match its typed payload")
        elif self.need_signature_id is not None:
            raise ValueError("need_signature_id requires a typed memory_need_signature")
        return self
