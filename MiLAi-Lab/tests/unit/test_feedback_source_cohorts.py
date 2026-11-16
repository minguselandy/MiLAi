"""Nested source selection preserves full histories, split boundaries and masked groups."""
import copy

import pytest

from prepare_feedback_source_cohorts import prepare_cohorts


def fixture():
    groups = [(f"history-{i}", "history") for i in range(4)] + [
        (f"evidence-{i}", "evidence") for i in range(8)]
    data = {"train": [{"metadata": {"family": group, "task": "memory_operation",
        "component": component, "split": "train"}, "gold": {} if i % 2 else {"next": "unused"}}
        for i, (group, component) in enumerate(groups)],
        "dev": [{"metadata": {"family": "held-dev", "component": "history",
                               "task": "memory_operation", "split": "dev"}, "gold": {}}]}
    histories = [{"id": group, "source_group": group, "split": split,
        "continuous": True, "sources": [{"content": 'literal Ω "text"', "occurred_at": None}],
        "requests": [{"content": "original task", "incoming_sources": []},
                     {"content": "later task", "incoming_sources": [{"content": "actual later"}]}]}
        for split, rows in data.items() for row in rows for group in [row["metadata"]["family"]]]
    return data, [{"histories": histories[:6]}, {"histories": histories[6:]}]


def test_component_balanced_nested_prefixes_preserve_every_source_and_request():
    data, fixtures = fixture()
    saved = copy.deepcopy((data, fixtures))
    cohorts, report = prepare_cohorts(data, fixtures, ["history-0"], [3, 7, 12], 0)
    assert (data, fixtures) == saved
    groups = report["cohorts"]
    assert groups["3"]["selected_groups"] == groups["7"]["selected_groups"][:3]
    assert groups["7"]["selected_groups"] == groups["12"]["selected_groups"][:7]
    assert groups["12"]["component_groups"] == {"history": 4, "evidence": 8}
    originals = {h["id"]: h for f in fixtures for h in f["histories"]}
    assert all(h == originals[h["id"]] for c in cohorts.values() for h in c["histories"])
    assert "held-dev" not in report["source_order"]
    assert report["registered_dev_groups"] == 1
    assert len(report["source_order"]) == len(set(report["source_order"])) == 12


def test_gold_and_outcome_changes_do_not_replace_masked_or_hard_groups():
    data, fixtures = fixture()
    first = prepare_cohorts(data, fixtures, ["history-0"], [3, 7], 0)
    for row in data["train"]:
        row["gold"] = {"opposite": "not consumed"}
        row["metadata"]["answerability"] = False
    assert prepare_cohorts(data, fixtures, ["history-0"], [3, 7], 0) == first


@pytest.mark.parametrize("change", ["dev_anchor", "changed_split", "missing_history", "duplicate"])
def test_source_admission_errors_do_not_silently_fill_another_group(change):
    data, fixtures = fixture()
    anchors = ["history-0"]
    if change == "dev_anchor":
        anchors = ["held-dev"]
    elif change == "changed_split":
        fixtures[0]["histories"][0]["split"] = "dev"
    elif change == "missing_history":
        fixtures[0]["histories"].pop()
    else:
        fixtures[0]["histories"].append(copy.deepcopy(fixtures[0]["histories"][0]))
    with pytest.raises(ValueError):
        prepare_cohorts(data, fixtures, anchors, [3], 0)
