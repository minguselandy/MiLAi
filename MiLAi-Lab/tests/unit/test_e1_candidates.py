"""A global two-nominee E1 budget is not a per-arm or deployment selection."""
import pytest

from analyze_e1_candidates import nominate


def report(arm, values):
    return {"recipe": {"planned_optimizer_updates": 128}, "curve": [
        {"update": update, "checkpoint": f"/{arm}/{update}", "answer_first": {
            "weighted_task_pair_loss": value, "coverage": {"target_pairs": 5}}}
        for update, value in zip([0, 16, 32, 64, 128], values, strict=True)]}


def test_two_nominees_keep_delivery_control_and_do_not_replace_update0():
    reports = {a: report(a, v) for a, v in [
        ("delivery-only", [.1, .9, .8, .8, .9]),
        ("answer-first-full", [.1, .6, .5, .5, .7]),
        ("answer-first-head", [.1, .7, .4, .4, .6])]}
    nominees = nominate(reports)
    assert [(p["arm"], p["update"]) for p in nominees] == [
        ("delivery-only", 32), ("answer-first-head", 32)]
    # Even when initialization has lower pair loss, actual task comparison retains it separately.
    assert len(nominees) == 2 and all(p["update"] > 0 for p in nominees)


def test_earliest_update_precedes_arm_tiebreak():
    reports = {a: report(a, [.9, .5, .5, .5, .5]) for a in (
        "delivery-only", "answer-first-full", "answer-first-head")}
    assert nominate(reports)[1]["arm"] == "answer-first-full"
    reports["answer-first-full"]["curve"][1]["answer_first"]["weighted_task_pair_loss"] = .7
    assert nominate(reports)[1]["arm"] == "answer-first-head"


def test_missing_arm_or_incomplete_curve_cannot_silently_reduce_the_comparison():
    reports = {a: report(a, [.9, .8, .7, .6, .5]) for a in (
        "delivery-only", "answer-first-full", "answer-first-head")}
    with pytest.raises(ValueError, match="all three"):
        nominate({k: v for k, v in reports.items() if k != "answer-first-head"})
    reports["answer-first-head"]["curve"].pop()
    with pytest.raises(ValueError, match="incomplete curve"):
        nominate(reports)
