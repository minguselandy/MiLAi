"""Internal compilation contracts for memory-context planning and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from milai.domain.memory_context import (
    EvidenceContextReceipt,
    MemoryContext,
    MemoryContextWindow,
)
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    DecisionSnapshot,
    ReaderEvidencePlan,
    ReaderEvidenceRender,
)
from milai.persistence import SessionContext


@dataclass(frozen=True, slots=True)
class ContextCompilation:
    memory_context: MemoryContext
    evidence_receipt: EvidenceContextReceipt | None
    reader_evidence_plan: ReaderEvidencePlan | None = None
    reader_render: ReaderEvidenceRender | None = None
    context_plan: ContextPlanCompilation | None = None


@dataclass(frozen=True, slots=True)
class ContextPlanCompilation:
    """Internal plan plus lossless Runtime projections needed for local renders."""

    reader_evidence_plan: ReaderEvidencePlan
    request: MemoryResolveRequest
    outcome: dict[str, Any]
    decision_snapshot: DecisionSnapshot
    unit_windows: tuple[tuple[str, MemoryContextWindow], ...]
    unit_canonical_items: tuple[tuple[str, dict[str, Any]], ...]
    ordered_windows: tuple[MemoryContextWindow, ...]
    canonical_items: tuple[dict[str, Any], ...]
    raw_derived: object
    expansion_trace: tuple[dict[str, object], ...]
    expansion_activation: dict[str, object]
    evidence_view_count: int
    derived_operand_view_count: int
    multi_session_required: bool
    required_evidence_ids: tuple[str, ...]
    required_source_refs: tuple[str, ...]
    recall_workspace_trace: dict[str, object] | None


class EvidenceAdjacencyReader(Protocol):
    def hydrate_evidence_adjacency(
        self,
        context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]: ...


class ContextTokenAccountingError(RuntimeError):
    """Typed failure when an exact presentation envelope cannot be counted."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code

