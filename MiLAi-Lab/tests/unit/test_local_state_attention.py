"""Zero-model checks for the P1 Store, graph hook and application path."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from jsonschema import ValidationError, validate

pytest.importorskip("langmem")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.base import PutOp
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, build_agent, invoke_public_message
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    LocalStateController,
    control_schema,
)
from milai_lab.methods.local_state_attention.integration import (
    SOURCE_VIEW_HEADER,
    _source_view,
    make_pre_model_hook,
)
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners import langmem_application_runtime as app_runtime
from milai_lab.runners.langmem_application import run_phase


def _response(value: dict[str, Any], index: int) -> httpx.Response:
    return httpx.Response(200, json={
        "id": f"mock-{index}", "model": "mock",
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(value)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


class LruReplies:
    def __init__(self, answers: dict[str, list[Any]]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
        stage = kwargs["response_format"]["json_schema"]["name"].removeprefix(
            "local_state_").removesuffix("_v1")
        self.calls.append({"stage": stage, "payload": json.loads(messages[1]["content"]),
                           "context_stage": CONTROL_STAGE.get(),
                           "prompt": messages[0]["content"],
                           "schema": kwargs["response_format"]["json_schema"]["schema"]})
        answer = self.answers[stage].pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(json.loads(messages[1]["content"]))
        return {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(answer)}}]}


def test_bank_order_noop_pending_scope_and_deletion() -> None:
    bank = LocalStateBank(InMemoryStore())
    alice = StateScope("run", "lsa", "alice")
    bob = StateScope("run", "lsa", "bob")
    bank.record_event(alice, {"id": "z", "kind": "user", "content": "first"})
    bank.record_event(alice, {"id": "a", "kind": "tool", "content": '{"ok":false}'})
    assert [row["id"] for row in bank.pending(alice)] == ["z", "a"]
    edit = {"id": None, "title": "matter", "content": "partially done",
            "evidence": ["a"]}
    receipts, invalid = bank.apply(alice, [edit], {"z", "a"})
    assert not invalid and receipts[0]["status"] == "created"
    state_id = receipts[0]["id"]
    assert bank.states(alice)[0]["dependency_source_ids"] == ["a", "z"]
    assert bank.states(bob) == []
    assert bank.pending(alice) == []
    puts_before_noop = bank.store_stats()["put"]["calls"]
    receipts, invalid = bank.apply(alice, [{**edit, "id": state_id}], set())
    assert not invalid and receipts[0]["status"] == "noop"
    assert bank.states(alice)[0]["revision"] == 1
    assert bank.store_stats()["put"]["calls"] == puts_before_noop
    bank.record_event(alice, {"id": "next", "kind": "user", "content": "new"})
    receipts, invalid = bank.apply(alice, [{"id": "missing", "content": "wrong",
                                            "evidence": ["next"]}], {"next"})
    assert invalid and receipts[0]["status"] == "skipped_invalid_edit"
    assert [row["id"] for row in bank.pending(alice)] == ["next"]
    assert bank.forget_source(alice, "a") == [state_id]
    assert bank.states(alice) == []
    assert all(row["id"] != "a" for row in bank.events(alice))
    bank.record_event(alice, {"id": "a", "kind": "tool", "content": '{"ok":false}'})
    assert all(row["id"] != "a" for row in bank.events(alice))
    bank.delete_scope(alice)
    bank.record_event(alice, {"id": "z", "kind": "user", "content": "first"})
    assert bank.events(alice) == []


def test_shared_aggregate_content_boundary_and_local_unaffected_state() -> None:
    bank = LocalStateBank(InMemoryStore(), max_states=8,
                          max_state_content_chars=4000, max_total_content_chars=16000)
    scope = StateScope("run", "local_all_sources", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "four matters"})
    edits = [{"id": None, "title": f"matter {index}", "content": str(index) * 4000}
             for index in range(4)]
    receipts, invalid = bank.apply(scope, edits, {"seed"}, query_source_id="seed")
    assert not invalid and all(row["status"] == "created" for row in receipts)
    assert sum(len(row["content"]) for row in bank.states(scope)) == 16000
    bank.record_event(scope, {"id": "extra", "kind": "user", "content": "another matter"})
    overflow, invalid = bank.apply(scope, [{"id": None, "title": "fifth", "content": "x"}],
                                   {"extra"}, query_source_id="extra")
    assert invalid and overflow[0]["reason"] == "aggregate_content_limit"
    assert [row["id"] for row in bank.pending(scope)] == ["extra"]
    before = {row["id"]: row for row in bank.states(scope)}
    first_id = receipts[0]["id"]
    revised, invalid = bank.apply(scope, [{"id": first_id, "content": "0" * 3999}],
                                  {"extra"}, query_source_id="extra")
    assert not invalid and revised[0]["status"] == "updated"
    after = {row["id"]: row for row in bank.states(scope)}
    assert all(after[key] == value for key, value in before.items() if key != first_id)
    assert [row["id"] for row in bank.pending(scope)] == []
    too_long, invalid = bank.apply(scope, [{"id": first_id, "content": "x" * 4001}], set())
    assert invalid and too_long[0]["reason"] == "state_content_limit"
    assert bank.states(scope) == list(sorted(after.values(), key=lambda row: row["id"]))


def test_global_note_create_update_noop_schema_pending_and_deletion() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store, max_states=1, max_state_content_chars=16000,
                          max_total_content_chars=16000)
    scope = StateScope("run", "global_note_sources", "alice")
    calls: list[dict[str, Any]] = []

    class GlobalControl:
        def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
            payload = json.loads(messages[1]["content"])
            schema = kwargs["response_format"]["json_schema"]["schema"]
            calls.append({"prompt": messages[0]["content"],
                          "payload": payload, "schema": schema})
            if len(calls) == 1:
                plan = {"edits": [{"id": None, "title": "Working note",
                                    "content": "first matter", "evidence": ["first"]}],
                        "focus": ["new:0"]}
            else:
                note_id = bank.states(scope)[0]["id"]
                plan = {"edits": [{"id": note_id,
                                    "content": "first matter; second matter"}],
                        "focus": [note_id]}
            validate(plan, schema)
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(plan)}}]}

    controller = LocalStateController(bank, GlobalControl(),  # type: ignore[arg-type]
                                      representation="global_note")
    bank.record_event(scope, {"id": "first", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": "first matter"})
    created = controller.prepare(scope, "first", "first matter")
    assert created["receipts"][0]["status"] == "created"
    note_id = bank.states(scope)[0]["id"]
    assert len(bank.states(scope)) == 1 and bank.states(scope)[0]["revision"] == 1
    assert "Maintain one global working note" in calls[0]["prompt"]
    assert "Maintain short local States" not in calls[0]["prompt"]
    bank.record_event(scope, {"id": "second", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": "second matter"})
    updated = controller.prepare(scope, "second", "second matter")
    assert updated["receipts"][0]["status"] == "updated"
    assert bank.states(scope)[0]["revision"] == 2
    with pytest.raises(ValidationError):
        validate({"edits": [{"id": None, "title": "illegal second note",
                              "content": "another"}], "focus": ["new:0"]},
                 calls[1]["schema"])
    assert calls[1]["payload"]["new_observations"] == [{
        "id": "second", "kind": "user", "actor": "alice",
        "tool_call_id": None, "content": "second matter"}]
    bank.record_event(scope, {"id": "third", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": "no new fact"})
    puts_before = bank.store_stats()["put"]["calls"]
    noop = controller.prepare(scope, "third", "no new fact")
    assert noop["receipts"][0]["status"] == "noop"
    assert bank.states(scope)[0]["revision"] == 2
    assert bank.store_stats()["put"]["calls"] == puts_before + 2  # event settled, focus
    bank.record_event(scope, {"id": "oversize", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": "long note"})
    rejected, invalid = bank.apply(scope, [{"id": note_id, "content": "x" * 16001}],
                                   {"oversize"}, query_source_id="oversize")
    assert invalid and rejected[0]["reason"] == "state_content_limit"
    assert [row["id"] for row in bank.pending(scope)] == ["oversize"]
    assert bank.forget_source(scope, "first") == [note_id]
    assert bank.states(scope) == []
    assert bank.is_forgotten(scope, "first")
    assert "second" in {row["id"] for row in bank.events(scope)}
    exact_scope = StateScope("run", "global_note_sources", "bob")
    exact, invalid = bank.apply(exact_scope, [{"id": None, "title": "Working note",
                                              "content": "x" * 16000}], set())
    assert not invalid and exact[0]["status"] == "created"
    assert len(bank.states(exact_scope)[0]["content"]) == 16000


def test_dependency_tracks_cross_state_copy_without_model_evidence() -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "lsa", "alice")
    for source_id in ("source-a", "source-b"):
        bank.record_event(scope, {"id": source_id, "kind": "user", "content": source_id})
    first, invalid = bank.apply(scope, [{"id": None, "title": "first",
                                         "content": "fact from source-a", "evidence": []}],
                                {"source-a"}, query_source_id="source-a")
    assert not invalid
    second, invalid = bank.apply(scope, [{"id": None, "title": "second",
                                          "content": "fact copied from first", "evidence": []}],
                                 set(), query_source_id="source-b")
    assert not invalid
    by_id = {row["id"]: row for row in bank.states(scope)}
    assert by_id[second[0]["id"]]["dependency_source_ids"] == ["source-a", "source-b"]
    bank.set_focus(scope, "source-b", [first[0]["id"], second[0]["id"]])
    assert set(bank.forget_source(scope, "source-a")) == {
        first[0]["id"], second[0]["id"]}
    assert bank.states(scope) == []
    assert [row["id"] for row in bank.events(scope)] == ["source-b"]
    assert bank.focus(scope, "source-b") == []
    bank.record_event(scope, {"id": "source-a", "kind": "user", "content": "replayed"})
    assert [row["id"] for row in bank.events(scope)] == ["source-b"]


def test_legacy_unknown_dependency_propagates_and_deletes_conservatively() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "lsa", "alice")
    store.put(scope.namespace("states"), "legacy", {
        "id": "legacy", "title": "old", "content": "untracked source material",
        "needs": [], "evidence_refs": [], "revision": 1, "archived": False}, index=False)
    bank.record_event(scope, {"id": "visible", "kind": "user", "content": "continue"})
    receipts, invalid = bank.apply(scope, [{"id": None, "title": "derived",
                                          "content": "from old state", "evidence": []}],
                                   {"visible"}, query_source_id="visible")
    assert not invalid
    derived = next(row for row in bank.states(scope) if row["id"] == receipts[0]["id"])
    assert derived["dependency_unknown"] is True
    assert set(bank.forget_source(scope, "unknown-old-source")) == {"legacy", derived["id"]}
    assert bank.states(scope) == []
    assert [row["id"] for row in bank.events(scope)] == ["visible"]


def test_bank_stats_match_actual_store_calls_and_failure() -> None:
    class CountingStore(InMemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self.calls: dict[str, int] = {name: 0 for name in (
                "get", "search", "put", "delete")}

        def get(self, *args: Any, **kwargs: Any) -> Any:
            self.calls["get"] += 1
            return super().get(*args, **kwargs)

        def search(self, *args: Any, **kwargs: Any) -> Any:
            self.calls["search"] += 1
            return super().search(*args, **kwargs)

        def put(self, *args: Any, **kwargs: Any) -> Any:
            self.calls["put"] += 1
            return super().put(*args, **kwargs)

        def delete(self, *args: Any, **kwargs: Any) -> Any:
            self.calls["delete"] += 1
            return super().delete(*args, **kwargs)

    store = CountingStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "lsa", "alice")
    bank.record_event(scope, {"id": "source", "kind": "user", "content": "fact"})
    bank.apply(scope, [{"id": None, "title": "matter", "content": "fact"}],
               {"source"}, query_source_id="source")
    bank.forget_source(scope, "source")
    stats = bank.store_stats()
    assert {operation: row["calls"] for operation, row in stats.items()} == store.calls
    assert all(row["failures"] == 0 and row["wall_ns"] >= 0 and row["cpu_ns"] >= 0
               for row in stats.values())
    assert stats["put"]["request_bytes"] > 0
    assert stats["search"]["result_bytes"] > 0


def test_hook_preserves_checkpoint_and_partial_tool_json(tmp_path: Path) -> None:
    script = {"initial_label_available": False, "phases": [{
        "id": 0, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": "reserve", "user_id": "alice", "session_id": "main",
            "public_index": 0, "text": "Reserve an item once."}]}]}
    wires: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        wires.append(payload)
        if payload["response_format"]["json_schema"]["name"] == "local_state_control_v1":
            observations = json.loads(payload["messages"][1]["content"])["new_observations"]
            if observations[0]["kind"] == "user":
                return _response({"edits": [{"id": None, "title": "item work",
                                            "content": "reservation requested",
                                            "evidence": [observations[0]["id"]]}],
                                  "focus": ["new:0"]}, len(wires))
            return _response({"edits": [], "focus": []}, len(wires))
        host_count = sum(wire["response_format"]["json_schema"]["name"] ==
                         "langmem_json_action_v1" for wire in wires)
        if host_count == 1:
            return _response({"calls": [{"name": "reserve_and_label", "arguments": {
                "item_key": "item", "quantity": 1, "destination": "east",
                "packing": "foam"}}]}, len(wires))
        return _response({"answer": "Reservation remains; label failed."}, len(wires))

    config = VLLMConfig(base_url="http://mock/v1/", model="mock")
    store = InMemoryStore()
    with VLLMClient(config, transport=httpx.MockTransport(respond)) as host:
        with VLLMClient(config, transport=httpx.MockTransport(respond)) as control:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                model = VLLMChatModel(client=host)
                bank = LocalStateBank(store)
                controller = LocalStateController(bank, control, emit=views.append)
                runtime = SimpleNamespace(model=model, store=store, checkpointer=saver,
                                          observer=SimpleNamespace(
                                              assert_healthy=lambda: None,
                                              run_tool=lambda request, execute, _: (
                                                  execute(request))))
                result = run_phase(script, tmp_path, "run", "local_state", 0,
                                   runtime, controller)
                scope = FoundationScope("run", "local_state", "alice", "application:main")
                graph = build_agent(model, store, saver,
                                    local_state_controller=controller)
                snapshot = graph.get_state(scope.config()).values["messages"]
    assert result["world"]["reservations"][0]["label_status"] == "not_created"
    assert sum(isinstance(item, HumanMessage) for item in snapshot) == 1
    tool = next(item for item in snapshot if isinstance(item, ToolMessage))
    assert json.loads(tool.content)["status"] == "reserved_label_failed"
    state_scope = StateScope("run", "local_state", "alice")
    assert any(row["kind"] == "tool" and "reserved_label_failed" in row["content"]
               for row in bank.events(state_scope))
    assert bank.pending(state_scope) == []
    assert len(bank.states(state_scope)) == 1
    assert any(view["event"] == "lsa_view" and view["states"] for view in views)
    state_id = bank.states(state_scope)[0]["id"]
    assert all(state_id not in wire["messages"][0]["content"]
               for wire in wires if wire["response_format"]["json_schema"]["name"] ==
               "langmem_json_action_v1")
    assert all('"revision"' not in wire["messages"][0]["content"]
               for wire in wires if wire["response_format"]["json_schema"]["name"] ==
               "langmem_json_action_v1")
    assert any(view["states"][0]["id"] == state_id
               for view in views if view["event"] == "lsa_view" and view["states"])
    control_wire = wires[0]
    legacy_payload = json.loads(control_wire["messages"][1]["content"])
    assert "current_task" in legacy_payload
    user_event = legacy_payload["new_observations"][0]
    assert user_event["kind"] == "user" and user_event["actor"] == "alice"
    assert user_event["tool_call_id"] is None
    tool_wire = next(wire for wire in wires if wire is not control_wire and
                     wire["response_format"]["json_schema"]["name"] ==
                     "local_state_control_v1")
    tool_event = json.loads(tool_wire["messages"][1]["content"])["new_observations"][0]
    assert tool_event["kind"] == "tool" and tool_event["tool_call_id"]
    assert tool_event["actor"] != "alice"
    assert "does not prove an operation" in control_wire["messages"][0]["content"]
    assert "partial effect when ok=false" in control_wire["messages"][0]["content"]
    assert "nonempty title" in control_wire["messages"][0]["content"]
    assert "Never put a title" in control_wire["messages"][0]["content"]
    assert control_wire["response_format"]["json_schema"]["schema"] == control_schema([], 32)
    assert set(control_wire["response_format"]["json_schema"]["schema"]["required"]) == {
        "edits", "focus"}
    host_wires = [wire for wire in wires if wire["response_format"]["json_schema"]["name"]
                  == "langmem_json_action_v1"]
    assert len(host_wires) == 2
    assert "Local State working view" in host_wires[0]["messages"][0]["content"]
    assert any(row["role"] == "tool" and "reserved_label_failed" in row["content"]
               for row in host_wires[1]["messages"])


def test_all_and_focus_read_same_bank_without_extra_control_or_host_id_leak(
    tmp_path: Path,
) -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "local_state", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "seed"})
    receipts, invalid = bank.apply(scope, [
        {"id": None, "title": "First matter", "content": "first fact"},
        {"id": None, "title": "Second matter", "content": "second fact"},
    ], {"seed"}, query_source_id="seed")
    assert not invalid
    first_id, second_id = (row["id"] for row in receipts)
    control_payloads: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []

    class FocusControl:
        def chat(self, messages: Any, **_kwargs: Any) -> dict[str, Any]:
            control_payloads.append(json.loads(messages[1]["content"]))
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "edits": [], "focus": [first_id]})}}]}

    controller = LocalStateController(bank, FocusControl(), emit=views.append)  # type: ignore[arg-type]
    host_wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        host_wires.append(json.loads(request.read()))
        return _response({"answer": "done"}, len(host_wires))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond)) as host:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            model = VLLMChatModel(client=host)
            for read_policy in ("focus", "all"):
                agent = build_agent(model, store, saver,
                                    local_state_controller=controller,
                                    local_state_read_policy=read_policy)
                invoke_public_message(agent, model, FoundationScope(
                    "run", "local_state", "alice", read_policy), "Current task")
            assert len(host_wires) == 2 and len(control_payloads) == 2
            focus_wire, all_wire = host_wires
            assert "First matter" in focus_wire["messages"][0]["content"]
            assert "Second matter" not in focus_wire["messages"][0]["content"]
            assert "First matter" in all_wire["messages"][0]["content"]
            assert "Second matter" in all_wire["messages"][0]["content"]
            assert [wire["messages"][1]["content"] for wire in host_wires] == [
                "Current task", "Current task"]
            assert all(first_id not in wire["messages"][0]["content"] and
                       second_id not in wire["messages"][0]["content"] and
                       '"revision"' not in wire["messages"][0]["content"]
                       for wire in host_wires)
            assert all({row["id"] for row in payload["states"]} == {first_id, second_id}
                       and all(row["revision"] == 1 for row in payload["states"])
                       for payload in control_payloads)
            delivered = [view for view in views if view["event"] == "lsa_view"]
            assert [(view["read_policy"], view["focus"],
                     view["controller_focus"], view["delivered_state_ids"])
                    for view in delivered] == [
                        ("focus", [first_id], [first_id], [first_id]),
                        ("all", [first_id], [first_id], sorted([first_id, second_id]))]
            assert all(all("revision" in row and "id" in row for row in view["states"])
                       for view in delivered)

            class RejectFullBank:
                enable_thinking = None

                def check(self, messages: Any, *_args: Any) -> Any:
                    assert "Second matter" in messages[0]["content"]
                    raise CapacityExceeded({"context_tokens": 1})

            host.capacity = RejectFullBank()  # type: ignore[assignment]
            agent = build_agent(model, store, saver, local_state_controller=controller,
                                local_state_read_policy="all")
            with pytest.raises(CapacityExceeded):
                invoke_public_message(agent, model, FoundationScope(
                    "run", "local_state", "alice", "full-over-capacity"), "Current task")
            assert len(host_wires) == 2 and len(control_payloads) == 3


def test_source_view_live_arm_expands_only_cited_events_on_actual_host_wire(
    tmp_path: Path,
) -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "local_all_sources", "alice")
    user_content = "The exact item is Café archive crates."
    receipt_content = '{"ok":false,"item_key":"Café archive crates","quantity":2}'
    bank.record_event(scope, {"id": "source-user", "kind": "user", "actor": "alice",
                              "tool_call_id": None, "content": user_content})
    bank.record_event(scope, {"id": "source-tool", "kind": "tool",
                              "actor": "reserve_and_label", "tool_call_id": "call-1",
                              "content": receipt_content})
    receipts, invalid = bank.apply(scope, [
        {"id": None, "title": "Matter", "content": "compressed summary",
         "evidence": ["source-user", "source-tool"]},
        {"id": None, "title": "Another matter", "content": "same cited receipt",
         "evidence": ["source-tool"]},
        {"id": None, "title": "Uncited matter", "content": "no citation"},
    ], {"source-user", "source-tool"}, query_source_id="source-user")
    assert not invalid
    control_payloads: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []

    class SameControl:
        def chat(self, messages: Any, **_kwargs: Any) -> dict[str, Any]:
            control_payloads.append(json.loads(messages[1]["content"]))
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"edits":[],"focus":[]}'}}]}

    controller = LocalStateController(bank, SameControl(), emit=views.append)  # type: ignore[arg-type]
    host_wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        host_wires.append(json.loads(request.read()))
        return _response({"answer": "done"}, len(host_wires))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond)) as host:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            model = VLLMChatModel(client=host)
            for policy in ("all", "all_sources"):
                agent = build_agent(model, store, saver,
                                    local_state_controller=controller,
                                    local_state_read_policy=policy,
                                    source_view_max_bytes=(16384 if policy == "all_sources"
                                                           else None))
                invoke_public_message(agent, model, FoundationScope(
                    "run", "local_all_sources", "alice", policy), "Continue the matter")
    assert len(host_wires) == len(control_payloads) == 2
    off, on = (wire["messages"][0]["content"] for wire in host_wires)
    assert SOURCE_VIEW_HEADER not in off
    assert on.startswith(off + "\n" + SOURCE_VIEW_HEADER + "\n")
    assert [wire["messages"][1]["content"] for wire in host_wires] == [
        "Continue the matter", "Continue the matter"]
    source_rows = [json.loads(line) for line in on.split(SOURCE_VIEW_HEADER + "\n", 1)[1]
                   .splitlines()]
    assert [row["id"] for row in source_rows] == ["source-user", "source-tool"]
    assert source_rows[0]["content"].encode("utf-8") == user_content.encode("utf-8")
    assert source_rows[1]["content"].encode("utf-8") == receipt_content.encode("utf-8")
    assert source_rows[1]["actor"] == "reserve_and_label"
    assert source_rows[1]["tool_call_id"] == "call-1"
    assert all(row["id"] not in on for row in bank.states(scope))
    assert all({"id", "revision"} <= set(state)
               for payload in control_payloads for state in payload["states"])
    delivered = [view for view in views if view["event"] == "lsa_view"]
    assert [view["read_policy"] for view in delivered] == ["all", "all_sources"]
    assert len(delivered[1]["source_requested_ids"]) == 2
    assert set(delivered[1]["source_requested_ids"]) == {"source-user", "source-tool"}
    assert delivered[1]["source_delivered_ids"] == ["source-user", "source-tool"]
    assert delivered[1]["source_view_bytes"] == len(on[len(off):].encode("utf-8"))
    assert delivered[1]["source_omitted"] == []
    assert delivered[0]["delivered_state_ids"] == delivered[1]["delivered_state_ids"]
    assert all("source_requested_ids" not in view for view in delivered[:1])
    assert all(row["id"] in delivered[1]["delivered_state_ids"] for row in receipts)


def test_global_and_local_share_source_wire_without_extra_control_calls(
    tmp_path: Path,
) -> None:
    wires: dict[str, dict[str, Any]] = {}
    host_counts: dict[str, int] = {}
    views: dict[str, dict[str, Any]] = {}
    controls: dict[str, list[dict[str, Any]]] = {}
    source_content = '{"ok":false,"item_key":"exact-key","quantity":2}'
    for arm in ("global_note_sources", "local_all_sources"):
        store = InMemoryStore()
        bank = LocalStateBank(store, max_states=1 if arm == "global_note_sources" else 4,
                              max_state_content_chars=(16000 if arm ==
                                                       "global_note_sources" else 4000),
                              max_total_content_chars=16000)
        scope = StateScope("run", arm, "alice")
        bank.record_event(scope, {"id": "receipt", "kind": "tool", "actor": "inventory",
                                  "tool_call_id": "call-1", "content": source_content})
        edits = [{"id": None, "title": "Working note", "content": "one matter",
                  "evidence": ["receipt"]}]
        if arm == "local_all_sources":
            edits.append({"id": None, "title": "Other matter", "content": "another matter",
                          "evidence": ["receipt"]})
        receipts, invalid = bank.apply(scope, edits, {"receipt"})
        assert not invalid and len(receipts) == len(edits)
        controls[arm] = []
        host_counts[arm] = 0
        emitted: list[dict[str, Any]] = []

        class NoEditControl:
            def __init__(self, arm_id: str) -> None:
                self.arm_id = arm_id

            def chat(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
                controls[self.arm_id].append({
                    "payload": json.loads(messages[1]["content"]),
                    "schema": kwargs["response_format"]})
                return {"choices": [{"finish_reason": "stop", "message": {
                    "content": '{"edits":[],"focus":[]}'}}]}

        def respond(request: httpx.Request, arm_id: str = arm) -> httpx.Response:
            host_counts[arm_id] += 1
            wires[arm_id] = json.loads(request.read())
            return _response({"answer": "done"}, 1)

        controller = LocalStateController(
            bank, NoEditControl(arm), emit=emitted.append,  # type: ignore[arg-type]
            representation=("global_note" if arm == "global_note_sources" else "local"))
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                        transport=httpx.MockTransport(respond)) as host:
            with SqliteSaver.from_conn_string(str(tmp_path / f"{arm}.sqlite")) as saver:
                model = VLLMChatModel(client=host)
                agent = build_agent(model, store, saver,
                                    local_state_controller=controller,
                                    local_state_read_policy="all_sources",
                                    source_view_max_bytes=16384)
                invoke_public_message(agent, model, FoundationScope(
                    "run", arm, "alice", "session"), "Continue both matters")
        views[arm] = next(row for row in emitted if row["event"] == "lsa_view")

    assert all(len(controls[arm]) == 1 for arm in controls)
    assert list(host_counts.values()) == [1, 1]
    assert all(controls[arm][0]["payload"]["new_observations"][0]["content"] ==
               "Continue both matters" for arm in controls)
    assert all(view["source_requested_ids"] == view["source_delivered_ids"] ==
               ["receipt"] for view in views.values())
    assert [len(views[arm]["delivered_state_ids"]) for arm in controls] == [1, 2]
    assert all(SOURCE_VIEW_HEADER in wire["messages"][0]["content"]
               and json.loads(wire["messages"][0]["content"].split(
                   SOURCE_VIEW_HEADER + "\n", 1)[1].splitlines()[0])["content"] ==
               source_content for wire in wires.values())
    assert all(wire["messages"][1]["content"] == "Continue both matters"
               for wire in wires.values())
    assert wires["global_note_sources"].get("tools") == wires["local_all_sources"].get(
        "tools")
    assert all(state_id not in wires[arm]["messages"][0]["content"]
               for arm, view in views.items() for state_id in view["delivered_state_ids"])


def test_lru_hook_updates_background_and_reads_only_foreground_sources(
    tmp_path: Path,
) -> None:
    bank = LocalStateBank(InMemoryStore(), max_total_content_chars=16000)
    scope = StateScope("run", "local_lru_sources", "alice")
    ids: list[str] = []
    for label in ("background", "foreground"):
        source_id = "source-" + label
        bank.record_event(scope, {"id": source_id, "kind": "tool", "actor": "tool",
                                  "tool_call_id": source_id,
                                  "content": "receipt-" + label})
        receipts, invalid = bank.apply(scope, [{"id": None, "title": label,
                                                "content": "old-" + label,
                                                "evidence": [source_id]}], {source_id})
        assert not invalid
        ids.append(receipts[0]["id"])
    background, foreground = ids
    replies = LruReplies({
        "update_selector": [{"update_ids": [background]}],
        "maintenance": [{"edits": [{"id": background,
                                      "content": "new-background"}]}],
        "read_selector": [{"read_ids": [foreground]}]})
    emitted: list[dict[str, Any]] = []
    controller = LocalStateController(
        bank, replies, emit=emitted.append,  # type: ignore[arg-type]
        capacity_path=tmp_path / "capacity.json", local_granularity=True,
        update_policy="lru")
    original = HumanMessage(content="Update background; answer from foreground", id="live")
    hook = make_pre_model_hook(controller, "Original system", "focus_sources", 16384)
    output = hook({"messages": [original]}, {"configurable": {
        "foundation_run_id": "run", "arm_id": "local_lru_sources", "user_id": "alice",
        "thread_id": "thread"}})
    view = next(row for row in emitted if row["event"] == "lsa_view")
    assert [call["stage"] for call in replies.calls] == [
        "update_selector", "maintenance", "read_selector"]
    assert [call["context_stage"] for call in replies.calls] == [
        "update_selector", "maintenance", "read_selector"]
    assert replies.calls[0]["payload"]["current_task"] == (
        "Update background; answer from foreground")
    assert set(replies.calls[1]["payload"]) == {
        "new_observations", "states", "source_ids_available"}
    assert replies.calls[2]["payload"]["current_task"] == (
        "Update background; answer from foreground")
    assert "current_task" not in replies.calls[1]["prompt"]
    validate({"update_ids": [background]},
             replies.calls[0]["schema"])
    validate({"edits": [{"id": background, "content": "new-background"}]},
             replies.calls[1]["schema"])
    validate({"read_ids": [foreground]}, replies.calls[2]["schema"])
    assert all("content" not in row for row in replies.calls[0]["payload"]["directory"])
    assert [row["id"] for row in replies.calls[1]["payload"]["states"]] == [background]
    assert "dependency_source_ids" not in replies.calls[1]["payload"]["states"][0]
    assert replies.calls[2]["payload"]["directory"] != []
    assert view["controller_focus"] == view["delivered_state_ids"] == [foreground]
    assert view["source_requested_ids"] == view["source_delivered_ids"] == [
        "source-foreground"]
    wire = output["llm_input_messages"]
    assert wire[1] is original and wire[1].id == "live"
    assert "receipt-foreground" in wire[0].content
    assert "receipt-background" not in wire[0].content
    assert bank.states(scope)[0 if background < foreground else 1]["content"] == (
        "new-background")
    assert json.loads((tmp_path / "capacity.json").read_text()) == {"thread:0": 3}
    assert {row["stage"] for row in emitted if row["event"] == "lsa_lru_call"} == {
        "update_selector", "maintenance", "read_selector"}


def test_lr_hook_reads_only_selected_sources_after_full_bank_maintenance() -> None:
    bank = LocalStateBank(InMemoryStore(), max_total_content_chars=16000)
    scope = StateScope("run", "local_lr_sources", "alice")
    state_ids: dict[str, str] = {}
    for label in ("background", "foreground"):
        source_id = "source-" + label
        bank.record_event(scope, {"id": source_id, "kind": "tool", "actor": "tool",
                                  "tool_call_id": source_id,
                                  "content": "receipt-" + label})
        created, invalid = bank.apply(scope, [{"id": None, "title": label,
                                               "content": "state-" + label,
                                               "evidence": [source_id]}], {source_id})
        assert not invalid
        state_ids[label] = created[0]["id"]
    replies = LruReplies({"maintenance": [{"edits": []}],
                          "read_selector": [{"read_ids": [state_ids["foreground"]]}]})
    emitted: list[dict[str, Any]] = []
    controller = LocalStateController(
        bank, replies, emit=emitted.append,  # type: ignore[arg-type]
        local_granularity=True, update_policy="lr", maintenance_only=True)
    original = HumanMessage(id="live", content="Read the foreground matter")
    hook = make_pre_model_hook(controller, "Original system", "focus_sources", 16384)
    output = hook({"messages": [original]}, {"configurable": {
        "foundation_run_id": "run", "arm_id": "local_lr_sources", "user_id": "alice",
        "thread_id": "thread"}})
    assert [call["stage"] for call in replies.calls] == ["maintenance", "read_selector"]
    assert {row["id"] for row in replies.calls[0]["payload"]["states"]} == set(
        state_ids.values())
    view = next(row for row in emitted if row["event"] == "lsa_view")
    assert view["controller_focus"] == view["delivered_state_ids"] == [
        state_ids["foreground"]]
    assert view["source_delivered_ids"] == ["source-foreground"]
    wire = output["llm_input_messages"]
    assert wire[1] is original
    assert "receipt-foreground" in wire[0].content
    assert "receipt-background" not in wire[0].content


@pytest.mark.parametrize("arm", ["global_note_sources", "local_all_sources"])
def test_all_read_maintenance_uses_only_pending_events_and_preserves_identity(
    arm: str,
) -> None:
    bank = LocalStateBank(InMemoryStore(), max_states=(
        1 if arm == "global_note_sources" else 32),
        max_state_content_chars=(16000 if arm == "global_note_sources" else 4000),
        max_total_content_chars=16000)
    scope = StateScope("run", arm, "alice")
    user_text = "Increase the three recorded values by one"
    replies = LruReplies({"maintenance": [
        lambda payload: {"edits": [{"id": None, "title": "continuing matter",
                                   "content": "recorded values",
                                   "evidence": [payload["new_observations"][0]["id"]]}]},
        lambda payload: {"edits": [{"id": bank.states(scope)[0]["id"],
                                   "content": "partial receipt observed",
                                   "evidence": [payload["new_observations"][0]["id"]]}]},
        {"edits": []}]})
    controller = LocalStateController(
        bank, replies,  # type: ignore[arg-type]
        representation=("global_note" if arm == "global_note_sources" else "local"),
        local_granularity=arm == "local_all_sources", maintenance_only=True)
    hook = make_pre_model_hook(controller, "Original system", "all_sources", 16384)
    cfg = {"configurable": {"foundation_run_id": "run", "arm_id": arm,
                            "user_id": "alice", "thread_id": "thread"}}
    user_one = HumanMessage(id="u1", content=user_text)
    first = hook({"messages": [user_one]}, cfg)
    assert first["llm_input_messages"][1] is user_one
    assert bank.states(scope)[0]["revision"] == 1
    ai = AIMessage(content="", tool_calls=[{"name": "manage_memory",
                                            "args": {}, "id": "call-1"}])
    receipt = ToolMessage(id="t1", name="manage_memory", tool_call_id="call-1",
                          content='{"ok":false,"partial":true}')
    second = hook({"messages": [user_one, ai, receipt]}, cfg)
    assert second["llm_input_messages"][3] is receipt
    assert bank.states(scope)[0]["content"] == "partial receipt observed"
    assert bank.states(scope)[0]["revision"] == 2
    user_two = HumanMessage(id="u2", content=user_text)
    hook({"messages": [user_one, ai, receipt, user_two]}, cfg)
    assert [call["stage"] for call in replies.calls] == ["maintenance"] * 3
    assert all(set(call["payload"]) == {
        "new_observations", "states", "source_ids_available"}
               and "current_task" not in call["prompt"]
               and "focus" not in call["prompt"].lower()
               and set(call["schema"]["required"]) == {"edits"}
               for call in replies.calls)
    assert [row["id"] for row in replies.calls[1]["payload"]["new_observations"]] == [
        next(row["id"] for row in bank.events(scope) if row["kind"] == "tool")]
    assert replies.calls[1]["payload"]["new_observations"][0]["content"] == (
        '{"ok":false,"partial":true}')
    assert replies.calls[1]["payload"]["new_observations"][0]["tool_call_id"] == "call-1"
    assert [row["id"] for row in bank.events(scope) if row["kind"] == "user"] == [
        "message:u1", "message:u2"]
    assert [row["id"] for row in replies.calls[2]["payload"]["new_observations"]] == [
        "message:u2"]
    assert len(bank.states(scope)) == 1 and bank.pending(scope) == []
    if arm == "global_note_sources":
        with pytest.raises(ValidationError):
            validate({"edits": [{"id": None, "title": "second note",
                                  "content": "wrong"}]}, replies.calls[1]["schema"])


def test_lru_shared_update_new_read_and_empty_update() -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "two matters"})
    created, invalid = bank.apply(scope, [
        {"id": None, "title": "first", "content": "old first"},
        {"id": None, "title": "second", "content": "old second"}], {"seed"})
    assert not invalid
    first, second = (row["id"] for row in created)
    bank.record_event(scope, {"id": "shared", "kind": "user", "content": "shared change"})
    replies = LruReplies({
        "update_selector": [{"update_ids": [first, second]},
                            {"update_ids": []}],
        "maintenance": [{"edits": [
            {"id": first, "content": "revised first"},
            {"id": second, "content": "revised second"},
            {"id": None, "title": "third", "content": "new matter"}]},
            {"edits": []}],
        "read_selector": [lambda payload: {"read_ids": [next(
            row["id"] for row in payload["directory"]
            if row["id"] not in {first, second})]}, {"read_ids": [first]}]})
    controller = LocalStateController(bank, replies,  # type: ignore[arg-type]
                                      update_policy="lru", local_granularity=True)
    result = controller.prepare(scope, "shared", "read new matter")
    assert not result["degraded"] and len(result["receipts"]) == 3
    assert result["focus"] == [result["receipts"][2]["id"]]
    assert {row["content"] for row in bank.states(scope)} == {
        "revised first", "revised second", "new matter"}
    assert bank.pending(scope) == []
    bank.record_event(scope, {"id": "irrelevant", "kind": "user", "content": "no change"})
    before = {row["id"]: row["revision"] for row in bank.states(scope)}
    no_op = controller.prepare(scope, "irrelevant", "read first")
    assert not no_op["degraded"] and no_op["receipts"] == []
    assert no_op["focus"] == [first] and bank.pending(scope) == []
    assert {row["id"]: row["revision"] for row in bank.states(scope)} == before
    assert [call["stage"] for call in replies.calls] == [
        "update_selector", "maintenance", "read_selector",
        "update_selector", "maintenance", "read_selector"]


def test_lr_matches_l_maintenance_and_reads_new_state_without_u() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store, max_total_content_chars=16000)
    l_scope = StateScope("run", "local_all_sources", "alice")
    lr_scope = StateScope("run", "local_lr_sources", "alice")
    bank.record_event(l_scope, {"id": "seed", "kind": "user", "content": "first matter"})
    created, invalid = bank.apply(l_scope, [{"id": None, "title": "first",
                                            "content": "old first"}], {"seed"})
    assert not invalid
    first_id = created[0]["id"]
    for state in bank.states(l_scope):
        store.put(lr_scope.namespace("states"), state["id"], state, index=False)
    for event in bank.events(l_scope):
        store.put(lr_scope.namespace("events"), event["id"], event, index=False)
    for scope in (l_scope, lr_scope):
        bank.record_event(scope, {"id": "change", "kind": "user",
                                  "content": "revise first; add second"})
    edits = [{"id": first_id, "content": "revised first"},
             {"id": None, "title": "second", "content": "new second"}]
    l_replies = LruReplies({"maintenance": [{"edits": edits}]})
    lr_replies = LruReplies({"maintenance": [{"edits": edits}],
                             "read_selector": [lambda payload: {"read_ids": [next(
                                 row["id"] for row in payload["directory"]
                                 if row["id"] != first_id)]}]})
    local_controller = LocalStateController(bank, l_replies,  # type: ignore[arg-type]
                                             local_granularity=True, maintenance_only=True)
    emitted: list[dict[str, Any]] = []
    lr = LocalStateController(bank, lr_replies, emit=emitted.append,  # type: ignore[arg-type]
                              local_granularity=True, update_policy="lr",
                              maintenance_only=True)
    l_result = local_controller.prepare(l_scope, "change", "read second")
    lr_result = lr.prepare(lr_scope, "change", "read second")
    assert not l_result["degraded"] and not lr_result["degraded"]
    assert l_replies.calls == lr_replies.calls[:1]
    assert [call["stage"] for call in lr_replies.calls] == [
        "maintenance", "read_selector"]
    assert [row["id"] for row in lr_replies.calls[0]["payload"]["states"]] == [first_id]
    assert lr_result["focus"] == [lr_result["receipts"][1]["id"]]
    assert lr_replies.calls[1]["payload"]["current_task"] == "read second"
    assert bank.pending(lr_scope) == []
    assert next(row for row in emitted if row["event"] == "lsa_lr_selection")[
        "selector_skipped_reason"] == "full_bank_policy"
    assert {row["stage"] for row in emitted if row["event"] == "lsa_control_stage_call"} == {
        "maintenance", "read_selector"}


def test_lr_and_lru_use_identical_independent_read_contract() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    lr_scope = StateScope("run", "local_lr_sources", "alice")
    lru_scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(lr_scope, {"id": "seed", "kind": "user", "content": "matter"})
    created, invalid = bank.apply(lr_scope, [{"id": None, "title": "matter",
                                              "content": "known"}], {"seed"})
    assert not invalid
    state_id = created[0]["id"]
    for state in bank.states(lr_scope):
        store.put(lru_scope.namespace("states"), state["id"], state, index=False)
    for event in bank.events(lr_scope):
        store.put(lru_scope.namespace("events"), event["id"], event, index=False)
    lr_replies = LruReplies({"read_selector": [{"read_ids": [state_id]}]})
    lru_replies = LruReplies({"read_selector": [{"read_ids": [state_id]}]})
    lr = LocalStateController(bank, lr_replies,  # type: ignore[arg-type]
                              update_policy="lr", maintenance_only=True)
    lru = LocalStateController(bank, lru_replies,  # type: ignore[arg-type]
                               update_policy="lru", maintenance_only=True)
    assert lr.prepare(lr_scope, "query", "read matter")["focus"] == [state_id]
    assert lru.prepare(lru_scope, "query", "read matter")["focus"] == [state_id]
    assert lr_replies.calls == lru_replies.calls
    assert [call["stage"] for call in lr_replies.calls] == ["read_selector"]


def test_lr_read_failure_keeps_committed_update_and_maintenance_failure_pending() -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lr_sources", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "matter"})
    created, invalid = bank.apply(scope, [{"id": None, "title": "matter",
                                           "content": "old"}], {"seed"})
    assert not invalid
    state_id = created[0]["id"]
    bank.record_event(scope, {"id": "change", "kind": "user", "content": "new"})
    replies = LruReplies({
        "maintenance": [httpx.ReadTimeout("mock"),
                        {"edits": [{"id": state_id, "content": "new"}]}],
        "read_selector": [httpx.ReadTimeout("mock"), {"read_ids": [state_id]}]})
    controller = LocalStateController(bank, replies,  # type: ignore[arg-type]
                                      update_policy="lr", maintenance_only=True)
    first = controller.prepare(scope, "change", "read matter")
    assert first["degraded"] and first["reason"] == "ReadTimeout"
    assert [row["id"] for row in bank.pending(scope)] == ["change"]
    assert bank.states(scope)[0]["content"] == "old"
    second = controller.prepare(scope, "change", "read matter")
    assert second["degraded"] and second["reason"] == "ReadTimeout"
    assert second["receipts"][0]["status"] == "updated"
    assert bank.pending(scope) == [] and bank.states(scope)[0]["content"] == "new"
    assert bank.focus(scope, "change") is None
    recovered = controller.prepare(scope, "change", "read matter")
    assert recovered["focus"] == [state_id] and not recovered["degraded"]
    assert [call["stage"] for call in replies.calls] == [
        "maintenance", "maintenance", "read_selector", "read_selector"]


def test_lru_first_observation_and_empty_u_each_reach_shared_maintainer() -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(scope, {"id": "first", "kind": "user", "content": "first matter"})
    first_id = ""
    replies = LruReplies({
        "update_selector": [{"update_ids": []}],
        "maintenance": [
            {"edits": [{"id": None, "title": "first", "content": "first fact"}]},
            {"edits": [{"id": None, "title": "second", "content": "second fact"}]}],
        "read_selector": [
            lambda payload: {"read_ids": [payload["directory"][0]["id"]]},
            lambda payload: {"read_ids": [next(
                row["id"] for row in payload["directory"] if row["id"] != first_id)]}]})
    controller = LocalStateController(bank, replies,  # type: ignore[arg-type]
                                      update_policy="lru")
    first = controller.prepare(scope, "first", "first matter")
    assert first["receipts"][0]["status"] == "created"
    first_id = first["receipts"][0]["id"]
    assert [call["stage"] for call in replies.calls] == ["maintenance", "read_selector"]
    assert [row["id"] for row in bank.pending(scope)] == []
    bank.record_event(scope, {"id": "second", "kind": "user", "content": "second matter"})
    second = controller.prepare(scope, "second", "second matter")
    assert second["receipts"][0]["status"] == "created"
    assert second["focus"] == [second["receipts"][0]["id"]]
    assert [call["stage"] for call in replies.calls] == [
        "maintenance", "read_selector", "update_selector", "maintenance",
        "read_selector"]
    assert replies.calls[2]["payload"]["directory"] == [{
        "id": first["receipts"][0]["id"], "title": "first", "needs": [],
        "revision": 1}]
    assert replies.calls[3]["payload"]["states"] == []
    assert {row["content"] for row in bank.states(scope)} == {
        "first fact", "second fact"}
    assert bank.pending(scope) == []


@pytest.mark.parametrize("failed_stage", ["update_selector", "maintenance",
                                           "read_selector", "unauthorized_update"])
def test_lru_control_failures_keep_pending_or_committed_state(
    failed_stage: str, tmp_path: Path,
) -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "matter"})
    prior, invalid = bank.apply(scope, [{"id": None, "title": "matter",
                                         "content": "old"}], {"seed"})
    assert not invalid
    state_id = prior[0]["id"]
    bank.record_event(scope, {"id": "change", "kind": "user", "content": "new"})
    failure = httpx.ReadTimeout("mock")
    answers: dict[str, list[Any]] = {
        "update_selector": [{"update_ids": [state_id]}],
        "maintenance": [{"edits": [{"id": state_id, "content": "new"}]}],
        "read_selector": [{"read_ids": [state_id]}]}
    if failed_stage == "unauthorized_update":
        answers["update_selector"] = [{"update_ids": []}]
        answers["maintenance"] = [{"edits": [{"id": state_id, "content": "new"}]}]
    else:
        answers[failed_stage] = [failure]
    replies = LruReplies(answers)
    controller = LocalStateController(
        bank, replies, capacity_path=tmp_path / "capacity.json",  # type: ignore[arg-type]
        update_policy="lru")
    result = controller.prepare(scope, "change", "question", message_key="one:0")
    assert result["degraded"] and result["focus"] == []
    if failed_stage == "read_selector":
        assert bank.pending(scope) == []
        assert bank.states(scope)[0]["content"] == "new"
        assert bank.focus(scope, "change") is None
        replies.answers["read_selector"] = [{"read_ids": [state_id]}]
        retried = controller.prepare(scope, "change", "question", message_key="one:0")
        assert retried["focus"] == [state_id]
        assert [call["stage"] for call in replies.calls][-1] == "read_selector"
    else:
        assert [row["id"] for row in bank.pending(scope)] == ["change"]
        assert bank.states(scope)[0]["content"] == "old"


def test_lru_empty_bank_skips_u_and_capacity_stops_read_without_rollback(
    tmp_path: Path,
) -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(scope, {"id": "change", "kind": "user", "content": "new"})
    replies = LruReplies({"update_selector": [],
                          "maintenance": [{"edits": [{"id": None, "title": "matter",
                                                       "content": "new"}]}],
                          "read_selector": []})
    controller = LocalStateController(
        bank, replies, capacity_path=tmp_path / "capacity.json",  # type: ignore[arg-type]
        max_calls_per_message=1, update_policy="lru")
    result = controller.prepare(scope, "change", "question", message_key="one:0")
    assert result["degraded"] and len(bank.states(scope)) == 1
    assert result["reason"] == "LSA_CONTROL_CAPACITY"
    assert bank.pending(scope) == []
    assert [call["stage"] for call in replies.calls] == ["maintenance"]
    assert json.loads((tmp_path / "capacity.json").read_text()) == {"one:0": 1}


def test_lru_mixed_valid_and_outside_candidate_edits_commit_independently() -> None:
    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_lru_sources", "alice")
    bank.record_event(scope, {"id": "seed", "kind": "user", "content": "two matters"})
    created, invalid = bank.apply(scope, [
        {"id": None, "title": "first", "content": "old first"},
        {"id": None, "title": "second", "content": "old second"}], {"seed"})
    assert not invalid
    first, second = (row["id"] for row in created)
    bank.record_event(scope, {"id": "change", "kind": "user", "content": "change"})
    replies = LruReplies({
        "update_selector": [{"update_ids": [first]}],
        "maintenance": [{"edits": [
            {"id": first, "content": "new first"},
            {"id": second, "content": "unauthorized second"},
            {"id": None, "title": "unauthorized third", "content": "new"}]}],
        "read_selector": []})
    emitted: list[dict[str, Any]] = []
    controller = LocalStateController(
        bank, replies, emit=emitted.append,  # type: ignore[arg-type]
        update_policy="lru")
    result = controller.prepare(scope, "change", "question")
    assert result["degraded"] and result["reason"] == "LSA_MAINTENANCE_INVALID"
    assert [row["status"] for row in result["receipts"]] == [
        "updated", "skipped_invalid_edit", "created"]
    assert result["receipts"][1]["reason"] == "outside_update_candidates"
    by_id = {row["id"]: row for row in bank.states(scope)}
    assert by_id[first]["content"] == "new first"
    assert by_id[second]["content"] == "old second"
    assert len(by_id) == 3
    assert [row["id"] for row in bank.pending(scope)] == ["change"]
    assert [row["stage"] for row in replies.calls] == ["update_selector", "maintenance"]
    terminal = next(row for row in emitted if row["event"] == "lsa_lru_result")
    assert terminal["update_ids"] == [first] and terminal["edits"] == result["receipts"]


def test_local_granularity_is_opt_in_and_global_prompt_unchanged() -> None:
    prompts: list[str] = []

    class PromptControl:
        def chat(self, messages: Any, **_kwargs: Any) -> dict[str, Any]:
            prompts.append(messages[0]["content"])
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"edits":[],"focus":[]}'}}]}

    bank = LocalStateBank(InMemoryStore())
    for index, (representation, granularity) in enumerate((
        ("local", False), ("local", True), ("global_note", True)
    )):
        scope = StateScope("run", "arm", str(index))
        bank.record_event(scope, {"id": "event", "kind": "user", "content": "matter"})
        controller = LocalStateController(
            bank, PromptControl(),  # type: ignore[arg-type]
            representation=representation, local_granularity=granularity)
        controller.prepare(scope, "event", "matter")
    phrase = "can be updated and resumed independently"
    assert phrase not in prompts[0]
    assert phrase in prompts[1]
    assert phrase not in prompts[2]
    assert "one global working note" in prompts[2]


def test_source_resolution_scope_deletion_restart_empty_refs_and_whole_event_budget() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    alice = StateScope("run", "local_all_sources", "alice")
    bob = StateScope("run", "local_all_sources", "bob")
    first = {"id": "z-first", "kind": "user", "actor": "alice",
             "tool_call_id": None, "content": "É" * 12}
    second = {"id": "a-second", "kind": "tool", "actor": "tool",
              "tool_call_id": "call-2", "content": '{"item_key":"exact"}'}
    bank.record_event(alice, first)
    bank.record_event(alice, second)
    bank.record_event(bob, {"id": "bob-only", "kind": "user", "actor": "bob",
                            "tool_call_id": None, "content": "private bob"})
    first_line = json.dumps(first, ensure_ascii=False)
    limit = len(("\n" + SOURCE_VIEW_HEADER + "\n" + first_line).encode("utf-8"))
    state = {"id": "state", "evidence_refs": ["a-second", "bob-only", "z-first",
                                              "missing", ""]}
    gets_before = bank.store_stats()["get"]["calls"]
    puts_before = bank.store_stats()["put"]["calls"]
    lines, trace = _source_view(bank, alice, [state], limit)
    assert lines == [SOURCE_VIEW_HEADER, first_line]
    assert trace["source_view_bytes"] == limit
    assert trace["source_delivered_ids"] == ["z-first"]
    assert trace["source_omitted"] == [{"id": "a-second", "bytes": len((
        "\n" + json.dumps(second, ensure_ascii=False)).encode("utf-8"))}]
    assert trace["source_missing_ids"] == ["bob-only", "missing"]
    assert trace["source_invalid_refs"] == [{"state_id": "state", "reference": "''"}]
    assert bank.store_stats()["get"]["calls"] - gets_before == 8
    assert bank.store_stats()["put"]["calls"] == puts_before
    bank.forget_source(alice, "z-first")
    reopened = LocalStateBank(store)
    lines, trace = _source_view(reopened, alice, [state], 16384)
    assert trace["source_deleted_ids"] == ["z-first"]
    assert trace["source_delivered_ids"] == ["a-second"]
    assert first["content"] not in "\n".join(lines)
    reopened.record_event(alice, first)
    assert reopened.resolve_evidence(alice, ["z-first"]).deleted_source_ids == ["z-first"]
    assert reopened.resolve_evidence(bob, ["a-second"]).missing_source_ids == ["a-second"]
    gets_before = reopened.store_stats()["get"]["calls"]
    lines, trace = _source_view(reopened, alice, [
        {"id": "uncited", "evidence_refs": [], "dependency_source_ids": ["a-second"]}],
        16384)
    assert lines == [] and trace["source_requested_ids"] == []
    assert reopened.store_stats()["get"]["calls"] == gets_before


def test_closed_path_keeps_first_wire(tmp_path: Path) -> None:
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return _response({"answer": "done"}, len(wires))

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond)) as client:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            model = VLLMChatModel(client=client)
            store = InMemoryStore()
            for variant, explicit in enumerate((False, True)):
                agent = (build_agent(model, store, saver, local_state_controller=None)
                         if explicit else build_agent(model, store, saver))
                invoke_public_message(agent, model, FoundationScope(
                    "run", "b1_control", "alice", f"session-{variant}"), "Hi")
    assert len(wires) == 2 and wires[0] == wires[1]
    assert wires[0]["messages"][0]["content"].endswith(
        "memories with the provided tools.")
    assert "Local State working view" not in json.dumps(wires[0])


def test_new_focus_uses_original_edit_index_after_skip() -> None:
    store = InMemoryStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "local_state", "alice")
    bank.record_event(scope, {"id": "source", "kind": "user", "content": "two matters"})

    class FakeClient:
        def chat(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "edits": [{"id": None, "content": "invalid missing title"},
                          {"id": None, "title": "good", "content": "valid",
                           "evidence": ["source"]}],
                "focus": ["new:0", "new:1"]})}}]}

    controller = LocalStateController(bank, FakeClient())  # type: ignore[arg-type]
    result = controller.prepare(scope, "source", "two matters")
    assert len(result["focus"]) == 1
    assert result["focus"][0] == bank.states(scope)[0]["id"]
    assert result["degraded"] is True
    assert [row["id"] for row in bank.pending(scope)] == ["source"]


def test_control_schema_rejects_r1_missing_title_and_factual_focus() -> None:
    schema = control_schema([], 32)
    r1_response = {
        "edits": [{"id": None,
                   "content": ("The Workshop handout packs matter involves 6 packs "
                               "destined for east archive E-2, packed in paper sleeves."),
                   "evidence": ["message:17d8c811-3614-4ab8-bd27-1afd20c6a1b9"]}],
        "focus": ["Workshop handout packs: 6 packs, east archive E-2, paper sleeves."],
    }
    with pytest.raises(ValidationError):
        validate(r1_response, schema)
    missing_title_only = {**r1_response, "focus": ["new:0"]}
    with pytest.raises(ValidationError):
        validate(missing_title_only, schema)
    factual_focus_only = {**r1_response,
                          "edits": [{**r1_response["edits"][0],
                                     "title": "Workshop handout packs"}]}
    with pytest.raises(ValidationError):
        validate(factual_focus_only, schema)
    legal_new = {**factual_focus_only, "focus": ["new:0"]}
    validate(legal_new, schema)

    bank = LocalStateBank(InMemoryStore())
    scope = StateScope("run", "local_state", "alice")
    source_id = r1_response["edits"][0]["evidence"][0]
    bank.record_event(scope, {"id": source_id, "kind": "user", "content": "source"})
    receipts, invalid = bank.apply(scope, legal_new["edits"], {source_id})
    assert not invalid and receipts[0]["status"] == "created"
    state_id = receipts[0]["id"]
    legal_update = {"edits": [{"id": state_id, "content": legal_new["edits"][0]["content"]}],
                    "focus": [state_id]}
    validate(legal_update, control_schema([state_id], 32))
    receipts, invalid = bank.apply(scope, legal_update["edits"], set())
    assert not invalid and receipts[0]["status"] == "noop"
    assert bank.states(scope)[0]["revision"] == 1


@pytest.mark.parametrize("arm", ["local_state", "local_all", "local_all_sources",
                                 "global_note_sources", "local_lr_sources",
                                 "local_lru_sources"])
def test_runtime_explicitly_disables_ser_for_local_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("SER projection must remain off")

    class FakeClient:
        def __init__(self, config: Any, **_kwargs: Any) -> None:
            self.config = config

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    @contextmanager
    def state(*_args: Any, **_kwargs: Any) -> Any:
        yield InMemoryStore(), object()

    monkeypatch.setattr(app_runtime, "projection_for_arm", forbidden)
    monkeypatch.setenv("MILAI_LANGMEM_POSTGRES_DSN", "mock-dsn")
    monkeypatch.setattr(app_runtime, "HostCapacity", lambda _settings: object())
    monkeypatch.setattr(app_runtime, "VLLMClient", FakeClient)
    monkeypatch.setattr(app_runtime, "open_persistent_state", state)
    monkeypatch.setattr(app_runtime, "VLLMChatModel", lambda **kwargs: SimpleNamespace(
        projection=kwargs["projection"]))
    config = {"budget_path": str(tmp_path / "budget.json"),
              "host": {"base_url": "http://mock/v1/", "model": "mock"},
              "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
              "capacity": {}, "embedding_dimension": 3}
    with app_runtime.open_application_runtime(
        config, "run", arm, tmp_path, "mock", enable_projection=False,
    ) as runtime:
        assert runtime.model.projection is None


def test_control_timeout_keeps_event_and_host_answers(tmp_path: Path) -> None:
    class TimedOutControl:
        def chat(self, *_args: Any, **_kwargs: Any) -> Any:
            raise httpx.ReadTimeout("mock timeout")

    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return _response({"answer": "ordinary reply"}, len(wires))

    store = InMemoryStore()
    bank = LocalStateBank(store)
    controller = LocalStateController(bank, TimedOutControl())  # type: ignore[arg-type]
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                    transport=httpx.MockTransport(respond)) as host:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            model = VLLMChatModel(client=host)
            agent = build_agent(model, store, saver, local_state_controller=controller)
            result = invoke_public_message(agent, model, FoundationScope(
                "run", "local_state", "alice", "session"), "Continue this matter")
    assert result[-1].content == "ordinary reply"
    assert len(wires) == 1
    assert "Unprocessed current observations" in wires[0]["messages"][0]["content"]
    assert len(bank.pending(StateScope("run", "local_state", "alice"))) == 1


def test_store_write_failure_remains_infrastructure_and_pending() -> None:
    class FailingStore(InMemoryStore):
        def batch(self, ops: Any) -> Any:
            rows = list(ops)
            if any(isinstance(op, PutOp) and op.namespace[-1] == "states" for op in rows):
                raise OSError("mock store write failure")
            return super().batch(rows)

    store = FailingStore()
    bank = LocalStateBank(store)
    scope = StateScope("run", "local_state", "alice")
    bank.record_event(scope, {"id": "source", "kind": "user", "content": "matter"})

    class FakeControl:
        def chat(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "edits": [{"id": None, "title": "matter", "content": "persist me",
                           "evidence": ["source"]}], "focus": ["new:0"]})}}]}

    controller = LocalStateController(bank, FakeControl())  # type: ignore[arg-type]
    with pytest.raises(OSError, match="mock store write failure"):
        controller.prepare(scope, "source", "matter")
    assert bank.states(scope) == []
    assert [row["id"] for row in bank.pending(scope)] == ["source"]
    assert bank.store_stats()["put"]["failures"] == 1


def test_deleted_checkpoint_source_does_not_reenter_state_or_host_view(
    tmp_path: Path,
) -> None:
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        if wires[-1]["response_format"]["json_schema"]["name"] == "local_state_control_v1":
            return _response({"edits": [], "focus": []}, len(wires))
        return _response({"answer": ("private old source confirmed"
                                     if len(wires) == 2 else "done")}, len(wires))

    store = InMemoryStore()
    scope = StateScope("run", "local_state", "alice")
    bank = LocalStateBank(store)
    config = VLLMConfig(base_url="http://mock/v1/", model="mock")
    with VLLMClient(config, transport=httpx.MockTransport(respond)) as host:
        with VLLMClient(config, transport=httpx.MockTransport(respond)) as control:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                model = VLLMChatModel(client=host)
                controller = LocalStateController(bank, control)
                agent = build_agent(model, store, saver, local_state_controller=controller)
                thread = FoundationScope("run", "local_state", "alice", "same-session")
                invoke_public_message(agent, model, thread, "private old source")
                old_id = bank.events(scope)[0]["id"]
                bank.delete_scope(scope)
                invoke_public_message(agent, model, thread, "new allowed source")
    assert [row["content"] for row in bank.events(scope)] == ["new allowed source"]
    assert bank.is_forgotten(scope, old_id)
    last_host = [wire for wire in wires if wire["response_format"]["json_schema"]["name"]
                 == "langmem_json_action_v1"][-1]
    assert "private old source" not in json.dumps(last_host)
    assert [row["content"] for row in last_host["messages"] if row["role"] == "user"] == [
        "new allowed source"]


@pytest.mark.parametrize("arm,read_policy", [
    ("local_state", "focus"), ("local_all", "all"),
    ("local_all_sources", "all_sources"),
    ("global_note_sources", "all_sources"),
    ("local_lr_sources", "focus_sources"),
    ("local_lru_sources", "focus_sources")])
def test_cli_local_state_path_reuses_application_runner_without_ser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str, read_policy: str,
) -> None:
    from milai_lab.methods.freshness_projection.identity import LAB

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_local_state_attention as entry

    script = tmp_path / "script.json"
    script.write_text(json.dumps({
        "kind": "MILAI_LOCAL_STATE_ATTENTION_SCRIPT", "script_id": "mock",
        "users": ["alice"], "initial_label_available": True,
        "phases": [{"id": 0, "operator_memory": [], "world_events": [],
                    "messages": [{"message_id": "m0", "user_id": "alice",
                                  "session_id": "main", "public_index": 0,
                                  "text": "hello"}]}]}))
    config = tmp_path / "config.json"
    config_value = {
        "host": {"base_url": "http://mock/v1/", "model": "mock"},
        "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
        "capacity": {}, "budget_path": str(tmp_path / "budget.json"),
        "control": {"max_tokens": 100, "max_states": 4, "max_events": 8,
                    "max_pending_batch": 4, "max_calls_per_message": 2,
                    "aggregate_content_chars": 16000,
                    "local_granularity": True}}
    if read_policy in {"all_sources", "focus_sources"}:
        config_value["source_view_max_bytes"] = 16384
    config.write_text(json.dumps(config_value))
    root = tmp_path / "runtime"
    args = SimpleNamespace(config=config, script=script, run="mock-run", arm=arm,
                           repeat=0, runtime_root=root, output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json", phase=0, stage="mock")
    entry.prepare(args)
    called: list[Any] = []

    class FakeClient:
        def __init__(self, config: Any, **kwargs: Any) -> None:
            self.config = config
            self.emit = kwargs.get("emit")
            self.budget = kwargs.get("budget")
            self.capacity = kwargs.get("capacity")

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    host = FakeClient(VLLMConfig(base_url="http://mock/v1/", model="mock"),
                      emit=Trace(root / "trace.jsonl", "mock"))

    @contextmanager
    def runtime(*_args: Any, **kwargs: Any) -> Any:
        called.append(kwargs["enable_projection"])
        yield SimpleNamespace(model=SimpleNamespace(client=host), store=InMemoryStore(),
                              checkpointer=object(), observer=object())

    def phase(*args_: Any, **kwargs: Any) -> dict[str, Any]:
        assert isinstance(args_[-1], LocalStateController)
        called.append(args_[-1].client.config.max_tokens)
        called.append(kwargs["local_state_read_policy"])
        called.append(kwargs["source_view_max_bytes"])
        called.append(args_[-1].representation)
        called.append(args_[-1].update_policy)
        called.append(args_[-1].local_granularity)
        called.append(args_[-1].maintenance_only)
        called.append((args_[-1].bank.max_states,
                       args_[-1].bank.max_state_content_chars,
                       args_[-1].bank.max_total_content_chars))
        args_[-1].bank.record_event(StateScope("mock-run", arm, "alice"), {
            "id": "source", "kind": "user", "content": "hello"})
        return {"status": "TERMINAL"}

    monkeypatch.setattr(entry, "open_application_runtime", runtime)
    monkeypatch.setattr(entry, "VLLMClient", FakeClient)
    monkeypatch.setattr(entry, "run_phase", phase)
    assert entry.run(args)["status"] == "TERMINAL"
    expected_limits = ((1, 16000, 16000) if arm == "global_note_sources" else
                       (4, 4000, 16000) if arm in {
                           "local_all_sources", "local_lr_sources",
                           "local_lru_sources"} else
                       (4, 4000, None))
    assert called == [False, 100, read_policy,
                      16384 if read_policy in {"all_sources", "focus_sources"} else None,
                      "global_note" if arm == "global_note_sources" else "local",
                      "lru" if arm == "local_lru_sources" else
                      "lr" if arm == "local_lr_sources" else "all",
                      arm in {"local_all_sources", "local_lr_sources",
                              "local_lru_sources"},
                      arm in {"global_note_sources", "local_all_sources",
                              "local_lr_sources", "local_lru_sources"},
                      expected_limits]
    manifest = json.loads((root / "run_manifest.json").read_text())
    assert manifest["status"] == "TERMINAL"
    assert manifest["identity"]["rubric_read_by_runner"] is False
    assert manifest["identity"]["read_policy"] == read_policy
    assert manifest["identity"]["representation"] == (
        "global_note" if arm == "global_note_sources" else "local")
    assert manifest["identity"]["local_granularity"] == (
        arm in {"local_all_sources", "local_lr_sources", "local_lru_sources"})
    assert manifest["identity"]["update_policy"] == (
        "lru" if arm == "local_lru_sources" else
        "lr" if arm == "local_lr_sources" else "all")
    assert manifest["identity"]["update_candidate_policy"] == (
        "all_existing_without_selector" if arm == "local_lr_sources" else
        "model_selected_existing" if arm == "local_lru_sources" else None)
    assert manifest["identity"]["read_selection_policy"] == (
        "independent_after_maintenance" if arm in {
            "local_lr_sources", "local_lru_sources"} else None)
    assert manifest["identity"]["creation_policy"] == (
        "shared_maintenance_each_pending_batch"
        if arm in {"local_lr_sources", "local_lru_sources"} else None)
    assert manifest["identity"]["maintenance_input_policy"] == (
        "pending_events_candidates_source_ids" if arm in {
            "global_note_sources", "local_all_sources", "local_lr_sources",
            "local_lru_sources"} else
        "current_task_pending_events_states_source_ids")
    assert manifest["identity"]["maintenance_response_contract"] == (
        "edits_only" if arm in {"global_note_sources", "local_all_sources",
                                "local_lr_sources", "local_lru_sources"} else
        "edits_and_focus")
    assert manifest["identity"]["effective_content_limits"] == dict(zip(
        ("max_states", "max_state_content_chars", "max_total_content_chars"),
        expected_limits, strict=True))
    store_stats = manifest["accounting"]["local_state_store_stats"]
    assert store_stats["put"]["calls"] == 1
    assert store_stats["get"]["calls"] == 2
    assert store_stats["search"]["calls"] == 1
    trace = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    assert [event["event"] for event in trace] == ["lsa_store_stats"]
    assert trace[0]["operations"] == store_stats


def test_missing_aggregate_setting_preserves_existing_local_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.methods.freshness_projection.identity import LAB

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_local_state_attention as entry

    config = {"control": {"max_states": 32}}
    assert entry._content_limits("local_all_sources", config) == {
        "max_states": 32, "max_state_content_chars": 4000,
        "max_total_content_chars": None}
    with pytest.raises(ValueError, match="LSA_GLOBAL_NOTE_CONTENT_LIMIT_MISSING"):
        entry._content_limits("global_note_sources", config)
    assert entry._local_granularity("local_all_sources", config) is False
    with pytest.raises(ValueError, match="LSA_LRU_REQUIRES_LOCAL_GRANULARITY"):
        entry._local_granularity("local_lru_sources", config)
    with pytest.raises(ValueError, match="LSA_LR_REQUIRES_LOCAL_GRANULARITY"):
        entry._local_granularity("local_lr_sources", config)


def test_lru_accounting_preserves_total_role_and_substage_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.methods.freshness_projection.identity import LAB

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_local_state_attention as entry

    events = [
        {"event": "vllm_response", "role": "state_control",
         "control_stage": "update_selector", "usage": {"total_tokens": 11}},
        {"event": "vllm_response", "role": "state_control",
         "control_stage": "maintenance", "usage": {"total_tokens": 17}},
        {"event": "vllm_error", "role": "state_control",
         "control_stage": "read_selector", "usage": None},
        {"event": "vllm_response", "role": "task_host",
         "usage": {"total_tokens": 23}},
    ]
    (tmp_path / "trace.jsonl").write_text("".join(
        json.dumps(row) + "\n" for row in events))
    accounting = entry._accounting(tmp_path, tmp_path / "missing-budget.json")
    assert accounting["by_role"]["state_control"] == {
        "requests": 3, "known_tokens": 28, "unknown_usage": 1, "errors": 1}
    assert accounting["by_control_stage"]["read_selector"] == {
        "requests": 1, "known_tokens": 0, "unknown_usage": 1, "errors": 1}
    assert accounting["by_role"]["task_host"]["known_tokens"] == 23
