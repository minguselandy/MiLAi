import copy

import pytest

from milai_lab.analysis.paired_sources import compare_sources


def records():
    return [{"seed": 0, "unit_id": f"a-{i}", "family": "many",
             "baseline": 0, "candidate": 1} for i in range(10)] + [
        {"seed": 0, "unit_id": "b", "family": "one", "baseline": 1, "candidate": 0}]


def test_family_macro_not_state_count_controls_the_paired_effect():
    result = compare_sources(records(), repeats=200)
    assert result["paired_family_interval"]["difference_second_minus_first"] == 0
    assert result["planned_families"] == 2 and result["planned_pairs"] == 11
    assert result["all_planned_family_macro_difference_bounds"] == [0, 0]


def test_repeated_seeds_remain_inside_families_not_new_bootstrap_units():
    one = records()
    many = [*one, *[{**r, "seed": 1} for r in one], *[{**r, "seed": 2} for r in one]]
    a, b = compare_sources(one, repeats=200), compare_sources(many, repeats=200)
    assert b["seeds"] == [0, 1, 2]
    assert a["paired_family_interval"] == b["paired_family_interval"]
    assert b["paired_family_interval"]["families"] == 2


def test_unknown_pairs_are_neither_dropped_from_coverage_nor_treated_as_failures():
    rows = [{"seed": 0, "unit_id": "x", "family": "f", "baseline": 1, "candidate": None}]
    result = compare_sources(rows, repeats=200)
    assert result["paired_scored"] == 0 and result["unscored_pairs"] == 1
    assert result["paired_family_interval"] is None
    assert result["all_planned_family_macro_difference_bounds"] == [-1, 0]


@pytest.mark.parametrize("change", ["missing_seed_unit", "family", "duplicate"])
def test_changed_pairing_is_not_silently_reconstructed(change):
    rows = records()
    rows += [{**copy.deepcopy(r), "seed": 1} for r in rows]
    if change == "missing_seed_unit":
        rows.pop()
    elif change == "family":
        rows[-1]["family"] = "different"
    else:
        rows.append(dict(rows[-1]))
    with pytest.raises(ValueError):
        compare_sources(rows)
