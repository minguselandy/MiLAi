"""Matched feedback/control preparation retains masks, original rows and source splits."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_feedback_training import prepare


def fixture():
    old = [{"state": {"text": f"Old input {i}"},
            "questions": {"next": {"criteria": {"read": "READ", "handoff": "HANDOFF"}}},
            "gold": {"next": {"probabilities": {"read": 1}}},
            "metadata": {"event_id": f"old-{i}", "family": f"family-{i}", "row": i,
                         "state_id": i, "split": "train", "task": "memory_operation",
                         "component": "history" if i < 8 else "complementary"}}
           for i in range(12)]
    dev = [{**copy.deepcopy(old[0]), "metadata": {**old[0]["metadata"],
            "event_id": "dev-0", "family": "held-dev", "split": "dev", "state_id": 12}}]
    feedback = [{"state": {"text": f"Actual new before {i}"},
                 "questions": copy.deepcopy(old[0]["questions"]), "gold": {},
                 "metadata": {"event_id": f"new-{i}", "family": "own-source", "row": i,
                              "split": "train"},
                 "feedback": {"comparisons": [{"left": "read", "right": "handoff",
                     "answer": "tie", "delivery": "left" if i == 0 else "unknown"}]}}
                for i in range(3)]
    return old, dev, feedback


def build(old, dev, feedback):
    return prepare(old, dev, feedback,
        {row["metadata"]["event_id"]: 100 + 10 * i for i, row in enumerate(old)},
        {row["metadata"]["event_id"]: 130 for row in feedback},
        {"history": .75, "complementary": .25}, 0)


def test_shared_pool_and_old_only_control_match_draws_without_deleting_ties_unknowns():
    old, dev, feedback = fixture()
    originals = copy.deepcopy((old, dev, feedback))
    data, report = build(old, dev, feedback)
    assert (old, dev, feedback) == originals
    assert len(data["feedback"]) == len(data["continued-ce"]) == 6
    assert data["dev"] == dev
    assert data["feedback"][3:] == data["continued-ce"][3:]
    assert all(row in old for row in data["continued-ce"])
    assert len({r["metadata"]["event_id"] for r in data["continued-ce"]}) == 6
    for source, new in zip(feedback, data["feedback"][:3], strict=True):
        assert all(source[k] == new[k] for k in ("state", "questions", "gold", "feedback"))
        assert new["metadata"]["state_id"] > 12
    assert report["optimizer_updates"] == 1 and report["row_draws_each_arm"] == 16
    assert report["feedback"]["answer"]["tie_pairs"] == 3
    assert report["feedback"]["delivery"]["unknown_pairs"] == 2
    assert build(old, dev, feedback) == (data, report)


def test_dev_family_cannot_be_relabelled_as_new_training_feedback():
    old, dev, feedback = fixture()
    feedback[0]["metadata"]["family"] = "held-dev"
    with pytest.raises(ValueError, match="overlaps development"):
        build(old, dev, feedback)


def test_declared_dev_rows_are_not_admitted_to_replay_or_feedback():
    old, dev, feedback = fixture()
    old[0]["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="training-source"):
        build(old, dev, feedback)
