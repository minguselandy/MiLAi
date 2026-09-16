from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.operations.smoke import _create_database, _database_url, _drop_database
from milai.persistence import Database

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
API_TOKEN = "test-token-with-at-least-32-characters"
BINDING_DIGEST = "a" * 64


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def working_state_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    with _working_state_application(tmp_path) as app:
        yield app


@pytest.fixture
def isolated_working_state_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    database = "milai_smoke_" + uuid4().hex[:20]
    _create_database(owner_url, database)
    try:
        for key in ["MILAI_MIGRATION_DATABASE_URL", "MILAI_TEST_API_DATABASE_URL",
                    "MILAI_TEST_STEWARD_DATABASE_URL"]:
            monkeypatch.setenv(key, _database_url(_url(key), database))
        with _working_state_application(tmp_path) as app:
            yield app
    finally:
        assert _drop_database(owner_url, database)["status"] == "PASS"


@contextmanager
def _working_state_application(tmp_path: Path):  # type: ignore[no-untyped-def]
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


def _binding(project_id: str = "project-one") -> dict[str, object]:
    return {
        "principal_binding_digest": BINDING_DIGEST,
        "project_id": project_id,
        "scope_type": "TASK",
        "scope_ref": "task-one",
    }


@pytest.mark.integration
@pytest.mark.security
def test_large_reference_set_preserves_disclosure_and_migration_rollback(
    isolated_working_state_app,
) -> None:  # type: ignore[no-untyped-def]
    client = isolated_working_state_app.test_client()
    binding = {**_binding(), "scope_ref": f"capacity-{uuid4()}"}

    def evidence(project: str) -> str:
        response = client.post(
            "/v1/evidence", headers=_headers(f"capacity-evidence-{uuid4()}"),
            json={"source_type": "RUNTIME_OBSERVATION", "source_ref": f"test://{uuid4()}",
                  "subject_id": "capacity", "observed_at": "2026-09-07T00:00:00Z",
                  "content": "Allowed observation", "permission_snapshot": {
                      "readable": True, "project_ids": [project]}},
        )
        assert response.status_code == 201
        return str(response.json["evidence_id"])

    refs = sorted(evidence("project-one") for _ in range(1024))
    request = {**binding, "expected_version": 0, "payload": {"evidence_refs": refs}}
    created = client.post("/v1/working-state/update", headers=_headers(f"capacity-{uuid4()}"),
                          json=request)
    assert created.status_code == 201
    assert created.json["payload"] == request["payload"]
    fetched = client.post("/v1/working-state/get", headers=_headers(), json=binding)
    assert fetched.json["payload"] == request["payload"]

    command.downgrade(Config("alembic.ini"), "0054_intra_source_shadow")
    try:
        retained = client.post("/v1/working-state/get", headers=_headers(), json=binding)
        assert retained.json["payload"] == request["payload"]
        refused = client.post("/v1/working-state/update", headers=_headers(f"old-{uuid4()}"),
                              json={**request, "state_id": created.json["state_id"],
                                    "expected_version": 1})
        assert refused.status_code == 400
    finally:
        command.upgrade(Config("alembic.ini"), "head")

    foreign = evidence("other-project")
    denied = client.post("/v1/working-state/update", headers=_headers(f"scope-{uuid4()}"),
                         json={**request, "state_id": created.json["state_id"],
                               "expected_version": 1,
                               "payload": {"evidence_refs": [*refs[:-1], foreign]}})
    assert denied.status_code == 409
    assert denied.json["error"]["code"] == "EVIDENCE_REFERENCE_INVALID"
    revoked = client.post(f"/v1/evidence/{refs[-1]}/revoke",
                          headers=_headers(f"revoke-{uuid4()}"),
                          json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"})
    assert revoked.status_code == 202
    hidden = client.post("/v1/working-state/get", headers=_headers(), json=binding)
    assert hidden.json["payload_withheld"] is True
    assert hidden.json["payload"] == {}
    assert hidden.json["warnings"] == [
        {"code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE", "evidence_id": refs[-1]}]
    rejected = client.post("/v1/working-state/update", headers=_headers(f"stale-{uuid4()}"),
                           json={**request, "state_id": created.json["state_id"],
                                 "expected_version": 1})
    assert rejected.status_code == 409
    assert rejected.json["error"]["code"] == "EVIDENCE_REFERENCE_INVALID"


@pytest.mark.integration
def test_public_payload_roundtrip_preserves_content_and_rejects_changed_replay(
    working_state_app,
) -> None:  # type: ignore[no-untyped-def]
    client = working_state_app.test_client()
    binding = {**_binding(), "scope_ref": f"fidelity-{uuid4()}"}
    payload = {"text": '  中文 "quote"\r\n\tcode\n\n',
               " key": [" value ", {"nested": "\t\n"}], "key": {"empty": ""}}
    request = {**binding, "expected_version": 0, "payload": payload}
    operation = f"fidelity-{uuid4()}"
    created = client.post("/v1/working-state/update", headers=_headers(operation), json=request)
    assert created.status_code == 201
    assert created.json["payload"] == payload
    fetched = client.post("/v1/working-state/get", headers=_headers(), json=binding)
    assert fetched.json["payload"] == payload
    replay = client.post("/v1/working-state/update", headers=_headers(operation), json=request)
    assert replay.status_code == 200 and replay.json["replayed"] is True
    assert replay.json["payload"] == payload
    changed = {**payload, "text": payload["text"].strip()}
    conflict = client.post("/v1/working-state/update", headers=_headers(operation),
                           json={**request, "payload": changed})
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "OPERATION_CONFLICT"
    updated = client.post("/v1/working-state/update", headers=_headers(f"fidelity-{uuid4()}"),
                          json={**request, "state_id": created.json["state_id"],
                                "expected_version": 1, "payload": changed})
    assert updated.status_code == 200 and updated.json["version"] == 2
    assert updated.json["state_digest"] != created.json["state_digest"]


@pytest.mark.integration
@pytest.mark.security
def test_append_only_cas_scope_evidence_revocation_and_audit(working_state_app) -> None:  # type: ignore[no-untyped-def]
    client = working_state_app.test_client()
    absent = client.post(
        "/v1/working-state/get",
        headers=_headers(),
        json=_binding(),
    )
    assert absent.status_code == 200
    assert absent.json["status"] == "ABSENT"
    assert absent.json["authority"] == "HOST_WORKING"

    evidence = client.post(
        "/v1/evidence",
        headers=_headers(f"hc-evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"integration://{uuid4()}",
            "subject_id": "host-cognitive-test",
            "observed_at": "2026-09-04T10:00:00+08:00",
            "content": "Product-10 showed budget displacement.",
            "permission_snapshot": {
                "readable": True,
                "project_ids": ["project-one"],
            },
        },
    )
    assert evidence.status_code == 201
    evidence_id = evidence.json["evidence_id"]
    create_payload = {
        **_binding(),
        "state_id": None,
        "expected_version": 0,
        "payload": {
            "task": {"active_goal": "implement Host cognition"},
            "known": [
                {
                    "text": "budget displacement was observed",
                    "basis": [{"evidence_id": evidence_id}],
                    "basis_relation": "HOST_ASSERTED",
                }
            ],
            "next_actions": ["test CAS"],
        },
    }
    operation_id = f"hc-create-{uuid4()}"
    created = client.post(
        "/v1/working-state/update",
        headers=_headers(operation_id),
        json=create_payload,
    )
    assert created.status_code == 201
    assert created.json["version"] == 1
    assert created.json["authority"] == "HOST_WORKING"
    state_id = created.json["state_id"]

    replayed = client.post(
        "/v1/working-state/update",
        headers=_headers(operation_id),
        json=create_payload,
    )
    assert replayed.status_code == 200
    assert replayed.json["state_id"] == state_id
    assert replayed.json["replayed"] is True

    operation_conflict = client.post(
        "/v1/working-state/update",
        headers=_headers(operation_id),
        json={
            **create_payload,
            "payload": {"task": {"active_goal": "different operation semantics"}},
        },
    )
    assert operation_conflict.status_code == 409
    assert operation_conflict.json["error"]["code"] == "OPERATION_CONFLICT"

    stale = client.post(
        "/v1/working-state/update",
        headers=_headers(f"hc-stale-{uuid4()}"),
        json={**create_payload, "state_id": state_id, "expected_version": 0},
    )
    assert stale.status_code == 400  # create/update shape fails before persistence

    wrong_project = client.post(
        "/v1/working-state/update",
        headers=_headers(f"hc-scope-{uuid4()}"),
        json={
            **create_payload,
            **_binding("other-project"),
            "state_id": state_id,
            "expected_version": 1,
        },
    )
    assert wrong_project.status_code == 403
    assert wrong_project.json["error"]["code"] == "HOST_WORKING_STATE_SCOPE_DENIED"

    updated = client.post(
        "/v1/working-state/update",
        headers=_headers(f"hc-update-{uuid4()}"),
        json={
            **create_payload,
            "state_id": state_id,
            "expected_version": 1,
            "payload": {**create_payload["payload"], "next_actions": ["done"]},
        },
    )
    assert updated.status_code == 200
    assert updated.json["version"] == 2

    late_replay = client.post(
        "/v1/working-state/update",
        headers=_headers(operation_id),
        json=create_payload,
    )
    assert late_replay.status_code == 200
    assert late_replay.json["replayed"] is True
    assert late_replay.json["version"] == 1
    assert late_replay.json["state_version_id"] == created.json["state_version_id"]
    assert late_replay.json["payload"]["next_actions"] == ["test CAS"]

    stale_version = client.post(
        "/v1/working-state/update",
        headers=_headers(f"hc-stale-version-{uuid4()}"),
        json={
            **create_payload,
            "state_id": state_id,
            "expected_version": 1,
        },
    )
    assert stale_version.status_code == 409
    assert stale_version.json["error"]["code"] == "STALE_WORKING_STATE"
    assert stale_version.json["error"]["details"]["current_version"] == 2

    revoked = client.post(
        f"/v1/evidence/{evidence_id}/revoke",
        headers=_headers(f"hc-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoked.status_code == 202
    fetched = client.post(
        "/v1/working-state/get", headers=_headers(), json=_binding()
    )
    assert fetched.status_code == 200
    assert fetched.json["payload"] == {}
    assert fetched.json["payload_withheld"] is True
    assert fetched.json["state_version_id"] == updated.json["state_version_id"]
    assert fetched.json["warnings"] == [
        {"code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE", "evidence_id": evidence_id}
    ]
    revoked_replay = client.post(
        "/v1/working-state/update", headers=_headers(operation_id), json=create_payload
    )
    assert revoked_replay.status_code == 200
    assert revoked_replay.json["replayed"] is True
    assert revoked_replay.json["state_version_id"] == created.json["state_version_id"]
    assert revoked_replay.json["payload"] == {}
    assert revoked_replay.json["payload_withheld"] is True
    assert revoked_replay.json["warnings"] == fetched.json["warnings"]
    rejected_reference = client.post(
        "/v1/working-state/update",
        headers=_headers(f"hc-revoked-ref-{uuid4()}"),
        json={
            **create_payload,
            "state_id": state_id,
            "expected_version": 2,
        },
    )
    assert rejected_reference.status_code == 409
    assert rejected_reference.json["error"]["code"] == "EVIDENCE_REFERENCE_INVALID"

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        versions = owner.execute(
            "SELECT count(*) FROM milai.host_cognitive_state_version WHERE state_id = %s",
            (UUID(state_id),),
        ).fetchone()[0]
        audit_events = owner.execute(
            """
            SELECT count(*) FROM milai.operational_event
            WHERE event_type IN (
              'HOST_WORKING_STATE_ACCESSED',
              'HOST_WORKING_STATE_VERSION_APPENDED'
            ) AND safe_metadata ->> 'state_id' = %s
            """,
            (state_id,),
        ).fetchone()[0]
    assert versions == 2
    assert audit_events >= 3

    with psycopg.connect(owner_url) as owner:
        owner.execute(
            """
            UPDATE milai.host_cognitive_state
            SET expires_at = CURRENT_TIMESTAMP - interval '1 second'
            WHERE state_id = %s
            """,
            (UUID(state_id),),
        )
    expired = client.post(
        "/v1/working-state/get", headers=_headers(), json=_binding()
    )
    assert expired.status_code == 200
    assert expired.json["status"] == "EXPIRED"
    assert expired.json["payload"] == {}

    with psycopg.connect(owner_url) as owner:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="IMMUTABLE_HOST_WORKING_HISTORY",
        ):
            owner.execute(
                """
                UPDATE milai.host_cognitive_state_version
                SET payload_json = '{"forbidden": true}'::jsonb
                WHERE state_id = %s
                """,
                (UUID(state_id),),
            )

    with psycopg.connect(owner_url) as owner:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="IMMUTABLE_HOST_WORKING_HISTORY",
        ):
            owner.execute(
                "DELETE FROM milai.host_cognitive_state_version WHERE state_id = %s",
                (UUID(state_id),),
            )

    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    with psycopg.connect(api_url) as api:
        api.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
        api.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute(
                "UPDATE milai.host_cognitive_state SET lifecycle = 'DELETED' WHERE state_id = %s",
                (UUID(state_id),),
            )

    audit_url = _url("MILAI_TEST_AUDIT_DATABASE_URL")
    with psycopg.connect(audit_url) as audit:
        audit.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
        audit.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            audit.execute(
                "SELECT payload_json FROM milai.host_cognitive_state_version WHERE state_id = %s",
                (UUID(state_id),),
            )

    other_tenant = UUID("22222222-2222-4222-8222-222222222222")
    with psycopg.connect(api_url) as api:
        api.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(other_tenant),))
        api.execute("SELECT set_config('milai.actor_id', %s, false)", (str(ACTOR_ID),))
        visible = api.execute(
            "SELECT count(*) FROM milai.host_cognitive_state WHERE state_id = %s",
            (UUID(state_id),),
        ).fetchone()[0]
    assert visible == 0

    other_actor = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    with psycopg.connect(api_url) as api:
        api.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
        api.execute("SELECT set_config('milai.actor_id', %s, false)", (str(other_actor),))
        visible = api.execute(
            "SELECT count(*) FROM milai.host_cognitive_state WHERE state_id = %s",
            (UUID(state_id),),
        ).fetchone()[0]
    assert visible == 0
