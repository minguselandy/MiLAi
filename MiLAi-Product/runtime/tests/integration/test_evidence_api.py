from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.persistence import Database

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )


def _headers(idempotency_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "Idempotency-Key": idempotency_key,
    }


def _payload(content: str = "deployment uses Python 3.11") -> dict[str, object]:
    return {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": f"integration://{uuid4()}",
        "subject_id": "milai-runtime-python",
        "observed_at": "2026-08-15T10:00:00+08:00",
        "content": content,
        "media_type": "text/plain; charset=utf-8",
        "permission_snapshot": {"readable": True, "scope": "local"},
        "retention_state": "READABLE",
    }


@pytest.fixture
def evidence_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    settings = _settings(tmp_path)
    prepare_runtime_directories(settings)
    database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    app = create_app(settings, database=database, steward_database=steward_database)
    app.config["TESTING"] = True
    yield app
    database.close()
    steward_database.close()


@pytest.mark.integration
def test_tx01_api_replay_conflict_blob_dedup_and_lineage(evidence_app) -> None:  # type: ignore[no-untyped-def]
    client = evidence_app.test_client()
    blocked_personal = client.post(
        "/v1/evidence",
        json={**_payload("synthetic stand-in"), "data_classification": "PERSONAL"},
        headers=_headers(f"evidence-personal-{uuid4()}"),
    )
    assert blocked_personal.status_code == 403
    assert blocked_personal.json["error"]["code"] == "DATA_MODE_BLOCKED"
    payload = _payload()
    key = f"evidence-{uuid4()}"

    created = client.post("/v1/evidence", json=payload, headers=_headers(key))
    assert created.status_code == 201
    assert created.json["replayed"] is False

    replayed = client.post("/v1/evidence", json=payload, headers=_headers(key))
    assert replayed.status_code == 200
    assert replayed.json["replayed"] is True
    assert replayed.json["evidence_id"] == created.json["evidence_id"]
    assert replayed.json["outbox_id"] == created.json["outbox_id"]

    changed = dict(payload)
    changed["content"] = "different content"
    conflict = client.post("/v1/evidence", json=changed, headers=_headers(key))
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    second_observation = dict(payload)
    second_observation["source_ref"] = f"integration://{uuid4()}"
    second = client.post(
        "/v1/evidence",
        json=second_observation,
        headers=_headers(f"evidence-{uuid4()}"),
    )
    assert second.status_code == 201
    assert second.json["evidence_id"] != created.json["evidence_id"]
    assert second.json["blob_id"] == created.json["blob_id"]

    fetched = client.get(
        f"/v1/evidence/{created.json['evidence_id']}",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert fetched.status_code == 200
    assert fetched.json["content"] == payload["content"]
    assert (
        fetched.json["content_hash"] == hashlib.sha256(str(payload["content"]).encode()).hexdigest()
    )

    lineage = client.get(
        f"/v1/evidence/{created.json['evidence_id']}/lineage",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert lineage.status_code == 200
    assert lineage.json["evidence"]["evidence_id"] == created.json["evidence_id"]
    assert lineage.json["claim_version_refs"] == []

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        evidence_count = owner.execute(
            "SELECT count(*) FROM milai.evidence_record WHERE evidence_id IN (%s, %s)",
            (UUID(created.json["evidence_id"]), UUID(second.json["evidence_id"])),
        ).fetchone()[0]
        outbox_count = owner.execute(
            "SELECT count(*) FROM milai.outbox_event WHERE aggregate_id = %s",
            (UUID(created.json["evidence_id"]),),
        ).fetchone()[0]
        event_count = owner.execute(
            """
            SELECT count(*) FROM milai.operational_event
            WHERE safe_metadata ->> 'evidence_id' = %s
            """,
            (created.json["evidence_id"],),
        ).fetchone()[0]
    assert evidence_count == 2
    assert outbox_count == 1
    assert event_count == 1


@pytest.mark.integration
def test_body_cannot_switch_authenticated_tenant(evidence_app) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    payload["tenant_id"] = "22222222-2222-4222-8222-222222222222"
    response = evidence_app.test_client().post(
        "/v1/evidence",
        json=payload,
        headers=_headers(f"evidence-{uuid4()}"),
    )
    assert response.status_code == 403
    assert response.json["error"]["code"] == "TENANT_MISMATCH"


@pytest.mark.integration
def test_permission_snapshot_that_is_not_readable_hides_evidence_content(evidence_app) -> None:  # type: ignore[no-untyped-def]
    payload = _payload("permission-protected synthetic content")
    payload["permission_snapshot"] = {"readable": False}
    created = evidence_app.test_client().post(
        "/v1/evidence",
        json=payload,
        headers=_headers(f"evidence-{uuid4()}"),
    )
    fetched = evidence_app.test_client().get(
        f"/v1/evidence/{created.json['evidence_id']}",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert fetched.status_code == 200
    assert fetched.json["content"] is None


@pytest.mark.integration
def test_project_read_rejects_before_loading_source_bytes(evidence_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = evidence_app.test_client()
    content = " \r\nprivate synthetic source 🧠\t "
    payload = _payload(content)
    payload["permission_snapshot"] = {"readable": True, "project_ids": ["project-a"]}
    created = client.post("/v1/evidence", json=payload, headers=_headers(str(uuid4())))
    assert created.status_code == 201
    path = f"/v1/evidence/{created.json['evidence_id']}"
    own = client.get(path + "?project_id=project-a", headers=_headers("read"))
    assert own.status_code == 200
    assert own.json["content"] == content

    def forbidden_read(*args, **kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("foreign-project lookup attempted to load private bytes")

    monkeypatch.setattr(
        evidence_app.extensions["milai.evidence_service"]._blob_store, "read", forbidden_read,
    )
    other = client.get(path + "?project_id=project-b", headers=_headers("read"))
    assert other.status_code == 404
    assert content not in other.get_data(as_text=True)


def _invoke_tx01(
    api_url: str,
    key: str,
    tenant_id: UUID = TENANT_ID,
    actor_id: UUID = ACTOR_ID,
) -> dict[str, object]:
    content_hash = hashlib.sha256(b"concurrent").hexdigest()
    with psycopg.connect(api_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
        connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(actor_id),))
        row = connection.execute(
            """
            SELECT milai.tx01_ingest_evidence(
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                tenant_id,
                actor_id,
                key,
                hashlib.sha256(key.encode()).hexdigest(),
                "RUNTIME_OBSERVATION",
                f"concurrency://{key}",
                "concurrent-subject",
                datetime.now(UTC),
                content_hash,
                f"cas://sha256/{tenant_id}/{content_hash}",
                len(b"concurrent"),
                "text/plain",
                Jsonb({"readable": True}),
                "READABLE",
            ),
        ).fetchone()
        assert row is not None
        return row[0]


@pytest.mark.integration
def test_tx01_concurrent_same_key_has_one_canonical_side_effect() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    key = f"concurrent-{uuid4()}"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _invoke_tx01(api_url, key), range(2)))
    assert results[0]["evidence_id"] == results[1]["evidence_id"]
    assert sorted(result["replayed"] for result in results) == [False, True]

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        count = owner.execute(
            "SELECT count(*) FROM milai.evidence_record WHERE ingest_idempotency_key = %s",
            (key,),
        ).fetchone()[0]
    assert count == 1


@pytest.mark.integration
def test_tx01_failure_rolls_back_idempotency_outbox_and_event() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    key = f"rollback-{uuid4()}"
    content_hash = hashlib.sha256(b"rollback").hexdigest()
    with psycopg.connect(api_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
        connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                SELECT milai.tx01_ingest_evidence(
                  %s, %s, %s, %s, '', %s, %s, %s,
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    TENANT_ID,
                    ACTOR_ID,
                    key,
                    hashlib.sha256(key.encode()).hexdigest(),
                    f"rollback://{key}",
                    "rollback-subject",
                    datetime.now(UTC),
                    content_hash,
                    f"cas://sha256/{TENANT_ID}/{content_hash}",
                    len(b"rollback"),
                    "text/plain",
                    Jsonb({"readable": True}),
                    "READABLE",
                ),
            )
        connection.rollback()

    with psycopg.connect(owner_url) as owner:
        idempotency_count = owner.execute(
            "SELECT count(*) FROM milai.idempotency_record WHERE idempotency_key = %s", (key,)
        ).fetchone()[0]
        evidence_count = owner.execute(
            "SELECT count(*) FROM milai.evidence_record WHERE ingest_idempotency_key = %s", (key,)
        ).fetchone()[0]
    assert idempotency_count == 0
    assert evidence_count == 0


@pytest.mark.integration
def test_content_blob_deduplication_never_crosses_tenants() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    other_tenant = UUID("22222222-2222-4222-8222-222222222222")
    other_actor = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    first = _invoke_tx01(api_url, f"tenant-one-{uuid4()}")
    second = _invoke_tx01(
        api_url,
        f"tenant-two-{uuid4()}",
        tenant_id=other_tenant,
        actor_id=other_actor,
    )
    assert first["blob_id"] != second["blob_id"]

    with psycopg.connect(owner_url) as owner:
        tenant_count = owner.execute(
            """
            SELECT count(DISTINCT tenant_id)
            FROM milai.content_blob
            WHERE blob_id IN (%s, %s)
            """,
            (UUID(str(first["blob_id"])), UUID(str(second["blob_id"]))),
        ).fetchone()[0]
    assert tenant_count == 2


@pytest.mark.integration
def test_evidence_capture_identity_is_immutable_even_for_owner() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    created = _invoke_tx01(api_url, f"immutable-{uuid4()}")
    with psycopg.connect(owner_url) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="IMMUTABLE_EVIDENCE_IDENTITY"):
            owner.execute(
                "UPDATE milai.evidence_record SET source_ref = 'forbidden' WHERE evidence_id = %s",
                (UUID(str(created["evidence_id"])),),
            )
