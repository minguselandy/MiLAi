from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

from milai.application.context_receipt import requirement_coverage
from milai.application.errors import RetrievalContinuationError
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.retrieval_continuation import RetrievalContinuationState
from milai.persistence import SessionContext
from milai.persistence.retrieval_continuation_repository import (
    RetrievalContinuationRepository,
    RetrievalContinuationRootWrite,
    RetrievalContinuationSuccessorWrite,
    RetrievalContinuationWriteResult,
)

_SEMANTICS_VERSION = "retrieval-continuation-v0.2"
_MAX_FRONTIER_REFS = 120


class ExactEvidenceHydrator(Protocol):
    def hydrate_evidence_by_ids(
        self,
        context: SessionContext,
        *,
        evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class RetrievalContinuationPage:
    predecessor: RetrievalContinuationState
    attempted_evidence_ids: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    ineligible_evidence_ids: tuple[str, ...]
    tail_evidence_ids: tuple[str, ...]
    items: tuple[dict[str, Any], ...]


class RetrievalContinuationService:
    """Persist and consume exact post-acquisition Evidence frontier identities."""

    def __init__(
        self,
        repository: RetrievalContinuationRepository,
        hydrator: ExactEvidenceHydrator,
        *,
        ttl_seconds: int = 86_400,
    ) -> None:
        if not 60 <= ttl_seconds <= 86_400:
            raise ValueError("retrieval continuation TTL must be between 60s and 1 day")
        self._repository = repository
        self._hydrator = hydrator
        self._ttl_seconds = ttl_seconds

    def page(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
    ) -> RetrievalContinuationPage | None:
        if request.previous_context_id is None:
            return None
        state = self._repository.get_owned(context, request.previous_context_id)
        if state is None:
            return None
        self._assert_state_digest(state)
        if state.expires_at <= datetime.now(UTC):
            raise RetrievalContinuationError("RETRIEVAL_CONTINUATION_UNAVAILABLE")
        if state.query_digest != _query_digest(request.query):
            raise RetrievalContinuationError("RETRIEVAL_CONTINUATION_QUERY_MISMATCH")
        if state.request_digest != _request_digest(
            request,
            semantics_version=state.payload_semantics_version,
        ):
            raise RetrievalContinuationError("RETRIEVAL_CONTINUATION_REQUEST_MISMATCH")
        if not state.frontier_evidence_ids:
            return RetrievalContinuationPage(state, (), (), (), (), ())

        page_size = min(24, request.budget.max_results, len(state.frontier_evidence_ids))
        attempted = state.frontier_evidence_ids[:page_size]
        tail = state.frontier_evidence_ids[page_size:]
        hydrated = self._hydrator.hydrate_evidence_by_ids(
            context,
            evidence_ids=list(attempted),
            requested_scope=dict(request.requested_scope),
            as_of=state.snapshot_as_of,
            max_items=page_size,
            statement_timeout_ms=request.budget.max_latency_ms,
        )
        by_id = {
            str(item["evidence_id"]): dict(item)
            for item in hydrated
            if isinstance(item, dict) and item.get("evidence_id") is not None
        }
        eligible = tuple(value for value in attempted if value in by_id)
        ineligible = tuple(value for value in attempted if value not in by_id)
        items = tuple(by_id[value] for value in eligible)
        return RetrievalContinuationPage(
            predecessor=state,
            attempted_evidence_ids=attempted,
            eligible_evidence_ids=eligible,
            ineligible_evidence_ids=ineligible,
            tail_evidence_ids=tail,
            items=items,
        )

    def register_root(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        *,
        context_id: UUID,
        selected_evidence_ids: list[str],
        candidate_items: tuple[dict[str, Any], ...],
        snapshot_as_of: datetime,
        canonical_position: int | None,
    ) -> RetrievalContinuationWriteResult:
        selected = _unique(selected_evidence_ids)
        seen = selected
        candidate_ids = _candidate_evidence_ids(candidate_items)
        candidate_frontier = tuple(
            value for value in candidate_ids if value not in set(seen)
        )
        frontier, removed_count = self._live_identity_subset(
            context,
            request,
            snapshot_as_of,
            candidate_frontier,
        )
        if len(frontier) > _MAX_FRONTIER_REFS:
            raise RetrievalContinuationError("FRONTIER_STATE_LIMIT_REACHED")
        material = _state_material(
            state_id=context_id,
            root_state_id=context_id,
            predecessor_state_id=None,
            generation=0,
            query_digest=_query_digest(request.query),
            request_digest=_request_digest(request),
            snapshot_as_of=snapshot_as_of,
            canonical_position=canonical_position,
            selected=selected,
            seen=seen,
            frontier=frontier,
            online_ineligible_count=removed_count,
            operation_fingerprint=None,
        )
        result = self._repository.create_root(
            context,
            RetrievalContinuationRootWrite(
                state_id=context_id,
                query_digest=str(material["query_digest"]),
                request_digest=str(material["request_digest"]),
                snapshot_as_of=snapshot_as_of,
                canonical_position=canonical_position,
                selected_evidence_ids=selected,
                seen_evidence_ids=seen,
                frontier_evidence_ids=frontier,
                online_ineligible_count=removed_count,
                state_digest=_digest(material),
                expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
            ),
        )
        self._assert_state_digest(result.state)
        return result

    def advance(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        page: RetrievalContinuationPage,
        *,
        visible_evidence_ids: list[str],
    ) -> RetrievalContinuationWriteResult:
        predecessor = page.predecessor
        visible = _unique(visible_evidence_ids)
        direct_selected = set(visible).intersection(page.eligible_evidence_ids)
        remaining_eligible = tuple(
            value for value in page.eligible_evidence_ids if value not in direct_selected
        )
        live_tail, tail_ineligible_count = self._live_identity_subset(
            context,
            request,
            predecessor.snapshot_as_of,
            page.tail_evidence_ids,
        )
        remaining = (*remaining_eligible, *live_tail)
        seen = _unique([*predecessor.seen_evidence_ids, *visible])
        fingerprint = _digest(
            {
                "predecessor_state_id": str(predecessor.state_id),
                "generation": predecessor.generation + 1,
                "query_digest": predecessor.query_digest,
                "request_digest": predecessor.request_digest,
                "root_snapshot_as_of": predecessor.snapshot_as_of.astimezone(UTC).isoformat(),
                "payload_semantics_version": _SEMANTICS_VERSION,
            }
        )
        successor_id = uuid5(
            predecessor.state_id,
            f"io.milai.retrieval-continuation/{fingerprint}",
        )
        live_tail_set = set(live_tail)
        discarded = _unique(
            [
                *page.ineligible_evidence_ids,
                *(value for value in page.tail_evidence_ids if value not in live_tail_set),
            ]
        )
        online_ineligible_count = (
            predecessor.online_ineligible_count
            + len(page.ineligible_evidence_ids)
            + tail_ineligible_count
        )
        material = _state_material(
            state_id=successor_id,
            root_state_id=predecessor.root_state_id,
            predecessor_state_id=predecessor.state_id,
            generation=predecessor.generation + 1,
            query_digest=predecessor.query_digest,
            request_digest=predecessor.request_digest,
            snapshot_as_of=predecessor.snapshot_as_of,
            canonical_position=predecessor.canonical_position,
            selected=visible,
            seen=seen,
            frontier=remaining,
            online_ineligible_count=online_ineligible_count,
            operation_fingerprint=fingerprint,
        )
        result = self._repository.create_successor(
            context,
            RetrievalContinuationSuccessorWrite(
                state_id=successor_id,
                predecessor_state_id=predecessor.state_id,
                operation_fingerprint=fingerprint,
                selected_evidence_ids=visible,
                seen_evidence_ids=seen,
                frontier_evidence_ids=remaining,
                discarded_evidence_ids=discarded,
                online_ineligible_count=online_ineligible_count,
                state_digest=_digest(material),
            ),
        )
        self._assert_state_digest(result.state)
        return result

    def _live_identity_subset(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        snapshot_as_of: datetime,
        evidence_ids: tuple[str, ...],
    ) -> tuple[tuple[str, ...], int]:
        live: set[str] = set()
        for offset in range(0, len(evidence_ids), 24):
            batch = evidence_ids[offset : offset + 24]
            hydrated = self._hydrator.hydrate_evidence_by_ids(
                context,
                evidence_ids=list(batch),
                requested_scope=dict(request.requested_scope),
                as_of=snapshot_as_of,
                max_items=len(batch),
                statement_timeout_ms=request.budget.max_latency_ms,
            )
            live.update(
                str(item["evidence_id"])
                for item in hydrated
                if isinstance(item, dict) and item.get("evidence_id") is not None
            )
        values = tuple(value for value in evidence_ids if value in live)
        return values, len(evidence_ids) - len(values)

    def _assert_state_digest(self, state: RetrievalContinuationState) -> None:
        semantics_version = state.payload_semantics_version
        if semantics_version not in {
            "retrieval-continuation-v0.1",
            _SEMANTICS_VERSION,
        }:
            raise RetrievalContinuationError("INVALID_RETRIEVAL_CONTINUATION")
        material = _state_material(
            state_id=state.state_id,
            root_state_id=state.root_state_id,
            predecessor_state_id=state.predecessor_state_id,
            generation=state.generation,
            query_digest=state.query_digest,
            request_digest=state.request_digest,
            snapshot_as_of=state.snapshot_as_of,
            canonical_position=state.canonical_position,
            selected=state.selected_evidence_ids,
            seen=state.seen_evidence_ids,
            frontier=state.frontier_evidence_ids,
            online_ineligible_count=state.online_ineligible_count,
            operation_fingerprint=state.operation_fingerprint,
            semantics_version=semantics_version,
        )
        if _digest(material) != state.state_digest:
            raise RetrievalContinuationError("INVALID_RETRIEVAL_CONTINUATION")


def continuation_assertion(
    state: RetrievalContinuationState,
    *,
    candidate_origin: Literal["PERSISTED_FRONTIER"] | None = None,
    attempted_count: int = 0,
    ineligible_count: int = 0,
    replayed: bool = False,
) -> dict[str, Any]:
    available = state.available
    reason = "UNEXPANDED_FRONTIER"
    if not available:
        reason = (
            "FRONTIER_ELIGIBILITY_CHANGED"
            if state.online_ineligible_count > 0
            else "PERSISTED_FRONTIER_EXHAUSTED"
        )
    return {
        "schema_version": "retrieval-continuation-assertion-v0.1",
        "context_id": str(state.state_id),
        "root_context_id": str(state.root_state_id),
        "generation": state.generation,
        "available": available,
        "reason": reason,
        "candidate_origin": candidate_origin,
        "persisted_frontier_count": len(state.frontier_evidence_ids),
        "attempted_frontier_count": attempted_count,
        "online_ineligible_count": state.online_ineligible_count,
        "current_page_ineligible_count": ineligible_count,
        "global_reacquisition_calls": 0 if candidate_origin == "PERSISTED_FRONTIER" else None,
        "candidate_pool_extension_calls": 0 if candidate_origin == "PERSISTED_FRONTIER" else None,
        "query_replanning_calls": 0 if candidate_origin == "PERSISTED_FRONTIER" else None,
        "operation_replayed": replayed,
        "semantic_completeness_asserted": False,
        "corpus_exhaustion_asserted": False,
    }


def _query_digest(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def _request_digest(
    request: MemoryResolveRequest,
    *,
    semantics_version: str = _SEMANTICS_VERSION,
) -> str:
    coverage = requirement_coverage(request)
    if semantics_version == "retrieval-continuation-v0.1":
        return _digest(coverage)
    return _digest(
        {
            "requirement_coverage": coverage,
            "reference_time": (
                request.reference_time.astimezone(UTC).isoformat()
                if request.reference_time is not None
                else None
            ),
        }
    )


def _candidate_evidence_ids(items: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    values: list[str] = []
    for item in items:
        singular = item.get("evidence_id")
        if isinstance(singular, str):
            values.append(singular)
        multiple = item.get("evidence_ids")
        if isinstance(multiple, list):
            values.extend(value for value in multiple if isinstance(value, str))
    return _unique(values)


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _state_material(
    *,
    state_id: UUID,
    root_state_id: UUID,
    predecessor_state_id: UUID | None,
    generation: int,
    query_digest: str,
    request_digest: str,
    snapshot_as_of: datetime,
    canonical_position: int | None,
    selected: tuple[str, ...],
    seen: tuple[str, ...],
    frontier: tuple[str, ...],
    online_ineligible_count: int,
    operation_fingerprint: str | None,
    semantics_version: str = _SEMANTICS_VERSION,
) -> dict[str, object]:
    material: dict[str, object] = {
        "payload_semantics_version": semantics_version,
        "state_id": str(state_id),
        "root_state_id": str(root_state_id),
        "predecessor_state_id": (
            str(predecessor_state_id) if predecessor_state_id is not None else None
        ),
        "generation": generation,
        "query_digest": query_digest,
        "request_digest": request_digest,
        "snapshot_as_of": snapshot_as_of.astimezone(UTC).isoformat(),
        "canonical_position": canonical_position,
        "selected_evidence_ids": list(selected),
        "seen_evidence_ids": list(seen),
        "frontier_evidence_ids": list(frontier),
        "operation_fingerprint": operation_fingerprint,
    }
    if semantics_version == _SEMANTICS_VERSION:
        material["online_ineligible_count"] = online_ineligible_count
    return material


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "RetrievalContinuationPage",
    "RetrievalContinuationService",
    "continuation_assertion",
]
