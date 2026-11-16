"""Development fixtures create real versions and delivered references, not invented history."""
import json
from pathlib import Path

from test_v13_5_functional_integration import prepared

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.runners.retrieval_histories import host_task_content, prepare_history_bank


def fixture(name):
    path = Path(__file__).parents[2] / "data/fixtures/host-intent-retrieval-v3-e0.json"
    return next(h for h in json.loads(path.read_text())["histories"] if h["id"] == name)


def test_original_statement_and_actual_saved_versions_remain_distinct(tmp_path):
    root = prepared(tmp_path, memory_method="milai_edit_m_v1")
    report = prepare_history_bank(root, bank="versions", owner="alice",
                                  history=fixture("stored_vs_original"))
    assert len(report["revisions"]) == 2 and all(r["ok"] for r in report["revisions"])
    assert report["model_calls"] == 0
    database = next(root.glob("banks/*/memory.sqlite"))
    with SqliteStore.from_conn_string(str(database)) as store:
        service = MemoryService(store, ("functional", "run", "versions", "alice"), "alice",
                                 database.parent / "memory.lock",
                                 functional_contract="functional_v1")
        record_id = report["revisions"][0]["id"]
        old = service.read(record_id, 1)
        current = service.read(record_id)
        assert old["value"]["revision"] == 1
        assert "April 8" in old["value"]["edit_state"]["units"][0]["text"]
        assert current["value"]["revision"] == 2
        assert "April 6" in current["value"]["edit_state"]["units"][0]["text"]
        original = service.source(report["sources"][0]["receipt"]["source_ref"])
        assert "April 3" in original["content"]


def test_partial_evidence_is_an_actual_return_and_only_supplied_when_declared(tmp_path):
    root = prepared(tmp_path, memory_method="milai_edit_m_v1")
    history = fixture("partial_evidence")
    report = prepare_history_bank(root, bank="partial", owner="alice", history=history)
    packet = report["prefetch"]
    assert packet["ok"] and packet["usage"]["read_operations"] == 1
    assert "N-214" in json.dumps(packet["evidence"])
    assert "7316" not in json.dumps(packet["evidence"])
    without = host_task_content(history["requests"][0], report)
    with_prior = host_task_content(history["requests"][1], report)
    assert "N-214" not in without
    assert json.dumps(packet, ensure_ascii=False) in with_prior
    assert history["review_basis"] not in with_prior
    assert report["stored_records"] == []
    database = next(root.glob("banks/*/memory.sqlite"))
    with SqliteStore.from_conn_string(str(database)) as store:
        # Existing Store snapshot, using the very reference delivered by the tool.
        ref = packet["evidence"][0]["ref"]
        service = MemoryService(store, ("functional", "run", "partial", "alice"), "alice",
                                 database.parent / "memory.lock",
                                 functional_contract="functional_v1")
        snapshot = store.get(namespace(service), ref["snapshot_id"]).value
        assert ref["item_index"] in snapshot["delivered_indices"]
        assert snapshot["schema"] == "milai_retrieval_snapshot_v1"
