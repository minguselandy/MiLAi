from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from milai.adapters import (
    DeterministicHashEmbedding,
    EmbeddingProvider,
    ErasureProof,
    LocalContentAddressedBlobStore,
    ProjectionIdentity,
)
from milai.adapters.http_models import HTTPEmbedding
from milai.api import create_app
from milai.application import RetrievalService
from milai.application.appointment_composition import compose_evidence_range_count
from milai.application.evidence_dense import evidence_turn_projection_version
from milai.application.query_planner import QueryPlanner
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain.retrieval import RetrievalRequest
from milai.operations.evidence_dense_rebuild import rebuild_evidence_dense
from milai.operations.smoke import _create_database, _database_url, _drop_database
from milai.persistence import Database, SessionContext
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_repository import RetrievalRepository
from milai.workers.main import FoundationWorker

ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
REVIEWER_TOKEN = "reviewer-token-with-at-least-32-characters"
OPERATOR_TOKEN = "operator-token-with-at-least-32-characters"
READER_TOKEN = "reader-token-with-at-least-32-characters"


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _settings(
    tmp_path: Path,
    tenant_id: UUID,
    *,
    max_attempts: int = 5,
    retry_delay: int = 0,
) -> RuntimeSettings:
    return RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=tenant_id,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        agent_reviewer_token=REVIEWER_TOKEN,
        agent_operator_token=OPERATOR_TOKEN,
        agent_reader_token=READER_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
        worker_event_limit=10000,
        worker_max_attempts=max_attempts,
        worker_retry_delay_seconds=retry_delay,
    )


@pytest.fixture
def worker_runtime(tmp_path: Path, request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    tenant_id = uuid4()
    settings = _settings(tmp_path, tenant_id)
    if getattr(request, "param", False):
        settings = settings.model_copy(update={"request_timing_enabled": True})
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(settings, dsn=_url("MILAI_TEST_WORKER_DATABASE_URL"))
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    yield settings, app, worker_database
    api_database.close()
    steward_database.close()
    worker_database.close()


def _headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _review_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {REVIEWER_TOKEN}",
        "Idempotency-Key": key,
    }


def _operator_headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _reader_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {READER_TOKEN}"}


def _ingest(client, content: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"worker-test://{uuid4()}",
            "subject_id": "worker-projection-subject",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201
    fetched = client.get(f"/v1/evidence/{response.json['evidence_id']}", headers=_headers())
    assert fetched.status_code == 200
    return {
        "evidence_id": response.json["evidence_id"],
        "blob_id": response.json["blob_id"],
        "outbox_id": response.json["outbox_id"],
        "content_hash": fetched.json["content_hash"],
    }


def _create_claim(client, evidence_id: str, *, memory_text: str | None = None) -> dict[str, str]:  # type: ignore[no-untyped-def]
    payload = {"value": "3.12", "keywords": "python runtime deployment"}
    if memory_text is not None:
        payload["memory_text"] = memory_text
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": f"projection-{uuid4()}",
                "predicate": "runtime.python.version",
                "claim_type": "FACT",
                "payload": payload,
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "worker-test-v1",
            "derivation_snapshot": {"fixture": "projection-worker"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "worker-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    return {
        "claim_id": review.json["claim_id"],
        "claim_version_id": review.json["claim_version_id"],
    }


def _worker(
    settings: RuntimeSettings,
    database: Database,
    *,
    embedding: EmbeddingProvider | None = None,
    worker_id: str,
) -> FoundationWorker:
    return FoundationWorker(
        settings,
        database,
        repository=ProjectionRepository(database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=embedding,
        worker_id=worker_id,
    )


class _Synthetic128Embedding:
    dimensions = 128
    identity = ProjectionIdentity(
        provider="synthetic_test",
        model_id="synthetic-128d",
        source_dimensions=128,
        projection_dimensions=128,
        normalization="l2",
        code_version="projection-128/v1",
    )

    def __init__(self) -> None:
        self.scalar_calls = 0
        self.batch_calls = 0
        self.batch_logical_items = 0

    def embed(self, text: str) -> list[float]:
        self.scalar_calls += 1
        vector = [0.0] * self.dimensions
        vector[0] = 1.0
        return vector

    def embed_many(self, texts: list[str], batch_size: int) -> list[list[float]]:
        assert 1 <= len(texts) <= batch_size
        self.batch_calls += 1
        self.batch_logical_items += len(texts)
        vector = [0.0] * self.dimensions
        vector[0] = 1.0
        return [list(vector) for _text in texts]


@pytest.mark.integration
def test_projection_worker_builds_fts_vector_and_contiguous_watermarks(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, f"projection-content-{uuid4()}")
    claim = _create_claim(client, evidence["evidence_id"])

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="projection-success-worker",
    )
    assert worker.run_once() > 0
    assert worker.run_once() == 0

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        document_count = owner.execute(
            """
            SELECT count(*) FROM milai.search_document
            WHERE tenant_id = %s AND claim_version_id = %s
              AND search_vector @@ websearch_to_tsquery('simple', 'python deployment')
            """,
            (settings.tenant_id, claim["claim_version_id"]),
        ).fetchone()[0]
        embedding_count = owner.execute(
            """
            SELECT count(*) FROM milai.search_embedding
            WHERE tenant_id = %s AND claim_version_id = %s
            """,
            (settings.tenant_id, claim["claim_version_id"]),
        ).fetchone()[0]
        max_sequence = owner.execute(
            "SELECT max(outbox_sequence) FROM milai.outbox_event WHERE tenant_id = %s",
            (settings.tenant_id,),
        ).fetchone()[0]
        watermarks = dict(
            owner.execute(
                """
                SELECT projection_name, last_contiguous_outbox_sequence
                FROM milai.index_watermark WHERE tenant_id = %s
                """,
                (settings.tenant_id,),
            ).fetchall()
        )
    assert document_count == 1
    assert embedding_count == 1
    assert watermarks == {
        "evidence": max_sequence,
        "fts": max_sequence,
        "purge": max_sequence,
        "vector": max_sequence,
    }


@pytest.mark.integration
def test_older_claim_projection_finishes_after_new_version_without_head_regression(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, "The runtime was upgraded from 3.12 to 3.13.")
    old = _create_claim(client, evidence["evidence_id"], memory_text="runtime before upgrade")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"late-projection-{uuid4()}"),
        json={
            "target_claim_id": old["claim_id"],
            "operation": "SUPERSEDE",
            "expected_version_id": old["claim_version_id"],
            "proposed_patch": {
                "payload": {"value": "3.13", "memory_text": "runtime after upgrade"},
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence["evidence_id"]],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "worker-test-v1",
            "derivation_snapshot": {"fixture": "late-projection"},
        },
    )
    assert proposal.status_code == 201
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"late-projection-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "worker-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    new_version = review.json["claim_version_id"]
    assert new_version != old["claim_version_id"]

    repository = ProjectionRepository(worker_database)
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    worker_id = "late-projection-worker"
    worker = _worker(
        settings, worker_database, embedding=DeterministicHashEmbedding(), worker_id=worker_id
    )
    for projection in ("fts", "vector"):
        events = repository.lease_many(context, projection, worker_id, 30, 5, 32)
        older = [
            event for event in events
            if event.payload.get("claim_version_id") == old["claim_version_id"]
        ]
        newer = [
            event for event in events
            if event.payload.get("claim_version_id") == new_version
        ]
        assert older and newer
        assert max(event.outbox_sequence for event in older) < min(
            event.outbox_sequence for event in newer
        )
        for event in events:
            if event not in older:
                worker._process(projection, event)

        with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
            before = owner.execute(
                "SELECT last_contiguous_outbox_sequence FROM milai.index_watermark "
                "WHERE tenant_id = %s AND projection_name = %s",
                (settings.tenant_id, projection),
            ).fetchone()[0]
            delivered = owner.execute(
                "SELECT count(*) FROM milai.projection_delivery "
                "WHERE tenant_id = %s AND projection_name = %s "
                "AND outbox_id = ANY(%s) AND state = 'DELIVERED'",
                (settings.tenant_id, projection, [event.outbox_id for event in newer]),
            ).fetchone()[0]
        assert delivered == len(newer)
        assert before < min(event.outbox_sequence for event in older)

        # The older task still has a valid lease; this is not a lost-owner rejection.
        for event in older:
            worker._process(projection, event)
        with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
            watermark = owner.execute(
                "SELECT last_contiguous_outbox_sequence FROM milai.index_watermark "
                "WHERE tenant_id = %s AND projection_name = %s",
                (settings.tenant_id, projection),
            ).fetchone()[0]
            head = owner.execute(
                "SELECT current_claim_version_id FROM milai.claim_head "
                "WHERE tenant_id = %s AND claim_id = %s",
                (settings.tenant_id, old["claim_id"]),
            ).fetchone()[0]
            documents = owner.execute(
                "SELECT claim_version_id FROM milai.search_document "
                "WHERE tenant_id = %s AND claim_id = %s",
                (settings.tenant_id, old["claim_id"]),
            ).fetchall()
            embeddings = owner.execute(
                "SELECT claim_version_id FROM milai.search_embedding "
                "WHERE tenant_id = %s AND claim_id = %s",
                (settings.tenant_id, old["claim_id"]),
            ).fetchall()
        assert watermark == max(event.outbox_sequence for event in events)
        assert str(head) == new_version
        expected_versions = {old["claim_version_id"], new_version}
        assert {str(row[0]) for row in documents} == expected_versions
        if projection == "vector":
            assert {str(row[0]) for row in embeddings} == expected_versions
        current = client.get(f"/v1/claims/{old['claim_id']}", headers=_headers())
        assert current.status_code == 200
        assert current.json["claim_version_id"] == new_version
        assert current.json["payload"]["value"] == "3.13"


