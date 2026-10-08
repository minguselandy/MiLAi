"""SQLite failure and reopen behavior used by the common runners."""

import sqlite3

import pytest

from milai_lab.harness.sqlite_store import TransactionalSqliteStore


def test_full_transaction_keeps_original_error_and_reopens(tmp_path):
    path = str(tmp_path / "memory.sqlite")
    with TransactionalSqliteStore.from_conn_string(path) as store:
        store.setup()
        store.put(("memory",), "before", {"content": "original"})
        pages = store.conn.execute("PRAGMA page_count").fetchone()[0]
        store.conn.execute(f"PRAGMA max_page_count={pages + 2}")
        with pytest.raises(sqlite3.DatabaseError, match="database or disk is full") as raised:
            store.put(("memory",), "failed", {"content": "x" * 100_000})
        assert raised.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert store.get(("memory",), "failed") is None
        store.put(("memory",), "after", {"content": "continued"})
    with TransactionalSqliteStore.from_conn_string(path) as store:
        assert store.get(("memory",), "before").value == {"content": "original"}
        assert store.get(("memory",), "after").value == {"content": "continued"}
        assert store.get(("memory",), "failed") is None
