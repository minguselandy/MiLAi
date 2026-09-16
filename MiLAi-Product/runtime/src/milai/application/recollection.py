"""Stable query/recollection boundary for Runtime consumers.

The concrete implementation remains ``RetrievalService``.  This module owns
only the consumer-facing types and structural interface so retrieval strategy
work can stay behind one behavior-preserving seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from milai.application.memory_access import MemoryAccessPlan
from milai.application.reader_evidence_plan import DecisionSnapshotRef
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext

if TYPE_CHECKING:
    from milai.application.memory_context import ContextPlanCompilation


MatchedReplayPolicy = Literal[
    "DG16_ANY_EVIDENCE_STOP",
    "DG17_QUERY_SPECIFIC_STOP",
]


@dataclass(frozen=True, slots=True)
class MatchedRetrievalReplay:
    """Internal, non-transport view of two policies over one retrieval execution."""

    schema_version: Literal["matched-retrieval-replay-v0.1"]
    evidence_snapshot: dict[str, Any]
    evidence_snapshot_digest: str
    policy_bodies: dict[MatchedReplayPolicy, dict[str, Any]]
    policy_metadata: dict[MatchedReplayPolicy, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RetrievalExecution:
    body: dict[str, Any]
    status_code: int = 200
    matched_replay: MatchedRetrievalReplay | None = None
    decision_snapshot: DecisionSnapshotRef | None = None
    context_plan: ContextPlanCompilation | None = None
    context_candidate_items: tuple[dict[str, Any], ...] = ()


class MatchedReplayInvariantError(RuntimeError):
    """The requested replay could not prove one stable evidence snapshot."""


@runtime_checkable
class RecollectionFacade(Protocol):
    """Stable read boundary implemented by the concrete retrieval service."""

    def retrieve(
        self,
        context: SessionContext,
        request: RetrievalRequest,
        request_id: str,
        *,
        require_user_confirmation: bool = False,
        context_budget: int = 8_000,
        resolved_claim_version_id: UUID | None = None,
        resolution_dimensions: dict[str, bool] | None = None,
        state_address_resolution_ms: float | None = None,
        allow_historical: bool = False,
        access_plan: MemoryAccessPlan | None = None,
        capture_matched_replay: bool = False,
        defer_decision_snapshot: bool = False,
    ) -> RetrievalExecution: ...

__all__ = [
    "MatchedReplayInvariantError",
    "MatchedReplayPolicy",
    "MatchedRetrievalReplay",
    "RecollectionFacade",
    "RetrievalExecution",
]
