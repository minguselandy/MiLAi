import copy
from dataclasses import asdict

from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example, score_operation_predictions


def test_export_matches_live_projection_and_does_not_label_teacher_choice():
    state = MemoryControlState(task={"request": "Which date?", "query_time": "2031-04-01"},
        last_result={"status": "searched", "candidates": 1})
    actions = [MemoryAction("r", "READ", "candidate 0", {"index": 0}),
               MemoryAction("h", "HANDOFF", "Reader")]
    event = {"before": state.project(), "actions": [asdict(a) for a in actions]}
    exported = decision_example(event, {"family": "offline-family", "teacher_choice": "h"})
    assert {k: exported[k] for k in ("state", "questions")} == operation_payload(state, actions)
    assert exported["gold"] == {}
    assert "offline-family" not in str(exported["state"])
    assert "teacher_choice" not in str(exported["questions"])


def test_operation_metrics_allow_multiple_actions_and_preserve_masked_states():
    row = {"gold": {"next": {"probabilities": {"r": 0.5, "v": 0.5}}},
           "metadata": {"family": "one", "label_status": "needs_evidence",
                        "action_kinds": {"r": "READ", "v": "USE_VIEW", "h": "HANDOFF"}}}
    masked = {**copy.deepcopy(row), "gold": {}}
    before = copy.deepcopy(row)
    report = score_operation_predictions([row, row, masked],
                                          [{"choice": "v"}, {"choice": "h"}, {"choice": "h"}])
    assert report["counts"] == {"labelled": 2, "accepted": 1,
                                 "handoff_outside_reviewed_preference": 1, "masked": 1}
    assert report["families"] == 1
    assert report["family_macro_acceptance"] == 0.5
    assert row == before
