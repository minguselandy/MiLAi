"""Persistent bounded views and incremental source observations over the actual Store."""
import json
from datetime import UTC, datetime

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.query_structure import (
    build_query_structure,
    cached_structures,
    next_structure_slot,
)


def interpretation(messages, schema):
    value = json.loads(messages[-1]["content"])
    return {"scope": value["question"], "nodes": [
        {"id": "n" + s["id"][1:], "text": s["text"], "evidence": [s["id"]],
         "kind": "reported"} for s in value["sources"]],
        "rules": [], "remove": [], "remove_rules": [], "unresolved": []}


def service_at(store, path, clock=None):
    return MemoryService(store, ("slots", "alice"), "alice", path / "lock",
                         functional_contract="functional_v1", clock=clock)


def operations(service, question, call=interpretation):
    state = MemoryControlState(task={"request": question, "query_time": "2032-07-02"})
    ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=call,
                             fits=lambda items: True, view_capacity=2)
    return state, ops


def test_a_b_a_reopens_original_slot_and_lru_evicts_other_scope(tmp_path):
    calls = []

    def call(messages, schema):
        calls.append(messages)
        return interpretation(messages, schema)

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        a = service.capture_user("s", "a", "A uses amber.")["source_ref"]
        b = service.capture_user("s", "b", "B uses blue.")["source_ref"]
        for slot, question, ref in (("current", "A color?", a), ("slot1", "B color?", b)):
            build_query_structure(service, question, "2032-07-02", [ref], policy="incremental",
                                  call=call, slot=slot, capacity=2, replace_slot=True)
        original = cached_structures(service, 2)["current"]
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        state, ops = operations(service, "A color?", call)
        selected = next(a for a in ops.actions(state) if a.id == "use_view_current")
        result = ops.execute(selected, state)
        assert result["ok"] and len(calls) == 2
        assert cached_structures(service, 2)["current"] == original
        assert "amber" in str(state.visible_evidence)
        assert next_structure_slot(service, 2) == "slot1"
        service.capture_user("s", "c", "C uses copper.")
        state, ops = operations(service, "C color?", call)
        selected = next(a for a in ops.actions(state) if a.id == "new_view")
        assert selected.parameters["slot"] == "slot1"
        ops.execute(selected, state)
        saved = cached_structures(service, 2)
        assert len(saved) == 2 and saved["current"] == original
        assert saved["slot1"]["revision"] == 2
        assert "copper" in str(saved["slot1"]["structure"])
        assert "blue" not in str(saved["slot1"]["structure"])


def test_equal_clock_arrival_outside_support_is_visible_and_revocation_is_slot_local(tmp_path):
    def clock():
        return datetime(2032, 7, 2, 9, tzinfo=UTC)
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, clock)
        a = service.capture_user("s", "a", "PRIVATE_A is the A label.")["source_ref"]
        build_query_structure(service, "A label?", "2032-07-02", [a], policy="incremental",
                              call=interpretation, capacity=2)
        b = service.capture_user("s", "b", "B label is public.")["source_ref"]
        state, ops = operations(service, "A label?")
        assert b in {e["source_ref"] for e in state.new_events}
        refresh = next(a for a in ops.actions(state) if a.id == "refresh_view_current")
        assert b in refresh.parameters["source_refs"]
        build_query_structure(service, "B label?", "2032-07-02", [b], policy="incremental",
            call=interpretation, slot="slot1", capacity=2, replace_slot=True)
        handle = service.source_fragments(a)[0]["fragment_handle"]
        service.forget("s", "forget", fragment_handles=[handle])
        state, ops = operations(service, "B label?")
        assert "PRIVATE_A" not in str(state.project())
        ids = {a.id for a in ops.actions(state)}
        assert "use_view_current" not in ids and "use_view_slot1" in ids


def test_incremental_source_filter_avoids_old_formation_enumeration(tmp_path, monkeypatch):
    moment = [datetime(2032, 7, 1, tzinfo=UTC)]
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, lambda: moment[0])
        for i in range(12):
            service.capture_user("s", str(i), f"Old event {i}.")
        moment[0] = datetime(2032, 7, 2, tzinfo=UTC)
        latest = service.capture_user("s", "new", "New event.")["source_ref"]

        def no_scan(namespace):
            raise AssertionError(
                "Source arrivals must not enumerate semantic records or all sources")

        monkeypatch.setattr(service, "_rows", no_scan)
        page = service.source_arrivals(moment[0].isoformat())
        assert [e["event_id"] for e in page["events"]] == [latest]
        assert page["rows_materialized"] == 1
        assert page["database_rows_scanned"] is None
