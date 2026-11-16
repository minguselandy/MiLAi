"""No new acquisition, information, protocol marker, or default change in the F1 variant."""

import copy
import sys

import httpx
import pytest
from test_given_retrieval import no_http, prepared_given

from current_raw_packet_tie import current_raw_packet_tie, current_raw_tie_choice
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods import memory_control
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.runners.frozen_retrieval import replay_call
from milai_lab.runners.functional import message


def raw(label, text):
    return {"kind": "original_source", "label": label,
            "evidence": [{"role": "tool", "content": text}]}


def example():
    first = raw("e0", "Cedar code")
    second = raw("e1", "Cedar code with another complementary reported part")
    state = MemoryControlState(task={"request": "Cedar code", "read_goal": {
        "evidence": ["original_source"], "required_points": ["Cedar code"]}},
        visible_evidence=[first, second], observed_materials=[],
        budget={"remaining_control_steps": 1})
    actions = [MemoryAction("current", "HANDOFF", "current"),
               MemoryAction("short", "HANDOFF", "selected", {"delivery_indices": [0]})]
    return state, actions


def test_exact_tie_preserves_raw_packet_only_inside_the_declared_context():
    state, actions = example()
    before = copy.deepcopy(state.project())
    original = memory_control.original_evidence_action
    assert original(state, actions, 4) == "short"
    rows = []
    with current_raw_packet_tie(rows.append):
        assert memory_control.original_evidence_action(state, actions, 4) == "current"
    assert memory_control.original_evidence_action is original
    assert original(state, actions, 4) == "short" and state.project() == before
    assert rows[0]["changed"] and rows[0]["baseline_coverage"] == rows[0]["current_coverage"]


def test_mixed_view_empty_current_and_unstructured_request_keep_the_original_route():
    state, actions = example()
    state.visible_evidence.append({"kind": "query_structure", "label": "e2",
                                   "interpretation": "Uncertified generated content"})
    with current_raw_packet_tie(lambda _: None):
        assert memory_control.original_evidence_action(state, actions, 4) == "short"
    state, actions = example()
    state.observed_evidence = state.visible_evidence
    state.visible_evidence = []
    chosen, info = current_raw_tie_choice(state, actions, "short")
    assert chosen == "short" and not info["changed"]
    state.task["read_goal"]["evidence"] = ["current_interpretation"]
    with current_raw_packet_tie(lambda _: None):
        assert memory_control.original_evidence_action(state, actions, 4) is None


def test_strictly_better_coverage_and_scope_rejection_do_not_become_current_preference():
    state, actions = example()
    state.task["read_goal"]["required_points"] = ["Cedar code bonus"]
    state.visible_evidence = [raw("e0", "Cedar code")]
    state.observed_evidence = [raw("e1", "Cedar code bonus")]
    actions[1] = MemoryAction("better", "HANDOFF", "selected", {"delivery_indices": [1]})
    with current_raw_packet_tie(lambda _: None):
        assert memory_control.original_evidence_action(state, actions, 4) == "better"
    original = memory_control.original_evidence_action
    with pytest.raises(ValueError, match="HANDOFF-only"):
        with current_raw_packet_tie(lambda _: None):
            memory_control.original_evidence_action(
                state, [*actions, MemoryAction("read", "READ", "candidate")], 4)
    assert memory_control.original_evidence_action is original


