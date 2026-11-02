"""Target-specific selection and family/state denominators in the frozen feedback curve."""

import json

import pytest

from analyze_feedback_fit import analyze, choose_feedback_checkpoint, feedback_partitions


def point(update, answer, delivery):
    return {"update": update, "feedback-dev": {
        target: {"family_macro_state_pair_accuracy": value}
        for target, value in [("answer", answer), ("delivery", delivery)]}}


def test_earliest_tie_includes_zero_and_ce_keeps_two_target_views():
    points = [point(24, .7, .8), point(12, .7, .9), point(0, .7, .8)]
    assert choose_feedback_checkpoint(points, "answer")["update"] == 0
    assert choose_feedback_checkpoint(points, "delivery")["update"] == 12
    with pytest.raises(ValueError, match="directional development coverage"):
        choose_feedback_checkpoint([point(0, None, .8)], "answer")


def test_partitions_use_event_identity_and_average_states_then_families():
    def row(event, family, pairs, policy="rules", step=0):
        return {"metadata": {"event_id": event, "state_id": 0, "family": family,
                             "collection_policy": policy, "control_step": step},
                "feedback": {"comparisons": pairs}}

    def pair(left, right, outcome):
        return {"left": left, "right": right, "answer": outcome, "delivery": "unknown"}

    rows = [
        row("old", "A", [pair("read", "stop", "right"),
                         pair("stop", "view", "right"), pair("read", "view", "right")]),
        row("new-a", "A", [pair("read", "stop", "left"), pair("stop", "view", "unknown")]),
        row("new-b", "B", [pair("read", "stop", "left"), pair("stop", "view", "tie")],
            policy="laya", step=1),
    ]
    predictions = [{"logits": {"read": 3.0, "stop": 2.0, "view": 1.0}} for _ in rows]
    report = feedback_partitions(rows, predictions, {"old"})
    combined = report["combined"]["targets"]["answer"]
    assert combined["family_macro_state_pair_accuracy"] == .75  # (.5 for A + 1 for B) / 2
    assert combined["counts"]["directional_pairs"] == 5
    assert combined["counts"]["unknown"] == combined["counts"]["tie"] == 1
    assert report["combined"]["targets"]["delivery"]["family_macro_state_pair_accuracy"] is None
    assert report["legacy"]["states"] == 1 and report["new"]["states"] == 2
    assert report["rules_initial"]["states"] == report["laya_post"]["states"] == 1
    with pytest.raises(ValueError, match="identities or legacy membership"):
        feedback_partitions([rows[0], rows[0]], predictions[:2], {"old"})
    with pytest.raises(ValueError, match="identities or legacy membership"):
        feedback_partitions(rows, predictions, {"absent-legacy"})


def test_live_or_partial_training_cannot_be_selected(tmp_path):
    output = tmp_path / "fit"
    output.mkdir()
    (output / "run.json").write_text(json.dumps({"status": "RUNNING", "optimizer_updates": 12}))
    argv = ["python", "train_bounded_laya.py", str(tmp_path / "data"),
            str(tmp_path / "base"), str(output), "--task", "memory_operation",
            "--objective", "pair",
            "--optimizer-updates", "192", "--eval-at-updates", "12", "24", "48", "96", "192",
            "--seed", "0", "--max-len", "16384", "--head-max-len", "2048",
            "--encoder-lr", "2.5e-5", "--head-lr", "1e-4", "--micro-batch-size", "1",
            "--operation-state", "shared_actions", "--compute-phase", "unit",
            "--budget", str(tmp_path / "budget.json")]
    plan = {"source_version": "test", "plans": [{"run_id": "unit", "arm": "answer", "argv": argv}]}
    with pytest.raises(ValueError, match="complete declared fit"):
        analyze(plan, "unit")
