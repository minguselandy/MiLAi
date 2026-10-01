"""Real invoke/native callback/shared counter; synthetic transport, zero sockets."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, RunLimits
from milai_lab.integrations.memory.mem0 import _ChatCompletions
from milai_lab.memory.service import MemoryService
from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers import generation_admission as admission
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

HOST_TOOLS = [{"type": "function", "function": {
    "name": "inspect_public_receipt", "description": "Read an actual public receipt.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}}]


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("SOCKET_FORBIDDEN")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def scope() -> dict[str, Any]:
    return {"owner": "alice", "bank": ["synthetic", "alice"], "session": "session",
            "request_ref": "actual-public-source", "request_sha256": "a" * 64,
            "config_sha256": "b" * 64}


def first_row(path: Path) -> dict[str, Any]:
    return next(iter(read_json(path)["messages"].values()))


def make(tmp_path: Path, cap: int = 12, *, fail: str | None = None,
         profile: str = "durable_shared_v1", budget_cap: int = 100) -> tuple[Any, Any, Any]:
    wires: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    budget = RunBudget(RunLimits(1, 1, budget_cap, 1000000, 0), tmp_path / "budget.json")

    def response(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        if profile == "durable_shared_v1":
            # The actual transport sees an already persisted slot and local budget.
            assert first_row(tmp_path / "capacity.json")["count"] == len(wires) + 1
        assert budget.state["generation_requests"] == len(wires) + 1
        wires.append(json.loads(request.content))
        if fail == "unknown":
            raise httpx.ReadError("SCRIPTED_UNKNOWN", request=request)
        if fail == "sent_exit":
            os._exit(73)
        return httpx.Response(200, json={
            "id": "scripted-response", "object": "chat.completion", "created": 0,
            "model": "mock", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"answer":"No change."}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })

    client = VLLMClient(VLLMConfig("http://mock/v1", "mock", max_tokens=8),
                        emit=events.append, transport=httpx.MockTransport(response), budget=budget)
    model = LangMemRecipeChatModel(client=client, capacity_path=tmp_path / "capacity.json",
                                  max_calls_per_message=cap,
                                  generation_admission_profile=profile)
    return model, wires, events


def begin(model: Any, *, phase: str = "start", checkpoint: int = 0,
          actual_scope: dict[str, Any] | None = None) -> None:
    model.begin_public_message("u", checkpoint_calls=checkpoint, admission_phase=phase,
                               admission_scope=actual_scope or scope())


def native(model: Any) -> Any:
    # The actual existing native transport callback; no SDK constructor or add mock.
    return _ChatCompletions(model.client, threading.Lock(), model._reserve_request).create(
        model="mock", temperature=0, max_tokens=8, top_p=1.0,
        messages=[{"role": "user", "content": "actual archived event data"}],
    )


def scripted_summary(model: Any) -> Any:
    # Planned direct caller only; this is explicitly NOT a B6 implementation.
    model._reserve_request(origin="scripted_summary_caller_unimplemented")
    return model.client.chat([{"role": "user", "content": "scripted summary input"}])


@pytest.mark.parametrize("cap", [12, 24])
def test_actual_host_native_m_and_scripted_summary_share_inclusive_cap(
    tmp_path: Path, cap: int,
) -> None:
    model, wires, _ = make(tmp_path, cap)
    host_checkpoint = []
    with SqliteStore.from_conn_string(str(tmp_path / "source.sqlite")) as store:
        service = MemoryService(store, ("synthetic", "alice"), "alice", tmp_path / "source.lock",
                                mutation_contract="event_bound_v1")
        captured = service.capture_user("session", "u", "Keep actual event roles.")
        source = service.source(captured["source_ref"])
        actual_scope = {**scope(), "request_ref": source["event_id"],
                        "request_sha256": source["content_sha256"]}
        begin(model, actual_scope=actual_scope)
        host_checkpoint.append(model.invoke([HumanMessage("真实输入 / entrada real")],
                                            tools=HOST_TOOLS))
        native(model)
        recipe = GroundedMemoryRecipe(service, len)
        config = {"configurable": {"user_id": "alice", "v13_session": "session",
                                   "v13_turn_id": "u"}}
        maintenance = recipe.maintain(model, session="session", turn_id="u",
                                     source_refs=[captured["source_ref"]], config=config,
                                     instruction="Use the actual sources.", repairs=0)
        assert maintenance["status"] == "no_change" and maintenance["generation_calls"] == 1
        assert len(wires) == 3
        scripted_summary(model)
        while len(wires) < cap:
            if len(wires) % 3 == 0:
                host_checkpoint.append(model.invoke([HumanMessage("actual continuation")],
                                                    tools=HOST_TOOLS))
            elif len(wires) % 3 == 1:
                native(model)
            else:
                scripted_summary(model)
        budget = model.client.budget
        assert budget.state["generation_requests"] == len(wires) == cap
        assert budget.state["generation"]["unknown_usage"] == 0
        assert budget.state["generation"]["known_tokens"] == cap * 6
        assert first_row(model.capacity_path)["count"] == cap
        # No second writer generation on actual completed-boundary replay.
        replay = recipe.maintain(model, session="session", turn_id="u",
                                 source_refs=[captured["source_ref"]], config=config,
                                 instruction="Use the actual sources.", repairs=0)
        assert replay == {**maintenance, "replayed": True}
        restored = LangMemRecipeChatModel(client=model.client, capacity_path=model.capacity_path,
                                         max_calls_per_message=cap,
                                         generation_admission_profile="durable_shared_v1")
        begin(restored, phase="resume", checkpoint=len(host_checkpoint), actual_scope=actual_scope)
        assert restored.calls_in_message == cap
        for invoke in (lambda: restored.invoke([HumanMessage("extra")], tools=HOST_TOOLS),
                       lambda: native(restored), lambda: scripted_summary(restored)):
            with pytest.raises(ValueError, match="GENERATION_CAPACITY_EXCEEDED"):
                invoke()
        assert len(wires) == budget.state["generation_requests"] == cap
        rows = first_row(model.capacity_path)["reservations"]
        assert [row["ordinal"] for row in rows] == list(range(1, cap + 1))
        assert rows[1]["origin"] is None  # Existing callback carries no origin argument.
        assert rows[2]["origin"] == "model_invoke"  # M shares invoke, not a guessed writer label.
    model.client.close()


@pytest.mark.parametrize("damage", ["missing_file", "missing_key", "malformed", "negative",
                                    "float", "bool", "string", "count_receipts_disagree",
                                    "reservation_ordinal", "over_cap"])
def test_bad_resume_refuses_before_any_transport(tmp_path: Path, damage: str) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    model.invoke([HumanMessage("actual")], tools=HOST_TOOLS)
    path = model.capacity_path
    state = read_json(path)
    row = next(iter(state["messages"].values()))
    if damage == "missing_file":
        path.unlink()
    elif damage == "malformed":
        path.write_text("{broken")
    else:
        if damage == "missing_key":
            state["messages"].clear()
        elif damage == "reservation_ordinal":
            row["reservations"][0]["ordinal"] = True
        else:
            row["count"] = {"negative": -1, "float": 1.5, "bool": True, "string": "1",
                            "count_receipts_disagree": 2, "over_cap": 13}[damage]
        write_json(path, state)
    with pytest.raises(ValueError, match="GENERATION_ADMISSION"):
        begin(model, phase="resume", checkpoint=1)
    with pytest.raises(ValueError, match="NOT_STARTED"):
        native(model)
    assert len(wires) == 1 and model.client.budget.state["generation_requests"] == 1
    model.client.close()


@pytest.mark.parametrize("field", ["owner", "bank", "session", "request_ref", "request_sha256",
                                   "config_sha256"])
def test_actual_scope_identity_must_match_on_resume(tmp_path: Path, field: str) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    changed = scope()
    changed[field] = ["other", "bank"] if field == "bank" else (
        "c" * 64 if field.endswith("sha256") else "other"
    )
    with pytest.raises(ValueError, match="GENERATION_ADMISSION"):
        begin(model, phase="resume", actual_scope=changed)
    assert not wires
    model.client.close()


def test_real_checkpoint_is_lower_bound_and_live_counter_cannot_decrease(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    checkpoints = [model.invoke([HumanMessage(text)], tools=HOST_TOOLS) for text in ("one", "two")]
    state = read_json(model.capacity_path)
    row = next(iter(state["messages"].values()))
    row["count"] = 1
    row["reservations"] = row["reservations"][:1]
    write_json(model.capacity_path, state)
    with pytest.raises(ValueError, match="LOWER_BOUND"):
        model.invoke([HumanMessage("three")], tools=HOST_TOOLS)
    with pytest.raises(ValueError, match="LOWER_BOUND"):
        begin(model, phase="resume", checkpoint=len(checkpoints))
    assert len(wires) == 2
    model.client.close()


def test_configuration_changed_cannot_dispatch_or_resume(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    model.client.config = replace(model.client.config, max_tokens=9)
    with pytest.raises(ValueError, match="CONFIGURATION_CHANGED"):
        model.invoke([HumanMessage("actual")], tools=HOST_TOOLS)
    with pytest.raises(ValueError, match="STATE_INCOMPATIBLE"):
        begin(model, phase="resume")
    assert not wires
    model.client.close()


def test_active_message_cannot_be_rebound_without_actual_begin(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    model.active_message_key = "another-message"
    with pytest.raises(ValueError, match="ACTIVE_MESSAGE_CHANGED"):
        native(model)
    assert first_row(model.capacity_path)["count"] == 0 and not wires
    model.client.close()


def test_explicit_phase_start_and_missing_live_key_are_fail_closed(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path)
    with pytest.raises(ValueError, match="EXPLICIT_CONTEXT"):
        model.begin_public_message("u")
    begin(model)
    with pytest.raises(ValueError, match="ALREADY_STARTED"):
        begin(model)
    begin(model, phase="resume")
    state = read_json(model.capacity_path)
    state["messages"].clear()
    write_json(model.capacity_path, state)
    with pytest.raises(ValueError, match="RESUMED_MESSAGE_MISSING"):
        scripted_summary(model)
    assert not wires
    model.client.close()


def test_unknown_keeps_slot_and_budget_without_automatic_retry(tmp_path: Path) -> None:
    model, wires, events = make(tmp_path, fail="unknown")
    begin(model)
    with pytest.raises(httpx.ReadError, match="SCRIPTED_UNKNOWN"):
        native(model)
    charged = read_json(tmp_path / "budget.json")
    begin(model, phase="resume", checkpoint=0)
    assert model.calls_in_message == first_row(model.capacity_path)["count"] == 1
    assert len(wires) == charged["generation_requests"] == 1
    assert charged["generation"]["unknown_usage"] == 1
    assert charged["generation"]["charged_tokens"] > 0
    assert read_json(tmp_path / "budget.json") == charged
    assert [event["event"] for event in events] == ["vllm_error"]
    model.client.close()


def test_global_budget_refusal_consumes_admission_without_dispatch(tmp_path: Path) -> None:
    model, wires, events = make(tmp_path, budget_cap=0)
    begin(model)
    with pytest.raises(BudgetExceeded):
        model.invoke([HumanMessage("actual")], tools=HOST_TOOLS)
    assert first_row(model.capacity_path)["count"] == 1
    assert not wires and model.client.budget.state["generation_requests"] == 0
    assert events[0]["event"] == "vllm_budget_rejected" and not events[0]["request_sent"]
    model.client.close()


@pytest.mark.parametrize("after_replace", [False, True])
def test_persistence_failure_prevents_transport_and_preserves_replaced_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_replace: bool,
) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    if after_replace:
        real_fsync = admission.os.fsync

        def fail_directory(descriptor: int) -> None:
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("SCRIPTED_DIRECTORY_FSYNC_CUT")
            real_fsync(descriptor)

        monkeypatch.setattr(admission.os, "fsync", fail_directory)
    else:
        def fail_replace(self: Path, target: Path) -> Any:
            raise OSError("SCRIPTED_BEFORE_REPLACE_CUT")

        monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="SCRIPTED_"):
        model.invoke([HumanMessage("actual")], tools=HOST_TOOLS)
    monkeypatch.undo()
    begin(model, phase="resume")
    assert model.calls_in_message == int(after_replace)
    assert not wires and model.client.budget.state["generation_requests"] == 0
    model.client.close()


@pytest.mark.parametrize("cut", ["admission", "ledger", "sent_exit"])
def test_real_process_exit_retains_slot_and_actual_unknown_ledger(tmp_path: Path, cut: str) -> None:
    code = """
