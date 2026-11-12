"""Whole-trajectory task review preserves event and first-response identity."""
import copy

import pytest

from prepare_trajectory_outcome_review import group_endpoints


def endpoint(method, step, status="COMPLETED"):
    return {"event_id": f"paper/q/step-{step}", "family": "paper", "question": "Public task",
            "native_control": {"native_question_id": "native-q", "split": "dev"},
            "branches": [{"action": {"id": "handoff", "kind": "HANDOFF", "parameters": {}},
                          "readout": f"/{method}/first.json", "readout_status": status,
                          "answer": None if status == "FAILED" else "Answer"}]}


def test_equal_action_ids_are_distinct_trajectories_and_failure_is_retained():
    a, b = endpoint("a", 2), endpoint("b", 7, "FAILED")
    cases, bindings = group_endpoints({"a": [a], "b": [b]})
    assert len(cases) == 1 and len(cases[0]["branches"]) == 2
    assert cases[0]["branches"][1]["readout_status"] == "FAILED"
    assert bindings["/a/first.json"]["original_event_id"] == "paper/q/step-2"
    assert bindings["/b/first.json"]["original_event_id"] == "paper/q/step-7"
    assert "before" not in cases[0]  # No fictional shared controller state.
    assert a == endpoint("a", 2) and b == endpoint("b", 7, "FAILED")


def test_native_task_or_role_cannot_be_silently_relabelled():
    a, b = endpoint("a", 2), endpoint("b", 3)
    wrong = copy.deepcopy(b)
    wrong["native_control"]["native_question_id"] = "other-q"
    with pytest.raises(ValueError, match="same ordered"):
        group_endpoints({"a": [a], "b": [wrong]})
    wrong = copy.deepcopy(b)
    wrong["native_control"]["split"] = "train"
    with pytest.raises(ValueError, match="DEV"):
        group_endpoints({"a": [a], "b": [wrong]})

