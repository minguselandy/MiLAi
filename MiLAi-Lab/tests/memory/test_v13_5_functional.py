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

from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import (
    FunctionalRejection,
    canonical,
    namespace,
    reference_key,
)
from milai_lab.memory.service import MemoryService
from milai_lab.memory.working_set import catalog_candidates, empty_view, select_view_refs

CONFIG_VERSION = "synthetic-v1"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SOCKET_FORBIDDEN")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)


@contextmanager
def opened(
    root: Path, owner: str = "alice", *, memory_profile: str = "ordinary", **options: Any
) -> Iterator[FunctionalMemory]:
    with SqliteStore.from_conn_string(str(root / "store.sqlite")) as store:
        service = MemoryService(
            store,
            ("functional-toy", owner),
            owner,
            root / "service.lock",
            functional_contract="functional_v1",
            memory_profile=memory_profile,
        )
        yield FunctionalMemory(service, len, **options)


def cfg(message: str = "u", owner: str = "alice") -> dict[str, Any]:
    return {
        "configurable": {
            "user_id": owner,
            "v13_session": "s",
            "v13_turn_id": message,
            "v13_config_version": CONFIG_VERSION,
        }
    }


def turn(memory: FunctionalMemory, message: str = "u", text: str = "公开原文 preference") -> str:
    receipt = memory.service.capture_user("s", message, text)
    assert receipt["ok"]
    memory.context("s", message, CONFIG_VERSION)
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


def test_state_driven_catalog_switch_reopen_reload_and_forget(tmp_path: Path) -> None:
    options = {"memory_view_mode": "state_driven", "read_limit": 20,
               "read_interface": "explicit_selectors_v1"}
    with opened(tmp_path, **options) as memory:
        atlas_ref = turn(memory, text="Atlas uses two visits weekly; holidays pause the plan.")
        atlas = memory.save(cfg(), "atlas-save",
                            "Atlas uses two visits weekly; holidays pause the plan.",
                            handles(memory, atlas_ref))
        orchid_ref = turn(memory, "orchid", "Orchid keeps an evening review, date undecided.")
        orchid = memory.save(cfg("orchid"), "orchid-save",
                             "Orchid keeps an evening review, date undecided.",
                             handles(memory, orchid_ref))
        turn(memory, "query", "Compare the Atlas and Orchid arrangements.")
        config = cfg("query")
        directory = memory.context("s", "query", CONFIG_VERSION)
        assert directory["delivered_semantic_record_count"] == 0
        assert {item["record_id"] for item in directory["candidates"]
                if item["type"] == "record_candidate"} == {atlas["id"], orchid["id"]}
        assert all(item["type"] == "fragment" for item in directory["items"])
        assert "read_handle" not in canonical(directory["candidates"])
        search = invoke(memory, "search_memory", {"query": "Atlas"}, "catalog", config)
        assert search["items"] == [] and search["delivered_units"] == 0
        assert search["delivered_raw_fragment_count"] == 0
        first = invoke(memory, "read_memory", {"record_id": atlas["id"]}, "atlas", config)
        assert "holidays pause" in first["items"][0]["content"]
        assert set(first["reading_basis"]) == {"current_at_snapshot"}
        assert search["reading_basis"] == {}
        invoke(memory, "read_memory", {"record_id": orchid["id"]}, "orchid", config)
        assert {item["record_id"] for item in memory.resident_items(config)} == {orchid["id"]}
        invoke(memory, "read_memory", {"record_id": atlas["id"], "keep_resident": True},
               "both", config)
        assert {item["record_id"] for item in memory.resident_items(config)} == {
            atlas["id"], orchid["id"]}
        state = memory.view_state(config)
        assert set(state) == {"focus", "read_goal", "resident_refs", "pending_refs"}
        assert "content" not in canonical(state)
        memory.focus_view(config, focus=orchid["id"], read_goal="current", resident_refs=[
            ref for ref in state["resident_refs"] if ref["id"] == orchid["id"]])
        assert memory.service.store.get(namespace(memory.service), first["snapshot_id"])
    with opened(tmp_path, **options) as memory:
        memory.context("s", "query", CONFIG_VERSION)
        config = cfg("query")
        assert {item["record_id"] for item in memory.resident_items(config)
                if item["type"] == "record"} == {orchid["id"]}
        reloaded = invoke(memory, "read_memory", {"record_id": atlas["id"]}, "reload", config)
        assert reloaded["items"] == first["items"]
        original = invoke(memory, "read_source", {"source_ref": atlas_ref}, "original", config)
        assert set(original["reading_basis"]) == {"original_source"}
        assert {item["type"] for item in memory.resident_items(config)} == {"record", "fragment"}
        old_refs = memory.view_state(config)["resident_refs"]
        forgotten = memory.service.forget(
            "s", "query", fragment_handles=handles(memory, atlas_ref))
        assert forgotten["ok"]
        turn(memory, "after", "Show the remaining Orchid arrangement.")
        memory.focus_view(cfg("after"), resident_refs=old_refs)
        assert memory.resident_items(cfg("after")) == []
        visible = invoke(memory, "read_memory", {"record_id": orchid["id"]}, "remaining",
                         cfg("after"))
        assert visible["ok"] and "date undecided" in visible["items"][0]["content"]


def test_state_view_current_refresh_and_fixed_pool_selection(tmp_path: Path) -> None:
    with opened(tmp_path, memory_view_mode="state_driven", read_limit=10,
                read_interface="explicit_selectors_v1") as memory:
        original = turn(memory, text="Atlas visits twice weekly; holidays pause visits.")
        saved = memory.save(cfg(), "save", "Atlas visits twice weekly; holidays pause visits.",
                            handles(memory, original))
        correction = turn(memory, "change", "Atlas now visits three times weekly; holidays pause.")
        config = cfg("change")
        before = invoke(memory, "read_memory", {"record_id": saved["id"]}, "before", config)
        old_handle = before["items"][0]["read_handle"]
        revised = memory.update(config, "revise", old_handle, [{"field": "content", "op": "set",
            "value": "Atlas visits three times weekly; holidays pause visits.",
            "fragment_handles": handles(memory, correction)}])
        assert revised["ok"] and revised["revision"] == 2
        current = invoke(memory, "read_memory", {"record_id": saved["id"]}, "current", config)
        assert {ref["revision"] for ref in memory.view_state(config)["resident_refs"]
                if ref["kind"] == "record"} == {2}
        history = invoke(memory, "read_memory_revision",
                         {"record_id": saved["id"], "revision": 1}, "history", config)
        assert set(history["reading_basis"]) == {"historical_exact_revision"}
        catalog = memory._page(memory._snapshot(memory._binding(config),
            catalog_candidates(history["items"]), "saved_history_catalog"),
            0, memory._binding(config))
        read = catalog["candidates"][0]["read"]
        reopened = invoke(memory, read["tool"], read["arguments"], "history-catalog", config)
        assert reopened["items"][0]["revision"] == 1
        assert "twice weekly" in reopened["items"][0]["content"]
        assert "three times" in current["items"][0]["content"]
        assert catalog["delivered_units"] == 0 and catalog["reading_basis"] == {}
        pool = [*current["view_refs"], *history["view_refs"]]
        state = select_view_refs(empty_view(), pool, [{"id": saved["id"], "view": "current"}])
        assert {ref["revision"] for ref in state["resident_refs"]} == {2}
        state = select_view_refs(state, pool,
                                 [{"id": saved["id"], "revision": 1, "view": "saved_history"}])
        assert {(ref["revision"], ref["view"]) for ref in state["resident_refs"]} == {
            (2, "current_at_snapshot"), (1, "historical_exact_revision")}
        state = select_view_refs(empty_view(), pool, [{"id": "outside-fixed-pool"}])
        assert state["resident_refs"] == []
        bound = memory._binding(config)
        search = invoke(memory, "search_memory", {"query": "holidays"}, "explore", config)
        assert memory._binding(config) == bound and search["delivered_units"] == 0
        assert all(len(candidate["description"]) <= memory.fragment_chars
                   for candidate in search["candidates"] if candidate["type"] == "source_candidate")
        with pytest.raises(FunctionalRejection, match="PUBLIC_QUERY_CHANGED"):
            memory.context("s", "change", CONFIG_VERSION, query="holidays")


def test_support_context_keeps_selected_bodies_separate_from_exact_record_and_old_support(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, support_context=True, read_interface='explicit_selectors_v1',
                material_limit=30000) as memory:
        old_ref = turn(memory, text='For this workshop only, plan two visits weekly.')
        saved = memory.save(cfg(), 'save', 'For this workshop only, plan two visits weekly.',
                            handles(memory, old_ref))
        before = memory.service.read(saved['id'])
        current_ref = turn(memory, 'change',
            'For this workshop, change the plan to three weekly; start week is undecided.')
        selected = handles(memory, current_ref)
        args = {'fragment_handles': selected, 'read_handle': before['candidate_handle']}
        result = invoke(memory, 'read_support_context', args, 'view', cfg('change'))
        assert result['operation_effect'] == 'read_only'
        assert not result['semantic_write_performed']
        assert result['support_context']['selection_status'] == (
            'read_preview_not_committed_field_support')
        record = next(row for row in result['items'] if row['type'] == 'record')
        assert record['record_id'] == saved['id'] and record['revision'] == 1
        assert record['content'] == before['value']['content']
        assert record['prior_field_support_identity']['content'][0]['source_ref'] == old_ref
        fragments = [row for row in result['items'] if row['type'] == 'fragment']
        assert {row['source_ref'] for row in fragments} == {current_ref}
        assert 'start week is undecided' in ''.join(row['content'] for row in fragments)
        assert memory.service.read(saved['id'])['value'] == before['value']
        assert invoke(memory, 'read_support_context', args, 'view', cfg('change')) == result
    with opened(tmp_path, support_context=True, read_interface='explicit_selectors_v1',
                material_limit=30000) as memory:
        memory.context('s', 'change', CONFIG_VERSION)
        assert invoke(memory, 'read_support_context', args, 'view', cfg('change')) == result
        assert memory.service.read(saved['id'])['value'] == before['value']
        revised = memory.update(cfg('change'), 'change', before['candidate_handle'], [{
            'field': 'content', 'op': 'set',
            'value': 'For this workshop only, plan three visits weekly; start week undecided.',
            'fragment_handles': handles(memory, old_ref) + selected}])
        assert revised['ok'] and revised['id'] == saved['id'] and revised['revision'] == 2
        value = memory.service.read(saved['id'])['value']
        assert set(value['functional_support']['content']['source_refs']) == {old_ref, current_ref}
        assert value['functional_support']['kind'] == before['value']['functional_support']['kind']


