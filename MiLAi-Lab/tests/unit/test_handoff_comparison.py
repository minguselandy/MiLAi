"""F1 uses actual restored evidence with no new acquisitions or real model calls."""
import copy
import sys
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest
from test_frozen_control_steps import captured_after
from test_given_retrieval import no_http, prepared_given, source

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.laya_memory_policy import payload_actions
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import message
from milai_lab.runners.handoff_comparison import prepare_handoff_call
from milai_lab.runners.memory_control import HandoffOnlyPolicy


def test_delivery_restriction_preserves_state_and_complete_bound_action_order():
    state = MemoryControlState(task={"request": "current exception"},
        budget={"acquisition_reads_remaining": 3, "remaining_control_steps": 7},
        observed_materials=[{"item_index": 4, "selected": False}])
    actions = [MemoryAction("read", "READ", "candidate", {"index": 6}),
        MemoryAction("stop", "HANDOFF", "opened"),
        MemoryAction("scope", "HANDOFF", "selected", {
            "delivery_indices": [4, 2], "retrieved_scope_indices": [2]})]
    before, original = state.project(), copy.deepcopy(actions)
    records = []

    class Choose:
        def choose(self, received, offered):
            assert received is state
            assert offered == actions[1:]
            return offered[-1].id

    assert HandoffOnlyPolicy(Choose(), records.append).choose(state, actions) == "scope"
    assert state.project() == before and actions == original
    assert records[0]["state"] == before
    assert records[0]["actions"] == [asdict(action) for action in actions[1:]]


def test_single_handoff_does_not_invoke_a_scorer_and_invalid_selection_never_executes():
    class Wrong:
        def choose(self, state, actions):
            return "read"

    state = MemoryControlState(task={"request": "code"})
    actions = [MemoryAction("read", "READ", "candidate"),
               MemoryAction("end", "HANDOFF", "opened")]
    records = []
    policy = HandoffOnlyPolicy(Wrong(), records.append)
    assert policy.choose(state, actions) == "end"
    assert records[-1]["selection_mode"] == "only_available_handoff"
    with pytest.raises(ValueError, match="outside the delivery menu"):
        policy.choose(state, [*actions, MemoryAction("empty", "HANDOFF", "empty", {
            "delivery_indices": []})])
    assert records[-1]["event"] == "handoff_comparison_input"


def test_rules_and_scripted_scorer_replay_same_post_read_state_without_new_read(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "max_control_steps": 6,
        "delivery_selection": True, "source_observation_tokens": 300})
    captures = tmp_path / "captures"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code", "read_goal": {
            "evidence": ["original_source"], "required_points": ["Cedar", "code"]}},
        retrieval_snapshots=captures, retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = captured_after(captures, "READ")
    call = read_json(captured / "call.json")
    saved = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    assert call["read_allowance"]["reads_remaining"] > 0
    assert any(a["kind"] != "HANDOFF" for a in call["initial_actions"])
    executed, model_inputs = [], []
    execute = EvidenceOperations.execute

    def record_execute(operations, action, state):
        executed.append(action)
        return execute(operations, action, state)

    class Model:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            model_inputs.append(payload)
            offered = payload_actions(payload)
            assert all(action.kind == "HANDOFF" for action in offered)
            return {"choice": "handoff_select_none"}

    monkeypatch.setattr(EvidenceOperations, "execute", record_execute)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    inputs, results = [], []
    for kind in ("rules", "laya"):
        folder = tmp_path / kind
        result = replay_call(captured, folder, {"policy": kind, "routing": "handoff_only",
            "checkpoint": "scripted", "device": "cpu", "state_projection": "shared_actions"},
            source_version="mechanical")
        assert result["status"] == "COMPLETED", result.get("error")
        assert result["frozen_initial_observation_and_actions_equal"]
        assert result["frozen_request_and_allowance_equal"]
        assert read_json(folder / "replay.json")["prefix_operations_reexecuted"] == 0
        assert result["budget_before"]["generation"] == result["budget_after"]["generation"]
        events = [event for path in (folder / "runtime").rglob("*-trace-*.jsonl")
                  for event in read_jsonl(path) if event["event"] == "handoff_comparison_input"]
        assert len(events) == 1
        inputs.append(events[0])
        results.append(result["retrieval_result"])
    assert inputs[0] == inputs[1]
    assert inputs[0]["state"] == call["initial_observation"]
    assert results[0]["evidence"] and not results[1]["evidence"]
    assert results[0]["usage"]["read_operations"] == results[1]["usage"]["read_operations"]
    assert len(model_inputs) == 1
    assert all(action.kind == "HANDOFF" for action in executed)
    assert {p.relative_to(captured): p.read_bytes()
            for p in captured.rglob("*") if p.is_file()} == saved


