"""Full short-stage exposure must include complete pairs without inventing labels or sources."""
import copy

import pytest

from milai_lab.datasets.conditional_exposure import (
    condition_stratified_auxiliary_panel,
    instruction_negative_coverage,
    paired_auxiliary_panel,
)
from milai_lab.datasets.conditional_reviews import binary_label


def pool():
    rows, pairs = [], []
    for query in range(3):
        for candidate in range(5):
            labels = ((True, False) if (query, candidate) == (0, 0)
                      else (True, True) if (query, candidate) == (1, 0)
                      else (None, False) if candidate == 4 else (False, False))
            events = []
            for condition, label in enumerate(labels):
                event = f"{query}/{candidate}/{condition}"
                events.append(event)
                rows.append({"state": {"candidate": {"text": f"body{candidate}"},
                    "task": {"retrieval_request": {"query": str(query),
                             "read_goal": {"purpose": str(condition)}}}},
                    "questions": {"applicability": {}},
                    "gold": {} if label is None else {"applicability": {"probabilities": {
                        "satisfies": float(label), "does_not_satisfy": float(not label)}}},
                    "metadata": {"event_id": event, "family": f"f{query}", "split": "train",
                        "query_unit": str(query), "training_event": f"{query}/{condition}",
                        "row": len(rows), "label_status": "known" if label is not None
                        else "unjudged"}})
            pairs.append({"left_event": events[0], "right_event": events[1],
                "family": f"f{query}", "query_unit": str(query), "left_label": labels[0],
                "right_label": labels[1], "kind": "unknown" if None in labels
                else "change" if labels[0] != labels[1] else "stable"})
    return rows, pairs


def test_full_panel_covers_rare_pairs_and_all_queries_with_literal_cells():
    rows, pairs = pool()
    before = copy.deepcopy((rows, pairs))
    result = paired_auxiliary_panel(rows, pairs, pair_budget=6, seed=0)
    assert (rows, pairs) == before
    assert result["counts"]["comparison_kind"] == {"change": 1, "stable": 5}
    assert result["counts"]["stable_positive_pairs"] == 1
    assert {p["query_unit"] for p in result["pairs"]} == {"0", "1", "2"}
    assert len(result["rows"]) == 12
    for row, slot in zip(result["rows"], result["slots"], strict=True):
        original = copy.deepcopy(rows[slot["source_matrix_position"]])
        original["metadata"]["state_id"] = slot["source_matrix_position"]
        assert row == original and row["gold"]
    assert result == paired_auxiliary_panel(rows, pairs, pair_budget=6, seed=0)
    assert result["pairs"] != paired_auxiliary_panel(rows, pairs, pair_budget=6, seed=1)["pairs"]


def test_shared_cell_across_distinct_condition_pairs_keeps_original_identity():
    rows, pairs = pool()
    original = rows[0]
    third = copy.deepcopy(original)
    third["metadata"]["event_id"] = "0/0/third"
    third["state"]["task"]["retrieval_request"]["read_goal"]["purpose"] = "third"
    rows.append(third)
    pairs.append({**pairs[0], "right_event": "0/0/third", "right_label": True,
                  "kind": "stable"})
    result = paired_auxiliary_panel(rows, pairs, pair_budget=6, seed=0)
    copies = [r for r in result["rows"] if r["metadata"]["event_id"] == "0/0/0"]
    assert len(copies) == 2 and copies[0] == copies[1]
    assert copies[0]["metadata"]["state_id"] == 0
    assert result["counts"]["distinct_cells"] == 11


@pytest.mark.parametrize("budget", [0, 1, 13])
def test_budget_never_silently_drops_required_queries_or_repeats_pairs(budget):
    rows, pairs = pool()
    with pytest.raises(ValueError, match="budget"):
        paired_auxiliary_panel(rows, pairs, pair_budget=budget, seed=0)


@pytest.mark.parametrize("mutation", ["dev", "candidate", "query", "label"])
def test_no_cross_split_or_changed_candidate_or_stale_label_is_admitted(mutation):
    rows, pairs = pool()
    if mutation == "dev":
        rows[0]["metadata"]["split"] = "dev"
    elif mutation == "candidate":
        rows[0]["state"]["candidate"]["text"] = "other"
    elif mutation == "query":
        rows[0]["state"]["task"]["retrieval_request"]["query"] = "other"
    else:
        pairs[0]["left_label"] = False
    with pytest.raises(ValueError):
        paired_auxiliary_panel(rows, pairs, pair_budget=6, seed=0)


def test_stratified_panel_covers_labels_rare_pairs_and_single_condition_queries():
    rows, pairs = pool()
    single = copy.deepcopy(rows[0])
    single["metadata"].update(event_id="single", query_unit="single", family="single",
                              training_event="single/0")
    rows.append(single)
    before = copy.deepcopy((rows, pairs))
    panel = condition_stratified_auxiliary_panel(rows, pairs, seed=0)
    assert (rows, pairs) == before
    assert panel == condition_stratified_auxiliary_panel(rows, pairs, seed=0)
    selected = panel["rows"]
    events = {r["metadata"]["event_id"] for r in selected}
    assert "single" in events and len(events) == len(selected)
    for pair in pairs:
        if pair["kind"] == "change" or (pair["kind"] == "stable" and pair["left_label"]):
            assert {pair["left_event"], pair["right_event"]} <= events
    for row in rows:
        if row["gold"]:
            assert any(z["metadata"]["training_event"] == row["metadata"]["training_event"]
                       and binary_label(z) == binary_label(row) for z in selected)
    assert any(x["query_unit"] == "single" and x["label"] is False
               for x in panel["missing_condition_labels"])
    for row, slot in zip(selected, panel["slots"], strict=True):
        original = copy.deepcopy(rows[slot["source_matrix_position"]])
        original["metadata"]["state_id"] = slot["source_matrix_position"]
        assert row == original and row["gold"]
    assert {p["query_unit"] for p in panel["pairs"] if p["kind"] == "stable"
            and p["left_label"] is False} == {"0", "1", "2"}


