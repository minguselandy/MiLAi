from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from milai.application.retrieval import RetrievalRepository
from milai.persistence import SessionContext

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("22222222-2222-4222-8222-222222222222")


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, *, scope_count: int = 0) -> None:
        self.executed: list[tuple[str, object]] = []
        self.scope_count = scope_count

    def execute(self, statement: str, parameters: object = None) -> _Cursor:
        self.executed.append((statement, parameters))
        if "bounded_scope" in statement:
            return _Cursor([(self.scope_count,)])
        if "set_config('hnsw.iterative_scan'" in statement:
            return _Cursor([("strict_order",)])
        return _Cursor([])


class _Database:
    def __init__(self, *, scope_count: int = 0) -> None:
        self.connection_value = _Connection(scope_count=scope_count)

    @contextmanager
    def connection(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        yield self.connection_value


def test_bounded_scoped_vector_search_materializes_exact_candidates() -> None:
    database = _Database()
    repository = RetrievalRepository(database)  # type: ignore[arg-type]

    candidates = repository.search_vector(
        SessionContext(TENANT_ID, ACTOR_ID),
        [0.0] * 128,
        {"project_ids": ["isolated-project"]},
        datetime.now(UTC),
        3,
        model_id="embedding-model",
        projection_version="projection-version",
    )

    assert candidates == []
    assert len(database.connection_value.executed) == 2
    count_statement, count_parameters = database.connection_value.executed[0]
    assert "bounded_scope" in count_statement
    assert count_parameters is not None
    search_statement, search_parameters = database.connection_value.executed[1]
    assert "search_embedding_window_128" in search_statement
    assert "WITH scoped AS MATERIALIZED" in search_statement
    assert search_parameters is not None


def test_large_scoped_vector_search_keeps_strict_iterative_hnsw_scan() -> None:
    database = _Database(scope_count=4_097)
    repository = RetrievalRepository(database)  # type: ignore[arg-type]

    candidates = repository.search_vector(
        SessionContext(TENANT_ID, ACTOR_ID),
        [0.0] * 128,
        {"project_ids": ["large-project"]},
        datetime.now(UTC),
        3,
        model_id="embedding-model",
        projection_version="projection-version",
    )

    assert candidates == []
    assert len(database.connection_value.executed) == 3
    setting_statement, setting_parameters = database.connection_value.executed[1]
    assert "set_config('hnsw.iterative_scan', 'strict_order', true)" in setting_statement
    assert setting_parameters is None
    search_statement, search_parameters = database.connection_value.executed[2]
    assert "WITH candidates AS" in search_statement
    assert "WITH scoped AS MATERIALIZED" not in search_statement
    assert search_parameters is not None


def test_search_candidate_sql_applies_entity_and_memory_type_before_ranking() -> None:
    database = _Database()
    repository = RetrievalRepository(database)  # type: ignore[arg-type]
    context = SessionContext(TENANT_ID, ACTOR_ID)
    now = datetime.now(UTC)

    repository.search_fts(
        context,
        "release owner",
        {"project_ids": ["milai"]},
        now,
        5,
        entities=["Release"],
        memory_types=["Project_State"],
        statement_timeout_ms=100,
    )

    statement, parameters = database.connection_value.executed[-1]
    assert "JOIN milai.claim claim" in statement
    assert "strpos(lower(concat_ws" in statement
    assert "lower(claim.claim_type) = ANY" in statement
    assert parameters is not None
    assert ["release"] in parameters  # type: ignore[operator]
    assert ["project_state"] in parameters  # type: ignore[operator]
