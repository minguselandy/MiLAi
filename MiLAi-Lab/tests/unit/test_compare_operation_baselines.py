"""Recorded action pairing retains unknown states and source groups."""
import pytest
from test_operation_curve_analysis import row

from compare_operation_baselines import BASELINES, compare


def fixture():
    rows = [row("d0", "A", "dev", 0), row("d1", "A", "dev", 1),
            row("d2", "B", "dev", 2, False)]
    predictions = [{"choice": "read"}, {"choice": "stop"}, {"choice": "read"}]
    baselines = {name: [{"event_id": r["metadata"]["event_id"], "choice": "stop"} for r in rows]
                 for name in BASELINES}
    return rows, predictions, baselines


def test_all_baselines_unknown_denominators_and_family_unit():
    rows, predictions, baselines = fixture()
    results, pairs = compare(rows, predictions, baselines, 2, repeats=100)
    assert set(results) == BASELINES
    score = results["rules"]
    assert score["planned_families"] == 2 and score["paired_scored"] == 2
    assert score["unscored_pairs"] == 1
    assert score["family_results"] == {"A": {"baseline": 0, "candidate": .5}}
    assert pairs["rules"][-1]["baseline"] is None
    assert pairs["rules"][-1]["candidate"] is None
    assert score["all_planned_family_macro_difference_bounds"] == [-.25, .75]


@pytest.mark.parametrize("change", ["identity", "unoffered", "missing_baseline"])
def test_changed_comparison_denominator_or_actions_reject(change):
    rows, predictions, baselines = fixture()
    if change == "identity":
        baselines["rules"].reverse()
    elif change == "unoffered":
        baselines["rules"][0]["choice"] = "fabricated"
    else:
        del baselines["rules"]
    with pytest.raises(ValueError):
        compare(rows, predictions, baselines, 0, repeats=100)
