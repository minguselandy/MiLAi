"""Collection executes real Source/Store operations; this test scripts only generation."""
import importlib.util
import itertools
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("order", list(itertools.permutations(("repeat", "unrelated", "changed"))))
def test_collection_preserves_actual_feedback_and_leaves_actions_unlabelled(tmp_path, order):
    lab = Path(__file__).parents[2]
    spec = importlib.util.spec_from_file_location("collect_operations",
        lab / "tools/collect_memory_operation_states.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = json.loads((lab / "data/fixtures/dynamic-memory-control/operation-families-v1.json"
                          ).read_text())
    family = fixture["families"][0]
    family["phase_order"] = ["cold", *order]
    family["offline_review"] = {"before_answer": "HIDDEN_GOLD"}
    inputs, rows = [], []

    def call(messages, schema):
        payload = json.loads(messages[-1]["content"])
        inputs.append(payload)
        assert "HIDDEN_GOLD" not in str(messages)
        return {"scope": "The parcel conditions", "nodes": [
            {"id": "n" + s["id"][1:], "text": s["text"], "evidence": [s["id"]],
             "kind": "reported"} for s in payload["sources"]],
            "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

    result = module.collect_family(family, tmp_path / "family", call=call,
        token_count=len, material_limit=100000, append=rows.append, source_version="test")
    assert len(inputs) == 2
    assert result["phases"]["repeat"]["actions"] == ["use_view", "handoff"]
    assert result["phases"]["unrelated"]["actions"] == ["use_view", "handoff"]
    assert result["phases"]["changed"]["view"]["revision"] == 2
    assert rows and all(not row["gold"] for row in rows)
    assert rows[0]["state"]["visible_evidence"] == []
    assert all("content" in event for event in rows[0]["state"]["new_events"])
    assert set(rows[0]["metadata"]["source_id_mapping"].values()) == {"a", "b", "c", "query:cold"}
    assert "HIDDEN_GOLD" not in str([r["state"] for r in rows])
    assert all(not phase["reader_executed"] for phase in result["phases"].values())
