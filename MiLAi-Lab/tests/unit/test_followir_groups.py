"""No row split may separate a connected source/topic component."""
from milai_lab.datasets.followir import group_followir


def test_topic_query_and_document_links_are_transitive_and_labels_do_not_select_split():
    rows = [
        {"id": "track-A---1", "query": "Requested topic", "document": "document A",
         "label": "true"},
        {"id": "track-A---1", "query": "requested   topic", "document": "document B",
         "label": "false"},
        {"id": "track-B---9", "query": "Requested topic", "document": "shared document",
         "label": "true"},
        {"id": "track-C---7", "query": "Different query", "document": "shared document",
         "label": "false"},
        {"id": "track-D---2", "query": "Independent topic", "document": "document D",
         "label": "true"},
    ]
    groups = group_followir(rows, dev_fraction=0.5)
    assert sorted(g["rows"] for g in groups) == [[0, 1, 2, 3], [4]]
    assert {g["split"] for g in groups} == {"train", "dev"}
    flipped = group_followir([{**r, "label": "false" if r["label"] == "true" else "true"}
                              for r in rows], dev_fraction=0.5)
    assert [(g["rows"], g["split"]) for g in groups] == [
        (g["rows"], g["split"]) for g in flipped]
