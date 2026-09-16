from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from milai.application.errors import RetrievalContinuationError
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_resolve import MemoryResolveService
from milai.application.recollection import RecollectionFacade, RetrievalExecution
from milai.application.retrieval_continuation import RetrievalContinuationService
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.retrieval_continuation import RetrievalContinuationState
from milai.persistence import SessionContext
from milai.persistence.retrieval_continuation_repository import (
    RetrievalContinuationRootWrite,
    RetrievalContinuationSuccessorWrite,
    RetrievalContinuationWriteResult,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("22222222-2222-4222-8222-222222222222")
EVIDENCE_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVIDENCE_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EVIDENCE_3 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class _Repository:
    def __init__(self) -> None:
        self.states: dict[UUID, RetrievalContinuationState] = {}
        self.successor_commands: list[RetrievalContinuationSuccessorWrite] = []

    def get_owned(
        self, _context: SessionContext, state_id: UUID
    ) -> RetrievalContinuationState | None:
        return self.states.get(state_id)

    def create_root(
        self,
        _context: SessionContext,
        command: RetrievalContinuationRootWrite,
    ) -> RetrievalContinuationWriteResult:
        now = datetime.now(UTC)
        state = RetrievalContinuationState(
            state_id=command.state_id,
            root_state_id=command.state_id,
            predecessor_state_id=None,
            generation=0,
            payload_semantics_version="retrieval-continuation-v0.2",
            query_digest=command.query_digest,
            request_digest=command.request_digest,
            snapshot_as_of=command.snapshot_as_of,
            canonical_position=command.canonical_position,
            selected_evidence_ids=command.selected_evidence_ids,
            seen_evidence_ids=command.seen_evidence_ids,
            frontier_evidence_ids=command.frontier_evidence_ids,
            online_ineligible_count=command.online_ineligible_count,
            operation_fingerprint=None,
            state_digest=command.state_digest,
            created_at=now,
            expires_at=command.expires_at,
        )
        self.states[state.state_id] = state
        return RetrievalContinuationWriteResult(state, False)

    def create_successor(
        self,
        _context: SessionContext,
        command: RetrievalContinuationSuccessorWrite,
    ) -> RetrievalContinuationWriteResult:
        self.successor_commands.append(command)
        predecessor = self.states[command.predecessor_state_id]
        existing = next(
            (
                state
                for state in self.states.values()
                if state.operation_fingerprint == command.operation_fingerprint
            ),
            None,
        )
        if existing is not None:
            return RetrievalContinuationWriteResult(existing, True)
        state = RetrievalContinuationState(
            state_id=command.state_id,
            root_state_id=predecessor.root_state_id,
            predecessor_state_id=predecessor.state_id,
            generation=predecessor.generation + 1,
            payload_semantics_version="retrieval-continuation-v0.2",
            query_digest=predecessor.query_digest,
            request_digest=predecessor.request_digest,
            snapshot_as_of=predecessor.snapshot_as_of,
            canonical_position=predecessor.canonical_position,
            selected_evidence_ids=command.selected_evidence_ids,
            seen_evidence_ids=command.seen_evidence_ids,
            frontier_evidence_ids=command.frontier_evidence_ids,
            online_ineligible_count=command.online_ineligible_count,
            operation_fingerprint=command.operation_fingerprint,
            state_digest=command.state_digest,
            created_at=datetime.now(UTC),
            expires_at=predecessor.expires_at,
        )
        self.states[state.state_id] = state
        return RetrievalContinuationWriteResult(state, False)


class _Hydrator:
    def __init__(self, items: dict[str, dict[str, Any]]) -> None:
        self.items = items
        self.calls: list[list[str]] = []

    def hydrate_evidence_by_ids(
        self,
        _context: SessionContext,
        *,
        evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        del requested_scope, as_of, statement_timeout_ms
        self.calls.append(evidence_ids)
        return [self.items[value] for value in evidence_ids if value in self.items][:max_items]


class _AdjacencyReader:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.calls = 0

    def hydrate_evidence_adjacency(
        self,
        _context: SessionContext,
        *,
        anchor_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        max_items: int,
    ) -> list[dict[str, Any]]:
        del anchor_evidence_ids, requested_scope, as_of
        self.calls += 1
        return deepcopy(self.items[:max_items])


class _MustNotRetrieve:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, *_args: object, **_kwargs: object) -> RetrievalExecution:
        self.calls += 1
        raise AssertionError("continuation must not run global retrieval")


class _StaticRetrieve:
    def __init__(self, body: dict[str, Any], candidates: tuple[dict[str, Any], ...]) -> None:
        self.body = body
        self.candidates = candidates

    def retrieve(self, *_args: object, **_kwargs: object) -> RetrievalExecution:
        return RetrievalExecution(
            deepcopy(self.body),
            context_candidate_items=deepcopy(self.candidates),
        )


def _item(evidence_id: str, content: str) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/alpha/turn/{evidence_id[0]}",
        "subject_id": "alpha",
        "observed_at": "2026-09-05T00:00:00+00:00",
        "speaker": "user",
        "content": content,
        "relevance_score": 1.0,
    }


