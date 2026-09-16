from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import Connection, InterfaceError, OperationalError
from psycopg.errors import QueryCanceled
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool, PoolTimeout, TooManyRequests

from milai.config import RuntimeSettings, WorkerSettings
from milai.observability.metrics import request_operation_timer


class DatabaseUnavailable(RuntimeError):
    """A safe, payload-free canonical database availability error."""


class DatabaseCapacityError(DatabaseUnavailable):
    """A bounded pool acquisition failed; not a whole-request commit receipt."""

    def __init__(self, reason: Literal[
        "POOL_QUEUE_FULL", "POOL_WAIT_TIMEOUT", "TENANT_CONCURRENCY_LIMIT",
    ]) -> None:
        super().__init__("database connection capacity is temporarily unavailable")
        self.reason = reason


class DatabaseStatementTimeout(RuntimeError):
    """A request-owned PostgreSQL statement budget was exhausted."""


class DatabaseRoleError(RuntimeError):
    """The connected session is not the dedicated, least-privilege runtime role."""


@dataclass(frozen=True, slots=True)
class SessionContext:
    tenant_id: UUID
    actor_id: UUID


def _reset_connection(connection: Connection[tuple[Any, ...]]) -> None:
    if connection.info.transaction_status != TransactionStatus.IDLE:
        connection.rollback()
    connection.execute("RESET ALL")
    connection.commit()


