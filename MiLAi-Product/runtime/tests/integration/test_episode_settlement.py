from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.persistence import Database

ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
SCOPE = {"project_ids": ["milai"]}


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def episode_runtime(tmp_path: Path):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    prepare_runtime_directories(settings)
    api_database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    app = create_app(settings, database=api_database, steward_database=steward_database)
    app.config["TESTING"] = True
    yield settings, app
    api_database.close()
    steward_database.close()


def _headers(key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {API_TOKEN}"}
    if key:
        result["Idempotency-Key"] = key
    return result


def _set_context(connection, tenant_id: UUID) -> None:  # type: ignore[no-untyped-def]
    connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
    connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))


def _ingest(client) -> str:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"episode-evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"episode-test://{uuid4()}",
            "subject_id": "episode-subject",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": "synthetic replayable Episode content",
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert response.status_code == 201
    return str(response.json["evidence_id"])


def _pending_proposal(client, evidence_id: str) -> str:  # type: ignore[no-untyped-def]
    response = client.post(
        "/v1/proposals",
        headers=_headers(f"episode-proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": "episode-subject",
                "predicate": "episode.residual",
                "claim_type": "RESIDUAL_CANDIDATE",
                "payload": {"candidate": "requires review"},
                "authority": "INFORMATIONAL",
                "confidence": 0.5,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": SCOPE,
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "episode-settlement-v1",
            "derivation_snapshot": {"source": "synthetic-episode"},
        },
    )
    assert response.status_code == 201
    return str(response.json["proposal_id"])


