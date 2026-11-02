"""Native-only judgment joins, honest unknowns and paired condition correctness."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from milai_lab.datasets.conditional_applicability import (
    compile_condition_union,
    score_condition_pairs,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl


def passage(name, *, title=None, text=None):
    return {"docid": name, "title": title or "Title " + name, "text": text or "Body " + name,
            "explanation": "TEACHER_SECRET", "followir_score": 999}


def source(instruction, positive, negatives, new=()):
    return {"query_id": "q-instruct" if instruction else "q", "only_query": "Fixed query",
            "only_instruction": instruction, "has_instruction": bool(instruction),
            "query": "unused combined field", "positive_passages": positive,
            "negative_passages": negatives, "new_negatives": list(new)}


def fixture():
    a, b, c, d = [passage(name) for name in "abcd"]
    rows = {0: source("", [a], [b, d]), 1: source("Recent only", [b], [a, d], [c])}
    groups = [{"source_group": "family", "split": "train", "rows": [0, 1]}]
    return rows, groups


def test_union_retains_missing_cells_and_never_uses_other_conditions_to_fill_labels():
    rows, groups = fixture()
    before = copy.deepcopy((rows, groups))
    result = compile_condition_union(rows, groups, "promptriever")
    assert result["counts"]["cell_status"] == {"known": 7, "unjudged": 1}
    assert result["counts"]["comparison_kind"] == {"change": 2, "stable": 1, "unknown": 1}
    missing, = [r for r in result["matrix"] if not r["gold"]]
    assert missing["metadata"]["native_docids"] == ["c"]
    assert missing["metadata"]["native_judgments"] == []
    assert missing["state"]["task"]["retrieval_request"]["read_goal"]["purpose"] == ""
    assert missing["state"]["candidate"] == {"title": "Title c", "text": "Body c"}
    for row in result["matrix"]:
        visible = json.dumps({key: row[key] for key in ("state", "questions")})
        assert "TEACHER_SECRET" not in visible and "followir_score" not in visible
        assert "native_docid" not in visible and "label_status" not in visible
    assert (rows, groups) == before


@pytest.mark.parametrize("changed_field", ["title", "text"])
def test_same_native_docid_with_changed_candidate_does_not_transfer_judgments(changed_field):
    a = passage("same-id")
    different = {**a, changed_field: "changed literal value"}
    rows = {0: source("", [a], []), 1: source("Condition", [], [different])}
    groups = [{"source_group": "family", "split": "train", "rows": [0, 1]}]
    result = compile_condition_union(rows, groups, "promptriever")
    assert result["units"][0]["native_docid_versions"] == {"same-id": [0, 1]}
    assert result["counts"]["comparison_kind"] == {"unknown": 2}
    assert result["counts"]["cell_status"] == {"known": 2, "unjudged": 2}


def test_identical_candidate_aliases_preserve_conflicting_native_judgments_as_masked():
    a = passage("a")
    alias = {**a, "docid": "alias"}
    rows = {0: source("", [a], [alias]), 1: source("Condition", [a], [])}
    groups = [{"source_group": "family", "split": "train", "rows": [0, 1]}]
    result = compile_condition_union(rows, groups, "promptriever")
    assert len(result["matrix"]) == 2
    first = result["matrix"][0]
    assert first["metadata"]["native_docids"] == ["a", "alias"]
    assert first["gold"] == {}
    assert [j["label"] for j in first["metadata"]["native_judgments"]] == [True, False]
    assert result["pairs"][0]["reason"] == "conflicting_native_judgments"


def test_query_changes_are_not_misattributed_to_purpose_changes():
    rows, groups = fixture()
    rows[1]["only_query"] = "Another query"
    result = compile_condition_union(rows, groups, "promptriever")
    assert all(pair["kind"] == "unknown" and pair["reason"] == "query_text_also_changed"
               for pair in result["pairs"])
    assert result["counts"]["cell_status"]["known"] == 7


def test_paired_accuracy_requires_both_sides_correct_and_excludes_unknown_denominator():
    rows, groups = fixture()
    result = compile_condition_union(rows, groups, "promptriever")
    predictions = []
    for row in result["matrix"]:
        target = row["gold"].get("applicability", {}).get("probabilities", {})
        predictions.append({"choice": max(target, key=target.__getitem__)
                            if target else "satisfies"})
    report = score_condition_pairs(result["matrix"], result["pairs"], predictions)["strata"]
    assert report["change"]["family_macro_query_pair_joint_accuracy"] == 1
    assert report["stable"]["family_macro_query_pair_joint_accuracy"] == 1
    assert report["unknown"]["family_macro_query_pair_joint_accuracy"] is None
    assert report["unknown"]["families_with_judged_pairs"] == 0
    flipped = [{"choice": "does_not_satisfy" if p["choice"] == "satisfies" else "satisfies"}
               for p in predictions]
    wrong = score_condition_pairs(result["matrix"], result["pairs"], flipped)["strata"]
    assert wrong["change"]["prediction_change_rate"] == 1
    assert wrong["change"]["family_macro_query_pair_joint_accuracy"] == 0
    assert wrong["stable"]["prediction_change_rate"] == 0
    assert wrong["stable"]["family_macro_query_pair_joint_accuracy"] == 0


def test_followir_candidate_labels_are_not_native_ranking_or_missing_negatives():
    rows = {0: {"id": "topic", "query": "Travel", "instruction": "Rail", "document": "Train",
                "label": "true"},
            1: {"id": "topic", "query": "Travel", "instruction": "Air", "document": "Train",
                "label": "false"},
            2: {"id": "topic", "query": "Travel", "instruction": "Rail", "document": "Bus",
                "label": "false"}}
    group = [{"source_group": "topic-family", "split": "train", "rows": [0, 1, 2]}]
    result = compile_condition_union(rows, group, "followir")
    assert result["counts"]["comparison_kind"] == {"change": 1, "unknown": 1}
    assert result["counts"]["cell_status"] == {"known": 3, "unjudged": 1}
    assert all("title" not in row["state"]["candidate"] for row in result["matrix"])


def test_pair_counts_do_not_replace_query_then_family_averages():
    matrix, pairs, predictions = [], [], []
    for family, query, count, correct in [("A", "one", 1, True),
                                          ("A", "many", 3, False), ("B", "one", 1, True)]:
        for index in range(count):
            names = [f"{family}/{query}/{index}/{side}" for side in ("left", "right")]
            matrix.extend({"metadata": {"event_id": name}} for name in names)
            pairs.append({"family": family, "query_unit": query, "kind": "change",
                          "left_event": names[0], "right_event": names[1],
                          "left_label": True, "right_label": False})
            predictions.extend({"choice": choice} for choice in (
                ("satisfies", "does_not_satisfy") if correct else
                ("does_not_satisfy", "satisfies")))
    result = score_condition_pairs(matrix, pairs, predictions)["strata"]["change"]
    assert result["by_family_joint_accuracy"] == {"A": .5, "B": 1.}
    assert result["family_macro_query_pair_joint_accuracy"] == .75


def test_cli_preserves_allocated_split_and_unicode_and_exports_only_known_training_cells(tmp_path):
    rows, groups = fixture()
    rows[0]["positive_passages"][0]["text"] = "one\u2028two\u2029three"
    source_file, allocation = tmp_path / "source.jsonl", tmp_path / "groups.json"
    source_file.write_text("".join(json.dumps(rows[i], ensure_ascii=False) + "\n" for i in rows)
                           + json.dumps({"unselected_dev_payload": "DEV_SECRET"}) + "\n")
    allocation.write_text(json.dumps({"groups": [*groups,
        {"source_group": "dev-family", "split": "dev", "rows": [2]}]}))
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "prepared"
    subprocess.run(  # noqa: S603 -- repository CLI, test-owned files, no model/network
        [sys.executable, str(root / "tools/prepare_conditional_applicability.py"), str(source_file),
         str(allocation), str(output), "--dataset", "promptriever", "--max-groups", "1"],
        env={**os.environ, "PYTHONPATH": str(root / "src")}, check=True, capture_output=True)
    matrix, training = read_jsonl(output / "matrix.jsonl"), read_jsonl(output / "train.jsonl")
    assert training == [row for row in matrix if row["gold"]]
    assert read_json(output / "groups.json")["groups"] == groups
    assert all(row["metadata"]["split"] == "train" for row in matrix)
    assert "DEV_SECRET" not in json.dumps(matrix)
    assert any(row["state"]["candidate"]["text"] == "one\u2028two\u2029three" for row in matrix)