def _structured_item(
    evidence_id: str,
    content: str,
    *,
    turn_ordinal: int,
) -> dict[str, Any]:
    item = _item(evidence_id, content)
    item["source_context_source"] = "STRUCTURED_TURN_METADATA"
    item["source_context"] = {
        "session_id": "alpha-session",
        "turn_id": f"turn-{turn_ordinal}",
        "round_id": f"round-{turn_ordinal}",
        "turn_ordinal": turn_ordinal,
        "round_ordinal": turn_ordinal,
        "previous_turn_id": f"turn-{turn_ordinal - 1}" if turn_ordinal > 0 else None,
        "next_turn_id": f"turn-{turn_ordinal + 1}",
    }
    return item


def _request(**updates: object) -> MemoryResolveRequest:
    request = MemoryResolveRequest(
        query="What purchases were mentioned?",
        requested_scope={"project_ids": ["milai"]},
        budget=MemoryResolveBudget(
            max_results=1,
            max_candidates=4,
            max_context_tokens=512,
            max_latency_ms=500,
        ),
    )
    return request.model_copy(update=updates)


def _retrieval_body(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": "L1",
        "consistency": "CANONICAL_REQUIRED",
        "query_plan": {},
        "results": [item],
        "derived_result": None,
        "open_issue_ids": [],
        "retrieval_trace_id": str(uuid4()),
        "snapshot": {
            "canonical_outbox_sequence": 7,
            "evidence_watermark": 7,
            "fts_watermark": 7,
            "vector_watermark": 7,
        },
        "degraded_components": [],
        "fallback_used": False,
        "fallback_reason": None,
        "abstained": False,
        "abstention_reason": None,
        "progressive_l1": {},
        "access_plan": {},
        "access_trace": {"retrieval_trace_id": str(uuid4())},
    }


def _root(
    service: RetrievalContinuationService,
    context: SessionContext,
    request: MemoryResolveRequest,
) -> RetrievalContinuationState:
    result = service.register_root(
        context,
        request,
        context_id=uuid4(),
        selected_evidence_ids=[EVIDENCE_1],
        candidate_items=(_item(EVIDENCE_1, "boots"), _item(EVIDENCE_2, "blazer")),
        snapshot_as_of=datetime.now(UTC),
        canonical_position=7,
    )
    return result.state


def test_enabling_continuation_does_not_change_first_call_context() -> None:
    first_item = _item(EVIDENCE_1, "Bought boots.")
    candidates = (first_item, _item(EVIDENCE_2, "Bought a blazer."))
    body = _retrieval_body(first_item)
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request = _request()
    baseline = MemoryResolveService(
        cast(RecollectionFacade, _StaticRetrieve(body, candidates))
    ).resolve(context, request, "baseline")

    repository = _Repository()
    continuations = RetrievalContinuationService(
        cast(Any, repository),
        cast(Any, _Hydrator({EVIDENCE_2: candidates[1]})),
    )
    enabled = MemoryResolveService(
        cast(RecollectionFacade, _StaticRetrieve(body, candidates)),
        continuations=continuations,
    ).resolve(context, request, "enabled")

    for field in (
        "text",
        "semantic_context_digest",
        "reader_context_digest",
        "selected_evidence_ids",
        "selected_source_turn_refs",
    ):
        assert enabled.body["memory_context"][field] == baseline.body["memory_context"][field]
    assert enabled.body["continuation"]["available"] is True
    assert enabled.body["continuation"]["reason"] == "UNEXPANDED_FRONTIER"
    assert len(repository.states) == 1


def test_same_query_resumes_persisted_frontier_without_global_retrieval() -> None:
    repository = _Repository()
    hydrator = _Hydrator({EVIDENCE_2: _item(EVIDENCE_2, "Bought a blazer.")})
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, hydrator)
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    first_request = _request()
    root = _root(continuations, context, first_request)
    retrieval = _MustNotRetrieve()
    service = MemoryResolveService(
        cast(RecollectionFacade, retrieval),
        continuations=continuations,
    )

    result = service.resolve(
        context,
        _request(previous_context_id=root.state_id),
        "continuation-request",
    )

    assert retrieval.calls == 0
    # Root registration revalidates the persisted frontier once; page 2
    # revalidates the exact identity again before exposing it.
    assert hydrator.calls == [[EVIDENCE_2], [EVIDENCE_2]]
    assert result.body["evidence_refs"] == [EVIDENCE_2]
    assert "Bought a blazer." in result.body["memory_context"]["text"]
    assertion = result.body["continuation"]
    assert assertion["candidate_origin"] == "PERSISTED_FRONTIER"
    assert assertion["global_reacquisition_calls"] == 0
    assert assertion["candidate_pool_extension_calls"] == 0
    assert assertion["query_replanning_calls"] == 0
    assert assertion["available"] is False
    assert assertion["reason"] == "PERSISTED_FRONTIER_EXHAUSTED"
    assert result.body["context_receipt"]["context_id"] == assertion["context_id"]