import os, sys
from pathlib import Path
sys.path.insert(0, 'tests/memory')
from test_v13_2_generation_admission import make, begin
p=Path(sys.argv[1]); cut=sys.argv[2]
model,wires,events=make(p,fail=cut)
begin(model)
if cut == 'admission':
    model._reserve_request(); os._exit(71)
if cut == 'ledger':
    original=model.client.budget.reserve
    def exit_after_ledger(*args,**kwargs):
        original(*args,**kwargs); os._exit(72)
    model.client.budget.reserve=exit_after_ledger
from langchain_core.messages import HumanMessage
model.invoke([HumanMessage('actual')])
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path), cut],  # noqa: S603
                            env=dict(os.environ), capture_output=True, text=True, timeout=40)
    assert result.returncode == {"admission": 71, "ledger": 72, "sent_exit": 73}[cut], result.stderr
    model, wires, _ = make(tmp_path)
    begin(model, phase="resume")
    assert model.calls_in_message == 1 and not wires
    state = model.client.budget.state
    assert state["generation_requests"] == int(cut != "admission")
    assert state["generation"]["unknown_usage"] == int(cut != "admission")
    model.client.close()


def test_legacy_default_counter_bytes_and_wire_stay_unchanged(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path, profile="legacy")
    assert model.generation_admission_profile == "legacy"
    model.begin_public_message("u")
    assert model.invoke([HumanMessage("actual")], tools=HOST_TOOLS).content == "No change."
    native(model)
    expected = json.dumps({"u": 2}, ensure_ascii=False, indent=2) + "\n"
    assert model.capacity_path.read_text() == expected
    model.begin_public_message("u", checkpoint_calls=3)
    assert model.calls_in_message == 3 and len(wires) == 2
    assert not model.capacity_path.with_suffix(".json.lock").exists()
    model.client.close()


