"""Method-neutral memory adapter contract for the DG-11 paper plane.

Adapters may build memory, retrieve it, and report their own costs.  They never
call the common answer model and never receive answer labels through this API.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "CAPABILITY_UNSUPPORTED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AdapterCapabilities:
    revoke: CapabilityStatus
    update: CapabilityStatus
    native_provider_calls: bool


@dataclass(frozen=True)
class MemoryEvent:
    event_id: str
    content: str
    observed_at: str
    actor: str
    scope: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id or not self.content or not self.observed_at:
            raise ValueError(
                "memory event identity, content, and observed_at are required"
            )
        forbidden = {"answer", "gold", "answer_session_ids", "has_answer"}
        if forbidden.intersection(self.metadata):
            raise ValueError("ordinary adapter ingest metadata contains scorer labels")


@dataclass(frozen=True)
class MemoryQueryResult:
    context: str
    source_ids: tuple[str, ...]
    trace: tuple[Mapping[str, Any], ...]
    declared_tokens: int
    latency_ms: float
    usage: Mapping[str, int | float | str]

    def __post_init__(self) -> None:
        if self.declared_tokens < 0 or self.latency_ms < 0:
            raise ValueError("query accounting values cannot be negative")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("query source IDs must be unique")


@dataclass(frozen=True)
class AdapterStats:
    method_id: str
    ingested_events: int
    query_count: int
    revoked_events: int
    provider_calls: Mapping[str, int]
    storage_bytes: int
    extra: Mapping[str, int | float | str | bool] = field(default_factory=dict)


@runtime_checkable
class MemoryAdapter(Protocol):
    method_id: str
    capabilities: AdapterCapabilities

    def reset(self, run_id: str, case_id: str) -> None: ...

    def ingest(self, event: MemoryEvent) -> None: ...

    def finalize(self) -> None: ...

    def query(
        self,
        question: str,
        question_at: str,
        token_budget: int,
        mode: str,
    ) -> MemoryQueryResult: ...

    def revoke(self, event_id: str) -> CapabilityStatus: ...

    def stats(self) -> AdapterStats: ...

    def close(self) -> None: ...
