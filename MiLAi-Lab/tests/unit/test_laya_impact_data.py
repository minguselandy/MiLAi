"""The event split precedes unit expansion; review metadata never becomes evidence."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_laya_impact import prepare


def event(tmp_path, identity, family, split):
    schema = {"properties": {"roots": {"items": {"enum": ["u7", "u2"]}}}}
    payload = {"observed_date": "2032-06-02", "delivery": {"event": "A changes"},
               "response_schema": schema}
    (tmp_path / f"{identity}.json").write_text(json.dumps({"messages": [
        {"role": "user", "content": json.dumps(payload)}]}))
    return {"event_id": identity, "family_id": family, "split": split,
            "request_path": f"{identity}.json", "future_answer": "private review only",
            "labels": {"u7": {"label": "direct_root", "reason": "actual source"},
                       "u2": {"label": None, "reason": "missing source"}}}


def test_masked_unit_stays_a_question_and_metadata_is_not_model_input(tmp_path):
    row = event(tmp_path, "a", "history", "train")
    output = prepare([row], tmp_path)["train"][0]
    assert output["state"] == {"observed_date": "2032-06-02", "delivery": {"event": "A changes"}}
    assert len(output["questions"]) == 2
    assert output["expected"] == {"unit_0": "direct_root"}
    assert "u7" in output["questions"]["unit_0"]["instructions"]
    assert "private review only" not in json.dumps(output["state"])
    assert output["metadata"]["family_id"] == "history"


def test_family_cannot_cross_splits_even_for_different_event_names(tmp_path):
    rows = [event(tmp_path, "a", "same-history", "train"),
            event(tmp_path, "b", "same-history", "dev")]
    with pytest.raises(ValueError, match="crosses splits"):
        prepare(rows, tmp_path)
