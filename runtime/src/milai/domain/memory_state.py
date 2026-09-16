from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from milai.domain.retrieval import RetrievalAuthority, RetrievalConsistency


class CanonicalStateAddress(BaseModel):
    """A stable Claim identity; it never contains a derived projection locator."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=255)
    claim_type: str = Field(min_length=1, max_length=255)


class MemoryStateGetRequest(BaseModel):
    """Exact StateKey/Claim read with explicit bitemporal coordinates."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim_id: UUID | None = None
    state_key: CanonicalStateAddress | None = None
    requested_scope: dict[str, JsonValue] = Field(default_factory=dict)
    required_authority: RetrievalAuthority = "INFORMATIONAL"
    consistency_mode: RetrievalConsistency = "CANONICAL_REQUIRED"
    causal_token: str | None = Field(default=None, min_length=16, max_length=512)
    valid_at: datetime | None = None
    known_at: datetime | None = None

    @model_validator(mode="after")
    def validate_address_and_time(self) -> Self:
        if (self.claim_id is None) == (self.state_key is None):
            raise ValueError("exactly one of claim_id or state_key is required")
        for value in (self.valid_at, self.known_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("valid_at and known_at must include timezone offsets")
        if self.required_authority == "ACTION_SAFE" and not self.requested_scope:
            raise ValueError("ACTION_SAFE state read requires a non-empty requested_scope")
        if self.consistency_mode == "READ_YOUR_WRITES" and self.causal_token is None:
            raise ValueError("READ_YOUR_WRITES requires a causal_token")
        if self.consistency_mode != "READ_YOUR_WRITES" and self.causal_token is not None:
            raise ValueError("causal_token is only valid for READ_YOUR_WRITES")
        return self

    @property
    def historical(self) -> bool:
        return self.valid_at is not None or self.known_at is not None
