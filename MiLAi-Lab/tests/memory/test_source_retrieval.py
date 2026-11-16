"""Source-first retrieval on temporary SQLite, without model or external I/O."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.service import MemoryService, reference_key


def test_source_identity_legacy_lookup_filters_once_and_keeps_owner_and_cached_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "identity.sqlite")) as store:
        service = service_at(store, tmp_path)
        original = service.capture_user("old-session", "old-key", "Original source.")["source_ref"]
        source = service.source(original)
        assert source is not None
        store.put(service.sources_namespace, "foreign", {**source, "owner": "foreign-owner",
                                                          "event_id": "foreign"}, index=False)
        ns = (*service.namespace, "source_identities")
        store.delete(ns, reference_key([service.owner, "old-session", "old-key", "user"]))
        calls = []
        search = store.search

        def filtered(namespace, **kwargs):
            calls.append(kwargs)
            assert kwargs["filter"]["owner"] == service.owner and kwargs["limit"] == 1
            return search(namespace, **kwargs)

        monkeypatch.setattr(store, "search", filtered)
        monkeypatch.setattr(service, "_rows", lambda *_: pytest.fail("Whole Source scan"))
        assert service.event_id("old-session", "old-key", "user") == original
        assert service.event_id("old-session", "old-key", "user") == original
        assert len(calls) == 1
        fresh = service.event_id("new-session", "new-key", "user")
        assert fresh != original and fresh != "foreign"
        assert service.event_id("new-session", "new-key", "user") == fresh
        assert len(calls) == 2


def test_source_query_skips_formation_and_keeps_owner_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        source = service.capture_user("session", "turn:0", "Original source.")
        other = MemoryService(store, (*service.sources_namespace, "bob"), "bob",
                              tmp_path / "bob.lock")
        other.capture_user("session", "turn:0", "Foreign source.")
        assert service.sources()[0]["formation_status"] == "pending"
        rows = service._rows

        def source_rows(namespace: tuple[str, ...]) -> list[dict[str, Any]]:
            assert namespace != service.namespace, "Source search traversed semantic history"
            return rows(namespace)

        monkeypatch.setattr(service, "_rows", source_rows)
        found = service.search_sources("Original", tokenization="unicode_v1")
        assert [row["event_id"] for row in found["raw_events"]] == [source["source_ref"]]
        assert "formation_status" not in found["raw_events"][0]
        assert service.read_source_materials(found["source_materials"]) == found["source_materials"]
        timings = found["source_retrieval"]["timings"]
        assert set(timings) == {"enumerate_seconds", "assemble_seconds", "index_seconds",
                                "rank_seconds", "open_seconds", "total_seconds"}
        assert all(value >= 0 for value in timings.values())


def test_unicode_queries_retrieve_original_roles_beyond_first_store_page(tmp_path: Path) -> None:
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        chinese = service.capture_user("cn", "turn:0", "研发部李明不能审批外部预算,先让赵敏确认。")
        reply = service.capture_assistant(
            "cn", "turn:1", "明白,是研发部的李明,不是采购部同名同事。")
        english = service.capture_user(
            "en", "turn:0", "Project OMEGA: release 2042, approval pending.")
        tool = service.capture_tool("tool", "turn:0", "inventory", "仓库乙库存剩余17件。", None)
        for index in range(105):
            service.capture_user(f"noise-{index}", "turn:0", f"日常旅行日记 tropical beach {index}")
        cases = [("研发部李明的预算审批", chinese["source_ref"]),
                 ("omega RELEASE 2042!", english["source_ref"]),
                 ("仓库乙剩余库存", tool["source_ref"])]
        for query, expected in cases:
            found = service.search_sources(query, limit=1, granularity="turn",
                                           tokenization="unicode_v1")
            assert expected in [row["event_id"] for row in found["raw_events"]]
            assert found["source_retrieval"]["indexed_count"] == 108
        turns = json.loads(service.search_sources(
            cases[0][0], limit=1, granularity="turn", tokenization="unicode_v1",
        )["source_materials"][0]["text"])
        assert [turn["source_ref"] for turn in turns] == [
            chinese["source_ref"], reply["source_ref"]]
        assert "不能" in turns[0]["content"] and "不是采购部" in turns[1]["content"]


def test_unicode_normalization_and_legacy_bm25_order() -> None:
    import numpy as np
    from rank_bm25 import BM25Okapi

    from milai_lab.memory.retrieval import _lexical_tokens, flat_bm25_rank

    units = [{"id": str(i), "index_text": text} for i, text in enumerate([
        "Café, 2042! 中文检索", "desert journey", "old report", "ocean trip",
    ])]
    assert _lexical_tokens("CAFÉ! 2042 中文检索") == _lexical_tokens("cafe\u0301, 2042 中文检索")
    assert len(_lexical_tokens("中文检索")) == 3
    assert flat_bm25_rank(units, "CAFÉ 2042", 1, tokenization="unicode_v1")[0]["id"] == "0"
    scores = BM25Okapi([row["index_text"].split(" ") for row in units]).get_scores(["trip"])
    legacy = flat_bm25_rank(units, "trip", 4)
    assert [row["id"] for row in legacy] == [str(i) for i in np.argsort(scores)[::-1]]
    assert [row["score"] for row in legacy] == list(sorted(scores, reverse=True))
    assert flat_bm25_rank([], "", 1, tokenization="unicode_v1") == []
    punctuation = flat_bm25_rank([{"index_text": "..."}], "!?", 1, tokenization="unicode_v1")
    assert punctuation[0]["score"] == 0


def service_at(store: SqliteStore, root: Path) -> MemoryService:
    return MemoryService(store, ("source-retrieval", "alice"), "alice", root / "memory.lock",
                         functional_contract="functional_v1", memory_profile="unified_v1")


def test_dense_record_search_skips_unused_backlinks_but_keeps_prefix_and_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        saved, refs = [], []
        for key, text in (("pine", "PINE_TOKEN cabin preference"),
                          ("oak", "OAK_TOKEN rail preference")):
            capture = service.capture_user("s", key, text)
            refs.append(capture["source_ref"])
            service.bind_public_turn("s", key, capture["source_ref"],
                                     config_version="dense-v1", phase="start")
            fragment = service.source_fragments(capture["source_ref"])[0]
            cfg = {"configurable": {"user_id": "alice", "v13_session": "s",
                                    "v13_turn_id": key, "v13_config_version": "dense-v1"}}
            receipt = FunctionalMemory(service, len).save(
                cfg, "save-" + key, f"Stored {key} preference.", [fragment["fragment_handle"]])
            assert receipt["ok"]
            saved.append(receipt["id"])

        def rank(query: str, records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
            return sorted(records, key=lambda row: row["id"])[::-1][:limit]

        monkeypatch.setattr(service, "semantic_retriever", SimpleNamespace(rank=rank))
        # The raw-inclusive path still performs the original backlink discovery.
        original = service.search("PINE_TOKEN", include_raw=True)
        assert original["raw_events"]
        sources, backlinks = service.sources, service.backlink_candidates

        def unused(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Dense current-record search scanned unused source backlinks")

        monkeypatch.setattr(service, "sources", unused)
        monkeypatch.setattr(service, "backlink_candidates", unused)
        selected = service.search("PINE_TOKEN", include_raw=False)
        assert selected["records"] == original["records"]
        assert selected["raw_events"] == []
        restricted = service.search("PINE_TOKEN", include_raw=False, source_refs=[refs[0]])
        assert [row["id"] for row in restricted["records"]] == [saved[0]]
        target = service.read(saved[0])
        assert service.forget("s", "forget-pine", scope="record",
                              candidate_handle=target["candidate_handle"])["ok"]
        remaining = service.search("PINE_TOKEN", include_raw=False)
        assert [row["id"] for row in remaining["records"]] == [saved[1]]

        # A withdrawn record still needs lexical matches through original
        # provenance when the compact stored text lacks the query's source word.
        monkeypatch.setattr(service, "sources", sources)
        monkeypatch.setattr(service, "backlink_candidates", backlinks)
        cancellation = service.capture_user("s", "cancel", "Withdraw the rail preference.")
        service.bind_public_turn("s", "cancel", cancellation["source_ref"],
                                 config_version="dense-v1", phase="start")
        cfg = {"configurable": {"user_id": "alice", "v13_session": "s",
                                "v13_turn_id": "cancel", "v13_config_version": "dense-v1"}}
        handle = service.source_fragments(cancellation["source_ref"])[0]["fragment_handle"]
        current = service.read(saved[1])
        withdrawn = FunctionalMemory(service, len).update(
            cfg, "withdraw-oak", current["candidate_handle"], [], [handle], retract=True)
        assert withdrawn["ok"]
        found = service.search("OAK_TOKEN", include_raw=False)
        assert found["records"] == []
        assert [row["record_id"] for row in found["withdrawals"]] == [saved[1]]


def test_unformed_original_prefix_reopen_and_forget_share_one_visibility(tmp_path: Path) -> None:
    body = "orchard original details " * 1000 + "COMPLETE_END"
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        user = service.capture_user("first", "turn:0", body, occurred_at="2030-01-01")
        reply = service.capture_assistant("first", "turn:1", "Acknowledged, not a new user claim.")
        assert service.record_no_change("first", "no-op", {"changes": []})["effect"] == "none"
        assert service.records() == []
        found = service.search_evidence("orchard", source_limit=20, semantic_limit=10)
        assert found["records"] == [] and len(found["source_materials"]) == 1
        material = found["source_materials"][0]
        assert material["kind"] == "original_source" and not material["truncated"]
        assert json.loads(material["text"])[0]["content"] == body
        assert {row["event_id"] for row in found["raw_events"]} == {
            user["source_ref"], reply["source_ref"]}
        assert all(not row["descriptions"] for row in service.episodes(limit=None))
        unanchored = service.search_sources(
            "Acknowledged", granularity="turn", source_refs=[reply["source_ref"]])
        assert len(unanchored["source_materials"]) == 1
        assert json.loads(unanchored["source_materials"][0]["text"])[0]["role"] == "assistant"
        # Later arrival reports an earlier date and repeats the exact wording.
        # Neither that date nor text equality grants access to the earlier prefix.
        later = service.capture_user("later", "turn:0", body, occurred_at="1990-01-01")
        prefix = service.search_sources(
            "orchard", source_refs=[user["source_ref"], reply["source_ref"]])
        assert {row["event_id"] for row in prefix["raw_events"]} == {
            user["source_ref"], reply["source_ref"]}
        assert prefix["source_retrieval"]["visible_source_count"] == 2
        assert service.search_sources("orchard", source_refs=[])["source_materials"] == []
        complete = service.search_sources("orchard")
        assert len(complete["source_materials"]) == 2
        cached = copy.deepcopy(complete["source_materials"])
        descriptor = {**material, "source_ranges": [
            {"source_ref": user["source_ref"], "source_revision": 1, "start": 0, "end": 8},
            {"source_ref": user["source_ref"], "source_revision": 1, "start": 4, "end": 12},
            {"source_ref": later["source_ref"], "source_revision": 1, "start": 0, "end": 12},
        ]}
        merged = service.read_source_materials([descriptor])[0]
        assert [(span["source_ref"], span["start"], span["end"])
                for span in merged["source_ranges"]] == [
                    (user["source_ref"], 0, 12), (later["source_ref"], 0, 12)]
        assert len(json.loads(merged["text"])) == 2 and merged["truncated"]

    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        assert len(service.search_sources("orchard")["source_materials"]) == 2
        service.bind_public_turn("first", "turn:0", user["source_ref"],
                                 config_version="source-v1", phase="start")
        config: dict[str, Any] = {"configurable": {"user_id": "alice", "v13_session": "first",
            "v13_turn_id": "turn:0", "v13_config_version": "source-v1"}}
        fragment = service.source_fragments(user["source_ref"])[0]
        memory = FunctionalMemory(service, len)
        saved = memory.save(config, "save", "orchard original details",
                            [fragment["fragment_handle"]])
        assert saved["ok"]
        evidence = service.search_evidence("orchard", source_limit=1, semantic_limit=1)
        assert evidence["source_retrieval"]["requested_count"] == 1
        assert evidence["semantic_retrieval"]["requested_count"] == 1
        assert len(evidence["records"]) == len(evidence["source_materials"]) == 1
        prefix_records = service.search_evidence("orchard", source_refs=[later["source_ref"]])
        assert prefix_records["records"] == []
        handles = [service.source_fragments(ref)[0]["fragment_handle"]
                   for ref in (user["source_ref"], reply["source_ref"])]
        forgotten = service.forget("first", "forget", scope="record_and_sources",
                                   fragment_handles=handles)
        assert forgotten["ok"] and service.source(user["source_ref"]) is None
        assert not service.read(saved["id"])["ok"]
        assert EpisodeIndex(service).read(user["episode_id"]) is None
        live = service.search_evidence("orchard")
        assert live["records"] == []
        assert {row["event_id"] for row in live["raw_events"]} == {later["source_ref"]}
        reopened = service.read_source_materials(cached)
        assert [row["id"] for row in reopened] == [row["id"] for row in cached]
        hidden = next(row for row in reopened if row["session_id"] == "first")
        assert hidden["visibility"] == "unavailable" and hidden["text"] == "[]"
        assert not hidden["source_ranges"] and len(hidden["unavailable_source_ranges"]) == 2
        assert "COMPLETE_END" not in json.dumps(hidden)
        semantic = {"kind": "semantic_interpretation", "record_id": saved["id"]}
        assert service.read_source_materials([semantic, cached[0]])[0] == semantic

    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = service_at(store, tmp_path)
        assert not service.read(saved["id"], 1)["ok"]
        assert service.read_source_materials([material])[0]["visibility"] == "unavailable"
        assert {row["event_id"] for row in service.search_sources("orchard")["raw_events"]} == {
            later["source_ref"]}
