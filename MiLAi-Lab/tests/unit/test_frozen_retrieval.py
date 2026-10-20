"""Actual Store snapshots and scripted Host calls; no real model or ledger."""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_given_retrieval import prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import frozen, message


def native_request(request, call_id="actual-call"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "milai_retrieve", "arguments": json.dumps(request)}}]}


def test_actual_host_request_replays_equal_before_with_other_policy_and_no_host_retry(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"
    request = {"query": "Cedar code", "read_goal": {"purpose": "quote the source"},
               "task_context": {"as_of": None}, "limits": {"max_control_steps": 5}}
    wires = scripted(monkeypatch, lambda wire, n: native_request(request) if n == 1 else
                     {"role": "assistant", "content": "4312" if n == 2
                      else '{"choice":"handoff"}'}, native=True)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED", original.get("error")
    assert len(wires) == 2
    captured, = snapshots.iterdir()
    call = read_json(captured / "call.json")
    assert call["status"] == "ORIGINAL_COMPLETED"
    assert call["request"] == request and call["call_id"] == "actual-call"
    assert call["host_request_generated"] is True and call["generation_calls_before"] == 1
    assert call["initial_observation"] and call["initial_actions"]
    original_files = {str(p.relative_to(captured)): p.read_bytes()
                      for p in captured.rglob("*") if p.is_file()}
    replay = replay_call(captured, tmp_path / "fixed", {"policy": "fixed", "reads": 4},
                         source_version="mechanical")
    assert replay["status"] == "COMPLETED", replay.get("error")
    assert replay["request_transport"] == "frozen_actual_tool_call"
    assert replay["frozen_request_and_allowance_equal"]
    assert replay["frozen_initial_observation_and_actions_equal"]
    assert replay["messages"][0]["tool_call_id"] == "actual-call"
    assert replay["final_answer"] is None and replay["host_request_regenerated"] is False
    assert len(wires) == 2
    assert {str(p.relative_to(captured)): p.read_bytes()
            for p in captured.rglob("*") if p.is_file()} == original_files
    assert replay["budget_before"]["generation"] == replay["budget_after"]["generation"]
    assert frozen(tmp_path / "fixed/runtime")["config"]["budget_path"] == (
        frozen(root)["config"]["budget_path"])

    class Handoff:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            return {"choice": "handoff"}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Handoff)
    stopped = replay_call(captured, tmp_path / "learned", {
        "policy": "laya", "checkpoint": "stub", "device": "cpu"}, source_version="mechanical")
    assert stopped["status"] == "COMPLETED", stopped.get("error")
    assert stopped["frozen_initial_observation_and_actions_equal"]
    assert stopped["retrieval_result"]["evidence"] == []
    assert replay["retrieval_result"]["evidence"]
    assert stopped["budget_after"]["compute"]["dynamic_memory_laya"]["forwards"] == 1
    assert len(wires) == 2
    generated = replay_call(captured, tmp_path / "generative", {"policy": "generative"},
                            source_version="mechanical")
    assert generated["status"] == "COMPLETED", generated.get("error")
    assert generated["frozen_initial_observation_and_actions_equal"]
    assert generated["retrieval_result"]["evidence"] == []
    assert len(wires) == 3
    assert "Control this MiLAi evidence retrieval" in wires[-1]["messages"][0]["content"]
    assert generated["budget_after"]["generation_requests"] == (
        generated["budget_before"]["generation_requests"] + 1)
    changed = tmp_path / "changed-observation"
    shutil.copytree(captured, changed)
    metadata = read_json(changed / "call.json")
    metadata["initial_observation"]["task"]["request"] = "Different target"
    (changed / "call.json").write_text(json.dumps(metadata))
    failed = replay_call(changed, tmp_path / "reject-changed", {"policy": "fixed"},
                         source_version="mechanical")
    assert failed["status"] == "FAILED"
    assert failed["error"] == "FROZEN_RETRIEVAL_INITIAL_OBSERVATION_CHANGED"
    assert len(wires) == 3


def test_second_request_keeps_prior_returned_refs_and_consumed_allowance(tmp_path, monkeypatch):
    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"

    def reply(wire, n):
        if n == 1:
            return native_request({"query": "Cedar code"}, "first")
        if n == 2:
            packet = json.loads(next(m["content"] for m in wire["messages"] if m["role"] == "tool"))
            return native_request({"query": "Cedar code", "task_context": {
                "known_evidence_refs": [item["ref"] for item in packet["evidence"]]}}, "second")
        return {"role": "assistant", "content": "4312"}

    wires = scripted(monkeypatch, reply, native=True)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find then verify the reported Cedar code", incoming_sources=[source()],
        retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED", original.get("error")
    cases = {read_json(path / "call.json")["call_id"]: path for path in snapshots.iterdir()}
    first, second = [read_json(cases[key] / "call.json") for key in ("first", "second")]
    assert second["generation_calls_before"] == 2
    assert second["read_allowance"]["reads_remaining"] < first["read_allowance"]["reads_remaining"]
    assert second["initial_observation"]["task"]["known_evidence"]
    replay = replay_call(cases["second"], tmp_path / "repeat-second",
                         {"policy": "fixed_context", "reads": 4}, source_version="mechanical")
    assert replay["status"] == "COMPLETED", replay.get("error")
    assert replay["frozen_initial_observation_and_actions_equal"]
    assert replay["frozen_request_and_allowance_equal"]
    assert len(wires) == 3


