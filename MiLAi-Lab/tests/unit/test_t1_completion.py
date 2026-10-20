"""Completion checks use temporary synthetic artifacts, never real model jobs."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_host_intent_t1_completion as completion
from milai_lab.harness.artifact_io import write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from retrieval_mixture import project_mixed_row, score_mixed_predictions


def export_fixture(tmp_path):
    operation = {
        "state": {"task": {"request": "Which date?"}},
        "questions": {"next": {"type": "choice", "criteria": {"read": "READ", "done": "HANDOFF"}}},
        "gold": {"next": {"probabilities": {"read": 1.0, "done": 0.0}}},
        "metadata": {"task": "memory_operation", "component": "history", "state_id": 0,
                     "family": "one", "label_status": "reviewed",
                     "action_kinds": {"read": "READ", "done": "HANDOFF"}},
    }
    instruction = {
        "state": {"task": {"retrieval_request": {"query": "date"}}},
        "questions": {"applicability": {"type": "choice",
                                       "criteria": {"satisfies": "yes", "no": "no"}}},
        "gold": {"applicability": {"probabilities": {"satisfies": 1.0, "no": 0.0}}},
        "metadata": {"task": "instruction_applicability", "component": "instructions",
                     "state_id": 1, "family": "topic"},
    }
    rows = [operation, instruction]
    common, old_data = tmp_path / "common.jsonl", tmp_path / "old.jsonl"
    common.write_text("".join(json.dumps(row) + "\n" for row in rows))
    old_data.write_text(json.dumps(operation) + "\n")
    fit, output, ledger = tmp_path / "fit", tmp_path / "evaluation", tmp_path / "budget.json"
    write_json(fit / "run.json", {"dev_source": str(old_data)})
    write_json(output / "run.json", {"status": "COMPLETED", "completed_states": 2,
                                     "loaded_weight_dtype": "torch.float32"})
    old = {"choice": "read", "logits": {"read": .5, "done": .4},
           "input_tokens": 10, "truncated": False}
    predictions = [{**old, "choice": "done", "logits": {"read": .41, "done": .49}},
                   {"choice": "satisfies", "logits": {"satisfies": 1.0, "no": 0.0},
                    "input_tokens": 10, "truncated": False}]
    write_json(fit / "dev/524/0.json", old)
    write_json(fit / "dev/524/summary.json", score_mixed_predictions([operation], [old]))
    for i, (row, prediction) in enumerate(zip(rows, predictions, strict=True)):
        projected = project_mixed_row(row, "shared")
        write_json(output / "calls" / str(i) / "input.json",
                   {key: projected[key] for key in ("state", "questions")})
        write_json(output / "calls" / str(i) / "output.json", prediction)
    write_json(output / "results.json", score_mixed_predictions(rows, predictions))
    compute = {"forwards": 2, "input_tokens": 20, "cpu_seconds": .1}
    write_json(output / "compute.json", compute)
    write_json(ledger, {"compute": {"test_export": compute}})
    return {"output": str(output), "fit_output": str(fit), "data": str(common),
            "phase": "test_export"}, ledger


def test_export_comparison_keeps_precision_changes_and_additional_common_task(tmp_path):
    stage, ledger = export_fixture(tmp_path)
    before = Path(stage["output"], "calls/0/output.json").read_bytes()
    report = completion.audit_export(stage, ledger)
    assert report["public_inputs_equal"] == 2
    assert report["in_process_comparison_rows"] == 1
    assert report["additional_common_dev_rows"] == 1
    assert report["changed_choices"] == [{"state_id": 0, "in_process": "read", "persisted": "done"}]
    assert report["shared_metrics_equal"] is False
    assert report["common_metrics"]["by_task"]["instruction_applicability"]["counts"][
        "correct"] == 1
    assert Path(stage["output"], "calls/0/output.json").read_bytes() == before


@pytest.mark.parametrize("change", ["input", "ledger"])
def test_export_audit_rejects_input_or_accounting_changes(tmp_path, change):
    stage, ledger = export_fixture(tmp_path)
    if change == "input":
        path = Path(stage["output"], "calls/0/input.json")
        row = json.loads(path.read_text())
        row["state"]["task"]["request"] = "Changed target"
        write_json(path, row)
    else:
        write_json(ledger, {"compute": {"test_export": {
            "forwards": 1, "input_tokens": 20, "cpu_seconds": .1}}})
    with pytest.raises(ValueError):
        completion.audit_export(stage, ledger)


def test_sequence_stops_after_first_failed_child_and_keeps_its_log(tmp_path, monkeypatch):
    ledger = tmp_path / "budget.json"
    initial = copy.deepcopy(RunBudget(RunLimits(), ledger).state)
    write_json(ledger, initial)
    plan = {"ledger": str(ledger), "source_version": "mechanical",
            "jobs": [{"name": f"stage-{i}", "output": str(tmp_path / f"result-{i}"),
                      "phase": f"test-{i}", "kind": "fit", "environment": {},
                      "argv": ["fake", str(i)]} for i in range(3)]}
    write_json(tmp_path / "plan.json", plan)
    started = []

    def child(argv, **kwargs):
        started.append(argv)
        return SimpleNamespace(pid=400000 + len(started),
                               wait=lambda: 0 if len(started) == 1 else 1)

    monkeypatch.setattr(completion.subprocess, "Popen", child)
    monkeypatch.setattr(completion, "audit_fit", lambda *_: {"status": "synthetic_closed"})
    monkeypatch.setattr(sys, "argv", ["completion", str(tmp_path / "plan.json"),
                                      str(tmp_path / "sequence")])
    with pytest.raises(RuntimeError, match="First failed"):
        completion.main()
    driver = json.loads((tmp_path / "sequence/driver.json").read_text())
    assert len(started) == 2 and len(driver["completed"]) == 1
    assert driver["status"] == "FAILED" and driver["active"]["exit_code"] == 1
    assert Path(driver["active"]["log"]).is_file()
    state = json.loads(ledger.read_text())
    assert all(state[key] == initial[key] for key in (
        "generation", "embedding", "generation_requests"))
