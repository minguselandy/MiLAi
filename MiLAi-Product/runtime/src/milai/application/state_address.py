from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from milai.domain.memory_state import MemoryStateGetRequest
from milai.persistence import SessionContext
from milai.persistence.memory_state_repository import (
    StateAddressRepository,
    StateAddressResolution,
)


class StateAddressService:
    """Resolve one canonical StateKey/ClaimID without consulting projections."""

    def __init__(self, repository: StateAddressRepository) -> None:
        self._repository = repository

    def resolve(
        self,
        context: SessionContext,
        request: MemoryStateGetRequest,
        *,
        now: datetime | None = None,
    ) -> tuple[StateAddressResolution, datetime, datetime]:
        reference = now or datetime.now(UTC)
        valid_at = request.valid_at or reference
        known_at = request.known_at or reference
        resolution = self._repository.resolve(
            context,
            claim_id=request.claim_id,
            state_key=request.state_key,
            requested_scope=cast(dict[str, object], dict(request.requested_scope)),
            valid_at=valid_at,
            known_at=known_at,
            allow_historical=request.historical,
        )
        return resolution, valid_at, known_at
