"""Reference acceptance retains masked failures and separates both false STOPs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from evaluate_bounded_laya import score_applicability_predictions, score_predictions


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


def test_applicability_keeps_topic_weight_and_masks_separate_from_operation_metrics():
    rows = [{"gold": {"applicability": {"probabilities": {
                "satisfies": float(label), "does_not_satisfy": float(not label)}}},
             "metadata": {"family": family}}
            for family, label in (("a", True), ("a", False), ("a", False), ("b", True))]
    rows.append({"gold": {}, "metadata": {"family": "masked"}})
    predictions = [{"choice": choice} for choice in (
        "satisfies", "does_not_satisfy", "does_not_satisfy", "does_not_satisfy", "satisfies")]
    result = score_applicability_predictions(rows, predictions)
    assert result["counts"] == {"labelled": 4, "correct": 3, "masked": 1}
    assert result["families"] == 2
    assert result["family_macro_accuracy"] == 0.5
    assert result["confusion"] == [
        {"expected": "does_not_satisfy", "predicted": "does_not_satisfy", "count": 2},
        {"expected": "satisfies", "predicted": "does_not_satisfy", "count": 1},
        {"expected": "satisfies", "predicted": "satisfies", "count": 1},
    ]
    assert "unsupported_sufficient_stop" not in result["counts"]


def test_all_masked_applicability_is_not_zero_accuracy():
    result = score_applicability_predictions(
        [{"gold": {}, "metadata": {"family": "a"}}], [{"choice": "satisfies"}])
    assert result["counts"] == {"masked": 1}
    assert result["family_macro_accuracy"] is None
