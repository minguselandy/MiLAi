from __future__ import annotations

from time import monotonic, sleep
from typing import Any

from milai.domain.projection_readiness import ProjectionReadinessRequest
from milai.persistence import SessionContext
from milai.persistence.projection_repository import ProjectionRepository


class ProjectionReadinessService:
    """Wait for an exact durable projection position without doing projection work."""

    def __init__(self, repository: ProjectionRepository) -> None:
        self._repository = repository

    def wait(
        self,
        context: SessionContext,
        request: ProjectionReadinessRequest,
    ) -> tuple[dict[str, Any], int]:
        started = monotonic()
        deadline = started + (request.timeout_ms / 1_000)
        polls = 0
        while True:
            polls += 1
            snapshot = self._repository.readiness_status(
                context,
                request.targets,
                tuple(request.required_projections),
                dict(request.expected_versions),
            )
            status = str(snapshot.get("status"))
            if status == "READY":
                return self._decorate(snapshot, started, polls), 200
            if status in {"DEAD_LETTER_GAP", "VERSION_MISMATCH"}:
                return self._decorate(snapshot, started, polls), 409
            now = monotonic()
            if now >= deadline:
                snapshot["status"] = "PROJECTION_READINESS_TIMEOUT"
                return self._decorate(snapshot, started, polls), 408
            remaining = deadline - now
            sleep(min(request.poll_interval_ms / 1_000, remaining))

    @staticmethod
    def _decorate(
        snapshot: dict[str, Any], started: float, polls: int
    ) -> dict[str, Any]:
        snapshot["barrier_wait_ms"] = round((monotonic() - started) * 1_000, 3)
        snapshot["poll_count"] = polls
        snapshot["projection_work_started"] = False
        return snapshot
