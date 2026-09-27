"""Small zero-model checks for the durable application workload."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

pytest.importorskip("langmem")

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.methods.freshness_projection.identity import LAB
from milai_lab.methods.local_state_attention.controller import CONTROL_STAGE
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners import langmem_application as app
from milai_lab.runners import langmem_application_runtime as app_runtime


def test_durable_partial_business_result_and_user_scope(tmp_path: Path) -> None:
    path = tmp_path / "world.sqlite"
    world = app.ApplicationWorld(path, initial_label_available=False)
    partial = json.loads(world.reserve_and_label(
        "alice", "same-item", 6, "east bay", "foam"))
    assert partial["ok"] is False and partial["status"] == "reserved_label_failed"
    assert partial["label_status"] == "not_created"
    reservation_id = partial["reservation_id"]
    assert json.loads(world.get_reservation("bob", "same-item"))["status"] == "not_found"
    world.close()

    reopened = app.ApplicationWorld(path, initial_label_available=True)
    assert reopened.snapshot()["label_available"] is False
    assert json.loads(reopened.get_reservation("alice", "same-item"))[
        "reservation_id"] == reservation_id
    reopened.set_label_available("restore", True)
    assert json.loads(reopened.complete_label("bob", reservation_id))["status"] == "not_found"
    completed = json.loads(reopened.complete_label("alice", reservation_id))
    assert completed["ok"] is True and completed["status"] == "label_created"
    duplicate = json.loads(reopened.reserve_and_label(
        "alice", "same-item", 6, "east bay", "foam"))
    assert duplicate["status"] == "duplicate_reservation_attempt"
    bob = json.loads(reopened.reserve_and_label(
        "bob", "same-item", 3, "south bay", "cloth"))
    assert bob["ok"] is True and bob["reservation_id"] != reservation_id
    assert len(reopened.snapshot()["reservations"]) == 2
    assert len(reopened.snapshot()["attempts"]) == 4
    reopened.close()


def test_operator_aliases_bind_public_tool_ids_per_user(tmp_path: Path) -> None:
    sidecar = RevisionSidecar(tmp_path / "sidecar.sqlite")
    observer = ProvenanceObserver(sidecar, "run", "b1_control")
    store = ObservedStore(InMemoryStore(), observer)
    runtime = SimpleNamespace(store=store, observer=observer)
    root = tmp_path / "runtime"
    root.mkdir()
    try:
        for user_id, content in (("alice", "Alice first"), ("bob", "Bob first")):
            app._operator_memory_event({
                "event_id": user_id + "-create", "user_id": user_id,
                "action": "create", "alias": "plan", "content": content},
                "run", "b1_control", root, runtime)
        update = {"event_id": "alice-update", "user_id": "alice",
                  "action": "update", "alias": "plan", "content": "Alice second"}
        app._operator_memory_event(update, "run", "b1_control", root, runtime)
        app._operator_memory_event(update, "run", "b1_control", root, runtime)
        app._operator_memory_event({
            "event_id": "alice-old-create", "user_id": "alice", "action": "create",
            "alias": "old", "content": "Obsolete"}, "run", "b1_control", root, runtime)
        app._operator_memory_event({
            "event_id": "alice-old-delete", "user_id": "alice", "action": "delete",
            "alias": "old"}, "run", "b1_control", root, runtime)
        ledger = json.loads((root / "operator-memory.json").read_text())
        alice_id = ledger["aliases"]["alice"]["plan"]["id"]
        bob_id = ledger["aliases"]["bob"]["plan"]["id"]
        assert alice_id != bob_id
        assert store.get(("langmem", "run", "b1_control", "alice"), alice_id).value[
            "content"] == "Alice second"
        assert store.get(("langmem", "run", "b1_control", "bob"), bob_id).value[
            "content"] == "Bob first"
        old_id = ledger["aliases"]["alice"]["old"]["id"]
        assert store.get(("langmem", "run", "b1_control", "alice"), old_id) is None
        assert len(ledger["events"]) == 5
        assert {row["tool_name"] for row in sidecar.rows("tool_calls")} == {
            "operator:manage_memory"}
        ledger["events"]["interrupted"] = {
            "input": {"event_id": "interrupted", "user_id": "alice",
                      "action": "update", "alias": "plan", "content": "Never replay"},
            "status": "pending"}
        (root / "operator-memory.json").write_text(json.dumps(ledger))
        with pytest.raises(ValueError, match="APPLICATION_OPERATOR_OUTCOME_UNKNOWN"):
            app._operator_memory_event(ledger["events"]["interrupted"]["input"],
                                       "run", "b1_control", root, runtime)
    finally:
        sidecar.close()


def test_phase_resume_and_local_capacity_only_skip_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = {"initial_label_available": False, "phases": [
        {"id": 0, "operator_memory": [], "world_events": [], "messages": [
            {"message_id": "a0", "user_id": "alice", "session_id": "main",
             "public_index": 0, "text": "a0"},
            {"message_id": "b0", "user_id": "bob", "session_id": "main",
             "public_index": 0, "text": "b0"}]},
        {"id": 1, "operator_memory": [], "world_events": [], "messages": [
            {"message_id": "a1", "user_id": "alice", "session_id": "main",
             "public_index": 1, "text": "capacity"},
            {"message_id": "a2", "user_id": "alice", "session_id": "main",
             "public_index": 2, "text": "skip"},
            {"message_id": "b1", "user_id": "bob", "session_id": "main",
             "public_index": 1, "text": "b1"}]},
    ]}
    calls: list[tuple[str, str, int]] = []

    def invoke(_agent: Any, _model: Any, scope: Any, text: str,
               index: int, _pending: bool) -> list[AIMessage]:
        calls.append((scope.user_id, text, index))
        if text == "capacity":
            raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")
        return [AIMessage(content="done", id=text)]

    monkeypatch.setattr(app, "build_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(app, "invoke_or_resume_public_message", invoke)
    runtime = SimpleNamespace(model=object(), store=object(), checkpointer=object(),
                              observer=SimpleNamespace(assert_healthy=lambda: None))
    first = app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime)
    assert first["status"] == "TERMINAL"
    assert app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime) == first
    second = app.run_phase(script, tmp_path, "run", "b1_control", 1, runtime)
    assert second["status"] == "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE"
    assert [row["status"] for row in second["messages"]] == [
        "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED",
        "SKIPPED_AFTER_LOCAL_CAPACITY", "COMPLETED"]
    assert calls == [("alice", "a0", 0), ("bob", "b0", 0),
                     ("alice", "capacity", 1), ("bob", "b1", 1)]

    def service_failure(*_args: Any) -> list[AIMessage]:
        raise RuntimeError("SERVICE_UNAVAILABLE")

    monkeypatch.setattr(app, "invoke_or_resume_public_message", service_failure)
    fault_root = tmp_path / "fault"
    fault_root.mkdir()
    with pytest.raises(RuntimeError, match="SERVICE_UNAVAILABLE"):
        app.run_phase({"initial_label_available": False, "phases": [{
            "id": 0, "operator_memory": [], "world_events": [], "messages": [
                {"message_id": "fault", "user_id": "alice", "session_id": "main",
                 "public_index": 0, "text": "fault"},
                {"message_id": "untouched", "user_id": "bob", "session_id": "main",
                 "public_index": 0, "text": "untouched"}]}]},
            fault_root, "run", "b1_control", 0, runtime)
    assert json.loads((fault_root / "phase-progress.json").read_text())[
        "pending_message"] == "fault"


def test_phase_reopens_checkpoint_and_new_session_starts_fresh(tmp_path: Path) -> None:
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "handoff" if index < 2 else "followup",
            "public_index": index if index < 2 else 0,
            "text": f"message {index}"}]}
        for index in range(3)]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"answer": "done"})}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    for phase_id in range(3):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(respond)) as client:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                runtime = SimpleNamespace(
                    model=VLLMChatModel(client=client), store=InMemoryStore(),
                    checkpointer=saver,
                    observer=SimpleNamespace(
                        assert_healthy=lambda: None,
                        run_tool=lambda request, execute, _wrapper: execute(request)))
                app.run_phase(script, tmp_path, "run", "b1_control", phase_id, runtime)
    assert [sum(message["role"] == "user" for message in wire["messages"])
            for wire in wires] == [1, 2, 1]


def test_full_history_replays_interleaved_turns_after_process_reopen(
    tmp_path: Path,
) -> None:
    from milai_lab.harness.contextual_artifacts import write_json

    write_json(tmp_path / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "full_history"}})
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "a" if index != 1 else "b",
            "public_index": 1 if index == 2 else 0,
            "text": f"message {index}"}]}
        for index in range(3)]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "read_history", "arguments": {
            "cursor": 0, "max_bytes": 16384}}]}
                  if len(wires) == 3 else
                  {"answer": f"done {len(wires) - (len(wires) == 4)}"})
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    store = InMemoryStore()
    for phase_id in range(3):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(respond)) as client:
            with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                runtime = SimpleNamespace(
                    model=VLLMChatModel(client=client), store=store, checkpointer=saver,
                    observer=SimpleNamespace(
                        assert_healthy=lambda: None,
                        run_tool=lambda request, execute, _wrapper: execute(request)))
                app.run_phase(script, tmp_path, "run", "full_history", phase_id, runtime,
                              history_mode="full", history_page_max_bytes=16384)
    last = wires[3]["messages"]
    assert [message["content"] for message in last if message["role"] == "user"] == [
        "message 0", "message 1", "message 2"]
    assert [message["content"] for message in last if message["role"] == "assistant"][:2] == [
        "done 1", "done 2"]
    result = next(message for message in last if message["role"] == "tool")
    assert [row["message_id"] for row in json.loads(result["content"])["records"]] == [
        "m0", "m1"]
    assert all("read_history" in wire["messages"][0]["content"] for wire in wires)
    progress = json.loads((tmp_path / "phase-progress.json").read_text())
    assert [row["visited_ordinal"] for row in progress["messages"].values()] == [0, 1, 2]


def test_window_summary_uses_one_accounted_control_call_and_same_history_tool(
    tmp_path: Path,
) -> None:
    from milai_lab.harness.contextual_artifacts import write_json

    write_json(tmp_path / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "window_summary"}})
    script = {"initial_label_available": False, "phases": [
        {"id": index, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": f"m{index}", "user_id": "alice",
            "session_id": "a" if index % 2 == 0 else "b",
            "public_index": index // 2,
            "text": f"message {index}"}]}
        for index in range(4)]}
    host_wires: list[dict[str, Any]] = []
    control_wires: list[dict[str, Any]] = []
    control_events: list[dict[str, Any]] = []

    def host_response(request: httpx.Request) -> httpx.Response:
        host_wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": f"host-{len(host_wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"answer": "done"})}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    def control_response(request: httpx.Request) -> httpx.Response:
        control_wires.append(json.loads(request.read()))
        return httpx.Response(200, json={
            "id": "control-1", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"summary": "Message 0."})}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    store = InMemoryStore()
    for phase_id in range(4):
        with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                   tool_mode="json_action"),
                        transport=httpx.MockTransport(host_response)) as host:
            with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                                       max_tokens=2048),
                            emit=lambda event: control_events.append({
                                **event, "role": "state_control",
                                "control_stage": CONTROL_STAGE.get()}),
                            transport=httpx.MockTransport(control_response)) as control:
                with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
                    runtime = SimpleNamespace(
                        model=VLLMChatModel(client=host), store=store, checkpointer=saver,
                        observer=SimpleNamespace(
                            assert_healthy=lambda: None,
                            run_tool=lambda request, execute, _wrapper: execute(request)))
                    summary = HistorySummaryController(
                        control, window_completed_turns=2,
                        summary_content_max_chars=16000,
                        capacity_path=tmp_path / "control-capacity.json",
                        max_calls_per_message=13)
                    app.run_phase(script, tmp_path, "run", "window_summary", phase_id,
                                  runtime, history_mode="window",
                                  history_page_max_bytes=16384,
                                  history_summary_controller=summary)
    assert len(host_wires) == 4 and len(control_wires) == 1
    assert [item["content"] for item in host_wires[-1]["messages"]
            if item["role"] == "user"] == ["message 1", "message 2", "message 3"]
    assert "Message 0." in host_wires[-1]["messages"][0]["content"]
    assert "message 3" not in json.dumps(control_wires[0], ensure_ascii=False)
    assert control_wires[0]["max_tokens"] == 2048
    assert any(item["event"] == "vllm_response" and item["role"] == "state_control"
               and item["control_stage"] == "history_summary"
               for item in control_events)
    counts = json.loads((tmp_path / "control-capacity.json").read_text())
    assert sum(value for key, value in counts.items()
               if key.startswith("history_summary:")) == 1
    schemas = [wire["response_format"] for wire in host_wires]
    assert all(item == schemas[0] for item in schemas)
    assert "read_history" in json.dumps(schemas[0])
    full_root = tmp_path / "full"
    full_root.mkdir()
    write_json(full_root / "run_manifest.json", {"identity": {
        "run_id": "run", "arm_id": "full_history"}})
    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(host_response)) as host:
        with SqliteSaver.from_conn_string(str(full_root / "checkpoint.sqlite")) as saver:
            runtime = SimpleNamespace(
                model=VLLMChatModel(client=host), store=store, checkpointer=saver,
                observer=SimpleNamespace(
                    assert_healthy=lambda: None,
                    run_tool=lambda request, execute, _wrapper: execute(request)))
            app.run_phase({**script, "phases": script["phases"][:1]}, full_root,
                          "run", "full_history", 0, runtime,
                          history_mode="full", history_page_max_bytes=16384)
    assert host_wires[-1]["response_format"] == schemas[0]


def test_mock_provider_business_call_commits_real_partial_result(tmp_path: Path) -> None:
    script = {"initial_label_available": False, "phases": [{
        "id": 0, "operator_memory": [], "world_events": [], "messages": [{
            "message_id": "reserve", "user_id": "alice", "session_id": "handoff",
            "public_index": 0, "text": "Reserve the complete item reference once."}]}]}
    wires: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        wires.append(json.loads(request.read()))
        action = ({"calls": [{"name": "reserve_and_label", "arguments": {
            "item_key": "Cobalt display panels", "quantity": 6,
            "destination": "east bay", "packing": "foam"}}]}
            if len(wires) == 1 else {"answer": "Reservation persisted; label failed."})
        return httpx.Response(200, json={
            "id": f"generation-{len(wires)}", "model": "mock",
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(action)}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    with VLLMClient(VLLMConfig(base_url="http://mock/v1/", model="mock",
                               tool_mode="json_action"),
                    transport=httpx.MockTransport(respond)) as client:
        with SqliteSaver.from_conn_string(str(tmp_path / "checkpoint.sqlite")) as saver:
            runtime = SimpleNamespace(
                model=VLLMChatModel(client=client), store=InMemoryStore(),
                checkpointer=saver,
                observer=SimpleNamespace(
                    assert_healthy=lambda: None,
                    run_tool=lambda request, execute, _wrapper: execute(request)))
            result = app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime)
            assert app.run_phase(script, tmp_path, "run", "b1_control", 0, runtime) == result
    assert len(wires) == 2
    assert "complete item reference" in wires[0]["messages"][0]["content"]
    assert len(result["world"]["reservations"]) == 1
    assert result["world"]["reservations"][0]["label_status"] == "not_created"
    assert len(result["world"]["attempts"]) == 1
    assert result["messages"][0]["business_calls"][0]["status"] == "complete"


def test_four_arm_policy_and_generic_frozen_script_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(app_runtime, "ProjectionController", lambda *_args, **kwargs: (
        captured.append(kwargs) or kwargs))
    config = {"refresh_policy": {
        "refresh_until_current_candidate": True,
        "max_exact_refresh_per_search": 1}}
    for arm in ("b1_control", "a3_exact_refresh", "a4_selective_rebase",
                "a5_rank_bounded_rebase"):
        app_runtime.projection_for_arm(None, None, None, arm, config)
    assert [item["arm"] for item in captured] == [
        "a3_exact_refresh", "a4_selective_rebase", "a5_rank_bounded_rebase"]
    assert all(item["stage"] == "v21" for item in captured)
    assert [item["max_exact_refresh_per_search"] for item in captured] == [None, None, 1]
    reserve_key = app.BUSINESS_SCHEMAS[0]["function"]["parameters"]["properties"]["item_key"]
    read_key = app.BUSINESS_SCHEMAS[1]["function"]["parameters"]["properties"]["item_key"]
    assert "complete item reference" in reserve_key["description"]
    assert "complete item reference" in read_key["description"]

    monkeypatch.syspath_prepend(str(LAB / "tools"))
    import run_milai_application_v25 as entry

    monkeypatch.setattr(entry, "verify_application_v25_lock", lambda *_args, **_kwargs: {})
    lock, app_config = tmp_path / "lock.json", tmp_path / "config.json"
    lock.write_text("{}")
    app_config.write_text("{}")
    for variant in ("short", "medium", "long"):
        suffix = "" if variant == "short" else "-" + variant
        script = LAB / f"data/diagnostics/milai-application-v25{suffix}-script.json"
        freeze = LAB / f"data/manifests/milai-application-v25{suffix}-input-freeze.json"
        receipt = entry.prepare(SimpleNamespace(
            lock=lock, config=app_config, script=script, input_freeze=freeze,
            run="run", arm="b1_control", runtime_root=tmp_path / variant,
            output=tmp_path / f"{variant}.json"))
        assert receipt["public_messages"] == 9
        assert receipt["rubric_read_by_runner"] is False
