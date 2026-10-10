"""A thin pure-memory entry assembled from the existing benchmark callbacks.

The facade owns neither a second maintenance algorithm nor a business Host.
Its caller retains the original MemoryService, model ledger and resource scope.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from milai_lab.contracts.memory_backend import IngestionResult, MemorySession, RetrievalResult


class MiLAiMemoryBackend:
    def __init__(
        self,
        *,
        maintain: Callable[[MemorySession, str], list[str]],
        retrieve: Callable[[str, str, str, int], list[dict[str, Any]]],
        maintenance_result: Callable[[str], dict[str, Any]] | None = None,
        retrieval_native: Callable[[str], Any] | None = None,
        usage: Callable[[], dict[str, Any]] | None = None,
        close: Callable[[], None] | None = None,
    ) -> None:
        self._maintain, self._retrieve = maintain, retrieve
        self._maintenance_result, self._retrieval_native = maintenance_result, retrieval_native
        self._usage, self._close = usage, close

    def _before(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._usage()) if self._usage is not None else None

    def _observed_usage(self, before: dict[str, Any] | None) -> dict[str, Any]:
        if self._usage is None:
            return {"observation": "unobserved"}
        return {"observation": "original_budget_snapshots", "before": before,
                "after": copy.deepcopy(self._usage())}

    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult:
        before = self._before()
        output = self._maintain(session, key)
        native = self._maintenance_result(key) if self._maintenance_result is not None else output
        status = native.get("status") if isinstance(native, dict) else None
        completed = status in {None, "completed", "COMPLETE_ATTEMPTS"}
        return {"session_id": session.session_id, "completed": completed,
                "native_return": native, "session_output": output,
                "usage": self._observed_usage(before)}

    def retrieve(
        self, question: str, date: str, *, key: str, limit: int,
    ) -> RetrievalResult:
        before = self._before()
        materials = self._retrieve(question, date, key, limit)
        native = self._retrieval_native(key) if self._retrieval_native is not None else materials
        return {"materials": materials, "native_return": native,
                "returned_count": len(materials),
                "source_mapping": "actual_retained_state_and_revision_evidence",
                "usage": self._observed_usage(before)}

    def close(self) -> None:
        if self._close is not None:
            self._close()
