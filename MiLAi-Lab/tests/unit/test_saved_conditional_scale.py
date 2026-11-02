"""Synthetic saved calls test real input joins and selection, without loading any scorer."""

import copy
from dataclasses import asdict
from pathlib import Path

import pytest
from test_conditional_scale_fit import complete_auxiliary_fixture, write_rows
from test_operation_curve_analysis import complete_fixture, tensor_file

from analyze_conditional_scale_fit import analyze_scale_fit
from analyze_saved_conditional_scale import select_operation, verify_saved_job
from evaluate_bounded_laya import score_applicability_predictions
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from retrieval_feedback import score_feedback
from retrieval_mixture import project_mixed_row, score_mixed_predictions


def install_saved_calls(tmp_path, native, run_id, point, kind):
    recipe = native["recipe"]
    root = Path(recipe["output"])
    conditional = kind == "conditional"
    split = "feedback-dev" if kind == "feedback" else "dev"
    data = (
        Path(recipe["dev_source"])
        if conditional
        else Path(recipe["feedback_dev_source"])
        if split == "feedback-dev"
        else Path(recipe["data"]) / "dev.jsonl"
    )
    rows = read_jsonl(data)
    checkpoint = (
        Path(native["fixed_terminal_checkpoint"])
        if conditional
        else Path(next(p["checkpoint"] for p in native["curve"] if p["update"] == point))
    )
    job_id = f"{run_id}/{point}/{kind}"
    output = tmp_path / "saved" / job_id
    task = {
        "conditional": "instruction_applicability",
        "operation": "mixed_retrieval",
        "feedback": "memory_feedback",
    }[kind]
    limits = (8192, 384) if conditional else (12288, 2048)
    lengths = read_json(root / "lengths.json")[split]
    predictions = []
    for i, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        payload = (
            row
            if conditional
            else (
                project_mixed_row(row, "shared_actions")
                if kind == "operation"
                else project_operation_payload(row, "shared_actions")
            )
        )
        write_json(
            output / "calls" / str(i) / "input.json",
            {k: payload[k] for k in ("state", "questions")},
        )
        qid = "applicability" if conditional else "next"
        keys = list(row["questions"][qid]["criteria"])
        if conditional:
            target = row["gold"].get(qid, {}).get("probabilities", {})
            choice = max(target, key=target.get) if target else keys[0]
        else:
            choice = "read" if point == 0 else "stop"
        prediction = {
            "choice": choice,
            "logits": {k: float(k == choice) for k in keys},
            "probabilities": {k: 0.75 if k == choice else 0.25 for k in keys},
            "input_tokens": length["sequence_tokens"],
            "truncated": False,
        }
        predictions.append(prediction)
        write_json(output / "calls" / str(i) / "output.json", prediction)
    run = {
        "status": "COMPLETED",
        "pid": 99999999,
        "device": "cpu",
        "visible_cuda_devices": "",
        "threads": 4,
        "task": task,
        "max_len": limits[0],
        "head_max_len": limits[1],
        "planned_states": len(rows),
        "completed_states": len(rows),
        "http_requests": 0,
        "reference_compile_override": False,
        "mha_fastpath_enabled": False,
        "loaded_weight_dtype": "torch.float32",
        "calibrated": False,
        "operation_state": "full" if conditional else "shared_actions",
        "checkpoint": str(checkpoint),
        "data": str(data),
    }
    write_json(output / "run.json", run)
    if conditional:
        score = score_applicability_predictions(rows, predictions)
    elif kind == "operation":
        score = score_mixed_predictions(rows, predictions)
    else:
        score = {
            target: score_feedback(rows, predictions, target) for target in ("answer", "delivery")
        }
    write_json(output / "results.json", score)
    phase = job_id.replace("/", "_")
    compute = {
        "cpu_seconds": 1.0,
        "wall_seconds": 1.0,
        "runs": 1,
        "forwards": len(rows),
        "state_tokenizations": len(rows),
        "sequence_rows": len(rows),
        "input_tokens": sum(x["input_tokens"] for x in predictions),
    }
    write_json(output / "compute.json", {**compute, "ledger": recipe["ledger"]})
    ledger = read_json(Path(recipe["ledger"]))
    ledger["compute"][phase] = compute
    write_json(Path(recipe["ledger"]), ledger)
    return {
        "job_id": job_id,
        "run_id": run_id,
        "point": point,
        "kind": kind,
        "checkpoint": str(checkpoint),
        "data": str(data),
        "output": str(output),
        "task": task,
        "states": len(rows),
        "max_len": limits[0],
        "head_max_len": limits[1],
        "phase": phase,
    }


