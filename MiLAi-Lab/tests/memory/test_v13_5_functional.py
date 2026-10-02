"""Functional contracts on installed SQLite, synthetic inputs only, denied sockets."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import canonical, namespace
from milai_lab.memory.service import MemoryService

SHA = "a" * 64


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SOCKET_FORBIDDEN")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


@contextmanager
def opened(root: Path, owner: str = "alice", **options: Any) -> Iterator[FunctionalMemory]:
    with SqliteStore.from_conn_string(str(root / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("functional-toy", owner),
            owner,
            root / "service.lock",
            functional_contract="functional_v1",
        )
        yield FunctionalMemory(service, len, **options)


def cfg(message: str = "u", owner: str = "alice") -> dict[str, Any]:
    return {
        "configurable": {
            "user_id": owner,
            "v13_session": "s",
            "v13_turn_id": message,
            "v13_support_config_sha256": SHA,
        }
    }


def turn(memory: FunctionalMemory, message: str = "u", text: str = "公开原文 preference") -> str:
    receipt = memory.service.capture_user("s", message, text)
    assert receipt["ok"]
    memory.context("s", message, SHA)
    return str(receipt["source_ref"])


def handles(memory: FunctionalMemory, ref: str) -> list[str]:
    return [f["fragment_handle"] for f in memory.service.source_fragments(ref)]


def invoke(
    memory: FunctionalMemory,
    tool: str,
    args: dict[str, Any],
    call: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    found = next(t for t in memory.tools() if t.name == tool)
    response = found.invoke(
        {"name": tool, "args": args, "id": call, "type": "tool_call"}, config=config or cfg()
    )
    return json.loads(response.content)


@pytest.mark.parametrize("after_put", [False, True])
@pytest.mark.parametrize("write_phase", ["source", "confirmation"])
def test_m01_actual_sqlite_unknown_capture_does_not_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    after_put: bool,
    write_phase: str,
) -> None:
    with opened(tmp_path) as memory:
        s = memory.service
        original = s.store.put

        def fail(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            if (write_phase == "source" and ns == s.sources_namespace) or (
                write_phase == "confirmation" and key.startswith("capture:")
            ):
                if after_put:
                    original(ns, key, value, **kwargs)
                raise OSError("injected uncertain acknowledgement")
            original(ns, key, value, **kwargs)

        monkeypatch.setattr(s.store, "put", fail)
        result = s.capture_user("s", "u", "actual original")
        assert result["status"] == "outcome_unknown" and not result["ok"]
        ref = result["source_ref"]
        assert (s.store.get(s.sources_namespace, ref) is not None) is (
            after_put or write_phase == "confirmation"
        )
        assert s.source(ref) is None
        with pytest.raises(ValueError, match="SOURCE_UNAVAILABLE"):
            s.source_fragments(ref)
        monkeypatch.setattr(s.store, "put", original)
        assert s.capture_user("s", "u", "actual original")["ok"]
        assert s.source_fragments(ref)[0]["content"] == "actual original"


def test_m02_fresh_subprocess_reopens_source_history_and_read_quota(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        receipt = memory.save(cfg(), "save", "Initial", handles(memory, ref))
        row = memory.service.read(receipt["id"])
        assert (
            memory.update(
                cfg(),
                "patch",
                row["candidate_handle"],
                [{"field": "content", "op": "set", "value": "Revised"}],
                handles(memory, ref),
            )["revision"]
            == 2
        )
        assert not invoke(memory, "read_source", {"fragment_handle": "fake"}, "bad")["ok"]
        record_id = receipt["id"]
    code = """import json,socket,sys
from pathlib import Path
from langgraph.store.sqlite import SqliteStore
from milai_lab.memory.service import MemoryService
from milai_lab.memory.functional import FunctionalMemory

def denied(*a,**k): raise AssertionError("SOCKET_FORBIDDEN")
socket.socket.connect=denied; socket.create_connection=denied
root=Path(sys.argv[1])
with SqliteStore.from_conn_string(str(root/"store.sqlite")) as store:
 s=MemoryService(store,("functional-toy","alice"),"alice",root/"service.lock",functional_contract="functional_v1")
 m=FunctionalMemory(s,len); m.context("s","u","a"*64)
 assert s.read(sys.argv[2])["value"]["content"]=="Revised"
 assert s.read(sys.argv[2],1)["value"]["content"]=="Initial"
 assert s.source(sys.argv[3])["content"]=="公开原文 preference"
 config={"configurable":{"user_id":"alice","v13_session":"s","v13_turn_id":"u","v13_support_config_sha256":"a"*64}}
 for index in range(3):
  result=m._read(config,"fresh"+str(index),{},lambda bound:{"ok":True})
 assert result["status"]=="read_limit_exhausted"
 print("FRESH_PROCESS_PASS")
