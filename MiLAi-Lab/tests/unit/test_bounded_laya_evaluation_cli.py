"""Check exported-checkpoint evaluation wiring with a model stub and isolated test ledger."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import evaluate_bounded_laya
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


@pytest.mark.parametrize("projection", ["shared", "shared_request_text"])
def test_operation_evaluator_projects_public_input_and_uses_operation_metrics(
    tmp_path, monkeypatch, projection,
):
    pytest.importorskip("torch")
    rows = [{"state": {"task": {"retrieval_request": {"query": "Question\u0085\u2028\u2029end"}},
                      "pending_candidates": []},
             "questions": {"next": {"type": "choice", "instructions": "Choose",
                                     "criteria": {"finish": "HANDOFF"}}},
             "gold": {"next": {"probabilities": {"finish": 1.0}}},
             "metadata": {"family": "f", "label_status": "reviewed",
                          "action_kinds": {"finish": "HANDOFF"}}}]
    data, budget, output = tmp_path / "dev.jsonl", tmp_path / "budget.json", tmp_path / "run"
    data.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n")
    budget.write_text(json.dumps(RunBudget(RunLimits(), budget).state))
    observed = []

    class StubDecision:
        def __init__(self, checkpoint, max_len, head_max_len, device):
            self.model = SimpleNamespace(
                parameters=lambda: iter([SimpleNamespace(dtype="float32")]))
            self.counters = {"forwards": 0, "sequence_rows": 0, "input_tokens": 0}
            assert device == "cpu"

        def predict(self, payload):
            observed.append(payload)
            self.counters.update(forwards=1, sequence_rows=1, input_tokens=10)
            return {"choice": "finish", "input_tokens": 10}

    monkeypatch.setattr(evaluate_bounded_laya, "NativeDecision", StubDecision)
    monkeypatch.setattr(sys, "argv", ["evaluate_bounded_laya", str(data),
        str(tmp_path / "checkpoint"), str(output), "--budget", str(budget),
        "--task", "memory_operation", "--operation-state", projection,
        "--compute-phase", "test_exported_operations"])
    evaluate_bounded_laya.main()
    result = json.loads((output / "results.json").read_text())
    assert result["counts"] == {"labelled": 1, "accepted": 1}
    assert result["selected_operations"] == {"HANDOFF": {"selected": 1, "accepted": 1}}
    assert set(observed[0]) == {"state", "questions"}
    if projection == "shared_request_text":
        from audit_request_text import recover_request_fields

        assert recover_request_fields(
            observed[0]["state"]["task"]["request_text"]) == rows[0]["state"]["task"]
    else:
        assert observed[0]["state"]["task"] == rows[0]["state"]["task"]
    run = json.loads((output / "run.json").read_text())
    assert run["status"] == "COMPLETED" and run["completed_states"] == 1
    assert run["task"] == "memory_operation" and run["operation_state"] == projection
    assert json.loads(budget.read_text())["compute"]["test_exported_operations"]["forwards"] == 1