@pytest.mark.integration
def test_current_owner_can_renew_but_stale_owner_cannot_mutate_lease(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    evidence = _ingest(app.test_client(), f"lease-renewal-{uuid4()}")
    repository = ProjectionRepository(worker_database)
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    events = repository.lease_many(context, "fts", "lease-owner-a", 2, 5, 1)
    assert len(events) == 1
    event = events[0]
    assert str(event.outbox_id) == evidence["outbox_id"]

    renewed = repository.renew_many(context, "fts", events, "lease-owner-a", 5)
    assert renewed.disposition == "RENEWED"
    assert renewed.renewed_count == 1
    assert renewed.delivered_count == 0
    assert renewed.ownership_lost_count == 0
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > event.lease_expires_at

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        before_stale = owner.execute(
            """
            SELECT state, lease_owner, lease_expires_at, attempt_count
            FROM milai.projection_delivery
            WHERE tenant_id = %s AND projection_name = 'fts' AND outbox_id = %s
            """,
            (settings.tenant_id, event.outbox_id),
        ).fetchone()
    stale = repository.renew_many(context, "fts", events, "lease-owner-b", 5)
    assert stale.disposition == "OWNERSHIP_LOST"
    assert stale.renewed_count == 0
    assert stale.delivered_count == 0
    assert stale.ownership_lost_count == 1
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        after_stale = owner.execute(
            """
            SELECT state, lease_owner, lease_expires_at, attempt_count
            FROM milai.projection_delivery
            WHERE tenant_id = %s AND projection_name = 'fts' AND outbox_id = %s
            """,
            (settings.tenant_id, event.outbox_id),
        ).fetchone()
    assert before_stale == after_stale
    assert after_stale[:2] == ("PROCESSING", "lease-owner-a")
    assert after_stale[3] == 1

    repository.complete_skipped_batch(
        context,
        "fts",
        events,
        "lease-owner-a",
        routing_version="dg15-routing-v1",
    )
    terminal = repository.renew_many(context, "fts", events, "lease-owner-a", 5)
    assert terminal.disposition == "TERMINAL"
    assert terminal.renewed_count == 0
    assert terminal.delivered_count == 1
    assert terminal.ownership_lost_count == 0


@pytest.mark.integration
def test_stale_owner_cannot_complete_or_advance_watermark_after_re_lease(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    _ingest(app.test_client(), f"lease-recovery-{uuid4()}")
    repository = ProjectionRepository(worker_database)
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    stale_events = repository.lease_many(context, "fts", "expired-owner", 1, 5, 1)
    assert len(stale_events) == 1
    time.sleep(1.1)
    current_events = repository.lease_many(context, "fts", "current-owner", 5, 5, 1)
    assert len(current_events) == 1
    assert current_events[0].outbox_id == stale_events[0].outbox_id
    assert current_events[0].attempt_count == 2

    stale = repository.renew_many(context, "fts", stale_events, "expired-owner", 5)
    assert stale.disposition == "OWNERSHIP_LOST"
    with pytest.raises(psycopg.Error, match="LEASE_LOST"):
        repository.complete_skipped_batch(
            context,
            "fts",
            stale_events,
            "expired-owner",
            routing_version="dg15-routing-v1",
        )
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        state, lease_owner, watermark = owner.execute(
            """
            SELECT delivery.state, delivery.lease_owner,
                   watermark.last_contiguous_outbox_sequence
            FROM milai.projection_delivery delivery
            JOIN milai.index_watermark watermark
              ON watermark.tenant_id = delivery.tenant_id
             AND watermark.projection_name = delivery.projection_name
            WHERE delivery.tenant_id = %s
              AND delivery.projection_name = 'fts'
              AND delivery.outbox_id = %s
            """,
            (settings.tenant_id, stale_events[0].outbox_id),
        ).fetchone()
    assert (state, lease_owner, watermark) == ("PROCESSING", "current-owner", 0)

    repository.complete_skipped_batch(
        context,
        "fts",
        current_events,
        "current-owner",
        routing_version="dg15-routing-v1",
    )
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        state, attempt_count, watermark = owner.execute(
            """
            SELECT delivery.state, delivery.attempt_count,
                   watermark.last_contiguous_outbox_sequence
            FROM milai.projection_delivery delivery
            JOIN milai.index_watermark watermark
              ON watermark.tenant_id = delivery.tenant_id
             AND watermark.projection_name = delivery.projection_name
            WHERE delivery.tenant_id = %s
              AND delivery.projection_name = 'fts'
              AND delivery.outbox_id = %s
            """,
            (settings.tenant_id, current_events[0].outbox_id),
        ).fetchone()
    assert (state, attempt_count, watermark) == (
        "DELIVERED",
        2,
        current_events[0].outbox_sequence,
    )


@pytest.mark.integration
def test_projection_lease_renew_complete_and_re_lease_are_serialized(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    _ingest(app.test_client(), f"lease-concurrency-{uuid4()}")
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    stale_repository = ProjectionRepository(worker_database)
    current_repository = ProjectionRepository(worker_database)
    stale_events = stale_repository.lease_many(context, "fts", "concurrent-stale-owner", 1, 5, 1)
    assert len(stale_events) == 1
    time.sleep(1.1)

    takeover_barrier = threading.Barrier(3)
    takeover: dict[str, object] = {}

    def renew_stale() -> None:
        try:
            takeover_barrier.wait()
            takeover["stale_renewal"] = stale_repository.renew_many(
                context,
                "fts",
                stale_events,
                "concurrent-stale-owner",
                5,
            )
        except Exception as exc:
            takeover["stale_error"] = exc

    def re_lease_current() -> None:
        try:
            takeover_barrier.wait()
            takeover["current_events"] = current_repository.lease_many(
                context,
                "fts",
                "concurrent-current-owner",
                5,
                5,
                1,
            )
        except Exception as exc:
            takeover["current_error"] = exc

    takeover_threads = (
        threading.Thread(target=renew_stale),
        threading.Thread(target=re_lease_current),
    )
    for thread in takeover_threads:
        thread.start()
    takeover_barrier.wait()
    for thread in takeover_threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert "stale_error" not in takeover
    assert "current_error" not in takeover
    stale_renewal = takeover["stale_renewal"]
    assert stale_renewal.disposition == "OWNERSHIP_LOST"  # type: ignore[union-attr]
    current_events = takeover["current_events"]
    assert isinstance(current_events, tuple)
    assert len(current_events) == 1
    assert current_events[0].attempt_count == 2

    finish_barrier = threading.Barrier(3)
    finish: dict[str, object] = {}

    def renew_current() -> None:
        try:
            finish_barrier.wait()
            finish["renewal"] = current_repository.renew_many(
                context,
                "fts",
                current_events,
                "concurrent-current-owner",
                5,
            )
        except Exception as exc:
            finish["renewal_error"] = exc

    def complete_current() -> None:
        try:
            finish_barrier.wait()
            finish["completion"] = current_repository.complete_skipped_batch(
                context,
                "fts",
                current_events,
                "concurrent-current-owner",
                routing_version="dg15-routing-v1",
            )
        except Exception as exc:
            finish["completion_error"] = exc

    finish_threads = (
        threading.Thread(target=renew_current),
        threading.Thread(target=complete_current),
    )
    for thread in finish_threads:
        thread.start()
    finish_barrier.wait()
    for thread in finish_threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert "renewal_error" not in finish
    assert "completion_error" not in finish
    assert finish["renewal"].disposition in {  # type: ignore[union-attr]
        "RENEWED",
        "TERMINAL",
    }

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        state, attempt_count, lease_owner, watermark = owner.execute(
            """
            SELECT delivery.state, delivery.attempt_count, delivery.lease_owner,
                   watermark.last_contiguous_outbox_sequence
            FROM milai.projection_delivery delivery
            JOIN milai.index_watermark watermark
              ON watermark.tenant_id = delivery.tenant_id
             AND watermark.projection_name = delivery.projection_name
            WHERE delivery.tenant_id = %s
              AND delivery.projection_name = 'fts'
              AND delivery.outbox_id = %s
            """,
            (settings.tenant_id, current_events[0].outbox_id),
        ).fetchone()
    assert (state, attempt_count, lease_owner, watermark) == (
        "DELIVERED",
        2,
        None,
        current_events[0].outbox_sequence,
    )


@pytest.mark.integration
def test_projection_lease_renewal_migration_permissions_and_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Historical migration roundtrips must not downgrade a shared database that
    # now contains immutable Note history. Use the existing disposable DB helper.
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_smoke_" + uuid4().hex[:20]
    _create_database(owner_url, database)
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", _database_url(owner_url, database))
        _projection_lease_migration_roundtrip()
    finally:
        assert _drop_database(owner_url, database)["status"] == "PASS"


def _projection_lease_migration_roundtrip() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    signature = "milai.renew_projection_event_batch(uuid,uuid,text,text,uuid[],integer)"
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        function, worker_allowed, api_allowed, steward_allowed = owner.execute(
            """
            SELECT to_regprocedure(%s),
                   has_function_privilege('milai_worker', %s, 'EXECUTE'),
                   has_function_privilege('milai_api', %s, 'EXECUTE'),
                   has_function_privilege('milai_steward', %s, 'EXECUTE')
            """,
            (signature, signature, signature, signature),
        ).fetchone()
    assert function is not None
    assert worker_allowed is True
    assert api_allowed is False
    assert steward_allowed is False

    try:
        command.downgrade(config, "0047_formation_hydration")
        with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
            absent = owner.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0]
        assert absent is None
    finally:
        command.upgrade(config, "head")
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        restored = owner.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0]
    assert restored is not None


@pytest.mark.integration
def test_projection_worker_renews_slow_evidence_batch_beyond_original_lease(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    original_settings, app, worker_database = worker_runtime
    settings = original_settings.model_copy(
        update={
            "worker_lease_seconds": 1,
            "worker_projection_batch_size": 32,
            "worker_event_limit": 32,
        }
    )
    client = app.test_client()
    ingested = tuple(
        _ingest(client, f"slow-evidence-batch-{index}-{uuid4()}") for index in range(32)
    )
    first_read_started = threading.Event()
    replacement_finished = threading.Event()
    replacement: dict[str, object] = {}

    class SlowFirstReadBlobStore(LocalContentAddressedBlobStore):
        def __init__(self) -> None:
            super().__init__(settings.blob_root)
            self._first_read = True

        def read(
            self,
            tenant_id: UUID,
            storage_uri: str,
            expected_hash: str,
            expected_length: int,
        ) -> bytes:
            if self._first_read:
                self._first_read = False
                first_read_started.set()
                if not replacement_finished.wait(timeout=10):
                    raise RuntimeError("replacement lease probe did not finish")
            return super().read(tenant_id, storage_uri, expected_hash, expected_length)

    def attempt_replacement_lease() -> None:
        try:
            if not first_read_started.wait(timeout=10):
                replacement["error"] = "SLOW_HANDLER_NOT_ENTERED"
                return
            time.sleep(1.1)
            events = ProjectionRepository(worker_database).lease_many(
                SessionContext(settings.tenant_id, settings.local_actor_id),
                "evidence",
                "slow-evidence-replacement-worker",
                1,
                5,
                32,
            )
            replacement["leased_count"] = len(events)
        except Exception as exc:
            replacement["error"] = exc
        finally:
            replacement_finished.set()

    replacement_thread = threading.Thread(target=attempt_replacement_lease)
    replacement_thread.start()

    worker = FoundationWorker(
        settings,
        worker_database,
        repository=ProjectionRepository(worker_database),
        blob_store=SlowFirstReadBlobStore(),
        embedding=None,
        worker_id="slow-evidence-renewal-worker",
    )
    assert worker.run_once() > 0
    replacement_thread.join(timeout=10)
    assert not replacement_thread.is_alive()
    assert replacement == {"leased_count": 0}
    counts = worker.metrics_snapshot()["counts"]
    assert counts["projection_lease_renewed_items"] >= 32
    assert counts.get("projection_ownership_lost_dispositions", 0) == 0

    outbox_ids = [item["outbox_id"] for item in ingested]
    evidence_ids = [item["evidence_id"] for item in ingested]
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        delivered, attempts, projected, watermark, maximum = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.projection_delivery
               WHERE tenant_id = %s AND projection_name = 'evidence'
                 AND outbox_id = ANY(%s::uuid[]) AND state = 'DELIVERED'),
              (SELECT max(attempt_count) FROM milai.projection_delivery
               WHERE tenant_id = %s AND projection_name = 'evidence'
                 AND outbox_id = ANY(%s::uuid[])),
              (SELECT count(*) FROM milai.evidence_search_document
               WHERE tenant_id = %s AND evidence_id = ANY(%s::uuid[])),
              (SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
               WHERE tenant_id = %s AND projection_name = 'evidence'),
              (SELECT max(outbox_sequence) FROM milai.outbox_event
               WHERE tenant_id = %s AND outbox_id = ANY(%s::uuid[]))
            """,
            (
                settings.tenant_id,
                outbox_ids,
                settings.tenant_id,
                outbox_ids,
                settings.tenant_id,
                evidence_ids,
                settings.tenant_id,
                settings.tenant_id,
                outbox_ids,
            ),
        ).fetchone()
    assert (delivered, attempts, projected) == (32, 1, 32)
    assert watermark == maximum


@pytest.mark.integration
def test_dg15_evidence_projection_is_queryable_noncanonical_and_revocation_safe(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    token = f"evidenceprojection{uuid4().hex}"
    capture = client.post(
        "/v1/evidence",
        headers=_headers(f"evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"lme://case/session-2/turn-7/{token}",
            "subject_id": "dg15-evidence-only-subject",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": f"Previously the user recorded the unique value {token}.",
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True, "project_ids": ["milai"]},
            "retention_state": "READABLE",
        },
    )
    assert capture.status_code == 201

    waiting = client.post(
        "/v1/system/projection-readiness",
        headers=_headers(),
        json={
            "target_outbox_id": capture.json["outbox_id"],
            "required_projections": ["evidence"],
            "expected_versions": {"evidence": "evidence-search-v1"},
            "timeout_ms": 0,
        },
    )
    assert waiting.status_code == 408
    assert waiting.json["status"] == "PROJECTION_READINESS_TIMEOUT"
    assert waiting.json["projection_work_started"] is False

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="dg15-evidence-projection-worker",
    )
    assert worker.run_once() > 0

    ready = client.post(
        "/v1/system/projection-readiness",
        headers=_headers(),
        json={
            "target_outbox_id": capture.json["outbox_id"],
            "required_projections": ["evidence"],
            "expected_versions": {"evidence": "evidence-search-v1"},
            "timeout_ms": 0,
        },
    )
    assert ready.status_code == 200
    assert ready.json["status"] == "READY"

    resolved = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"What did I previously record about {token}?",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "budget": {"max_results": 3, "max_context_tokens": 512},
        },
    )
    assert resolved.status_code == 200
    assert resolved.json["status"] == "HIT", resolved.json
    assert resolved.json["items"][0]["kind"] == "EVIDENCE_OBSERVATION"
    assert resolved.json["items"][0]["evidence_id"] == capture.json["evidence_id"]
    assert resolved.json["items"][0]["canonical"] is False
    assert resolved.json["context_candidate_kinds"] == ["EVIDENCE_OBSERVATION"]
    assert resolved.json["memory_context"]["schema_version"] == "memory-context-v0.1"
    assert resolved.json["memory_context"]["authority_class"] == "EVIDENCE_ONLY"
    assert token in resolved.json["memory_context"]["text"]
    assert capture.json["evidence_id"] not in resolved.json["memory_context"]["text"]
    assert "[E1 EVIDENCE WINDOW" in resolved.json["memory_context"]["text"]
    assert len(resolved.json["memory_context"]["semantic_context_digest"]) == 64
    assert len(resolved.json["memory_context"]["reader_context_digest"]) == 64
    assert resolved.json["context_receipt"]["schema_version"] == ("context-receipt-v0.2")
    assert resolved.json["context_receipt"]["authority_class"] == "EVIDENCE_ONLY"
    assert resolved.json["context_receipt"]["source_evidence_ids"] == [capture.json["evidence_id"]]
    assert resolved.json["context_receipt"]["receipt_mapping"][0]["alias"] == "E1"
    assert resolved.json["context_receipt"]["receipt_mapping"][0]["evidence_ids"] == [
        capture.json["evidence_id"]
    ]
    assert resolved.json["context_receipt"]["canonical_mutation"] is False

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        canonical_claims, evidence_documents = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.claim WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.evidence_search_document
               WHERE tenant_id = %s AND evidence_id = %s)
            """,
            (settings.tenant_id, settings.tenant_id, capture.json["evidence_id"]),
        ).fetchone()
    assert canonical_claims == 0
    assert evidence_documents == 1

    revoke = client.post(
        f"/v1/evidence/{capture.json['evidence_id']}/revoke",
        headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202

    stale_candidate_rejected = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"What did I previously record about {token}?",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "budget": {"max_results": 3, "max_context_tokens": 512},
        },
    )
    assert stale_candidate_rejected.status_code == 200
    assert stale_candidate_rejected.json["status"] != "HIT"
    assert stale_candidate_rejected.json["items"] == []

    assert worker.run_once() > 0
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        remaining = owner.execute(
            """
            SELECT count(*) FROM milai.evidence_search_document
            WHERE tenant_id = %s AND evidence_id = %s
            """,
            (settings.tenant_id, capture.json["evidence_id"]),
        ).fetchone()[0]
    assert remaining == 0