"""
    result = subprocess.run(  # noqa: S603 -- fixed test code, temporary DB only
        [sys.executable, "-c", code, str(tmp_path), record_id, ref],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "FRESH_PROCESS_PASS"


def test_m03_unicode_exact_fragments_and_program_quotes(tmp_path: Path) -> None:
    text = "中文🙂e\u0301\n第二段 العربية\nfinal"
    with opened(tmp_path, fragment_chars=8) as memory:
        ref = turn(memory, text=text)
        parts = memory.service.source_fragments(ref, max_chars=8)
        assert "".join(f["content"] for f in parts) == text
        for part in parts:
            assert part["content"] == text[part["start"] : part["end"]]
        receipt = memory.save(cfg(), "save", "summary", [parts[1]["fragment_handle"]])
        support = memory.service.read(receipt["id"])["value"]["functional_support"]["content"]
        assert support["quotes"][0]["content"] == parts[1]["content"]
        assert support["semantic_support"] == "unchecked"


def test_m04_handles_roles_and_source_identity_fail_closed(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        handle = handles(memory, ref)[0]
        with pytest.raises(ValueError, match="NOT_ISSUED"):
            memory.service.source_fragment(handle + "x")
        with pytest.raises(ValueError, match="OWNER_MISMATCH"):
            memory.save(cfg(owner="bob"), "x", "bad", [handle])
        with opened(tmp_path, owner="bob") as other:
            with pytest.raises(ValueError, match="NOT_ISSUED"):
                other.service.source_fragment(handle)
        item = memory.service.store.get(memory.service.sources_namespace, ref)
        assert item is not None
        item.value["role"] = "tool"
        memory.service.store.put(memory.service.sources_namespace, ref, item.value, index=False)
        with pytest.raises(ValueError, match="SOURCE_IDENTITY_INVALID"):
            memory.service.source_fragment(handle)


def test_m05_large_source_body_ranking_group_reachability_and_wrapper_limit(tmp_path: Path) -> None:
    text = ("unrelated paragraph " * 100 + "\n") * 9 + "needle exception final requirement\n"
    with opened(tmp_path, fragment_chars=600, read_limit=40) as memory:
        ref = memory.service.capture_user("archive", "large", text)["source_ref"]
        turn(memory, text="needle")
        page = memory.context("s", "u", SHA)
        assert any("needle exception" in u["content"] for u in page["items"])
        assert len(canonical(page)) <= 8192 and page["delivery_status"] == "partial"
        assert any(g["source_ref"] == ref for g in page["source_groups"])
        result = invoke(memory, "read_source", {"source_ref": ref}, "source0")
        delivered = list(result["items"])
        index = 0
        while result["next_cursor"]:
            index += 1
            result = invoke(memory, "read_source", {"cursor": result["next_cursor"]}, str(index))
            assert len(canonical(result)) <= 8192
            delivered += result["items"]
        assert "".join(u["content"] for u in delivered) == text
        assert result["delivery_status"] == "complete_snapshot"


def test_m06_overlap_subtracts_only_exact_version_and_retains_residual(tmp_path: Path) -> None:
    with opened(tmp_path) as base:
        ref = base.service.capture_user("archive", "a", "0123456789🙂XYZ")["source_ref"]
        other = base.service.capture_user("archive", "b", "0123456789🙂XYZ")["source_ref"]
        candidates = [
            {"source_ref": r, "start": a, "end": b, "retrieval_score": score}
            for r, a, b, score in [(ref, 0, 8, 3), (ref, 5, 14, 2), (other, 5, 14, 1)]
        ]
        memory = FunctionalMemory(base.service, len, retrieval_candidates=candidates)
        turn(memory, text="query")
        units = memory.context("s", "u", SHA)["items"]
        parts = [u for u in units if u.get("source_ref") == ref]
        assert [(u["start"], u["end"]) for u in parts] == [(0, 8), (8, 14)]
        assert "".join(u["content"] for u in parts) == "0123456789🙂XYZ"
        assert any(u.get("source_ref") == other for u in units)
        with pytest.raises(ValueError, match="RANGE_INVALID"):
            base.service.source_fragment_range(ref, -1, 9)


def test_m07_ordinary_and_explicit_cursor_do_not_switch_snapshot(tmp_path: Path) -> None:
    with opened(tmp_path, material_limit=3500, fragment_chars=500) as memory:
        ref = memory.service.capture_user("archive", "a", "topic paragraph " * 300)["source_ref"]
        turn(memory, text="topic")
        ordinary = memory.context("s", "u", SHA)
        assert ordinary["next_cursor"]
        explicit = invoke(memory, "search_memory", {"query": "paragraph"}, "search")
        assert explicit["snapshot_id"] != ordinary["snapshot_id"]
        assert memory.context("s", "u", SHA) == ordinary
        page = invoke(memory, "read_memory", {"cursor": ordinary["next_cursor"]}, "next")
        assert page["snapshot_id"] == ordinary["snapshot_id"]
        assert all(u.get("source_ref") == ref for u in page["items"])
        bad = invoke(memory, "read_memory", {"cursor": "snapshot-forged:1"}, "wrong")
        assert bad["status"] == "read_rejected"


def test_m08_m09_nested_patch_noop_history_and_unchanged_leaf_support(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, text="项目仅本季度周二; unrelated inquiry?")
        old_handles = handles(memory, ref)
        receipt = memory.save(
            cfg(),
            "save",
            "review",
            old_handles,
            {"project": {"period": "quarter", "time": "Tuesday"}, "except": None},
        )
        old = memory.service.read(receipt["id"])
        old_support = old["value"]["functional_support"]
        for op, changes in [
            ("empty", []),
            ("same", [{"field": "scope.project.time", "op": "set", "value": "Tuesday"}]),
        ]:
            assert (
                memory.update(cfg(), op, old["candidate_handle"], changes, [])["status"]
                == "no_change"
            )
        newer = turn(memory, "u2", "改为周四;其他不变,顺便问天气?")
        result = memory.update(
            cfg("u2"),
            "patch",
            old["candidate_handle"],
            [{"field": "scope.project.time", "op": "set", "value": "Thursday"}],
            handles(memory, newer),
        )
        assert result["id"] == receipt["id"] and result["revision"] == 2
        current = memory.service.read(receipt["id"])["value"]
        assert current["scope"] == {
            "project": {"period": "quarter", "time": "Thursday"},
            "except": None,
        }
        assert (
            current["functional_support"]["scope.project.period"]
            == old_support["scope.project.period"]
        )
        assert current["functional_support"]["scope.project.time"]["fragment_handles"] == handles(
            memory, newer
        )
        assert (
            memory.service.read(receipt["id"], 1)["value"]["scope"]["project"]["time"] == "Tuesday"
        )
        assert memory.service.history_index(receipt["id"])["revisions"] == [1, 2]


def test_m10_remove_null_absent_and_retract(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "fact", hs, {"a": {"b": "v", "c": "keep"}})

        def patch(op: str, changes: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
            read = memory.service.read(saved["id"])
            return memory.update(cfg(), op, read["candidate_handle"], changes, hs, **kw)

        assert patch("null", [{"field": "scope.a.b", "op": "set", "value": None}])["revision"] == 2
        assert memory.service.read(saved["id"])["value"]["scope"]["a"]["b"] is None
        assert patch("remove", [{"field": "scope.a.b", "op": "remove"}])["revision"] == 3
        row = memory.service.read(saved["id"])["value"]
        assert row["scope"] == {"a": {"c": "keep"}}
        assert "scope.a.b" in row["removed_field_support"]
        assert patch("absent", [{"field": "scope.absent", "op": "remove"}])["status"] == "no_change"
        assert patch("retract", [], retract=True)["revision"] == 4
        assert memory.service.read(saved["id"])["status"] == "retracted"
        assert memory.service.search("fact")["records"] == []
        assert memory.service.read(saved["id"], 1)["value"]["content"] == "fact"
        turn(memory, "query-after-retract", "what about fact?")
        packet = memory.context("s", "query-after-retract", SHA)
        assert any(
            unit["type"] == "withdrawal" and unit["state"] == "withdrawn_not_current_fact"
            for unit in packet["items"]
        )


def test_m11_cas_replay_and_atomic_failed_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "initial", hs)
        old = memory.service.read(saved["id"])
        changes = [{"field": "content", "op": "set", "value": "new"}]
        first = memory.update(cfg(), "patch", old["candidate_handle"], changes, hs)
        assert first["ok"]
        assert memory.update(cfg(), "patch", old["candidate_handle"], changes, hs)["replayed"]
        stale = memory.update(cfg(), "stale", old["candidate_handle"], changes, hs)
        assert not stale["ok"] and stale["reason"] == "revision_conflict"
        current = memory.service.read(saved["id"])
        original = memory.service.store.put

        def fail(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            if ns == memory.service.namespace:
                raise OSError("before single atomic record put")
            original(ns, key, value, **kwargs)

        monkeypatch.setattr(memory.service.store, "put", fail)
        result = invoke(
            memory,
            "update_memory",
            {
                "read_handle": current["candidate_handle"],
                "changes": [
                    {"field": "content", "op": "set", "value": "never"},
                    {"field": "scope.new", "op": "set", "value": "never"},
                ],
                "fragment_handles": hs,
            },
            "failed",
        )
        assert result["status"] == "outcome_unknown"
        assert memory.service.read(saved["id"])["value"] == current["value"]


def test_m12_query_context_is_not_fact_commit_and_explicit_read_failure_counts(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as memory:
        turn(memory, text="what did I say?")
        for _ in range(4):
            memory.context("s", "u", SHA)
        assert memory.service.records() == []
        for index in range(3):
            assert (
                invoke(memory, "read_source", {"fragment_handle": "bogus"}, str(index))["status"]
                == "read_rejected"
            )
        assert (
            invoke(memory, "search_memory", {"query": "anything"}, "four")["status"]
            == "read_limit_exhausted"
        )
        assert memory.service.records() == []


def test_m13_save_commit_unknown_recovery_never_double_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        assert memory.service.sources()[0]["formation_status"] == "pending"
        original = memory.service.store.put

        def uncertain(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            original(ns, key, value, **kwargs)
            if ns == memory.service.namespace:
                raise OSError("actual committed row, lost acknowledgement")

        monkeypatch.setattr(memory.service.store, "put", uncertain)
        args = {"content": "saved only after commit", "fragment_handles": handles(memory, ref)}
        assert invoke(memory, "save_memory", args, "save")["status"] == "outcome_unknown"
        monkeypatch.setattr(memory.service.store, "put", original)
        receipt = invoke(memory, "save_memory", args, "save")
        assert receipt["ok"] and receipt["replayed"] and receipt["revision"] == 1
        assert len(memory.service.records()) == 1
        assert memory.service.sources()[0]["formation_status"] == "formed"


def test_m14_forget_revokes_old_handles_snapshot_raw_and_replay_cache(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, text="private preference")
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "private preference", hs)
        turn(memory, "u2", "forget private preference")
        cached = memory.context("s", "u2", SHA)
        row = memory.service.read(saved["id"])
        explicit = invoke(memory, "read_source", {"fragment_handle": hs[0]}, "read", cfg("u2"))
        assert explicit["ok"]
        receipt = invoke(
            memory, "forget_memory", {"read_handle": row["candidate_handle"]}, "forget", cfg("u2")
        )
        assert receipt["ok"] and receipt["forget_epoch"] == 1
        assert "private preference" not in canonical(receipt)
        assert memory.service.source(ref) is None
        assert memory.service.read(saved["id"], 1)["status"] == "visibility_revoked"
        assert memory.service.history_index(saved["id"])["status"] == "visibility_revoked"
        assert memory.service.candidate(row["candidate_handle"]) is None
        with pytest.raises(ValueError, match="SOURCE_UNAVAILABLE"):
            memory.service.source_fragment(hs[0])
        with pytest.raises(ValueError, match="REPLAY_REVOKED"):
            invoke(memory, "read_source", {"fragment_handle": hs[0]}, "read", cfg("u2"))
        assert all(r["event_id"] != ref for r in memory.service.search("private")["raw_events"])
        new = memory.context("s", "u2", SHA)
        assert new["snapshot_id"] != cached["snapshot_id"]
        assert all(u.get("source_ref") != ref for u in new["items"])
        assert memory.service.store.get(memory.service.sources_namespace, ref) is not None
        assert (
            memory.service.store.get(namespace(memory.service), cached["snapshot_id"]) is not None
        )


def test_history_body_cursor_stays_on_issued_versions_after_later_update(tmp_path: Path) -> None:
    with opened(tmp_path, material_limit=3500, fragment_chars=300, read_limit=20) as memory:
        ref = turn(memory)
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "version1 " * 30, hs)
        for index in range(2, 9):
            row = memory.service.read(saved["id"])
            result = memory.update(
                cfg(),
                str(index),
                row["candidate_handle"],
                [{"field": "content", "op": "set", "value": f"version{index} " * 30}],
                hs,
            )
            assert result["ok"]
        first = invoke(
            memory, "read_memory", {"record_id": saved["id"], "history": True}, "history"
        )
        assert first["items"] and first["next_cursor"]
        row = memory.service.read(saved["id"])
        memory.update(
            cfg(),
            "later",
            row["candidate_handle"],
            [{"field": "content", "op": "set", "value": "version9"}],
            hs,
        )
        units = first["items"][:]
        page = first
        index = 0
        while page["next_cursor"]:
            index += 1
            page = invoke(memory, "read_memory", {"cursor": page["next_cursor"]}, f"page{index}")
            assert page["snapshot_id"] == first["snapshot_id"]
            units.extend(page["items"])
        assert {u["revision"] for u in units} == set(range(1, 9))
        assert all(u["version_view"] == "historical_exact_revision" for u in units)
        assert "version1" in units[0]["content"]


def test_raw_only_source_forget_is_visible_and_replayable(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = memory.service.capture_user("old", "raw", "raw pending secret")["source_ref"]
        hs = handles(memory, ref)
        turn(memory, text="forget the old raw source")
        args = {"fragment_handles": hs}
        result = invoke(memory, "forget_memory", args, "forget")
        assert result["ok"] and ref in result["revoked_source_refs"]
        assert result["source_visibility_scope"] == "selected_support_trigger_and_assistant_outputs"
        assert result["revoked_ids"] == []
        assert invoke(memory, "forget_memory", args, "forget")["replayed"]
        assert memory.service.source(ref) is None
        assert all(row["event_id"] != ref for row in memory.service.sources())


def test_source_body_version_and_fixed_pool_tamper_are_rejected(tmp_path: Path) -> None:
    with opened(tmp_path) as base:
        ref = base.service.capture_user("old", "raw", "Original bytes")["source_ref"]
        memory = FunctionalMemory(
            base.service,
            len,
            retrieval_candidates=[
                {"source_ref": ref, "start": 0, "end": 8, "retrieval_score": 1.0}
            ],
        )
        turn(memory)
        assert memory.retrieval_candidates is not None
        memory.retrieval_candidates[0]["start"] = 1
        with pytest.raises(ValueError, match="CANDIDATES_CHANGED"):
            memory._search_units("query")
        fragment = base.service.source_fragments(ref)[0]
        source = base.service.store.get(base.service.sources_namespace, ref)
        assert source is not None
        source.value["content"] = "Tampered bytes"
        base.service.store.put(base.service.sources_namespace, ref, source.value, index=False)
        with pytest.raises(ValueError, match="CONFIRMATION_CHANGED"):
            base.service.source_fragment(fragment["fragment_handle"])


def test_m14_exposed_query_assistant_and_forget_trigger_stay_hidden_after_reopen(
    tmp_path: Path,
) -> None:
    secret = "SEKRET-LITERAL-431"
    with opened(tmp_path) as memory:
        ref = turn(memory, "remember", "password " + secret)
        saved = memory.save(cfg("remember"), "save", "password " + secret, handles(memory, ref))
        exposed_query = turn(memory, "query", "what password did I give?")
        assert secret in canonical(memory.context("s", "query", SHA))
        assistant = memory.service.capture_assistant("s", "query:final", "It was " + secret)
        assert assistant["ok"]
        trigger = turn(memory, "forget", "forget password " + secret)
        handle = memory.service.read(saved["id"])["candidate_handle"]
        forgotten = invoke(
            memory, "forget_memory", {"read_handle": handle}, "forget-op", cfg("forget")
        )
        assert {ref, assistant["source_ref"], trigger} <= set(forgotten["revoked_source_refs"])
        assert exposed_query not in forgotten["revoked_source_refs"]
        assert secret not in canonical(memory.context("s", "forget", SHA))
        assert memory.service.public_turn("s", message_id="forget") is not None
        with pytest.raises(ValueError, match="SOURCE_UNAVAILABLE"):
            memory.service.source_fragments(trigger)
        final = memory.service.capture_assistant("s", "forget:final", "Forgot " + secret)
        assert final["ok"] and final["visibility"] == "revoked"
        assert memory.service.source(final["source_ref"]) is None
        assert (
            memory.service.store.get(memory.service.sources_namespace, final["source_ref"])
            is not None
        )
    with opened(tmp_path) as reopened:
        # Same-message recovery validates the original public input without making it retrievable.
        assert reopened.service.capture_user("s", "forget", "forget password " + secret)["ok"]
        reopened.service.bind_source_boundary("s", "forget", [trigger])
        assert secret not in canonical(reopened.context("s", "forget", SHA))
        fresh = reopened.service.capture_user(
            "new-session", "query", "what password is remembered?"
        )
        assert fresh["ok"]
        packet = reopened.context("new-session", "query", SHA)
        assert secret not in canonical(packet)
        assert secret not in canonical(reopened.service.sources())
        for hidden in (ref, assistant["source_ref"], trigger, final["source_ref"]):
            assert reopened.service.source(hidden) is None
    code = """import json,socket,sys
