"""Real SQLite snapshots and scripted policy execution, without model calls."""
import shutil
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import memory_at

from milai_lab.harness.artifact_io import read_json
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.state_bench_adapter import (
    StateMemoryHook,
    learning_envelope,
    make_state_agent,
)
from milai_lab.runners.state_retrieval_capture import capture_state_retrieval


def setup_capture(store, root, **options):
    service = MemoryService(store, ("state-capture", "alice"), "alice", root / "lock",
                            functional_contract="functional_v1")
    service.capture_user("history", "rule", "Cancellation requires approval before execution.")
    service.capture_tool("history", "receipt", "cancel_booking",
                         "Cancellation completed after approval for booking B1.", None)
    memory = memory_at(service, control_delivery_selection=True, **options)
    hook = StateMemoryHook(memory, session="task", now="2026-06-15T10:00:00",
        domain="travel", user_id="u1", config_version="test", record=lambda _: None)
    hook.bind_conversation([{"role": "user", "content": "Was the cancellation executed?"}])
    domain = {"bookings": {"B1": {"status": "confirmed"}}}
    frame = {"conversation": [{"role": "user", "content": "Was it executed?"}]}
    recorder = capture_state_retrieval(hook, root, domain_snapshot=lambda: domain,
                                       context=lambda: {"host_frame": frame})
    return service, hook, domain, frame, recorder


