"""New experience cannot be fabricated, and repeated controls share actual replay inputs."""
import copy

import pytest

from prepare_reader_scale_comparison import prepare_comparison


def row(event, weak=False, active=True):
    return {"state": {"literal": event},
            "questions": {"next": {"criteria": {"a": "READ", "b": "STOP"}}},
            "gold": {} if weak else {"next": {"probabilities": {"a": 1}}},
            "metadata": {"event_id": event, "family": event.split("/")[0], "training_event": "q",
                         "split": "train", "state_id": 0, "row": 0},
            **({"utility": {"candidates": [{"score_known": True, "mean_logprob": x}
                                           for x in (-1., -2. if active else -1.)]}}
               if weak else {})}


def test_scale_pool_keeps_prefix_and_common_replay_identity_and_real_exposure_counts():
    base = [row("a/q0", True), row("b/q0", True), row("old/q")]
    candidates = [row("c/q0", True), row("d/q0", True), row("e/q0", True, False)]
    replay = [row("a/q0"), row("c/q0"), row("r/q0"), row("s/q0")]
    original = copy.deepcopy((base, candidates, replay))
    arms, report = prepare_comparison(base, candidates, replay, 2, 2, {"c": "c", "d": "c"}, 0)
    assert (base, candidates, replay) == original
    assert [r["state"] for r in arms["expanded"][:2]] == [r["state"] for r in base[:2]]
    assert arms["expanded"][-2:] == arms["repeat"][-2:]
    assert {r["metadata"]["event_id"] for r in arms["repeat"][-2:]} == {"r/q0", "s/q0"}
    assert report["expanded_raw_families"] == 4 and report["expanded_dependency_groups"] == 3
    assert report["schedules"]["expanded"]["primary_exposures"] == 12
    assert report["schedules"]["repeat"]["primary_exposures"] == 12
    assert report["schedules"]["repeat"]["passes"] == 6


def test_shortfall_duplicate_versions_and_wrong_role_do_not_become_new_samples():
    base, candidates, replay = [row("a/q0", True)], [row("b/q0", True)], [row("r/q0")]
    with pytest.raises(ValueError, match="Only 1 actual active"):
        prepare_comparison(base, candidates, replay, 2, 1, {}, 0)
    with pytest.raises(ValueError, match="Repeated event"):
        prepare_comparison(base, candidates * 2, replay, 1, 1, {}, 0)
    wrong = copy.deepcopy(candidates)
    wrong[0]["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="TRAIN"):
        prepare_comparison(base, wrong, replay, 1, 1, {}, 0)
    with pytest.raises(ValueError, match="scored utility"):
        prepare_comparison(base, [row("unscored/q")], replay, 1, 1, {}, 0)