def test_support_context_rejects_foreign_or_revoked_evidence_and_cache_on_reopen(
    tmp_path: Path,
) -> None:
    owner_text = 'A separate owner private assertion.'
    with opened(tmp_path, owner='bob') as other:
        ref = turn(other, text=owner_text)
        foreign = handles(other, ref)
    with opened(tmp_path, support_context=True, read_interface='explicit_selectors_v1',
                material_limit=30000) as memory:
        ref = turn(memory, text='A temporary phrase visible only before forgetting.')
        selected = handles(memory, ref)
        bad = invoke(memory, 'read_support_context', {'fragment_handles': foreign}, 'foreign')
        assert bad['status'] == 'read_rejected' and owner_text not in canonical(bad)
        result = invoke(memory, 'read_support_context', {'fragment_handles': selected}, 'view')
        assert result['ok']
        turn(memory, 'forget', 'Forget the temporary phrase.')
        forgotten = memory.service.forget('s', 'forget', fragment_handles=selected)
        assert forgotten['ok']
        with pytest.raises(FunctionalRejection):
            invoke(memory, 'read_support_context', {'fragment_handles': selected}, 'view')
        turn(memory, 'after', 'Which selected originals are still available?')
        blocked = invoke(memory, 'read_support_context', {'fragment_handles': selected},
                         'new-view', cfg('after'))
        assert blocked['status'] == 'read_rejected'
        assert 'temporary phrase visible only' not in canonical(blocked)
    with opened(tmp_path, support_context=True, read_interface='explicit_selectors_v1',
                material_limit=30000) as memory:
        turn(memory, 'later', 'What sources are visible now?')
        blocked = invoke(memory, 'read_support_context', {'fragment_handles': selected},
                         'reopen', cfg('later'))
        assert blocked['status'] == 'read_rejected'
        assert 'temporary phrase visible only' not in canonical(blocked)


def test_support_context_oversized_record_reports_omission_and_reaches_selected_original(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, support_context=True, read_interface='explicit_selectors_v1',
                material_limit=5000) as memory:
        ref = turn(memory, text='Only the proposed arrangement is known; start date is unknown.')
        selected = handles(memory, ref)
        saved = memory.save(cfg(), 'save', 'A proposed arrangement.', selected,
                            scope={'large': 'x' * 8000})
        row = memory.service.read(saved['id'])
        result = invoke(memory, 'read_support_context',
            {'fragment_handles': selected, 'read_handle': row['candidate_handle']}, 'view')
        assert result['status'] == 'advanced_with_explicit_omission'
        assert result['skipped_units'][0]['type'] == 'record'
        assert result['examined_units'] == 2 and result['next_cursor'] is None
        assert result['delivery_status'] == 'snapshot_end_with_omissions'
        assert result['items'][0]['content'].endswith('start date is unknown.')
        assert len(canonical(result)) <= 5000
        assert memory.service.read(saved['id'])['value'] == row['value']


def test_explicit_existing_confirmation_preserves_version_support_and_owner_on_reopen(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, existing_confirmation=True) as memory:
        ref = turn(memory, text='For this exhibition only, use quiet reminders.')
        saved = memory.save(cfg(), 'save', 'For this exhibition only, use quiet reminders.',
                            handles(memory, ref))
        row = memory.service.read(saved['id'])
        handle = row['candidate_handle']
        tool = next(t for t in memory.tools() if t.name == 'confirm_existing_memory')
        assert set(tool.tool_call_schema.model_fields) == {'read_handle'}
        result = invoke(memory, 'confirm_existing_memory', {'read_handle': handle}, 'confirm')
        assert result['status'] == 'no_change' and result['effect'] == 'none'
        assert result['id'] == saved['id'] and result['revision'] == 1
        assert memory.service.read(saved['id'])['value'] == row['value']
        replay = invoke(memory, 'confirm_existing_memory', {'read_handle': handle}, 'confirm')
        assert replay['status'] == 'no_change' and replay['revision'] == 1
        ref2 = turn(memory, 'change', 'For this exhibition only, use written reminders.')
        revised = memory.update(cfg('change'), 'revise', handle, [{'field': 'content',
            'op': 'set', 'value': 'For this exhibition only, use written reminders.',
            'fragment_handles': handles(memory, ref2)}])
        assert revised['revision'] == 2
        stale = invoke(memory, 'confirm_existing_memory', {'read_handle': handle}, 'stale',
                       cfg('change'))
        assert not stale['ok'] and stale['reason'] == 'revision_conflict'
        current = memory.service.read(saved['id'])
    with opened(tmp_path, existing_confirmation=True) as memory:
        unbound = invoke(memory, 'confirm_existing_memory',
                         {'read_handle': current['candidate_handle']}, 'unbound', cfg('change'))
        assert unbound['reason'] == 'V13_5_ACTUAL_PUBLIC_TURN_REQUIRED'
        memory.context('s', 'change', CONFIG_VERSION)
        reopened = memory.service.read(saved['id'])
        result = invoke(memory, 'confirm_existing_memory',
                        {'read_handle': reopened['candidate_handle']}, 'reopened', cfg('change'))
        assert result['status'] == 'no_change' and result['revision'] == 2
        assert memory.service.read(saved['id'])['value'] == current['value']
        history = memory.service.history_index(saved['id'])
        assert len(history['revisions']) == 2
    with opened(tmp_path, owner='bob', existing_confirmation=True) as other:
        turn(other)
        wrong_owner = invoke(other, 'confirm_existing_memory',
                             {'read_handle': current['candidate_handle']},
                             'wrong', cfg(owner='bob'))
        assert not wrong_owner['ok'] and wrong_owner['effect'] == 'none'
    with opened(tmp_path) as old:
        assert 'confirm_existing_memory' not in {t.name for t in old.tools()}


def test_existing_confirmation_cannot_restore_a_withdrawn_record(tmp_path: Path) -> None:
    with opened(tmp_path, existing_confirmation=True) as memory:
        ref = turn(memory, text='For this workshop only, prefer the window seats.')
        saved = memory.save(cfg(), 'save', 'For this workshop only, prefer the window seats.',
                            handles(memory, ref))
        original = memory.service.read(saved['id'])
        cancel = turn(memory, 'cancel', 'The workshop is over; withdraw that seating preference.')
        withdrawn = memory.update(cfg('cancel'), 'withdraw', original['candidate_handle'], [],
                                  handles(memory, cancel), retract=True)
        assert withdrawn['revision'] == 2
        failed = invoke(memory, 'confirm_existing_memory',
                        {'read_handle': original['candidate_handle']}, 'old', cfg('cancel'))
        assert not failed['ok']
        assert memory.service.read(saved['id'])['status'] == 'retracted'
        assert len(memory.service.history_index(saved['id'])['revisions']) == 2


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
        ordinary = memory.context("s", "u", CONFIG_VERSION)
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
        assert memory.context("s", "u", CONFIG_VERSION) == ordinary
        read = invoke(memory, "read_memory", {"record_id": committed["id"]}, "record")
        assert_read_delivery(read)
        assert read["delivered_semantic_record_ids"] == [committed["id"]]
        assert read["delivered_raw_fragment_count"] == 0
        refused = invoke(memory, "read_source", {"fragment_handle": "unknown"}, "over-limit")
        assert refused["status"] == "read_limit_exhausted" and not refused["ok"]
        assert_read_delivery(refused)
        assert len(memory.service.records()) == 1