def test_wal_before_and_actual_post_read_can_resume_without_reexecuting_prefix(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        store.conn.execute("PRAGMA journal_mode=WAL")
        store.conn.execute("PRAGMA wal_autocheckpoint=0")
        service, hook, domain, frame, recorder = setup_capture(store, tmp_path)
        sources_before = service.sources()
        hook.retrieve({"query": "Cancellation approval booking B1"})
        captured, = (tmp_path / "retrieval-snapshots").iterdir()
        call = read_json(captured / "call.json")
        assert call["schema"] == "state_dynamic_retrieval_call_v1"
        assert call["status"] == "ORIGINAL_COMPLETED" and call["original_result"]["evidence"]
        assert call["known_references_before"] == []
        assert call["runnable_config"] == hook.config
        assert call["initial_observation"] and call["initial_actions"]
        assert (tmp_path / "live.sqlite-wal").stat().st_size > 0
        shutil.copyfile(captured / "before/memory.sqlite", tmp_path / "check.sqlite")
        with SqliteStore.from_conn_string(str(tmp_path / "check.sqlite")) as before:
            saved = MemoryService(before, service.namespace, service.owner, tmp_path / "saved.lock",
                                  functional_contract="functional_v1")
            assert saved.sources() == sources_before
            binding = call["binding"]
            saved.bind_public_turn(binding["session"], binding["message_id"], binding["source_ref"],
                                   config_version=binding["config_version"], phase="resume")
            restored = memory_at(saved, control_delivery_selection=True)
            assert restored.read_allowance(call["runnable_config"]) == call["read_allowance"]
        assert read_json(captured / "before/domain.json") == domain
        frame["conversation"].clear()
        domain["bookings"]["B1"]["status"] = "cancelled"
        assert read_json(captured / "call.json")["host_frame"]["conversation"]
        assert read_json(captured / "before/domain.json")["bookings"]["B1"]["status"] == "confirmed"
        # The acquired material and prefix come from a real READ, not the final Store.
        steps = sorted((captured / "steps").iterdir())
        step = next(p for p in steps
                    if read_json(p / "control.json")["operations"]["observed"])
        row, checkpoint = read_json(step / "call.json"), read_json(step / "control.json")
        assert row["schema"] == "state_dynamic_retrieval_decision_v1"
        assert row["initial_observation"] == checkpoint["state"]
        assert any(e["result"]["status"] == "opened" for e in checkpoint["prefix_trace"])
        originals = {p: p.read_bytes() for p in captured.rglob("*") if p.is_file()}
        shutil.copyfile(step / "before/memory.sqlite", tmp_path / "resume.sqlite")
        events = []
        with SqliteStore.from_conn_string(str(tmp_path / "resume.sqlite")) as resumed_store:
            resumed_service = MemoryService(resumed_store, service.namespace, service.owner,
                tmp_path / "resume.lock", functional_contract="functional_v1")
            resumed_service.bind_public_turn(binding["session"], binding["message_id"],
                binding["source_ref"], config_version=binding["config_version"], phase="resume")
            resumed = memory_at(resumed_service, control_delivery_selection=True,
                replay_control_checkpoint=checkpoint, control_record=events.append,
                return_envelope=learning_envelope)
            assert resumed.read_allowance(row["runnable_config"]) == row["read_allowance"]
            packet = resumed.retrieve(row["runnable_config"], row["call_id"],
                                      RetrievalRequest.model_validate(row["request"]))
        decisions = [e for e in events if e.get("phase") == "decision_input"]
        assert decisions[0]["before"] == row["initial_observation"]
        assert decisions[0]["actions"] == row["initial_actions"]
        assert all(e["step"] >= row["control_step"] for e in decisions)
        assert packet == call["original_result"]
        assert {p: p.read_bytes() for p in originals} == originals
        assert recorder.calls[call["call_id"]][1]["control_events"] == call["control_events"]
        with pytest.raises(ValueError, match="requires a functional capture"):
            replay_call(captured, tmp_path / "wrong-protocol", {}, source_version="test")
        assert not (tmp_path / "wrong-protocol").exists()


def test_execution_failure_keeps_selected_binding_without_inventing_result(tmp_path, monkeypatch):
    def fail(*_, **__):
        raise RuntimeError("actual admission failed")

    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        _, hook, _, _, _ = setup_capture(store, tmp_path)
        monkeypatch.setattr(hook.memory, "_read", fail)
        with pytest.raises(RuntimeError, match="actual admission failed"):
            hook.retrieve({"query": "Cancellation"})
    captured, = (tmp_path / "retrieval-snapshots").iterdir()
    row = read_json(captured / "call.json")
    assert row["status"] == "ORIGINAL_FAILED"
    assert row["initial_actions"] and row["initial_observation"]
    assert "original_result" not in row
    event, = row["control_events"]
    assert event["phase"] == "decision_output" and "result" not in event
    assert any(action["id"] == event["selected"] for action in row["initial_actions"])


def test_zero_decision_call_retains_before_without_inventing_actions(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        _, hook, _, _, _ = setup_capture(store, tmp_path, control_steps=0)
        hook.retrieve({"query": "Cancellation"})
    captured, = (tmp_path / "retrieval-snapshots").iterdir()
    row = read_json(captured / "call.json")
    assert row["status"] == "ORIGINAL_COMPLETED"
    assert row["initial_observation"] is None and row["initial_actions"] is None
    assert "control_events" not in row
    assert (captured / "before/memory.sqlite").is_file()


def test_sdk_batch_snapshot_has_actual_sibling_effect_but_original_public_frame(tmp_path):
    sdk = pytest.importorskip("state_bench.agents.base")
    from state_bench.domain import get_domain_config
    from state_bench.domains.travel.schemas import EnvironmentData, HotelInventoryItem, User
    from state_bench.orchestrator import _run_harness_executed_agent_turn

    data = EnvironmentData(flights=[], bookings=[], users=[User("u1", "Alice", "a@example.test")],
        hotel_inventory=[HotelInventoryItem("H1", "Example Hotel", "DEN", "2026-07-01",
                                           "2026-07-02", "standard", 100, 100)])
    now = "2026-06-15T10:00:00"
    domain = get_domain_config("travel")
    environment = domain.environment_class(data, now)
    frames, host_frame = [], {}
    responses = iter([AIMessage(content="", tool_calls=[
        {"id": "book", "name": "book_hotel", "args": {"user_id": "u1", "hotel_id": "H1"}},
        {"id": "memory", "name": "retrieve_learnings", "args": {"query": "Cancellation"}}]),
        AIMessage(content="Booked.")])
    model = SimpleNamespace(begin_public_message=lambda _: None)
    model.bind_tools = lambda _: SimpleNamespace(invoke=lambda _: next(responses))

    def observe(frame):
        frames.append(frame)
        host_frame.clear()
        host_frame.update(frame)

    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        _, hook, _, _, _ = setup_capture(store, tmp_path)
        capture_state_retrieval(hook, tmp_path, domain_snapshot=environment.get_full_snapshot,
                                context=lambda: {"host_frame": host_frame})
        runtime = sdk.AgentRuntimeContext(task_id="hidden task", user_id="u1", domain="travel",
            now=now, task_summary="hidden summary", state_requirements=[{"hidden": True}])
        agent = make_state_agent(model, hook, runtime, observe_host=observe)
        _, calls = _run_harness_executed_agent_turn(agent=agent, system_prompt="Public policy",
            conversation_full=[{"role": "user", "content": "Was the cancellation executed?"}],
            domain_tools=domain.tool_schemas, domain_tool_handlers=environment.tool_handlers)
    captured, = (tmp_path / "retrieval-snapshots").iterdir()
    row = read_json(captured / "call.json")
    before = read_json(captured / "before/domain.json")
    assert next(iter(before["hotels"].values()))["hotel_id"] == "H1"
    assert [call["name"] for call in calls] == ["book_hotel", "retrieve_learnings"]
    assert row["host_frame"] == frames[0]
    assert len(row["host_frame"]["conversation"]) == 1
    assert frames[1]["conversation"][1]["tool_calls"] == calls
    assert "hidden" not in str(row["host_frame"])
    assert "result" not in row["host_frame"]["response"]["tool_calls"][0]
