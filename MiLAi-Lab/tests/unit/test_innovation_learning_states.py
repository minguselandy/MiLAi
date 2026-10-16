"""The evaluation reopens an actual source bank with its original public-turn authority."""

import json
import sys
from pathlib import Path

from langgraph.store.sqlite import SqliteStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from innovation_learning_states import components, main


def test_saved_generation_applies_to_copy_after_public_turn_rebind(tmp_path, monkeypatch):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"case_id": "actual-source",
        "source": "The paper pass is valid.", "reported_at": "2038-02-10T09:00:00+08:00"}]}))
    root = tmp_path / "evaluation"
    argv = ["learning-states", str(cases), str(root), "--interface", "native",
            "--maintenance-mode", "semantic_delta_v2"]
    monkeypatch.setattr(sys, "argv", [*argv, "--phase", "prepare"])
    main()
    generations = tmp_path / "generations"
    generations.mkdir()
    (generations / "base.json").write_text(json.dumps({"objective": "base", "sequences": [{
        "example_id": "actual-source", "finish_reason": "stop", "text": json.dumps({
            "creates": [{"nodes": [{"text": "The paper pass is valid.", "basis": "e1",
                                     "kind": "reported"}]}]})}]}))
    monkeypatch.setattr(sys, "argv", [*argv, "--phase", "apply", "--generations", str(generations)])
    main()
    result = json.loads((root / "applied-results.json").read_text())["results"][0]
    assert result["before"] == [] and result["status"] == "applied"
    assert result["receipts"][0]["effect"] == "memory_only"
    assert result["after"][0]["value"]["edit_state"]["units"][0]["text"] == (
        "The paper pass is valid.")
    seed = root / "source-banks/actual-source"
    with SqliteStore.from_conn_string(str(seed / "memory.sqlite")) as store:
        service, _ = components(store, seed, "actual-source", "semantic_delta_v2")
        assert service.records() == []