def test_episode_description_matches_keep_source_links_and_revocation_on_reopen(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, memory_profile="unified_v1") as memory:
        meeting = turn(memory, text="We agreed to meet Friday at 14:00.")
        preparation = turn(memory, "preparation", "Bring printed copies.")
        turn(memory, "raw-only", "Cobalt planning meeting.")
        episodes = EpisodeIndex(memory.service)
        episode = episodes.register("meeting", [meeting, preparation], descriptions=[
            {"kind": "event", "basis": "reported", "text": "Cobalt planning meeting",
             "source_refs": [meeting]},
            {"kind": "context", "basis": "inferred", "text": "Cobalt",
             "source_refs": [meeting]},
            {"kind": "context", "basis": "reported", "text": "Travel preparation",
             "source_refs": [preparation]},
        ])
        episodes.register("same-meeting", [meeting], descriptions=[
            {"kind": "event", "basis": "reported", "text": "Cobalt planning meeting",
             "source_refs": [meeting]},
        ])
        assert episodes.source_matches("CObalt PLANNING") == {meeting: 2}
        assert episodes.source_matches("travel") == {preparation: 1}
        assert episodes.source_matches("printed") == {}
        assert episodes.source_matches("  ") == {}
        found = memory.service.search("CObalt PLANNING")
        original = next(row for row in found["raw_events"] if row["event_id"] == meeting)
        assert original["content"] == "We agreed to meet Friday at 14:00."
        assert original["role"] == "user"
        semantic_only = memory.service.search("cobalt planning", include_raw=False)
        assert semantic_only["records"] == [] and semantic_only["raw_events"] == []
        assert episodes.read("meeting") == {k: v for k, v in episode.items() if k != "replayed"}
        assert all(d["content_verification"] == "unchecked" for d in episode["descriptions"])
        assert memory.service.records() == []
    with opened(tmp_path, owner="bob", memory_profile="unified_v1") as other:
        assert EpisodeIndex(other.service).source_matches("cobalt travel") == {}
        assert other.service.search("cobalt planning")["raw_events"] == []
    with opened(tmp_path, memory_profile="unified_v1") as memory:
        episodes = EpisodeIndex(memory.service)
        assert episodes.source_matches("cobalt planning") == {meeting: 2}
        assert any(row["event_id"] == meeting
                   for row in memory.service.search("cobalt planning")["raw_events"])
        turn(memory, "forget", "Forget the Friday arrangement.")
        forgotten = invoke(memory, "forget_memory", {"fragment_handles": handles(memory, meeting)},
                           "forget-meeting", cfg("forget"))
        assert forgotten["ok"]
        assert memory.service.source(preparation) is not None
        assert episodes.read("meeting") is None
        assert episodes.source_matches("cobalt travel") == {}
        assert all(row["event_id"] != meeting
                   for row in memory.service.search("cobalt planning")["raw_events"])
    with opened(tmp_path, memory_profile="unified_v1") as memory:
        assert EpisodeIndex(memory.service).source_matches("cobalt travel") == {}
        assert all(row["event_id"] != meeting
                   for row in memory.service.search("cobalt planning")["raw_events"])


def test_read_delivery_metadata_is_budgeted_for_mixed_immutable_pages(tmp_path: Path) -> None:
    with opened(tmp_path, material_limit=3500, fragment_chars=240, read_limit=40) as memory:
        ref = turn(memory, text="synthetic source " * 90)
        saved = memory.save(cfg(), "save", "synthetic record " * 80, handles(memory, ref))
        turn(memory, "query", "synthetic")
        page = memory.context("s", "query", CONFIG_VERSION)
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
        memory.context("s", "u", CONFIG_VERSION)
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


@pytest.mark.parametrize("interface", [
    "content_and_scope_v1", "unified_assertion_v2", "unified_assertion_v3"])
def test_public_update_selects_evidence_per_field_and_retains_unchanged_history(
    tmp_path: Path, interface: str,
) -> None:
    evidence_key = ("evidence_for_new_value" if interface != "content_and_scope_v1"
                    else "fragment_handles")
    with opened(tmp_path, formation_interface=interface) as memory:
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
             evidence_key: corrected},
            {"field": "scope.project", "op": "set", "value": "Beta", evidence_key: scoped},
            {"field": "scope.nested.only", "op": "remove", evidence_key: corrected},
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
                 evidence_key: []}]}, "no-change", cfg("change"))
        assert unchanged["status"] == "no_change" and unchanged["revision"] == 2
        assert memory.service.history_index(saved["id"])["revisions"] == [1, 2]
        packet = memory.context("s", "change", CONFIG_VERSION)
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


@pytest.mark.parametrize("corrupt", [None, "source_revision"])
def test_frozen_candidate_version_binds_exact_body_range(
    tmp_path: Path, corrupt: str | None,
) -> None:
    with opened(tmp_path) as base:
        ref = base.service.capture_user("archive", "a", "prefix\r\n🙂literal body\r\nsuffix")[
            "source_ref"]
        fragment = base.service.source_fragment_range(ref, 8, 20)
        candidate = {key: fragment[key] for key in (
            "source_ref", "start", "end", "source_revision")}
        candidate["retrieval_score"] = 0.75
        if corrupt:
            candidate[corrupt] = fragment[corrupt] + 1
            with pytest.raises(FunctionalRejection, match="CANDIDATE_VERSION_MISMATCH"):
                FunctionalMemory(base.service, len, retrieval_candidates=[candidate])
            return
        memory = FunctionalMemory(base.service, len, retrieval_candidates=[candidate])
        turn(memory, text="Read the supplied material")
        units = memory.context("s", "u", CONFIG_VERSION)["items"]
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
 m=FunctionalMemory(s,len); m.context("s","u","synthetic-v1")
 assert s.read(sys.argv[2])["value"]["content"]=="Revised"
 assert s.read(sys.argv[2],1)["value"]["content"]=="Initial"
 assert s.source(sys.argv[3])["content"]=="公开原文 preference"
 config={"configurable":{"user_id":"alice","v13_session":"s","v13_turn_id":"u","v13_config_version":"synthetic-v1"}}
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


@pytest.mark.parametrize("explicit", [False, True])
def test_m05_large_source_body_ranking_group_reachability_and_wrapper_limit(
    tmp_path: Path, explicit: bool,
) -> None:
    text = ("unrelated paragraph " * 100 + "\n") * 9 + "needle exception final requirement\n"
    with opened(tmp_path, fragment_chars=600, read_limit=40,
                read_interface="explicit_selectors_v1" if explicit
                else "combined_selectors_v1") as memory:
        ref = memory.service.capture_user("archive", "large", text)["source_ref"]
        turn(memory, text="needle")
        page = memory.context("s", "u", CONFIG_VERSION)
        assert any("needle exception" in u["content"] for u in page["items"])
        assert len(canonical(page)) <= 8192 and page["delivery_status"] == "partial"
        assert any(g["source_ref"] == ref for g in page["source_groups"])
        result = invoke(memory, "read_source", {"source_ref": ref}, "source0")
        delivered = list(result["items"])
        index = 0
        while result["next_cursor"]:
            index += 1
            result = invoke(memory, "read_page" if explicit else "read_source",
                            {"cursor": result["next_cursor"]}, str(index))
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
        units = memory.context("s", "u", CONFIG_VERSION)["items"]
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
        ordinary = memory.context("s", "u", CONFIG_VERSION)
        assert ordinary["next_cursor"]
        explicit = invoke(memory, "search_memory", {"query": "paragraph"}, "search")
        assert explicit["snapshot_id"] != ordinary["snapshot_id"]
        assert memory.context("s", "u", CONFIG_VERSION) == ordinary
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


@pytest.mark.parametrize("archived", [False, True])
def test_withdrawal_selection_keeps_cancellation_separate_from_old_support(
    tmp_path: Path, archived: bool,
) -> None:
    with opened(tmp_path, formation_interface="unified_assertion_v3") as memory:
        old = turn(memory, text="Keep this preference for the local sample only.")
        saved = memory.save(cfg(), "save", "Local sample preference.", handles(memory, old), {})
        before = memory.service.read(saved["id"])
        cancellation = turn(memory, "cancel", "Withdraw that local sample preference.")
        selected = handles(memory, cancellation)
        message_id = "query" if archived else "cancel"
        if archived:
            query = turn(memory, "query", "What is currently recorded?")
        tool = next(t for t in memory.tools() if t.name == "update_memory")
        properties = tool.tool_call_schema.model_json_schema()["properties"]
        assert "evidence_for_withdrawal" in properties and "fragment_handles" not in properties
        result = invoke(memory, "update_memory", {
            "read_handle": before["candidate_handle"], "changes": [], "retract": True,
            "evidence_for_withdrawal": selected,
        }, "withdraw", cfg(message_id))
        assert result["ok"] and result["id"] == saved["id"] and result["revision"] == 2
        assert memory.service.read(saved["id"])["status"] == "retracted"
        version = memory.service.read(saved["id"], 2)["value"]
        assert version["functional_support"] == before["value"]["functional_support"]
        withdrawal = version["removed_field_support"]["record"]
        assert withdrawal["source_refs"] == [cancellation]
        assert withdrawal["quotes"][0]["content"] == "Withdraw that local sample preference."
        assert withdrawal["semantic_support"] == "unchecked"
        assert memory.service.read(saved["id"], 1)["value"] == before["value"]
        if archived:
            assert query not in version["source_refs"]


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
        packet = memory.context("s", "query-after-retract", CONFIG_VERSION)
        assert any(
            unit["type"] == "withdrawal" and unit["state"] == "withdrawn_not_current_fact"
            for unit in packet["items"]
        )


def test_revision_preview_preserves_old_fact_and_binds_exact_evidence_across_reopen(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, formation_interface="reviewed_assertion_v1") as memory:
        old = turn(memory, text="This sample uses ounces; keep commercial labels unchanged.")
        saved = memory.save(cfg(), "save", "Sample uses ounces; labels unchanged.",
                            handles(memory, old), {})
        row = memory.service.read(saved["id"])
        new = turn(memory, "correction", "Change this sample to grams; labels unchanged.")
        args = {"read_handle": row["candidate_handle"], "changes": [{
            "field": "content", "op": "set", "value": "Sample uses grams; labels unchanged.",
            "evidence_for_new_value": handles(memory, old)}]}
        wrong = invoke(memory, "update_memory", args, "preview-old", cfg("correction"))
        assert wrong["status"] == "revision_review_required"
        assert not wrong["semantic_write_performed"] and wrong["effect"] == "none"
        assert memory.service.read(saved["id"])["value"] == row["value"]
        change = wrong["proposed_changes"][0]
        assert change["same_selection_as_prior_field_support"]
        assert "ounces" in change["selected_original_fragments"][0]["content"]
        args["changes"][0]["evidence_for_new_value"] = handles(memory, new)
        rejected = invoke(memory, "update_memory", {
            **args, "review_token": wrong["review_token"]}, "bad-confirm", cfg("correction"))
        assert rejected["status"] == "rejected" and rejected["effect"] == "none"
        preview = invoke(memory, "update_memory", args, "preview-new", cfg("correction"))
        assert not preview["proposed_changes"][0]["same_selection_as_prior_field_support"]
        assert memory.service.history_index(saved["id"])["revisions"] == [1]
    with opened(tmp_path, formation_interface="reviewed_assertion_v1") as memory:
        memory.context("s", "correction", CONFIG_VERSION)
        confirmed = {**args, "review_token": preview["review_token"]}
        receipt = invoke(memory, "update_memory", confirmed, "commit", cfg("correction"))
        assert receipt["ok"] and receipt["revision"] == 2, receipt
        repeated = invoke(memory, "update_memory", confirmed, "commit", cfg("correction"))
        assert repeated["id"] == receipt["id"] and repeated["revision"] == 2
        current = memory.service.read(saved["id"])["value"]
        assert current["functional_support"]["content"]["source_refs"] == [new]
        assert memory.service.read(saved["id"], 1)["value"] == row["value"]


