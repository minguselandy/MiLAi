"""Source expansion must not move exposed dev material into training through new links."""
import copy

import pytest
from test_promptriever import source

from milai_lab.datasets.promptriever import extend_promptriever_allocation, source_keys


def allocation_fixture():
    prior = [source(i) for i in range(4)]
    groups = [{"source_group": f"old-{i}", "split": "train" if i % 2 == 0 else "dev",
               "rows": [i]} for i in range(4)]
    rows = copy.deepcopy(prior) + [source(i) for i in range(4, 9)]
    for new, old in [(4, 0), (5, 1), (6, 2), (6, 3)]:
        rows[new]["negative_passages"].append(copy.deepcopy(prior[old]["positive_passages"][0]))
    return rows, prior, groups


def test_old_anchors_stay_locked_and_cross_split_bridges_are_excluded():
    rows, prior, groups = allocation_fixture()
    before = copy.deepcopy((rows, prior, groups))
    result = extend_promptriever_allocation(rows, prior, groups, allocation_id="expanded",
                                           seed=0, dev_fraction=.5)
    by_rows = {tuple(g["rows"]): g for g in result["groups"]}
    assert by_rows[0, 4]["split"] == "train"
    assert by_rows[1, 5]["split"] == "dev"
    assert by_rows[2, 3, 6]["split"] == "excluded"
    assert by_rows[2, 3, 6]["allocation_basis"] == "bridge_between_prior_train_and_dev"
    assert {by_rows[(i,)]["split"] for i in (7, 8)} == {"train", "dev"}
    keys = {split: {key for g in result["groups"] if g["split"] == split
                   for i in g["rows"] for key in source_keys(rows[i])}
            for split in ["train", "dev", "excluded"]}
    assert not keys["train"] & keys["dev"]
    assert not keys["train"] & keys["excluded"]
    assert not keys["dev"] & keys["excluded"]
    assert (rows, prior, groups) == before


def test_new_label_membership_cannot_select_the_partition():
    rows, prior, groups = allocation_fixture()
    first = extend_promptriever_allocation(rows, prior, groups, allocation_id="expanded")
    for row in rows[len(prior):]:
        row["positive_passages"], row["negative_passages"] = (
            row["negative_passages"], row["positive_passages"])
    second = extend_promptriever_allocation(rows, prior, groups, allocation_id="expanded")
    assert first == second


def test_prior_declared_family_is_not_split_when_broader_than_literal_keys():
    prior = [source(0), source(1)]
    rows = [*copy.deepcopy(prior), source(2)]
    groups = [{"source_group": "historical-semantic-family", "split": "train", "rows": [0, 1]}]
    result = extend_promptriever_allocation(rows, prior, groups, allocation_id="expanded")
    assert sorted(g["rows"] for g in result["groups"]) == [[0, 1], [2]]
    family, = [g for g in result["groups"] if g["rows"] == [0, 1]]
    assert family["split"] == "train"
    assert family["prior_anchor_groups"] == [{"source_group": "historical-semantic-family",
                                              "split": "train"}]


def test_prior_exclusion_cannot_become_eligible_after_further_expansion():
    prior = [source(0)]
    rows = [*copy.deepcopy(prior), source(1)]
    rows[1]["negative_passages"].append(copy.deepcopy(prior[0]["positive_passages"][0]))
    result = extend_promptriever_allocation(rows, prior, [
        {"source_group": "old-bridge", "split": "excluded", "rows": [0]}],
        allocation_id="next")
    group, = result["groups"]
    assert group["split"] == "excluded" and group["allocation_basis"] == "prior_exclusion"


def test_changed_prior_payload_or_incomplete_prior_allocation_is_rejected():
    rows, prior, groups = allocation_fixture()
    changed = copy.deepcopy(rows)
    changed[0]["positive_passages"][0]["text"] = "Changed old source"
    with pytest.raises(ValueError, match="source prefix"):
        extend_promptriever_allocation(changed, prior, groups, allocation_id="expanded")
    with pytest.raises(ValueError, match="cover each old row"):
        extend_promptriever_allocation(rows, prior, groups[1:], allocation_id="expanded")