def test_continuation_render_never_expands_to_adjacent_evidence() -> None:
    repository = _Repository()
    anchor = _structured_item(EVIDENCE_2, "Bought a blazer.", turn_ordinal=2)
    neighbor = _structured_item(EVIDENCE_3, "Bought trousers.", turn_ordinal=3)
    hydrator = _Hydrator({EVIDENCE_2: anchor})
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, hydrator)
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request = _request(query="What was mentioned in the same conversation?")
    root = continuations.register_root(
        context,
        request,
        context_id=uuid4(),
        selected_evidence_ids=[EVIDENCE_1],
        candidate_items=(_item(EVIDENCE_1, "Bought boots."), anchor),
        snapshot_as_of=datetime.now(UTC),
        canonical_position=7,
    ).state
    adjacency = _AdjacencyReader([neighbor])
    service = MemoryResolveService(
        cast(RecollectionFacade, _MustNotRetrieve()),
        continuations=continuations,
        context_compiler=MemoryContextCompiler(
            adjacency_reader=cast(Any, adjacency),
        ),
    )

    result = service.resolve(
        context,
        request.model_copy(update={"previous_context_id": root.state_id}),
        "continuation-with-adjacent-neighbor",
    )

    selected = set(result.body["memory_context"]["selected_evidence_ids"])
    assert adjacency.calls == 0
    assert selected == {EVIDENCE_2}
    assert selected.issubset(set(root.frontier_evidence_ids))
    assert repository.successor_commands[-1].selected_evidence_ids == (EVIDENCE_2,)
    assert result.body["memory_context"]["compile_trace"]["expansion_activation"][
        "reason"
    ] == "PERSISTED_FRONTIER_RENDER_ONLY"


def test_online_ineligible_candidate_is_consumed_without_becoming_visible() -> None:
    repository = _Repository()
    hydrator = _Hydrator({EVIDENCE_2: _item(EVIDENCE_2, "Bought a blazer.")})
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, hydrator)
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    request = _request()
    root = _root(continuations, context, request)
    hydrator.items.clear()
    page = continuations.page(
        context, _request(previous_context_id=root.state_id)
    )
    assert page is not None
    assert page.ineligible_evidence_ids == (EVIDENCE_2,)

    result = continuations.advance(
        context,
        _request(previous_context_id=root.state_id),
        page,
        visible_evidence_ids=[],
    )

    assert result.state.frontier_evidence_ids == ()
    assert result.state.online_ineligible_count == 1
    assert EVIDENCE_2 not in result.state.seen_evidence_ids


def test_continuation_rejects_query_or_request_drift() -> None:
    repository = _Repository()
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, _Hydrator({EVIDENCE_2: _item(EVIDENCE_2, "x")}))
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    root = _root(continuations, context, _request())

    with pytest.raises(
        RetrievalContinuationError,
        match="RETRIEVAL_CONTINUATION_QUERY_MISMATCH",
    ):
        continuations.page(
            context,
            MemoryResolveRequest(
                query="A different query",
                requested_scope={"project_ids": ["milai"]},
                budget=_request().budget,
                previous_context_id=root.state_id,
            ),
        )

    with pytest.raises(
        RetrievalContinuationError,
        match="RETRIEVAL_CONTINUATION_REQUEST_MISMATCH",
    ):
        continuations.page(
            context,
            _request(
                previous_context_id=root.state_id,
                required_freshness="STALE",
            ),
        )


def test_expired_state_fails_closed() -> None:
    repository = _Repository()
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, _Hydrator({}))
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    root = _root(continuations, context, _request())
    repository.states[root.state_id] = replace(
        root,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(
        RetrievalContinuationError,
        match="RETRIEVAL_CONTINUATION_UNAVAILABLE",
    ):
        continuations.page(
            context,
            _request(previous_context_id=root.state_id),
        )


def test_unknown_continuation_locator_never_falls_back_to_global_search() -> None:
    repository = _Repository()
    continuations = RetrievalContinuationService(
        cast(Any, repository), cast(Any, _Hydrator({}))
    )
    retrieval = _MustNotRetrieve()
    service = MemoryResolveService(
        cast(RecollectionFacade, retrieval),
        continuations=continuations,
    )

    with pytest.raises(
        RetrievalContinuationError,
        match="RETRIEVAL_CONTINUATION_UNAVAILABLE",
    ):
        service.resolve(
            SessionContext(TENANT_ID, ACTOR_ID),
            _request(previous_context_id=uuid4()),
            "unknown-continuation",
        )

    assert retrieval.calls == 0
