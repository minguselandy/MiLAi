from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.domain.host_execution_event import HostExecutionEventWindowRequest
from milai.persistence import Database, SessionContext
from milai.persistence.host_execution_event_repository import HostExecutionEventRepository

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
BINDING_DIGEST = "a" * 64


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _database_url(source: str, database: str) -> str:
    parsed = urlsplit(source)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, ""))


@pytest.fixture
def host_event_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    _url("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    prepare_runtime_directories(settings)
    database = Database(settings)
    steward = Database(settings, dsn=settings.steward_database_dsn)
    app = create_app(settings, database=database, steward_database=steward)
    app.config["TESTING"] = True
    yield app
    database.close()
    steward.close()


def _headers(operation_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    if operation_id is not None:
        headers["Idempotency-Key"] = operation_id
    return headers


def _binding(*, project_id: str = "project-one", task_ref: str = "task-one") -> dict[str, str]:
    return {
        "principal_binding_digest": BINDING_DIGEST,
        "project_id": project_id,
        "task_ref": task_ref,
    }


def _event(
    *,
    project_id: str = "project-one",
    task_ref: str = "task-one",
    event_type: str = "TEST_RESULT",
) -> dict[str, object]:
    return {
        **_binding(project_id=project_id, task_ref=task_ref),
        "event_family": "EXECUTION",
        "event_type": event_type,
        "observed_at": "2026-09-05T01:00:00+00:00",
        "evidence_refs": [],
        "bounded_payload": {"status": "FAILED", "suite": "runtime"},
    }


class _InterleavingConnection:
    """Run one concurrent append between the window's two SELECT statements."""

    def __init__(self, connection: Any, interleave: Any) -> None:
        self._connection = connection
        self._interleave = interleave
        self._execute_count = 0

    def execute(self, query: Any, params: Any = None) -> Any:
        self._execute_count += 1
        if self._execute_count == 2:
            self._interleave()
        return self._connection.execute(query, params)


class _InterleavingDatabase:
    def __init__(self, database: Database, interleave: Any) -> None:
        self._database = database
        self._interleave = interleave

    @contextmanager
    def connection(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        with self._database.connection(*args, **kwargs) as connection:
            yield _InterleavingConnection(connection, self._interleave)


@pytest.mark.integration
@pytest.mark.security
def test_append_window_idempotency_scope_revocation_and_audit(host_event_app) -> None:  # type: ignore[no-untyped-def]
    client = host_event_app.test_client()
    nonce = uuid4().hex
    project_id = f"project-one-{nonce}"
    task_ref = f"task-one-{nonce}"
    evidence = client.post(
        "/v1/evidence",
        headers=_headers(f"host-event-evidence-{uuid4()}"),
        json={
            "source_type": "AGENT_EVENT",
            "source_ref": f"host-event://{uuid4()}",
            "subject_id": "host-event-test",
            "observed_at": "2026-09-05T01:00:00+00:00",
            "content": f"The user changed task requirement {nonce}.",
            "permission_snapshot": {
                "readable": True,
                "project_ids": [project_id],
            },
        },
    )
    assert evidence.status_code == 201
    evidence_id = evidence.json["evidence_id"]

    dialogue = {
        **_binding(project_id=project_id, task_ref=task_ref),
        "event_family": "DIALOGUE",
        "event_type": "MESSAGE",
        "observed_at": "2026-09-05T01:00:00+00:00",
        "evidence_refs": [evidence_id],
        "bounded_payload": {"role": "USER"},
    }
    operation_id = f"host-event-dialogue-{uuid4()}"
    appended = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=dialogue,
    )
    assert appended.status_code == 201
    assert appended.json["schema_version"] == "host-execution-event-v1"
    assert appended.json["event"]["evidence_refs"] == [evidence_id]
    first_position = appended.json["event"]["position"]

    replayed = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=dialogue,
    )
    assert replayed.status_code == 200
    assert replayed.json["replayed"] is True
    assert replayed.json["event"]["event_id"] == appended.json["event"]["event_id"]

    conflict = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json={**dialogue, "bounded_payload": {"role": "ASSISTANT"}},
    )
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "OPERATION_CONFLICT"

    # A different binding consumes a global position but is not visible in this task window.
    other = client.post(
        "/v1/host-events/append",
        headers=_headers(f"host-event-other-{uuid4()}"),
        json=_event(project_id=f"project-two-{nonce}", task_ref=f"task-two-{nonce}"),
    )
    assert other.status_code == 201
    second = client.post(
        "/v1/host-events/append",
        headers=_headers(f"host-event-second-{uuid4()}"),
        json=_event(
            project_id=project_id,
            task_ref=task_ref,
            event_type="FILES_CHANGED",
        ),
    )
    assert second.status_code == 201
    assert second.json["event"]["position"] > first_position + 1

    window = client.post(
        "/v1/host-events/window",
        headers=_headers(),
        json={
            **_binding(project_id=project_id, task_ref=task_ref),
            "after_position": 0,
            "limit": 10,
        },
    )
    assert window.status_code == 200
    assert [item["event_id"] for item in window.json["events"]] == [
        appended.json["event"]["event_id"],
        second.json["event"]["event_id"],
    ]
    assert window.json["visible_high_watermark"] == second.json["event"]["position"]
    assert window.json["next_position"] == second.json["event"]["position"]
    assert window.json["has_more"] is False

    next_window = client.post(
        "/v1/host-events/window",
        headers=_headers(),
        json={
            **_binding(project_id=project_id, task_ref=task_ref),
            "after_position": first_position,
            "limit": 1,
        },
    )
    assert next_window.status_code == 200
    assert [item["event_id"] for item in next_window.json["events"]] == [
        second.json["event"]["event_id"]
    ]

    revoked = client.post(
        f"/v1/evidence/{evidence_id}/revoke",
        headers=_headers(f"host-event-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoked.status_code == 202
    after_revoke = client.post(
        "/v1/host-events/window",
        headers=_headers(),
        json={
            **_binding(project_id=project_id, task_ref=task_ref),
            "after_position": 0,
            "limit": 10,
        },
    )
    first = after_revoke.json["events"][0]
    assert first["evidence_refs"] == []
    assert first["warnings"] == [
        {"code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE", "evidence_id": evidence_id}
    ]

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    event_id = UUID(appended.json["event"]["event_id"])
    with psycopg.connect(owner_url) as owner:
        audit_count = owner.execute(
            """
            SELECT count(*) FROM milai.operational_event
            WHERE event_type IN (
              'HOST_EXECUTION_EVENT_APPENDED',
              'HOST_EXECUTION_EVENT_WINDOW_READ'
            )
              AND tenant_id = %s
            """,
            (TENANT_ID,),
        ).fetchone()[0]
        assert audit_count >= 5
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="IMMUTABLE_HOST_EXECUTION_EVENT",
        ):
            owner.execute(
                "UPDATE milai.host_execution_event SET event_type = 'OTHER' "
                "WHERE event_id = %s",
                (event_id,),
            )

    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    other_actor = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    with psycopg.connect(api_url) as api:
        api.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
        api.execute("SELECT set_config('milai.actor_id', %s, false)", (str(other_actor),))
        visible = api.execute(
            "SELECT count(*) FROM milai.host_execution_event WHERE event_id = %s",
            (event_id,),
        ).fetchone()[0]
    assert visible == 0


@pytest.mark.integration
def test_window_watermark_and_rows_share_one_repeatable_read_snapshot(
    host_event_app,
) -> None:  # type: ignore[no-untyped-def]
    client = host_event_app.test_client()
    nonce = uuid4().hex
    project_id = f"project-window-{nonce}"
    task_ref = f"task-window-{nonce}"
    first = client.post(
        "/v1/host-events/append",
        headers=_headers(f"host-event-window-first-{uuid4()}"),
        json=_event(
            project_id=project_id,
            task_ref=task_ref,
            event_type="FIRST_EVENT",
        ),
    )
    assert first.status_code == 201
    first_position = first.json["event"]["position"]
    appended_during_read: dict[str, object] = {}

    def append_between_selects() -> None:
        concurrent = client.post(
            "/v1/host-events/append",
            headers=_headers(f"host-event-window-concurrent-{uuid4()}"),
            json=_event(
                project_id=project_id,
                task_ref=task_ref,
                event_type="CONCURRENT_EVENT",
            ),
        )
        assert concurrent.status_code == 201
        appended_during_read.update(concurrent.json["event"])

    database = cast(Database, host_event_app.extensions["milai.database"])
    interleaving_database = cast(
        Database,
        _InterleavingDatabase(database, append_between_selects),
    )
    repository = HostExecutionEventRepository(interleaving_database)
    request = HostExecutionEventWindowRequest.model_validate(
        {
            **_binding(project_id=project_id, task_ref=task_ref),
            "after_position": 0,
            "limit": 10,
        }
    )
    result = repository.read_window(SessionContext(TENANT_ID, ACTOR_ID), request)

    assert appended_during_read["position"] > first_position
    assert result.visible_high_watermark == first_position
    assert [event.position for event in result.events] == [first_position]
    assert result.next_position <= result.visible_high_watermark

    later = client.post(
        "/v1/host-events/window",
        headers=_headers(),
        json={
            **_binding(project_id=project_id, task_ref=task_ref),
            "after_position": 0,
            "limit": 10,
        },
    )
    assert later.status_code == 200
    assert [event["position"] for event in later.json["events"]] == [
        first_position,
        appended_during_read["position"],
    ]
    assert later.json["visible_high_watermark"] == appended_during_read["position"]


@pytest.mark.integration
def test_public_operation_id_is_namespaced_by_host_binding(host_event_app) -> None:  # type: ignore[no-untyped-def]
    client = host_event_app.test_client()
    nonce = uuid4().hex
    operation_id = f"shared-public-operation-{nonce}"
    first_event = {
        **_event(project_id=f"project-{nonce}", task_ref=f"task-{nonce}"),
        "principal_binding_digest": "b" * 64,
    }
    second_event = {
        **first_event,
        "principal_binding_digest": "c" * 64,
    }

    first = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=first_event,
    )
    second = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=second_event,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json["event"]["event_id"] != second.json["event"]["event_id"]

    first_replay = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=first_event,
    )
    second_replay = client.post(
        "/v1/host-events/append",
        headers=_headers(operation_id),
        json=second_event,
    )
    assert first_replay.status_code == 200
    assert second_replay.status_code == 200
    assert first_replay.json["replayed"] is True
    assert second_replay.json["replayed"] is True
    assert first_replay.json["event"]["event_id"] == first.json["event"]["event_id"]
    assert second_replay.json["event"]["event_id"] == second.json["event"]["event_id"]


