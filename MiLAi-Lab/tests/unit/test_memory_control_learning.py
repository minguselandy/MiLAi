import copy
from dataclasses import asdict

from milai_lab.methods.laya_memory_policy import (
    LayaMemoryPolicy,
    operation_payload,
    project_operation_payload,
)
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import (
    decision_example,
    reviewed_prefix_preferences,
    score_operation_predictions,
)


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


def test_retrained_mechanical_projection_keeps_feedback_but_hides_semantic_difference():
    state = MemoryControlState(task={"request": "Who is currently responsible?"},
        visible_evidence=[{"label": "e0", "kind": "query_structure", "revision": 2,
            "interpretation": {"nodes": {"n1": {"text": "Alice is responsible"}}},
            "evidence": [{"source": "s0", "role": "user", "content": "Alice"}]}],
        pending_candidates=[{"item_index": 1, "kind": "original_source", "excerpt": "Alice"}],
        views=[{"id": "v0", "revision": 2, "visibility": "visible", "scope": "Alice",
                "built_for": "Alice", "pending_events": ["s1"]}],
        new_events=[{"source_ref": "s1", "role": "user", "content": "Bob replaces Alice"}],
        last_result={"ok": True, "status": "opened", "index": 0},
        budget={"remaining_control_steps": 3})
    actions = [MemoryAction("r", "READ", "candidate 1", {"index": 1}),
               MemoryAction("h", "HANDOFF", "Reader")]
    row = decision_example({"before": state.project(), "actions": [asdict(a) for a in actions]},
                            {"family": "one"})
    row["gold"] = {"next": {"probabilities": {"r": 1.0}}}
    before = copy.deepcopy(row)
    training = project_operation_payload(row, "mechanical")
    observed = []
    policy = LayaMemoryPolicy(lambda p: observed.append(p) or {"choice": "r"}, "mechanical")
    assert policy.choose(state, actions) == "r"
    assert observed[0] == {k: training[k] for k in ("state", "questions")}
    exported = decision_example(
        {"before": state.project(), "actions": [asdict(a) for a in actions]},
        {"family": "one"}, projection="mechanical")
    assert observed[0] == {k: exported[k] for k in ("state", "questions")}
    assert training["gold"] == row["gold"] and training["metadata"] == row["metadata"]
    assert "Alice" not in str(training["state"]) and "Bob" not in str(training["state"])
    assert row == before
    changed = copy.deepcopy(state)
    changed.new_events[0]["content"] = "Alice remains responsible"
    assert operation_payload(changed, actions) != operation_payload(state, actions)
    assert operation_payload(changed, actions, "mechanical") == observed[0]
    changed.last_result = {"ok": False, "status": "view_rejected"}
    assert operation_payload(changed, actions, "mechanical") != observed[0]


def test_own_prefix_stale_view_needs_new_source_and_unreviewed_view_is_masked():
    actions = [{"id": "read_new", "kind": "READ"},
               {"id": "refresh", "kind": "REFRESH_VIEW"}, {"id": "handoff", "kind": "HANDOFF"}]
    inputs = dict(proofs=[{"a", "b", "u"}], covered={"a", "b", "c"},
                  read_sources={"read_new": {"u"}}, refresh_sources={"refresh": {"a", "b", "u"}})
    selected, status, _ = reviewed_prefix_preferences(actions, **inputs, opened_views=[False])
    assert selected == ["read_new", "refresh"]
    assert status == "acquire_evidence_preference"
    selected, status, _ = reviewed_prefix_preferences(actions, **inputs, opened_views=[None])
    assert selected == [] and status == "unreviewed_opened_view_masked"
    selected, status, _ = reviewed_prefix_preferences(actions, **inputs, opened_views=[True])
    assert selected == ["handoff"] and status == "ready_handoff_preference"
    inputs["covered"] = {"a", "b", "u"}
    selected, status, _ = reviewed_prefix_preferences(actions, **inputs, opened_views=[None])
    assert selected == ["handoff"] and status == "ready_handoff_preference"
