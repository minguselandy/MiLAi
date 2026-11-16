"""The physical paging index preserves the SDK's values, order and namespace rules."""

from pathlib import Path

from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore


def test_order_index_keeps_prefix_pages_ties_filters_and_updates(tmp_path: Path) -> None:
    path = str(tmp_path / "bank.sqlite")
    with SqliteStore.from_conn_string(path) as legacy:
        for i in range(135):
            ns = ("bank", "alice") if i % 3 else ("bank", "alice", "journal")
            legacy.put(ns, f"key-{135-i:03}", {"content": "真实原件 " + str(i),
                                               "selected": i % 2 == 0, "nested": [i, None]})
        legacy.put(("bank", "bob"), "other", {"content": "Other owner"})
        legacy.conn.execute("UPDATE store SET updated_at='2030-01-01 00:00:00'")

        def pages(store: SqliteStore) -> list:
            return [item for offset in (0, 40, 80, 120)
                    for item in store.search(("bank", "alice"), limit=40, offset=offset)]

        expected = pages(legacy)
        selected = legacy.search(("bank", "alice"), filter={"selected": True}, limit=100)
    with TransactionalSqliteStore.from_conn_string(path) as indexed:
        actual = pages(indexed)
        assert actual == expected
        assert indexed.search(("bank", "alice"), filter={"selected": True}, limit=100) == selected
        assert all(item.namespace[:2] == ("bank", "alice") for item in actual)
        plan = indexed.conn.execute(
            "EXPLAIN QUERY PLAN SELECT prefix,key,value FROM store WHERE prefix LIKE ? "
            "ORDER BY updated_at DESC LIMIT 40 OFFSET 80", ("bank.alice%",)
        ).fetchall()
        assert any("milai_store_updated_at_idx" in str(row) for row in plan)
        assert all("TEMP B-TREE" not in str(row) for row in plan)
        indexed.put(("bank", "alice"), "new", {"content": "New observation"})
        indexed.delete(("bank", "alice"), "key-134")
        expected_after = pages(indexed)
        indexed.conn.execute("DROP INDEX milai_store_updated_at_idx")
        assert pages(indexed) == expected_after
    with TransactionalSqliteStore.from_conn_string(path) as reopened:
        assert pages(reopened) == expected_after
        reopened.setup()
        assert reopened.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='milai_store_updated_at_idx'"
        ).fetchone()[0] == 1