def test_revision_preview_allows_supported_archived_reinterpretation_without_current_input(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, formation_interface="reviewed_assertion_v1") as memory:
        source = turn(memory, text="Work days only: favor short answers; weekends unrestricted.")
        saved = memory.save(cfg(), "save", "Work days only: short answers preferred.",
                            handles(memory, source), {})
        query = turn(memory, "later", "Clarify the stored wording using its original source.")
        args = {"read_handle": memory.service.read(saved["id"])["candidate_handle"],
                "changes": [{"field": "content", "op": "set",
                    "value": "Favor short answers on work days; weekends unrestricted.",
                    "evidence_for_new_value": handles(memory, source)}]}
        preview = invoke(memory, "update_memory", args, "preview", cfg("later"))
        assert preview["proposed_changes"][0]["same_selection_as_prior_field_support"]
        receipt = invoke(memory, "update_memory", {**args, "review_token": preview["review_token"]},
                         "commit", cfg("later"))
        assert receipt["ok"] and receipt["revision"] == 2
        current = memory.service.read(saved["id"])["value"]
        assert current["functional_support"]["content"]["source_refs"] == [source]
        assert query not in current["source_refs"]


@pytest.mark.parametrize("withdraw", [False, True])
@pytest.mark.parametrize("archived", [False, True])
def test_short_evidence_cue_rejects_wrong_fragment_and_keeps_actual_changed_support(
    tmp_path: Path, withdraw: bool, archived: bool,
) -> None:
    with opened(tmp_path, formation_interface="anchored_assertion_v1") as memory:
        old = turn(memory, text="Only this sample uses ounces; labels unchanged.")
        saved = memory.save(cfg(), "save", "Only this sample uses ounces; labels unchanged.",
                            handles(memory, old), {})
        before = memory.service.read(saved["id"])
        new_text = ("Withdraw this sample rule; keep history." if withdraw else
                    "Use grams for this sample; labels remain unchanged.")
        new = turn(memory, "change", new_text)
        message_id = "later" if archived else "change"
        if archived:
            query = turn(memory, "later", "Apply the previously stated change.")
        cue = "Withdraw this sample rule" if withdraw else "Use grams"
        wrong = {"fragment_handle": handles(memory, old)[0], "supporting_words": cue}
        args: dict[str, Any] = {"read_handle": before["candidate_handle"], "changes": []}
        if withdraw:
            args.update(retract=True, evidence_for_withdrawal=[wrong])
        else:
            args["changes"] = [{"field": "content", "op": "set",
                "value": "Only this sample uses grams; labels unchanged.",
                "evidence_for_new_value": [wrong]}]
        rejected = invoke(memory, "update_memory", args, "wrong", cfg(message_id))
        assert rejected["status"] == "rejected" and rejected["effect"] == "none"
        assert "EVIDENCE_CUE_NOT_IN_SELECTED_FRAGMENT" in rejected["reason"]
        assert memory.service.read(saved["id"])["value"] == before["value"]
        selected = {"fragment_handle": handles(memory, new)[0], "supporting_words": cue}
        if withdraw:
            args["evidence_for_withdrawal"] = [selected]
        else:
            args["changes"][0]["evidence_for_new_value"] = [selected]
        receipt = invoke(memory, "update_memory", args, "right", cfg(message_id))
        assert receipt["ok"] and receipt["id"] == saved["id"] and receipt["revision"] == 2
        current = memory.service.read(saved["id"], 2)["value"]
        support = (current["removed_field_support"]["record"] if withdraw else
                   current["functional_support"]["content"])
        assert support["source_refs"] == [new]
        assert support["quotes"][0]["content"] == new_text  # Full quote is program-extracted.
        assert support["semantic_support"] == "unchecked"
        assert memory.service.read(saved["id"], 1)["value"] == before["value"]
        if archived:
            assert query not in current["source_refs"]


@pytest.mark.parametrize("profile", [
    "anchored_assertion_v1", "anchored_assertion_v2", "anchored_assertion_v3"])
def test_evidence_cue_keeps_same_source_reinterpretation_and_exact_no_change_legal(
    tmp_path: Path, profile: str,
) -> None:
    with opened(tmp_path, formation_interface=profile) as memory:
        ref = turn(memory, text="Work days only: favor short replies; weekends unrestricted.")
        saved = memory.save(cfg(), "save", "Favor short replies on work days.",
                            handles(memory, ref), {})
        read = memory.service.read(saved["id"])
        args = {"read_handle": read["candidate_handle"], "changes": [{
            "field": "content", "op": "set",
            "value": "Favor short replies on work days; weekends unrestricted.",
            "evidence_for_new_value": [{"fragment_handle": handles(memory, ref)[0],
                                       "supporting_words": "weekends unrestricted"}]}]}
        receipt = invoke(memory, "update_memory", args, "reformulate")
        assert receipt["ok"] and receipt["revision"] == 2
        args["read_handle"] = memory.service.read(saved["id"])["candidate_handle"]
        args["changes"][0]["evidence_for_new_value"] = []
        no_change = invoke(memory, "update_memory", args, "same")
        assert no_change["status"] == "no_change" and no_change["revision"] == 2


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("alias", ["original", "subset", "union"])
@pytest.mark.parametrize("profile", ["anchored_assertion_v2", "anchored_assertion_v3"])
def test_withdrawal_cannot_reuse_only_affirmation_even_with_valid_literal_cue(
    tmp_path: Path, archived: bool, alias: str, profile: str,
) -> None:
    with opened(tmp_path, formation_interface=profile) as memory:
        affirmation = "Only this trial: prefer window seats."
        old = turn(memory, text=affirmation)
        prior_handles = ([memory.service.source_fragment_range(old, start, end)["fragment_handle"]
                          for start, end in [(0, 15), (15, len(affirmation))]] if alias == "union"
                         else handles(memory, old))
        saved = memory.save(cfg(), "save", "Only this trial: prefer window seats.",
                            prior_handles, {})
        before = memory.service.read(saved["id"])
        cancel = turn(memory, "cancel", "Withdraw that entire preference; keep history.")
        message = "later" if archived else "cancel"
        if archived:
            turn(memory, "later", "Apply the earlier cancellation, not a new fact.")
        old_handle = (memory.service.source_fragment_range(old, 0, 15)["fragment_handle"]
                      if alias == "subset" else handles(memory, old)[0])
        args = {"read_handle": before["candidate_handle"], "changes": [], "retract": True,
                "evidence_for_withdrawal": [{"fragment_handle": old_handle,
                                             "supporting_words": "Only this trial"}]}
        if profile == "anchored_assertion_v3":
            args.pop("changes")
        refused = invoke(memory, "update_memory", args, "wrong-affirmation", cfg(message))
        assert refused["status"] == "rejected" and refused["effect"] == "none"
        assert "WITHDRAWAL_REUSES_ONLY_PRIOR_SUPPORT" in refused["reason"]
        assert memory.service.read(saved["id"])["value"] == before["value"]
        args["evidence_for_withdrawal"] = [{"fragment_handle": handles(memory, cancel)[0],
                                          "supporting_words": "Withdraw that entire preference"}]
        result = invoke(memory, "update_memory", args, "actual-cancellation", cfg(message))
        assert result["ok"] and result["revision"] == 2
        after = memory.service.read(saved["id"], 2)["value"]
        support = after["removed_field_support"]["record"]
        assert support["source_refs"] == [cancel] and support["semantic_support"] == "unchecked"
        assert memory.service.read(saved["id"], 1)["value"] == before["value"]


def test_optional_withdrawal_patch_does_not_infer_an_ordinary_update_or_its_evidence(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, formation_interface="anchored_assertion_v3") as memory:
        ref = turn(memory, text="Only this trial: favor blue markers.")
        saved = memory.save(cfg(), "save", "Only this trial: favor blue markers.",
                            handles(memory, ref), {})
        before = memory.service.read(saved["id"])
        args = {"read_handle": before["candidate_handle"]}
        rejected = invoke(memory, "update_memory", args, "missing-patch")
        assert rejected["status"] == "rejected" and rejected["effect"] == "none"
        assert "NON_WITHDRAWAL_CHANGES_REQUIRED" in rejected["reason"]
        missing_evidence = invoke(memory, "update_memory", {**args, "retract": True}, "no-proof")
        assert missing_evidence["status"] == "rejected" and missing_evidence["effect"] == "none"
        unchanged = invoke(memory, "update_memory", {**args, "changes": []}, "explicit-same")
        assert unchanged["status"] == "no_change" and unchanged["revision"] == 1
        assert memory.service.read(saved["id"])["value"] == before["value"]


