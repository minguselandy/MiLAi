"""Actual choices preserve parameters, unknown outcomes, and saved input identity."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from analyze_feedback_choices import executed_outcomes
from feedback_choices import (
    baseline_choice,
    captured_decisions,
    decision_actions,
    full_menu_choice,
    relative_quality,
    saved_decisions,
    summarize_choices,
)
from milai_lab.harness.artifact_io import write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from prepare_view_feedback_branches import main


def menu():
    return [{"id": key, "kind": "READ", "target": "source", "parameters": parameters}
        for key, parameters in (("read", {"index": 0}),
                                ("observe", {"index": 0, "observe_only": True}),
                                ("range", {"index": 0, "ranges": [[20, 40]]}))]


def test_full_argmax_observe_and_other_read_parameters_are_not_collapsed():
    actions = menu()
    call = {"initial_actions": actions}
    selected = decision_actions(call, {"read": 2., "observe": 4., "range": 3.}, "read", ["range"])
    assert [a["id"] for a in selected] == ["observe", "read", "range"]
    selected[0]["parameters"]["index"] = 99
    assert actions[1]["parameters"]["index"] == 0


def test_raw_delivery_baseline_uses_only_current_handoff_bindings():
    call = {"initial_observation": MemoryControlState(task={"request": "both facts"},
        visible_evidence=[{"content": "one"}, {"content": "two"}]).project(),
        "initial_actions": [
            {"id": "search", "kind": "SEARCH", "target": "query", "parameters": {}},
            {"id": "one", "kind": "HANDOFF", "target": "selected",
             "parameters": {"delivery_indices": [0]}},
            {"id": "all", "kind": "HANDOFF", "target": "opened", "parameters": {}}]}
    assert baseline_choice(call, "raw_context", 4) == "search"
    assert baseline_choice(call, "raw_delivery", 4) == "all"


def test_fixed_prefix_baseline_retains_retrieval_order_and_exact_read_parameters():
    state = MemoryControlState(task={"request": "read"}, budget={"remaining_steps": 3})
    actions = [
        {"id": "read", "kind": "READ", "target": "candidate0", "parameters": {"index": 0}},
        {"id": "context", "kind": "READ", "target": "candidate1",
         "parameters": {"index": 1, "expand_context": True}},
        {"id": "handoff", "kind": "HANDOFF", "target": "reader", "parameters": {}}]
    call = {"initial_observation": state.project(), "initial_actions": actions}
    assert baseline_choice(call, "raw_context", 4) == "context"
    selected = baseline_choice(call, "fixed_prefix", 4)
    assert selected == "read"
    choices = decision_actions(call, {"read": 0., "context": 1., "handoff": -1.}, selected)
    assert [a["parameters"] for a in choices] == [{"index": 1, "expand_context": True},
                                                {"index": 0}]


def test_same_executable_binding_runs_once_without_filling_three_slots():
    action = menu()[0]
    actions = [action, {**copy.deepcopy(action), "id": "alias"}]
    selected = decision_actions({"initial_actions": actions}, {"read": 1., "alias": 2.}, "read")
    assert selected == [actions[1]]


def test_logits_require_full_menu_and_ties_follow_offered_order():
    assert full_menu_choice(menu(), {"range": 2., "observe": 2., "read": 2.}) == "read"
    with pytest.raises(ValueError, match="complete actual menu"):
        full_menu_choice(menu(), {"read": 1.})


def test_unexecuted_binding_of_same_kind_stays_unknown_and_cost_is_not_quality():
    row = {"feedback": {"comparisons": [{"left": "read", "right": "range",
        "answer": "left", "basis": {"quality_before_resource_tiebreak": {
            "answer": "tie", "delivery": "unknown"}}}]}}
    executed = {"read", "range"}
    assert relative_quality(row, "observe", "read", "answer", executed) == "unknown"
    assert relative_quality(row, "range", "read", "answer", executed) == "tie"
    assert relative_quality(row, "range", "read", "delivery", executed) == "unknown"
    assert relative_quality(row, "observe", "observe", "answer", executed) == "unknown"
    assert relative_quality(row, "read", "read", "answer", executed) == "same_binding"


def evaluation_fixture(tmp_path, *, singleton=False):
    root = tmp_path / "collection"
    capture = root / "frozen-retrieval-calls" / "capture"
    actions = [{"id": "stop", "kind": "HANDOFF", "target": "Host", "parameters": {}}]
    if not singleton:
        actions = menu() + actions
    call = {"initial_observation": MemoryControlState(task={"request": "read"}).project(),
        "initial_actions": actions, "bank": "history-request", "source_root": str(root),
        "request": {}, "public_message": {"message_id": "message"}, "status": "ORIGINAL_COMPLETED"}
    write_json(capture / "call.json", call)
    write_json(root / "driver.json", {"status": "COMPLETED", "source_version": "test-source"})
    write_json(root / "fixture.json", {"histories": [{"id": "history", "source_group": "family",
        "split": "train", "requests": [{"id": "request"}]}]})
    row = decision_example({"before": call["initial_observation"], "actions": actions},
                           {"path": str(capture), "capture": "capture"})
    row = project_operation_payload(row, "shared_actions")
    data = tmp_path / "data.jsonl"
    data.write_text(json.dumps(row) + "\n")
    evaluation = tmp_path / "evaluation"
    write_json(evaluation / "run.json", {"status": "COMPLETED", "data": str(data),
        "checkpoint": "saved-checkpoint", "completed_states": 1,
        "operation_state": "shared_actions"})
    write_json(evaluation / "calls/0/input.json", {k: row[k] for k in ("state", "questions")})
    write_json(evaluation / "calls/0/output.json", {"logits": {
        a["id"]: float(i) for i, a in enumerate(actions)}, "choice": "stop"})
    return root, evaluation


def test_saved_input_binds_complete_state_menu_and_literal_model_prompt(tmp_path):
    _, evaluation = evaluation_fixture(tmp_path)
    _, decisions = saved_decisions(evaluation)
    assert len(decisions) == 1
    input_path = evaluation / "calls/0/input.json"
    payload = json.loads(input_path.read_text())
    payload["questions"]["next"]["instructions"] = "changed condition"
    write_json(input_path, payload)
    with pytest.raises(ValueError, match="different literal model inputs"):
        saved_decisions(evaluation)


def captured_score_fixture(tmp_path):
    root, evaluation = evaluation_fixture(tmp_path)
    capture = root / "frozen-retrieval-calls/capture"
    call = json.loads((capture / "call.json").read_text())
    prediction = json.loads((evaluation / "calls/0/output.json").read_text())
    call.update(call_id="actual-call", host_prefix_trace="trace.jsonl", control_events=[{
        "phase": "decision_output", "step": 0, "selected": prediction["choice"],
        "before": call["initial_observation"], "actions": call["initial_actions"]}])
    write_json(capture / "call.json", call)
    write_json(root / "input-freeze.json", {"config": {"memory_control": {
        "policy": "laya", "checkpoint": "saved-checkpoint", "state_projection": "shared_actions"}}})
    event = {"event": "memory_control_model_result", "result": prediction,
             "input": json.loads((evaluation / "calls/0/input.json").read_text())}
    (root / "trace.jsonl").write_text(json.dumps(event) + "\n")
    return root, capture


def test_captured_logits_are_reused_only_for_the_same_menu_state_and_executed_choice(tmp_path):
    root, capture = captured_score_fixture(tmp_path)
    info, scores = captured_decisions(root)
    assert info["score_origin"] == "actual_closed_policy_trace"
    assert scores[str(capture.resolve())]["prediction"]["choice"] == "stop"
    call = json.loads((capture / "call.json").read_text())
    call["control_events"][0]["selected"] = "read"
    write_json(capture / "call.json", call)
    with pytest.raises(ValueError, match="action actually chosen"):
        captured_decisions(root)


def test_missing_model_score_is_not_reconstructed_from_action_type_or_other_state(tmp_path):
    root, _ = captured_score_fixture(tmp_path)
    event = json.loads((root / "trace.jsonl").read_text())
    event["input"]["questions"]["next"]["instructions"] = "Different input condition"
    (root / "trace.jsonl").write_text(json.dumps(event) + "\n")
    info, scores = captured_decisions(root)
    assert not scores and len(info["unscored"]) == 1


def test_current_decision_cli_can_use_actual_collector_scores_without_an_evaluation(tmp_path,
                                                                                monkeypatch):
    root, _ = captured_score_fixture(tmp_path)
    output = tmp_path / "branches"
    monkeypatch.setattr(sys, "argv", ["prepare_view_feedback_branches", str(root),
        "--groups", "family", "--branch-sampling", "current-decision",
        "--decision-collection", str(root), "--output", str(output)])
    main()
    selection = json.loads((output / "selection.json").read_text())
    assert selection["score_origin"] == "actual_closed_policy_trace"
    assert selection["decision_nominations"][0]["argmax"] == "stop"
    assert selection["decision_evaluation"] is None


@pytest.mark.parametrize("singleton", [False, True])
def test_current_decision_cli_preserves_singleton_and_emits_actual_argmax(tmp_path, monkeypatch,
                                                                       singleton):
    root, evaluation = evaluation_fixture(tmp_path, singleton=singleton)
    output = tmp_path / "branches"
    monkeypatch.setattr(sys, "argv", ["prepare_view_feedback_branches", str(root),
        "--groups", "family", "--branch-sampling", "current-decision",
        "--decision-evaluation", str(evaluation), "--output", str(output)])
    main()
    selection = json.loads((output / "selection.json").read_text())
    nomination, = selection["decision_nominations"]
    assert nomination["argmax"] == "stop"
    assert nomination["has_comparison"] is not singleton
    assert selection["branches"] == (1 if singleton else 2)
    policies = json.loads((output / "policies.json").read_text())
    assert policies[0]["intervention"]["first_action"]["id"] == "stop"
    row = json.loads((output / "raw-selected-states.jsonl").read_text())
    assert {k: row[k] for k in ("state", "questions")} == json.loads(
        (evaluation / "calls/0/input.json").read_text())


def test_unknown_states_remain_in_denominator_without_numeric_gain():
    rows = [{"family": "family", "full_menu_executed": False, "baseline_executed": True,
        "full_menu_readout_completed": False,
        "quality_vs_baseline": {t: {k: "unknown" for k in (
            "full_menu", "executed_submenu", "fixed_type_order")} for t in ("answer", "delivery")},
        "observed_improvement_space": {t: "unknown" for t in ("answer", "delivery")}}]
    report = summarize_choices(rows)
    assert report["states"] == 1
    assert report["targets"]["answer"]["comparisons"]["full_menu"][
        "conditional_family_macro_signed_preference"] is None


def test_failed_readout_is_retained_but_different_before_state_is_not_comparable(tmp_path):
    actions = menu()[:2]
    cases = [tmp_path / str(i) for i in range(2)]
    row = {"feedback": {"comparisons": [{"left": "read", "right": "observe",
        "left_case": str(cases[0]), "right_case": str(cases[1])}]}}
    for action, path in zip(actions, cases, strict=True):
        write_json(path / "replay.json", {"status": "COMPLETED",
            "intervention": {"first_action": action, "continuation_steps": 2},
            "policy": {"policy": "fixed_context", "reads": 4},
            "result": {"frozen_request_and_allowance_equal": True,
                       "frozen_initial_observation_and_actions_equal": True}})
        write_json(path / "host-readout/readout.json", {"status": "FAILED"})
        write_json(path / "host-readout/frame.json", {"call_id": "same-call"})
    call = {"initial_actions": actions, "call_id": "same-call"}
    assert executed_outcomes(row, call)["observe"]["readout_status"] == "FAILED"
    path = cases[1] / "replay.json"
    replay = json.loads(path.read_text())
    replay["result"]["frozen_initial_observation_and_actions_equal"] = False
    write_json(path, replay)
    with pytest.raises(ValueError, match="captured before state"):
        executed_outcomes(row, call)


def test_current_decision_does_not_silently_replace_prefix_protocol(tmp_path, monkeypatch):
    root, evaluation = evaluation_fixture(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prepare_view_feedback_branches", str(root),
        "--groups", "family", "--branch-sampling", "current-decision",
        "--decision-evaluation", str(evaluation), "--prefix-selection", "existing-prefix.json",
        "--output", str(tmp_path / "new")])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
