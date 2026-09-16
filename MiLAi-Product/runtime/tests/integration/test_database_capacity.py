from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from test_host_cognitive_state import ACTOR_ID, API_TOKEN, _binding, _headers, _url

from milai.api import create_app
from milai.config import RuntimeSettings
from milai.persistence import Database, SessionContext


@pytest.mark.integration
def test_bounded_waiters_reject_without_scope_leak_and_recover_after_release(tmp_path) -> None:
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="capacity-test-secret-at-least-32-characters",
        database_pool_min_size=1,
        database_pool_max_size=1,
        database_pool_max_waiting=1,
        database_connect_timeout_seconds=2,
    )
    database = Database(settings)
    steward = Database(settings, dsn=settings.steward_database_dsn)
    app = create_app(settings, database=database, steward_database=steward)
    binding = {**_binding(), "scope_ref": "capacity-scope-" + uuid4().hex}
    payload = {
        **binding,
        "expected_version": 0,
        "payload": {"first": "retained", "last": "private-canary"},
    }

    def request(path, body, *, headers=None):
        with app.test_client() as client:
            return client.post(path, json=body, headers=headers or _headers())

    try:
        database.open()
        steward.open()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with database.connection(SessionContext(settings.tenant_id, ACTOR_ID)):
                waiting = executor.submit(request, "/v1/working-state/get", binding)
                deadline = time.monotonic() + 1
                while database._pool.get_stats()["requests_waiting"] != 1:
                    assert time.monotonic() < deadline and not waiting.done()
                    time.sleep(0.005)
                begin = time.monotonic()
                rejected = request(
                    "/v1/working-state/update",
                    payload,
                    headers={**_headers(), "Idempotency-Key": "same-after-capacity"},
                )
                assert time.monotonic() - begin < 1, "queue-full must not wait for the 2s timeout"
                assert rejected.status_code == 503
                assert rejected.json["error"] == {
                    "code": "DATABASE_CAPACITY_EXCEEDED",
                    "message": "Database connection capacity is temporarily unavailable.",
                    "retryable": True,
                    "details": {"reason": "POOL_QUEUE_FULL"},
                }
                rendered = json.dumps(rejected.json)
                assert "private-canary" not in rendered and API_TOKEN not in rendered
                assert binding["scope_ref"] not in rendered
                denied = request(
                    "/v1/working-state/get", binding, headers={"Authorization": "Bearer invalid"}
                )
                assert denied.status_code == 401
                # An independent pool remains usable while API capacity is occupied.
                with steward.connection(SessionContext(settings.tenant_id, ACTOR_ID)) as connection:
                    assert connection.execute(
                        "SELECT current_setting('milai.tenant_id')"
                    ).fetchone() == (str(settings.tenant_id),)
                assert database._pool.get_stats()["requests_waiting"] == 1
            first_read = waiting.result(timeout=3)
            assert first_read.status_code == 200 and first_read.json["status"] == "ABSENT"
        saved = request(
            "/v1/working-state/update",
            payload,
            headers={**_headers(), "Idempotency-Key": "same-after-capacity"},
        )
        assert saved.status_code == 201 and saved.json["version"] == 1
        replay = request(
            "/v1/working-state/update",
            payload,
            headers={**_headers(), "Idempotency-Key": "same-after-capacity"},
        )
        assert replay.status_code == 200 and replay.json["replayed"]
        assert replay.json["state_version_id"] == saved.json["state_version_id"]
        head = request("/v1/working-state/get", binding)
        assert head.json["payload"] == payload["payload"]
        peer = request(
            "/v1/working-state/get",
            {**binding, "principal_binding_digest": hashlib.sha256(b"other-host").hexdigest()},
        )
        assert peer.json["status"] == "ABSENT" and peer.json["payload"] == {}
    finally:
        database.close()
        steward.close()