def test_new_message_and_session_get_separate_scoped_slots(tmp_path: Path) -> None:
    model, wires, _ = make(tmp_path)
    begin(model)
    model.invoke([HumanMessage("one")], tools=HOST_TOOLS)
    # Same actual message ID in another session is a different public turn.
    other = {**scope(), "session": "other-session", "request_ref": "other-source"}
    begin(model, actual_scope=other)
    assert model.calls_in_message == 0
    assert len(read_json(model.capacity_path)["messages"]) == 2
    begin(model, phase="resume")
    assert model.calls_in_message == 1 and len(wires) == 1
    model.client.close()


def test_runner_uses_actual_checkpoint_phase_source_hash_and_frozen_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_v13_1_p5 as old

    from milai_lab.runners import v13_1_p5 as runner

    old.prepared(tmp_path)
    config = read_json(tmp_path / "config.json")
    config["generation_admission_profile"] = "durable_shared_v1"
    write_json(tmp_path / "durable.json", config)
    root = tmp_path / "durable-run"
    runner.prepare(tmp_path / "public.json", tmp_path / "durable.json", root)

    def local(settings: Any, budget: Any, trace: Any, resource_root: Path) -> Any:
        original = old.local_model(settings, budget, trace, resource_root)
        return old.ScriptModel(client=original.client, capacity_path=original.capacity_path,
                               max_calls_per_message=original.max_calls_per_message,
                               generation_admission_profile="durable_shared_v1",
                               wire_path=original.wire_path)

    monkeypatch.setattr(runner, "make_model", local)
    started = runner.step(root, "mechanical", 0, attempt_id="gate-start")
    assert started["status"] == "completed", started
    resource = runner.case_path(root, "mechanical")
    path = resource / "host-capacity.json"
    row = first_row(path)
    identity = row["identity"]
    assert identity["public_message_id"] == "m1" and identity["owner"] == "alice"
    assert identity["config_sha256"] == hashlib.sha256(
        (tmp_path / "durable.json").read_bytes()
    ).hexdigest()
    assert identity["request_ref"] == started["capture_receipt"]["source_ref"]
    count = row["count"]
    resumed = runner.step(root, "mechanical", 0, phase="resume", attempt_id="gate-resume")
    assert resumed["status"] == "completed", resumed
    assert first_row(path)["count"] == count
    before = (resource / "test-model-wire.jsonl").read_bytes()
    original = read_json(path)
    state = read_json(path)
    changed = next(iter(state["messages"].values()))
    changed.update(count=0, reservations=[])
    write_json(path, state)
    below = runner.step(root, "mechanical", 0, phase="resume", attempt_id="gate-below")
    assert below["status"] == "interrupted" and "COUNTER_BELOW_LOWER_BOUND" in below["error"]
    assert (resource / "test-model-wire.jsonl").read_bytes() == before
    write_json(path, original)
    path.unlink()
    refused = runner.step(root, "mechanical", 0, phase="resume", attempt_id="gate-missing")
    assert refused["status"] == "interrupted" and "RESUMED_FILE_MISSING" in refused["error"]
    assert (resource / "test-model-wire.jsonl").read_bytes() == before


def test_make_model_explicit_opt_in_and_legacy_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import v13_1_p5 as runner

    monkeypatch.setattr(runner, "HostCapacity", lambda settings: None)
    settings = {"host": asdict(VLLMConfig("http://mock/v1", "mock")), "capacity": {}}
    budget = RunBudget(RunLimits(1, 1, 0, 0, 0), tmp_path / "budget.json")
    legacy = runner.make_model(settings, budget, lambda event: None, tmp_path)
    settings["generation_admission_profile"] = "durable_shared_v1"
    durable = runner.make_model(settings, budget, lambda event: None, tmp_path)
    assert legacy.generation_admission_profile == "legacy"
    assert durable.generation_admission_profile == "durable_shared_v1"
    assert legacy.client.budget is durable.client.budget is budget
    legacy.client.close()
    durable.client.close()
