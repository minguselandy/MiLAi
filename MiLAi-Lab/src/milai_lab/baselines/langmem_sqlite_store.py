"""Local transaction cleanup for the optional LangMem SQLite Store."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.store.sqlite import SqliteStore


class TransactionalSqliteStore(SqliteStore):
    """Keep the original operation error when SQLite ends its transaction."""

    def setup(self) -> None:
        if self.is_setup:
            return
        super().setup()
        # The SDK pages by updated_at. Without this physical index, every
        # namespace page sorts all matching values, including large journals.
        with self.lock, self.conn:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS milai_store_updated_at_idx ON store(updated_at DESC)"
            )

    @contextmanager
    def _cursor(self, *, transaction: bool = True) -> Iterator[sqlite3.Cursor]:
        if not self.is_setup:
            self.setup()
        with self.lock:
            if transaction:
                self.conn.execute("BEGIN")
            cursor = self.conn.cursor()
            try:
                yield cursor
            except BaseException as error:
                if transaction:
                    try:
                        self.conn.rollback()
                    except sqlite3.Error as cleanup_error:
                        error.add_note(f"SQLite rollback cleanup: {cleanup_error}")
                raise
            else:
                if transaction:
                    self.conn.commit()
            finally:
                cursor.close()
