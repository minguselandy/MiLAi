from __future__ import annotations

import json
import time
from contextlib import ExitStack
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from support.working_state import ACTOR_ID, API_TOKEN, _binding, _headers, _url

from milai.api import create_app
from milai.config import RuntimeSettings
from milai.persistence import Database, SessionContext
from milai.persistence.database import DatabaseCapacityError

pytestmark = pytest.mark.integration


def _settings(tmp_path, **overrides) -> RuntimeSettings:
    return RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(), local_actor_id=ACTOR_ID, api_token=API_TOKEN,
        causal_token_secret="tenant-capacity-secret-at-least-32-characters",
        database_pool_min_size=2, database_pool_max_size=2,
        database_pool_max_waiting=2, database_connect_timeout_seconds=1,
        **overrides,
    )


@pytest.mark.integration
def test_unpartitioned_pool_allows_one_tenant_to_exhaust_peer_capacity(tmp_path) -> None:
    """Reproduce the existing interference; not a fairness PASS."""
    command.upgrade(Config("alembic.ini"), "head")
    settings = _settings(tmp_path)
    database = Database(settings)
    noisy = SessionContext(settings.tenant_id, ACTOR_ID)
    peer = SessionContext(uuid4(), ACTOR_ID)
    try:
        with ExitStack() as held:
            for _ in range(2):
                held.enter_context(database.connection(noisy))
            with pytest.raises(DatabaseCapacityError) as error, database.connection(peer):
                pytest.fail("peer should be blocked while both physical connections are held")
            assert error.value.reason == "POOL_WAIT_TIMEOUT"
        with database.connection(peer) as connection:
            assert connection.execute("SELECT current_setting('milai.tenant_id')").fetchone() == (
                str(peer.tenant_id),)
    finally:
        database.close()


@pytest.mark.integration
def test_tenant_cap_keeps_peer_state_available_and_rejects_before_commit(tmp_path) -> None:
    command.upgrade(Config("alembic.ini"), "head")
    settings = _settings(tmp_path, database_pool_max_per_tenant=1)
    peer_settings = settings.model_copy(update={"tenant_id": uuid4()})
    database = Database(settings)
    steward = Database(settings, dsn=settings.steward_database_dsn)
    apps = [create_app(s, database=database, steward_database=steward)
            for s in (settings, peer_settings)]
    binding = {**_binding(), "scope_ref": "same-task-" + uuid4().hex}
    bodies = [{**binding, "expected_version": 0,
               "payload": {"first": "TENANT_PRIVATE_" + str(i), "text": " 空白\n\t",
                           "last": "END_" + str(i)}} for i in range(2)]

    def request(index, path, body, operation=None):
        with apps[index].test_client() as client:
            return client.post(path, json=body, headers=_headers(operation))

    try:
        seeds = [request(i, "/v1/working-state/update", body, "seed-" + uuid4().hex)
                 for i, body in enumerate(bodies)]
        assert all(s.status_code == 201 for s in seeds)
        assert seeds[0].json["state_id"] != seeds[1].json["state_id"]
        update = {**bodies[0], "state_id": seeds[0].json["state_id"], "expected_version": 1,
                  "payload": {**bodies[0]["payload"], "revision": "next"}}
        operation = "retry-after-admission-" + uuid4().hex
        with database.connection(SessionContext(settings.tenant_id, ACTOR_ID)):
            started = time.monotonic()
            rejected = request(0, "/v1/working-state/update", update, operation)
            assert time.monotonic() - started < 0.5
            assert rejected.status_code == 503
            assert rejected.json["error"]["code"] == "DATABASE_CAPACITY_EXCEEDED"
            assert rejected.json["error"]["details"] == {"reason": "TENANT_CONCURRENCY_LIMIT"}
            assert "TENANT_PRIVATE_0" not in json.dumps(rejected.json)
            # Changing actor within the same tenant cannot claim another tenant's share.
            with pytest.raises(DatabaseCapacityError) as error, database.connection(
                SessionContext(settings.tenant_id, uuid4()),
            ):
                pytest.fail("actor change must not bypass tenant admission")
            assert error.value.reason == "TENANT_CONCURRENCY_LIMIT"
            assert database._pool.get_stats()["requests_waiting"] == 0
            peer = request(1, "/v1/working-state/get", binding)
            assert peer.status_code == 200 and peer.json["payload"] == bodies[1]["payload"]
            assert "TENANT_PRIVATE_0" not in json.dumps(peer.json)
            with apps[0].test_client() as client:
                invalid = client.post("/v1/working-state/get", json=binding,
                                      headers={"Authorization": "Bearer invalid"})
                assert invalid.status_code == 401
        unchanged = request(0, "/v1/working-state/get", binding)
        assert unchanged.json["state_version_id"] == seeds[0].json["state_version_id"]
        updated = request(0, "/v1/working-state/update", update, operation)
        assert updated.status_code == 200 and updated.json["version"] == 2
        assert updated.json["payload"] == update["payload"]
        replay = request(0, "/v1/working-state/update", update, operation)
        assert replay.json["replayed"] and (
            replay.json["state_version_id"] == updated.json["state_version_id"])
        assert database._tenant_active == {}
    finally:
        database.close()
        steward.close()


@pytest.mark.integration
@pytest.mark.parametrize("exception", [RuntimeError, KeyboardInterrupt])
def test_tenant_slot_is_released_after_transaction_failure_or_cancellation(
    tmp_path, exception,
) -> None:
    settings = _settings(tmp_path, database_pool_max_per_tenant=1)
    database = Database(settings)
    context = SessionContext(settings.tenant_id, ACTOR_ID)
    try:
        with pytest.raises(exception), database.connection(context) as connection:
            connection.execute("SELECT 1")
            raise exception("controlled interruption")
        with database.connection(context) as connection:
            assert connection.execute("SELECT current_setting('milai.tenant_id')").fetchone() == (
                str(context.tenant_id),)
        assert database._tenant_active == {}
    finally:
        database.close()


@pytest.mark.integration
def test_tenant_slot_is_released_when_global_pool_acquisition_times_out(tmp_path) -> None:
    settings = _settings(tmp_path, database_pool_max_per_tenant=1)
    database = Database(settings)
    waiting = SessionContext(settings.tenant_id, ACTOR_ID)
    try:
        with ExitStack() as held:
            for _ in range(2):
                held.enter_context(database.connection(SessionContext(uuid4(), ACTOR_ID)))
            with pytest.raises(DatabaseCapacityError) as error, database.connection(waiting):
                pytest.fail("physical pool is occupied by two other tenants")
            assert error.value.reason == "POOL_WAIT_TIMEOUT"
            assert waiting.tenant_id not in database._tenant_active
        with database.connection(waiting) as connection:
            assert connection.execute("SELECT 1").fetchone() == (1,)
        assert database._tenant_active == {}
    finally:
        database.close()