def test_stratified_panel_rejects_dev_even_without_pairs_and_never_labels_unknown():
    rows, _ = pool()
    rows[0]["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="training split"):
        condition_stratified_auxiliary_panel(rows, [], seed=0)
    rows[0]["metadata"]["split"] = "train"
    unknown = [r for r in rows if not r["gold"]]
    panel = condition_stratified_auxiliary_panel(unknown, [], seed=0)
    assert not panel["rows"] and panel["counts"]["unrepresented_families"] == ["f0", "f1", "f2"]


def test_instruction_negative_coverage_is_distinct_from_ordinary_label_coverage():
    rows, pairs = pool()
    for row in rows:
        meta = row['metadata']
        meta['native_judgments'] = [{'native_field': 'new_negatives'}] if (
            meta['event_id'].split('/')[1] == '4') else [{'native_field': 'negative_passages'}]
    panel = condition_stratified_auxiliary_panel(rows, pairs, seed=0)
    ordinary = [r for r in rows if r['metadata']['event_id'].split('/')[1] != '4' and r['gold']]
    coverage = instruction_negative_coverage(rows, ordinary)
    assert coverage['available_known_units'] == coverage['eligible_conditions'] == 3
    assert coverage['selected_known_units'] == coverage['represented_conditions'] == 0
    assert len(coverage['missing_conditions']) == 3
    # Unknown opposite-condition cells retain unknown even when their origin is instructional.
    all_known = [r for r in rows if r['gold']]
    full = instruction_negative_coverage(rows, all_known)
    assert full['selected_known_units'] == 3 and not full['missing_conditions']
    assert panel['instruction_negative_coverage'] == instruction_negative_coverage(
        rows, panel['rows'])


def test_native_priority_replaces_same_condition_negatives_without_changing_known_labels():
    rows, pairs = pool()
    for row in rows:
        row['metadata']['native_judgments'] = [{'native_field': 'new_negatives'}] if (
            row['metadata']['event_id'].split('/')[1] == '4') else []
    before = copy.deepcopy((rows, pairs))
    legacy = condition_stratified_auxiliary_panel(rows, pairs, seed=0)
    native = condition_stratified_auxiliary_panel(rows, pairs, seed=0,
                                                negative_selection='native-priority')
    assert (rows, pairs) == before
    assert native['instruction_negative_coverage']['represented_conditions'] == 3
    assert native['counts']['training_slots'] == legacy['counts']['training_slots']
    assert native['counts']['negative_slots'] == legacy['counts']['negative_slots']
    assert native['missing_condition_labels'] == legacy['missing_condition_labels']
    for panel in (legacy, native):
        for row in panel['rows']:
            assert row['gold']
    positives = lambda panel: {r['metadata']['event_id'] for r in panel['rows']  # noqa: E731
                               if binary_label(r) is True}
    assert positives(native) == positives(legacy)
    assert [p for p in native['pairs'] if p['kind'] == 'change'] == [
        p for p in legacy['pairs'] if p['kind'] == 'change']
    # A mandatory negative endpoint can exhaust its condition's only slot.
    limited = condition_stratified_auxiliary_panel(rows[:2] + rows[8:10], pairs[:1], seed=0,
                                                 negative_selection='native-priority')
    assert limited['instruction_negative_coverage']['represented_conditions'] == 0
    assert limited['counts']['training_slots'] == 2


@pytest.mark.parametrize("mutation", ["candidate", "query", "label"])
def test_stratified_panel_does_not_train_stale_conditional_pairs(mutation):
    rows, pairs = pool()
    if mutation == "candidate":
        rows[0]["state"]["candidate"]["text"] = "changed"
    elif mutation == "query":
        rows[0]["state"]["task"]["retrieval_request"]["query"] = "changed"
    else:
        pairs[0]["left_label"] = False
    with pytest.raises(ValueError, match="matching training query"):
        condition_stratified_auxiliary_panel(rows, pairs, seed=0)


def test_appended_families_do_not_resample_the_existing_scale_prefix():
    rows, pairs = pool()
    for i in range(2):
        extra = copy.deepcopy(rows[0])
        extra["metadata"].update(event_id=f"extra-{i}", family="f2", query_unit="2",
                                  training_event="2/0")
        rows.append(extra)
    appended_rows, appended_pairs = copy.deepcopy((rows[:4], pairs[:2]))
    for row in appended_rows:
        meta = row["metadata"]
        meta.update(event_id="new/" + meta["event_id"], family="new", query_unit="new",
                    training_event="new/" + meta["training_event"])
        row["state"]["task"]["retrieval_request"]["query"] = "new"
    for pair in appended_pairs:
        pair.update(left_event="new/" + pair["left_event"],
                    right_event="new/" + pair["right_event"], family="new", query_unit="new")
    old_ids = {r["metadata"]["event_id"] for r in rows}
    for seed in range(8):
        small = condition_stratified_auxiliary_panel(rows, pairs, seed=seed)
        large = condition_stratified_auxiliary_panel(
            rows + appended_rows, pairs + appended_pairs, seed=seed)
        assert {r["metadata"]["event_id"] for r in small["rows"]} == {
            r["metadata"]["event_id"] for r in large["rows"]
            if r["metadata"]["event_id"] in old_ids}
