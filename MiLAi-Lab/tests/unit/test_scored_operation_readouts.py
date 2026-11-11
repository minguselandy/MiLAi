"""Scored full actions may continue acquisition; exact before and arguments remain bound."""

import copy
from dataclasses import asdict

import pytest

from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from prepare_scored_operation_readouts import bind_choice


def fixture():
    state = MemoryControlState(
        task={"request": "q", "retrieval_request": {"query": "q"}},
        observed_materials=[],
        observed_evidence=[],
        retrieved_scopes=[],
    )
    actions = [
        MemoryAction("read", "READ", "candidate", {"index": 3}),
        MemoryAction("handoff", "HANDOFF", "current"),
    ]
    case = {
        "before": state.project(),
        "actions": [asdict(a) for a in actions],
        "event_id": "f/q/step-1",
        "branches": [{"action": asdict(actions[1])}],
    }
    row = decision_example(case, {"event_id": case["event_id"]})
    projected = project_operation_payload(row, "shared_actions")
    actual = {k: projected[k] for k in ("state", "questions")}
    return row, case, actual, {"choice": "read", "logits": {"read": 3.0, "handoff": 1.0}}


def test_full_choice_can_select_an_unexecuted_read_instead_of_forcing_handoff():
    row, case, actual, prediction = fixture()
    assert bind_choice(row, case, "shared_actions", actual, prediction) == "read"
    assert [b["action"]["id"] for b in case["branches"]] == ["handoff"]


def test_changed_parameters_or_saved_input_do_not_reuse_an_incompatible_score():
    row, case, actual, prediction = fixture()
    changed = copy.deepcopy(case)
    changed["actions"][0]["parameters"]["index"] = 8
    with pytest.raises(ValueError, match="complete action bindings"):
        bind_choice(row, changed, "shared_actions", actual, prediction)
    with pytest.raises(ValueError, match="complete reached-state input"):
        bind_choice(row, case, "shared_actions", {**actual, "state": {}}, prediction)
    with pytest.raises(ValueError, match="actual logits"):
        bind_choice(row, case, "shared_actions", actual, {**prediction, "choice": "handoff"})
