"""The state probe removes only declared read fields and preserves action space."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import decision_payload
from probe_reader_state import prepare, project, score


def test_projection_keeps_question_candidates_actions_and_open_ids():
    read = [{"id": "p4", "title": "bridge", "text": "visible premise"}]
    remaining = [{"id": "p9", "title": "answer", "text": "another premise"}]
    full = decision_payload("question", read, remaining)
    original = copy.deepcopy(full)
    titles, ids = project(full, "titles_only"), project(full, "ids_only")
    assert full == original
    assert titles["state"]["read_evidence"] == [{"id": "p4", "title": "bridge"}]
    assert ids["state"]["read_evidence"] == [{"id": "p4"}]
    for payload in (titles, ids):
        assert payload["questions"] == full["questions"]
        assert payload["state"]["question"] == full["state"]["question"]
        assert payload["state"]["candidates"] == full["state"]["candidates"]
    empty = decision_payload("question", [], remaining)
    assert project(empty, "titles_only") == project(empty, "ids_only") == empty


def test_preparation_uses_recorded_prefixes_without_reading_gold(tmp_path):
    candidates = [{"id": f"p{i}", "title": str(i), "text": f"source {i}"} for i in range(3)]
    case = {"case_id": "row-7", "question": "q", "candidates": candidates}
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(case) + "\n")
    selector, fixed = tmp_path / "selector", tmp_path / "fixed"
    write_json(selector / "run.json", {"status": "COMPLETED", "cases": str(cases),
        "checkpoint": "fixture", "max_len": 8192, "head_max_len": 512})
    write_json(fixed / "run.json", {"status": "COMPLETED"})
    traces = []
    for step in range(2):
        path = tmp_path / "original" / str(step) / "input.json"
        write_json(path, decision_payload("q", candidates[:step], candidates[step:]))
        traces.append({"source": str(path)})
    write_json(fixed / "row-7/k4.json", {"selected_ids": ["p0", "p1"],
                                       "controller_trace": traces})
    result = prepare({"selector": str(selector), "fixed_four": str(fixed),
                      "labels": "must-not-open", "source_review": "must-not-open"},
                     tmp_path / "prepared")
    assert result["planned_positions"] == 4
    assert result["unchanged_empty_positions"] == result["maximum_new_forwards"] == 2
    assert read_json(tmp_path / "prepared/inputs/row-7/1/ids_only.json")["state"][
        "read_evidence"] == [{"id": "p0"}]


def test_review_does_not_open_labels_while_predictions_are_running(tmp_path):
    write_json(tmp_path / "run.json", {"status": "RUNNING"})
    with pytest.raises(ValueError, match="must be closed"):
        score(tmp_path / "missing-prepared", tmp_path)
