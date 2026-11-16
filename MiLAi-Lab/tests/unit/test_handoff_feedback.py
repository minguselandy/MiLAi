"""Partial actual delivery judgments must not manufacture quality for unknown branches."""
import copy

import pytest

from prepare_handoff_feedback import compile_feedback, reviewed_relation


def test_partial_quality_and_failed_readout_remain_unknown():
    assert reviewed_relation("sufficient", "insufficient", "delivery") == "left"
    assert reviewed_relation("insufficient", "insufficient", "delivery") == "unknown"
    assert reviewed_relation("unknown", "sufficient", "delivery") == "unknown"
    assert reviewed_relation("complete", "failed", "answer") == "unknown"
    assert reviewed_relation("complete", "complete", "answer") == "tie"
    assert reviewed_relation("complete", "incorrect", "answer") == "left"
    assert reviewed_relation("incorrect", "complete", "answer") == "right"
    assert reviewed_relation("incorrect", "incorrect", "answer") == "unknown"
    assert reviewed_relation("incorrect", "incomplete", "answer") == "unknown"


def test_actual_binding_dedup_keeps_original_inputs_and_unknown_alternatives():
    row = {"state": {"request": "Use A and B"},
           "questions": {"next": {"criteria": {"ab": "A+B", "a": "A", "other": "C"}}},
           "gold": {}, "metadata": {"family": "train-f", "split": "train",
               "action_parameters": {"ab": {"delivery_indices": [0, 1]},
                                     "a": {"delivery_indices": [0]},
                                     "other": {"delivery_indices": [2]}}}}
    before = copy.deepcopy(row)
    outcomes, reviews = [], []
    for case, key, quality in (("fixed", "ab", "sufficient"),
                               ("rules", "ab", "sufficient"), ("model", "a", "insufficient")):
        action = {"id": key, "kind": "HANDOFF", "target": "observed",
                  "parameters": row["metadata"]["action_parameters"][key]}
        outcomes.append({"case": case, "state_index": 0, "family": "train-f",
                         "tool": {"action": action}})
        reviews.append({"case": case, "state_index": 0, "family": "train-f",
                        "actual_action": action, "material_status": quality,
                        "answer_status": "failed"})
    result, = compile_feedback([row], reviews, outcomes)
    pair, = result["feedback"]["comparisons"]
    assert pair["left"] == "ab" and pair["right"] == "a"
    assert pair["delivery"] == "left" and pair["answer"] == "unknown"
    assert result["state"] == row["state"] and result["questions"] == row["questions"]
    assert row == before
    assert len(result["metadata"]["actual_branch_cases"]) == 3
    reviews[-1] = {**reviews[-1], "actual_action": {**reviews[-1]["actual_action"],
                    "parameters": {"delivery_indices": [2]}}}
    with pytest.raises(ValueError, match="binding"):
        compile_feedback([row], reviews, outcomes)
