from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.api import create_app
from milai.application.errors import RetrievalContinuationError
from milai.application.intra_source_acquisition import IntraSourceAcquisitionService
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.persistence import Database, SessionContext
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_continuation_repository import (
    RetrievalContinuationRepository,
    RetrievalContinuationRootWrite,
    RetrievalContinuationSuccessorWrite,
)
from milai.persistence.retrieval_repository import RetrievalRepository
from milai.workers.main import FoundationWorker

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER_ACTOR_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def continuation_repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    _url("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token="test-token-with-at-least-32-characters",
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    prepare_runtime_directories(settings)
    database = Database(settings)
    yield RetrievalContinuationRepository(database)
    database.close()


@pytest.fixture
def continuation_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    _url("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "continuation-blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token="test-token-with-at-least-32-characters",
        agent_reader_token="reader-token-with-at-least-32-characters",
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
        worker_event_limit=10_000,
        worker_retry_delay_seconds=0,
        worker_max_attempts=1,
        retrieval_continuation_v0_1_enabled=True,
        intra_source_acquisition_v0_1_mode="SHADOW",
    )
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(settings, dsn=_url("MILAI_TEST_WORKER_DATABASE_URL"))
    app = create_app(
        settings,
        database=api_database,
        steward_database=steward_database,
    )
    app.config["TESTING"] = True
    yield settings, app, worker_database
    api_database.close()
    steward_database.close()
    worker_database.close()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.integration
@pytest.mark.security
def test_root_successor_idempotency_rls_and_no_frontier_extension(
    continuation_repository: RetrievalContinuationRepository,
) -> None:
    repository = continuation_repository
    owner = SessionContext(TENANT_ID, ACTOR_ID)
    other = SessionContext(TENANT_ID, OTHER_ACTOR_ID)
    root_id = uuid4()
    evidence_1 = str(uuid4())
    evidence_2 = str(uuid4())
    evidence_3 = str(uuid4())
    now = datetime.now(UTC)
    root = repository.create_root(
        owner,
        RetrievalContinuationRootWrite(
            state_id=root_id,
            query_digest=_digest("query"),
            request_digest=_digest("request"),
            snapshot_as_of=now,
            canonical_position=17,
            selected_evidence_ids=(evidence_1,),
            seen_evidence_ids=(evidence_1,),
            frontier_evidence_ids=(evidence_2,),
            online_ineligible_count=0,
            state_digest=_digest("root-state"),
            expires_at=now + timedelta(hours=1),
        ),
    )
    assert root.state.state_id == root_id
    assert root.state.frontier_evidence_ids == (evidence_2,)
    assert repository.get_owned(other, root_id) is None

    operation = _digest(f"same-predecessor-generation-query-snapshot:{root_id}")
    successor_id = uuid4()
    successor_command = RetrievalContinuationSuccessorWrite(
        state_id=successor_id,
        predecessor_state_id=root_id,
        operation_fingerprint=operation,
        selected_evidence_ids=(evidence_2,),
        seen_evidence_ids=(evidence_1, evidence_2),
        frontier_evidence_ids=(),
        discarded_evidence_ids=(),
        online_ineligible_count=0,
        state_digest=_digest("successor-state"),
    )
    successor = repository.create_successor(owner, successor_command)
    assert successor.replayed is False
    assert successor.state.generation == 1
    assert successor.state.frontier_evidence_ids == ()

    replay = repository.create_successor(owner, successor_command)
    assert replay.replayed is True
    assert replay.state.state_id == successor_id

    with pytest.raises(RetrievalContinuationError, match="OPERATION_CONFLICT"):
        repository.create_successor(
            owner,
            replace(
                successor_command,
                state_id=uuid4(),
                state_digest=_digest("racing-state"),
            ),
        )

    with pytest.raises(
        RetrievalContinuationError,
        match="INVALID_RETRIEVAL_CONTINUATION",
    ):
        repository.create_successor(
            owner,
            RetrievalContinuationSuccessorWrite(
                state_id=uuid4(),
                predecessor_state_id=root_id,
                operation_fingerprint=_digest(f"new-operation:{root_id}"),
                selected_evidence_ids=(),
                seen_evidence_ids=(evidence_1,),
                frontier_evidence_ids=(evidence_3,),
                discarded_evidence_ids=(),
                online_ineligible_count=0,
                state_digest=_digest("invalid-extension"),
            ),
        )


@pytest.mark.integration
def test_memory_resolve_exposes_novel_persisted_frontier_page(
    continuation_app,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = continuation_app
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token-with-at-least-32-characters"}
    for ordinal, purchase in enumerate(("boots", "blazer", "trousers"), start=1):
        capture = client.post(
            "/v1/evidence",
            headers={**headers, "Idempotency-Key": f"continuation-capture-{uuid4()}"},
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"continuation://session-{ordinal}/turn-1",
                "subject_id": "continuation-test",
                "speaker": "user",
                "source_context": {
                    "session_id": f"continuation-session-{ordinal}",
                    "turn_id": "turn-1",
                    "turn_ordinal": 1,
                    "round_id": "round-1",
                    "round_ordinal": 1,
                },
                "observed_at": f"2026-09-0{ordinal}T10:00:00+08:00",
                "content": f"Purchase marker: bought {purchase}.",
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert capture.status_code == 201

    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"continuation-worker-{uuid4()}",
    )
    assert worker.run_once() > 0

    payload: dict[str, object] = {
        "query": "Recall every purchase marker",
        "requested_scope": {"project_ids": ["milai"]},
        "budget": {
            "max_results": 1,
            "max_candidates": 4,
            "max_context_tokens": 512,
            "max_latency_ms": 1000,
        },
    }
    first = client.post("/v1/memory/resolve", headers=headers, json=payload)
    assert first.status_code == 200
    first_ids = set(first.json["memory_context"]["selected_evidence_ids"])
    assert len(first_ids) == 1
    assert first.json["continuation"]["available"] is True
    assert first.json["intra_source_acquisition_shadow"]["mode"] == "SHADOW"
    assert first.json["intra_source_acquisition_shadow"]["public_context_changed"] is False
    first_context_id = first.json["context_receipt"]["context_id"]
    assert first.json["continuation"]["context_id"] == first_context_id

    for changed in (
        {"query": "A different purchase query"},
        {"requested_scope": {"project_ids": ["other-project"]}},
    ):
        rejected = client.post("/v1/memory/resolve", headers=headers,
                               json={**payload, "previous_context_id": first_context_id,
                                     **changed})
        assert rejected.status_code == 409
        assert "RETRIEVAL_CONTINUATION_" in str(rejected.json)

    unknown = client.post("/v1/memory/resolve", headers=headers,
                          json={**payload, "previous_context_id": str(uuid4())})
    assert unknown.status_code == 409
    assert "RETRIEVAL_CONTINUATION_" in str(unknown.json)

    second = client.post(
        "/v1/memory/resolve",
        headers=headers,
        json={**payload, "previous_context_id": first_context_id},
    )
    assert second.status_code == 200
    second_ids = set(second.json["memory_context"]["selected_evidence_ids"])
    assert len(second_ids) == 1
    assert first_ids.isdisjoint(second_ids)
    assertion = second.json["continuation"]
    assert assertion["candidate_origin"] == "PERSISTED_FRONTIER"
    assert assertion["global_reacquisition_calls"] == 0
    assert assertion["candidate_pool_extension_calls"] == 0
    assert assertion["query_replanning_calls"] == 0
    assert second.json["access_trace"]["planned_stage"] == "PERSISTED_FRONTIER"
    assert "intra_source_acquisition_shadow" not in second.json

    replay = client.post(
        "/v1/memory/resolve",
        headers=headers,
        json={**payload, "previous_context_id": first_context_id},
    )
    assert replay.status_code == 200
    assert replay.json["memory_context"]["selected_evidence_ids"] == sorted(second_ids)
    assert replay.json["continuation"]["context_id"] == assertion["context_id"]
    assert replay.json["continuation"]["operation_replayed"] is True


@pytest.mark.integration
def test_trace_v2_rejects_real_ready_source_change(continuation_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import milai.testkit.retrieval_trace as trace

    settings, app, worker_database = continuation_app
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token-with-at-least-32-characters"}
    worker = FoundationWorker(
        settings, worker_database, repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(), worker_id=f"trace-change-{uuid4()}",
    )

    def capture(ordinal: int) -> None:
        response = client.post("/v1/evidence", headers={**headers, "Idempotency-Key": str(uuid4())},
                               json={"source_type": "RUNTIME_OBSERVATION",
                                     "source_ref": f"trace-change://{ordinal}",
                                     "subject_id": "trace-change", "speaker": "user",
                                     "observed_at": "2026-01-01T10:00:00Z",
                                     "content": f"Purchase marker: item {ordinal} awaits pickup.",
                                     "media_type": "text/plain",
                                     "permission_snapshot": {"readable": True,
                                                             "project_ids": ["trace-change"]},
                                     "retention_state": "READABLE"})
        assert response.status_code == 201
        assert worker.run_once() > 0

    capture(1)
    original = trace._resolve_once
    bodies = []

    def changed_resolve(*args, **kwargs):  # type: ignore[no-untyped-def]
        body = original(*args, **kwargs)
        bodies.append(body)
        if len(bodies) == 1:
            capture(2)
        return body

    monkeypatch.setattr(trace, "_resolve_once", changed_resolve)
    # Deliberate future cutoff makes both public captures eligible; this is a mutation control.
    request = trace.RetrievalTraceTestkitRequest.model_validate({
        "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
        "comparison_semantics_version": "v0.2", "run_identity": "ready-change-negative",
        "source_snapshot_as_of": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "memory_request": {"query": "Recall purchase marker items awaiting pickup",
                           "requested_scope": {"project_ids": ["trace-change"]}},
    })
    with pytest.raises(RuntimeError, match="TRACING_BEHAVIOR_CHANGED"):
        trace.run_live_retrieval_trace(request, settings=settings)
    assert len(bodies) == 3
    assert bodies[0]["memory_context"]["selected_evidence_ids"] != (
        bodies[1]["memory_context"]["selected_evidence_ids"]
    ), "negative control must actually change admitted Evidence"


@pytest.mark.integration
def test_continuation_renderer_does_not_hydrate_late_adjacent_evidence(
    continuation_app,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = continuation_app
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token-with-at-least-32-characters"}

    for ordinal in (1, 2):
        captured = client.post(
            "/v1/evidence",
            headers={**headers, "Idempotency-Key": f"no-adjacent-root-{uuid4()}"},
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"no-adjacent://session-{ordinal}/turn-1",
                "subject_id": "no-adjacent-continuation",
                "speaker": "user",
                "source_context": {
                    "session_id": f"no-adjacent-session-{ordinal}",
                    "turn_id": "turn-1",
                    "turn_ordinal": 1,
                    "round_id": "round-1",
                    "round_ordinal": 1,
                    "next_turn_id": "turn-2",
                },
                "observed_at": f"2026-09-0{ordinal}T10:00:00+08:00",
                "content": f"Same conversation purchase marker {ordinal}.",
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert captured.status_code == 201

    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"no-adjacent-worker-{uuid4()}",
    )
    assert worker.run_once() > 0
    payload: dict[str, object] = {
        "query": "Recall every purchase marker from the same conversation",
        "requested_scope": {"project_ids": ["milai"]},
        "budget": {
            "max_results": 1,
            "max_candidates": 4,
            "max_context_tokens": 512,
            "max_latency_ms": 1000,
        },
    }
    first = client.post("/v1/memory/resolve", headers=headers, json=payload)
    assert first.status_code == 200
    root_id = first.json["continuation"]["context_id"]
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        frontier_row = owner.execute(
            """
            SELECT state.frontier_evidence_ids,
                   document.source_session_id,
                   document.source_turn_id
            FROM milai.retrieval_continuation_state state
            JOIN milai.evidence_search_document document
              ON document.tenant_id = state.tenant_id
             AND document.evidence_id =
                 (state.frontier_evidence_ids ->> 0)::uuid
            WHERE state.tenant_id = %s AND state.state_id = %s
            """,
            (settings.tenant_id, UUID(root_id)),
        ).fetchone()
    assert frontier_row is not None and len(frontier_row[0]) == 1
    frontier_id = str(frontier_row[0][0])
    frontier_session = str(frontier_row[1])
    frontier_turn = str(frontier_row[2])

    late_neighbor = client.post(
        "/v1/evidence",
        headers={**headers, "Idempotency-Key": f"late-adjacent-{uuid4()}"},
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"no-adjacent://{frontier_session}/turn-2",
            "subject_id": "no-adjacent-continuation",
            "speaker": "user",
            "source_context": {
                "session_id": frontier_session,
                "turn_id": "turn-2",
                "turn_ordinal": 2,
                "round_id": "round-2",
                "round_ordinal": 2,
                "previous_turn_id": frontier_turn,
            },
            # Observed before the root snapshot, but projected only afterwards.
            # It is intentionally outside the persisted frontier.
            "observed_at": "2026-09-03T10:00:00+08:00",
            "content": "Late adjacent evidence must not enter continuation rendering.",
            "media_type": "text/plain",
            "permission_snapshot": {
                "readable": True,
                "project_ids": ["milai"],
            },
            "retention_state": "READABLE",
        },
    )
    assert late_neighbor.status_code == 201
    late_neighbor_id = late_neighbor.json["evidence_id"]
    assert worker.run_once() > 0

    second = client.post(
        "/v1/memory/resolve",
        headers=headers,
        json={**payload, "previous_context_id": root_id},
    )
    assert second.status_code == 200, second.json
    selected = set(second.json["memory_context"]["selected_evidence_ids"])
    assert selected == {frontier_id}
    assert late_neighbor_id not in selected
    assert second.json["memory_context"]["compile_trace"]["expansion_activation"][
        "reason"
    ] == "PERSISTED_FRONTIER_RENDER_ONLY"
    assert second.json["continuation"]["candidate_origin"] == "PERSISTED_FRONTIER"


@pytest.mark.integration
@pytest.mark.security
def test_same_scope_oauth_principals_cannot_consume_each_others_frontier(
    continuation_app,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = continuation_app
    client = app.test_client()
    writer_headers = {
        "Authorization": "Bearer test-token-with-at-least-32-characters"
    }
    for ordinal in range(2):
        capture = client.post(
            "/v1/evidence",
            headers={
                **writer_headers,
                "Idempotency-Key": f"principal-isolation-capture-{uuid4()}",
            },
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"principal-isolation://session/{ordinal}",
                "subject_id": "principal-isolation",
                "speaker": "user",
                "observed_at": f"2026-09-01T0{ordinal}:00:00+00:00",
                "content": f"Purchase marker: bought isolation item {ordinal}.",
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert capture.status_code == 201

    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"principal-isolation-worker-{uuid4()}",
    )
    assert worker.run_once() > 0

    def reader_headers(binding: str) -> dict[str, str]:
        return {
            "Authorization": "Bearer reader-token-with-at-least-32-characters",
            "X-MiLA-Host-Principal-Binding-Digest": binding,
        }

    payload: dict[str, object] = {
        "query": "Recall every purchase marker",
        "requested_scope": {"project_ids": ["milai"]},
        "budget": {
            "max_results": 1,
            "max_candidates": 4,
            "max_context_tokens": 512,
            "max_latency_ms": 1000,
        },
    }
    first = client.post(
        "/v1/memory/resolve",
        headers=reader_headers("a" * 64),
        json=payload,
    )
    assert first.status_code == 200
    assert "continuation" in first.json, first.json
    context_id = first.json["continuation"]["context_id"]
    assert first.json["continuation"]["available"] is True

    denied = client.post(
        "/v1/memory/resolve",
        headers=reader_headers("b" * 64),
        json={**payload, "previous_context_id": context_id},
    )
    assert denied.status_code == 409
    assert denied.json["error"]["code"] == "RETRIEVAL_CONTINUATION_UNAVAILABLE"

    owner = client.post(
        "/v1/memory/resolve",
        headers=reader_headers("a" * 64),
        json={**payload, "previous_context_id": context_id},
    )
    assert owner.status_code == 200
    assert owner.json["continuation"]["candidate_origin"] == "PERSISTED_FRONTIER"


@pytest.mark.integration
@pytest.mark.security
def test_projection_identity_mismatch_becomes_ineligible_not_exhausted_or_visible(
    continuation_app,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = continuation_app
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token-with-at-least-32-characters"}
    for ordinal in range(2):
        capture = client.post(
            "/v1/evidence",
            headers={**headers, "Idempotency-Key": f"hash-mismatch-{uuid4()}"},
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"hash-mismatch://session/{ordinal}",
                "subject_id": "hash-mismatch",
                "speaker": "user",
                "observed_at": f"2026-09-01T0{ordinal}:00:00+00:00",
                "content": f"Hash identity marker purchase {ordinal}.",
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert capture.status_code == 201
    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"hash-mismatch-worker-{uuid4()}",
    )
    assert worker.run_once() > 0

    payload: dict[str, object] = {
        "query": "Recall hash identity marker purchase",
        "requested_scope": {"project_ids": ["milai"]},
        "budget": {
            "max_results": 1,
            "max_candidates": 4,
            "max_context_tokens": 512,
            "max_latency_ms": 1000,
        },
    }
    first = client.post("/v1/memory/resolve", headers=headers, json=payload)
    assert first.status_code == 200
    root_id = first.json["continuation"]["context_id"]
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        row = owner.execute(
            """
            SELECT frontier_evidence_ids
            FROM milai.retrieval_continuation_state
            WHERE tenant_id = %s AND state_id = %s
            """,
            (settings.tenant_id, UUID(root_id)),
        ).fetchone()
        assert row is not None and len(row[0]) == 1
        frontier_id = UUID(str(row[0][0]))
        owner.execute(
            """
            UPDATE milai.evidence_search_document
            SET content_hash = %s
            WHERE tenant_id = %s AND evidence_id = %s
            """,
            ("0" * 64, settings.tenant_id, frontier_id),
        )

    second = client.post(
        "/v1/memory/resolve",
        headers=headers,
        json={**payload, "previous_context_id": root_id},
    )
    assert second.status_code == 200
    assert second.json["memory_context"]["selected_evidence_ids"] == []
    assertion = second.json["continuation"]
    assert assertion["available"] is False
    assert assertion["reason"] == "FRONTIER_ELIGIBILITY_CHANGED"
    assert assertion["online_ineligible_count"] == 1

    terminal = client.post(
        "/v1/memory/resolve",
        headers=headers,
        json={**payload, "previous_context_id": assertion["context_id"]},
    )
    assert terminal.status_code == 200
    assert terminal.json["continuation"]["reason"] == (
        "FRONTIER_ELIGIBILITY_CHANGED"
    )


@pytest.mark.integration
def test_intra_source_lexical_shadow_stays_inside_coarse_session_pool(
    continuation_app,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = continuation_app
    client = app.test_client()
    headers = {"Authorization": "Bearer test-token-with-at-least-32-characters"}
    captured_ids: list[str] = []
    for source_type, session_id, turn, project_id in (
        ("RUNTIME_OBSERVATION", "fine-session-in-pool", 1, "milai"),
        ("RUNTIME_OBSERVATION", "fine-session-in-pool", 7, "milai"),
        ("RUNTIME_OBSERVATION", "fine-session-outside-pool", 1, "milai"),
        ("USER_OBSERVATION", "fine-session-in-pool", 9, "milai"),
        ("RUNTIME_OBSERVATION", "fine-session-in-pool", 11, "other-project"),
    ):
        capture = client.post(
            "/v1/evidence",
            headers={**headers, "Idempotency-Key": f"fine-shadow-{uuid4()}"},
            json={
                "source_type": source_type,
                "source_ref": f"fine-shadow://{source_type}/{session_id}/turn-{turn}",
                "subject_id": "fine-shadow-test",
                "speaker": "user",
                "source_context": {
                    "session_id": session_id,
                    "turn_id": f"turn-{turn}",
                    "turn_ordinal": turn,
                    "round_id": f"round-{turn}",
                    "round_ordinal": turn,
                },
                "observed_at": "2026-09-01T10:00:00+08:00",
                "content": f"Fine lexical marker purchase at turn {turn}.",
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": [project_id],
                },
                "retention_state": "READABLE",
            },
        )
        assert capture.status_code == 201
        captured_ids.append(capture.json["evidence_id"])

    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"fine-shadow-worker-{uuid4()}",
    )
    assert worker.run_once() > 0

    fine_database = Database(settings)
    service = IntraSourceAcquisitionService(RetrievalRepository(fine_database))
    request = MemoryResolveRequest(
        query="Recall fine lexical marker purchase",
        requested_scope={"project_ids": ["milai"]},
        budget=MemoryResolveBudget(
            max_results=1,
            max_candidates=4,
            max_context_tokens=512,
            max_latency_ms=1000,
        ),
    )
    coarse_anchor = {
        "kind": "EVIDENCE_OBSERVATION",
        "evidence_id": captured_ids[0],
        "source_ref": "fine-shadow://fine-session-in-pool/turn-1",
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": "fine-session-in-pool",
            "turn_id": "turn-1",
        },
    }
    try:
        result = service.shadow(
            SessionContext(settings.tenant_id, settings.local_actor_id),
            request,
            coarse_candidate_items=(coarse_anchor,),
            snapshot_as_of=datetime.now(UTC),
            decision_digest="d" * 64,
        )
    finally:
        fine_database.close()

    fine_ids = {str(item["evidence_id"]) for item in result.candidate_items}
    assert fine_ids == {captured_ids[0], captured_ids[1]}
    assert captured_ids[2] not in fine_ids
    assert captured_ids[3] not in fine_ids
    assert captured_ids[4] not in fine_ids
    assert result.trace["requested_coarse_session_ids"] == ["fine-session-in-pool"]
    assert result.trace["matched_eligible_source_keys"] == [
        {
            "source_type": "RUNTIME_OBSERVATION",
            "session_id": "fine-session-in-pool",
        }
    ]
    assert result.trace["new_global_source_acquisition_calls"] == 0
