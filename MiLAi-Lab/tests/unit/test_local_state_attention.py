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

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.base import PutOp
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope, build_agent, invoke_public_message
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    LocalStateController,
    control_schema,
)
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
    control_wire = wires[0]
    user_event = json.loads(control_wire["messages"][1]["content"])["new_observations"][0]
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
    host_wires = [wire for wire in wires if wire["response_format"]["json_schema"]["name"]
                  == "langmem_json_action_v1"]
    assert len(host_wires) == 2
    assert "Local State working view" in host_wires[0]["messages"][0]["content"]
    assert any(row["role"] == "tool" and "reserved_label_failed" in row["content"]
               for row in host_wires[1]["messages"])


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


def test_runtime_explicitly_disables_ser_for_local_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
        config, "run", "local_state", tmp_path, "mock", enable_projection=False,
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


def test_cli_local_state_path_reuses_application_runner_without_ser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
    config.write_text(json.dumps({
        "host": {"base_url": "http://mock/v1/", "model": "mock"},
        "embedding": {"base_url": "http://mock/v1/", "model": "mock"},
        "capacity": {}, "budget_path": str(tmp_path / "budget.json"),
        "control": {"max_tokens": 100, "max_states": 4, "max_events": 8,
                    "max_pending_batch": 4, "max_calls_per_message": 2}}))
    root = tmp_path / "runtime"
    args = SimpleNamespace(config=config, script=script, run="mock-run", arm="local_state",
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

    def phase(*args_: Any) -> dict[str, Any]:
        assert isinstance(args_[-1], LocalStateController)
        called.append(args_[-1].client.config.max_tokens)
        args_[-1].bank.record_event(StateScope("mock-run", "local_state", "alice"), {
            "id": "source", "kind": "user", "content": "hello"})
        return {"status": "TERMINAL"}

    monkeypatch.setattr(entry, "open_application_runtime", runtime)
    monkeypatch.setattr(entry, "VLLMClient", FakeClient)
    monkeypatch.setattr(entry, "run_phase", phase)
    assert entry.run(args)["status"] == "TERMINAL"
    assert called == [False, 100]
    manifest = json.loads((root / "run_manifest.json").read_text())
    assert manifest["status"] == "TERMINAL"
    assert manifest["identity"]["rubric_read_by_runner"] is False
    store_stats = manifest["accounting"]["local_state_store_stats"]
    assert store_stats["put"]["calls"] == 1
    assert store_stats["get"]["calls"] == 2
    assert store_stats["search"]["calls"] == 1
    trace = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    assert [event["event"] for event in trace] == ["lsa_store_stats"]
    assert trace[0]["operations"] == store_stats
