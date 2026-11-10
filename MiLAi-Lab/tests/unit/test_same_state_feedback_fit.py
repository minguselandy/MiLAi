"""Keep model inputs, option seeds and source/component masses matched across objectives."""

import copy

import pytest

from prepare_same_state_feedback_fit import prepare


def row(event, family, state_id, split="train"):
    return {
        "state": {"request": event},
        "questions": {"next": {"type": "choice", "criteria": {"a": "READ", "b": "HANDOFF"}}},
        "gold": {"next": {"probabilities": {"b": 1}}},
        "metadata": {
            "event_id": event,
            "family": family,
            "split": split,
            "row": event,
            "training_event": event,
            "state_id": state_id,
            "action_parameters": {"a": {"index": 0}, "b": {}},
        },
    }


def fixture():
    sft = [row("new0", "new", 0), row("new1", "new", 1)]
    feedback = copy.deepcopy(sft)
    for item in feedback:
        item["gold"] = {}
        item["feedback"] = {
            "comparisons": [{"left": "a", "right": "b", "answer": "unknown", "delivery": "left"}]
        }
        item["metadata"]["feedback_rollout"] = {
            "policy": "fixed_context",
            "steps": 4,
            "terminal_handoff": "policy",
        }
    old = [
        row("o0", "old_a", 0),
        row("o1", "old_a", 1),
        row("o2", "old_b", 2),
        row("o3", "old_c", 3),
    ]
    dev = [row("dev0", "dev", 100, "dev")]
    return (
        feedback,
        sft,
        old,
        dev,
        {"o0": 10, "o1": 11, "o2": 100, "o3": 13},
        {"new0": 10, "new1": 11},
    )


def test_full_input_source_sampling_and_loss_mass_match_without_mutating_inputs():
    inputs = fixture()
    before = copy.deepcopy(inputs)
    data, report = prepare(*inputs, seed=0)
    assert inputs == before
    assert report["new_family_overlap_with_old_pool"] == []
    assert len({r["metadata"]["family"] for r in data["feedback"][2:]}) == 2
    for a, b in zip(data["feedback"], data["continued-sft"], strict=True):
        assert a["state"] == b["state"] and a["questions"] == b["questions"]
        assert a["metadata"]["state_id"] == b["metadata"]["state_id"]
    assert data["feedback"][0]["metadata"]["state_id"] == 101
    weights = report["weights_both_arms"]
    assert sum(weights[:2]) / len(weights) == pytest.approx(0.8)
    assert sum(weights[2:]) / len(weights) == pytest.approx(0.2)
    assert data["feedback"][2:] == data["continued-sft"][2:]


def test_rejects_changed_binding_and_mixed_feedback_horizons():
    args = fixture()
    args[1][0]["metadata"]["action_parameters"]["a"]["index"] = 99
    with pytest.raises(ValueError, match="full menu"):
        prepare(*args, seed=0)
    args = fixture()
    args[0][1]["metadata"]["feedback_rollout"]["steps"] = 2
    with pytest.raises(ValueError, match="conditions separate"):
        prepare(*args, seed=0)
