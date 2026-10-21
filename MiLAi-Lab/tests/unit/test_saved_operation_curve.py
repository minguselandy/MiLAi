"""Saved-vs-memory selection and partial failure, with synthetic files and no model calls."""
from pathlib import Path

import pytest
from test_operation_curve_analysis import complete_fixture

import evaluate_saved_operation_curve as saved
from analyze_operation_curve import analyze
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload


def install_evaluator(monkeypatch, recipe, *, corrupt=None):
    calls = []

    def evaluate(data, checkpoint, output, actual_recipe, phase):
        assert actual_recipe == recipe
        rows = read_jsonl(data)
        lengths = read_json(Path(recipe["output"]) / "lengths.json")
        by_id = {x["event_id"]: x for values in lengths.values() for x in values}
        is_train = output.name == "selected-train"
        if not is_train:
            assert not (output.parent / "selection.json").exists()
        calls.append(output.name)
        initial = checkpoint == Path(recipe["base_checkpoint"])
        tokens = 0
        for i, row in enumerate(rows):
            payload = project_operation_payload(row, recipe["operation_state"])
            write_json(output / "calls" / str(i) / "input.json",
                       {k: payload[k] for k in ("state", "questions")})
            correct = (i < 2 if is_train else initial)
            prediction = {"choice": "read" if correct else "stop",
                "logits": {"read": float(correct), "stop": float(not correct)},
                "probabilities": {"read": .75 if correct else .25,
                                  "stop": .25 if correct else .75},
                "input_tokens": by_id[row["metadata"]["event_id"]]["sequence_tokens"],
                "truncated": False}
            tokens += prediction["input_tokens"]
            write_json(output / "calls" / str(i) / "output.json", prediction)
        run = {"status": "COMPLETED", "completed_states": len(rows), "device": "cpu",
            "reference_compile_override": False, "mha_fastpath_enabled": False,
            "loaded_weight_dtype": "torch.float32", "operation_state": recipe["operation_state"],
            "calibrated": False, "max_len": recipe["max_len"],
            "head_max_len": recipe["head_max_len"], "checkpoint": str(checkpoint)}
        write_json(output / "run.json", run)
        compute = {"sequence_rows": len(rows), "input_tokens": tokens, "cpu_seconds": 1.0,
                   "wall_seconds": 1.0, "runs": 1}
        write_json(output / "compute.json", {**compute, "ledger": recipe["ledger"]})
        ledger = read_json(Path(recipe["ledger"]))
        ledger["compute"][phase] = compute
        write_json(Path(recipe["ledger"]), ledger)
        if corrupt is not None and output.name == "update-2":
            corrupt(output)

    monkeypatch.setattr(saved, "evaluate_file", evaluate)
    return calls


def test_saved_selection_uses_all_actual_saved_candidates_and_matching_train(tmp_path, monkeypatch):
    recipe = complete_fixture(tmp_path)
    analysis = analyze(recipe)
    assert analysis["in_memory_selection"]["update"] == 2
    calls = install_evaluator(monkeypatch, recipe)
    result = saved.run_saved_curve(analysis, tmp_path / "saved")
    assert calls == ["update-0", "update-2", "update-4", "selected-train"]
    assert result["deployment_selection"]["update"] == 0
    assert result["original_in_memory_selection"]["update"] == 2
    feedback = result["curve"][0]["feedback-dev"]
    assert feedback["answer"]["family_macro_state_pair_accuracy"] == 1
    assert feedback["delivery"]["family_macro_state_pair_accuracy"] == 0
    assert result["selected_train_dev_family_gap"] == -.25
    assert result["curve"][0]["in_memory_gpu_vs_saved_cpu"]["choice_changes"] == 2
    assert read_json(tmp_path / "saved/driver.json")["status"] == "COMPLETED"


@pytest.mark.parametrize("change", ["missing", "input", "nan", "ledger"])
def test_failed_saved_candidate_cannot_bind_a_partial_selection(tmp_path, monkeypatch, change):
    recipe = complete_fixture(tmp_path)
    analysis = analyze(recipe)

    def corrupt(output):
        if change == "missing":
            (output / "calls/1/output.json").unlink()
        elif change == "input":
            path = output / "calls/0/input.json"
            value = read_json(path)
            value["state"] = {}
            write_json(path, value)
        elif change == "nan":
            path = output / "calls/0/output.json"
            value = read_json(path)
            value["logits"]["read"] = float("nan")
            write_json(path, value)
        else:
            path = output / "compute.json"
            value = read_json(path)
            value["input_tokens"] += 1
            write_json(path, value)

    calls = install_evaluator(monkeypatch, recipe, corrupt=corrupt)
    with pytest.raises((ValueError, FileNotFoundError)):
        saved.run_saved_curve(analysis, tmp_path / "saved")
    assert calls == ["update-0", "update-2"]
    assert not (tmp_path / "saved/selection.json").exists()
    assert read_json(tmp_path / "saved/driver.json")["status"] == "FAILED"


def test_explicit_staging_reports_matching_train_pending(tmp_path, monkeypatch):
    recipe = complete_fixture(tmp_path)
    install_evaluator(monkeypatch, recipe)
    result = saved.run_saved_curve(analyze(recipe), tmp_path / "saved", evaluate_train=False)
    assert result["status"] == "SAVED_SELECTION_COMPLETE_SELECTED_TRAIN_PENDING"
    assert "selected_train_dev_family_gap" not in result


def test_missing_declared_candidate_is_rejected_before_dispatch(tmp_path, monkeypatch):
    recipe = complete_fixture(tmp_path)
    calls = install_evaluator(monkeypatch, recipe)
    analysis = analyze(recipe)
    analysis["saved_checkpoints"].pop()
    with pytest.raises(ValueError, match="evaluation schedule"):
        saved.run_saved_curve(analysis, tmp_path / "saved")
    assert calls == []
