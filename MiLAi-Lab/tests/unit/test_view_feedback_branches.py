"""Branch sampling preserves real bindings and does not infer outcome labels."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_view_feedback_branches import (
    branch_actions,
    call_stratum,
    nominated_actions,
    select_states,
)


def call(*, view=False, originals=False, arrivals=False):
    return {
        "initial_observation": {"views": [{"id": "existing"}] if view else [],
                                "task": {"known_evidence": []}},
        "request": {"read_goal": {"evidence": ["original_source"] if originals else []}},
        "public_message": {"incoming_sources": [{"event_key": "arrival"}] if arrivals else []},
        "initial_actions": [
            {"id": "a" + str(i), "kind": kind, "target": "literal target",
             "parameters": parameters}
            for i, (kind, parameters) in enumerate([
                ("SEARCH", {"query_from": "request", "limit": 8}),
                ("READ", {"source_ref": "actual-ref", "observe_only": True}),
                ("READ", {"source_ref": "actual-ref", "ranges": [[3, 97]]}),
                ("USE_VIEW", {"slot": "current"}),
                ("REFRESH_VIEW", {"source_refs": ["actual-ref"], "slot": "current"}),
                ("HANDOFF", {}),
            ])
        ],
    }


def test_actual_parameters_are_preserved_for_three_distinct_operations():
    original = call(view=True, originals=True, arrivals=True)
    saved = copy.deepcopy(original)
    actions = branch_actions(original)
    assert [a["kind"] for a in actions] == ["HANDOFF", "USE_VIEW", "READ"]
    assert actions[-1]["parameters"] == {"source_ref": "actual-ref", "ranges": [[3, 97]]}
    assert all(action in original["initial_actions"] for action in actions)
    actions[-1]["parameters"]["ranges"][0][0] = 5
    assert original == saved


def test_observable_context_changes_branch_coverage_without_source_id_rules():
    assert call_stratum(call(view=True, originals=True, arrivals=True)) == (
        True, False, True, True)
    assert [a["kind"] for a in branch_actions(call())] == ["HANDOFF", "SEARCH", "REFRESH_VIEW"]
    assert [a["kind"] for a in branch_actions(call(view=True, arrivals=True))] == [
        "HANDOFF", "USE_VIEW", "REFRESH_VIEW"]
    assert [a["kind"] for a in branch_actions(call(view=True))] == [
        "HANDOFF", "USE_VIEW", "SEARCH"]


def test_source_balance_strata_and_nominations_survive_outcome_changes():
    entries = [
        {"capture": f"{group}-{stratum}-{i}", "family": group,
         "stratum": [bool(stratum), False, bool(stratum), False],
         "answer": "not consumed", "grade": "not consumed"}
        for group in ("source-a", "source-b") for stratum in (0, 1) for i in range(4)
    ]
    nominated = "source-a-1-3"
    selected = select_states(entries, ["source-a", "source-b"], 3, 0, [nominated])
    assert len(selected) == 6
    assert sum(e["family"] == "source-a" for e in selected) == 3
    assert nominated in {e["capture"] for e in selected}
    for group in ("source-a", "source-b"):
        assert {e["stratum"][0] for e in selected if e["family"] == group} == {False, True}
    changed = copy.deepcopy(entries)
    for i, entry in enumerate(changed):
        entry.update(answer=str(i), grade="opposite", action_scores={"a0": 1000})
    assert [e["capture"] for e in selected] == [
        e["capture"] for e in select_states(changed, ["source-a", "source-b"], 3, 0, [nominated])]


def test_missing_nominated_actual_state_is_not_replaced_with_another():
    with pytest.raises(ValueError, match="eligible real state"):
        select_states([], ["source-a"], 6, 0, ["missing"])


def test_small_groups_are_retained_without_repeating_states_to_fill_a_quota():
    entries = [{"capture": "a", "family": "source-a", "stratum": [False] * 4}]
    assert select_states(entries, ["source-a", "source-b"], 6, 0, []) == entries


def test_source_review_can_compare_different_bindings_of_one_kind():
    original = call(view=True, originals=True)
    original["initial_actions"].append(
        {"id": "another-read", "kind": "READ", "target": "another actual source",
         "parameters": {"source_ref": "other-ref", "ranges": [[11, 52]]}})
    actions = nominated_actions(original, ["a2", "another-read", "a5"])
    assert [a["kind"] for a in actions] == ["READ", "READ", "HANDOFF"]
    assert actions[1]["parameters"] == {"source_ref": "other-ref", "ranges": [[11, 52]]}
    with pytest.raises(ValueError, match="captured action"):
        nominated_actions(original, ["a2", "invented"])
