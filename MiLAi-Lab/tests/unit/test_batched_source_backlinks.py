"""Batch history discovery preserves source links, visibility, limits and result order."""
from collections import Counter

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory


def service_at(store, path, owner="alice"):
    return MemoryService(store, ("links", owner), owner, path / (owner + ".lock"),
                         functional_contract="functional_v1")


def writer_at(service, session, event_key, text):
    source = service.capture_user(session, event_key, text)["source_ref"]
    writer = FunctionalEditMemory(service, len, interface_version="I2",
                                  source_access="independent_v1", material_limit=20000)
    writer.context(session, event_key, "batch-backlinks-test")
    config = {"configurable": {"user_id": service.owner, "v13_session": session,
        "v13_turn_id": event_key, "v13_config_version": "batch-backlinks-test"}}
    evidence = [row["fragment_handle"] for row in service.source_fragments(source)]
    return writer, config, source, evidence


def save(service, session, text, summary):
    writer, config, source, evidence = writer_at(service, session, "event", text)
    receipt = writer.save_edit(config, "save", units=[{
        "text": summary, "role": "content", "evidence": evidence}])
    assert receipt["ok"], receipt
    return receipt["id"], source


def test_source_only_search_does_not_fetch_or_scan_backlinks(tmp_path, monkeypatch):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        for index in range(5):
            service.capture_user("s", str(index), "needle source " + str(index))

        def forbidden(*args, **kwargs):
            raise AssertionError("There are no records to link; no source/history scan is needed")

        monkeypatch.setattr(service, "sources", forbidden)
        monkeypatch.setattr(service, "backlink_candidates", forbidden)
        monkeypatch.setattr(service, "_backlink_record_ids", forbidden)
        assert service.search("needle", include_raw=False)["records"] == []


def test_empty_exact_namespace_checks_names_without_materializing_children(tmp_path, monkeypatch):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        for index in range(130):
            store.put((*service.namespace, str(index)), "child", {"value": index})
        search = store.search
        queries = []

        def observed(prefix, **kwargs):
            queries.append(prefix)
            return search(prefix, **kwargs)

        monkeypatch.setattr(store, "search", observed)
        assert service._rows(service.namespace) == []
        assert queries == []
        store.put(service.namespace, "new-root", {"literal": "newly visible"})
        assert service._rows(service.namespace) == [
            {"id": "new-root", "value": {"literal": "newly visible"}}]
        assert queries  # No persistent negative cache after the earlier empty read.


def test_batch_links_match_single_source_history_discovery_and_keep_per_source_cap(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        record, old = save(service, "old", "oldneedle version", "first summary")
        writer, config, new, evidence = writer_at(service, "new", "event", "newneedle version")
        current = service.read(record)
        unit = current["value"]["edit_state"]["units"][0]["unit_id"]
        changed = writer.update_edit(config, "change", current["candidate_handle"], [{
            "operation": "replace", "target_unit": unit, "text": "second summary",
            "evidence": evidence}])
        assert changed["ok"], changed
        other_record, other = save(service, "other", "oldneedle other", "unrelated summary")
        foreign = service_at(store, tmp_path, "bob")
        _, foreign_ref = save(foreign, "foreign", "oldneedle foreign", "foreign summary")
        refs = [old, new, other, foreign_ref]
        for limit in [1, 100]:
            batch = service._backlink_record_ids(refs, limit_per_source=limit)
            actual = {ref: [rid for rid in batch.get(ref, []) if service.read(rid)["ok"]]
                      for ref in refs}
            expected = {ref: [row["id"] for row in service.backlink_candidates([ref], limit)]
                        for ref in refs}
            assert actual == expected
        assert record in batch[old] and record in batch[new]
        assert other_record in batch[other] and foreign_ref not in batch


def test_search_batches_one_record_scan_and_preserves_legacy_ranking(tmp_path, monkeypatch):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        records = [save(service, f"source-{i}", f"共同 needle label {i}", f"summary {i}")
                   for i in range(4)]
        batched = service.search("共同 needle", limit=10, include_raw=False)
        original = service._backlink_record_ids

        def single_source(refs, *, limit_per_source):
            return {ref: [row["id"] for row in service.backlink_candidates([ref], limit_per_source)]
                    for ref in refs}

        monkeypatch.setattr(service, "_backlink_record_ids", single_source)
        legacy = service.search("共同 needle", limit=10, include_raw=False)
        assert batched == legacy
        monkeypatch.setattr(service, "_backlink_record_ids", original)
        calls = Counter()
        rows = service._rows

        def count_rows(ns):
            calls[ns] += 1
            return rows(ns)

        monkeypatch.setattr(service, "_rows", count_rows)
        links = service._backlink_record_ids([ref for _, ref in records], limit_per_source=100)
        assert calls[service.namespace] == 1
        assert set(links) == {ref for _, ref in records}
        hidden, source = records[0]
        store.put(namespace(service), "visibility", {"owner": service.owner,
            "bank": list(service.namespace), "epoch": 1, "records": [hidden],
            "sources": [], "operations": {}})
        assert not service.read(hidden)["ok"]
        assert hidden not in {row["id"] for row in service.search("needle")["records"]}
        assert service._backlink_record_ids([source], limit_per_source=1)[source] == [hidden]
