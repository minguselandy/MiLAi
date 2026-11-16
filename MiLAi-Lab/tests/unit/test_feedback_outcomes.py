"""Collected outcomes are reused as collected, never forged into another replay."""
import copy
import json

import pytest

from feedback_outcomes import observed_outcome, paired_outcomes
from milai_lab.harness.artifact_io import write_json
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from prepare_retrieval_feedback import compile_collected_feedback
from quality_feedback import answer_first_counts, validate_quality_pool
from retrieval_feedback import RESOURCE_FIELDS


def artifacts(tmp_path):
    root = tmp_path / "runtime"
    capture = tmp_path / "capture"
    actions = [{"id": "read", "kind": "READ", "target": "original", "parameters": {"index": 0}},
               {"id": "stop", "kind": "HANDOFF", "target": "opened", "parameters": {}}]
    before = MemoryControlState(task={"request": "both facts"}).project()
    public = {"content": "both facts", "message_id": "q"}
    packet = {"evidence": [{"content": "literal fact"}]}
    call = {"call_id": "actual-call", "bank": "bank", "public_message": public,
        "source_root": str(root), "host_result_path": "result.json", "control_step": 2,
        "initial_observation": before, "initial_actions": actions, "original_result": packet,
        "control_events": [{"phase": "decision_output", "step": 2, "selected": "read",
                            "before": before, "actions": actions}],
        "request": {"query": "both facts"}}
    write_json(capture / "call.json", call)
    result = {"status": "COMPLETED", "bank": "bank", **public, "retrieval_result": packet}
    write_json(root / "result.json", result)
    reader = tmp_path / "reader"
    write_json(reader / "readout.json", {"status": "FAILED"})
    write_json(reader / "frame.json", {"schema": "given_request_host_readout_v1",
                                       "call_id": "actual-call"})
    wire = {"model": "fixed", "messages": [{"role": "system", "content": "same system"},
        {"role": "user", "content": json.dumps({"request": "both facts",
            "retrieval_request": call["request"], "memory": packet})}]}
    write_json(reader / "request.json", wire)
    origin = {"kind": "closed_collector_last_decision", "call": str(capture / "call.json"),
              "result": str(root / "result.json"), "readout": str(reader / "readout.json")}
    row = decision_example({"before": before, "actions": actions}, {
        "path": str(capture), "event_id": "event", "split": "train", "row": 0, "family": "paper"})
    return capture, origin, row


def test_real_collected_file_and_failed_reader_remain_an_unknown_outcome(tmp_path):
    capture, origin, _ = artifacts(tmp_path)
    result = observed_outcome(capture, origin)
    assert result["action"]["id"] == "read"
    assert result["tool_status"] == "COMPLETED" and result["readout_status"] == "FAILED"
    assert not (capture / "replay.json").exists()


def test_later_original_decision_prevents_reusing_final_result_for_an_earlier_action(tmp_path):
    capture, origin, _ = artifacts(tmp_path)
    from milai_lab.harness.artifact_io import read_json

    call = read_json(capture / "call.json")
    later = {**call["control_events"][-1], "step": 3, "selected": "stop"}
    call["control_events"].append(later)
    write_json(capture / "call.json", call)
    with pytest.raises(ValueError, match="earlier decision"):
        observed_outcome(capture, origin)


def test_pair_requires_one_fixed_reader_condition_outside_actual_packet(tmp_path, monkeypatch):
    capture, origin, _ = artifacts(tmp_path)
    left = observed_outcome(capture, origin)
    right = copy.deepcopy(left)
    right["action"]["id"] = "stop"
    right["wire"]["messages"][0]["content"] = "Different instruction"
    monkeypatch.setattr("feedback_outcomes.observed_outcome",
                        lambda _, item: left if item["side"] == "left" else right)
    with pytest.raises(ValueError, match="outside the actual"):
        paired_outcomes(capture, {"read": {"side": "left"}, "stop": {"side": "right"}})


def test_compiler_keeps_origin_and_unknown_answer_with_known_delivery(tmp_path, monkeypatch):
    capture, origin, row = artifacts(tmp_path)
    current = observed_outcome(capture, origin)
    baseline = {**copy.deepcopy(current), "action": {
        "id": "stop", "kind": "HANDOFF", "target": "opened", "parameters": {}},
        "readout_status": "COMPLETED"}
    monkeypatch.setattr("prepare_retrieval_feedback.paired_outcomes",
                        lambda *_: {"read": current, "stop": baseline})
    review = {"capture": str(capture), "current_action": current["action"],
        "baseline_action": baseline["action"], "current_origin": origin,
        "baseline_origin": {"kind": "new_same_before_raw_delivery", "case": "branch"},
        "quality_before_resource_tiebreak": {"answer": "unknown", "delivery": "right"},
        "resources": {k: dict.fromkeys(RESOURCE_FIELDS, 0) for k in ("current", "baseline")},
        "target": "both facts", "review": "Source review", "limitation": "First failure retained",
        "reviewer": "test author", "pure_delivery": False}
    original = copy.deepcopy(row)
    compiled, = compile_collected_feedback([row], [review])
    assert row == original and compiled["gold"] == {}
    validate_quality_pool([compiled])
    assert compiled["feedback"]["outcomes"]["read"] == origin
    assert compiled["feedback"]["comparisons"][0]["answer"] == "unknown"
    assert answer_first_counts([compiled])["components"]["delivery_auxiliary"]["pairs"] == 1
    review["quality_before_resource_tiebreak"]["answer"] = "right"
    with pytest.raises(ValueError, match="incomplete final answer"):
        compile_collected_feedback([row], [review])
