"""Verify actual saved CPU jobs and select complete matched-operation curves only."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from analyze_conditional_scale_fit import (
    applicability_predictions,
    auxiliary_recipe,
    conditional_diagnostics,
    validate_applicability_prediction,
)
from analyze_operation_curve import (
    choose_checkpoint,
    read_predictions,
    recipe_from_plan,
    saved_tensor_dtypes,
    validate_prediction,
)
from evaluate_bounded_laya import score_applicability_predictions
from evaluate_saved_operation_curve import verified_compute
from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.methods.laya_memory_policy import project_operation_payload
from retrieval_feedback import score_feedback
from retrieval_mixture import project_mixed_row, score_mixed_predictions


def native_inputs(
    study: dict[str, Any], native: dict[str, Any], job: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Path]:
    recipe = native["recipe"]
    root = Path(recipe["output"])
    if job["kind"] == "conditional":
        if native["status"] != "TERMINAL_AUXILIARY_EPOCH_VERIFIED;SAVED_RELOAD_PENDING":
            raise ValueError("Conditional reload requires a verified completed auxiliary fit")
        (spec,) = [
            arm["auxiliary"]
            for arm in study["arms"]
            if arm["auxiliary"]["run_id"] == native["run_id"]
        ]
        if recipe != auxiliary_recipe(spec):
            raise ValueError("Native auxiliary analysis differs from the declared scale recipe")
        if job["run_id"] == "common-multilingual-base":
            if job["point"] != 0:
                raise ValueError("The common auxiliary base is point zero")
            checkpoint = Path(recipe["base_checkpoint"])
        else:
            if job["run_id"] != native["run_id"] or job["point"] != 1:
                raise ValueError("The auxiliary saved endpoint is the fixed declared epoch")
            checkpoint = Path(native["fixed_terminal_checkpoint"])
        split = "dev"
        rows = read_jsonl(Path(recipe["dev_source"]))
    else:
        if native["status"] != "COMPLETE_IN_MEMORY_CURVE_AUDITED;PERSISTED_SELECTION_PENDING":
            raise ValueError("Saved operation selection requires a fully audited native curve")
        if job["run_id"] != native["run_id"]:
            raise ValueError("Saved job names a different operation run")
        if job["run_id"] == "pure-operation-baseline":
            spec = study["baseline_operation_spec"]
        else:
            (spec,) = [
                arm["operation"]
                for arm in study["arms"]
                if arm["operation"]["run_id"] == native["run_id"]
            ]
        expected = recipe_from_plan(
            {**spec, "source_version": "declared-query-scale-operation-freeze"}
        )
        if recipe != expected:
            raise ValueError("Native operation analysis differs from the declared matched recipe")
        (point,) = [p for p in native["curve"] if p["update"] == job["point"]]
        checkpoint = Path(point["checkpoint"])
        split = "dev" if job["kind"] == "operation" else "feedback-dev"
        rows = read_jsonl(
            Path(recipe["data"]) / "dev.jsonl"
            if split == "dev"
            else Path(recipe["feedback_dev_source"])
        )
    run = read_json(root / "run.json")
    representation = "full" if job["kind"] == "conditional" else "shared_actions"
    if recipe["operation_state"] != representation or (
        recipe["max_len"],
        recipe["head_max_len"],
    ) != (job["max_len"], job["head_max_len"]):
        raise ValueError("Saved representation or capacity differs from the fitted condition")
    proc = Path("/proc", str(run["pid"]), "cmdline")
    if (
        run["status"] != "COMPLETED"
        or run["optimizer_updates"] != recipe["planned_optimizer_updates"]
        or (proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"))
    ):
        raise ValueError("The native model job is not closed")
    if read_jsonl(Path(job["data"])) != rows or Path(job["checkpoint"]) != checkpoint:
        raise ValueError("Saved data or checkpoint differs from the native binding")
    return rows, read_json(root / "lengths.json")[split], checkpoint


def verify_saved_job(
    study: dict[str, Any], plan: dict[str, Any], native: dict[str, Any], job_id: str
) -> dict[str, Any]:
    (job,) = [j for j in plan["jobs"] if j["job_id"] == job_id]
    if job["kind"] not in {"conditional", "operation", "feedback"}:
        raise ValueError("Unknown scale-study saved task")
    rows, lengths, checkpoint = native_inputs(study, native, job)
    conditional = job["kind"] == "conditional"
    task = {
        "conditional": "instruction_applicability",
        "operation": "mixed_retrieval",
        "feedback": "memory_feedback",
    }[job["kind"]]
    limits = (8192, 384) if conditional else (12288, 2048)
    if (
        job["task"] != task
        or (job["max_len"], job["head_max_len"]) != limits
        or job["states"] != len(rows)
        or plan["original_ledger"] != study["original_ledger"]
    ):
        raise ValueError("Saved task, capacity, row coverage or original ledger changed")
    root = Path(job["output"])
    run = read_json(root / "run.json")
    expected = {
        "status": "COMPLETED",
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
    }
    if (
        any(run[k] != value for k, value in expected.items())
        or Path(run["checkpoint"]) != checkpoint
        or Path(run["data"]) != Path(job["data"])
    ):
        raise ValueError("Saved CPU inference differs from the declared common condition")
    proc = Path("/proc", str(run["pid"]), "cmdline")
    if proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"):
        raise ValueError("The saved CPU evaluator still owns its output")
    calls = root / "calls"
    if sorted(int(p.name) for p in calls.iterdir()) != list(range(len(rows))):
        raise ValueError("Saved CPU calls do not cover the complete ordered input")
    predictions = []
    for i, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        projected = (
            row
            if conditional
            else (
                project_mixed_row(row, "shared_actions")
                if job["kind"] == "operation"
                else project_operation_payload(row, "shared_actions")
            )
        )
        payload = {k: projected[k] for k in ("state", "questions")}
        observed = read_json(calls / str(i) / "input.json")
        if json.dumps(observed, ensure_ascii=False) != json.dumps(payload, ensure_ascii=False):
            raise ValueError("Saved CPU call did not receive the same literal model input")
        prediction = read_json(calls / str(i) / "output.json")
        validator = validate_applicability_prediction if conditional else validate_prediction
        validator(row, prediction, length)
        predictions.append(prediction)
    compute = verified_compute(root, {"ledger": plan["original_ledger"]}, job["phase"], predictions)
    if compute["forwards"] != len(rows) or compute["state_tokenizations"] != len(rows):
        raise ValueError("Saved call accounting differs from the completed input coverage")
    if conditional:
        score = score_applicability_predictions(rows, predictions)
    elif job["kind"] == "operation":
        score = score_mixed_predictions(rows, predictions)
    else:
        score = {
            target: score_feedback(rows, predictions, target) for target in ("answer", "delivery")
        }
    if read_json(root / "results.json") != score:
        raise ValueError("Saved aggregate differs from the actual CPU predictions")
    native_root = Path(native["recipe"]["output"])
    split = "feedback-dev" if job["kind"] == "feedback" else "dev"
    reader = applicability_predictions if conditional else read_predictions
    previous = reader(native_root / split / str(job["point"]), rows, lengths)
    report = {
        "status": "SAVED_SCALE_JOB_INPUTS_RESULTS_AND_COMPUTE_VERIFIED",
        "job_id": job_id,
        "run_id": job["run_id"],
        "point": job["point"],
        "kind": job["kind"],
        "checkpoint": str(checkpoint),
        "condition": expected,
        "score": score,
        "stored_tensor_dtypes": saved_tensor_dtypes(checkpoint / "model.safetensors"),
        "native_vs_saved_choice_changes": sum(
            a["choice"] != z["choice"] for a, z in zip(previous, predictions, strict=True)
        ),
        "native_compute_already_recorded": compute,
        "scope": "Actual CPU reload; device and storage changes are combined, not isolated "
        "quantization. No model rerun, ledger mutation or Host result from this audit.",
    }
    if conditional:
        report["conditional"] = conditional_diagnostics(study, rows, predictions)
        report["auxiliary_endpoint_selection"] = "fixed epoch1; no metric-based reselection"
    return report


def select_operation(
    study: dict[str, Any], plan: dict[str, Any], native: dict[str, Any]
) -> dict[str, Any]:
    run_id = native["run_id"]
    jobs = [j for j in plan["jobs"] if j["run_id"] == run_id]
    expected = {(p["update"], kind) for p in native["curve"] for kind in ("operation", "feedback")}
    if len(jobs) != len(expected) or {(j["point"], j["kind"]) for j in jobs} != expected:
        raise ValueError(
            "Operation selection requires all declared saved points and feedback reads"
        )
    reports = {
        (j["point"], j["kind"]): verify_saved_job(study, plan, native, j["job_id"]) for j in jobs
    }
    curve = []
    for point in native["curve"]:
        update = point["update"]
        op, feedback = reports[update, "operation"], reports[update, "feedback"]
        if op["checkpoint"] != feedback["checkpoint"]:
            raise ValueError("Operation and feedback scores must refer to the same saved weights")
        curve.append(
            {
                "update": update,
                "checkpoint": op["checkpoint"],
                "dev": op["score"]["by_task"]["memory_operation"],
                "feedback-dev": feedback["score"],
                "verified_jobs": [op["job_id"], feedback["job_id"]],
            }
        )
    chosen = choose_checkpoint(curve)
    return {
        "status": "COMPLETE_SAVED_SCALE_OPERATION_SELECTION;HOST_PENDING",
        "run_id": run_id,
        "curve": curve,
        "common_endpoint": curve[-1],
        "deployment_selection": {
            "update": chosen["update"],
            "checkpoint": chosen["checkpoint"],
            "metric": chosen["dev"]["family_macro_acceptance"],
            "rule": "Highest operation-dev family macro, earliest tie, initialization eligible",
        },
        "native_in_memory_selection": native["in_memory_selection"],
        "scope": "Both common endpoint and complete saved selection retained; conditional/feedback "
        "scores do not choose the operation checkpoint. Actual Host outcomes remain pending.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("job", "select-operation"))
    parser.add_argument("study", type=Path)
    parser.add_argument("saved_plan", type=Path)
    parser.add_argument("native_analysis", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--job-id")
    args = parser.parse_args()
    if (args.mode == "job") != bool(args.job_id):
        parser.error("Single-job verification requires exactly one --job-id")
    started = time.process_time()
    study, plan, native = [
        read_json(path) for path in (args.study, args.saved_plan, args.native_analysis)
    ]
    result = (
        verify_saved_job(study, plan, native, args.job_id)
        if args.mode == "job"
        else select_operation(study, plan, native)
    )
    result.update(
        model_calls=0,
        ledger_recorded=False,
        cpu_seconds_pending=time.process_time() - started,
        no_sha_validation=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(result["status"])


if __name__ == "__main__":
    main()