def test_withdrawal_accepts_distinct_span_in_same_archived_source_not_query_trigger(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, formation_interface="anchored_assertion_v2") as memory:
        affirmation = "Use green markers."
        cancellation = "Withdraw the marker preference."
        ref = turn(memory, text=affirmation + "\n" + cancellation)
        first = memory.service.source_fragment_range(ref, 0, len(affirmation))
        second = memory.service.source_fragment_range(
            ref, len(affirmation) + 1, len(affirmation) + 1 + len(cancellation))
        saved = memory.save(cfg(), "save", affirmation, [first["fragment_handle"]], {})
        query = turn(memory, "later", "Apply the cancellation already in the archive.")
        args = {"read_handle": memory.service.read(saved["id"])["candidate_handle"],
                "changes": [], "retract": True,
                "evidence_for_withdrawal": [{"fragment_handle": second["fragment_handle"],
                                             "supporting_words": "Withdraw the marker preference"}]}
        receipt = invoke(memory, "update_memory", args, "withdraw", cfg("later"))
        assert receipt["ok"] and receipt["revision"] == 2
        current = memory.service.read(saved["id"], 2)["value"]
        support = current["removed_field_support"]["record"]
        assert support["source_refs"] == [ref] and query not in current["source_refs"]
        assert support["quotes"][0]["content"] == cancellation


def test_revision_preview_withdrawal_and_oversize_never_write_before_confirmation(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, formation_interface="reviewed_assertion_v1") as memory:
        old = turn(memory, text="Only this trial: prefer blue markers.")
        saved = memory.save(cfg(), "save", "Only this trial: prefer blue markers.",
                            handles(memory, old), {})
        cancel = turn(memory, "cancel", "Withdraw the whole trial preference; keep its history.")
        args = {"read_handle": memory.service.read(saved["id"])["candidate_handle"],
                "changes": [], "retract": True,
                "evidence_for_withdrawal": handles(memory, cancel)}
        memory.material_limit = 20
        too_big = invoke(memory, "update_memory", args, "oversize", cfg("cancel"))
        assert too_big["status"] == "rejected"
        assert memory.service.read(saved["id"])["ok"]
        memory.material_limit = 8192
        preview = invoke(memory, "update_memory", args, "preview", cfg("cancel"))
        assert preview["proposed_changes"][0]["field"] == "record"
        assert memory.service.read(saved["id"])["value"]["revision"] == 1
        receipt = invoke(memory, "update_memory", {**args, "review_token": preview["review_token"]},
                         "commit", cfg("cancel"))
        assert receipt["ok"] and receipt["revision"] == 2
        assert memory.service.read(saved["id"])["status"] == "retracted"
        latest = memory.service.read(saved["id"], 2)["value"]
        assert latest["removed_field_support"]["record"]["source_refs"] == [cancel]


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
            memory.context("s", "u", CONFIG_VERSION)
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
            receipt_write = key.startswith("read-admission:") and "result" in (
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


@pytest.mark.parametrize("explicit", [False, True])
def test_m14_forget_revokes_old_handles_snapshot_raw_and_replay_cache(
    tmp_path: Path, explicit: bool,
) -> None:
    with opened(tmp_path, read_interface="explicit_selectors_v1" if explicit
                else "combined_selectors_v1") as memory:
        read_tool = "read_fragment" if explicit else "read_source"
        ref = turn(memory, text="private preference")
        hs = handles(memory, ref)
        saved = memory.save(cfg(), "save", "private preference", hs)
        turn(memory, "u2", "forget private preference")
        cached = memory.context("s", "u2", CONFIG_VERSION)
        history_entry = next(u["stored_history"] for u in cached["items"]
                             if u["type"] == "record" and "stored_history" in u)["read"]
        row = memory.service.read(saved["id"])
        explicit = invoke(memory, read_tool, {"fragment_handle": hs[0]}, "read", cfg("u2"))
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
            invoke(memory, read_tool, {"fragment_handle": hs[0]}, "read", cfg("u2"))
        assert all(r["event_id"] != ref for r in memory.service.search("private")["raw_events"])
        new = memory.context("s", "u2", CONFIG_VERSION)
        assert new["snapshot_id"] != cached["snapshot_id"]
        assert all(u.get("source_ref") != ref for u in new["items"])
        hidden_history = invoke(memory, history_entry["tool"], history_entry["arguments"],
                                "hidden-history", cfg("u2"))
        assert hidden_history["status"] == "visibility_revoked"
        assert "private preference" not in canonical(hidden_history)
        assert memory.service.store.get(memory.service.sources_namespace, ref) is not None
        assert (
            memory.service.store.get(namespace(memory.service), cached["snapshot_id"]) is not None
        )


@pytest.mark.parametrize("explicit", [False, True])
def test_history_body_cursor_stays_on_issued_versions_after_later_update(
    tmp_path: Path, explicit: bool,
) -> None:
    with opened(tmp_path, material_limit=3500, fragment_chars=300, read_limit=20,
                read_interface="explicit_selectors_v1" if explicit
                else "combined_selectors_v1",
                memory_view_mode="state_driven" if explicit else "legacy") as memory:
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
        current = invoke(memory, "read_memory", {"record_id": saved["id"],
            **({"read_goal": "saved_history"} if explicit else {})}, "current")
        if explicit:
            assert memory.view_state(cfg())["read_goal"] == "saved_history"
        entry = current["items"][0]["stored_history"]
        assert entry["current_revision_at_index"] == entry["revision_count"] == 8
        assert entry["revisions"] == list(range(1, 7)) and entry["omitted_count"] == 2
        assert entry["index_next_cursor"] and entry["body_page_tool"] == (
            "read_page" if explicit else "read_memory"
        )
        assert current["items"][0]["committed_at"] == (
            memory.service.read(saved["id"])["value"]["committed_at"]
        )
        assert all(u["revision"] == 8 for u in current["items"])
        assert sum("stored_history" in u for u in current["items"]) == 1
        assert "version1" not in canonical(current)
        assert len(canonical(current)) <= memory.material_limit
        first = invoke(
            memory, entry["read"]["tool"], entry["read"]["arguments"], "history"
        )
        assert first["items"] and first["next_cursor"]
        if explicit:
            assert memory.view_state(cfg())["read_goal"] == "saved_history"
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
            page = invoke(memory, "read_page" if explicit else "read_memory",
                          {"cursor": page["next_cursor"]}, f"page{index}")
            assert page["snapshot_id"] == first["snapshot_id"]
            if explicit:
                assert memory.view_state(cfg())["read_goal"] == "saved_history"
            units.extend(page["items"])
        assert {u["revision"] for u in units} == set(range(1, 9))
        assert all(u["version_view"] == "historical_exact_revision" for u in units)
        assert all("stored_history" not in u and u["committed_at"] for u in units)
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


def test_source_capture_version_and_fixed_pool_are_immutable(tmp_path: Path) -> None:
    with opened(tmp_path) as base:
        ref = base.service.capture_user("old", "raw", "Original bytes")["source_ref"]
        supplied = [{"source_ref": ref, "start": 0, "end": 8, "retrieval_score": 1.0}]
        memory = FunctionalMemory(
            base.service,
            len,
            retrieval_candidates=supplied,
        )
        turn(memory)
        assert memory.retrieval_candidates is not None
        supplied[0]["start"] = 1
        assert memory.retrieval_candidates[0]["start"] == 0
        archived = [unit for unit in memory._search_units("query") if unit.get("source_ref") == ref]
        assert len(archived) == 1 and archived[0]["content"] == "Original"
        with pytest.raises(ValueError, match="SOURCE_EVENT_CHANGED"):
            base.service.capture_user("old", "raw", "Changed bytes")
        assert base.service.source(ref)["content"] == "Original bytes"
        fragment = base.service.source_fragments(ref)[0]
        source = base.service.store.get(base.service.sources_namespace, ref)
        assert source is not None
        source.value["source_revision"] += 1
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
        assert secret in canonical(memory.context("s", "query", CONFIG_VERSION))
        assistant = memory.service.capture_assistant("s", "query:final", "It was " + secret)
        assert assistant["ok"]
        trigger = turn(memory, "forget", "forget password " + secret)
        handle = memory.service.read(saved["id"])["candidate_handle"]
        forgotten = invoke(
            memory, "forget_memory", {"read_handle": handle}, "forget-op", cfg("forget")
        )
        assert {ref, assistant["source_ref"], trigger} <= set(forgotten["revoked_source_refs"])
        assert exposed_query not in forgotten["revoked_source_refs"]
        assert secret not in canonical(memory.context("s", "forget", CONFIG_VERSION))
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
        assert secret not in canonical(reopened.context("s", "forget", CONFIG_VERSION))
        fresh = reopened.service.capture_user(
            "new-session", "query", "what password is remembered?"
        )
        assert fresh["ok"]
        packet = reopened.context("new-session", "query", CONFIG_VERSION)
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
 packet=m.context("fresh-process","query","synthetic-v1")
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
        b_packet = memory.context("s", "b", CONFIG_VERSION)
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
        packet = memory.context('s', 'q', CONFIG_VERSION)
        delivered = [u['source_ref'] for u in packet['items'] if u['type'] == 'fragment']
        assert delivered[:5] == [current, *refs[-4:]]
        assert refs[0] not in delivered and refs[1] not in delivered
        assert 'OTHER_SESSION' not in json.dumps(packet)
        fixed = FunctionalMemory(memory.service, len, recent_context='session_events_v1',
                                 material_limit=30000, retrieval_candidates=[])
        with pytest.raises(ValueError, match='SNAPSHOT_BINDING_CHANGED'):
            fixed.context('s', 'q', CONFIG_VERSION)
        fixed_current = memory.service.capture_user('fixed-session', 'q', '那个呢?')['source_ref']
        fixed_packet = fixed.context('fixed-session', 'q', CONFIG_VERSION)
        assert [u['source_ref'] for u in fixed_packet['items']] == [fixed_current]


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
                                        config_version=CONFIG_VERSION, phase='start')
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
        assert failure['source_ref'] not in json.dumps(memory.context('s', 'later', CONFIG_VERSION))


