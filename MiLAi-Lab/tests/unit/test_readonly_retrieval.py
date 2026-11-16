"""Actual SQLite write prohibition, prebuilt Views and task-local references."""
import json
import sqlite3

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import FunctionalRejection, canonical
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import FixedContextMemoryPolicy, RulesMemoryPolicy
from milai_lab.methods.query_structure import build_query_structure
from milai_lab.methods.readonly_retrieval import (
    ReadOnlyMemoryService,
    ReadOnlyRetrieval,
    open_readonly_store,
)
from milai_lab.runners.state_bench_adapter import StateReadOnlyMemoryHook


def service(store, root, *, readonly=False):
    cls = ReadOnlyMemoryService if readonly else MemoryService
    return cls(store, ("readonly-test", "alice"), "alice", root / "lock",
               functional_contract="functional_v1")


def freeze(store):
    before = list(store.conn.iterdump())
    store.conn.execute("PRAGMA query_only=ON")
    return before


def test_prebuilt_artifact_opens_with_sqlite_readonly_uri(tmp_path):
    path = tmp_path / "training.sqlite"
    with SqliteStore.from_conn_string(str(path)) as store:
        service(store, tmp_path).capture_user("train", "source", "Cedar code is 4312.")
    before = path.read_bytes()
    with open_readonly_store(path) as store:
        readonly = service(store, tmp_path, readonly=True)
        memory = ReadOnlyRetrieval(readonly, len, FixedContextMemoryPolicy())
        memory.begin_turn("test")
        packet = memory.retrieve(RetrievalRequest(query="Cedar code"))
        assert "4312" in canonical(packet)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.put(("forbidden",), "test", {"content": "Do not persist"})
    assert path.read_bytes() == before