from pathlib import Path
from langgraph.store.sqlite import SqliteStore
from milai_lab.memory.service import MemoryService
from milai_lab.memory.functional import FunctionalMemory

def denied(*a,**k): raise AssertionError("SOCKET_FORBIDDEN")
socket.socket.connect=denied; socket.create_connection=denied
root=Path(sys.argv[1])
with SqliteStore.from_conn_string(str(root/"store.sqlite")) as store:
 s=MemoryService(store,("functional-toy","alice"),"alice",root/"service.lock",functional_contract="functional_v1")
 m=FunctionalMemory(s,len)
 assert s.capture_user("fresh-process","query","What preferences remain?")["ok"]
 packet=m.context("fresh-process","query","a"*64)
 assert "SEKRET-LITERAL-431" not in json.dumps(packet)
 assert "SEKRET-LITERAL-431" not in json.dumps(s.sources())
 assert s.forget_epoch>0
 print("FRESH_PROCESS_FORGET_PASS")
"""
    result = subprocess.run(  # noqa: S603 -- fixed test code and isolated temporary DB
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "FRESH_PROCESS_FORGET_PASS"


def test_forget_does_not_derive_independent_user_b_from_prefetched_a(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        a = turn(memory, "a", "marker record A belongs to Alpha")
        a_record = memory.save(cfg("a"), "save-a", "marker record A", handles(memory, a))
        b = turn(memory, "b", "marker record B belongs to Beta")
        b_packet = memory.context("s", "b", SHA)
        assert any(unit.get("source_ref") == a for unit in b_packet["items"])
        b_record = memory.save(cfg("b"), "save-b", "marker record B", handles(memory, b))
        assert memory.service.read(b_record["id"])["value"]["source_refs"] == [b]
        turn(memory, "forget-a", "Forget marker record A")
        receipt = invoke(
            memory,
            "forget_memory",
            {"read_handle": memory.service.read(a_record["id"])["candidate_handle"]},
            "forget-a",
            cfg("forget-a"),
        )
        assert receipt["ok"] and b not in receipt["revoked_source_refs"]
        assert memory.service.source(b) is not None
        assert memory.service.read(b_record["id"])["ok"]
        assert (
            memory.service.source_fragment(handles(memory, b)[0])["content"]
            == "marker record B belongs to Beta"
        )
        assert memory.service.source(a) is None


def test_known_independent_copy_requires_explicit_additional_fragment_selection(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, "save", "private marker literal")
        saved = memory.save(cfg("save"), "save", "private marker literal", handles(memory, ref))
        copy_ref = memory.service.capture_user("other", "copy", "private marker literal")[
            "source_ref"
        ]
        copy_handles = handles(memory, copy_ref)
        turn(memory, "forget", "forget specified memory and this independently supplied copy")
        receipt = invoke(
            memory,
            "forget_memory",
            {
                "read_handle": memory.service.read(saved["id"])["candidate_handle"],
                "additional_fragment_handles": copy_handles,
            },
            "forget",
            cfg("forget"),
        )
        assert receipt["ok"] and copy_ref in receipt["revoked_source_refs"]
        assert receipt["independent_input_copies"] == "require_explicit_fragment_selection"
        assert receipt["scope_counts"]["explicit_support_sources"] == 2
        assert memory.service.source(copy_ref) is None
