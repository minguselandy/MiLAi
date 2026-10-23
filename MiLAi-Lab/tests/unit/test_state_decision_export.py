"""Actual failed decisions remain masked; source groups and branch identities stay explicit."""
import copy
import json

import pytest
from langgraph.store.sqlite import SqliteStore
from test_retrieval_feedback import branch_fixture
from test_state_retrieval_capture import setup_capture

from export_host_intent_states import export_state_states, state_source_groups
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace
from milai_lab.methods.memory_control import FixedMemoryPolicy
from prepare_retrieval_feedback import compile_feedback


def test_actual_failed_prediction_state_and_full_bindings_export_without_teacher_labels(tmp_path):
    trace = Trace(tmp_path / "trace.jsonl", "export-test")

    class FailAfterRead:
        def choose(self, state, actions):
            if state.last_result and state.last_result["action"]["kind"] == "READ":
                raise RuntimeError("prediction capacity failed")
            return FixedMemoryPolicy().choose(state, actions)

    with SqliteStore.from_conn_string(str(tmp_path / "live.sqlite")) as store:
        _, hook, _, _, _ = setup_capture(store, tmp_path)
        hook.memory.control_record = trace
        hook.memory.control_policy = FailAfterRead()
        with pytest.raises(RuntimeError, match="capacity failed"):
            hook.retrieve({"query": "Cancellation"})
    run = {"status": "FAILED", "error": "prediction capacity failed", "split": "train",
        "memory_protocol": "dynamic", "memory_policy": "scripted", "source_version": "test",
        "task_id": "task", "source_selection": {"domain": "travel", "task_id": "task",
                                               "memory_trajectory_ids": ["history"]}}
    rows = export_state_states(tmp_path, run, "one-connected-group")
    inputs = [json.loads(line) for line in trace.path.read_text().splitlines()
              if json.loads(line).get("phase") == "decision_input"]
    assert len(rows) == len(inputs) >= 3
    assert all(row["gold"] == {} and "feedback" not in row for row in rows)
    assert rows[-1]["metadata"]["decision_status"] == "selection_not_returned"
    assert "selected_action" not in rows[-1]["metadata"]
    assert rows[-1]["metadata"]["capture_status"] == "ORIGINAL_FAILED"
    assert rows[-1]["metadata"]["task_status"] == "FAILED"
    assert any(row["metadata"].get("operation_result", {}).get("status") == "opened"
               for row in rows)
    for row, actual in zip(rows, inputs, strict=True):
        assert row["metadata"]["actual_bindings"]["candidate_materials"] == actual[
            "candidate_materials"]
        assert row["metadata"]["action_parameters"] == {
            action["id"]: action["parameters"] for action in actual["actions"]}
    invalid = {**run, "status": "RUNNING"}
    with pytest.raises(ValueError, match="closed task"):
        export_state_states(tmp_path, invalid, "one-connected-group")


def test_state_grouping_merges_transitive_shared_task_history_identities(tmp_path):
    runs = [(tmp_path / str(i), {"source_selection": {"domain": domain, "task_id": task,
        "memory_trajectory_ids": histories}}) for i, (domain, task, histories) in enumerate([
            ("travel", "a", ["b"]), ("travel", "c", ["d"]), ("travel", "b", ["c"]),
            ("retail", "a", ["b"])])]
    original = copy.deepcopy(runs)
    groups = state_source_groups(runs)
    assert len(set(groups.values())) == 2
    assert len({groups[str(path.resolve())] for path, _ in runs[:3]}) == 1
    assert runs == original


def test_zero_decision_call_stays_in_inventory_without_a_fabricated_state(tmp_path, monkeypatch):
    import export_host_intent_states as cli

    root = tmp_path / "run"
    root.mkdir()
    trace = Trace(root / "trace.jsonl", "export-test")
    with SqliteStore.from_conn_string(str(root / "live.sqlite")) as store:
        _, hook, _, _, _ = setup_capture(store, root, control_steps=0)
        hook.memory.control_record = trace
        hook.retrieve({"query": "Cancellation"})
    write_json(root / "run.json", {"status": "COMPLETED_RESEARCH_TRAJECTORY", "split": "train",
        "memory_protocol": "dynamic", "memory_policy": "fixed", "source_version": "test",
        "task_id": "task", "source_selection": {"domain": "travel", "task_id": "task",
                                                "memory_trajectory_ids": ["history"]}})
    monkeypatch.setattr("sys.argv", ["export", str(root), "--protocol", "state_dynamic",
        "--output", str(tmp_path / "output")])
    cli.main()
    report = read_json(tmp_path / "output/export.json")
    assert report["states"] == report["labelled"] == 0
    assert report["captured_calls"] == report["calls_without_decisions"] == 1
    assert report["registered_source_groups"] == 1
    assert (tmp_path / "output/train.jsonl").read_text() == ""


def state_branch_fixture(tmp_path):
    raw, reviews, cases = branch_fixture(tmp_path)
    capture = tmp_path / "captured/call.json"
    call = read_json(capture)
    call["schema"] = "state_dynamic_retrieval_decision_v1"
    write_json(capture, call)
    for case in cases:
        old = read_json(case / "replay.json")
        write_json(case / "retrieval/replay.json", {
            "status": old["status"], "captured_call": old["captured_call"],
            "intervention": old["intervention"], "frozen_request_and_allowance_equal": True,
            "frozen_initial_observation_and_actions_equal": True})
        write_json(case / "run.json", {"recipe": {"policy": old["policy"],
                                                  "intervention": old["intervention"]}})
        (case / "replay.json").unlink()
    return raw, reviews, cases


def test_state_pairs_use_actual_layout_and_preserve_unknown_states(tmp_path):
    raw, reviews, _ = state_branch_fixture(tmp_path)
    reviews[0]["comparisons"][0].update(answer="unknown", delivery="unknown")
    compiled, = compile_feedback([raw], reviews)
    assert compiled["state"] == raw["state"] and compiled["questions"] == raw["questions"]
    assert compiled["gold"] == {}
    comparison, = compiled["feedback"]["comparisons"]
    assert comparison["answer"] == comparison["delivery"] == "unknown"
    assert comparison["tool_statuses"] == comparison["host_readout_statuses"] == [
        "COMPLETED", "COMPLETED"]


@pytest.mark.parametrize("field", ["frozen_request_and_allowance_equal",
                                    "frozen_initial_observation_and_actions_equal", "intervention"])
def test_state_pair_rejects_changed_actual_execution_condition(tmp_path, field):
    raw, reviews, cases = state_branch_fixture(tmp_path)
    path = cases[0] / "retrieval/replay.json"
    branch = read_json(path)
    if field == "intervention":
        branch[field]["continuation_steps"] += 1
    else:
        branch[field] = False
    write_json(path, branch)
    with pytest.raises(ValueError):
        compile_feedback([raw], reviews)
