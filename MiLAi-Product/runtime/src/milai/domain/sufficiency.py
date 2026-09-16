"""DG-17 v0.1 contract for query-specific retrieval sufficiency."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SufficiencyStatus = Literal[
    "COMPLETE",
    "PARTIAL",
    "UNSATISFIED",
    "CONTESTED",
    "UNBOUNDED",
]
SufficiencyStopReason = Literal[
    "REQUIREMENT_SATISFIED",
    "SEARCH_SPACE_EXHAUSTED",
    "BUDGET_EXHAUSTED",
    "PROJECTION_NOT_READY",
    "QUERY_AMBIGUOUS",
    "ACCESS_DENIED",
    "MEMORY_UNAVAILABLE",
]


class SufficiencyProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bounded_scan_completed: bool = False
    source_partition_closed: bool = False
    projection_watermark: int | None = None
    deduplication_completed: bool = False
    version_chain_complete: bool = False


class SufficiencyDecision(BaseModel):
    """Versioned proof that a query may stop, escalate, or abstain.

    Candidate presence is intentionally absent from this contract: a hit is an
    acquisition fact, not a completeness proof.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["sufficiency-decision-v0.1"] = (
        "sufficiency-decision-v0.1"
    )
    status: SufficiencyStatus
    covered_slots: list[str] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    proof: SufficiencyProof = Field(default_factory=SufficiencyProof)
    stop_reason: SufficiencyStopReason

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE"

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "SufficiencyDecision",
    "SufficiencyProof",
    "SufficiencyStatus",
    "SufficiencyStopReason",
]
