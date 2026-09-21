from __future__ import annotations

import os
import shutil
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.operations import (
    BackupError,
    create_backup,
    expire_backup,
    restore_backup,
    verify_backup,
)
from milai.persistence import Database
from milai.persistence.projection_repository import ProjectionRepository
from milai.workers.main import FoundationWorker

pytestmark = pytest.mark.integration

ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
REVIEWER_TOKEN = "reviewer-token-with-at-least-32-characters"


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _database_url(source: str, database: str) -> str:
    parsed = urlsplit(source)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, ""))


def _database_admin_url(database: str) -> str:
    return _database_url(_url("MILAI_MIGRATION_DATABASE_URL"), database)


def _create_database(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop_database(admin_url: str, name: str) -> None:
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _settings(tmp_path: Path, tenant_id: UUID, database: str) -> RuntimeSettings:
    return RuntimeSettings(
        database_url=_database_url(_url("MILAI_TEST_API_DATABASE_URL"), database),
        steward_database_url=_database_url(_url("MILAI_TEST_STEWARD_DATABASE_URL"), database),
        blob_root=tmp_path / "source-blobs",
        tenant_id=tenant_id,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        agent_reviewer_token=REVIEWER_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
        worker_event_limit=10_000,
        worker_retry_delay_seconds=0,
    )


def _runtime(settings: RuntimeSettings, database: str):  # type: ignore[no-untyped-def]
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    worker_database = Database(
        settings, dsn=_database_url(_url("MILAI_TEST_WORKER_DATABASE_URL"), database)
    )
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    return app, api_database, steward_database, worker_database


def _close_and_wait_for_quiescence(
    owner_database_url: str,
    *databases: Database,
) -> None:
    for database in databases:
        database.close()
    deadline = monotonic() + 5.0
    while True:
        with psycopg.connect(owner_database_url) as connection:
            rows = connection.execute(
                """
                SELECT usename, count(*)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND usename = ANY(%s)
                GROUP BY usename
                ORDER BY usename
                """,
                (["milai_api", "milai_steward", "milai_worker"],),
            ).fetchall()
        if not rows:
            return
        if monotonic() >= deadline:
            pytest.fail(f"runtime database sessions did not quiesce after close: {rows!r}")
        sleep(0.01)


def _headers(key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def _review_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {REVIEWER_TOKEN}",
        "Idempotency-Key": key,
    }


def _create_grounded_claim(client, token: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    evidence = client.post(
        "/v1/evidence",
        headers=_headers(f"evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"backup-test://{uuid4()}",
            "subject_id": "backup-test",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": f"backup content {token}",
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert evidence.status_code == 201
    evidence_id = str(evidence.json["evidence_id"])
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": f"backup-{uuid4()}",
                "predicate": "backup.fact",
                "claim_type": "FACT",
                "payload": {"token": token},
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "backup-test-v1",
            "derivation_snapshot": {"fixture": "backup"},
        },
    )
    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_review_headers(f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "backup-test-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    return evidence_id, str(review.json["claim_version_id"])


def _capture_and_settle_episode(client, evidence_id: str) -> str:  # type: ignore[no-untyped-def]
    captured = client.post(
        "/v1/episodes",
        headers=_headers(f"backup-episode-{uuid4()}"),
        json={"subject_id": "backup-test", "evidence_refs": [evidence_id]},
    )
    assert captured.status_code == 201
    episode_id = str(captured.json["episode_id"])
    settled = client.post(
        f"/v1/episodes/{episode_id}/settle",
        headers=_headers(f"backup-settlement-{uuid4()}"),
        json={"expected_revision": 1, "confirmation": "SETTLE"},
    )
    assert settled.status_code == 200
    return episode_id


def _run_worker(settings: RuntimeSettings, database: Database) -> None:
    worker = FoundationWorker(
        settings,
        database,
        repository=ProjectionRepository(database),
        blob_store=LocalContentAddressedBlobStore(settings.blob_root),
        embedding=DeterministicHashEmbedding(),
        worker_id=f"backup-worker-{uuid4()}",
    )
    assert worker.run_once() > 0


@pytest.mark.integration
def test_consistency_backup_restore_and_deletion_expiry_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_database = f"milai_backup_src_{uuid4().hex[:12]}"
    target_database = f"milai_backup_dst_{uuid4().hex[:12]}"
    admin_url = _database_admin_url("postgres")
    _create_database(admin_url, source_database)
    _create_database(admin_url, target_database)
    source_owner = _database_admin_url(source_database)
    target_owner = _database_admin_url(target_database)
    source_audit = _database_url(_url("MILAI_TEST_AUDIT_DATABASE_URL"), source_database)
    settings = _settings(tmp_path, uuid4(), source_database)
    prepare_runtime_directories(settings)
    first_archive = tmp_path / "backup-before-revoke"
    second_archive = tmp_path / "backup-after-revoke"
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", source_owner)
        command.upgrade(Config("alembic.ini"), "head")
        app, api_database, steward_database, worker_database = _runtime(settings, source_database)
        client = app.test_client()
        evidence_id, claim_version_id = _create_grounded_claim(client, f"backuptoken{uuid4().hex}")
        note_binding = {"principal_binding_digest": "a" * 64, "project_id": "backup-note"}
        note_text = " \r\nNote survives archive recovery 🧠\t "
        note = client.post("/v1/notes/write", headers=_headers("backup-note-add"), json={
            **note_binding, "operation": "ADD", "content": note_text,
        })
        assert note.status_code == 200
        deleted = client.post("/v1/notes/write", headers=_headers("backup-note-delete"), json={
            **note_binding, "operation": "DELETE", "memory_id": note.json["memory_id"],
            "expected_version": 1,
        })
        assert deleted.status_code == 200
        episode_id = _capture_and_settle_episode(client, evidence_id)
        _run_worker(settings, worker_database)
        _close_and_wait_for_quiescence(
            source_owner,
            api_database,
            steward_database,
            worker_database,
        )

        first = create_backup(
            settings,
            first_archive,
            owner_database_url=source_owner,
            audit_database_url=source_audit,
        )
        assert verify_backup(first_archive).manifest["backup_id"] == first["backup_id"]
        assert len(first["blob_files"]) == 1
        assert first["inventory"]["tables"]["host_note"]["count"] == 1
        assert first["inventory"]["tables"]["host_note_version"]["count"] == 2
        assert {
            "episode",
            "episode_settlement",
            "episode_transition",
            "retrieval_trace",
            "context_capsule",
            "projection_delivery",
            "steward_decision",
            "legacy_issue_transition_quarantine",
            "legacy_grounding_relation_quarantine",
        } <= set(first["inventory"]["tables"])

        app, api_database, steward_database, worker_database = _runtime(settings, source_database)
        client = app.test_client()
        revoke = client.post(
            f"/v1/evidence/{evidence_id}/revoke",
            headers=_headers(f"revoke-{uuid4()}"),
            json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
        )
        assert revoke.status_code == 202
        deletion_request_id = str(revoke.json["deletion_request_id"])
        _run_worker(settings, worker_database)
        _close_and_wait_for_quiescence(
            source_owner,
            api_database,
            steward_database,
            worker_database,
        )

        with psycopg.connect(source_owner) as owner:
            statuses = owner.execute(
                """
                SELECT primary_bytes_status, backup_expiry_status
                FROM milai.deletion_request
                WHERE tenant_id = %s AND deletion_request_id = %s
                """,
                (settings.tenant_id, deletion_request_id),
            ).fetchone()
        assert statuses == ("ERASED", "PENDING")

        second = create_backup(
            settings,
            second_archive,
            owner_database_url=source_owner,
            audit_database_url=source_audit,
        )
        assert second["blob_files"] == []
        with psycopg.connect(source_owner) as owner:
            pending = owner.execute(
                """
                SELECT count(*) FROM milai.backup_deletion_obligation
                WHERE tenant_id = %s AND deletion_request_id = %s AND status = 'PENDING'
                """,
                (settings.tenant_id, deletion_request_id),
            ).fetchone()[0]
        assert pending == 1

        expired = expire_backup(
            settings,
            first_archive,
            audit_database_url=source_audit,
            confirmation="ERASE_BACKUP_ARCHIVE",
        )
        assert expired["status"] == "EXPIRED"
        assert not first_archive.exists()
        with psycopg.connect(source_owner) as owner:
            backup_status = owner.execute(
                """
                SELECT backup_expiry_status FROM milai.deletion_request
                WHERE tenant_id = %s AND deletion_request_id = %s
                """,
                (settings.tenant_id, deletion_request_id),
            ).fetchone()[0]
        assert backup_status == "COMPLETED"

        restored = restore_backup(
            second_archive,
            tmp_path / "restored-blobs",
            target_database_url=target_owner,
            confirm_empty_target=True,
        )
        assert restored["status"] == "RESTORED_AND_RECONCILED"
        with psycopg.connect(target_owner) as target:
            (
                restored_version,
                restored_block,
                restored_episode,
                restored_settlement,
            ) = target.execute(
                """
                SELECT
                  (SELECT count(*) FROM milai.claim_version
                   WHERE tenant_id = %s AND claim_version_id = %s),
                  (SELECT count(*) FROM milai.grounding_block
                   WHERE tenant_id = %s AND claim_version_id = %s AND active),
                  (SELECT count(*) FROM milai.episode
                   WHERE tenant_id = %s AND episode_id = %s AND status = 'SETTLED'),
                  (SELECT count(*) FROM milai.episode_settlement
                   WHERE tenant_id = %s AND episode_id = %s)
                """,
                (
                    settings.tenant_id,
                    claim_version_id,
                    settings.tenant_id,
                    claim_version_id,
                    settings.tenant_id,
                    episode_id,
                    settings.tenant_id,
                    episode_id,
                ),
            ).fetchone()
        assert (
            restored_version,
            restored_block,
            restored_episode,
            restored_settlement,
        ) == (1, 1, 1, 1)
        with psycopg.connect(target_owner) as target:
            note_rows = target.execute(
                "SELECT version, content, deleted FROM milai.host_note_version "
                "WHERE memory_id = %s ORDER BY version", (note.json["memory_id"],),
            ).fetchall()
            head = target.execute(
                "SELECT current_version, deleted FROM milai.host_note WHERE memory_id = %s",
                (note.json["memory_id"],),
            ).fetchone()
        assert note_rows == [(1, note_text, False), (2, None, True)]
        assert head == (2, True)

        tampered = tmp_path / "tampered-backup"
        shutil.copytree(second_archive, tampered)
        with (tampered / "database.dump").open("ab") as handle:
            handle.write(b"tamper")
        with pytest.raises(BackupError, match="database dump hash mismatch"):
            verify_backup(tampered)
    finally:
        _drop_database(admin_url, target_database)
        _drop_database(admin_url, source_database)
