from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalContinuationState:
    """One immutable, non-canonical page in a retrieval lineage."""

    state_id: UUID
    root_state_id: UUID
    predecessor_state_id: UUID | None
    generation: int
    payload_semantics_version: str
    query_digest: str
    request_digest: str
    snapshot_as_of: datetime
    canonical_position: int | None
    selected_evidence_ids: tuple[str, ...]
    seen_evidence_ids: tuple[str, ...]
    frontier_evidence_ids: tuple[str, ...]
    online_ineligible_count: int
    operation_fingerprint: str | None
    state_digest: str
    created_at: datetime
    expires_at: datetime

    @property
    def available(self) -> bool:
        return bool(self.frontier_evidence_ids)


__all__ = ["RetrievalContinuationState"]
