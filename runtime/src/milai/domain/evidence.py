from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class EvidenceSourceContext(BaseModel):
    """Immutable source-authored turn/round identity used for bounded adjacency."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=512)
    turn_id: str = Field(min_length=1, max_length=512)
    turn_ordinal: int = Field(ge=0)
    round_id: str = Field(min_length=1, max_length=512)
    round_ordinal: int = Field(ge=0)
    previous_turn_id: str | None = Field(default=None, min_length=1, max_length=512)
    next_turn_id: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_adjacency(self) -> Self:
        if self.turn_id in {self.previous_turn_id, self.next_turn_id}:
            raise ValueError("a source turn cannot be adjacent to itself")
        if (
            self.previous_turn_id is not None
            and self.previous_turn_id == self.next_turn_id
        ):
            raise ValueError("previous and next source turns must be distinct")
        return self


class EvidenceIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    source_type: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    source_ref: str = Field(min_length=1, max_length=2048)
    subject_id: str = Field(min_length=1, max_length=512)
    speaker: Literal["user", "assistant", "system", "tool"] | None = None
    source_context: EvidenceSourceContext | None = None
    observed_at: AwareDatetime
    content: str = Field(min_length=1)
    data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"] = "SYNTHETIC"
    media_type: str = Field(default="text/plain; charset=utf-8", min_length=1, max_length=255)
    permission_snapshot: dict[str, JsonValue]
    retention_state: Literal["READABLE", "UNREADABLE", "EXPIRED", "LEGAL_HOLD"] = "READABLE"

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_datetime(cls, value: datetime) -> datetime:
        return value
