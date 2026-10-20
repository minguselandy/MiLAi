"""Unknown branches cannot acquire negative targets through a full-option denominator."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from prepare_retrieval_feedback import compile_feedback
from retrieval_feedback import (
    encoding_row,
    feedback_counts,
    pair_loss,
    score_feedback,
    validate_feedback,
)
from train_bounded_laya import training_stages


def example():
    return {
        "state": {"task": "original unchanged request"},
        "questions": {"next": {"criteria": {
            "read": "READ", "handoff": "HANDOFF", "refresh": "REFRESH_VIEW"}}},
        "gold": {},
        "metadata": {"state_id": 4, "family": "source-a"},
        "feedback": {"comparisons": [
            {"left": "read", "right": "handoff", "answer": "tie", "delivery": "left"},
            {"left": "read", "right": "refresh", "answer": "unknown", "delivery": "unknown"},
        ]},
    }


def test_unknown_options_and_padding_have_no_negative_logit_pressure():
    torch = pytest.importorskip("torch")
    row = example()
    logits = torch.tensor([0.5, -0.2, 1000.0, -float("inf")], requires_grad=True)
    loss = pair_loss(logits, list(row["questions"]["next"]["criteria"]),
                     row["feedback"]["comparisons"], "delivery")
    assert loss.item() == pytest.approx(torch.nn.functional.softplus(torch.tensor(-0.7)).item())
    loss.backward()
    assert logits.grad[0] < 0 and logits.grad[1] > 0
    assert logits.grad[2:].tolist() == [0, 0]
    assert torch.isfinite(logits.grad).all()


def test_option_permutations_preserve_pair_loss_and_semantic_gradients():
    torch = pytest.importorskip("torch")
    row = example()
    keys = list(row["questions"]["next"]["criteria"])
    values = [0.4, -0.8, 3.0]
    gradients = []
    for order in ([0, 1, 2], [2, 0, 1], [1, 2, 0]):
        logits = torch.tensor([values[i] for i in order], requires_grad=True)
        loss = pair_loss(logits, [keys[i] for i in order],
                         row["feedback"]["comparisons"], "delivery")
        loss.backward()
        gradients.append({keys[i]: logits.grad[j].item() for j, i in enumerate(order)})
    assert gradients[0] == gradients[1] == gradients[2]


def test_ties_and_unknown_states_remain_in_both_matched_sampling_plans():
    torch = pytest.importorskip("torch")
    rows = [example(), example()]
    rows[1]["feedback"]["comparisons"][0]["delivery"] = "tie"
    plans = []
    for target in ("answer", "delivery"):
        counts = feedback_counts(rows, target)
        assert counts["feedback_states"] == 2
        plans.append(training_stages(len(rows), 1, 7, update_budget=2))
    assert plans[0] == plans[1]
    logits = torch.tensor([0.1, 0.2, 0.3, -float("inf")], requires_grad=True)
    loss = pair_loss(logits, ["read", "handoff", "refresh"],
                     rows[0]["feedback"]["comparisons"], "answer")
    loss.backward()
    assert loss.item() == 0 and logits.grad.tolist() == [0, 0, 0, 0]


def test_codec_targets_do_not_change_saved_labels_or_model_inputs():
    row = example()
    saved = copy.deepcopy(row)
    encoded = encoding_row(row)
    assert row == saved and not row["gold"]
    assert encoded["state"] == row["state"] and encoded["questions"] == row["questions"]
    assert set(encoded["gold"]["next"]["probabilities"]) == {"read", "handoff", "refresh"}
    replay = {**row, "gold": {"next": {"probabilities": {"read": 1}}}}
    del replay["feedback"]
    assert encoding_row(replay) is replay


@pytest.mark.parametrize("mutation", ["missing_action", "duplicate", "invalid_outcome", "ce"])
def test_conflicting_or_unoffered_pair_labels_are_rejected(mutation):
    row = example()
    pair = row["feedback"]["comparisons"][0]
    if mutation == "missing_action":
        pair["right"] = "invented_action"
    elif mutation == "duplicate":
        row["feedback"]["comparisons"].append(dict(pair))
    elif mutation == "invalid_outcome":
        pair["answer"] = "not_reviewed_but_negative"
    else:
        row["gold"] = {"next": {"probabilities": {"read": 1}}}
    with pytest.raises(ValueError):
        validate_feedback(row)


def test_pair_count_does_not_scale_one_states_objective():
    torch = pytest.importorskip("torch")
    row = example()
    logits = torch.tensor([0.4, -0.2, -0.2])
    one = pair_loss(logits, ["read", "handoff", "refresh"],
                    row["feedback"]["comparisons"], "delivery")
    row["feedback"]["comparisons"][1]["delivery"] = "left"
    two = pair_loss(logits, ["read", "handoff", "refresh"],
                    row["feedback"]["comparisons"], "delivery")
    assert one.item() == two.item()
    scored = score_feedback([row], [{"logits": {"read": .4, "handoff": -.2, "refresh": -.2}}],
                            "delivery")
    assert scored["counts"] == {"directional_pairs": 2, "ordered_correctly": 2}


def branch_fixture(tmp_path):
    capture = tmp_path / "captured"
    capture.mkdir()
    actions = [
        {"id": "read", "kind": "READ", "target": "source", "parameters": {"index": 3}},
        {"id": "handoff", "kind": "HANDOFF", "target": "Host", "parameters": {}},
        {"id": "refresh", "kind": "REFRESH_VIEW", "target": "current", "parameters": {}},
    ]
    before = MemoryControlState(task={"request": "Quote the actual statement"}).project()
    (capture / "call.json").write_text(json.dumps(
        {"initial_observation": before, "initial_actions": actions}))
    raw = decision_example({"before": before, "actions": actions},
                           {"event_id": "actual/0", "split": "train", "family": "source-a"})
    cases = []
    for action in actions[:2]:
        case = tmp_path / action["id"]
        (case / "host-readout").mkdir(parents=True)
        (case / "replay.json").write_text(json.dumps({
            "captured_call": str(capture), "status": "COMPLETED",
            "policy": {"policy": "fixed_context", "reads": 4},
            "intervention": {"first_action": action, "continuation_steps": 2},
            "result": {"frozen_initial_observation_and_actions_equal": True},
        }))
        (case / "host-readout/readout.json").write_text(json.dumps({"status": "COMPLETED"}))
        cases.append(case)
    reviews = [{"event_id": "actual/0", "capture": str(capture), "reviewer": "test author",
                "comparisons": [{"left_case": str(cases[0]), "right_case": str(cases[1]),
                                 "answer": "tie", "delivery": "left",
                                 "basis": {"answer": "same content",
                                           "delivery": "actual witness"}}]}]
    return raw, reviews, cases


def test_compile_keeps_actual_input_and_both_feedbacks_in_one_pool(tmp_path):
    raw, reviews, _ = branch_fixture(tmp_path)
    untouched = copy.deepcopy(raw)
    compiled, = compile_feedback([raw], reviews)
    assert raw == untouched
    assert all(compiled[k] == raw[k] for k in ("state", "questions", "gold"))
    pair, = compiled["feedback"]["comparisons"]
    assert (pair["left"], pair["right"], pair["answer"], pair["delivery"]) == (
        "read", "handoff", "tie", "left")
    assert "refresh" in compiled["questions"]["next"]["criteria"]
    assert "refresh" not in {pair["left"], pair["right"]}


@pytest.mark.parametrize("change", ["parameters", "before", "continuation", "source_split"])
def test_changed_experiment_cannot_be_compiled_as_same_state_feedback(tmp_path, change):
    raw, reviews, cases = branch_fixture(tmp_path)
    path = cases[0] / "replay.json"
    replay = json.loads(path.read_text())
    if change == "parameters":
        replay["intervention"]["first_action"]["parameters"]["index"] = 9
    elif change == "before":
        replay["result"]["frozen_initial_observation_and_actions_equal"] = False
    elif change == "continuation":
        replay["intervention"]["continuation_steps"] = 3
    else:
        raw["metadata"]["split"] = "dev"
    path.write_text(json.dumps(replay))
    with pytest.raises(ValueError):
        compile_feedback([raw], reviews)


def test_unfinished_readout_remains_unknown_and_state_is_retained(tmp_path):
    raw, reviews, cases = branch_fixture(tmp_path)
    (cases[0] / "host-readout/readout.json").write_text(json.dumps({"status": "FAILED"}))
    with pytest.raises(ValueError):
        compile_feedback([raw], reviews)
    reviews[0]["comparisons"][0].update(answer="unknown", delivery="unknown")
    compiled = compile_feedback([raw], reviews)
    assert len(compiled) == 1
    assert feedback_counts(compiled, "delivery") == {
        "feedback_states": 1, "states_with_direction": 0, "unknown_pairs": 1}


def test_closed_material_delivery_can_be_reviewed_when_host_readout_failed(tmp_path):
    raw, reviews, cases = branch_fixture(tmp_path)
    (cases[0] / "host-readout/readout.json").write_text(json.dumps({"status": "FAILED"}))
    reviews[0]["comparisons"][0].update(answer="unknown", delivery="left")
    compiled, = compile_feedback([raw], reviews)
    pair, = compiled["feedback"]["comparisons"]
    assert pair["answer"] == "unknown" and pair["delivery"] == "left"
    assert pair["host_readout_statuses"] == ["FAILED", "COMPLETED"]
    assert pair["tool_statuses"] == ["COMPLETED", "COMPLETED"]