@pytest.mark.integration
def test_host_execution_event_migration_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_host_event_roundtrip_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    signature = (
        "milai.append_host_execution_event(uuid,uuid,text,text,text,text,text,"
        "timestamp with time zone,jsonb,uuid[],text,text)"
    )
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0050_host_cognitive_state")
        with psycopg.connect(target_url) as owner:
            assert owner.execute(
                "SELECT to_regclass('milai.host_execution_event'), to_regprocedure(%s)",
                (signature,),
            ).fetchone() == (None, None)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            upgraded = owner.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.host_execution_event') IS NOT NULL,
                       to_regprocedure(%s) IS NOT NULL,
                       has_function_privilege('milai_api', %s, 'EXECUTE'),
                       has_table_privilege('milai_api', 'milai.host_execution_event', 'INSERT')
                """,
                (signature, signature),
            ).fetchone()
        assert upgraded == ("0056_host_notes", True, True, True, False)

        command.downgrade(config, "0050_host_cognitive_state")
        with psycopg.connect(target_url) as owner:
            downgraded = owner.execute(
                "SELECT (SELECT version_num FROM alembic_version), "
                "to_regclass('milai.host_execution_event'), to_regprocedure(%s)",
                (signature,),
            ).fetchone()
        assert downgraded == ("0050_host_cognitive_state", None, None)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            reupgraded = owner.execute("SELECT version_num FROM alembic_version").fetchone()
        assert reupgraded == ("0056_host_notes",)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
