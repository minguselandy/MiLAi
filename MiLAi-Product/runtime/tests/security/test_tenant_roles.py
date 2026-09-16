from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest

from milai.config.settings import RuntimeSettings
from milai.persistence import Database, DatabaseRoleError, SessionContext

TENANT_ONE = UUID("11111111-1111-4111-8111-111111111111")
TENANT_TWO = UUID("22222222-2222-4222-8222-222222222222")
ACTOR_ONE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ACTOR_TWO = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _set_context(
    connection: psycopg.Connection[tuple[object, ...]], tenant: UUID, actor: UUID
) -> None:
    connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant),))
    connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(actor),))


@pytest.mark.integration
@pytest.mark.security
def test_api_role_cannot_read_or_insert_another_tenant() -> None:
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    event_id = uuid4()
    with psycopg.connect(api_url) as tenant_one:
        _set_context(tenant_one, TENANT_ONE, ACTOR_ONE)
        tenant_one.execute(
            """
            INSERT INTO milai.operational_event
              (tenant_id, event_id, event_type, created_by_actor_id)
            VALUES (%s, %s, 'SECURITY_TEST', %s)
            """,
            (TENANT_ONE, event_id, ACTOR_ONE),
        )

    with psycopg.connect(api_url) as tenant_two:
        _set_context(tenant_two, TENANT_TWO, ACTOR_TWO)
        assert (
            tenant_two.execute(
                "SELECT count(*) FROM milai.operational_event WHERE event_id = %s",
                (event_id,),
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tenant_two.execute(
                """
                INSERT INTO milai.operational_event
                  (tenant_id, event_id, event_type, created_by_actor_id)
                VALUES (%s, %s, 'CROSS_TENANT_ATTEMPT', %s)
                """,
                (TENANT_ONE, uuid4(), ACTOR_TWO),
            )


@pytest.mark.integration
@pytest.mark.security
def test_api_context_is_transaction_scoped_and_reset_on_pool_reuse(tmp_path) -> None:  # type: ignore[no-untyped-def]
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    settings = RuntimeSettings(
        database_url=api_url,
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ONE,
        local_actor_id=ACTOR_ONE,
        api_token="test-token-with-at-least-32-characters",
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    database = Database(settings)
    event_id = uuid4()
    try:
        with database.connection(SessionContext(TENANT_ONE, ACTOR_ONE)) as connection:
            connection.execute(
                """
                INSERT INTO milai.operational_event
                  (tenant_id, event_id, event_type, created_by_actor_id)
                VALUES (%s, %s, 'POOL_RESET_TEST', %s)
                """,
                (TENANT_ONE, event_id, ACTOR_ONE),
            )

        with database.connection(read_only=True) as connection:
            current_tenant = connection.execute(
                "SELECT current_setting('milai.tenant_id', true)"
            ).fetchone()[0]
            visible = connection.execute(
                "SELECT count(*) FROM milai.operational_event WHERE event_id = %s",
                (event_id,),
            ).fetchone()[0]
        assert current_tenant in (None, "")
        assert visible == 0

        with database.connection(
            SessionContext(TENANT_TWO, ACTOR_TWO), read_only=True
        ) as connection:
            visible_to_other_tenant = connection.execute(
                "SELECT count(*) FROM milai.operational_event WHERE event_id = %s",
                (event_id,),
            ).fetchone()[0]
        assert visible_to_other_tenant == 0
    finally:
        database.close()


@pytest.mark.integration
@pytest.mark.security
def test_runtime_roles_have_minimal_cluster_attributes() -> None:
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        rows = owner.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolbypassrls
            FROM pg_roles
            WHERE rolname IN ('milai_api', 'milai_steward', 'milai_worker', 'milai_audit')
            ORDER BY rolname
            """
        ).fetchall()
    assert len(rows) == 4
    assert all(row[1:] == (False, False, False, False, False) for row in rows)


@pytest.mark.integration
@pytest.mark.security
def test_database_boundary_rejects_owner_and_misassigned_runtime_login(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ONE,
        local_actor_id=ACTOR_ONE,
        api_token="test-token-with-at-least-32-characters",
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    with pytest.raises(DatabaseRoleError, match="assigned runtime role"):
        Database(
            settings,
            dsn=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
            expected_role="milai_api",
        )
    with pytest.raises(DatabaseRoleError, match="allowed runtime role"):
        Database(settings, dsn=_url("MILAI_MIGRATION_DATABASE_URL"))


@pytest.mark.integration
@pytest.mark.security
def test_append_only_event_permissions_are_role_specific() -> None:
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    audit_url = _url("MILAI_TEST_AUDIT_DATABASE_URL")
    with psycopg.connect(api_url) as api:
        _set_context(api, TENANT_ONE, ACTOR_ONE)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("UPDATE milai.operational_event SET reason_code = 'forbidden'")

    with psycopg.connect(audit_url) as audit:
        _set_context(audit, TENANT_ONE, ACTOR_ONE)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            audit.execute(
                """
                INSERT INTO milai.operational_event
                  (tenant_id, event_id, event_type, created_by_actor_id)
                VALUES (%s, %s, 'AUDIT_WRITE_ATTEMPT', %s)
                """,
                (TENANT_ONE, uuid4(), ACTOR_ONE),
            )
