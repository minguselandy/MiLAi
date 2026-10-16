"""Reader feature boundary and missing-output denominators with the native scorer."""

import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_musique_reader import reader_input, score


def test_reader_sees_only_chosen_sources_without_gold_or_controller_verdict():
    case = {"question": "q", "answer": "private", "stop_reason": "stop_sufficient",
            "candidates": [{"id": "p0", "title": "title", "text": "source",
                            "is_supporting": True},
                           {"id": "p1", "title": "unused", "text": "unselected"}]}
    messages, schema = reader_input(case, ["p0"])
    assert json.loads(messages[1]["content"]) == {"question": "q", "documents": [
        {"id": "p0", "title": "title", "text": "source"}]}
    jsonschema.validate({"answer": "source", "answerable": True, "support_ids": ["p0"]},
                        schema["json_schema"]["schema"])
    _, empty = reader_input(case, [])
    jsonschema.Draft202012Validator.check_schema(empty["json_schema"]["schema"])
    jsonschema.validate({"answer": "", "answerable": False, "support_ids": []},
                        empty["json_schema"]["schema"])


@pytest.mark.local_artifacts
def test_official_pairs_and_orphan_missing_remain_in_full_denominator(tmp_path):
    official = os.environ.get("MILAI_MUSIQUE_OFFICIAL")
    if not official:
        pytest.skip("requires downloaded official MuSiQue metrics")
    selections = tmp_path / "selections"
    labels = []
    for i, (qid, answerable, answer) in enumerate((("q0", True, "blue"),
                                                 ("q0", False, "blue"),
                                                 ("q1", True, "red"))):
        labels.append({"case_id": str(i), "family": qid, "candidate_source_indices": {"p0": 0},
            "source": {"id": qid, "answerable": answerable, "answer": answer,
                       "answer_aliases": [], "paragraphs": [{"idx": 0, "title": qid,
                       "paragraph_text": answer if answerable else "unrelated",
                       "is_supporting": answerable}]}})
        folder = selections / str(i)
        folder.mkdir(parents=True)
        (folder / "k2.json").write_text(json.dumps({"selected_ids": ["p0"]}))
    gold = tmp_path / "labels.jsonl"
    gold.write_text("".join(json.dumps(row) + "\n" for row in labels))
    predictions = tmp_path / "reader" / "predictions" / "arm"
    predictions.mkdir(parents=True)
    for i in (0, 1):
        (predictions / f"{i}.json").write_text(json.dumps({"answer": {
            "answer": "blue" if i == 0 else "", "answerable": i == 0,
            "support_ids": ["p0"] if i == 0 else []}}))
    protocol = {"labels": str(gold), "official_scorer": official,
                "arms": {"arm": {"selection_root": str(selections), "policy": "k2"}}}
    result = score(protocol, tmp_path / "reader", tmp_path / "scores")["arm"]
    assert result["cases"] == 3
    assert result["missing"] == ["2"]
    assert result["answer_em_with_missing_zero"] == 0.5
    assert result["native_metrics_valid_pairs"]["group_answer_sufficiency_f1"] == 1.0
    assert result["planned_pairs"] == result["valid_pairs"] == 1
