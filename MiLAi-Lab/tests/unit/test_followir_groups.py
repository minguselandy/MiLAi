"""No row split may separate a connected source/topic component."""
from milai_lab.datasets.followir import applicability_row, group_followir


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


def test_candidate_targets_and_teacher_scores_never_enter_model_input():
    row = {"id": "topic-1", "query": "Options for a trip", "instruction": "Only rail travel",
           "document": "A train route with transfers.", "label": "true", "score": 0.83}
    group = {"source_group": "followir-topic-0000", "split": "dev"}
    positive = applicability_row(row, 3, group)
    negative = applicability_row({**row, "label": "false", "score": 0.12}, 3, group)
    assert positive["state"] == negative["state"] == {
        "task": {"retrieval_request": {
            "query": row["query"], "read_goal": {"purpose": row["instruction"]}}},
        "candidate": {"text": row["document"]},
    }
    assert positive["questions"] == negative["questions"]
    assert positive["gold"]["applicability"]["probabilities"] == {
        "satisfies": 1.0, "does_not_satisfy": 0.0}
    assert negative["gold"]["applicability"]["probabilities"] == {
        "satisfies": 0.0, "does_not_satisfy": 1.0}
    assert positive["metadata"]["split"] == "dev"
    assert positive["metadata"]["family"] == group["source_group"]
    assert positive["metadata"]["task"] == "instruction_applicability"


def test_changed_requirement_is_visible_without_inventing_operation_state():
    row = {"id": "topic-1", "query": "Trip", "instruction": "Rail only",
           "document": "Travel options", "label": "false"}
    group = {"source_group": "followir-topic-0000", "split": "train"}
    before = applicability_row(row, 0, group)
    after = applicability_row({**row, "instruction": "Air travel only"}, 1, group)
    assert before["state"]["candidate"] == after["state"]["candidate"]
    assert before["state"]["task"] != after["state"]["task"]
    assert set(before["questions"]) == {"applicability"}
    assert set(before["state"]) == {"task", "candidate"}
