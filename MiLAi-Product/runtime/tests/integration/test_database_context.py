from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from support.working_state import ACTOR_ID, API_TOKEN, _url

from milai.config import RuntimeSettings
from milai.persistence import Database, DatabaseRoleError, SessionContext

pytestmark = pytest.mark.integration


@pytest.fixture
def context_database(tmp_path):
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=uuid4(),
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="context-test-secret-at-least-32-characters",
        database_pool_min_size=1,
        database_pool_max_size=1,
    )
    database = Database(settings)
    database.open()
    try:
        yield database
    finally:
        database.close()


@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_local_context_is_complete_and_does_not_leak_on_pool_reuse(
    context_database, monkeypatch, outcome
):
    database = context_database
    first, second = SessionContext(uuid4(), uuid4()), SessionContext(uuid4(), uuid4())
    installed = []
    execute = psycopg.Connection.execute

    def observed(connection, query, *args, **kwargs):
        if isinstance(query, str) and "set_config('milai.tenant_id'" in query:
            installed.append((query, args[0]))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", observed)
    seen = []
    failure = KeyboardInterrupt if outcome == "cancel" else ValueError

    def first_transaction():
        with database.connection(first, read_only=True, isolation_level="REPEATABLE READ") as conn:
            seen.append(conn.execute(
                "SELECT pg_backend_pid(), current_setting('milai.tenant_id'), "
                "current_setting('milai.actor_id'), current_setting('transaction_read_only'), "
                "current_setting('transaction_isolation')"
            ).fetchone())
            if outcome != "success":
                raise failure("body failure")

    if outcome == "success":
        first_transaction()
    else:
        with pytest.raises(failure):
            first_transaction()
    assert seen[0][1:] == (str(first.tenant_id), str(first.actor_id), "on", "repeatable read")
    with database.connection() as conn:
        row = conn.execute(
            "SELECT pg_backend_pid(), current_setting('milai.tenant_id', true), "
            "current_setting('milai.actor_id', true)"
        ).fetchone()
        assert row[0] == seen[0][0]
        assert row[1] in (None, "") and row[2] in (None, "")
    with database.connection(second) as conn:
        row = conn.execute(
            "SELECT pg_backend_pid(), current_setting('milai.tenant_id'), "
            "current_setting('milai.actor_id')"
        ).fetchone()
        assert row == (seen[0][0], str(second.tenant_id), str(second.actor_id))
    assert len(installed) == 2
    assert all("set_config('milai.actor_id'" in query for query, _ in installed)
    assert [params for _, params in installed] == [
        (str(first.tenant_id), str(first.actor_id)),
        (str(second.tenant_id), str(second.actor_id)),
    ]


@pytest.mark.integration
def test_role_attestation_rejects_before_context_installation(context_database, monkeypatch):
    database = context_database
    execute = psycopg.Connection.execute
    installed = []

    def observed(connection, query, *args, **kwargs):
        if isinstance(query, str) and "set_config('milai." in query:
            installed.append(query)
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", observed)
    # The physical API role is unchanged; require a different role after open
    # to prove each transaction re-attests before installing identity.
    monkeypatch.setattr(database, "_expected_role", "milai_worker")
    with pytest.raises(DatabaseRoleError, match="expected least-privilege"):
        with database.connection(SessionContext(uuid4(), uuid4())):
            pytest.fail("role mismatch must not yield a business connection")
    assert installed == []