def auxiliary_saved_fixture(tmp_path):
    study, spec, _ = complete_auxiliary_fixture(tmp_path)
    native = analyze_scale_fit(study, spec["run_id"])
    study["original_ledger"] = native["recipe"]["ledger"]
    job = install_saved_calls(tmp_path, native, spec["run_id"], 1, "conditional")
    return study, {"original_ledger": study["original_ledger"], "jobs": [job]}, native, job


def test_actual_conditional_reload_keeps_native_and_reviewed_masks_separate(tmp_path):
    study, plan, native, job = auxiliary_saved_fixture(tmp_path)
    result = verify_saved_job(study, plan, native, job["job_id"])
    assert result["native_vs_saved_choice_changes"] > 0
    assert result["score"]["counts"]["masked"] == 1
    assert (
        result["conditional"]["reviewed"]["all_reviewed"]["strata"]["unknown"][
            "family_macro_query_pair_joint_accuracy"
        ]
        is None
    )
    assert result["auxiliary_endpoint_selection"] == "fixed epoch1; no metric-based reselection"


@pytest.mark.parametrize(
    "mutation",
    [
        "input",
        "missing",
        "nan",
        "tokens",
        "head",
        "dtype",
        "ledger",
        "aggregate",
        "native_running",
        "task",
    ],
)
def test_saved_conditional_job_rejects_unmatched_or_partial_evidence(tmp_path, mutation):
    study, plan, native, job = auxiliary_saved_fixture(tmp_path)
    output = Path(job["output"])
    if mutation == "missing":
        (output / "calls/0/output.json").unlink()
    elif mutation == "task":
        job["task"] = "memory_feedback"
    else:
        path = (
            output
            / {
                "input": "calls/0/input.json",
                "nan": "calls/0/output.json",
                "tokens": "calls/0/output.json",
                "head": "run.json",
                "dtype": "run.json",
                "ledger": "compute.json",
                "aggregate": "results.json",
                "native_running": "run.json",
            }[mutation]
        )
        if mutation == "native_running":
            path = Path(native["recipe"]["output"]) / "run.json"
        value = read_json(path)
        if mutation == "input":
            value["state"]["candidate"]["text"] = "changed body"
        elif mutation == "nan":
            value["logits"]["satisfies"] = float("nan")
        elif mutation == "tokens":
            value["input_tokens"] += 1
        elif mutation == "head":
            value["head_max_len"] = 2048
        elif mutation == "dtype":
            value["loaded_weight_dtype"] = "torch.float16"
        elif mutation == "ledger":
            value["cpu_seconds"] += 1
        elif mutation == "aggregate":
            value["counts"]["correct"] += 1
        else:
            value["status"] = "RUNNING"
        write_json(path, value)
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_saved_job(study, plan, native, job["job_id"])