def test_bank_recent_context_resolves_cross_session_without_bypassing_visibility_or_fixed_pool(
    tmp_path: Path,
) -> None:
    with opened(tmp_path, recent_context='bank_recent_v2', material_limit=50000) as memory:
        ref = turn(memory, text='English field record: cobalt samples, only in this trial.')
        saved = invoke(memory, 'save_memory', {'content': 'Only this trial uses cobalt samples.',
            'fragment_handles': handles(memory, ref)}, 'save')
        assert saved['ok']
        memory.service.capture_user('other-session', 'query', '此前那条记录改一下。')
        packet = memory.context('other-session', 'query', CONFIG_VERSION)
        rows = [u for u in packet['items'] if u['type'] == 'record']
        assert len(rows) == 1 and rows[0]['record_id'] == saved['id']
        assert rows[0]['version_view'] == 'current_at_snapshot'
        assert any(u.get('source_ref') == ref for u in packet['items'])
        # Trusted fixed candidate pools admit no recency supplementation.
        controlled = FunctionalMemory(memory.service, len, recent_context='bank_recent_v2',
                                      retrieval_candidates=[], material_limit=50000)
        memory.service.capture_user('fixed', 'query', 'Unrelated controlled query.')
        fixed = controlled.context('fixed', 'query', CONFIG_VERSION)
        assert not any(u['type'] == 'record' or u.get('source_ref') == ref for u in fixed['items'])
        config = {'configurable': {'user_id': 'alice', 'v13_session': 'other-session',
            'v13_turn_id': 'query', 'v13_config_version': CONFIG_VERSION}}
        forgotten = invoke(memory, 'forget_memory', {'read_handle': rows[0]['read_handle']},
                           'forget', config)
        assert forgotten['ok']
        memory.service.capture_user('after-forget', 'query', '现在有什么记录?')
        visible = memory.context('after-forget', 'query', CONFIG_VERSION)
        assert not any(u['type'] == 'record' or u.get('source_ref') == ref
                       for u in visible['items'])
    with opened(tmp_path, owner='bob', recent_context='bank_recent_v2') as other:
        turn(other, text='Any recent records?')
        assert not other.service.records()
        assert 'cobalt' not in json.dumps(other.context('s', 'u', CONFIG_VERSION))


def test_revision_support_hook_sees_selected_originals_and_rejection_preserves_history(
    tmp_path: Path,
) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()
        if len(reviewed) == 1:
            raise FunctionalRejection('SCRIPTED_SUPPORT_REJECTION')

    with opened(tmp_path, revision_support_review=review) as memory:
        old_ref = turn(memory, text='Only this sample uses unit A; supplier labels are excluded.')
        saved = memory.save(cfg(), 'save', 'Only this sample uses unit A; labels excluded.',
                            handles(memory, old_ref), scope={'sample': 'this one'})
        initial = memory.service.read(saved['id'])
        new_ref = turn(memory, 'correct', 'For that sample, use unit B instead; retain exclusions.')
        changes = [{'field': 'content', 'op': 'set',
                    'value': 'Only this sample uses unit B; labels excluded.',
                    'fragment_handles': handles(memory, old_ref)}]
        rejected = invoke(memory, 'update_memory', {
            'read_handle': initial['candidate_handle'], 'changes': changes}, 'bad', cfg('correct'))
        assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
        assert memory.service.read(saved['id'])['value'] == initial['value']
        evidence = reviewed[0]
        assert evidence['record_id'] == saved['id'] and evidence['read_revision'] == 1
        assert evidence['old_scope'] == {'sample': 'this one'}
        assert len(evidence['changes']) == 1
        change = evidence['changes'][0]
        assert change['field'] == 'content' and change['after_present']
        assert change['before'] == initial['value']['content']
        assert change['after'] == changes[0]['value']
        quote = change['selected_original_fragments'][0]
        assert quote['source_role'] == 'user' and quote['source_ref'] == old_ref
        assert 'unit A' in quote['content'] and 'unit B' not in quote['content']
        assert new_ref not in [q['source_ref'] for q in change['selected_original_fragments']]
        changes[0]['fragment_handles'] = handles(memory, new_ref)
        good = memory.update(cfg('correct'), 'good', initial['candidate_handle'], changes)
        current = memory.service.read(saved['id'])['value']
        assert good['revision'] == 2 and current['scope'] == initial['value']['scope']
        assert current['functional_support']['scope.sample'] == initial['value'][
            'functional_support']['scope.sample']
        assert current['functional_support']['content']['source_refs'] == [new_ref]
        assert current['functional_support']['content']['semantic_support'] == 'unchecked'
        assert len(reviewed) == 2
        replay = memory.update(cfg('correct'), 'good', initial['candidate_handle'], changes)
        assert replay['status'] == 'no_change' and replay['replayed']
        assert replay['original_status'] == 'committed' and replay['revision'] == 2
        assert len(reviewed) == 2  # Durable commit replay does not run a new model review.
        noop = memory.update(cfg('correct'), 'no-change',
                             memory.service.read(saved['id'])['candidate_handle'], [])
        assert noop['status'] == 'no_change' and len(reviewed) == 2


def test_revision_support_hook_allows_same_source_reinterpretation_and_reviews_removals(
    tmp_path: Path,
) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()

    with opened(tmp_path, revision_support_review=review) as memory:
        ref = turn(memory, text='Use blue, not red. This applies without a project restriction.')
        saved = memory.save(cfg(), 'save', 'Use red.', handles(memory, ref), scope={'project': 'A'})
        handle = memory.service.read(saved['id'])['candidate_handle']
        fixed = memory.update(cfg(), 'reinterpret', handle, [
            {'field': 'content', 'op': 'set', 'value': 'Use blue.',
             'fragment_handles': handles(memory, ref)},
            {'field': 'scope.project', 'op': 'remove', 'fragment_handles': handles(memory, ref)},
        ])
        assert fixed['revision'] == 2
        changes = {r['field']: r for r in reviewed[0]['changes']}
        assert set(changes) == {'content', 'scope.project'}
        assert changes['scope.project']['before_present']
        assert not changes['scope.project']['after_present']
        assert all(q['source_ref'] == ref for c in changes.values()
                   for q in c['selected_original_fragments'])
        # Withdrawing has its own selected evidence even when content is unchanged.
        cancel = turn(memory, 'cancel', 'Withdraw that entire preference.')
        withdrawn = memory.update(cfg('cancel'), 'withdraw',
            memory.service.read(saved['id'])['candidate_handle'], [],
            fragment_handles=handles(memory, cancel), retract=True)
        assert withdrawn['revision'] == 3
        change = reviewed[1]['changes'][0]
        assert change['field'] == 'record' and change['after'] == 'withdrawn'
        assert change['selected_original_fragments'][0]['source_ref'] == cancel


@pytest.mark.parametrize('delivered', [False, True])
def test_revision_review_delivery_forget_does_not_revoke_independent_input(
    tmp_path: Path, delivered: bool,
) -> None:
    def review(evidence: dict[str, Any], report_delivery: Callable[[], None]) -> None:
        if delivered:
            report_delivery()
        raise FunctionalRejection('SCRIPTED_REVIEW_DECLINED_BEFORE_COMMIT')

    with opened(tmp_path, revision_support_review=review) as memory:
        secret = turn(memory, 'old', 'MECHANICAL_REVIEW_PRIVATE preference.')
        saved = memory.save(cfg('old'), 'save', 'MECHANICAL_REVIEW_PRIVATE preference.',
                            handles(memory, secret))
        original = memory.service.read(saved['id'])
        independent = memory.service.capture_user('s', 'change', 'Independent replacement input.')
        memory.service.bind_public_turn('s', 'change', independent['source_ref'],
                                        config_version=CONFIG_VERSION, phase='start')
        # No ordinary retrieval: any exposure below must come from the review callback.
        anchor = 'exposure:' + independent['source_ref']
        assert memory.service.store.get(namespace(memory.service), anchor) is None
        rejected = invoke(memory, 'update_memory', {'read_handle': original['candidate_handle'],
            'changes': [{'field': 'content', 'op': 'set', 'value': 'Replacement preference.',
                         'fragment_handles': handles(memory, secret)}]}, 'revise', cfg('change'))
        assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
        assert memory.service.read(saved['id'])['value'] == original['value']
        exposure = memory.service.store.get(namespace(memory.service), anchor)
        assert bool(exposure) is delivered
        if exposure is not None:
            assert exposure.value['source_refs'] == [secret]
        assistant = memory.service.capture_assistant('s', 'change:final',
            'Review of MECHANICAL_REVIEW_PRIVATE was declined.' if delivered else 'No review sent.')
        turn(memory, 'forget', 'Forget the old preference and its supporting input.')
        removed = invoke(memory, 'forget_memory', {'read_handle': original['candidate_handle']},
                         'forget', cfg('forget'))
        assert removed['ok']
        assert memory.service.source(secret) is None
        assert memory.service.source(independent['source_ref']) is not None
        assert (memory.service.source(assistant['source_ref']) is None) is delivered


