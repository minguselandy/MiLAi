from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.retrieval import RetrievalAuthority, RetrievalConsistency


class ContextBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    retrieval_trace_id: UUID
    active_goal: str = Field(min_length=1, max_length=2_000)
    constraints: list[str] = Field(default_factory=list, max_length=64)
    detail_level: Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"] = "OVERVIEW"
    byte_budget: int = Field(default=16_384, ge=64, le=1_000_000)
    ttl_seconds: int = Field(default=900, ge=1, le=86_400)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    query: str = Field(min_length=1, max_length=2_000)
    active_goal: str = Field(min_length=1, max_length=2_000)
    constraints: list[str] = Field(default_factory=list, max_length=64)
    requested_scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority = "INFORMATIONAL"
    consistency: RetrievalConsistency = "CANONICAL_REQUIRED"
    causal_token: str | None = Field(default=None, min_length=16, max_length=512)
    causal_wait_timeout_ms: int = Field(default=250, ge=0, le=2_000)
    limit: int = Field(default=5, ge=1, le=20)
    byte_budget: int = Field(default=16_384, ge=64, le=1_000_000)
    ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    action_sensitive: bool = False
    live_confirmation: Literal["CONFIRM_ACTION"] | None = None
    confirmation_evidence_id: UUID | None = None
    confirmation_nonce: UUID | None = None

    @model_validator(mode="after")
    def validate_action_policy(self) -> Self:
        if self.consistency == "READ_YOUR_WRITES" and self.causal_token is None:
            raise ValueError("READ_YOUR_WRITES chat requires a causal_token")
        if self.consistency != "READ_YOUR_WRITES" and self.causal_token is not None:
            raise ValueError("causal_token is only valid for READ_YOUR_WRITES chat")
        if self.action_sensitive:
            if self.required_authority != "ACTION_SAFE":
                raise ValueError("action-sensitive chat requires ACTION_SAFE authority")
            if not self.requested_scope:
                raise ValueError("action-sensitive chat requires a non-empty scope")
            confirmation_values = (
                self.live_confirmation,
                self.confirmation_evidence_id,
                self.confirmation_nonce,
            )
            if any(value is not None for value in confirmation_values) and not all(
                value is not None for value in confirmation_values
            ):
                raise ValueError("live confirmation requires Evidence ID and nonce")
        elif any(
            value is not None
            for value in (
                self.live_confirmation,
                self.confirmation_evidence_id,
                self.confirmation_nonce,
            )
        ):
            raise ValueError("live confirmation is only valid for action-sensitive chat")
        return self