@pytest.mark.parametrize('exclude_requests', [False, True])
def test_current_input_derivation_preserves_actual_prefix_and_strict_replay_admission(
    tmp_path, monkeypatch, exclude_requests,
):
    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "max_control_steps": 6,
        "delivery_selection": True, "source_observation_tokens": 300,
        "exclude_given_requests": exclude_requests})
    captures = tmp_path / "captures"
    monkeypatch.setattr(httpx.Client, "send", no_http)
    original = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the reported Cedar code", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code", "read_goal": {
            "evidence": ["original_source"]}},
        retrieval_snapshots=captures, retrieval_step_snapshots=True)
    assert original["status"] == "COMPLETED", original.get("error")
    captured = captured_after(captures, "READ")
    old, checkpoint = read_json(captured / "call.json"), read_json(captured / "control.json")
    # Simulate the pre-projection capture format using the actual acquired state.
    del old["initial_observation"]["retrieved_scopes"]
    del checkpoint["state"]["retrieved_scopes"]
    old["initial_actions"] = [a for a in old["initial_actions"]
                              if a["id"] != "handoff_select_none"]
    write_json(captured / "call.json", old)
    write_json(captured / "control.json", checkpoint)
    saved = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    prepared = tmp_path / "current"
    report = prepare_handoff_call(captured, prepared, source_version="current-test")
    assert report["status"] == "PREPARED_NOT_EXECUTED"
    assert report["changed_observation_fields"] == ["retrieved_scopes"]
    current = read_json(prepared / "call.json")
    assert current["schema"] == "handoff_comparison_decision_v1"
    assert current["original_result"] == old["original_result"]
    assert current["read_allowance"] == old["read_allowance"]
    assert current["request"] == old["request"]
    assert read_json(prepared / "control.json")["prefix_trace"] == checkpoint["prefix_trace"]
    assert read_json(prepared / "control.json")["operations"] == checkpoint["operations"]
    assert any(a["id"] == "handoff_select_none" for a in current["initial_actions"])

    executed = []
    execute = EvidenceOperations.execute

    def record_execute(operations, action, state):
        executed.append(action)
        return execute(operations, action, state)

    monkeypatch.setattr(EvidenceOperations, "execute", record_execute)
    policy = {"policy": "rules", "routing": "handoff_only"}
    result = replay_call(prepared, tmp_path / "rule", policy, source_version="current-test")
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["frozen_initial_observation_and_actions_equal"]
    assert result["frozen_request_and_allowance_equal"]
    assert read_json(tmp_path / "rule/replay.json")["comparison_projection"] == (
        current["comparison_projection"])
    assert all(action.kind == "HANDOFF" for action in executed)
    assert {p.relative_to(captured): p.read_bytes()
            for p in captured.rglob("*") if p.is_file()} == saved
    with pytest.raises(ValueError, match="declared version and HANDOFF-only"):
        replay_call(prepared, tmp_path / "wrong-version", policy, source_version="other")
    with pytest.raises(ValueError, match="declared version and HANDOFF-only"):
        replay_call(prepared, tmp_path / "wrong-mode", {"policy": "rules"},
                    source_version="current-test")
    with pytest.raises(ValueError, match="declared version and HANDOFF-only"):
        replay_call(prepared, tmp_path / "wrong-intervention", policy,
            source_version="current-test", intervention={
                "first_action": checkpoint["state"]["last_result"]["action"],
                "continuation_steps": 0})
    current["initial_actions"][0]["target"] = "Changed binding must still be rejected"
    write_json(prepared / "call.json", current)
    failed = replay_call(prepared, tmp_path / "changed-menu", policy, source_version="current-test")
    assert failed["status"] == "FAILED"
    assert failed["error"] == "FROZEN_RETRIEVAL_FIRST_DECISION_CHANGED"
