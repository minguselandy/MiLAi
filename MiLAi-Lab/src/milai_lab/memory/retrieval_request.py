"""Tool input schema; identity and access remain in the runtime context."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StructuredReadGoal(RequestFields):
    """Semantic requirements, never a sufficiency verdict or an operation program."""

    # Additional semantic requirements stay literal for the policy. They do not
    # become identities, resource limits or runtime permissions.
    model_config = ConfigDict(extra="allow", strict=True)
    purpose: str | None = None
    evidence: list[Literal[
        "current_interpretation", "saved_history", "original_source", "live_business"
    ]] = Field(default_factory=list)
    required_points: list[str] = Field(default_factory=list)


class MaterialReference(RequestFields):
    """The existing Store material reference, copied from an actual delivery."""

    snapshot_id: str
    collection: Literal["materials"] = "materials"
    item_index: int = Field(ge=0)


class RetrievalContext(RequestFields):
    """Caller-visible semantic context; references still use their bound read path."""

    model_config = ConfigDict(extra="allow", strict=True)
    as_of: str | None = None
    target_scope: str | dict[str, Any] | None = None
    known_evidence_refs: list[MaterialReference] = Field(default_factory=list)


class RetrievalLimits(RequestFields):
    max_return_tokens: int | None = Field(default=None, ge=1)
    max_control_steps: int | None = Field(default=None, ge=0)


class RetrievalRequest(RequestFields):
    query: str = Field(min_length=1)
    read_goal: str | StructuredReadGoal | None = None
    task_context: RetrievalContext = Field(default_factory=RetrievalContext)
    limits: RetrievalLimits = Field(default_factory=RetrievalLimits)

    def project(self) -> dict[str, Any]:
        """The same literal request is used for decisions and training export."""
        return self.model_dump(mode="json", exclude_unset=True)