def test_maintenance_limit_reopens_reuses_refusal_and_new_request_can_reaffirm(
    tmp_path: Path,
) -> None:
    from milai_lab.memory.functional_state import FunctionalReviewRejection

    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()
        if evidence['binding']['message_id'] == 'u':
            raise FunctionalReviewRejection(
                'SCRIPTED_ACTUAL_GAP', 'review_declined', evidence['proposal_id'])

    options = {'semantic_reproposal_policy': 'maintenance_two_proposals_v1',
               'formation_support_review': review, 'revision_support_review': review}
    with opened(tmp_path, **options) as memory:
        ref = turn(memory, text='Planned three visits weekly; start week undecided.')
        selected = handles(memory, ref)
        args = {'content': 'Three visits weekly.', 'fragment_handles': selected}
        first = invoke(memory, 'save_memory', args, 'first')
        assert first['review_status'] == 'review_declined'
        assert invoke(memory, 'save_memory', args, 'different-call-id') == first
        assert len(reviewed) == 1
        second = invoke(memory, 'save_memory',
                        {**args, 'content': 'Three weekly visits.'}, 'second')
        assert second['review_status'] == 'review_declined' and len(reviewed) == 2
    with opened(tmp_path, **options) as memory:
        turn(memory, text='Planned three visits weekly; start week undecided.')
        third = invoke(memory, 'save_memory',
                       {**args, 'content': 'Visits three times weekly.'}, 'third')
        assert third['effect'] == 'none' and third['formation_status'] == 'pending'
        assert third['maintenance']['proposals_used'] == third['maintenance']['proposal_limit'] == 2
        assert invoke(memory, 'save_memory', args, 'fourth') == first
        assert len(reviewed) == 2 and memory.service.source(ref) is not None
        new_ref = turn(memory, 'reaffirm', 'Please remember the planned frequency, start unknown.')
        new_args = {'content': 'Planned three visits weekly; start unknown.',
                    'fragment_handles': [*selected, *handles(memory, new_ref)]}
        saved = invoke(memory, 'save_memory', new_args, 'reaffirm-save', cfg('reaffirm'))
        assert saved['status'] == 'committed' and len(reviewed) == 3
        assert invoke(memory, 'save_memory', new_args, 'reaffirm-save', cfg('reaffirm'))['replayed']
        duplicate = invoke(memory, 'save_memory', new_args, 'new-id', cfg('reaffirm'))
        assert duplicate['status'] == 'no_change' and duplicate['existing_record']
        assert duplicate['id'] == saved['id'] and len(reviewed) == 3
        correction = turn(memory, 'later-change', 'Change the planned frequency to four.')
        memory.update(cfg('later-change'), 'update-later',
            memory.service.read(saved['id'])['candidate_handle'], [{'field': 'content',
                'op': 'set', 'value': 'Planned four visits weekly; start unknown.',
                'fragment_handles': [*handles(memory, correction), *selected]}])
        memory.context('s', 'reaffirm', CONFIG_VERSION)
        stale = invoke(memory, 'save_memory', new_args, 'stale-copy', cfg('reaffirm'))
        assert stale['status'] == 'rejected' and 'ORIGINAL_OPERATION_ID' in stale['reason']
        assert memory.service.read(saved['id'])['value']['revision'] == 2


def test_maintenance_limit_binds_record_not_wording_version_or_source_order(tmp_path: Path) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()
        if evidence['binding']['message_id'] == 'change':
            raise FunctionalRejection('SCRIPTED_REVISION_GAP')

    options = {'semantic_reproposal_policy': 'maintenance_two_proposals_v1',
               'formation_support_review': review, 'revision_support_review': review}
    with opened(tmp_path, **options) as memory:
        a = turn(memory, text='Only sample A: unit A.')
        ra = memory.save(cfg(), 'save-a', 'Only sample A: unit A.', handles(memory, a))
        b = turn(memory, 'b', 'Only sample B: unit B.')
        rb = memory.save(cfg('b'), 'save-b', 'Only sample B: unit B.', handles(memory, b))
        correction = turn(memory, 'change', 'For sample A use unit C; for sample B use unit D.')
        read_a = memory.service.read(ra['id'])
        selections = [*handles(memory, a), *handles(memory, correction)]
        args = {'read_handle': read_a['candidate_handle'], 'changes': [{'field': 'content',
            'op': 'set', 'value': 'Only sample A: unit C.', 'fragment_handles': selections}]}
        first = invoke(memory, 'update_memory', args, 'a1', cfg('change'))
        assert first['status'] == 'rejected'
        args['changes'][0]['fragment_handles'] = list(reversed(selections))
        assert invoke(memory, 'update_memory', args, 'a2', cfg('change'))['status'] == 'rejected'
        args['changes'][0]['value'] = 'For sample A only, unit C.'
        args['read_handle'] = memory.service.read(ra['id'])['candidate_handle']
        limited = invoke(memory, 'update_memory', args, 'a3', cfg('change'))
        assert limited['maintenance']['proposals_used'] == 2
        assert len(reviewed) == 4
        args_b = {'read_handle': memory.service.read(rb['id'])['candidate_handle'],
                  'changes': [{'field': 'content', 'op': 'set', 'value': 'Only sample B: unit D.',
                               'fragment_handles': handles(memory, correction)}]}
        assert invoke(memory, 'update_memory', args_b, 'b1', cfg('change'))['status'] == 'rejected'
        assert len(reviewed) == 5  # An independent actual target gets its own allowance.
        no_change = invoke(memory, 'update_memory', {'read_handle': read_a['candidate_handle'],
                           'changes': []}, 'unchanged', cfg('change'))
        assert no_change['status'] == 'no_change' and len(reviewed) == 5
        assert memory.service.read(ra['id'])['value'] == read_a['value']


def test_maintenance_refusal_cache_never_restores_forgotten_or_foreign_support(
    tmp_path: Path,
) -> None:
    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        raise FunctionalRejection('SCRIPTED_DECLINE')

    options = {'semantic_reproposal_policy': 'maintenance_two_proposals_v1',
               'formation_support_review': review, 'revision_support_review': review}
    with opened(tmp_path, **options) as memory:
        ref = turn(memory, text='PRIVATE_SUPPORT_FOR_REJECTION')
        args = {'content': 'PRIVATE_SUPPORT_FOR_REJECTION',
                'fragment_handles': handles(memory, ref)}
        assert invoke(memory, 'save_memory', args, 'decline')['reason'] == 'SCRIPTED_DECLINE'
        turn(memory, 'forget', 'Forget that source.')
        forgotten = invoke(memory, 'forget_memory', {'fragment_handles': args['fragment_handles']},
                           'forget', cfg('forget'))
        assert forgotten['ok']
        denied = invoke(memory, 'save_memory', args, 'again', cfg('forget'))
        assert denied['reason'] != 'SCRIPTED_DECLINE' and denied['effect'] == 'none'
    with opened(tmp_path, owner='bob', **options) as foreign:
        turn(foreign, text='A different owner.')
        denied = invoke(foreign, 'save_memory', args, 'foreign', cfg(owner='bob'))
        assert denied['reason'] != 'SCRIPTED_DECLINE' and denied['effect'] == 'none'


