"""Semantic acceptance, evidence response and masked denominators stay distinct."""

import pytest

from analyze_source_selection_learning import evidence_metrics, pair_metrics


def row(choices):
    return {"gold": {"next": {"probabilities": {k: 1 / len(choices) for k in choices}}}
            if choices else {},
            "state": {"question": "q", "candidates": [
                {"id": "p0", "text": "a"}, {"id": "p1", "text": "b"}]},
            "questions": {"next": {"criteria": {"open_p0": "a", "open_p1": "b"}}}}


def test_equivalent_acceptable_changes_are_not_errors_and_masks_not_successes():
    data = [row(["open_p0", "open_p1"]), row(["open_p0"]), row([])]
    left = [{"choice": "open_p0"}] * 3
    right = [{"choice": "open_p1"}, {"choice": "open_p0"}, {"choice": "open_p0"}]
    result = pair_metrics(data, left, right, [True, False, True])
    assert result["both_accepted"] == 2
    assert result["canonical_choice_equal"] == 2
    assert result["masked"] == 1
    assert result["changed_input_labelled"] == result["changed_input_both_accepted"] == 1


def test_switch_alone_does_not_satisfy_actual_evidence_change():
    data = [row(["open_p0"]), row(["open_p1"])]
    pairs = [{"left": 0, "right": 1, "requires_choice_change": True}]
    wrong = [{"choice": "open_p1"}, {"choice": "open_p0"}]
    result = evidence_metrics(data, wrong, pairs)["counts"]
    assert result["choice_changed"] == result["changed_but_not_both_accepted"] == 1
    assert result["required_change_and_both_accepted"] == 0
    right = list(reversed(wrong))
    assert evidence_metrics(data, right, pairs)["counts"]["required_change_and_both_accepted"] == 1
    data[1]["state"]["candidates"].pop()
    with pytest.raises(ValueError, match="offered actions/candidates"):
        evidence_metrics(data, right, pairs)
