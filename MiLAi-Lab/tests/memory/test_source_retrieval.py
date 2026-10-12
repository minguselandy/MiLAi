"""Source-first retrieval on temporary SQLite, without model or external I/O."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.service import MemoryService


def service_at(store: SqliteStore, root: Path) -> MemoryService:
    return MemoryService(store, ("source-retrieval", "alice"), "alice", root / "memory.lock",
                         functional_contract="functional_v1", memory_profile="unified_v1")


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
