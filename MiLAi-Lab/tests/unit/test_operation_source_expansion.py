"""New operation sources inherit exclusions without turning native references into gold."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from audit_source_selection import panel
from prepare_operation_source_expansion import boundary_issues, inherited_rows, training_clusters


def record(family, title, text, supporting=True):
    return {"metadata": {"row": 0, "family": family},
            "source": {"question": f"question {family}", "paragraphs": [
                {"idx": 0, "title": title, "paragraph_text": text, "is_supporting": supporting}]}}


def test_later_training_partition_removes_rows_and_never_relabels_a_role():
    rows = [{"row": i, "family": f"f{i}", "question_id": f"2hop__{i}",
             "split": "train", "included": True} for i in range(3)]
    assert inherited_rows([rows, rows[1:]]) == rows[1:]
    changed = copy.deepcopy(rows[1:])
    changed[0]["split"] = "dev"
    with pytest.raises(ValueError, match="split"):
        inherited_rows([rows, changed])


def test_target_title_overlap_catches_different_text_without_exporting_protected_content():
    candidate = record("new", "same title", "new passage")
    protected = panel([record("held", "same title", "PROTECTED TEXT")], {})
    issues = boundary_issues([candidate], {"reserved": protected})
    assert issues[0]["counts"]["left_target_title_in_right_pool"] == 1
    assert issues[0]["counts"]["left_target_in_right_pool"] == 0
    assert "PROTECTED TEXT" not in str(issues)


def test_shared_background_alone_is_reported_without_becoming_target_overlap():
    candidate = record("new", "background", "shared", supporting=False)
    protected = panel([record("held", "background", "shared", supporting=False)], {})
    assert boundary_issues([candidate], {"reserved": protected}) == []


def test_shared_train_targets_form_transitive_clusters_without_rewriting_families():
    records = [record("old", "alpha", "a"), record("new", "alpha", "b"),
               record("new", "beta", "c"), record("next", "beta", "d")]
    original = copy.deepcopy(records)
    assert training_clusters(records, {"old", "new", "next", "isolated"}) == [
        ["isolated"], ["new", "next", "old"]]
    assert records == original


def test_source_expansion_to_public_collection_preserves_unicode_but_excludes_native_gold(
    tmp_path, monkeypatch,
):
    import prepare_host_intent_t1
    import prepare_operation_source_expansion
    from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json

    native = {"id": "2hop__1_2", "question": "What is supported?", "answer": "OFFLINE GOLD",
              "answerable": False, "question_decomposition": [{"answer": "HIDDEN"}],
              "paragraphs": [{"idx": 0, "title": "Document", "is_supporting": True,
                              "paragraph_text": "one\u0085two\u2028three\u2029four"}]}
    source, metadata = tmp_path / "source.jsonl", tmp_path / "metadata.jsonl"
    source.write_text(json.dumps(native, ensure_ascii=False) + "\n")
    metadata.write_text(json.dumps({"row": 0, "question_id": native["id"], "family": "family",
                                    "split": "train", "included": True}) + "\n")
    protocol, admitted = tmp_path / "protocol.json", tmp_path / "admitted"
    write_json(protocol, {"metadata_files": [str(metadata)], "seed": 0,
        "source_jsonl": str(source), "protected_panels": [], "normalized_panels": [],
        "dataset": "public_train", "new_family_target": 1,
        "existing_operation_train_families": [], "existing_normalized_records": []})
    monkeypatch.setattr(sys, "argv", ["prepare", str(protocol), str(admitted)])
    prepare_operation_source_expansion.main()
    views = read_jsonl(admitted / "source-review-inputs.jsonl")
    assert "answer" not in views[0] and "is_supporting" not in views[0]["paragraphs"][0]
    allocation, old = tmp_path / "allocation.json", tmp_path / "old.json"
    public = tmp_path / "public"
    write_json(old, {"histories": []})
    write_json(allocation, {
        "normalized_original_sources": str(admitted / "offline-references.jsonl"),
        "new_sources": {"train": [{"dataset": "public_train", "family": "family",
                                   "question_id": native["id"], "source_rows": [0]}], "dev": []},
        "primary_source_groups": {"train": 1, "dev": 0}})
    monkeypatch.setattr(sys, "argv", ["prepare", str(allocation), str(old), str(public)])
    prepare_host_intent_t1.main()
    request = read_json(public / "new-histories.json")["histories"][0]["requests"][0]
    assert request["sources"][0]["content"] == "Document\none\u0085two\u2028three\u2029four"
    assert "OFFLINE GOLD" not in json.dumps(request) and "HIDDEN" not in json.dumps(request)
