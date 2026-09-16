from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from milai.adapters.embedding import ProjectionIdentity
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import EvidenceAcquisitionExecutor
from milai.application.query_planner import QueryPlanner
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.retrieval_repository import ProjectionState
from milai.testkit.context_replay import (
    FrozenAcquisitionSnapshot,
    FrozenReplayInvariantError,
    capture_frozen_acquisition_snapshot,
    replay_frozen_context,
)

REFERENCE = datetime(2026, 9, 3, 8, tzinfo=UTC)
CONTEXT = SessionContext(UUID(int=1), UUID(int=2))


class _Embedding:
    dimensions = 128
    identity = ProjectionIdentity(
        provider="synthetic",
        model_id="synthetic-128",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="test-v1",
    )

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [float(len(text) % 7)] * 128

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class _Repository:
    def __init__(self) -> None:
        self.fts_calls = 0
        self.vector_calls = 0
        self.locality_calls = 0

    def search_evidence(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        self.fts_calls += 1
        return [
            _evidence(
                "answer-support",
                "answer-session",
                "I paid $60 for six ceramic planters.",
                1.0,
            ),
            _evidence(
                "governed-unbound",
                "noise-session",
                "A different household purchase was discussed.",
                0.5,
            ),
        ]

    def search_evidence_dense(
        self, *args: object, **kwargs: object
    ) -> dict[str, object]:
        self.vector_calls += 1
        return {
            "status": "COMPLETE",
            "items": [
                _evidence(
                    "dense-only",
                    "dense-session",
                    "The planter order had a total and an item count.",
                    0.9,
                )
            ],
        }

    def hydrate_evidence_adjacency(
        self, *args: object, **kwargs: object
    ) -> list[dict[str, object]]:
        self.locality_calls += 1
        return []

    def scan_evidence_range(self, *args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("non-temporal replay cannot scan a range")


def _evidence(
    evidence_id: str,
    session_id: str,
    content: str,
    score: float,
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": evidence_id,
        "source_ref": f"memory://session/{session_id}/turn/0",
        "subject_id": "fixture-user",
        "observed_at": REFERENCE.isoformat(),
        "captured_at": REFERENCE.isoformat(),
        "content": content,
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": "turn-0",
            "turn_ordinal": 0,
            "round_id": "round-0",
            "round_ordinal": 0,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
        "relevance_score": score,
    }


def _snapshot() -> tuple[
    FrozenAcquisitionSnapshot,
    EvidenceAcquisitionExecutor,
    _Repository,
    _Embedding,
]:
    query = "How much did I pay per ceramic planter?"
    memory_request = MemoryResolveRequest(
        query=query,
        requested_scope={"project_ids": ["milai"]},
        budget=MemoryResolveBudget(
            max_results=10,
            max_candidates=120,
            max_context_tokens=16_384,
            max_latency_ms=5_000,
        ),
        reference_time=REFERENCE,
    )
    retrieval_request = RetrievalRequest(
        route="L1",
        query=query,
        requested_scope={"project_ids": ["milai"]},
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
        required_authority="INFORMATIONAL",
    )
    query_plan = QueryPlanner().plan(retrieval_request)
    acquisition_plan = compile_acquisition_plan(
        query_plan,
        query=query,
        principal_scope=retrieval_request.requested_scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=240,
        context_tokens=32_000,
        enable_dense=True,
        enable_same_session_expansion=True,
        additive_union_v0_2=True,
    )
    repository = _Repository()
    embedding = _Embedding()
    policy = AcquisitionCapabilityPolicy(
        policy_version="product08-test-v0.1",
        max_candidates=240,
        max_hydrated_items=160,
    )
    projection_state = ProjectionState(7, 7, 7, False, False, 7, False)
    capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            evidence_dense_enabled=True,
            embedding_projection_dimensions=128,
            adjacent_turns_acquisition_enabled=True,
        ),
        projection_state=projection_state,
        repository=repository,
        policy=policy,
        generated_at=REFERENCE,
    )
    executor = EvidenceAcquisitionExecutor(repository, embedding)
    snapshot = capture_frozen_acquisition_snapshot(
        executor=executor,
        context=CONTEXT,
        memory_request=memory_request,
        retrieval_request=retrieval_request,
        query_plan=query_plan,
        acquisition_plan=acquisition_plan,
        capability_set=capabilities,
        projection_state=projection_state,
    )
    return snapshot, executor, repository, embedding


def test_product08_replays_boundary_change_without_fresh_external_calls() -> None:
    snapshot, executor, repository, embedding = _snapshot()
    capture_counts = (
        repository.fts_calls,
        repository.vector_calls,
        repository.locality_calls,
        embedding.calls,
    )

    control = replay_frozen_context(snapshot, "C", executor=executor)
    admission = replay_frozen_context(snapshot, "X", executor=executor)
    hybrid = replay_frozen_context(snapshot, "Y", executor=executor)

    assert control["before_boundary"]["trace_sha256"] == (
        admission["before_boundary"]["trace_sha256"]
    )
    assert control["decision_snapshot_digest"] == admission["decision_snapshot_digest"]
    assert set(control["reader_visible_evidence_ids"]).issubset(
        admission["reader_visible_evidence_ids"]
    )
    assert control["reader_visible_evidence_ids"] == []
    assert admission["reader_visible_evidence_ids"]
    assert admission["packing"]["reader_readiness"] == "READY"
    assert "dense-only" in hybrid["boundary"]["before_boundary_ids"]
    assert (
        repository.fts_calls,
        repository.vector_calls,
        repository.locality_calls,
        embedding.calls,
    ) == capture_counts
    serialized = json.dumps({"C": control, "X": admission, "Y": hybrid})
    assert "I paid $60" not in serialized
    assert all(arm["fresh_repository_calls"] == 0 for arm in (control, admission, hybrid))


def test_product08_replay_fails_closed_when_snapshot_material_drifts() -> None:
    snapshot, executor, _repository, _embedding = _snapshot()
    drifted_plan = snapshot.acquisition_plan.model_copy(
        update={"query_ir_digest": "a" * 64}
    )
    drifted = replace(snapshot, acquisition_plan=drifted_plan)

    with pytest.raises(
        FrozenReplayInvariantError,
        match="FROZEN_ACQUISITION_SNAPSHOT_DRIFT",
    ):
        replay_frozen_context(drifted, "X", executor=executor)

    drifted_request = snapshot.memory_request.model_copy(
        update={"requested_scope": {"project_ids": ["other-project"]}}
    )
    with pytest.raises(
        FrozenReplayInvariantError,
        match="FROZEN_ACQUISITION_SNAPSHOT_DRIFT",
    ):
        replay_frozen_context(
            replace(snapshot, memory_request=drifted_request),
            "X",
            executor=executor,
        )
