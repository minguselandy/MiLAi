"""Review provenance and masks are mechanical contracts, not an automated semantic judge."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_conditional_applicability import fixture

from milai_lab.datasets.conditional_applicability import compile_condition_union
from milai_lab.datasets.conditional_reviews import (
    apply_development_applicability_reviews,
    apply_training_applicability_reviews,
    binary_label,
)
from milai_lab.harness.artifact_io import read_json, read_jsonl


def reviewed_fixture(decision="satisfies"):
    raw, groups = fixture()
    result = compile_condition_union(raw, groups, "promptriever")
    row, = [r for r in result["matrix"] if not r["gold"]]
    request = row["state"]["task"]["retrieval_request"]
    text = row["state"]["candidate"]["text"]
    review = {"review_id": "mechanical-review", "event_id": row["metadata"]["event_id"],
        "family": row["metadata"]["family"], "input_binding": {"query": request["query"],
            "purpose": request["read_goal"]["purpose"], "candidate": row["state"]["candidate"]},
        "decision": decision, "rationale": "Mechanical source-binding fixture, not a real grade.",
        "anchors": [{"field": "text", "range": [0, len(text)], "quote": text}],
        "basis": "mechanical fixture", "factuality_independently_verified": False}
    return result, review


def test_new_known_cell_changes_only_its_gold_provenance_and_affected_pair():
    native, review = reviewed_fixture()
    before = copy.deepcopy((native, review))
    result = apply_training_applicability_reviews(native["matrix"], native["pairs"], [review])
    assert (native, review) == before
    assert result["counts"]["new_known_cells"] == 1
    assert result["counts"]["comparison_kind"] == {"change": 3, "stable": 1}
    for a, z in zip(native["matrix"], result["matrix"], strict=True):
        assert all(a[key] == z[key] for key in ("state", "questions"))
        assert a["metadata"]["native_judgments"] == z["metadata"]["native_judgments"]
        if a["metadata"]["event_id"] != review["event_id"]:
            assert a == z
        else:
            assert binary_label(z) is True
            assert z["metadata"]["label_status"] == "source_author_reviewed"
    added, = [p for p in result["pairs"] if "label_origins" in p]
    assert added["reason"] == "native_and_source_author_judgments"
    assert added["label_origins"] == {"left": "source_author_review", "right": "native"}


def test_unknown_review_remains_unlabelled_and_cannot_be_applied_twice():
    native, review = reviewed_fixture("unknown")
    result = apply_training_applicability_reviews(native["matrix"], native["pairs"], [review])
    row, = [r for r in result["matrix"] if r["metadata"]["event_id"] == review["event_id"]]
    assert row["gold"] == {} and row["metadata"]["label_status"] == "unjudged"
    assert result["counts"]["new_known_cells"] == 0
    assert result["counts"]["reviewed_still_unknown_cells"] == 1
    assert result["counts"]["comparison_kind"] == native["counts"]["comparison_kind"]
    with pytest.raises(ValueError, match="originally unjudged"):
        apply_training_applicability_reviews(result["matrix"], result["pairs"], [review])


@pytest.mark.parametrize("mutation", ["purpose", "body", "family", "quote", "duplicate"])
def test_review_binding_or_provenance_cannot_drift(mutation):
    native, review = reviewed_fixture()
    records = [copy.deepcopy(review)]
    if mutation == "purpose":
        records[0]["input_binding"]["purpose"] = "Different requirement"
    elif mutation == "body":
        records[0]["input_binding"]["candidate"]["text"] = "Different material"
    elif mutation == "family":
        records[0]["family"] = "Different family"
    elif mutation == "quote":
        records[0]["anchors"][0]["quote"] = "Not in the source"
    else:
        records.append(copy.deepcopy(review))
    with pytest.raises(ValueError):
        apply_training_applicability_reviews(native["matrix"], native["pairs"], records)


@pytest.mark.parametrize("kind", ["native_known", "native_conflict", "dev"])
def test_native_judgments_and_nontraining_splits_are_not_overwritten(kind):
    native, review = reviewed_fixture()
    row, = [r for r in native["matrix"] if r["metadata"]["event_id"] == review["event_id"]]
    if kind == "native_known":
        row["gold"] = {"applicability": {"probabilities": {
            "satisfies": 0., "does_not_satisfy": 1.}}}
        row["metadata"]["label_status"] = "known"
    elif kind == "native_conflict":
        row["metadata"]["label_status"] = "conflicting_native_judgments"
        row["metadata"]["native_judgments"] = [{"label": True}, {"label": False}]
    else:
        row["metadata"]["split"] = "dev"
    with pytest.raises(ValueError, match="originally unjudged training"):
        apply_training_applicability_reviews(native["matrix"], native["pairs"], [review])


def test_nonbinary_uncertainty_is_not_silently_turned_into_a_negative():
    with pytest.raises(ValueError, match="known binary label"):
        binary_label({"gold": {"applicability": {"probabilities": {
            "satisfies": .5, "does_not_satisfy": .5}}}})


def test_no_reviews_preserve_the_complete_native_dataset():
    native, _ = reviewed_fixture()
    result = apply_training_applicability_reviews(native["matrix"], native["pairs"], [])
    assert result["matrix"] == native["matrix"] and result["pairs"] == native["pairs"]


@pytest.mark.parametrize("decision", ["satisfies", "unknown"])
def test_development_reviews_keep_split_inputs_native_gold_and_unknowns(decision):
    native, review = reviewed_fixture(decision)
    with pytest.raises(ValueError, match="originally unjudged development"):
        apply_development_applicability_reviews(native["matrix"], native["pairs"], [review])
    for row in native["matrix"]:
        row["metadata"]["split"] = "dev"
    for pair in native["pairs"]:
        pair["split"] = "dev"
    before = copy.deepcopy(native)
    result = apply_development_applicability_reviews(native["matrix"], native["pairs"], [review])
    assert native == before
    for a, z in zip(native["matrix"], result["matrix"], strict=True):
        assert z["metadata"]["split"] == "dev"
        assert a["state"] == z["state"] and a["questions"] == z["questions"]
        if a["gold"]:
            assert a == z
    assert result["counts"]["new_known_cells"] == int(decision != "unknown")
    assert result["counts"]["reviewed_still_unknown_cells"] == int(decision == "unknown")
    assert all(pair["split"] == "dev" for pair in result["pairs"])


@pytest.mark.parametrize("split", ["train", "dev"])
def test_cli_separate_export_keeps_native_files_and_unknown_review_positions(tmp_path, split):
    native, review = reviewed_fixture("unknown")
    for row in native["matrix"]:
        row["metadata"]["split"] = split
    for values in (native["pairs"], native["units"]):
        for value in values:
            value["split"] = split
    source = tmp_path / "native"
    source.mkdir()
    for name, rows in [("matrix", native["matrix"]), ("condition-pairs", native["pairs"])]:
        (source / (name + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in rows))
    (source / "groups.json").write_text(json.dumps({"groups": []}))
    (source / "query-units.json").write_text(json.dumps({"units": native["units"]}))
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"source_matrix": str(source / "matrix.jsonl"),
        "families": [{"selected_event_ids": [review["event_id"]]}]}))
    judgments = tmp_path / "reviews.json"
    judgments.write_text(json.dumps({"selection": str(selection), "records": [review]}))
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "reviewed"
    command = [sys.executable, str(root / "tools/apply_conditional_applicability_reviews.py"),
               "--split", split, str(source), str(judgments), str(output)]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    subprocess.run(command, env=env, check=True, capture_output=True)  # noqa: S603
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    assert read_json(output / "preparation.json")["counts"]["reviewed_still_unknown_cells"] == 1
    assert len(read_jsonl(output / (split + ".jsonl"))) == 7
    other = "train" if split == "dev" else "dev"
    assert not (output / (other + ".jsonl")).exists()
    mismatched = subprocess.run(  # noqa: S603
        [*command[:3], other, *command[4:-1], str(tmp_path / "wrong-split")],
        env=env, capture_output=True)
    assert mismatched.returncode != 0 and b"never relabel partitions" in mismatched.stderr
    assert not (tmp_path / "wrong-split").exists()
    selection.write_text(json.dumps({"source_matrix": str(source / "matrix.jsonl"),
        "families": [{"selected_event_ids": [review["event_id"], "missing-position"]}]}))
    failed = subprocess.run([*command[:-1], str(tmp_path / "bad")], env=env,  # noqa: S603
                            capture_output=True)
    assert failed.returncode != 0 and b"every preselected review position" in failed.stderr
    assert not (tmp_path / "bad").exists()
