"""Mock HTTP, scoped records and actual SQLite checks for continuous shared use."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, invoke_public_message
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_prompt
from milai_lab.runners import shared_record_use as runner
from milai_lab.runners.langmem_application_runtime import ApplicationRuntime

LAB = Path(__file__).resolve().parents[2]


def _config(root: Path) -> dict[str, Any]:
    return {"recipe_id": "synthetic-shared-use", "memory_contract": "strict",
            "host": {"base_url": "http://mock/v1/", "model": "mock", "temperature": 0,
                     "max_tokens": 4096, "tool_mode": "json_action", "max_calls": 12,
                     "enable_thinking": False},
            "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
            "control": {"max_tokens": 2048, "max_calls_per_message": 13,
                        "max_states": 32, "max_events": 256, "aggregate_content_chars": 16000},
            "history": {"enabled": True, "page_max_bytes": 16384},
            "source_view_max_bytes": 16384, "capacity": {"enable_thinking": False},
            "budget_path": str(root / "budget.json")}


@contextmanager
def _runtime(config: dict[str, Any], root: Path, store: InMemoryStore,
             requests: list[dict[str, Any]], respond: Any, *, max_calls: int = 12) -> Any:
    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.read())
        requests.append(payload)
        return httpx.Response(200, json={
            "id": f"generation-{len(requests)}", "choices": [{"finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(respond(payload))}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13}})

    budget = RunBudget(RunLimits(1, 2, None, None, None), Path(config["budget_path"]))
    with VLLMClient(VLLMConfig(**config["host"]), transport=httpx.MockTransport(transport),
                    emit=Trace(root / "trace.jsonl", "synthetic"), budget=budget) as client:
        with SqliteSaver.from_conn_string(str(root / "checkpoints.sqlite")) as saver:
            observer = SimpleNamespace(assert_healthy=lambda: None,
                run_tool=lambda request, execute, _wrapper: execute(request))
            yield ApplicationRuntime(VLLMChatModel(
                client=client, capacity_path=root / "message-capacity.json",
                max_calls_per_message=max_calls), store, saver, observer)


def _section(system: str, header: str) -> Any:
    return json.loads(system.split(header + "\n", 1)[1].split("\n", 1)[0])


def _state(key: str, content: str) -> dict[str, Any]:
    return {"id": key, "title": "plan", "content": content, "needs": [],
            "evidence_refs": [], "revision": 2, "archived": False}


def test_actual_wire_has_common_records_sources_history_and_only_body_switch(
    tmp_path: Path,
) -> None:
    wires: list[dict[str, Any]] = []
    for arm in runner.ARMS:
        root = tmp_path / arm
        root.mkdir()
        write_json(root / "run_manifest.json", {"identity": {"run_id": "run", "arm_id": arm}})
        write_json(root / "phase-progress.json", {"messages": {"prior": {
            "message_id": "prior", "user_id": "alice", "session_id": "old",
            "public_index": 0, "visited_ordinal": 0, "status": "COMPLETED"}}})
        store = InMemoryStore()
        scope = StateScope("run", arm, "alice")
        store.put(scope.namespace("states"), "state-a", _state("state-a", "UNIQUE_STATE_BODY"),
                  index=False)
        store.put(("langmem", "run", arm, "alice"), "memory-a", {"content": "ordinary body"})
        store.put(("langmem", "run", arm, "bob"), "secret", {"content": "PRIVATE_OWNER"})
        bank = LocalStateBank(store)
        bank.record_event(scope, {"id": "prior-source", "kind": "user", "actor": "alice",
                                  "tool_call_id": None, "content": "source body"})
        bank.acknowledge_events(scope, {"prior-source"})
        own_wires: list[dict[str, Any]] = []
        with _runtime(_config(root), root, store, own_wires, lambda _wire: {"answer": "done"}
                      ) as runtime:
            factory, completed = runner._adapters(
                runtime, bank, root, "run", arm, _config(root), "application")
            agent = factory(runtime.model, store, runtime.checkpointer, [], user_id="alice")
            agent.update_state(FoundationScope("run", arm, "alice", "application:old").config(),
                {"messages": [HumanMessage(content="prior question", id="prior-user"),
                              AIMessage(content="prior final", id="prior-answer")]},
                as_node="agent")
            current = FoundationScope("run", arm, "alice", "application:new")
            invoke_public_message(agent, runtime.model, current, "current question")
            completed(agent, current, 0, "COMPLETED", [])
        assert len(own_wires) == 1
        wire = own_wires[0]
        assert [row["content"] for row in wire["messages"][1:]] == [
            "prior question", "prior final", "current question"]
        assert "PRIVATE_OWNER" not in json.dumps(wire)
        catalog = _section(wire["messages"][0]["content"],
                          "[Actual scoped source events; pending=true means not yet acknowledged:]")
        assert [row["content"] for row in catalog] == ["source body", "current question"]
        assert catalog[0]["pending"] is False and catalog[1]["pending"] is True
        assert "prior question" not in [row["content"] for row in bank.events(scope)]
        assert bank.pending(scope) == []
        assert wire["messages"][0]["content"].startswith(_action_prompt(runner._catalog([])))
        wires.append(wire)
    body = json.dumps({"title": "plan", "content": "UNIQUE_STATE_BODY", "needs": [],
                       "evidence_refs": []}, ensure_ascii=False) + "\n"
    assert body not in wires[0]["messages"][0]["content"]
    # Ignore only the program-generated current Human source id, which is scope independent.
    systems = [wire["messages"][0]["content"] for wire in wires]
    catalogs = [_section(system,
        "[Actual scoped source events; pending=true means not yet acknowledged:]")
        for system in systems]
    systems[1] = systems[1].replace(catalogs[1][-1]["id"], catalogs[0][-1]["id"])
    assert systems[1].replace(body, "") == systems[0]
    assert wires[0]["response_format"] == wires[1]["response_format"]


def _application_inputs() -> dict[str, Any]:
    texts = [("alice", "form"), ("bob", "other"), ("alice", "delete_and_act"),
             ("alice", "report"), ("bob", "summary")]
    messages = [{"message_id": str(index), "user_id": owner, "session_id": str(index),
                 "public_index": 0, "text": text} for index, (owner, text) in enumerate(texts)]
    return {"kind": "MILAI_SHARED_RECORD_USE_INPUTS", "workload": "application", "script": {
        "users": ["alice", "bob"], "initial_label_available": False, "phases": [
            {"id": index, "operator_memory": [], "world_events": [], "messages": rows}
            for index, rows in enumerate((messages[:3], messages[3:]))]}}


def _args(tmp_path: Path, arm: str, inputs: dict[str, Any]) -> SimpleNamespace:
    config_path, input_path = tmp_path / "config.json", tmp_path / "inputs.json"
    write_json(config_path, _config(tmp_path))
    write_json(input_path, inputs)
    return SimpleNamespace(config=config_path, inputs=input_path, run="run", arm=arm,
                           runtime_root=tmp_path / "runtime", output=tmp_path / "prepared.json",
                           prepared=tmp_path / "prepared.json", phase=0,
                           command="prepare", stage="synthetic")


@pytest.mark.parametrize("arm", ["H_shared", "all_shared"])
def test_live_crud_exact_deletion_owner_partial_and_closed_turn_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str,
) -> None:
    args = _args(tmp_path, arm, _application_inputs())
    store, wires = InMemoryStore(), []

    def respond(wire: dict[str, Any]) -> dict[str, Any]:
        question = next(row["content"] for row in reversed(wire["messages"])
                        if row["role"] == "user")
        if wire["messages"][-1]["role"] == "tool":
            return {"answer": "actual tools completed"}
        if question in {"form", "other"}:
            contents = ["plan", "reminder"] if question == "form" else ["foreign plan"]
            return {"calls": [call for content in contents for call in (
                {"name": "manage_memory", "arguments": {"action": "create", "content": content}},
                {"name": "manage_state", "arguments": {"action": "create", "title": content,
                                                       "content": content}})]}
        if question == "delete_and_act":
            system = wire["messages"][0]["content"]
            states = _section(system, "[Scoped State directory for exact writer targets:]")
            memories = _section(system, "[Actual scoped ordinary memory records (id and value):]")
            state_id = next(row["id"] for row in states if row["title"] == "reminder")
            memory_id = next(row["id"] for row in memories if row["value"]["content"] == "reminder")
            return {"calls": [
                {"name": "manage_memory", "arguments": {"action": "delete", "id": memory_id}},
                {"name": "manage_state", "arguments": {"action": "delete", "id": state_id}},
                {"name": "reserve_and_label", "arguments": {"item_key": "parcel", "quantity": 2,
                      "destination": "shelf", "packing": "case"}}]}
        if question == "report":
            system = wire["messages"][0]["content"]
            states = _section(system, "[Scoped State directory for exact writer targets:]")
            return {"calls": [
                {"name": "read_record", "arguments": {"target_kind": "state",
                                                       "id": states[0]["id"]}},
                {"name": "read_history", "arguments": {"cursor": 0}},
                {"name": "get_reservation", "arguments": {"item_key": "parcel"}}]}
        assert question == "summary"
        return {"answer": "foreign owner's own summary"}

    @contextmanager
    def open_runtime(config: Any, _run: str, _arm: str, root: Path,
                     _stage: str, **kwargs: Any) -> Any:
        assert kwargs == {"enable_projection": False}
        with _runtime(config, root, store, wires, respond) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    receipt = runner.prepare(args, lab_root=LAB)
    assert receipt["public_messages"] == 5
    args.command = "run-phase"
    args.phase = 1
    with pytest.raises(ValueError, match="SHARED_USE_PHASE_OUT_OF_ORDER"):
        runner.run(args, lab_root=LAB)
    args.phase = 0
    first = runner.run(args, lab_root=LAB)
    assert read_json(args.runtime_root / "run_manifest.json")["status"] == "PHASE_COMPLETED"
    assert len(first["world"]["reservations"]) == len(first["world"]["attempts"]) == 1
    reserved_id = first["world"]["reservations"][0]["reservation_id"]
    assert first["world"]["reservations"][0]["label_status"] == "not_created"
    before_reopen = len(wires)
    args.phase = 1
    final = runner.run(args, lab_root=LAB)
    assert final["world"] == first["world"]
    report_wire = wires[before_reopen]
    assert [row["content"] for row in report_wire["messages"] if row["role"] == "user"] == [
        "form", "delete_and_act", "report"]
    assert "other" not in [row["content"] for row in report_wire["messages"]
                           if row["role"] == "user"]
    assert reserved_id in json.dumps(report_wire)
    reservation = json.loads(next(row["content"] for row in wires[before_reopen + 1]["messages"]
                                  if row.get("name") == "get_reservation"))
    assert reservation["reservation_id"] == reserved_id
    bank = LocalStateBank(store)
    alice, bob = StateScope("run", arm, "alice"), StateScope("run", arm, "bob")
    assert [row["content"] for row in bank.states(alice)] == ["plan"]
    assert [row["content"] for row in bank.states(bob)] == ["foreign plan"]
    assert bank.pending(alice) == bank.pending(bob) == []
    assert not bank.has_forgotten_sources(alice)
    assert any(row["content"] == "form" for row in bank.events(alice))
    turns = [read_json(path) for path in (args.runtime_root / "turns").glob("*.json")]
    assert len(turns) == 5 and all(row["status"] == "COMPLETED" for row in turns)
    deleted = next(row for row in turns if row["session_id"] == "2")
    assert [row["value"]["content"] for row in deleted["ordinary_records"]] == ["plan"]
    assert [row["content"] for row in deleted["states"]] == ["plan"]
    assert any(json.loads(row["content"]).get("status") == "reserved_label_failed"
               for row in deleted["tool_receipts"])
    manifest = read_json(args.runtime_root / "run_manifest.json")
    assert manifest["status"] == "TERMINAL"
    assert manifest["accounting"]["by_role"]["task_host"]["requests"] == len(wires)
    assert manifest["accounting"]["by_control_stage"] == {}
    assert manifest["accounting"]["record_observation_costs"]["shared_turn_checkpoint_read"][
        "calls"] == 5
    assert manifest["accounting"]["physical_store_io"] is None
    with pytest.raises(ValueError, match="SHARED_USE_ATTEMPT_ALREADY_STARTED"):
        runner.run(args, lab_root=LAB)
    assert final["world"] == first["world"]


def test_capacity_retains_actual_prefix_side_effect_pending_and_failure_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _application_inputs()
    inputs["script"]["phases"] = [{"id": 0, "operator_memory": [], "world_events": [],
        "messages": [{"message_id": "only", "user_id": "alice", "session_id": "one",
                      "public_index": 0, "text": "one attempt"}]}]
    args = _args(tmp_path, "H_shared", inputs)
    wires: list[dict[str, Any]] = []
    store = InMemoryStore()
    action = {"calls": [{"name": "reserve_and_label", "arguments": {
        "item_key": "parcel", "quantity": 2, "destination": "shelf", "packing": "case"}}]}

    @contextmanager
    def open_runtime(config: Any, _run: str, _arm: str, root: Path,
                     _stage: str, **_kwargs: Any) -> Any:
        with _runtime(config, root, store, wires, lambda _wire: action, max_calls=1) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    runner.prepare(args, lab_root=LAB)
    args.command = "run-phase"
    result = runner.run(args, lab_root=LAB)
    assert result["status"] == "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE" and len(wires) == 1
    assert len(result["world"]["reservations"]) == 1
    scope = StateScope("run", "H_shared", "alice")
    assert len(LocalStateBank(store).pending(scope)) == 2
    turn = read_json(next((args.runtime_root / "turns").glob("*.json")))
    assert turn["acknowledged_event_ids"] == []
    assert json.loads(turn["tool_receipts"][0]["content"])["ok"] is False
    assert read_json(args.runtime_root / "run_manifest.json")["status"] == (
        "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE")


def test_store_failure_is_not_success_or_terminal_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedStore(InMemoryStore):
        def put(self, namespace: Any, key: Any, value: Any, **kwargs: Any) -> Any:
            if namespace[0] == "langmem":
                raise ValueError("STORE_WRITE_FAILED")
            return super().put(namespace, key, value, **kwargs)

    args = _args(tmp_path, "H_shared", _application_inputs())
    store = FailedStore()
    wires: list[dict[str, Any]] = []

    @contextmanager
    def open_runtime(config: Any, _run: str, _arm: str, root: Path,
                     _stage: str, **_kwargs: Any) -> Any:
        with _runtime(config, root, store, wires, lambda _wire: {"calls": [
            {"name": "manage_memory", "arguments": {"action": "create", "content": "body"}}]}
                      ) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    runner.prepare(args, lab_root=LAB)
    args.command = "run-phase"
    with pytest.raises(ValueError, match="STORE_WRITE_FAILED"):
        runner.run(args, lab_root=LAB)
    manifest = read_json(args.runtime_root / "run_manifest.json")
    assert manifest["status"] == "FAILED"
    assert manifest["attempts"]["phase:0"] == {"status": "FAILED", "error_type": "ValueError"}
    assert len(LocalStateBank(store).pending(StateScope("run", "H_shared", "alice"))) == 1
    assert not (args.runtime_root / "turns").exists()


class NativeWorld:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE actions(value TEXT)")

    def snapshot(self) -> dict[str, Any]:
        return {"actions": [row[0] for row in self.conn.execute("SELECT value FROM actions")],
                "PRIVATE_CHECKER_STATE": True}


def test_native_factory_preserves_all_original_messages_tools_world_and_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_messages = [["episode zero"], ["episode one a", "episode one b"],
                     ["episode two"], ["episode three"], ["episode four a", "episode four b"]]
    checks: list[Any] = []
    episodes = [SimpleNamespace(index=index, task=SimpleNamespace(
        task_id=f"task{index}", kind="original", dependent=False, checker="check",
        checker_args={"private_target": "PRIVATE_CHECKER_ARGUMENT"}, user_messages=messages,
        golds=lambda: ["PRIVATE_GOLD"])) for index, messages in enumerate(user_messages)]
    arc = SimpleNamespace(arc_id="synthetic-native", episodes=episodes, make_world=NativeWorld)
    schema = {"type": "function", "function": {"name": "native_action", "description": "native",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}},
                       "required": ["value"], "additionalProperties": False}}}

    def action(world: NativeWorld, value: str) -> str:
        with world.conn:
            world.conn.execute("INSERT INTO actions VALUES (?)", (value,))
        return json.dumps({"actual_value": value})

    def check(snapshot: Any, **kwargs: Any) -> bool:
        checks.append((snapshot, kwargs))
        return bool(snapshot["actions"])

    selection = {"private_artifacts": {"arc_sha256": "synthetic-byte-lock"},
                 "episode_count": 5, "dependent_episode_count": 0}
    loaded = (selection, arc, SimpleNamespace(TOOL_SCHEMAS=[schema],
                                              TOOL_FUNCS={"native_action": action}),
              SimpleNamespace(check=check, memory_utilized=lambda *_args: False),
              SimpleNamespace(SYSTEM_PROMPT="ORIGINAL_RULES {memory_block}"))
    monkeypatch.setattr(runner, "load_frozen_arc", lambda _path: loaded)
    selection_path = tmp_path / "selection.json"
    write_json(selection_path, {})
    args = _args(tmp_path, "H_shared", {"kind": "MILAI_SHARED_RECORD_USE_INPUTS",
        "workload": "merit", "selection_mode": "frozen", "selection_path": str(selection_path)})
    wires: list[dict[str, Any]] = []
    store = InMemoryStore()

    def respond(wire: dict[str, Any]) -> dict[str, Any]:
        current = next(row["content"] for row in reversed(wire["messages"])
                       if row["role"] == "user")
        if current == "episode zero" and wire["messages"][-1]["role"] == "user":
            return {"calls": [{"name": "native_action", "arguments": {"value": "real"}}]}
        return {"answer": "final " + current}

    @contextmanager
    def open_runtime(config: Any, _run: str, _arm: str, root: Path,
                     _stage: str, **_kwargs: Any) -> Any:
        with _runtime(config, root, store, wires, respond) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    prepared = runner.prepare(args, lab_root=LAB)
    assert prepared["public_messages"] == 7
    native_catalog = read_json(args.runtime_root / "run_manifest.json")["identity"]["tool_catalog"]
    assert native_catalog[-1] == schema
    args.command = "run-merit"
    result = runner.run(args, lab_root=LAB)
    assert result["native_denominator"] == 5 and len(checks) == 10
    assert all(kwargs == {"private_target": "PRIVATE_CHECKER_ARGUMENT"} for _, kwargs in checks)
    assert [next(row["content"] for row in reversed(wire["messages"]) if row["role"] == "user")
            for wire in wires if wire["messages"][-1]["role"] == "user"] == [
        text for episode in user_messages for text in episode]
    assert all("ORIGINAL_RULES" in wire["messages"][0]["content"] for wire in wires)
    assert not any(token in json.dumps(wires) for token in (
        "PRIVATE_GOLD", "PRIVATE_CHECKER_ARGUMENT", "PRIVATE_CHECKER_STATE"))
    assert len(read_json(args.runtime_root / "phase-progress.json")["messages"]) == 7
    assert len(list((args.runtime_root / "turns").glob("*.json"))) == 7
    with sqlite3.connect(args.runtime_root / "world.sqlite") as conn:
        assert conn.execute("SELECT value FROM actions").fetchall() == [("real",)]
    assert read_json(args.runtime_root / "run_manifest.json")["status"] == "TERMINAL"


def test_empty_seed_owner_dirty_scope_rejected_before_host_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _args(tmp_path, "H_shared", _application_inputs())
    store = InMemoryStore()
    store.put(("langmem", "run", "H_shared", "bob"), "prior", {"content": "dirty"})
    wires: list[dict[str, Any]] = []

    @contextmanager
    def open_runtime(config: Any, _run: str, _arm: str, root: Path,
                     _stage: str, **_kwargs: Any) -> Any:
        with _runtime(config, root, store, wires, lambda _wire: {"answer": "never"}) as runtime:
            yield runtime

    monkeypatch.setattr(runner, "open_application_runtime", open_runtime)
    runner.prepare(args, lab_root=LAB)
    args.command = "run-phase"
    with pytest.raises(ValueError, match="SHARED_USE_NAMESPACE_DIRTY"):
        runner.run(args, lab_root=LAB)
    assert wires == [] and not (args.runtime_root / "business-world.sqlite").exists()
    assert store.get(("langmem", "run", "H_shared", "bob"), "prior").value == {"content": "dirty"}
