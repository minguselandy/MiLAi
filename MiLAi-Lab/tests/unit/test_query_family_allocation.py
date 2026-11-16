"""Shared-corpus allocation must preserve old families, exclusions and query identities."""
import copy

import pytest

from milai_lab.datasets.query_family_allocation import extend_query_families


def fixture():
    rows = [{"query_id": str(i), "only_query": f"question {i}",
             "negative_passages": [{"docid": "shared", "text": "same corpus passage"}]}
            for i in range(8)]
    prior = [{"source_group": "old-train", "split": "train", "rows": [0, 1]},
             {"source_group": "old-dev", "split": "dev", "rows": [2]},
             {"source_group": "old-excluded", "split": "excluded", "rows": [3]}]
    return rows, prior


def test_prior_source_families_stay_whole_but_document_sharing_is_not_a_query_edge():
    rows, prior = fixture()
    before = copy.deepcopy((rows, prior))
    result = extend_query_families(rows, prior, prior_rows=4, allocation_id="query")
    groups = {tuple(g["rows"]): g for g in result["groups"]}
    assert groups[0, 1]["split"] == "train"
    assert groups[2,]["split"] == "dev"
    assert groups[3,]["split"] == "excluded"
    assert len(groups) == 7 and result["counts"]["unanchored_query_families"] == 4
    assert {groups[i,]["split"] for i in range(4, 8)} == {"train", "dev"}
    assert (rows, prior) == before


def test_all_instruction_versions_follow_native_query_and_prior_exclusion():
    rows, prior = fixture()
    rows[4].update(query_id="3-instruct", only_query="different displayed wording")
    result = extend_query_families(rows, prior, prior_rows=4, allocation_id="query")
    group, = [g for g in result["groups"] if 4 in g["rows"]]
    assert group["rows"] == [3, 4] and group["split"] == "excluded"


def test_normalized_query_links_and_cross_prior_split_bridge_are_not_split():
    rows, prior = fixture()
    rows[4].update(query_id="0-instruct", only_query=" QUESTION   2 ")
    result = extend_query_families(rows, prior, prior_rows=4, allocation_id="query")
    group, = [g for g in result["groups"] if 4 in g["rows"]]
    assert group["rows"] == [0, 1, 2, 4] and group["split"] == "excluded"
    assert group["allocation_basis"] == "query_bridge_between_prior_splits"


def test_labels_passage_bodies_and_instruction_text_do_not_allocate_queries():
    rows, prior = fixture()
    expected = extend_query_families(rows, prior, prior_rows=4, allocation_id="query")
    for i, row in enumerate(rows):
        row.update(positive_passages=[{"docid": str(i), "text": "changed"}],
                   negative_passages=[], only_instruction="opposite", teacher_score=100)
    assert extend_query_families(rows, prior, prior_rows=4, allocation_id="query") == expected


@pytest.mark.parametrize("mutation", ["missing_prior_row", "duplicate_prior_row", "empty_query"])
def test_incomplete_identity_mapping_is_not_repaired(mutation):
    rows, prior = fixture()
    if mutation == "missing_prior_row":
        prior[0]["rows"].pop()
    elif mutation == "duplicate_prior_row":
        prior[0]["rows"].append(0)
    else:
        rows[5]["only_query"] = " "
    with pytest.raises(ValueError):
        extend_query_families(rows, prior, prior_rows=4, allocation_id="query")
