from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from milai.application.intra_source_acquisition import IntraSourceAcquisitionService
from milai.application.memory_resolve import MemoryResolveService
from milai.application.recollection import RecollectionFacade, RetrievalExecution
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.persistence import SessionContext

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("22222222-2222-4222-8222-222222222222")
EVIDENCE_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EVIDENCE_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EVIDENCE_3 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class _SessionSearch:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def search_evidence_within_sources(
        self,
        _context: SessionContext,
        query: str,
        coarse_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        *,
        hits_per_session: int,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "query": query,
                "coarse_evidence_ids": coarse_evidence_ids,
                "requested_scope": requested_scope,
                "as_of": as_of,
                "hits_per_session": hits_per_session,
                "max_items": max_items,
                "statement_timeout_ms": statement_timeout_ms,
            }
        )
        return deepcopy(self.results)


class _UnavailableSourceSearch(_SessionSearch):
    def search_evidence_within_sources(
        self,
        _context: SessionContext,
        query: str,
        coarse_evidence_ids: list[str],
        requested_scope: dict[str, object],
        as_of: datetime,
        *,
        hits_per_session: int,
        max_items: int,
        statement_timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        raise RuntimeError("simulated projection contract failure")


class _StaticRetrieve:
    def __init__(self, item: dict[str, Any], candidates: tuple[dict[str, Any], ...]) -> None:
        self.item = item
        self.candidates = candidates

    def retrieve(self, *_args: object, **_kwargs: object) -> RetrievalExecution:
        return RetrievalExecution(
            {
                "route": "L1",
                "consistency": "CANONICAL_REQUIRED",
                "query_plan": {},
                "results": [deepcopy(self.item)],
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
            },
            context_candidate_items=deepcopy(self.candidates),
        )


def _item(
    evidence_id: str,
    content: str,
    *,
    session_id: str,
    turn: int,
    fine_rank: int = 1,
) -> dict[str, Any]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": f"memory://{session_id}/turn-{turn}",
        "subject_id": "subject:self",
        "observed_at": "2026-09-05T00:00:00+00:00",
        "content": content,
        "content_hash": evidence_id.replace("-", "")[:32].ljust(64, "0"),
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"turn-{turn}",
            "turn_ordinal": turn,
            "round_id": f"round-{turn}",
            "round_ordinal": turn,
        },
        "fine_source_rank": fine_rank,
        "fine_global_rank": fine_rank,
        "relevance_score": 1.0,
    }


def _request() -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query="Recall purchase markers",
        requested_scope={"project_ids": ["milai"]},
        budget=MemoryResolveBudget(
            max_results=1,
            max_candidates=4,
            max_context_tokens=512,
            max_latency_ms=500,
        ),
    )


def test_shadow_search_is_bounded_to_exact_structured_coarse_sessions() -> None:
    anchor = _item(EVIDENCE_1, "Bought boots.", session_id="session-a", turn=1)
    other = _item(EVIDENCE_3, "Other.", session_id="session-b", turn=2)
    fine = _item(EVIDENCE_2, "Bought a blazer.", session_id="session-a", turn=7)
    repository = _SessionSearch([anchor, fine])
    service = IntraSourceAcquisitionService(cast(Any, repository))
    snapshot = datetime.now(UTC)

    result = service.shadow(
        SessionContext(TENANT_ID, ACTOR_ID),
        _request(),
        coarse_candidate_items=(
            anchor,
            other,
            {"kind": "CANONICAL_STATE", "claim_id": str(uuid4())},
        ),
        snapshot_as_of=snapshot,
        decision_digest="d" * 64,
    )

    assert repository.calls[0]["coarse_evidence_ids"] == [
        EVIDENCE_1,
        EVIDENCE_3,
    ]
    assert repository.calls[0]["hits_per_session"] == 8
    assert repository.calls[0]["max_items"] == 120
    assert result.trace["mode"] == "SHADOW"
    assert result.trace["new_global_source_acquisition_calls"] == 0
    assert result.trace["public_context_changed"] is False
    assert result.trace["frontier_changed"] is False
    candidates = cast(list[dict[str, object]], result.trace["candidates"])
    assert [candidate["evidence_id"] for candidate in candidates] == [
        EVIDENCE_1,
        EVIDENCE_2,
    ]
    assert candidates[0]["already_in_coarse_pool"] is True
    assert candidates[1]["already_in_coarse_pool"] is False
    assert all(candidate["discovery_disposition"] == "DIRECT_ANCHOR" for candidate in candidates)
    assert all("content" not in candidate for candidate in candidates)


def test_shadow_trace_does_not_change_first_call_memory_context() -> None:
    anchor = _item(EVIDENCE_1, "Bought boots.", session_id="session-a", turn=1)
    fine = _item(EVIDENCE_2, "Bought a blazer.", session_id="session-a", turn=7)
    retrieval = cast(RecollectionFacade, _StaticRetrieve(anchor, (anchor,)))
    context = SessionContext(TENANT_ID, ACTOR_ID)
    baseline = MemoryResolveService(retrieval).resolve(context, _request(), "baseline")
    treatment = MemoryResolveService(
        retrieval,
        intra_source_acquisition=IntraSourceAcquisitionService(
            cast(Any, _SessionSearch([anchor, fine]))
        ),
    ).resolve(context, _request(), "shadow")

    for field in (
        "text",
        "semantic_context_digest",
        "reader_context_digest",
        "selected_evidence_ids",
        "selected_source_turn_refs",
    ):
        assert treatment.body["memory_context"][field] == baseline.body["memory_context"][field]
    assert treatment.body["intra_source_acquisition_shadow"]["fine_candidate_count"] == 2
    assert treatment.body["intra_source_acquisition_shadow"]["public_context_changed"] is False


def test_shadow_projection_failure_is_fail_open_for_official_memory_context() -> None:
    anchor = _item(EVIDENCE_1, "Bought boots.", session_id="session-a", turn=1)
    retrieval = cast(RecollectionFacade, _StaticRetrieve(anchor, (anchor,)))
    context = SessionContext(TENANT_ID, ACTOR_ID)
    baseline = MemoryResolveService(retrieval).resolve(context, _request(), "baseline")
    treatment = MemoryResolveService(
        retrieval,
        intra_source_acquisition=IntraSourceAcquisitionService(
            cast(Any, _UnavailableSourceSearch([]))
        ),
    ).resolve(context, _request(), "shadow-unavailable")

    assert treatment.status_code == baseline.status_code
    assert treatment.body["memory_context"] == baseline.body["memory_context"]
    assert treatment.body["intra_source_acquisition_shadow"] == {
        "schema_version": "intra-source-acquisition-shadow-v0.1",
        "mode": "SHADOW",
        "status": "UNAVAILABLE",
        "reason": "RuntimeError",
        "public_context_changed": False,
        "frontier_changed": False,
        "new_global_source_acquisition_calls": 0,
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }


def test_shadow_does_not_silently_truncate_an_oversized_coarse_session_pool() -> None:
    coarse = tuple(
        _item(
            str(uuid4()),
            "Marker.",
            session_id=f"session-{ordinal}",
            turn=1,
        )
        for ordinal in range(51)
    )
    service = IntraSourceAcquisitionService(cast(Any, _SessionSearch([])))

    with pytest.raises(ValueError, match="coarse session pool"):
        service.shadow(
            SessionContext(TENANT_ID, ACTOR_ID),
            _request(),
            coarse_candidate_items=coarse,
            snapshot_as_of=datetime.now(UTC),
            decision_digest="d" * 64,
        )
