from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from test_host_cognitive_state import ACTOR_ID, API_TOKEN, TENANT_ID, _binding, _headers, _url

from milai.api import create_app
from milai.config import RuntimeSettings
from milai.observability.logging import JsonFormatter
from milai.observability.metrics import OperationTimer, request_operation_timer
from milai.persistence import Database, SessionContext


@pytest.mark.integration
def test_real_pool_wait_timeout_and_request_context_are_measured_without_payload(
    tmp_path,
    monkeypatch,
) -> None:
    _url("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="timing-secret-with-at-least-32-characters",
        database_pool_min_size=1,
        database_pool_max_size=1,
        database_connect_timeout_seconds=0.4,
        request_timing_enabled=True,
    )
    database = Database(settings)
    steward = Database(settings, dsn=settings.steward_database_dsn)
    entered = Event()
    original_getconn = database._pool.getconn

    def getconn(*args, **kwargs):
        entered.set()
        return original_getconn(*args, **kwargs)

    monkeypatch.setattr(database._pool, "getconn", getconn)
    app = create_app(settings, database=database, steward_database=steward)
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("milai.api.app")
    # Alembic fileConfig can disable an already-imported logger in a full run.
    # Enable only this test's capture, then restore its original state.
    monkeypatch.setattr(logger, "disabled", False)
    original_level = logger.level
    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    binding = {**_binding(), "scope_ref": "payload-canary-" + str(uuid4())}

    def request_state(request_id):
        assert request_operation_timer.get() is None
        with app.test_client() as client:
            response = client.post(
                "/v1/working-state/get",
                json=binding,
                headers={
                    **_headers(),
                    "X-Request-ID": request_id,
                },
            )
        assert request_operation_timer.get() is None
        return response

    def observation(request_id):
        matches = [
            r
            for r in records
            if r.msg == "runtime_request_timing" and getattr(r, "request_id", None) == request_id
        ]
        assert len(matches) == 1
        rendered = JsonFormatter().format(matches[0])
        assert binding["scope_ref"] not in rendered and API_TOKEN not in rendered
        assert request_id not in rendered
        value = json.loads(rendered)
        assert (
            value["request_id_fingerprint"] == hashlib.sha256(request_id.encode()).hexdigest()[:16]
        )
        return value["safe_metadata"]

    try:
        database.open()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.connection(SessionContext(TENANT_ID, ACTOR_ID)):
                entered.clear()
                pending = pool.submit(request_state, "request-with-pool-wait")
                assert entered.wait(2) and not pending.done()
                time.sleep(0.08)
            response = pending.result(timeout=2)
            assert response.status_code == 200 and response.json["status"] == "ABSENT"
            value = observation("request-with-pool-wait")
            assert value["durations_ms"]["db_pool_acquire_ms"] >= 50
            assert value["counts"] == {
                "db_pool_acquire_ms": 1,
                "db_connection_hold_ms": 1,
                "db_transaction_enter_ms": 1,
                "db_transaction_exit_ms": 1,
            }
            durations = value["durations_ms"]
            assert durations["db_connection_hold_ms"] >= (
                durations["db_transaction_enter_ms"] + durations["db_transaction_exit_ms"]
            )
            assert value["application_ms"] >= value["durations_ms"]["db_pool_acquire_ms"]

            with database.connection(SessionContext(TENANT_ID, ACTOR_ID)):
                response = pool.submit(request_state, "request-pool-timeout").result(timeout=2)
            assert response.status_code == 503
            assert response.json["error"]["code"] == "DATABASE_CAPACITY_EXCEEDED"
            assert response.json["error"]["details"] == {"reason": "POOL_WAIT_TIMEOUT"}
            failed = observation("request-pool-timeout")
            assert failed["counts"] == {"db_pool_acquire_ms": 1}
            assert failed["durations_ms"]["db_pool_acquire_ms"] >= 350
            assert "db_connection_hold_ms" not in failed["durations_ms"]
            assert (
                pool.submit(request_state, "request-after-timeout").result(timeout=2).status_code
                == 200
            )
        assert request_operation_timer.get() is None
        disabled = create_app(
            settings.model_copy(update={"request_timing_enabled": False}),
            database=database,
            steward_database=steward,
        )
        before = sum(r.msg == "runtime_request_timing" for r in records)
        with disabled.test_client() as client:
            response = client.post("/v1/working-state/get", json=binding, headers=_headers())
            assert response.status_code == 200 and response.json["status"] == "ABSENT"
        assert sum(r.msg == "runtime_request_timing" for r in records) == before
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        handler.close()
        database.close()
        steward.close()


@pytest.mark.integration
@pytest.mark.parametrize("rollback", [False, True])
def test_measured_real_transaction_preserves_commit_and_rollback(rollback, tmp_path):
    _url("MILAI_MIGRATION_DATABASE_URL")
    command.upgrade(Config("alembic.ini"), "head")
    database = Database(
        RuntimeSettings(
            database_url=_url("MILAI_TEST_API_DATABASE_URL"),
            steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
            blob_root=tmp_path / "blobs",
            tenant_id=TENANT_ID,
            local_actor_id=ACTOR_ID,
            api_token=API_TOKEN,
            causal_token_secret="timing-secret-with-at-least-32-characters",
        )
    )
    context = SessionContext(TENANT_ID, ACTOR_ID)
    event_id = uuid4()
    timer = OperationTimer()
    failure = ValueError("rollback fixture")

    def write_event():
        token = request_operation_timer.set(timer)
        try:
            with database.connection(context) as connection:
                connection.execute(
                    """
                    INSERT INTO milai.operational_event (
                      tenant_id, event_id, event_type, safe_metadata, created_by_actor_id
                    ) VALUES (%s, %s, 'HOST_WORKING_STATE_ACCESSED', '{}'::jsonb, %s)
                    """,
                    (TENANT_ID, event_id, ACTOR_ID),
                )
                if rollback:
                    raise failure
        finally:
            request_operation_timer.reset(token)

    try:
        if rollback:
            with pytest.raises(ValueError) as caught:
                write_event()
            assert caught.value is failure
        else:
            write_event()
        assert timer.counts["db_transaction_enter_ms"] == 1
        assert timer.counts["db_transaction_exit_ms"] == 1
        assert request_operation_timer.get() is None
        with database.connection(context) as connection:
            row = connection.execute(
                "SELECT count(*) FROM milai.operational_event WHERE event_id = %s",
                (event_id,),
            ).fetchone()
            assert row == (0 if rollback else 1,)
    finally:
        database.close()
