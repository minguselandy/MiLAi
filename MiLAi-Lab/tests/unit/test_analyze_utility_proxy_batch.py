import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from analyze_utility_proxy_batch import group_summary, paired_rows, unadmitted_reservations


def test_unfinished_pair_is_unknown_and_not_dropped():
    plan = [
        {
            "pair_index": 0,
            "domain": "db_bench",
            "task_id": "1",
            "repeat": False,
            "selection_changed": False,
            "mechanism_eligible": False,
            "arm": arm,
            "attempt_id": arm,
        }
        for arm in ("STATIC", "UTILITY")
    ]
    arms = {
        "STATIC": {"outcome": "correct", "status": "completed", "charged_tokens": 100, "seconds": 1}
    }
    pairs = paired_rows(plan, arms)
    summary = group_summary(pairs)
    assert summary["scheduled_pairs"] == summary["unknown_quality_pairs"] == 1
    assert summary["known_quality_pairs"] == summary["cost_complete_pairs"] == 0
    assert pairs[0]["arms"]["UTILITY"] is None


def test_quality_regression_is_not_hidden_by_token_saving():
    plan = [
        {
            "pair_index": 0,
            "domain": "os_interaction",
            "task_id": "1",
            "repeat": False,
            "selection_changed": True,
            "mechanism_eligible": True,
            "arm": arm,
            "attempt_id": arm,
        }
        for arm in ("STATIC", "UTILITY")
    ]
    arms = {
        "STATIC": {
            "outcome": "correct",
            "status": "completed",
            "charged_tokens": 100,
            "seconds": 1,
        },
        "UTILITY": {
            "outcome": "incorrect",
            "status": "completed",
            "charged_tokens": 50,
            "seconds": 2,
        },
    }
    summary = group_summary(paired_rows(plan, arms))
    assert summary["quality_regressions"] == 1
    assert summary["charged_tokens_delta_known_pairs"] == -50
    assert summary["wall_seconds_delta_known_pairs"] == 1


def test_identical_payloads_do_not_hide_a_refused_dispatch():
    events = [
        {"event": "RESERVED", "request_id": str(n), "payload_sha256": "same"} for n in range(3)
    ]
    assert unadmitted_reservations(events, ["same", "same"]) == ["2"]
