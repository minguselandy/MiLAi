"""Own-state learning compares real common request/condition support and shared replay."""
import copy

import pytest
from test_reader_scale_comparison import row

from prepare_matched_own_states import match_states


def state(family, step, condition="cold", active=True):
    value = row(f"{family}/q/{condition}/{step}", True, active)
    value["metadata"]["condition"] = condition
    value["state"]["task"] = {"retrieval_request": {
        "query": "original question", "task_context": {"known": condition}}}
    return value


def test_common_strata_match_counts_keep_actual_inputs_and_share_replay():
    old = [state("a", i) for i in range(3)] + [state("b", 0, "known")]
    own = [state("a", 4), state("b", 2, "known"), state("c", 0),
           state("a", 8, active=False)]
    replay = [row("replay/q0"), row("another/q0")]
    original = copy.deepcopy((old, own, replay))
    arms, report = match_states(old, own, replay, {"a": "group", "b": "group"})
    assert (old, own, replay) == original
    assert report["selected_each"] == 2
    assert report["raw_families"] == 2 and report["dependency_groups"] == 1
    assert report["not_selected_active"] == {"old": 2, "own": 1}
    assert arms["old"][-2:] == arms["own"][-2:]
    assert report["schedules"]["old"] == report["schedules"]["own"]
    assert report["schedules"]["old"]["primary_exposures"] == 6
    for method, source in (("old", old), ("own", own)):
        by_event = {r["metadata"]["event_id"]: r for r in source}
        for selected in arms[method][:2]:
            actual = by_event[selected["metadata"]["event_id"]]
            assert all(selected[k] == actual[k] for k in ("state", "questions", "utility"))


def test_request_known_evidence_and_condition_are_not_silently_merged():
    old, own, replay = [state("a", 0)], [state("a", 1)], [row("r/q")]
    changed = copy.deepcopy(own)
    changed[0]["state"]["task"]["retrieval_request"]["task_context"]["known"] = "other"
    with pytest.raises(ValueError, match="request or K"):
        match_states(old, changed, replay, {})
    with pytest.raises(ValueError, match="No common active"):
        match_states(old, [state("a", 1, "known")], replay, {})


def test_failed_scoring_wrong_roles_duplicate_events_and_replay_overlap_rejected():
    old, own, replay = [state("a", 0)], [state("a", 1)], [row("r/q")]
    failed = copy.deepcopy(own)
    failed[0]["utility"]["candidates"][0]["execution_status"] = "failed"
    with pytest.raises(ValueError, match="No common active"):
        match_states(old, failed, replay, {})
    wrong = copy.deepcopy(own)
    wrong[0]["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="TRAIN"):
        match_states(old, wrong, replay, {})
    with pytest.raises(ValueError, match="unique actual events"):
        match_states(old * 2, own, replay, {})
    collision = row(old[0]["metadata"]["event_id"])
    with pytest.raises(ValueError, match="overlaps"):
        match_states(old, own, [collision], {})