@pytest.mark.integration
def test_dg15_namespace_cleanup_is_one_submission_with_staged_per_item_receipts(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    project_id = f"dg15-cleanup-{uuid4().hex}"
    other_project = f"dg15-other-{uuid4().hex}"
    captured: list[dict[str, str]] = []
    for ordinal, project in enumerate((project_id, project_id, other_project)):
        response = client.post(
            "/v1/evidence",
            headers=_headers(f"cleanup-evidence-{uuid4()}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"lme://cleanup/session-1/turn-{ordinal}",
                "subject_id": "dg15-cleanup-subject",
                "observed_at": "2026-08-15T10:00:00+08:00",
                "content": f"cleanup token {project} ordinal {ordinal}",
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True, "project_ids": [project]},
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201
        captured.append(dict(response.json))

    operation_id = f"namespace-cleanup-{uuid4()}"
    wrong_profile = client.post(
        "/v1/namespace-cleanups",
        headers={**_reader_headers(), "Idempotency-Key": f"wrong-{uuid4()}"},
        json={
            "project_id": project_id,
            "reason_code": "USER_REQUEST",
            "confirmation": "CLEANUP_NAMESPACE",
        },
    )
    assert wrong_profile.status_code == 403
    assert wrong_profile.json["error"]["code"] == "CAPABILITY_REQUIRED"

    submitted = client.post(
        "/v1/namespace-cleanups",
        headers=_operator_headers(operation_id),
        json={
            "project_id": project_id,
            "reason_code": "USER_REQUEST",
            "confirmation": "CLEANUP_NAMESPACE",
        },
    )
    assert submitted.status_code == 202
    assert submitted.json["status"] == "ACCEPTED"
    assert submitted.json["cleanup_accepted"] is True
    assert submitted.json["evidence_count"] == 2
    assert submitted.json["accepted_count"] == 2
    assert submitted.json["failed_count"] == 0
    assert submitted.json["target_purge_outbox_id"] is not None

    replay = client.post(
        "/v1/namespace-cleanups",
        headers=_operator_headers(operation_id),
        json={
            "project_id": project_id,
            "reason_code": "USER_REQUEST",
            "confirmation": "CLEANUP_NAMESPACE",
        },
    )
    assert replay.status_code == 200
    assert replay.json["replayed"] is True
    assert replay.json["cleanup_job_id"] == submitted.json["cleanup_job_id"]

    before_projection = client.get(
        f"/v1/namespace-cleanups/{submitted.json['cleanup_job_id']}?offset=0&limit=100",
        headers=_operator_headers(),
    )
    assert before_projection.status_code == 200
    assert before_projection.json["canonical_blocked_count"] == 2
    assert before_projection.json["projection_purged_count"] == 0
    assert before_projection.json["primary_bytes_terminal_count"] == 0
    assert before_projection.json["primary_bytes_erased_count"] == 0
    assert before_projection.json["primary_bytes_retained_shared_count"] == 0
    assert before_projection.json["primary_bytes_retention_blocked_count"] == 0
    assert len(before_projection.json["item_outcomes"]) == 2
    assert {item["evidence_id"] for item in before_projection.json["item_outcomes"]} == {
        captured[0]["evidence_id"],
        captured[1]["evidence_id"],
    }
    assert all(
        item["outcome"] == "TX05_APPLIED" for item in before_projection.json["item_outcomes"]
    )

    for evidence in captured[:2]:
        metadata = client.get(f"/v1/evidence/{evidence['evidence_id']}", headers=_headers())
        assert metadata.status_code == 200
        assert metadata.json["content"] is None
        assert metadata.json["revoked_at"] is not None
    other = client.get(f"/v1/evidence/{captured[2]['evidence_id']}", headers=_headers())
    assert other.status_code == 200
    assert other.json["content"] is not None
    assert other.json["revoked_at"] is None

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="dg15-namespace-cleanup-worker",
    )
    assert worker.run_once() > 0
    worker_metrics = worker.metrics_snapshot()
    assert worker_metrics["counts"]["search_purge_projection_batch_ms"] == 2
    assert worker_metrics["counts"]["search_purge_projection_batch_items"] == 4
    after_projection = client.get(
        f"/v1/namespace-cleanups/{submitted.json['cleanup_job_id']}?offset=0&limit=100",
        headers=_operator_headers(),
    )
    assert after_projection.status_code == 200
    assert after_projection.json["projection_purged_count"] == 2
    assert after_projection.json["primary_bytes_terminal_count"] == 2
    assert after_projection.json["primary_bytes_erased_count"] == 2
    assert after_projection.json["primary_bytes_retained_shared_count"] == 0
    assert after_projection.json["primary_bytes_retention_blocked_count"] == 0
    assert after_projection.json["backup_expiry_completed_count"] == 0
    assert all(
        item["derived_purge_status"] == "COMPLETED"
        and item["primary_bytes_status"] == "ERASED"
        and item["backup_expiry_status"] == "PENDING"
        for item in after_projection.json["item_outcomes"]
    )


@pytest.mark.integration
def test_namespace_cleanup_shared_blob_is_terminal_then_last_reference_erases(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    cleaned_project = f"shared-cleanup-{uuid4().hex}"
    live_project = f"shared-live-{uuid4().hex}"
    token = f"shared-cas-{uuid4().hex}"

    evidence: list[dict[str, str]] = []
    for project in (cleaned_project, live_project):
        response = client.post(
            "/v1/evidence",
            headers=_headers(f"shared-evidence-{uuid4()}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": f"shared-cas://{project}",
                "subject_id": "shared-cas-cleanup-subject",
                "observed_at": "2026-08-15T10:00:00+08:00",
                "content": token,
                "media_type": "text/plain",
                "permission_snapshot": {"readable": True, "project_ids": [project]},
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201
        evidence.append(dict(response.json))
    assert evidence[0]["blob_id"] == evidence[1]["blob_id"]

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="shared-cas-cleanup-worker",
    )
    assert worker.run_once() > 0

    submitted = client.post(
        "/v1/namespace-cleanups",
        headers=_operator_headers(f"shared-cleanup-{uuid4()}"),
        json={
            "project_id": cleaned_project,
            "reason_code": "USER_REQUEST",
            "confirmation": "CLEANUP_NAMESPACE",
        },
    )
    assert submitted.status_code == 202
    assert submitted.json["accepted_count"] == 1
    assert worker.run_once() > 0

    cleanup_url = f"/v1/namespace-cleanups/{submitted.json['cleanup_job_id']}?offset=0&limit=100"
    retained = client.get(cleanup_url, headers=_operator_headers())
    assert retained.status_code == 200
    assert retained.json["primary_bytes_terminal_count"] == 1
    assert retained.json["primary_bytes_erased_count"] == 0
    assert retained.json["primary_bytes_retained_shared_count"] == 1
    assert retained.json["primary_bytes_retention_blocked_count"] == 0
    assert (
        retained.json["primary_bytes_erased_count"]
        + retained.json["primary_bytes_retained_shared_count"]
        + retained.json["primary_bytes_retention_blocked_count"]
        == retained.json["accepted_count"]
    )

    cleaned = client.get(f"/v1/evidence/{evidence[0]['evidence_id']}", headers=_headers())
    live = client.get(f"/v1/evidence/{evidence[1]['evidence_id']}", headers=_headers())
    assert cleaned.status_code == live.status_code == 200
    assert cleaned.json["content"] is None
    assert live.json["content"] == token
    not_retrievable = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": token,
            "requested_scope": {"project_ids": [cleaned_project]},
            "required_authority": "INFORMATIONAL",
            "budget": {"max_results": 3, "max_context_tokens": 512},
        },
    )
    assert not_retrievable.status_code == 200
    assert not_retrievable.json["status"] != "HIT"
    assert not_retrievable.json["items"] == []

    final_revoke = client.post(
        f"/v1/evidence/{evidence[1]['evidence_id']}/revoke",
        headers=_headers(f"shared-final-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert final_revoke.status_code == 202
    assert final_revoke.json["primary_bytes_status"] == "PENDING"
    assert worker.run_once() > 0

    erased = client.get(cleanup_url, headers=_operator_headers())
    assert erased.status_code == 200
    assert erased.json["primary_bytes_terminal_count"] == 1
    assert erased.json["primary_bytes_erased_count"] == 1
    assert erased.json["primary_bytes_retained_shared_count"] == 0
    assert erased.json["primary_bytes_retention_blocked_count"] == 0
    blob_path = (
        settings.blob_root
        / str(settings.tenant_id)
        / live.json["content_hash"][:2]
        / live.json["content_hash"]
    )
    assert not blob_path.exists()


@pytest.mark.integration
def test_coordinated_legacy_rebuild_with_revoked_history(
    worker_runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    from milai.adapters import http_models
    from milai.operations.cli import _rebuild_projection

    if os.environ.get("BGE_HTTP_LIVE_TEST") != "1":
        monkeypatch.setattr(http_models, "_post_json", lambda endpoint, payload, timeout: {
            "model": "bge-m3", "data": [
                {"index": i, "embedding": [1.0, *([0.0] * 1023)]}
                for i in range(len(payload["input"]))
            ],
        })
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    live = _ingest(client, "synthetic legacy live observation")
    revoked = _ingest(client, "synthetic legacy revoked observation")
    live_claim = _create_claim(client, live["evidence_id"])
    revoked_claim = _create_claim(client, revoked["evidence_id"])
    old = _worker(settings, worker_database, embedding=DeterministicHashEmbedding(),
                  worker_id="legacy-16")
    old.run_once()
    assert client.post(
        f"/v1/evidence/{revoked['evidence_id']}/revoke", headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    ).status_code == 202
    old.run_once()
    for projection in ("fts", "vector"):
        _rebuild_projection(settings.tenant_id, settings.local_actor_id, projection,
                            "REBUILD_DERIVED_PROJECTION", settings.steward_database_dsn)
    new = HTTPEmbedding("http://127.0.0.1:7861/v1/embeddings", model_id="bge-m3",
                        revision="synthetic-coordinated-v1", source_dimensions=1024,
                        projection_dimensions=128)
    worker = _worker(
        settings.model_copy(update={"worker_event_limit": 1, "worker_projection_batch_size": 1}),
        worker_database, embedding=new, worker_id="coordinated-recovery",
    )
    repository = RetrievalRepository(app.extensions["milai.database"])
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    for _ in range(100):
        processed = worker.run_once()
        blocked = client.get(f"/v1/evidence/{revoked['evidence_id']}", headers=_headers())
        assert blocked.status_code == 200 and blocked.json["content"] is None
        now = datetime.now(UTC)
        gated = RetrievalRepository(app.extensions["milai.database"]).gate_and_hydrate(
            context, [UUID(revoked_claim["claim_version_id"])], "INFORMATIONAL",
            {"project_ids": ["milai"]}, now, "ACTIVE", ["VERIFIED", "PROVISIONAL"],
            "CURRENT", 0.0, now,
        )
        assert gated.claims == [] and not gated.outcomes[0]["accepted"]
        state = repository.projection_state(context)
        assert not state.fts_dead_letter and not state.vector_dead_letter
        assert state.fts_watermark == state.vector_watermark
        if processed == 0:
            break
    else:
        pytest.fail("coordinated replay did not finish")
    assert state.fts_watermark == state.vector_watermark == state.canonical_snapshot_outbox_sequence
    results = repository.search_vector(
        context, new.embed("synthetic live observation"), {"project_ids": ["milai"]},
        datetime.now(UTC), 3, model_id=new.identity.model_id, projection_version=new.identity.key,
    )
    assert [item.claim_version_id for item in results] == [UUID(live_claim["claim_version_id"])]
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        assert owner.execute("SELECT count(*) FROM milai.claim_version WHERE tenant_id=%s",
                             (settings.tenant_id,)).fetchone()[0] == 2
        assert owner.execute(
            "SELECT count(*) FROM milai.search_document_fragment WHERE tenant_id=%s "
            "AND claim_version_id=%s", (settings.tenant_id, revoked_claim["claim_version_id"]),
        ).fetchone()[0] == 0
        assert owner.execute(
            "SELECT count(*) FROM milai.search_embedding_window_128 WHERE tenant_id=%s "
            "AND claim_version_id=%s", (settings.tenant_id, revoked_claim["claim_version_id"]),
        ).fetchone()[0] == 0


@pytest.mark.integration
def test_http_embedding_rebuild_isolates_identity_and_preserves_canonical(
    worker_runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    from milai.adapters import http_models

    if os.environ.get("BGE_HTTP_LIVE_TEST") != "1":
        monkeypatch.setattr(http_models, "_post_json", lambda endpoint, payload, timeout: {
            "model": "bge-m3", "data": [
                {"index": i, "embedding": [1.0, *([0.0] * 1023)]}
                for i in range(len(payload["input"]))
            ],
        })
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, "合成测试: 人工智能是计算机科学的一个分支。")
    claim = _create_claim(client, evidence["evidence_id"],
                          memory_text="合成测试: 人工智能是计算机科学的一个分支。")
    old = _Synthetic128Embedding()
    assert _worker(settings, worker_database, embedding=old, worker_id="old-model").run_once() > 0
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    repository = RetrievalRepository(worker_database)
    new = HTTPEmbedding("http://127.0.0.1:7861/v1/embeddings", model_id="bge-m3",
                        revision="synthetic-integration-v1", source_dimensions=1024,
                        projection_dimensions=128)
    query_vector = new.embed("什么是人工智能?")

    def search(identity: ProjectionIdentity, scope: str = "milai"):
        return repository.search_vector(
            context, query_vector, {"project_ids": [scope]}, datetime.now(UTC), 3,
            model_id=identity.model_id, projection_version=identity.key,
        )

    assert search(new.identity) == []  # Never read old vectors as BGE vectors.
    with psycopg.connect(settings.steward_database_dsn) as steward:
        steward.execute("SELECT set_config('milai.tenant_id', %s, true)", (str(context.tenant_id),))
        steward.execute("SELECT set_config('milai.actor_id', %s, true)", (str(context.actor_id),))
        steward.execute(
            "SELECT milai.rebuild_search_projection(%s,%s,'vector','REBUILD_DERIVED_PROJECTION')",
            (context.tenant_id, context.actor_id),
        )
    worker = _worker(settings, worker_database, embedding=new, worker_id="http-model")
    assert worker.run_once() > 0
    assert search(new.identity)[0].claim_version_id == UUID(claim["claim_version_id"])
    assert search(new.identity, "other-project") == []
    assert repository.search_vector(
        SessionContext(uuid4(), context.actor_id), query_vector, {"project_ids": ["milai"]},
        datetime.now(UTC), 3, model_id=new.identity.model_id, projection_version=new.identity.key,
    ) == []
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        canonical, model_count = owner.execute(
            "SELECT (SELECT count(*) FROM milai.claim_version WHERE tenant_id=%s),"
            "(SELECT count(DISTINCT model_id) FROM milai.search_embedding_window_128 "
            "WHERE tenant_id=%s)", (context.tenant_id, context.tenant_id),
        ).fetchone()
    assert canonical == 1 and model_count == 2  # Old 128d index retained for rollback.
    revoked = client.post(
        f"/v1/evidence/{evidence['evidence_id']}/revoke", headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoked.status_code == 202
    assert worker.run_once() > 0
    assert search(new.identity) == []


@pytest.mark.integration
def test_dg11_worker_projects_turn_windows_to_128d_and_resolves_parent_claim(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, f"dg11-window-{uuid4()}")
    claim = _create_claim(
        client,
        evidence["evidence_id"],
        memory_text=(
            "user: I prefer blue trail shoes for wet weather.\n"
            "assistant: I recommend the Alpine model for that preference."
        ),
    )
    embedding = _Synthetic128Embedding()
    worker = _worker(
        settings,
        worker_database,
        embedding=embedding,
        worker_id="dg11-window-worker",
    )

    assert worker.run_once() > 0
    worker_metrics = worker.metrics_snapshot()
    assert embedding.batch_calls >= 1
    assert embedding.scalar_calls == 0
    assert worker_metrics["counts"]["embedding_logical_items"] >= 1
    assert worker_metrics["counts"]["embedding_inference_batches"] == embedding.batch_calls
    assert worker_metrics["counts"]["fragment_derivation_ms"] >= 2
    assert worker_metrics["durations_ms"]["fragment_derivation_ms"] >= 0
    assert worker_metrics["counts"]["projection_write_ms"] >= 2
    repository = RetrievalRepository(worker_database)
    context = SessionContext(settings.tenant_id, settings.local_actor_id)
    fts = repository.search_fts(
        context,
        "blue trail shoes",
        {"project_ids": ["milai"]},
        datetime.now(UTC),
        3,
    )
    vector = repository.search_vector(
        context,
        embedding.embed("Which shoes do I prefer?"),
        {"project_ids": ["milai"]},
        datetime.now(UTC),
        3,
        model_id=embedding.identity.model_id,
        projection_version=embedding.identity.key,
    )
    wrong_scope = repository.search_vector(
        context,
        embedding.embed("Which shoes do I prefer?"),
        {"project_ids": ["other-project"]},
        datetime.now(UTC),
        3,
        model_id=embedding.identity.model_id,
        projection_version=embedding.identity.key,
    )
    cross_tenant = repository.search_vector(
        SessionContext(uuid4(), settings.local_actor_id),
        embedding.embed("Which shoes do I prefer?"),
        {"project_ids": ["milai"]},
        datetime.now(UTC),
        3,
        model_id=embedding.identity.model_id,
        projection_version=embedding.identity.key,
    )

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        fragment_count = owner.execute(
            """
            SELECT count(*) FROM milai.search_document_fragment
            WHERE tenant_id = %s AND claim_version_id = %s
            """,
            (settings.tenant_id, claim["claim_version_id"]),
        ).fetchone()[0]
        embedding_count = owner.execute(
            """
            SELECT count(*) FROM milai.search_embedding_window_128
            WHERE tenant_id = %s AND claim_version_id = %s
            """,
            (settings.tenant_id, claim["claim_version_id"]),
        ).fetchone()[0]
    assert fragment_count == 3
    assert embedding_count == 3
    assert fts[0].claim_version_id == UUID(claim["claim_version_id"])
    assert vector[0].claim_version_id == UUID(claim["claim_version_id"])
    assert wrong_scope == []
    assert cross_tenant == []

    revoke = client.post(
        f"/v1/evidence/{evidence['evidence_id']}/revoke",
        headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202
    assert worker.run_once() > 0
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        remaining = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.search_document_fragment
               WHERE tenant_id = %s AND claim_version_id = %s),
              (SELECT count(*) FROM milai.search_embedding_window_128
               WHERE tenant_id = %s AND claim_version_id = %s)
            """,
            (
                settings.tenant_id,
                claim["claim_version_id"],
                settings.tenant_id,
                claim["claim_version_id"],
            ),
        ).fetchone()
    assert remaining == (0, 0)


@pytest.mark.integration
def test_dead_letter_blocks_watermark_until_explicit_retry(tmp_path: Path) -> None:
    command.upgrade(Config("alembic.ini"), "head")
    tenant_id = uuid4()
    settings = _settings(tmp_path, tenant_id, max_attempts=1).model_copy(
        update={"worker_projection_batch_size": 1}
    )
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(settings, dsn=_url("MILAI_TEST_WORKER_DATABASE_URL"))
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    try:
        client = app.test_client()
        evidence = _ingest(client, f"dead-letter-{uuid4()}")
        claim = _create_claim(client, evidence["evidence_id"])
        later = client.post(
            "/v1/proposals",
            headers=_headers(f"no-change-{uuid4()}"),
            json={
                "target_claim_id": claim["claim_id"],
                "operation": "NO_CHANGE",
                "expected_version_id": claim["claim_version_id"],
                "proposed_patch": {},
                "scope_predicate": {"project_ids": ["milai"]},
                "requested_authority": "ACTION_SAFE",
                "derivation_policy_id": "worker-test-v1",
                "derivation_snapshot": {},
            },
        )
        assert later.status_code == 201

        broken = _worker(
            settings,
            worker_database,
            embedding=None,
            worker_id="missing-embedding-worker",
        )
        broken.run_once()
        owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
        with psycopg.connect(owner_url) as owner:
            dead_id, dead_sequence = owner.execute(
                """
                SELECT outbox_id, outbox_sequence
                FROM milai.projection_delivery
                WHERE tenant_id = %s AND projection_name = 'vector'
                  AND state = 'DEAD_LETTER'
                """,
                (tenant_id,),
            ).fetchone()
            watermark = owner.execute(
                """
                SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
                WHERE tenant_id = %s AND projection_name = 'vector'
                """,
                (tenant_id,),
            ).fetchone()[0]
            later_pending = owner.execute(
                """
                SELECT count(*) FROM milai.projection_delivery
                WHERE tenant_id = %s AND projection_name = 'vector'
                  AND outbox_sequence > %s AND state = 'PENDING'
                """,
                (tenant_id, dead_sequence),
            ).fetchone()[0]
        assert watermark < dead_sequence
        assert later_pending > 0

        with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
            steward.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
            steward.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
            steward.execute(
                "SELECT milai.retry_dead_letter(%s, %s, 'vector', %s)",
                (tenant_id, ACTOR_ID, dead_id),
            ).fetchone()

        recovered = _worker(
            settings,
            worker_database,
            embedding=DeterministicHashEmbedding(),
            worker_id="recovery-worker",
        )
        recovered.run_once()
        with psycopg.connect(owner_url) as owner:
            remaining = owner.execute(
                """
                SELECT count(*) FROM milai.projection_delivery
                WHERE tenant_id = %s AND projection_name = 'vector'
                  AND state <> 'DELIVERED'
                """,
                (tenant_id,),
            ).fetchone()[0]
            watermark, max_sequence = owner.execute(
                """
                SELECT
                  (SELECT last_contiguous_outbox_sequence
                   FROM milai.index_watermark
                   WHERE tenant_id = %s AND projection_name = 'vector'),
                  (SELECT max(outbox_sequence) FROM milai.outbox_event
                   WHERE tenant_id = %s)
                """,
                (tenant_id, tenant_id),
            ).fetchone()
        assert remaining == 0
        assert watermark == max_sequence
    finally:
        api_database.close()
        steward_database.close()
        worker_database.close()


@pytest.mark.integration
def test_purge_worker_erases_blob_and_derived_claim_projection(worker_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, f"purge-worker-{uuid4()}")
    claim = _create_claim(client, evidence["evidence_id"])
    revoke = client.post(
        f"/v1/evidence/{evidence['evidence_id']}/revoke",
        headers=_headers(f"revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="purge-success-worker",
    )
    worker.run_once()

    deletion = client.get(
        f"/v1/deletion-requests/{revoke.json['deletion_request_id']}",
        headers=_headers(),
    )
    assert deletion.status_code == 200
    assert deletion.json["derived_purge_status"] == "COMPLETED"
    assert deletion.json["primary_bytes_status"] == "ERASED"
    assert deletion.json["primary_erasure_disposition"] == ("ERASED_AND_VERIFIED_ABSENT")
    assert len(deletion.json["primary_erasure_proof_hash"]) == 64
    assert deletion.json["primary_erasure_verified_at"] is not None
    blob_path = (
        settings.blob_root
        / str(settings.tenant_id)
        / evidence["content_hash"][:2]
        / evidence["content_hash"]
    )
    assert not blob_path.exists()

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        document_count, embedding_count, block_count = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.search_document
               WHERE tenant_id = %s AND claim_version_id = %s),
              (SELECT count(*) FROM milai.search_embedding
               WHERE tenant_id = %s AND claim_version_id = %s),
              (SELECT count(*) FROM milai.grounding_block
               WHERE tenant_id = %s AND claim_version_id = %s AND active)
            """,
            (
                settings.tenant_id,
                claim["claim_version_id"],
                settings.tenant_id,
                claim["claim_version_id"],
                settings.tenant_id,
                claim["claim_version_id"],
            ),
        ).fetchone()
    assert (document_count, embedding_count, block_count) == (0, 0, 1)


@pytest.mark.integration
def test_forged_erasure_proof_dead_letters_then_verified_absence_recovers(
    tmp_path: Path,
) -> None:
    command.upgrade(Config("alembic.ini"), "head")
    tenant_id = uuid4()
    settings = _settings(tmp_path, tenant_id, max_attempts=1)
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(settings, dsn=_url("MILAI_TEST_WORKER_DATABASE_URL"))
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    try:
        client = app.test_client()
        evidence = _ingest(client, f"purge-retry-{uuid4()}")
        claim = _create_claim(client, evidence["evidence_id"])
        revoke = client.post(
            f"/v1/evidence/{evidence['evidence_id']}/revoke",
            headers=_headers(f"revoke-{uuid4()}"),
            json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
        )
        assert revoke.status_code == 202

        class ForgedProofStore(LocalContentAddressedBlobStore):
            def erase(self, tenant: UUID, storage_uri: str, expected_hash: str) -> ErasureProof:
                authentic = super().erase(tenant, storage_uri, expected_hash)
                return ErasureProof(
                    disposition=authentic.disposition,
                    content_hash=authentic.content_hash,
                    storage_uri=authentic.storage_uri,
                    proof_hash="0" * 64,
                )

        broken = FoundationWorker(
            settings,
            worker_database,
            repository=ProjectionRepository(worker_database),
            blob_store=ForgedProofStore(settings.blob_root),
            embedding=DeterministicHashEmbedding(),
            worker_id="purge-forged-proof-worker",
        )
        broken.run_once()
        with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
            (
                dead_id,
                delivery_state,
                derived_status,
                primary_status,
                error_code,
                proof_hash,
            ) = owner.execute(
                """
                SELECT delivery.outbox_id, delivery.state,
                       deletion.derived_purge_status,
                       deletion.primary_bytes_status,
                       deletion.last_error_code,
                       deletion.primary_erasure_proof_hash
                FROM milai.projection_delivery delivery
                JOIN milai.outbox_event event
                  ON event.tenant_id = delivery.tenant_id
                 AND event.outbox_id = delivery.outbox_id
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = event.tenant_id
                 AND deletion.deletion_request_id = event.aggregate_id
                WHERE delivery.tenant_id = %s
                  AND delivery.projection_name = 'purge'
                  AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                """,
                (tenant_id,),
            ).fetchone()
        assert (delivery_state, derived_status, primary_status, error_code) == (
            "DEAD_LETTER",
            "DEAD_LETTER",
            "ERROR",
            "INVALID_ERASURE_PROOF",
        )
        assert proof_hash is None
        erased_path = (
            settings.blob_root
            / str(tenant_id)
            / evidence["content_hash"][:2]
            / evidence["content_hash"]
        )
        assert not erased_path.exists()

        with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
            steward.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
            steward.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
            steward.execute(
                "SELECT milai.retry_dead_letter(%s, %s, 'purge', %s)",
                (tenant_id, ACTOR_ID, dead_id),
            ).fetchone()

        recovered = _worker(
            settings,
            worker_database,
            embedding=DeterministicHashEmbedding(),
            worker_id="purge-recovery-worker",
        )
        recovered.run_once()
        deletion = client.get(
            f"/v1/deletion-requests/{revoke.json['deletion_request_id']}",
            headers=_headers(),
        )
        assert deletion.status_code == 200
        assert deletion.json["derived_purge_status"] == "COMPLETED"
        assert deletion.json["primary_bytes_status"] == "ERASED"
        assert deletion.json["primary_erasure_disposition"] == "VERIFIED_ALREADY_ABSENT"
        assert len(deletion.json["primary_erasure_proof_hash"]) == 64
        with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
            delivery_state, document_count, embedding_count = owner.execute(
                """
                SELECT
                  (SELECT state FROM milai.projection_delivery
                   WHERE tenant_id = %s AND projection_name = 'purge'
                     AND outbox_id = %s),
                  (SELECT count(*) FROM milai.search_document
                   WHERE tenant_id = %s AND claim_version_id = %s),
                  (SELECT count(*) FROM milai.search_embedding
                   WHERE tenant_id = %s AND claim_version_id = %s)
                """,
                (
                    tenant_id,
                    dead_id,
                    tenant_id,
                    claim["claim_version_id"],
                    tenant_id,
                    claim["claim_version_id"],
                ),
            ).fetchone()
        assert (delivery_state, document_count, embedding_count) == ("DELIVERED", 0, 0)
    finally:
        api_database.close()
        steward_database.close()
        worker_database.close()


@pytest.mark.integration
def test_search_projection_rebuild_replays_outbox_without_canonical_mutation(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    evidence = _ingest(client, f"projection-rebuild-{uuid4()}")
    claim = _create_claim(client, evidence["evidence_id"])
    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="projection-before-rebuild",
    )
    worker.run_once()

    with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
        steward.execute(
            "SELECT set_config('milai.tenant_id', %s, false)",
            (str(settings.tenant_id),),
        )
        steward.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        for projection in ("fts", "vector"):
            result = steward.execute(
                """
                SELECT milai.rebuild_search_projection(
                  %s, %s, %s, 'REBUILD_DERIVED_PROJECTION'
                )
                """,
                (settings.tenant_id, ACTOR_ID, projection),
            ).fetchone()[0]
            assert result["watermark"] == 0

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        before = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.search_document
               WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.search_embedding
               WHERE tenant_id = %s),
              (SELECT count(*) FROM milai.claim_version
               WHERE tenant_id = %s AND claim_version_id = %s)
            """,
            (
                settings.tenant_id,
                settings.tenant_id,
                settings.tenant_id,
                claim["claim_version_id"],
            ),
        ).fetchone()
    assert before == (0, 0, 1)

    replay = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id="projection-rebuild-replay",
    )
    assert replay.run_once() > 0
    with psycopg.connect(owner_url) as owner:
        documents, embeddings, fts_watermark, vector_watermark, max_sequence = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.search_document
               WHERE tenant_id = %s AND claim_version_id = %s),
              (SELECT count(*) FROM milai.search_embedding
               WHERE tenant_id = %s AND claim_version_id = %s),
              (SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
               WHERE tenant_id = %s AND projection_name = 'fts'),
              (SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
               WHERE tenant_id = %s AND projection_name = 'vector'),
              (SELECT max(outbox_sequence) FROM milai.outbox_event
               WHERE tenant_id = %s)
            """,
            (
                settings.tenant_id,
                claim["claim_version_id"],
                settings.tenant_id,
                claim["claim_version_id"],
                settings.tenant_id,
                settings.tenant_id,
                settings.tenant_id,
            ),
        ).fetchone()
    assert (documents, embeddings) == (1, 1)
    assert fts_watermark == vector_watermark == max_sequence


@pytest.mark.integration
def test_dg17_a1_evidence_search_ranks_matching_turns_without_session_backfill(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    token = f"a1turn{uuid4().hex}"
    suffix = uuid4().hex
    source_refs = {
        "primary": f"dg17-a1://{suffix}/session-a/turn-0",
        "decoy-1": f"dg17-a1://{suffix}/session-a/turn-1",
        "decoy-2": f"dg17-a1://{suffix}/session-a/turn-2",
        "secondary": f"dg17-a1://{suffix}/session-b/turn-0",
    }
    payloads = (
        (
            source_refs["primary"],
            f"dg17-a1-session-a-{suffix}",
            f"user: {token} {token} {token} is the primary matching turn.",
        ),
        (
            source_refs["decoy-1"],
            f"dg17-a1-session-a-{suffix}",
            "user: unrelated session backfill must not consume a candidate slot.",
        ),
        (
            source_refs["decoy-2"],
            f"dg17-a1-session-a-{suffix}",
            "assistant: another unrelated turn in the high-score session.",
        ),
        (
            source_refs["secondary"],
            f"dg17-a1-session-b-{suffix}",
            f"user: {token} is also present in this independent turn.",
        ),
    )
    for ordinal, (source_ref, subject_id, content) in enumerate(payloads):
        response = client.post(
            "/v1/evidence",
            headers=_headers(f"dg17-a1-{suffix}-{ordinal}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": source_ref,
                "subject_id": subject_id,
                "observed_at": "2026-08-27T19:30:00+08:00",
                "content": content,
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201, response.json

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg17-a1-turn-first-{suffix}",
    )
    assert worker.run_once() >= len(payloads)

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api_connection:
        api_connection.execute(
            "SELECT set_config('milai.tenant_id', %s, false)",
            (str(settings.tenant_id),),
        )
        api_connection.execute(
            "SELECT set_config('milai.actor_id', %s, false)",
            (str(ACTOR_ID),),
        )
        items = api_connection.execute(
            """
            SELECT milai.search_evidence_projection(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                settings.tenant_id,
                ACTOR_ID,
                token,
                Jsonb({"project_ids": ["milai"]}),
                datetime(2026, 8, 28, tzinfo=UTC),
                3,
                "evidence-search-v1",
            ),
        ).fetchone()[0]

    assert [item["source_ref"] for item in items] == [
        source_refs["primary"],
        source_refs["secondary"],
    ]
    assert [item["turn_rank"] for item in items] == [1, 2]
    assert all(item["candidate_unit"] == "TURN" for item in items)
    assert all(item["acquisition_channel"] == "FTS_RAW" for item in items)
    assert all(item["matched_fields"] == ["lexical_text"] for item in items)
    assert all(item["anchor_match"] is True for item in items)
    assert all(item["canonical"] is False for item in items)
    assert not {source_refs["decoy-1"], source_refs["decoy-2"]}.intersection(
        item["source_ref"] for item in items
    )


@pytest.mark.integration
def test_dg17_a2_product_path_executes_typed_slot_probes_and_retains_fusion_provenance(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    token = f"planter{suffix}"
    source_refs = {
        "price": f"dg17-a2://{suffix}/price/turn-0",
        "count": f"dg17-a2://{suffix}/count/turn-0",
    }
    payloads = (
        (
            source_refs["price"],
            f"dg17-a2-price-{suffix}",
            f"user: I paid $60 total for the ceramic {token} order.",
        ),
        (
            source_refs["count"],
            f"dg17-a2-count-{suffix}",
            f"user: I bought six ceramic {token} items in that order.",
        ),
    )
    for ordinal, (source_ref, subject_id, content) in enumerate(payloads):
        response = client.post(
            "/v1/evidence",
            headers=_headers(f"dg17-a2-{suffix}-{ordinal}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": source_ref,
                "subject_id": subject_id,
                "speaker": "user",
                "observed_at": "2026-08-27T20:00:00+08:00",
                "content": content,
                "media_type": "text/plain",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": ["milai"],
                },
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201, response.json

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg17-a2-acquisition-{suffix}",
    )
    assert worker.run_once() >= len(payloads)

    resolved = client.post(
        "/v1/retrieval/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": f"How much did I pay per ceramic {token}?",
            "memory_intent": "HISTORY",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "limit": 10,
        },
    )
    assert resolved.status_code == 200, resolved.json
    progressive = resolved.json["progressive_l1"]
    acquisition = progressive["acquisition_plan"]
    assert acquisition["schema_version"] == "acquisition-plan-v0.1"
    assert acquisition["fusion"]["policy_identity"] == ("RRF_K60_PER_SLOT_QUOTA_THEN_GLOBAL_CAP_V1")
    assert {probe["requirement_slot"] for probe in acquisition["probes"]} == {
        None,
        "TOTAL_PRICE",
        "ITEM_COUNT",
    }
    dispositions = progressive["acquisition_probe_dispositions"]
    assert len(dispositions) == 3
    assert all(item["status"] == "EXECUTED" for item in dispositions)
    results_by_ref = {
        item["source_ref"]: item
        for item in resolved.json["results"]
        if item.get("kind") == "EVIDENCE_OBSERVATION"
    }
    assert set(source_refs.values()) <= set(results_by_ref)
    envelopes = [
        results_by_ref[source_ref]["acquisition_candidate"] for source_ref in source_refs.values()
    ]
    assert all(envelope["schema_version"] == "candidate-envelope-v0.2" for envelope in envelopes)
    assert all(envelope["matched_probes"] for envelope in envelopes)
    assert all(envelope["channel_ranks"]["FTS_RAW"] >= 1 for envelope in envelopes)
    assert all(envelope["fusion_rank"] >= 1 for envelope in envelopes)
    assert all(envelope["speaker"] == "user" for envelope in envelopes)
    assert all(envelope["speaker_source"] == "STRUCTURED_TURN_METADATA" for envelope in envelopes)
    assert resolved.json["stage_metrics"]["counts"]["evidence_fts_ms"] == 1
    assert resolved.json["stage_metrics"]["counts"]["evidence_slot_fts_ms"] == 2


@pytest.mark.integration
def test_dg17_a3_structured_speaker_round_trips_without_body_prefix_inference(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    token = f"speakerlineage{suffix}"
    payloads = (
        (
            "structured",
            "assistant",
            f"A source envelope, without a rendered role prefix, contains {token}.",
        ),
        (
            "prefix-only",
            None,
            f"assistant: this body prefix alone must not classify {token}.",
        ),
    )
    receipts: dict[str, dict[str, object]] = {}
    for ordinal, (name, speaker, content) in enumerate(payloads):
        body: dict[str, object] = {
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"dg17-a3://{suffix}/{name}/turn-0",
            "subject_id": f"dg17-a3-session-{suffix}",
            "observed_at": "2026-08-27T20:30:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True, "project_ids": ["milai"]},
            "retention_state": "READABLE",
        }
        if speaker is not None:
            body["speaker"] = speaker
        created = client.post(
            "/v1/evidence",
            headers=_headers(f"dg17-a3-{suffix}-{ordinal}"),
            json=body,
        )
        assert created.status_code == 201, created.json
        fetched = client.get(f"/v1/evidence/{created.json['evidence_id']}", headers=_headers())
        assert fetched.status_code == 200, fetched.json
        receipts[name] = {**created.json, **fetched.json}

    assert receipts["structured"]["speaker"] == "assistant"
    assert receipts["structured"]["speaker_source"] == "STRUCTURED_TURN_METADATA"
    assert receipts["prefix-only"]["speaker"] == "unknown"
    assert receipts["prefix-only"]["speaker_source"] == "UNKNOWN"

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg17-a3-speaker-{suffix}",
    )
    assert worker.run_once() >= len(payloads)

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api_connection:
        api_connection.execute(
            "SELECT set_config('milai.tenant_id', %s, false)",
            (str(settings.tenant_id),),
        )
        api_connection.execute(
            "SELECT set_config('milai.actor_id', %s, false)",
            (str(ACTOR_ID),),
        )
        items = api_connection.execute(
            """
            SELECT milai.search_evidence_projection(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                settings.tenant_id,
                ACTOR_ID,
                token,
                Jsonb({"project_ids": ["milai"]}),
                datetime(2026, 8, 28, tzinfo=UTC),
                10,
                "evidence-search-v1",
            ),
        ).fetchone()[0]

    by_ref = {item["source_ref"].split("/")[-2]: item for item in items}
    assert by_ref["structured"]["speaker"] == "assistant"
    assert by_ref["structured"]["speaker_source"] == "STRUCTURED_TURN_METADATA"
    assert by_ref["prefix-only"]["speaker"] == "unknown"
    assert by_ref["prefix-only"]["speaker_source"] == "UNKNOWN"

    resolved = client.post(
        "/v1/retrieval/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": f"What contains {token}?",
            "memory_intent": "HISTORY",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "limit": 10,
        },
    )
    assert resolved.status_code == 200, resolved.json
    envelopes = {
        item["source_ref"].split("/")[-2]: item["acquisition_candidate"]
        for item in resolved.json["results"]
        if item.get("kind") == "EVIDENCE_OBSERVATION"
        and item.get("source_ref", "").startswith(f"dg17-a3://{suffix}/")
    }
    assert envelopes["structured"]["speaker"] == "assistant"
    assert envelopes["structured"]["speaker_source"] == "STRUCTURED_TURN_METADATA"
    assert envelopes["prefix-only"]["speaker"] == "unknown"
    assert envelopes["prefix-only"]["speaker_source"] == "UNKNOWN"


@pytest.mark.integration
def test_dg18_r1b_governed_structured_adjacency_hydration(worker_runtime) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    token = f"adjacency{suffix}"
    session_id = f"structured-session-{suffix}"

    def capture(
        name: str,
        *,
        turn: int,
        round_ordinal: int,
        content: str,
        project_id: str = "milai",
        readable: bool = True,
        observed_at: str = "2026-08-27T20:30:00+08:00",
        structured: bool = True,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"opaque://{suffix}/{name}",
            "subject_id": f"subject-{suffix}",
            "speaker": "assistant" if turn % 2 else "user",
            "observed_at": observed_at,
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {
                "readable": readable,
                "project_ids": [project_id],
            },
            "retention_state": "READABLE",
        }
        if structured:
            body["source_context"] = {
                "session_id": session_id,
                "turn_id": f"turn-{turn}",
                "turn_ordinal": turn,
                "round_id": f"round-{round_ordinal}",
                "round_ordinal": round_ordinal,
                "previous_turn_id": f"turn-{turn - 1}" if turn > 0 else None,
                "next_turn_id": None,
            }
        created = client.post(
            "/v1/evidence",
            headers=_headers(f"dg18-r1b-{suffix}-{name}"),
            json=body,
        )
        assert created.status_code == 201, created.json
        return created.json

    anchor = capture(
        "anchor",
        turn=2,
        round_ordinal=1,
        content=f"What is the {token} code?",
    )
    same = capture(
        "same",
        turn=3,
        round_ordinal=1,
        content="The governed same-round answer is 47.",
    )
    adjacent = capture(
        "adjacent",
        turn=1,
        round_ordinal=0,
        content="The preceding round establishes the cobalt topic.",
    )
    capture(
        "wrong-scope",
        turn=4,
        round_ordinal=2,
        content="This wrong-scope neighbor must remain hidden.",
        project_id="secret",
    )
    capture(
        "unreadable",
        turn=4,
        round_ordinal=2,
        content="This unreadable neighbor must remain hidden.",
        readable=False,
    )
    capture(
        "future",
        turn=4,
        round_ordinal=2,
        content="This future neighbor must remain hidden.",
        observed_at="2026-08-29T20:30:00+08:00",
    )
    revoked = capture(
        "revoked",
        turn=4,
        round_ordinal=2,
        content="This revoked neighbor must remain hidden.",
    )
    capture(
        "legacy",
        turn=3,
        round_ordinal=1,
        content="assistant: legacy source-ref-like content is not structure.",
        structured=False,
    )

    fetched = client.get(
        f"/v1/evidence/{anchor['evidence_id']}",
        headers=_headers(),
    )
    assert fetched.status_code == 200, fetched.json
    assert fetched.json["source_context"]["session_id"] == session_id
    assert fetched.json["source_context_source"] == "STRUCTURED_TURN_METADATA"

    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg18-r1b-{suffix}",
    )
    assert worker.run_once() >= 8
    revoke = client.post(
        f"/v1/evidence/{revoked['evidence_id']}/revoke",
        headers=_headers(f"dg18-r1b-revoke-{suffix}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202, revoke.json

    repository = RetrievalRepository(app.extensions["milai.database"])
    hydrated = repository.hydrate_evidence_adjacency(
        SessionContext(settings.tenant_id, ACTOR_ID),
        anchor_evidence_ids=[str(anchor["evidence_id"])],
        requested_scope={"project_ids": ["milai"]},
        as_of=datetime(2026, 8, 28, tzinfo=UTC),
        max_items=20,
    )
    assert [item["evidence_id"] for item in hydrated] == [
        same["evidence_id"],
        adjacent["evidence_id"],
    ]
    assert [item["context_expansion"]["trigger"] for item in hydrated] == [
        "SAME_ROUND",
        "ADJACENT_ROUND",
    ]
    assert revoked["evidence_id"] not in {item["evidence_id"] for item in hydrated}

    resolved = client.post(
        "/v1/memory/resolve",
        headers=_headers(),
        json={
            "query": f"Recall the previous turn in the same conversation: {token}",
            "requested_scope": {"project_ids": ["milai"]},
            "budget": {"max_context_tokens": 2_048},
        },
    )
    assert resolved.status_code == 200, resolved.json
    memory_context = resolved.json["memory_context"]
    assert memory_context["compile_trace"]["hydrated_evidence_count"] >= 1
    activation = memory_context["compile_trace"]["expansion_activation"]
    assert activation["eligible"] is True
    assert activation["activated"] is True
    assert {same["evidence_id"], adjacent["evidence_id"]} <= set(
        memory_context["selected_evidence_ids"]
    )


@pytest.mark.integration
def test_dg17_a4_enriched_probe_is_separate_and_recovers_safe_morphology(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    source_ref = f"dg17-a4://{suffix}/drone/turn-0"
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"dg17-a4-{suffix}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": source_ref,
            "subject_id": f"dg17-a4-session-{suffix}",
            "speaker": "tool",
            "observed_at": "2026-08-27T20:30:00+08:00",
            "content": "A drone completed the route.",
            "media_type": "text/plain",
            "permission_snapshot": {
                "readable": True,
                "project_ids": ["milai"],
            },
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201, response.json
    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg17-a4-lexical-{suffix}",
    )
    assert worker.run_once() >= 1

    request = {
        "route": "L1",
        "query": "Which drones?",
        "memory_intent": "HISTORY",
        "requested_scope": {"project_ids": ["milai"]},
        "required_authority": "INFORMATIONAL",
        "limit": 10,
    }
    baseline = client.post("/v1/retrieval/query", headers=_headers(), json=request)
    assert baseline.status_code == 200, baseline.json
    assert source_ref not in {item.get("source_ref") for item in baseline.json["results"]}

    app.extensions["milai.retrieval_service"] = RetrievalService(
        RetrievalRepository(app.extensions["milai.database"]),
        embedding=DeterministicHashEmbedding(),
        lexical_enrichment_enabled=True,
    )
    enriched = client.post("/v1/retrieval/query", headers=_headers(), json=request)
    assert enriched.status_code == 200, enriched.json
    selected = next(
        item for item in enriched.json["results"] if item.get("source_ref") == source_ref
    )
    envelope = selected["acquisition_candidate"]
    assert envelope["channel_ranks"] == {"FTS_ENRICHED": 1}
    assert envelope["matched_fields"] == ["enriched_lexical_query"]
    probes = enriched.json["progressive_l1"]["acquisition_plan"]["probes"]
    assert [probe["channel"] for probe in probes] == [
        "FTS_RAW",
        "FTS_RAW",
        "FTS_ENRICHED",
    ]


@pytest.mark.integration
def test_dg17_a5_observed_time_projection_cannot_close_event_time_domain(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    source_ref = f"dg17-a5://{suffix}/reported-later/turn-0"
    created = client.post(
        "/v1/evidence",
        headers=_headers(f"dg17-a5-{suffix}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": source_ref,
            "subject_id": f"dg17-a5-session-{suffix}",
            "speaker": "user",
            "observed_at": "2023-03-15T09:00:00+00:00",
            "content": "Maya's baby was born on January 5th, 2023.",
            "media_type": "text/plain",
            "permission_snapshot": {
                "readable": True,
                "project_ids": ["milai"],
            },
            "retention_state": "READABLE",
        },
    )
    assert created.status_code == 201, created.json
    worker = _worker(
        settings,
        worker_database,
        embedding=DeterministicHashEmbedding(),
        worker_id=f"dg17-a5-temporal-{suffix}",
    )
    assert worker.run_once() >= 1

    repository = RetrievalRepository(app.extensions["milai.database"])
    source_scan = repository.scan_evidence_range(
        SessionContext(settings.tenant_id, ACTOR_ID),
        {"project_ids": ["milai"]},
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 2, 1, tzinfo=UTC),
        2_000,
    )
    assert source_scan["status"] == "COMPLETE"
    assert source_scan["scan_axis"] == "SOURCE_OBSERVED_TIME"
    assert source_scan["items"] == []

    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L1",
            query="How many babies were born in January?",
            requested_scope={"project_ids": ["milai"]},
            as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
            system_as_of=datetime(2023, 3, 27, 12, tzinfo=UTC),
        )
    )
    derived = compose_evidence_range_count(plan, source_scan)
    assert derived is not None
    assert derived["status"] == "PARTIAL"
    assert derived["reason"] == "EVENT_TIME_DOMAIN_UNPROVEN"
    assert derived["value"] is None

    resolved = client.post(
        "/v1/retrieval/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": "How many babies were born in January?",
            "memory_intent": "HISTORY",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "as_of": "2023-03-27T12:00:00+00:00",
            "system_as_of": "2023-03-27T12:00:00+00:00",
            "limit": 10,
        },
    )
    assert resolved.status_code == 200, resolved.json
    assert resolved.json["progressive_l1"]["temporal_acquisition"] == {
        "query_axis": "EVENT_OCCURRENCE_TIME",
        "scan_axis": "CANDIDATE_SET",
        "disposition": "EVENT_PROJECTION_UNAVAILABLE",
    }
    assert resolved.json["derived_result"]["status"] == "PARTIAL"
    assert resolved.json["derived_result"]["reason"] == "EVENT_TIME_DOMAIN_UNPROVEN"
    assert resolved.json["stage_metrics"]["counts"].get("evidence_range_scan_ms", 0) == 0


@pytest.mark.integration
def test_dg17_a6_raw_evidence_dense_is_prefiltered_lossless_and_purge_safe(
    worker_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app, worker_database = worker_runtime
    client = app.test_client()
    suffix = uuid4().hex
    source_ref = f"dg17-a6://{suffix}/cobalt/turn-0"
    content = f"A cobalt instrument carried the opaque marker {suffix}."
    created = client.post(
        "/v1/evidence",
        headers=_headers(f"dg17-a6-{suffix}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": source_ref,
            "subject_id": f"dg17-a6-session-{suffix}",
            "speaker": "tool",
            "observed_at": "2026-08-27T20:30:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {
                "readable": True,
                "project_ids": ["milai"],
            },
            "retention_state": "READABLE",
        },
    )
    assert created.status_code == 201, created.json
    embedding = _Synthetic128Embedding()
    worker = _worker(
        settings,
        worker_database,
        embedding=embedding,
        worker_id=f"dg17-a6-dense-{suffix}",
    )
    assert worker.run_once() >= 1
    projection_version = evidence_turn_projection_version(embedding.identity)

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        owner.execute(
            "DELETE FROM milai.evidence_dense_embedding_128 "
            "WHERE tenant_id = %s AND evidence_id = %s",
            (settings.tenant_id, created.json["evidence_id"]),
        )
    rebuilt = rebuild_evidence_dense(
        ProjectionRepository(worker_database),
        SessionContext(settings.tenant_id, ACTOR_ID),
        embedding,
        batch_size=8,
    )
    assert rebuilt["status"] == "COMPLETE"
    assert rebuilt["projected_count"] == 1
    assert rebuilt["canonical_mutation"] is False

    repository = RetrievalRepository(app.extensions["milai.database"])
    dense = repository.search_evidence_dense(
        SessionContext(settings.tenant_id, ACTOR_ID),
        embedding.embed("an unrelated semantic query"),
        {"project_ids": ["milai"]},
        datetime(2026, 8, 28, tzinfo=UTC),
        10,
        model_id=embedding.identity.model_id,
        projection_version=projection_version,
    )
    assert dense["status"] == "COMPLETE"
    assert dense["source_count"] == dense["projected_count"] == 1
    assert dense["items"][0]["source_ref"] == source_ref
    assert dense["items"][0]["content"] == content
    assert dense["items"][0]["speaker"] == "tool"
    assert dense["items"][0]["acquisition_channel"] == "EVIDENCE_DENSE"

    app.extensions["milai.retrieval_service"] = RetrievalService(
        repository,
        embedding=embedding,
        evidence_dense_enabled=True,
    )
    resolved = client.post(
        "/v1/retrieval/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": "Which item is semantically related to an unseen phrase?",
            "memory_intent": "HISTORY",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "as_of": "2026-08-28T00:00:00+00:00",
            "system_as_of": "2026-08-28T00:00:00+00:00",
            "limit": 10,
        },
    )
    assert resolved.status_code == 200, resolved.json
    selected = next(
        item for item in resolved.json["results"] if item.get("source_ref") == source_ref
    )
    envelope = selected["acquisition_candidate"]
    assert envelope["channel_ranks"] == {"EVIDENCE_DENSE": 1}
    assert envelope["matched_fields"] == ["evidence_dense_embedding"]
    dense_dispositions = [
        item
        for item in resolved.json["progressive_l1"]["acquisition_probe_dispositions"]
        if item["channel"] == "EVIDENCE_DENSE"
    ]
    assert dense_dispositions
    assert all(item["status"] == "EXECUTED" for item in dense_dispositions)

    event_bounded = client.post(
        "/v1/retrieval/query",
        headers=_headers(),
        json={
            "route": "L1",
            "query": "How many times did I bake something in the past two weeks?",
            "memory_intent": "HISTORY",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "as_of": "2026-08-28T00:00:00+00:00",
            "system_as_of": "2026-08-28T00:00:00+00:00",
            "limit": 10,
        },
    )
    assert event_bounded.status_code == 200, event_bounded.json
    event_dense_dispositions = [
        item
        for item in event_bounded.json["progressive_l1"]["acquisition_probe_dispositions"]
        if item["channel"] == "EVIDENCE_DENSE"
    ]
    assert event_dense_dispositions
    assert all(
        item["status"] == "EVENT_TIME_FILTER_UNAVAILABLE" and item["candidate_count"] == 0
        for item in event_dense_dispositions
    )

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        owner.execute(
            "DELETE FROM milai.evidence_dense_embedding_128 "
            "WHERE tenant_id = %s AND evidence_id = %s",
            (settings.tenant_id, created.json["evidence_id"]),
        )
    partial = repository.search_evidence_dense(
        SessionContext(settings.tenant_id, ACTOR_ID),
        embedding.embed("projection readiness probe"),
        {"project_ids": ["milai"]},
        datetime(2026, 8, 28, tzinfo=UTC),
        10,
        model_id=embedding.identity.model_id,
        projection_version=projection_version,
    )
    assert partial["status"] == "PARTIAL"
    assert partial["source_count"] == 1
    assert partial["projected_count"] == 0
    assert partial["projection_ready"] is False
    assert (
        rebuild_evidence_dense(
            ProjectionRepository(worker_database),
            SessionContext(settings.tenant_id, ACTOR_ID),
            embedding,
            batch_size=8,
        )["status"]
        == "COMPLETE"
    )

    revoke = client.post(
        f"/v1/evidence/{created.json['evidence_id']}/revoke",
        headers=_headers(f"dg17-a6-revoke-{suffix}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoke.status_code == 202, revoke.json
    assert worker.run_once() >= 1
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        remaining = owner.execute(
            "SELECT count(*) FROM milai.evidence_dense_embedding_128 "
            "WHERE tenant_id = %s AND evidence_id = %s",
            (settings.tenant_id, created.json["evidence_id"]),
        ).fetchone()[0]
    assert remaining == 0