def test_actual_replay_keeps_before_allowance_and_ordinary_handoff_without_new_read(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "reads": 2,
        "max_control_steps": 8, "delivery_selection": True})
    monkeypatch.setattr(httpx.Client, "send", no_http)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="Find the complete Cedar code", incoming_sources=[{
            "session_id": f"reference-{i}", "event_key": f"part-{i}", "role": "tool",
            "origin": "reference_document", "content": f"Cedar code part {i} is {part}."}
            for i, part in enumerate(["43", "12"])],
        given_retrieval_request={"query": "Cedar code", "read_goal": {
            "evidence": ["original_source"], "required_points": ["Cedar code"]}},
        retrieval_snapshots=captures, retrieval_step_snapshots=True)
    assert result["status"] == "COMPLETED"
    candidates = [p.parent for p in captures.glob("*/steps/*/call.json")
                  if len(read_json(p)["initial_observation"]["visible_evidence"]) == 2]
    captured = sorted(candidates, key=lambda p: read_json(p / "call.json")["control_step"])[-1]
    old = {p.relative_to(captured): p.read_bytes() for p in captured.rglob("*") if p.is_file()}
    config = {"policy": "rules", "routing": "handoff_only", "reads": 4}
    baseline = replay_call(captured, tmp_path / "baseline", config, source_version="mechanical")
    records = []
    with current_raw_packet_tie(records.append):
        variant = replay_call(captured, tmp_path / "variant", config, source_version="mechanical")
    assert baseline["status"] == variant["status"] == "COMPLETED"
    assert len(baseline["retrieval_result"]["evidence"]) == 1
    assert len(variant["retrieval_result"]["evidence"]) == 2
    assert records[0]["changed"]
    for result, name in ((baseline, "baseline"), (variant, "variant")):
        assert result["frozen_initial_observation_and_actions_equal"]
        assert result["frozen_request_and_allowance_equal"]
        assert result["retrieval_result"]["termination_reason"] == "policy_handoff"
        report = read_json(tmp_path / name / "replay.json")
        assert "intervention" not in report and report["prefix_operations_reexecuted"] == 0
        assert result["retrieval_result"]["usage"]["read_operations"] == (
            report["restored_prefix_usage"]["read_operations"])
    assert old == {p.relative_to(captured): p.read_bytes()
                   for p in captured.rglob("*") if p.is_file()}


@pytest.mark.parametrize("policy,intervention", [("laya", False), ("rules", True)])
def test_cli_rejects_scorer_or_intervention_recipes_before_entry(
    tmp_path, monkeypatch, policy, intervention,
):
    import run_current_raw_packet_tie

    entry = tmp_path / "run_frozen_retrieval_calls.py"
    entry.write_text('raise AssertionError("entry must not execute")\n')
    recipes = [{"policy": {"policy": policy, "routing": "handoff_only"},
                **({"intervention": {}} if intervention else {})}]
    policy_file = tmp_path / "policies.json"
    write_json(policy_file, recipes)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(sys, "argv", ["wrapper", str(receipt), str(entry),
                                     str(tmp_path / "captures"), str(policy_file), "out"])
    with pytest.raises(ValueError, match="ordinary rules/HANDOFF"):
        run_current_raw_packet_tie.main()
    assert not receipt.exists()


def test_cli_installs_declared_policy_records_it_and_restores_binding(tmp_path, monkeypatch):
    import run_current_raw_packet_tie

    entry = tmp_path / "run_frozen_retrieval_calls.py"
    entry.write_text('''from milai_lab.methods.memory_control import (
    MemoryAction, MemoryControlState, RulesMemoryPolicy)
raw=lambda label,text:{"kind":"original_source","label":label,
                       "evidence":[{"role":"tool","content":text}]}
state=MemoryControlState(task={"request":"Cedar code","read_goal":{
    "evidence":["original_source"],"required_points":["Cedar code"]}},
    visible_evidence=[raw("e0","Cedar code"),raw("e1","Cedar code complementary part")],
    observed_materials=[],budget={"remaining_control_steps":1})
actions=[MemoryAction("current","HANDOFF","current"),
         MemoryAction("short","HANDOFF","selected",{"delivery_indices":[0]})]
assert RulesMemoryPolicy().choose(state,actions)=="current"
''')
    policies = tmp_path / "policies.json"
    write_json(policies, [{"policy": {"policy": "rules", "routing": "handoff_only"}}])
    receipt = tmp_path / "receipt.json"
    argv = ["wrapper", str(receipt), str(entry), "captures", str(policies), "out"]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(sys, "path", sys.path[:])
    original = memory_control.original_evidence_action
    run_current_raw_packet_tie.main()
    report = read_json(receipt)
    assert report["status"] == "COMPLETED" and report["selector_restored"]
    assert not report["intervention_used"] and len(report["policy_calls"]) == 1
    assert report["policy_calls"][0]["baseline"] == "short"
    assert report["policy_calls"][0]["selected"] == "current"
    assert memory_control.original_evidence_action is original and sys.argv == argv
