"""Structural completion/progress targets never claim Reader utility or infer unseen negatives."""
import copy

import pytest

from native_t1_structural import captured_prefix_states, structural_supervision


def coverage(covered, required=2):
    return {"covered": covered, "required": required,
            "complete": None if covered is None else covered == required}


def outcome(action, delivered, acquired, operations):
    return {"action": action, "reason": "intervention_handoff",
            "delivered_coverage": coverage(delivered), "acquired_coverage": coverage(acquired),
            "nonterminal_operations": operations}


def test_ready_O_requires_real_delivery_and_control_cost_only_breaks_structural_ties():
    actions = [{"id": "current", "kind": "HANDOFF"},
               {"id": "select_O", "kind": "HANDOFF"}, {"id": "read_more", "kind": "READ"}]
    outcomes = [outcome(actions[0], 0, 2, 0), outcome(actions[1], 2, 2, 0),
                outcome(actions[2], 2, 2, 3)]
    original = copy.deepcopy(outcomes)
    labels = structural_supervision(actions, outcomes, coverage(2))
    assert labels["good_action_ids"] == ["select_O"]
    assert labels["observed_action_ids"] == labels["choice_action_ids"] == [
        a["id"] for a in actions]
    assert labels["preferences"] == [] and outcomes == original


def test_observe_only_progress_is_not_mistaken_for_delivered_support_or_task_success():
    actions = [{"id": "stop", "kind": "HANDOFF"}, {"id": "O", "kind": "READ"}]
    labels = structural_supervision(actions, [outcome(actions[0], 0, 0, 0),
        outcome(actions[1], 0, 1, 1)], coverage(0))
    assert labels["good_action_ids"] == ["O"]
    assert labels["structural_ranks"]["O"] == [1, 1, -1]
    assert "not Reader success" in labels["scope"]


def test_flat_no_progress_and_unknown_menus_stay_masked_and_missing_execution_is_rejected():
    actions = [{"id": "stop", "kind": "HANDOFF"}, {"id": "read", "kind": "READ"}]
    results = [outcome(actions[0], 0, 0, 0), outcome(actions[1], 0, 0, 1)]
    labels = structural_supervision(actions, results, coverage(0))
    assert labels["good_action_ids"] == labels["choice_action_ids"] == []
    results[1]["acquired_coverage"] = coverage(None)
    labels = structural_supervision(actions, results, coverage(0))
    assert labels["good_action_ids"] == [] and "read" not in labels["structural_ranks"]
    with pytest.raises(ValueError, match="entire actual offered menu"):
        structural_supervision(actions, results[:1], coverage(0))


def test_captured_prefix_loads_the_exact_actual_event_and_policy_without_reconstruction(tmp_path):
    import json

    saved = {"event_id": "root/question", "policy": "learned", "decision": {
        "step": 2, "before": {"task": {"request": "literal"}}, "actions": []},
        "executor_checkpoint": {"observed": {"0": "actual original"}}}
    path = tmp_path / "decisions.jsonl"
    path.write_text(json.dumps(saved) + "\n")
    selector = {"name": "pre_stop", "record_index": 0,
                "checkpoint_path": str(path), "policy": "learned"}
    manifest = {"events": {"root/question": [selector]}}
    assert captured_prefix_states(manifest, "root/question") == {"pre_stop": saved}
    selector["policy"] = "other"
    with pytest.raises(ValueError, match="another event or policy"):
        captured_prefix_states(manifest, "root/question")
    selector["policy"] = "learned"
    manifest["events"]["root/question"].append(copy.deepcopy(selector))
    with pytest.raises(ValueError, match="unique names"):
        captured_prefix_states(manifest, "root/question")
