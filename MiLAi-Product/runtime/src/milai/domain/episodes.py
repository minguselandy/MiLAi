from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EpisodeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    subject_id: str = Field(min_length=1, max_length=512)
    evidence_refs: list[UUID] = Field(default_factory=list, max_length=256)
    chat_turn_refs: list[UUID] = Field(default_factory=list, max_length=256)
    context_capsule_refs: list[UUID] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_replayable_refs(self) -> Self:
        groups = (self.evidence_refs, self.chat_turn_refs, self.context_capsule_refs)
        if not any(groups):
            raise ValueError("an Episode requires at least one replayable reference")
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("Episode references must be unique within each type")
        return self


class EpisodeSettleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: UUID | None = None
    expected_revision: int = Field(ge=1)
    residual_proposal_ids: list[UUID] = Field(default_factory=list, max_length=3)
    open_issue_ids: list[UUID] = Field(default_factory=list, max_length=256)
    confirmation: Literal["SETTLE"]

    @model_validator(mode="after")
    def validate_unique_refs(self) -> Self:
        if len(self.residual_proposal_ids) != len(set(self.residual_proposal_ids)):
            raise ValueError("residual Proposal IDs must be unique")
        if len(self.open_issue_ids) != len(set(self.open_issue_ids)):
            raise ValueError("OpenIssue IDs must be unique")
        return self