def test_queries_and_actual_tool_observations_never_enter_training_artifact(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        writer = service(store, tmp_path)
        writer.capture_user("train", "source", "The historical Cedar code is 4312.")
        readonly = service(store, tmp_path, readonly=True)
        events = []
        memory = ReadOnlyRetrieval(readonly, len, FixedContextMemoryPolicy(),
                                   material_limit=1800, record=events.append)
        hook = StateReadOnlyMemoryHook(memory, session="test-task", now="2030-01-01",
            domain="travel", user_id="current-user", record=events.append)
        before = freeze(store)
        conversation = [{"role": "user", "content": "TEST_SECRET_9999. Retrieve Cedar code."}]
        assert hook.bind_conversation(conversation)
        reply = hook.retrieve({"query": "Cedar code", "top_k": 99})
        assert isinstance(reply, list) and len(reply) <= 3
        packet = json.loads(reply[0])
        assert "4312" in canonical(packet) and len(canonical(reply)) <= 1800
        remaining = memory.remaining_reads
        conversation += [{"role": "assistant", "content": "Test answer", "tool_calls": [
            {"name": "update", "arguments": {}, "result": {"code": "TEST_TOOL_9999"}}]}]
        assert not hook.bind_conversation(conversation)
        assert memory.remaining_reads == remaining
        conversation.append({"role": "user", "content": "Remember TEST_NEW_9999 instead."})
        assert hook.bind_conversation(conversation)
        again = hook.retrieve({"query": "Cedar code"})
        assert "TEST_" not in canonical(again)
        assert list(store.conn.iterdump()) == before
        assert len(readonly.sources()) == 1
        assert not any(a["kind"] == "REFRESH_VIEW" for e in events
                       if e.get("phase") == "decision_input" for a in e["actions"])
        assert memory.snapshots and hook.references  # Ephemeral real delivery references.
        foreign = ReadOnlyRetrieval(readonly, len, FixedContextMemoryPolicy())
        foreign.begin_turn("turn-1")
        with pytest.raises(FunctionalRejection, match="REFERENCE_NOT_DELIVERED"):
            foreign.retrieve(RetrievalRequest.model_validate({"query": "Cedar code",
                "task_context": {"known_evidence_refs": hook.references}}))


def test_prebuilt_multislot_view_can_be_used_without_recency_or_refresh_writes(tmp_path):
    class UseCurrent:
        def choose(self, state, actions):
            assert not any(a.kind == "REFRESH_VIEW" for a in actions)
            return next((a.id for a in actions if a.kind == "USE_VIEW"
                         and a.parameters.get("slot") == "current"), "handoff")

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        writer = service(store, tmp_path)
        ref = writer.capture_user("train", "source", "The limit is 40 if both approvals hold.")[
            "source_ref"]

        def generate(messages, _schema):
            data = json.loads(messages[-1]["content"])
            return {"scope": "Approval limits", "nodes": [{"id": "n0", "kind": "reported",
                "text": data["sources"][0]["text"], "evidence": [data["sources"][0]["id"]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        for slot in ["current", "slot1"]:
            build_query_structure(writer, "limit", "", [ref], policy="incremental",
                                   call=generate, capacity=2, slot=slot)
        readonly = service(store, tmp_path, readonly=True)
        memory = ReadOnlyRetrieval(readonly, len, UseCurrent(),
                                   material_limit=2500, view_capacity=2)
        before = freeze(store)
        memory.begin_turn("turn-1")
        packet = memory.retrieve(RetrievalRequest(query="limit"))
        assert packet["evidence"][0]["kind"] == "query_structure"
        assert "both approvals" in canonical(packet)
        assert list(store.conn.iterdump()) == before


def test_semantic_reads_and_paged_history_issue_no_persistent_credentials(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        writer = service(store, tmp_path)
        memory = FunctionalMemory(writer, len, material_limit=24000)

        def capture(key, text):
            ref = writer.capture_user("train", key, text)["source_ref"]
            writer.bind_source_boundary("train", key, [ref])
            writer.bind_public_turn("train", key, ref, config_version="train", phase="start")
            cfg = {"configurable": {"user_id": "alice", "v13_session": "train",
                "v13_turn_id": key, "v13_config_version": "train"}}
            return writer.source_fragments(ref)[0]["fragment_handle"], cfg

        fragment, cfg = capture("first", "Run twice weekly; start date unknown.")
        saved = memory.save(cfg, "save", "Run twice weekly; start date unknown.", [fragment])
        handle = writer.read(saved["id"])["candidate_handle"]
        correction, cfg = capture("second", "Run three times weekly; date still unknown.")
        changed = memory.update(cfg, "change", handle, [{"field": "content", "op": "set",
            "value": "Run three times weekly; date still unknown.",
            "fragment_handles": [correction]}])
        assert changed["ok"]
        readonly = service(store, tmp_path, readonly=True)
        before = freeze(store)
        assert "candidate_handle" not in readonly.read(saved["id"])
        first = readonly.history_index(saved["id"], limit=1)
        second = readonly.history_index(saved["id"], cursor=first["next_cursor"], limit=1)
        assert first["revisions"] == [1] and second["revisions"] == [2]
        assert "twice" in readonly.read(saved["id"], 1)["value"]["content"]
        retrieval = ReadOnlyRetrieval(readonly, len, RulesMemoryPolicy(), material_limit=8000)
        retrieval.begin_turn("query")
        packet = retrieval.retrieve(RetrievalRequest.model_validate({"query": "weekly",
            "read_goal": {"evidence": ["saved_history"]}}))
        assert "twice" in canonical(packet)
        assert list(store.conn.iterdump()) == before


def test_readonly_known_refs_share_turn_allowance_and_recheck_revocation(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        writer = service(store, tmp_path)
        ref = writer.capture_user("train", "source", "PRIVATE_CODE_4312 is the Cedar code.")[
            "source_ref"]
        fragment = writer.source_fragments(ref)[0]["fragment_handle"]
        readonly = service(store, tmp_path, readonly=True)
        memory = ReadOnlyRetrieval(readonly, len, FixedContextMemoryPolicy(), read_limit=3)
        memory.begin_turn("turn-1")
        before = freeze(store)
        first = memory.retrieve(RetrievalRequest(query="Cedar code"))
        assert first["evidence"] and memory.remaining_reads == 0
        known = [e["ref"] for e in first["evidence"]]
        memory.begin_turn("turn-1")
        exhausted = memory.retrieve(RetrievalRequest.model_validate({"query": "Cedar code",
            "task_context": {"known_evidence_refs": known}}))
        assert not exhausted["ok"] and not exhausted["evidence"]
        assert exhausted["usage"]["read_operations"] == 0
        assert list(store.conn.iterdump()) == before
        store.conn.execute("PRAGMA query_only=OFF")
        writer.forget("admin", "revoke", fragment_handles=[fragment])
        revoked = freeze(store)
        memory.begin_turn("turn-2")
        result = memory.retrieve(RetrievalRequest.model_validate({"query": "Cedar code",
            "task_context": {"known_evidence_refs": known}}))
        assert "PRIVATE_CODE_4312" not in canonical(result)
        assert list(store.conn.iterdump()) == revoked
