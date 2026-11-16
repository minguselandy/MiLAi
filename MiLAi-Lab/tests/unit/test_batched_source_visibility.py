"""Bulk source reads keep the same capture, owner, visibility and ordering decisions."""
from collections import Counter

import pytest
from langgraph.store.base import GetOp
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import FunctionalIntegrityError, namespace
from milai_lab.memory.service import MemoryService


def source_row(index, *, owner="alice"):
    ref = f"source-{index:04d}"
    return {"event_id": ref, "owner": owner, "session": "same-session",
            "capture_key": str(index), "role": "tool", "origin": "reference_document",
            "object_ref": None, "content": f"Literal source {index} 甲🙂",
            "occurred_at": None, "observed_at": "2030-01-01T00:00:00+00:00",
            "source_revision": 1}


def test_bulk_reads_match_single_source_checks_across_pages_and_keep_unknowns(
    tmp_path, monkeypatch,
):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("bulk", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        for index in range(518):
            row = source_row(index, owner="bob" if index == 515 else "alice")
            store.put(service.sources_namespace, row["event_id"], row, index=False)
            if index != 514:
                store.put(namespace(service), "capture:" + row["event_id"], {
                    "source_ref": row["event_id"], "source_revision": 1}, index=False)
        service._uncertain_captures.add("source-0513")
        store.put(namespace(service), "visibility", {"owner": "alice",
            "bank": list(service.namespace), "epoch": 1, "records": [],
            "sources": ["source-0512"], "operations": {}})
        expected = [event for i in range(518)
                    if (event := service.source(f"source-{i:04d}")) is not None]
        counts = Counter()
        batch = store.batch

        def observed(operations):
            operations = list(operations)
            confirmations = [op for op in operations if isinstance(op, GetOp)
                             and op.namespace == namespace(service)
                             and op.key.startswith("capture:")]
            if confirmations:
                counts["confirmation_batches"] += 1
                counts["confirmations"] += len(confirmations)
            return batch(operations)

        monkeypatch.setattr(store, "batch", observed)
        actual = service._visible_sources()
        assert actual == expected
        assert counts["confirmation_batches"] == 2
        assert counts["confirmations"] == 515
        assert all(row["occurred_at"] is None for row in actual)
        page = service.source_arrivals("2030-01-01T00:00:00+00:00")
        assert page["events"] == expected
        assert page["rows_materialized"] == 517  # The Store owner filter excludes Bob.
        assert service.source_arrivals("2030-01-02T00:00:00+00:00")["events"] == []


@pytest.mark.parametrize("corruption", ["identity", "confirmation"])
def test_bulk_read_does_not_weaken_source_integrity_failures(tmp_path, corruption):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("bulk", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        row = source_row(0)
        if corruption == "identity":
            row["role"] = "system"
        store.put(service.sources_namespace, row["event_id"], row, index=False)
        store.put(namespace(service), "capture:" + row["event_id"], {
            "source_ref": row["event_id"],
            "source_revision": 2 if corruption == "confirmation" else 1}, index=False)
        for read in [lambda: service.source(row["event_id"]), service._visible_sources,
                     service.source_arrivals]:
            with pytest.raises(FunctionalIntegrityError):
                read()


def test_exclusion_matches_the_previous_visible_id_allowlist_before_ranking(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("bulk", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        for i in range(4):
            service.capture_user("session", str(i), "needle value " + str(i))
        current = service.capture_user("query", "q", "needle needle incorrect premise")[
            "source_ref"]
        refs = [row["event_id"] for row in service._visible_sources() if row["event_id"] != current]
        old = service.search_sources("needle", source_refs=refs, include_scope=True,
                                     tokenization="unicode_v1")
        new = service.search_sources("needle", excluded_source_refs=[current], include_scope=True,
                                     tokenization="unicode_v1")
        for key in ["source_materials", "source_scope", "raw_events"]:
            assert new[key] == old[key]
        assert new["source_retrieval"]["indexed_count"] == old["source_retrieval"]["indexed_count"]
        assert new["source_retrieval"]["excluded_source_count"] == 1