@pytest.mark.parametrize("steps", [0, 4])
def test_zero_decision_and_failed_calls_remain_available_without_repair(
    tmp_path, monkeypatch, steps,
):
    root = prepared_given(tmp_path, policy={"policy": "laya", "checkpoint": "stub",
        "device": "cpu", "max_control_steps": 4}, failure_receipts=True)
    snapshots = tmp_path / "snapshots"
    attempts = []

    class Failure:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            attempts.append(payload)
            raise RuntimeError("original policy failed")

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Failure)
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Cedar code", incoming_sources=[source()], retrieval_snapshots=snapshots,
        given_retrieval_request={"query": "Cedar code", "limits": {"max_control_steps": steps}})
    assert result["status"] == ("FAILED" if steps else "COMPLETED")
    captured, = snapshots.iterdir()
    call = read_json(captured / "call.json")
    assert call["status"] == ("ORIGINAL_FAILED" if steps else "ORIGINAL_COMPLETED")
    assert bool(call["initial_observation"]) is bool(steps)
    replay = replay_call(captured, tmp_path / "fixed", {"policy": "fixed"},
                         source_version="mechanical")
    assert replay["status"] == "COMPLETED", replay.get("error")
    assert replay["frozen_request_and_allowance_equal"]
    assert "failure_delivery" not in replay
    assert len(attempts) == (1 if steps else 0)


@pytest.mark.parametrize("readout", [False, True])
def test_multiple_native_calls_are_serially_captured_and_complete_cli_cohort_runs(
    tmp_path, monkeypatch, readout,
):
    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"

    def reply(wire, n):
        if n == 1:
            result = native_request({"query": "Cedar code"}, "first")
            result["tool_calls"].extend(
                native_request({"query": "Cedar code"}, "second")["tool_calls"])
            return result
        return {"role": "assistant", "content": "4312"}

    wires = scripted(monkeypatch, reply, native=True)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported code", incoming_sources=[source()],
        retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED", original.get("error")
    calls = sorted((read_json(path / "call.json") for path in snapshots.iterdir()),
                   key=lambda row: row["captured_epoch"])
    assert [call["call_id"] for call in calls] == ["first", "second"]
    assert [call["generation_calls_before"] for call in calls] == [1, 1]
    assert (calls[1]["read_allowance"]["reads_remaining"]
            < calls[0]["read_allowance"]["reads_remaining"])
    policies = tmp_path / "policies.json"
    policies.write_text(json.dumps([{"name": "fixed", "policy": {"policy": "fixed"}},
                                   {"name": "context", "policy": {"policy": "fixed_context"}}]))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    import run_frozen_retrieval_calls

    monkeypatch.setattr(sys, "argv", ["run_frozen_retrieval_calls", str(snapshots),
        str(policies), str(tmp_path / "matrix"), "--source-version", "mechanical",
        *(["--host-readout"] if readout else [])])
    run_frozen_retrieval_calls.main()
    driver = read_json(tmp_path / "matrix/driver.json")
    assert driver["status"] == "COMPLETED"
    assert driver["planned_positions"] == len(driver["completed"]) == 4
    assert all(row["before_equal"] for row in driver["completed"])
    assert len(wires) == (6 if readout else 2)
    assert driver["orchestration_cpu_seconds_not_yet_recorded"] >= 0
    if readout:
        assert all(row["host_readout_status"] == "COMPLETED" for row in driver["completed"])


def test_cached_actual_call_keeps_prior_packet_and_does_not_invent_a_policy_decision(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path)
    snapshots = tmp_path / "snapshots"
    retrieve = IntentRetrievalMemory.retrieve

    def repeat_entry(memory, config, call_id, request):
        # Explicitly exercise the tool's idempotent re-entry. The Host wire itself
        # correctly rejects duplicate tool-call IDs, so it sends one request.
        first = retrieve(memory, config, call_id, request)
        second = retrieve(memory, config, call_id, request)
        assert first == second
        return second

    monkeypatch.setattr(IntentRetrievalMemory, "retrieve", repeat_entry)
    wires = scripted(monkeypatch, lambda wire, n:
        native_request({"query": "Cedar code"}, "same-call") if n == 1 else
        {"role": "assistant", "content": "4312"}, native=True)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported code", incoming_sources=[source()],
        retrieval_snapshots=snapshots)
    assert original["status"] == "COMPLETED", original.get("error")
    calls = sorted(((path, read_json(path / "call.json")) for path in snapshots.iterdir()),
                   key=lambda row: row[1]["captured_epoch"])
    assert len(calls) == 2 and len(wires) == 2
    assert [row["served_from_cache"] for _, row in calls] == [False, True]
    captured, call = calls[1]
    assert call["initial_observation"] is None
    monkeypatch.setattr(IntentRetrievalMemory, "retrieve", retrieve)
    # This unused executor must not load a model merely to return an existing receipt.
    replay = replay_call(captured, tmp_path / "cached", {
        "policy": "laya", "checkpoint": "must-not-load"}, source_version="mechanical")
    assert replay["status"] == "COMPLETED", replay.get("error")
    assert replay["frozen_request_and_allowance_equal"]
    assert replay["retrieval_result"] == call["original_result"]
    assert "frozen_initial_observation_and_actions_equal" not in replay
    assert len(wires) == 2
