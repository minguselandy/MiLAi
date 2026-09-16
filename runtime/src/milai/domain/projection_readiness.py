from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProjectionName = Literal["evidence", "fts", "vector", "purge"]


class ProjectionReadinessRequest(BaseModel):
    """Exact ordered projection position that a caller needs before proceeding."""

    model_config = ConfigDict(extra="forbid")

    target_outbox_id: UUID | None = None
    target_outbox_ids: list[UUID] = Field(default_factory=list, max_length=512)
    required_projections: list[ProjectionName] = Field(min_length=1, max_length=4)
    expected_versions: dict[ProjectionName, str]
    timeout_ms: int = Field(default=15_000, ge=0, le=30_000)
    poll_interval_ms: int = Field(default=25, ge=10, le=1_000)

    @model_validator(mode="after")
    def validate_projection_identity(self) -> ProjectionReadinessRequest:
        if (self.target_outbox_id is None) == (not self.target_outbox_ids):
            raise ValueError("exactly one readiness target form is required")
        if len(set(self.target_outbox_ids)) != len(self.target_outbox_ids):
            raise ValueError("target_outbox_ids must be unique")
        if len(set(self.required_projections)) != len(self.required_projections):
            raise ValueError("required_projections must be unique")
        if set(self.expected_versions) != set(self.required_projections):
            raise ValueError("expected_versions must exactly match required_projections")
        if any(not version.strip() for version in self.expected_versions.values()):
            raise ValueError("expected projection versions must be non-empty")
        return self

    @property
    def targets(self) -> tuple[UUID, ...]:
        return (
            (self.target_outbox_id,)
            if self.target_outbox_id is not None
            else tuple(self.target_outbox_ids)
        )
