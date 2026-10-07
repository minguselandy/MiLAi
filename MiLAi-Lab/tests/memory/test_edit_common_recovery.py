"""Actual persistent recovery after removal of content-derived identities."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.native_journal import NativePublicActionJournal
from milai_lab.application.world import ApplicationWorld
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.functional import _bank_reference, _message_reference, _thread_reference


def request(name: str, arguments: dict[str, Any], generation: str) -> Any:
    return SimpleNamespace(
        tool_call={"name": name, "args": arguments, "id": generation},
        state={
            "messages": [
                HumanMessage(content="original request"),
                AIMessage(content="", id=generation),
            ]
        },
        runtime=SimpleNamespace(
            config={
                "max_concurrency": 1,
                "configurable": {
                    "thread_id": "thread",
                    "foundation_run_id": "run",
                    "arm_id": "arm",
                    "user_id": "alice",
                },
            }
        ),
    )


def test_legacy_operation_identity_keeps_confirmed_effect_and_resolution(tmp_path: Path) -> None:
    args = {"item_key": "item", "quantity": 1, "destination": "local", "packing": "box"}
    binding = {
        "run_id": "run",
        "arm_id": "arm",
        "owner": "alice",
        "thread_id": "thread",
        "message_id": "m",
        "public_index": 0,
        "task_id": "task",
        "operations": [
            {"operation_id": "reserve", "tool": "reserve_and_label", "args": args, "target": args}
        ],
    }
    path = tmp_path / "journal.json"
    original = BusinessActionJournal(path, ["reserve_and_label"], application_protection=True)
    original.bind_request(binding)
    world = ApplicationWorld(tmp_path / "world.sqlite", True)
    try:
        original(
            request("reserve_and_label", args, "first"),
            lambda call: ToolMessage(
                content=world.reserve_and_label("alice", **args), tool_call_id="first"
            ),
        )
        stored = read_json(path)
        app = stored["_application"]
        binding_id = next(iter(app["bindings"]))
        old_operation = next(iter(app["operations"]))
        legacy_binding, legacy_operation = "a" * 64, "b" * 64
        app["bindings"] = {legacy_binding: {"hash": legacy_binding, "binding": binding}}
        app["operations"] = {legacy_operation: app["operations"][old_operation]}
        app["resolved"] = {legacy_operation: args}
        app.pop("operation_identities", None)
        for row in stored.values():
            if isinstance(row, dict) and row.get("binding_id") == binding_id:
                row["binding_hash"] = legacy_binding
                row.pop("binding_id")
                row["operation_key"] = legacy_operation
        write_json(path, stored)
        reopened = BusinessActionJournal(path, ["reserve_and_label"], application_protection=True)
        reopened.bind_request(binding)
        assert reopened.operation_key(binding, "reserve") == legacy_operation
        dispatches = []
        result = reopened(
            request("reserve_and_label", args, "second"), lambda call: dispatches.append(call)
        )
        assert (
            json.loads(result.content)["status"] == "APPLICATION_OPERATION_EFFECT_ALREADY_CONFIRMED"
        )
        assert not dispatches
        assert world.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert read_json(path)["_application"]["resolved"][legacy_operation] == args
    finally:
        world.close()


@pytest.mark.parametrize("available,effect", [(True, "confirmed"), (False, "partial")])
def test_discovered_unknown_effect_cannot_repeat_in_new_public_turn(
    tmp_path: Path,
    available: bool,
    effect: str,
) -> None:
    world = ApplicationWorld(tmp_path / "world.sqlite", available)
    args = {"item_key": "item", "quantity": 1, "destination": "local", "packing": "box"}
    journal = NativePublicActionJournal(
        tmp_path / "journal.json",
        ["reserve_and_label", "get_reservation"],
        owner="alice",
        world=world,
    )
    journal.bind_public_turn(
        "s",
        "first",
        {
            "owner": "alice",
            "session": "s",
            "role": "user",
            "event_id": "original-source",
            "source_revision": 1,
        },
    )

    def interrupted(call: Any) -> Any:
        world.reserve_and_label("alice", **args)
        raise OSError("real effect committed but response lost")

    try:
        with pytest.raises(OSError):
            journal(request("reserve_and_label", args, "lost"), interrupted)
        journal.bind_public_turn(
            "next",
            "second",
            {
                "owner": "alice",
                "session": "next",
                "role": "user",
                "event_id": "next-source",
                "source_revision": 1,
            },
        )
        journal(
            request("get_reservation", {"item_key": "item"}, "query"),
            lambda call: ToolMessage(
                content=world.get_reservation("alice", "item"), tool_call_id="query"
            ),
        )
        original = next(
            row
            for row in read_json(journal.path).values()
            if isinstance(row, dict) and row.get("call_id") == "lost"
        )
        assert original["status"] == "pending" and "result" not in original
        assert journal.recovery_for_call(original["journal_key"])["effect"] == effect
        dispatches = []
        rejected = journal(
            request("reserve_and_label", args, "repeat"), lambda call: dispatches.append(call)
        )
        assert json.loads(rejected.content)["status"] == "operation_effect_already_observed"
        assert not dispatches
        assert world.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    finally:
        world.close()


def test_existing_store_namespace_and_message_reopen_with_opaque_legacy_ids(tmp_path: Path) -> None:
    legacy = "c" * 64
    bank = tmp_path / "banks" / legacy
    bank.mkdir(parents=True)
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        store.put(("functional", "run", "bank", "alice", "records"), "record", {"content": "kept"})
    assert _bank_reference(tmp_path, "run", "bank", "alice") == legacy
    assert _bank_reference(tmp_path, "run", "bank", "alice") == legacy
    write_json(bank / ("d" * 64 + "-input.json"), {"session": "s", "message_id": "m"})
    assert _message_reference(bank, "s", "m") == "d" * 64
    assert _bank_reference(tmp_path, "run", "bank", "bob") != legacy


def test_existing_sdk_checkpoint_reuses_opaque_thread_by_public_message_metadata(
    tmp_path: Path,
) -> None:
    identity = {"foundation_run_id": "run", "arm_id": "bank", "user_id": "alice",
                "v13_session": "s", "v13_turn_id": "m"}
    legacy = "e" * 64
    config: Any = {"configurable": {**identity, "thread_id": "new-ordinary-id"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"messages": [HumanMessage(content="saved old request")]}
        saver.put({"configurable": {**identity, "thread_id": legacy, "checkpoint_ns": ""}},
                  checkpoint, {"source": "input", "step": 0, "parents": {}}, {})
        assert _thread_reference(tmp_path, saver, config) == legacy
        assert _thread_reference(tmp_path, saver, config) == legacy
        old = saver.get_tuple({"configurable": {"thread_id": legacy}})
        assert old is not None
        assert old.checkpoint["channel_values"]["messages"][0].content == "saved old request"
        other = {"configurable": {**identity, "v13_turn_id": "next",
                                  "thread_id": "next-ordinary-id"}}
        assert _thread_reference(tmp_path, saver, other) == "next-ordinary-id"
