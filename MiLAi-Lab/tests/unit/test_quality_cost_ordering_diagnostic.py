"""Quality/cost contributions add under original unequal state/family support."""

import copy

import pytest

from quality_cost_ordering_diagnostic import ordering_components
from retrieval_feedback import RESOURCE_FIELDS


def pair(left, right, quality, *, cost_right=False):
    cheap = dict.fromkeys(RESOURCE_FIELDS, 0)
    costly = {**cheap, "read_operations": 1}
    return {
        "left": left,
        "right": right,
        "answer": "right" if quality == "tie" and cost_right else quality,
        "delivery": "unknown",
        "basis": {
            "quality_before_resource_tiebreak": {"answer": quality, "delivery": "unknown"},
            "resource_order": {"left": costly if cost_right else cheap, "right": cheap},
        },
    }


def row(family, comparisons):
    return {
        "questions": {"next": {"criteria": dict.fromkeys(["a", "b", "c"])}},
        "gold": {},
        "metadata": {"family": family},
        "feedback": {"comparisons": comparisons},
    }


def test_components_preserve_original_denominators_and_do_not_equal_subgroup_sum():
    rows = [
        row("A", [pair("a", "b", "left"), pair("a", "c", "tie", cost_right=True)]),
        row("A", [pair("b", "c", "left")]),
        row("B", [pair("a", "b", "left")]),
        row("C", [pair("a", "b", "unknown")]),
    ]
    predictions = [{"logits": {"a": 2, "b": 1, "c": 0}} for _ in rows]
    before = copy.deepcopy(rows)
    result = ordering_components(rows, predictions, "answer")
    macro = result["original_denominator_macro"]
    assert macro["quality_direction_mass"] == 0.875
    assert macro["cost_tie_break_mass"] == 0.125
    assert macro["quality_direction_contribution"] == 0.875
    assert macro["cost_tie_break_contribution"] == 0
    assert result["original_metric"]["family_macro_state_pair_accuracy"] == 0.875
    assert (
        result["conditional_group_metrics"]["quality_direction"]["family_macro_state_pair_accuracy"]
        == 1
    )
    assert result["counts"]["unknown_pairs"] == 1 and result["families"] == 2
    assert rows == before


def test_change_decomposes_without_treating_equal_logits_as_correct():
    rows = [row("A", [pair("a", "b", "left"), pair("a", "c", "tie", cost_right=True)])]
    first = ordering_components(rows, [{"logits": {"a": 0, "b": 0, "c": 0}}], "answer")
    second = ordering_components(rows, [{"logits": {"a": 1, "b": 0, "c": 2}}], "answer")
    assert first["original_metric"]["family_macro_state_pair_accuracy"] == 0
    assert second["original_metric"]["family_macro_state_pair_accuracy"] == 1
    assert second["original_denominator_macro"]["quality_direction_contribution"] == 0.5
    assert second["original_denominator_macro"]["cost_tie_break_contribution"] == 0.5


def test_quality_unknown_cannot_turn_into_cost_direction_and_empty_support_stays_missing():
    rows = [row("A", [pair("a", "b", "unknown")])]
    pred = [{"logits": {"a": 1, "b": 0}}]
    result = ordering_components(rows, pred, "answer")
    assert result["original_metric"]["family_macro_state_pair_accuracy"] is None
    assert result["original_denominator_macro"] == {} and result["families"] == 0
    rows[0]["feedback"]["comparisons"][0]["answer"] = "left"
    with pytest.raises(ValueError, match="contradicts"):
        ordering_components(rows, pred, "answer")