@pytest.mark.integration
def test_episode_capture_settlement_is_replayable_governed_and_expires_context(
    episode_runtime,
) -> None:  # type: ignore[no-untyped-def]
    settings, app = episode_runtime
    client = app.test_client()
    evidence_id = _ingest(client)
    proposal_id = _pending_proposal(client, evidence_id)
    capsule_id = uuid4()
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        owner.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(settings.tenant_id),))
        owner.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        owner.execute(
            """
            INSERT INTO milai.context_capsule (
              tenant_id, capsule_id, status, protected_sections,
              content_hash, expires_at, created_by_actor_id
            ) VALUES (%s, %s, 'ACTIVE', '{}'::jsonb, %s, %s, %s)
            """,
            (
                settings.tenant_id,
                capsule_id,
                "0" * 64,
                datetime.now(UTC) + timedelta(hours=1),
                ACTOR_ID,
            ),
        )
        claims_before = owner.execute(
            "SELECT count(*) FROM milai.claim_version WHERE tenant_id = %s",
            (settings.tenant_id,),
        ).fetchone()[0]

    capture_body = {
        "subject_id": "episode-subject",
        "evidence_refs": [evidence_id],
        "context_capsule_refs": [str(capsule_id)],
    }
    captured = client.post("/v1/episodes", headers=_headers("episode-capture-1"), json=capture_body)
    assert captured.status_code == 201
    assert captured.json["status"] == "OPEN"
    assert captured.json["revision"] == 1
    episode_id = captured.json["episode_id"]

    replay = client.post("/v1/episodes", headers=_headers("episode-capture-1"), json=capture_body)
    assert replay.status_code == 200
    assert replay.json["episode_id"] == episode_id
    assert replay.json["replayed"] is True

    conflict = client.post(
        "/v1/episodes",
        headers=_headers("episode-capture-1"),
        json={**capture_body, "subject_id": "different"},
    )
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    open_episode = client.get(f"/v1/episodes/{episode_id}", headers=_headers())
    assert open_episode.status_code == 200
    assert open_episode.json["evidence_refs"] == [evidence_id]
    assert open_episode.json["context_capsule_refs"] == [str(capsule_id)]
    assert [item["event_type"] for item in open_episode.json["transitions"]] == ["EPISODE_CAPTURED"]

    settle_body = {
        "expected_revision": 1,
        "residual_proposal_ids": [proposal_id],
        "open_issue_ids": [],
        "confirmation": "SETTLE",
    }
    settled = client.post(
        f"/v1/episodes/{episode_id}/settle",
        headers=_headers("episode-settle-1"),
        json=settle_body,
    )
    assert settled.status_code == 200
    assert settled.json["status"] == "SETTLED"
    assert settled.json["revision"] == 2
    assert settled.json["residual_proposal_ids"] == [proposal_id]
    assert settled.json["expired_context_capsule_ids"] == [str(capsule_id)]

    settle_replay = client.post(
        f"/v1/episodes/{episode_id}/settle",
        headers=_headers("episode-settle-1"),
        json=settle_body,
    )
    assert settle_replay.status_code == 200
    assert settle_replay.json["settlement_id"] == settled.json["settlement_id"]
    assert settle_replay.json["replayed"] is True

    stale = client.post(
        f"/v1/episodes/{episode_id}/settle",
        headers=_headers("episode-settle-stale"),
        json=settle_body,
    )
    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "EPISODE_REVISION_CONFLICT"

    final_episode = client.get(f"/v1/episodes/{episode_id}", headers=_headers())
    assert final_episode.json["status"] == "SETTLED"
    assert final_episode.json["settlement"]["residual_proposal_ids"] == [proposal_id]
    assert [item["event_type"] for item in final_episode.json["transitions"]] == [
        "EPISODE_CAPTURED",
        "EPISODE_SETTLED",
    ]

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        context_state = owner.execute(
            """
            SELECT status, invalidation_reason FROM milai.context_capsule
            WHERE tenant_id = %s AND capsule_id = %s
            """,
            (settings.tenant_id, capsule_id),
        ).fetchone()
        claims_after = owner.execute(
            "SELECT count(*) FROM milai.claim_version WHERE tenant_id = %s",
            (settings.tenant_id,),
        ).fetchone()[0]
        with pytest.raises(psycopg.Error):
            owner.execute(
                """
                UPDATE milai.episode SET subject_id = 'mutated'
                WHERE tenant_id = %s AND episode_id = %s
                """,
                (settings.tenant_id, episode_id),
            )
    assert context_state == ("EXPIRED", "EPISODE_SETTLED")
    assert claims_after == claims_before

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as other_tenant:
        _set_context(other_tenant, uuid4())
        visible = other_tenant.execute(
            "SELECT count(*) FROM milai.episode WHERE episode_id = %s", (episode_id,)
        ).fetchone()[0]
        assert visible == 0

    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as api:
        _set_context(api, settings.tenant_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute(
                "UPDATE milai.episode SET revision = revision + 1 WHERE episode_id = %s",
                (episode_id,),
            )

    with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
        _set_context(steward, settings.tenant_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            steward.execute(
                "DELETE FROM milai.episode_settlement WHERE episode_id = %s", (episode_id,)
            )


@pytest.mark.integration
def test_episode_rejects_unknown_refs_tenant_switch_and_excess_residuals(
    episode_runtime,
) -> None:  # type: ignore[no-untyped-def]
    _settings, app = episode_runtime
    client = app.test_client()
    unknown = client.post(
        "/v1/episodes",
        headers=_headers("episode-unknown"),
        json={"subject_id": "subject", "evidence_refs": [str(uuid4())]},
    )
    assert unknown.status_code == 409
    assert unknown.json["error"]["code"] == "EPISODE_REFERENCE_INVALID"

    evidence_id = _ingest(client)
    tenant_switch = client.post(
        "/v1/episodes",
        headers=_headers("episode-tenant-switch"),
        json={
            "tenant_id": str(uuid4()),
            "subject_id": "subject",
            "evidence_refs": [evidence_id],
        },
    )
    assert tenant_switch.status_code == 403
    assert tenant_switch.json["error"]["code"] == "TENANT_MISMATCH"

    captured = client.post(
        "/v1/episodes",
        headers=_headers("episode-limit-capture"),
        json={"subject_id": "subject", "evidence_refs": [evidence_id]},
    )
    too_many = client.post(
        f"/v1/episodes/{captured.json['episode_id']}/settle",
        headers=_headers("episode-limit-settle"),
        json={
            "expected_revision": 1,
            "residual_proposal_ids": [str(uuid4()) for _ in range(4)],
            "confirmation": "SETTLE",
        },
    )
    assert too_many.status_code == 400
    assert too_many.json["error"]["code"] == "INVALID_REQUEST"