def operation_saved_fixture(tmp_path):
    recipe = complete_fixture(tmp_path)
    data, output = Path(recipe["data"]), Path(recipe["output"])
    actions = [
        MemoryAction("read", "READ", "0", {"before": 0, "after": 8}),
        MemoryAction("stop", "HANDOFF", "Reader"),
    ]
    state = MemoryControlState(task={"request": "synthetic request"})
    for name in ["train", "dev", "feedback"]:
        rows = read_jsonl(data / (name + ".jsonl"))
        for row in rows:
            projected = decision_example(
                {"before": state.project(), "actions": [asdict(action) for action in actions]},
                row["metadata"],
            )
            row["state"], row["questions"] = projected["state"], projected["questions"]
            row["metadata"]["action_parameters"] = projected["metadata"]["action_parameters"]
        write_rows(data / (name + ".jsonl"), rows)
    run = read_json(output / "run.json")
    run["operation_state"] = "shared_actions"
    write_json(output / "run.json", run)
    for checkpoint in [
        Path(recipe["base_checkpoint"]),
        *list((output / "checkpoints").iterdir()),
        output / "checkpoint",
    ]:
        path = checkpoint / "rl_agent_config.json"
        config = read_json(path)
        config["training"]["milai_reader"]["operation_state"] = "shared_actions"
        write_json(path, config)
    spec = {
        "run_id": "synthetic-operation",
        "argv": [
            "python",
            "train_bounded_laya.py",
            str(data),
            recipe["base_checkpoint"],
            str(output),
            "--task",
            "memory_operation",
            "--objective",
            "soft-ce",
            "--operation-state",
            "shared_actions",
            "--seed",
            "0",
            "--optimizer-updates",
            "4",
            "--eval-at-updates",
            "2",
            "4",
            "--evaluate-train",
            "--shuffle-options",
            "--gradient-checkpointing",
            "--max-len",
            "12288",
            "--head-max-len",
            "2048",
            "--encoder-lr",
            "2.5e-5",
            "--head-lr",
            "1e-4",
            "--micro-batch-size",
            "2",
            "--feedback-dev-data",
            str(data / "feedback.jsonl"),
            "--compute-phase",
            "test-fit",
            "--budget",
            recipe["ledger"],
        ],
    }
    study = {
        "arms": [{"auxiliary": {"run_id": "unused-aux"}, "operation": spec}],
        "baseline_operation_run": str(output),
        "original_ledger": recipe["ledger"],
    }
    native = analyze_scale_fit(study, spec["run_id"])
    jobs = [
        install_saved_calls(tmp_path, native, spec["run_id"], point, kind)
        for point in [0, 2, 4]
        for kind in ["operation", "feedback"]
    ]
    return study, {"original_ledger": recipe["ledger"], "jobs": jobs}, native


def test_saved_operation_selection_uses_all_actual_points_and_initialization(tmp_path):
    study, plan, native = operation_saved_fixture(tmp_path)
    result = select_operation(study, plan, native)
    assert native["in_memory_selection"]["update"] == 2
    assert result["deployment_selection"]["update"] == 0
    assert result["common_endpoint"]["update"] == 4
    assert len(result["curve"]) == 3 and len(result["curve"][0]["verified_jobs"]) == 2
    missing = copy.deepcopy(plan)
    missing["jobs"].pop()
    with pytest.raises(ValueError, match="all declared saved points"):
        select_operation(study, missing, native)


def test_saved_operation_does_not_reuse_a_different_input_length(tmp_path):
    study, plan, native = operation_saved_fixture(tmp_path)
    plan["jobs"][0]["max_len"] = 16384
    with pytest.raises(ValueError, match="capacity differs"):
        verify_saved_job(study, plan, native, plan["jobs"][0]["job_id"])


def test_saved_auxiliary_common_base_does_not_use_endpoint_weights(tmp_path):
    study, plan, native, job = auxiliary_saved_fixture(tmp_path)
    base = Path(native["recipe"]["base_checkpoint"])
    tensor_file(base / "model.safetensors", 0.0)
    job.update(run_id="common-multilingual-base", point=0)
    with pytest.raises(ValueError, match="checkpoint differs"):
        verify_saved_job(study, plan, native, job["job_id"])
