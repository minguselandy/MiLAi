"""Thin research backend boundary; native text and usage retain their provenance."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class MemorySession(Protocol):
    """The existing ObservedSession satisfies this read-only structural interface."""

    @property
    def session_id(self) -> str: ...

    @property
    def date(self) -> str: ...

    @property
    def turns(self) -> tuple[dict[str, str], ...]: ...


class IngestionResult(TypedDict):
    session_id: str
    completed: bool
    native_return: Any
    session_output: list[str] | None
    usage: dict[str, Any]


class RetrievalResult(TypedDict):
    """Materials are actual backend returns, not another extraction or summary.

    A material may be a supported MiLAi state, a whole original exchange, or an
    external retrieved memory. source_mapping and each material's provenance
    describe that distinction; missing native costs are unobserved, never zero.
    """

    materials: list[dict[str, Any]]
    native_return: Any
    returned_count: int
    source_mapping: str
    usage: dict[str, Any]


class MemoryBackend(Protocol):
    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult: ...

    def retrieve(
        self, question: str, date: str, *, key: str, limit: int,
    ) -> RetrievalResult: ...

    def close(self) -> None: ...