class Database:
    """Small connection-pool boundary with transaction-scoped tenant context."""

    def __init__(
        self,
        settings: RuntimeSettings | WorkerSettings,
        *,
        dsn: str | None = None,
        expected_role: Literal["milai_api", "milai_steward", "milai_worker"] | None = None,
    ) -> None:
        if dsn is None:
            if isinstance(settings, WorkerSettings):
                raise DatabaseRoleError("worker settings require an explicit worker DSN")
            connection_dsn = settings.database_dsn
        else:
            connection_dsn = dsn
        inferred_role = urlsplit(connection_dsn).username
        self._expected_role = expected_role or ("milai_api" if dsn is None else str(inferred_role))
        if self._expected_role not in {"milai_api", "milai_steward", "milai_worker"}:
            raise DatabaseRoleError("database login role is not an allowed runtime role")
        if inferred_role != self._expected_role:
            raise DatabaseRoleError("database URL login does not match its assigned runtime role")
        self._connect_timeout = settings.database_connect_timeout_seconds
        self._tenant_limit = settings.database_pool_max_per_tenant
        self._tenant_lock = Lock()
        self._tenant_active: dict[UUID, int] = {}
        self._pool = ConnectionPool(
            conninfo=connection_dsn,
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
            max_waiting=settings.database_pool_max_waiting,
            timeout=settings.database_connect_timeout_seconds,
            open=False,
            reset=_reset_connection,
            kwargs={"autocommit": False},
        )
        self._open_lock = Lock()
        self._opened = False

    def open(self) -> None:
        if self._opened:
            return
        with self._open_lock:
            if not self._opened:
                try:
                    self._pool.open(wait=True, timeout=self._connect_timeout)
                    with self._pool.connection() as connection:
                        self._assert_runtime_role(connection)
                except DatabaseRoleError:
                    self._pool.close()
                    raise
                except (InterfaceError, OperationalError, PoolTimeout, OSError) as exc:
                    raise DatabaseUnavailable("canonical database is unavailable") from exc
                self._opened = True

    def close(self) -> None:
        with self._open_lock:
            if self._opened:
                # Pool maintenance workers and returned Flask request connections may
                # complete concurrently with shutdown.  Wait long enough for a clean
                # close so isolated databases can prove a zero-connection teardown.
                self._pool.close(timeout=30)
                self._opened = False

    def ping(self) -> None:
        try:
            self.open()
            with self._pool.connection() as connection:
                self._assert_runtime_role(connection)
                connection.execute("SELECT 1").fetchone()
        except (InterfaceError, OperationalError, PoolTimeout, OSError) as exc:
            raise DatabaseUnavailable("canonical database is unavailable") from exc

    @contextmanager
    def _tenant_slot(self, context: SessionContext | None) -> Iterator[None]:
        # This is per Database/pool/process, keyed by trusted tenant identity.
        # No waiting thread or tenant record is retained after the last release.
        if self._tenant_limit is None or context is None:
            yield
            return
        tenant = context.tenant_id
        with self._tenant_lock:
            active = self._tenant_active.get(tenant, 0)
            if active >= self._tenant_limit:
                raise DatabaseCapacityError("TENANT_CONCURRENCY_LIMIT")
            self._tenant_active[tenant] = active + 1
        try:
            yield
        finally:
            with self._tenant_lock:
                remaining = self._tenant_active[tenant] - 1
                if remaining:
                    self._tenant_active[tenant] = remaining
                else:
                    del self._tenant_active[tenant]

    @contextmanager
    def _request_connection(self) -> Iterator[Connection[tuple[Any, ...]]]:
        timer = request_operation_timer.get()
        with ExitStack() as stack:
            # Translate acquisition errors only. A later failure may follow
            # earlier committed work and must not be called admission rejection.
            try:
                if timer is None:
                    connection = stack.enter_context(self._pool.connection())
                else:
                    with timer.measure("db_pool_acquire_ms"):
                        connection = stack.enter_context(self._pool.connection())
            except TooManyRequests as exc:
                raise DatabaseCapacityError("POOL_QUEUE_FULL") from exc
            except PoolTimeout as exc:
                raise DatabaseCapacityError("POOL_WAIT_TIMEOUT") from exc
            if timer is None:
                yield connection
            else:
                with timer.measure("db_connection_hold_ms"):
                    yield connection

    @contextmanager
    def _transaction(self, connection: Connection[tuple[Any, ...]]) -> Iterator[None]:
        timer = request_operation_timer.get()
        if timer is None:
            with connection.transaction():
                yield
            return
        transaction = connection.transaction()
        timer.call("db_transaction_enter_ms", transaction.__enter__)
        try:
            yield
        except BaseException:
            # Forward the original exception, including cancellation, so the
            # driver retains its rollback/suppression semantics. Never close a
            # failed transaction as if its body had completed successfully.
            if not timer.call("db_transaction_exit_ms", transaction.__exit__, *sys.exc_info()):
                raise
        else:
            timer.call("db_transaction_exit_ms", transaction.__exit__, None, None, None)

    @contextmanager
    def connection(
        self,
        context: SessionContext | None = None,
        *,
        read_only: bool = False,
        isolation_level: Literal["READ COMMITTED", "REPEATABLE READ"] = "READ COMMITTED",
        statement_timeout_ms: int | None = None,
    ) -> Iterator[Connection[tuple[Any, ...]]]:
        if statement_timeout_ms is not None and (
            isinstance(statement_timeout_ms, bool)
            or not 1 <= statement_timeout_ms <= 10_000
        ):
            raise ValueError("statement_timeout_ms must be between 1 and 10000")
        try:
            self.open()
            with (self._tenant_slot(context), self._request_connection() as connection,
                  self._transaction(connection)):
                # PostgreSQL requires transaction characteristics before the
                # first ordinary query. Role attestation is intentionally the
                # first query after these safe SET TRANSACTION statements.
                if isolation_level == "REPEATABLE READ":
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                if read_only:
                    connection.execute("SET TRANSACTION READ ONLY")
                self._assert_runtime_role(connection)
                if context is not None:
                    connection.execute(
                        "SELECT set_config('milai.tenant_id', %s, true), "
                        "set_config('milai.actor_id', %s, true)",
                        (str(context.tenant_id), str(context.actor_id)),
                    )
                if statement_timeout_ms is not None:
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (f"{statement_timeout_ms}ms",),
                    )
                yield connection
        except DatabaseUnavailable:
            raise
        except QueryCanceled as exc:
            raise DatabaseStatementTimeout("database statement deadline exceeded") from exc
        except (InterfaceError, OperationalError, PoolTimeout, OSError) as exc:
            raise DatabaseUnavailable("canonical database operation failed") from exc

    def _assert_runtime_role(self, connection: Connection[tuple[Any, ...]]) -> None:
        row = connection.execute(
            """
            SELECT session_user, current_user,
                   role.rolsuper, role.rolbypassrls, role.rolcreatedb,
                   role.rolcreaterole, role.rolinherit,
                   EXISTS (
                     SELECT 1 FROM pg_namespace namespace
                     WHERE namespace.nspname = 'milai'
                       AND namespace.nspowner = role.oid
                   ) OR EXISTS (
                     SELECT 1
                     FROM pg_class object
                     JOIN pg_namespace namespace
                       ON namespace.oid = object.relnamespace
                     WHERE namespace.nspname = 'milai'
                       AND object.relowner = role.oid
                   ) AS owns_milai_object
            FROM pg_roles role
            WHERE role.rolname = session_user
            """
        ).fetchone()
        if row is None:
            raise DatabaseRoleError("database session role metadata is unavailable")
        session_user, current_user, *unsafe_attributes = row
        if (
            session_user != self._expected_role
            or current_user != self._expected_role
            or any(bool(value) for value in unsafe_attributes)
        ):
            raise DatabaseRoleError(
                "database session is not the expected least-privilege runtime role"
            )
