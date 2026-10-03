"""Functional contracts on installed SQLite, synthetic inputs only, denied sockets."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.store.sqlite import SqliteStore
from pydantic import ValidationError

from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import FunctionalRejection, canonical, namespace
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


def test_unified_assertion_rejects_split_scope_and_preserves_explicit_body_on_reopen(
    tmp_path: Path,
) -> None:
    body = "Only during this particular review, use short answers; other meetings are unchanged."
    with opened(tmp_path, formation_interface="unified_assertion_v1") as memory:
        ref = turn(memory, text=body)
        args = {"content": body, "fragment_handles": handles(memory, ref)}
        with pytest.raises(ValidationError, match="Extra inputs"):
            invoke(memory, "save_memory", {**args, "scope": {"context": "review"}}, "bad")
        assert memory.service.records() == []
        receipt = invoke(memory, "save_memory", args, "save")
        assert receipt["status"] == "committed"
    with opened(tmp_path, formation_interface="unified_assertion_v1") as memory:
        row = memory.service.read(receipt["id"])
        assert row["value"]["content"] == body and row["value"]["scope"] == {}
        assert row["value"]["functional_support"]["content"]["quotes"][0]["content"] == body


def assert_read_delivery(packet: dict[str, Any]) -> None:
    items = packet.get("items", [])
    ids = list(dict.fromkeys(u["record_id"] for u in items if u["type"] == "record"))
    assert packet["operation_effect"] == "read_only"
    assert packet["semantic_write_performed"] is False
    assert packet["delivered_semantic_record_ids"] == ids
    assert packet["delivered_semantic_record_count"] == len(ids)
    assert packet["delivered_semantic_record_units"] == sum(u["type"] == "record" for u in items)
    assert packet["delivered_raw_fragment_count"] == sum(u["type"] == "fragment" for u in items)
    assert packet["delivery_count_scope"] == "this_packet_items_only_not_owner_total_or_writes"


def test_read_only_raw_searches_are_not_formation_and_snapshot_counts_stay_fixed(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, text="public synthetic marker")
        ordinary = memory.context("s", "u", SHA)
        for packet in [ordinary, *[
            invoke(memory, "search_memory", {"query": "synthetic marker"}, f"search-{i}")
            for i in range(2)
        ]]:
            assert_read_delivery(packet)
            assert packet["delivered_semantic_record_count"] == 0
            assert packet["delivered_raw_fragment_count"] > 0
            assert {u["source_ref"] for u in packet["items"]} == {ref}
        assert memory.service.records() == []
        committed = memory.save(cfg(), "actual-save", "synthetic marker", handles(memory, ref))
        assert committed["ok"] and committed["status"] == "committed"
        assert memory.context("s", "u", SHA) == ordinary
        read = invoke(memory, "read_memory", {"record_id": committed["id"]}, "record")
        assert_read_delivery(read)
        assert read["delivered_semantic_record_ids"] == [committed["id"]]
        assert read["delivered_raw_fragment_count"] == 0
        refused = invoke(memory, "read_source", {"fragment_handle": "unknown"}, "over-limit")
        assert refused["status"] == "read_limit_exhausted" and not refused["ok"]
        assert_read_delivery(refused)
        assert len(memory.service.records()) == 1


def test_read_delivery_metadata_is_budgeted_for_mixed_immutable_pages(tmp_path: Path) -> None:
    with opened(tmp_path, material_limit=3500, fragment_chars=240, read_limit=40) as memory:
        ref = turn(memory, text="synthetic source " * 90)
        saved = memory.save(cfg(), "save", "synthetic record " * 80, handles(memory, ref))
        turn(memory, "query", "synthetic")
        page = memory.context("s", "query", SHA)
        snapshot = memory.service.store.get(namespace(memory.service), page["snapshot_id"])
        assert snapshot is not None
        original_items = snapshot.value["items"]
        delivered = []
        index = 0
        assert page["next_cursor"] is not None
        while True:
            assert_read_delivery(page)
            assert len(canonical(page)) <= memory.material_limit
            assert page["items"]
            assert page["items"] == original_items[page["start"]:
                                                  page["start"] + len(page["items"])]
            delivered.extend(page["items"])
            if page["next_cursor"] is None:
                break
            index += 1
            page = invoke(memory, "read_memory", {"cursor": page["next_cursor"]},
                          f"page-{index}", cfg("query"))
        assert delivered == original_items
        assert any(u["type"] == "fragment" for u in delivered)
        chunks = [u for u in delivered if u["type"] == "record"]
        assert len(chunks) > 1 and {u["record_id"] for u in chunks} == {saved["id"]}
        assert "".join(u["content"] for u in sorted(chunks, key=lambda u: u["content_range"])) == (
            memory.service.read(saved["id"])["value"]["content"]
        )
        failed = invoke(memory, "read_source", {"fragment_handle": "unknown"},
                        "failed", cfg("query"))
        assert failed["status"] == "read_rejected" and not failed["ok"]
        assert_read_delivery(failed)
        assert len(canonical(failed)) <= memory.material_limit


def test_same_public_save_is_idempotent_across_tool_ids_and_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, text="Synthetic preference")
        args = {"content": "Synthetic preference", "fragment_handles": handles(memory, ref),
                "scope": {"project": "local"}}
        first = invoke(memory, "save_memory", args, "call-one")
    with opened(tmp_path) as memory:
        memory.context("s", "u", SHA)
        repeat = invoke(memory, "save_memory", args, "call-two")
        assert repeat["status"] == "no_change" and repeat["effect"] == "none"
        assert repeat["id"] == first["id"] and repeat["revision"] == 1
        assert repeat["duplicate_request"] and repeat["existing_record"]
        assert len(memory.service.records()) == 1
        assert memory.service.history_index(first["id"])["revisions"] == [1]
        replay = invoke(memory, "save_memory", args, "call-two")
        assert replay["replayed"] and replay["effect"] == "none"
        conflicting = invoke(memory, "save_memory", {**args, "content": "changed"}, "call-one")
        assert conflicting["status"] == "rejected"
        assert conflicting["reason"] == "proposal_id_conflict"


@pytest.mark.parametrize("difference", ["content", "scope", "fragments", "public_turn"])
def test_exact_save_guard_does_not_merge_different_requests(
    tmp_path: Path, difference: str,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory, text="Synthetic preference")
        args = {"content": "Synthetic preference", "fragment_handles": handles(memory, ref),
                "scope": {"project": "local"}}
        first = invoke(memory, "save_memory", args, "call-one")
        config = cfg()
        if difference == "content":
            args["content"] = "Different preference"
        elif difference == "scope":
            args["scope"] = {"project": "other"}
        elif difference == "fragments":
            other = memory.service.capture_user("archive", "other", "Synthetic preference")
            args["fragment_handles"] = handles(memory, other["source_ref"])
        else:
            turn(memory, "another", "New independent request")
            config = cfg("another")
        second = invoke(memory, "save_memory", args, "call-two", config)
        assert second["status"] == "committed" and second["id"] != first["id"]
        assert len(memory.service.records()) == 2


def test_duplicate_save_cannot_restore_an_old_value_after_update(tmp_path: Path) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        hs = handles(memory, ref)
        args = {"content": "old", "fragment_handles": hs}
        first = invoke(memory, "save_memory", args, "one")
        read = memory.service.read(first["id"])
        memory.update(cfg(), "update", read["candidate_handle"],
                      [{"field": "content", "op": "set", "value": "new"}], hs)
        repeated = invoke(memory, "save_memory", args, "two")
        assert repeated["status"] == "rejected" and repeated["effect"] == "none"
        assert repeated["reason"] == "duplicate_save_target_changed_or_hidden"
        assert len(memory.service.records()) == 1
        assert memory.service.read(first["id"])["value"]["content"] == "new"


def test_correction_fragment_selection_is_explicit_not_inferred_from_trigger(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as memory:
        original = turn(memory, text="synthetic value A")
        old_handles = handles(memory, original)
        saved = memory.save(cfg(), "save", "synthetic value A", old_handles, {"project": "local"})
        row = memory.service.read(saved["id"])
        corrected = turn(memory, "correction", "synthetic value B")
        new_handles = handles(memory, corrected)
        result = memory.update(cfg("correction"), "correct", row["candidate_handle"],
            [{"field": "content", "op": "set", "value": "synthetic value B"}], new_handles)
        assert result["ok"] and result["fragment_provenance_verified"]
        version = memory.service.read(saved["id"])["value"]
        assert version["functional_support"]["content"]["fragment_handles"] == new_handles
        assert version["functional_support"]["scope.project"]["fragment_handles"] == old_handles
        # A later execution trigger alone never becomes evidence for a changed field.
        unused = turn(memory, "other", "independent current request")
        current = memory.service.read(saved["id"])
        again = memory.update(cfg("other"), "explicit-support", current["candidate_handle"],
            [{"field": "content", "op": "set", "value": "value B"}], new_handles)
        assert again["ok"]
        support = memory.service.read(saved["id"])["value"]["functional_support"]["content"]
        assert support["fragment_handles"] == new_handles
        assert unused not in support["source_refs"]
        packet = invoke(memory, "read_memory", {"record_id": saved["id"]}, "read", cfg("other"))
        assert packet["semantic_support"] == "unchecked"
        assert packet["evidence_contract"]["trigger_binding"] == (
            "execution_attribution_not_field_evidence"
        )
        descriptions = {t.name: t.description for t in memory.tools()}
        assert "directly support the new content" in descriptions["save_memory"]
        assert "NEW changed value" in descriptions["update_memory"]
        assert "not automatically" in descriptions["update_memory"]
        assert "Search never saves or updates" in descriptions["search_memory"]


def test_public_update_selects_evidence_per_field_and_retains_unchanged_history(
    tmp_path: Path,
) -> None:
    with opened(tmp_path) as memory:
        initial = turn(memory, text="Distance in miles; project Alpha; weekdays only.")
        original = handles(memory, initial)
        saved = memory.save(cfg(), "save", "Distance in miles.", original,
                            {"project": "Alpha", "days": "weekdays", "nested": {"only": "old"}})
        correction = turn(memory, "change", "Use kilometers; remove the old nested limit.")
        project = memory.service.capture_user("archive", "scope", "The project is now Beta.")
        corrected, scoped = handles(memory, correction), handles(memory, project["source_ref"])
        current = memory.service.read(saved["id"])
        changes = [
            {"field": "content", "op": "set", "value": "Distance in kilometers.",
             "fragment_handles": corrected},
            {"field": "scope.project", "op": "set", "value": "Beta", "fragment_handles": scoped},
            {"field": "scope.nested.only", "op": "remove", "fragment_handles": corrected},
        ]
        response = invoke(memory, "update_memory", {
            "read_handle": current["candidate_handle"], "changes": changes},
            "update", cfg("change"))
        assert response["ok"] and response["id"] == saved["id"] and response["revision"] == 2
        value = memory.service.read(saved["id"])["value"]
        supports = value["functional_support"]
        assert supports["content"]["fragment_handles"] == corrected
        assert supports["scope.project"]["fragment_handles"] == scoped
        assert supports["scope.days"]["fragment_handles"] == original
        assert supports["scope.nested"]["fragment_handles"] == corrected
        assert value["scope"] == {"project": "Beta", "days": "weekdays", "nested": {}}
        assert value["removed_field_support"]["scope.nested.only"]["fragment_handles"] == corrected
        assert all(s["semantic_support"] == "unchecked" for s in supports.values())
        assert memory.service.read(saved["id"], 1)["value"] == current["value"]
        read = memory.service.read(saved["id"])
        unchanged = invoke(memory, "update_memory", {
            "read_handle": read["candidate_handle"], "changes": [
                {"field": "content", "op": "set", "value": value["content"],
                 "fragment_handles": []}]}, "no-change", cfg("change"))
        assert unchanged["status"] == "no_change" and unchanged["revision"] == 2
        assert memory.service.history_index(saved["id"])["revisions"] == [1, 2]
        packet = memory.context("s", "change", SHA)
        assert all(u["input_relation"] == ("current_request" if u["source_ref"] == correction
                   else "archived_source") for u in packet["items"] if u["type"] == "fragment")


@pytest.mark.parametrize("bad", ["missing", "empty", "unknown", "global"])
def test_public_update_cannot_borrow_another_changes_evidence(tmp_path: Path, bad: str) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "old", hs, {"project": "Alpha"})
        old = memory.service.read(saved["id"])
        changes = [{"field": "content", "op": "set", "value": "new", "fragment_handles": hs},
                   {"field": "scope.project", "op": "set", "value": "Beta"}]
        if bad != "missing":
            changes[1]["fragment_handles"] = [] if bad == "empty" else ["unknown"]
        args = {"read_handle": old["candidate_handle"], "changes": changes}
        if bad == "global":
            args["fragment_handles"] = hs
        if bad == "missing":
            with pytest.raises(ValidationError, match="fragment_handles"):
                invoke(memory, "update_memory", args, "bad")
        else:
            result = invoke(memory, "update_memory", args, "bad")
            assert result["status"] == "rejected" and result["effect"] == "none"
        assert memory.service.read(saved["id"])["value"] == old["value"]
        assert memory.service.history_index(saved["id"])["revisions"] == [1]


@pytest.mark.parametrize("corrupt", [None, "source_sha256", "body_text_sha256", "span_sha256"])
def test_frozen_candidate_hash_metadata_binds_exact_body_range(
    tmp_path: Path, corrupt: str | None,
) -> None:
    with opened(tmp_path) as base:
        ref = base.service.capture_user("archive", "a", "prefix\r\n🙂literal body\r\nsuffix")[
            "source_ref"]
        fragment = base.service.source_fragment_range(ref, 8, 20)
        candidate = {key: fragment[key] for key in (
            "source_ref", "start", "end", "source_sha256", "body_text_sha256", "span_sha256")}
        candidate["retrieval_score"] = 0.75
        if corrupt:
            candidate[corrupt] = "0" * 64
            with pytest.raises(FunctionalRejection, match="CANDIDATE_HASH_MISMATCH"):
                FunctionalMemory(base.service, len, retrieval_candidates=[candidate])
            return
        memory = FunctionalMemory(base.service, len, retrieval_candidates=[candidate])
        turn(memory, text="Read the supplied material")
        units = memory.context("s", "u", SHA)["items"]
        selected = [u for u in units if u.get("source_ref") == ref]
        assert len(selected) == 1 and selected[0]["content"] == fragment["content"]
        assert (selected[0]["start"], selected[0]["end"]) == (8, 20)
        assert memory.retrieval_candidates == [candidate]


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
                    {"field": "content", "op": "set", "value": "never", "fragment_handles": hs},
                    {"field": "scope.new", "op": "set", "value": "never", "fragment_handles": hs},
                ],
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


def test_validation_refusal_and_read_storage_value_error_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        refused = invoke(memory, "save_memory", {"content": "", "fragment_handles": []}, "bad")
        assert refused["status"] == "rejected" and refused["effect"] == "none"
        assert refused["phase"] == "pre_mutation_contract"
        assert memory.service.records() == []
        fragment = handles(memory, ref)[0]
        original = memory.service.store.get

        def failed(ns: tuple[str, ...], key: str) -> Any:
            if key == fragment:
                raise ValueError("storage decoding failure, not caller validation")
            return original(ns, key)

        monkeypatch.setattr(memory.service.store, "get", failed)
        result = invoke(memory, "read_source", {"fragment_handle": fragment}, "read")
        assert result["status"] == "read_outcome_unknown"
        assert result["error_type"] == "ValueError" and result["read_state_effect"] == "unconfirmed"
        assert_read_delivery(result)
        monkeypatch.setattr(memory.service.store, "get", original)
        assert invoke(memory, "read_source", {"fragment_handle": fragment}, "read") == result


def check_oversized_metadata_progress(root: Path, token_count: Callable[[str], int]) -> None:
    """Shared mechanical probe; also run with the pinned provider tokenizer locally."""
    with opened(root, material_limit=8192, read_limit=3) as memory:
        memory.token_count = token_count
        ref = turn(memory)
        hs = handles(memory, ref)
        big = memory.save(cfg(), "big", "Oversized scope record", hs,
                          {"context": "public scope 0123456789 " * 10000})
        small = memory.save(cfg(), "small", "Small reachable record", hs)
        bound = memory._binding(cfg())
        units = [*memory._record_units(memory.service.read(big["id"])),
                 *memory._record_units(memory.service.read(small["id"]))]
        key = memory._snapshot(bound, units, "explicit_oversize_probe")
        page = memory._page(key, 0, bound)
        assert page["skipped_units"][0]["unit_index"] == 0
        assert page["skipped_units"][0]["reason"] == "unit_exceeds_material_limit"
        assert page["skipped_units"][0]["required_packet_tokens"] > memory.material_limit
        assert page["skipped_units"][0]["snapshot_body_delivered"] is False
        delivered = list(page["items"])
        for index in range(3):
            assert token_count(canonical(page)) <= memory.material_limit
            assert page["examined_units"] > 0
            if page["next_cursor"] is None:
                break
            assert int(page["next_cursor"].rpartition(":")[2]) > page["start"]
            page = invoke(memory, "read_memory", {"cursor": page["next_cursor"]}, f"p{index}")
            delivered.extend(page["items"])
        assert page["next_cursor"] is None
        assert [unit["record_id"] for unit in delivered] == [small["id"]]
        assert memory.service.store.get(namespace(memory.service), key).value["items"] == units
        alone = memory._snapshot(bound, units[:1], "only_oversized_unit")
        terminal = memory._page(alone, 0, bound)
        assert terminal["next_cursor"] is None and terminal["items"] == []
        assert terminal["delivery_status"] == "snapshot_end_with_omissions"
        assert terminal["omitted_units"] == 1 and terminal["examined_units"] == 1
        assert token_count(canonical(terminal)) <= memory.material_limit


def test_oversized_first_unit_does_not_block_later_record(tmp_path: Path) -> None:
    check_oversized_metadata_progress(tmp_path, len)


@pytest.mark.parametrize("after_put", [False, True])
def test_read_receipt_persistence_failure_keeps_unknown_and_actual_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_put: bool,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        fragment = handles(memory, ref)[0]
        original = memory.service.store.put

        def failed(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            receipt_write = key.startswith("read-admission-") and "result" in (
                value["calls"].get("read", {}))
            if receipt_write and not after_put:
                raise ValueError("read receipt write not acknowledged")
            original(ns, key, value, **kwargs)
            if receipt_write:
                raise ValueError("read receipt committed but acknowledgement lost")

        monkeypatch.setattr(memory.service.store, "put", failed)
        args = {"fragment_handle": fragment}
        result = invoke(memory, "read_source", args, "read")
        assert result["status"] == "read_outcome_unknown"
        assert result["phase"] == "read_receipt_persistence"
        assert result["delivered_raw_fragment_count"] == 0
        monkeypatch.setattr(memory.service.store, "put", original)
        if after_put:
            actual = invoke(memory, "read_source", args, "read")
            assert actual["ok"] and actual["items"][0]["fragment_handle"] == fragment
        else:
            with pytest.raises(ValueError, match="READ_OUTCOME_UNKNOWN"):
                invoke(memory, "read_source", args, "read")


def test_forget_value_error_after_visibility_commit_is_unknown_not_no_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        args = {"fragment_handles": handles(memory, ref)}
        original = memory.service.store.put

        def failed(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            original(ns, key, value, **kwargs)
            if key == "visibility":
                raise ValueError("committed visibility state, lost acknowledgement")

        monkeypatch.setattr(memory.service.store, "put", failed)
        result = invoke(memory, "forget_memory", args, "forget")
        assert result["status"] == "outcome_unknown" and result["effect"] == "unconfirmed"
        assert result["phase"] == "visibility_commit" and memory.service.source(ref) is None
        monkeypatch.setattr(memory.service.store, "put", original)
        again = invoke(memory, "forget_memory", args, "forget")
        assert again["ok"] and again["replayed"] and again["forget_epoch"] == 1


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError, FunctionalRejection])
@pytest.mark.parametrize("after_put", [False, True])
def test_m13_save_commit_unknown_recovery_never_double_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception], after_put: bool,
) -> None:
    with opened(tmp_path) as memory:
        ref = turn(memory)
        assert memory.service.sources()[0]["formation_status"] == "pending"
        original = memory.service.store.put

        def uncertain(ns: tuple[str, ...], key: str, value: Any, **kwargs: Any) -> None:
            if ns == memory.service.namespace and not after_put:
                raise error_type("before actual record write")
            original(ns, key, value, **kwargs)
            if ns == memory.service.namespace:
                raise error_type("actual committed row, lost acknowledgement")

        monkeypatch.setattr(memory.service.store, "put", uncertain)
        args = {"content": "saved only after commit", "fragment_handles": handles(memory, ref)}
        unknown = invoke(memory, "save_memory", args, "save")
        assert unknown["status"] == "outcome_unknown"
        assert unknown["effect"] == "unconfirmed" and unknown["error_type"] == error_type.__name__
        assert unknown["phase"] == "semantic_commit"
        assert len(memory.service.records()) == int(after_put)
        monkeypatch.setattr(memory.service.store, "put", original)
        receipt = invoke(memory, "save_memory", args, "save")
        assert receipt["ok"] and receipt["revision"] == 1
        assert bool(receipt.get("replayed")) is after_put
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


def test_recent_public_events_are_bounded_visible_and_fixed_pool_is_unchanged(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, recent_context='session_events_v1', material_limit=30000) as memory:
        refs = []
        for i in range(6):
            refs.append(turn(memory, str(i), 'unrelated subject ' + str(i)))
        memory.service.capture_user('different-session', 'x', 'OTHER_SESSION')
        current = memory.service.capture_user('s', 'q', '那个呢?')['source_ref']
        packet = memory.context('s', 'q', SHA)
        delivered = [u['source_ref'] for u in packet['items'] if u['type'] == 'fragment']
        assert delivered[:5] == [current, *refs[-4:]]
        assert refs[0] not in delivered and refs[1] not in delivered
        assert 'OTHER_SESSION' not in json.dumps(packet)
        fixed = FunctionalMemory(memory.service, len, recent_context='session_events_v1',
                                 material_limit=30000, retrieval_candidates=[])
        fixed_packet = fixed.context('s', 'q', SHA)
        assert [u['source_ref'] for u in fixed_packet['items']] == [current]


@pytest.mark.parametrize('recent', ['disabled', 'session_events_v1'])
def test_preagent_failure_lineage_forget_preserves_later_independent_input(
    tmp_path: Path, recent: str,
) -> None:
    with opened(tmp_path, recent_context=recent, material_limit=30000) as memory:
        secret = turn(memory, 'old', 'private marker for a canceled arrangement')
        record = memory.save(cfg('old'), 'save', 'private marker arrangement',
                             handles(memory, secret))
        request = memory.service.capture_user('s', 'failed', 'cancel private marker arrangement')
        memory.service.bind_public_turn('s', 'failed', request['source_ref'],
                                        config_sha256=SHA, phase='start')
        failure = memory.service.capture_assistant('s', 'failed:failure-final:0',
                                                   'Processing failed; no semantic commit.')
        independent = turn(memory, 'new', 'independent beta preference')
        turn(memory, 'forget', 'Forget that old record and its cancellation request.')
        receipt = invoke(memory, 'forget_memory', {
            'read_handle': memory.service.read(record['id'])['candidate_handle'],
            'additional_fragment_handles': handles(memory, request['source_ref']),
        }, 'forget', cfg('forget'))
        assert receipt['ok']
        assert memory.service.source(failure['source_ref']) is None
        assert memory.service.source(independent) is not None
        turn(memory, 'later', 'private marker')
        assert failure['source_ref'] not in json.dumps(memory.context('s', 'later', SHA))