@pytest.mark.parametrize('after_commit', [False, True])
def test_maintenance_approval_does_not_replay_unknown_commit_as_new_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_commit: bool,
) -> None:
    from milai_lab.memory.functional_state import FunctionalOperationError

    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()

    options = {'semantic_reproposal_policy': 'maintenance_two_proposals_v1',
               'formation_support_review': review, 'revision_support_review': review}
    with opened(tmp_path, **options) as memory:
        ref = turn(memory, text='Only this trial uses unit A.')
        args = {'content': 'Only this trial uses unit A.', 'fragment_handles': handles(memory, ref)}
        commit = memory._commit

        def interrupted(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if after_commit:
                commit(*args, **kwargs)
            raise FunctionalOperationError('semantic_commit', ValueError('acknowledgment lost'))

        monkeypatch.setattr(memory, '_commit', interrupted)
        unknown = invoke(memory, 'save_memory', args, 'original')
        assert unknown['status'] == 'outcome_unknown' and unknown['error_type'] == 'ValueError'
        assert len(reviewed) == 1
    with opened(tmp_path, **options) as memory:
        turn(memory, text='Only this trial uses unit A.')
        prohibited = invoke(memory, 'save_memory', args, 'new-operation')
        if after_commit:
            assert prohibited['status'] == 'no_change' and prohibited['existing_record']
        else:
            assert prohibited['effect'] == 'none'
            assert 'ORIGINAL_OPERATION_ID' in prohibited['reason']
            changed = invoke(memory, 'save_memory',
                             {**args, 'content': 'Unit A is used only in this trial.'}, 'reworded')
            assert changed['effect'] == 'none' and 'PRIOR_OUTCOME_UNCONFIRMED' in changed['reason']
            assert changed['maintenance']['proposals_used'] == 1 and len(reviewed) == 1
        recovered = invoke(memory, 'save_memory', args, 'original')
        assert recovered['ok'] and len(reviewed) == 1
        assert recovered['status'] == ('no_change' if after_commit else 'committed')
        assert memory.service.read(recovered['id'])['value']['revision'] == 1


def test_maintenance_create_then_revise_actual_record_keeps_original_allowance(
    tmp_path: Path,
) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()

    options = {'semantic_reproposal_policy': 'maintenance_two_proposals_v1',
               'formation_support_review': review, 'revision_support_review': review}
    with opened(tmp_path, **options) as memory:
        ref = turn(memory, text='Only sample A uses unit A; other samples are unknown.')
        selected = handles(memory, ref)
        saved = memory.save(cfg(), 'create', 'Sample A uses unit A.', selected)
        row = memory.service.read(saved['id'])
        revised = invoke(memory, 'update_memory', {'read_handle': row['candidate_handle'],
            'changes': [{'field': 'content', 'op': 'set',
                         'value': 'Only sample A uses unit A; other samples are unknown.',
                         'fragment_handles': selected}]}, 'revision')
        assert revised['ok'] and revised['id'] == saved['id'] and revised['revision'] == 2
        assert len(reviewed) == 2
    with opened(tmp_path, **options) as memory:
        turn(memory, text='Only sample A uses unit A; other samples are unknown.')
        row = memory.service.read(saved['id'])
        limited = invoke(memory, 'update_memory', {'read_handle': row['candidate_handle'],
            'changes': [{'field': 'content', 'op': 'set',
                         'value': 'Unit A is used by sample A only; other samples remain unknown.',
                         'fragment_handles': selected}]}, 'third')
        assert limited['effect'] == 'none' and 'PROPOSAL_LIMIT' in limited['reason']
        assert limited['maintenance']['proposals_used'] == 2 and len(reviewed) == 2
        assert memory.service.read(saved['id'])['value'] == row['value']


def test_formation_review_rejection_preserves_raw_and_replay_skips_review(tmp_path: Path) -> None:
    reviewed: list[dict[str, Any]] = []

    def review(evidence: dict[str, Any], delivered: Callable[[], None]) -> None:
        reviewed.append(evidence)
        delivered()
        if len(reviewed) == 1:
            raise FunctionalRejection('SCRIPTED_SCOPE_AND_MODALITY_REJECTION')

    with opened(tmp_path, formation_support_review=review) as memory:
        ref = turn(memory, text='Only for this trial, imagine an early reminder; labels unchanged.')
        selected = handles(memory, ref)
        rejected = invoke(memory, 'save_memory', {'content': 'An early reminder is set.',
            'scope': {'activity': 'all'}, 'fragment_handles': selected}, 'wrong')
        assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
        assert memory.service.records() == [] and memory.service.source(ref) is not None
        evidence = reviewed[0]
        assert evidence['record_id'] is None and evidence['basis'] == 'user_statement'
        assert evidence['semantic_support'] == 'unchecked'
        changes = {c['field']: c for c in evidence['changes']}
        assert set(changes) == {'content', 'scope.activity'}
        assert changes['scope.activity']['after'] == 'all'
        assert all(not c['before_present'] and c['after_present'] for c in changes.values())
        assert all(q['source_role'] == 'user' and q['source_ref'] == ref
                   and 'Only for this trial' in q['content']
                   for c in changes.values() for q in c['selected_original_fragments'])
        args = {'content': 'Only this trial: imagine an early reminder; labels unchanged.',
                'scope': {'activity': 'this trial'}, 'fragment_handles': selected}
        saved = memory.save(cfg(), 'corrected', **args)
        current = memory.service.read(saved['id'])['value']
        assert saved['revision'] == 1 and len(memory.service.records()) == 1
        assert current['functional_support']['content']['semantic_support'] == 'unchecked'
        replay = memory.save(cfg(), 'corrected', **args)
        assert replay['replayed'] and replay['status'] == 'no_change'
        assert len(reviewed) == 2 and len(memory.service.records()) == 1


@pytest.mark.parametrize('delivered', [False, True])
def test_formation_review_rejection_exposure_preserves_independent_input(
    tmp_path: Path, delivered: bool,
) -> None:
    count = 0

    def review(evidence: dict[str, Any], report_delivery: Callable[[], None]) -> None:
        nonlocal count
        count += 1
        if count == 1:
            report_delivery()
            return
        if delivered:
            report_delivery()
        raise FunctionalRejection('SCRIPTED_FORMATION_DECLINED')

    with opened(tmp_path, formation_support_review=review) as memory:
        ref = turn(memory, 'old', 'MECHANICAL_FORMATION_PRIVATE is a temporary preference.')
        saved = memory.save(cfg('old'), 'old-save', 'MECHANICAL_FORMATION_PRIVATE preference.',
                            handles(memory, ref))
        initial = memory.service.read(saved['id'])
        independent = memory.service.capture_user('s', 'new', 'Independent new request.')
        memory.service.bind_public_turn('s', 'new', independent['source_ref'],
                                        config_version=CONFIG_VERSION, phase='start')
        anchor = 'exposure:' + independent['source_ref']
        assert memory.service.store.get(namespace(memory.service), anchor) is None
        rejected = invoke(memory, 'save_memory', {'content': 'A broader assertion.',
            'fragment_handles': handles(memory, ref)}, 'new-save', cfg('new'))
        assert rejected['status'] == 'rejected' and rejected['effect'] == 'none'
        assert len(memory.service.records()) == 1
        assert bool(memory.service.store.get(namespace(memory.service), anchor)) is delivered
        assistant = memory.service.capture_assistant('s', 'new:final',
            'MECHANICAL_FORMATION_PRIVATE assessment declined.' if delivered else 'No review.')
        turn(memory, 'forget', 'Forget the earlier private preference and sources.')
        forgotten = invoke(memory, 'forget_memory', {'read_handle': initial['candidate_handle']},
                           'forget', cfg('forget'))
        assert forgotten['ok'] and memory.service.source(ref) is None
        assert memory.service.source(independent['source_ref']) is not None
        assert (memory.service.source(assistant['source_ref']) is None) is delivered


@pytest.mark.parametrize(("name", "args"), [
    ("read_memory", {"record_id": "issued", "revision": ""}),
    ("read_memory_history", {"record_id": "issued", "revision": "None"}),
    ("read_memory_revision", {"record_id": "issued", "revision": "1"}),
    ("read_memory_revision", {"record_id": "issued", "revision": True}),
    ("read_memory_revision", {"record_id": "issued", "revision": None}),
    ("read_memory_revision", {"record_id": "issued", "revision": 0}),
    ("read_source", {"source_ref": "issued", "fragment_handle": None}),
    ("read_fragment", {"fragment_handle": None}),
    ("read_page", {"cursor": ""}),
    ("read_page", {"cursor": "issued", "record_id": "unused"}),
])
def test_explicit_read_selectors_reject_placeholders_and_extra_fields_before_execution(
    tmp_path: Path, name: str, args: dict[str, Any],
) -> None:
    import jsonschema
    from langchain_core.utils.function_calling import convert_to_openai_tool

    with opened(tmp_path, read_interface="explicit_selectors_v1") as memory:
        turn(memory)
        tool = next(t for t in memory.tools() if t.name == name)
        schema = convert_to_openai_tool(tool)['function']['parameters']
        assert schema['additionalProperties'] is False
        assert set(schema['required']) == set(schema['properties'])
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(args, schema)
        with pytest.raises(ValidationError):
            invoke(memory, name, args, 'bad')
        assert memory.service.records() == []
        assert not any(item.key.startswith('read-admission:')
                       for item in memory.service.store.search(namespace(memory.service)))


def test_explicit_read_shared_budget_identity_and_owner_survive_reopen(tmp_path: Path) -> None:
    options = {"read_interface": "explicit_selectors_v1", "memory_view_mode": "state_driven"}
    admission_key = "read-admission:" + reference_key(["s", "u"])
    with opened(tmp_path, **options) as memory:
        ref = turn(memory, text='Personal record with original support.')
        fragment = handles(memory, ref)[0]
        saved = memory.save(cfg(), 'save', 'Personal record with original support.', [fragment])
        current = memory.service.read(saved['id'])
        original = invoke(memory, 'read_source', {'source_ref': ref}, 'first')
        admission = memory.service.store.get(namespace(memory.service), admission_key)
        assert admission is not None
        omitted_arguments = admission.value['calls']['first']['arguments']
        assert omitted_arguments == {'tool': 'read_source', 'source_ref': ref,
                                     'keep_resident': False}
        exact = invoke(memory, 'read_memory_revision',
                       {'record_id': saved['id'], 'revision': 1,
                        'read_goal': 'saved_history'}, 'second')
        assert original['ok'] and exact['items'][0]['revision'] == 1
        assert exact['items'][0]['version_view'] == 'historical_exact_revision'
        assert memory.view_state(cfg())['read_goal'] == 'saved_history'
        with pytest.raises(FunctionalRejection, match='READ_CALL_CHANGED'):
            invoke(memory, 'read_source', {'source_ref': ref, 'read_goal': 'original_source'},
                   'first')
        with pytest.raises(FunctionalRejection, match='OWNER_MISMATCH'):
            invoke(memory, 'read_memory_history', {'record_id': saved['id']}, 'wrong-owner',
                   cfg(owner='bob'))
        with pytest.raises(FunctionalRejection, match='READ_CALL_CHANGED'):
            invoke(memory, 'read_memory', {'record_id': saved['id']}, 'second')
    with opened(tmp_path, **options) as memory:
        memory.context('s', 'u', CONFIG_VERSION)
        assert invoke(memory, 'read_source', {'source_ref': ref}, 'first') == original
        admission = memory.service.store.get(namespace(memory.service), admission_key)
        assert admission is not None and len(admission.value['calls']) == 2
        assert admission.value['calls']['first']['arguments'] == omitted_arguments
        assert memory.view_state(cfg())['read_goal'] == 'saved_history'
        assert invoke(memory, 'read_fragment', {'fragment_handle': fragment}, 'third')['ok']
        assert memory.view_state(cfg())['read_goal'] == 'saved_history'
        exhausted = invoke(memory, 'read_memory_history', {'record_id': saved['id']}, 'fourth')
        assert exhausted['status'] == 'read_limit_exhausted'
        assert memory.service.read(saved['id'])['value'] == current['value']
        assert memory.service.history_index(saved['id'])['revisions'] == [1]
    with opened(tmp_path, owner='bob', **options) as memory:
        memory.service.capture_user('s', 'u', 'Unrelated user asks about history.')
        memory.context('s', 'u', CONFIG_VERSION)
        result = invoke(memory, 'read_memory_history', {'record_id': saved['id']}, 'foreign',
                        cfg(owner='bob'))
        assert not result['ok'] and 'Personal record' not in canonical(result)
