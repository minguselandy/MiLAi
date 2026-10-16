"""Reference acceptance retains masked failures and separates both false STOPs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from evaluate_bounded_laya import score_predictions


def row(target, family="f0"):
    return {"questions": {"next": {"criteria": {
        "open_p0": "a", "open_p1": "b", "stop_sufficient": "s", "stop_exhausted": "e"}}},
        "gold": {"next": {"probabilities": target}} if target else {},
        "metadata": {"label_status": "label", "family": family}}


def test_equivalent_actions_masking_and_false_stop_denominators():
    rows = [row({"open_p0": 0.5, "open_p1": 0.5}), row({"open_p0": 1}),
            row({"open_p0": 1}), row({"stop_sufficient": 1}), row({}, "masked")]
    predicted = [{"choice": c} for c in (
        "open_p1", "stop_sufficient", "stop_exhausted", "open_p0", "stop_sufficient")]
    result = score_predictions(rows, predicted)
    assert result["counts"] == {
        "labelled": 4, "accepted": 1, "masked_reference": 1,
        "unsupported_sufficient_stop": 1, "unsupported_exhaustion_stop": 1,
        "unnecessary_continue": 1, "first_remaining_candidate_accepted": 3}
    assert result["families"] == 1
    assert result["family_macro_acceptance"] == 0.25
