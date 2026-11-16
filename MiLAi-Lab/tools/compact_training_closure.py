"""Compose original audit functions for compact operation selection and feedback initialization."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from analyze_operation_curve import (
    choose_checkpoint,
    operation_diagnostics,
    recipe_from_plan,
)
from evaluate_saved_operation_curve import verified_compute, verified_predictions
from milai_lab.harness.artifact_io import read_json, read_jsonl
from retrieval_feedback import score_feedback


def check_job(
    job: dict[str, Any],
    recipe: dict[str, Any],
    rows: list[dict[str, Any]],
    lengths: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(job["output"])
    run = read_json(root / "run.json")
    if (
        run["threads"] != 4
        or run["visible_cuda_devices"] != ""
        or run["task"] != job["task"]
        or Path(run["data"]).resolve() != Path(job["data"])
        or read_jsonl(Path(job["data"])) != rows
        or run["planned_states"] != len(rows)
    ):
        raise ValueError("Compact saved job differs from the declared data/runtime")
    proc = Path("/proc", str(run["pid"]), "cmdline")
    if proc.exists() and str(root).encode() in proc.read_bytes().split(b"\0"):
        raise ValueError("Compact saved evaluator still owns its output")
    predictions = verified_predictions(root, rows, lengths, recipe, Path(job["checkpoint"]))
    compute = verified_compute(root, recipe, job["phase"], predictions)
    return predictions, compute


def select_operation(
    study: dict[str, Any], plan: dict[str, Any], native: dict[str, Any]
) -> dict[str, Any]:
    recipe = recipe_from_plan(study["operation"])
    if (
        native["status"] != "COMPLETE_IN_MEMORY_CURVE_AUDITED;PERSISTED_SELECTION_PENDING"
        or native["recipe"] != recipe
        or recipe["operation_state"] != "compact_actions"
    ):
        raise ValueError("Compact operation selection requires its complete matching native audit")
    data = Path(recipe["data"])
    dev, feedback = read_jsonl(data / "dev.jsonl"), read_jsonl(Path(recipe["feedback_dev_source"]))
    lengths = read_json(Path(recipe["output"]) / "lengths.json")
    if [j["update"] for j in plan["operation_candidates"]] != recipe["evaluation_updates"]:
        raise ValueError("Read every declared compact operation candidate, including update0")
    points = []
    for job in plan["operation_candidates"]:
        expected = (
            Path(recipe["base_checkpoint"])
            if job["update"] == 0
            else Path(recipe["output"]) / "checkpoints" / f"update-{job['update']}"
        )
        if Path(job["checkpoint"]) != expected:
            raise ValueError("Operation candidate names another checkpoint")
        predictions, compute = check_job(
            job, recipe, [*dev, *feedback], [*lengths["dev"], *lengths["feedback-dev"]]
        )
        primary = operation_diagnostics(dev, predictions[: len(dev)], lengths["dev"], {})
        points.append(
            {
                "update": job["update"],
                "checkpoint": str(expected),
                "dev": primary,
                "feedback-dev": {
                    target: score_feedback(feedback, predictions[len(dev) :], target)
                    for target in ("answer", "delivery")
                },
                "native_compute_already_recorded": compute,
                "job_id": job["job_id"],
            }
        )
    chosen = choose_checkpoint(points)
    return {
        "status": "COMPACT_OPERATION_SAVED_CURVE_VERIFIED;MATCHING_TRAIN_PENDING",
        "recipe": recipe,
        "curve": points,
        "selection": {
            "update": chosen["update"],
            "checkpoint": chosen["checkpoint"],
            "metric": chosen["dev"]["family_macro_acceptance"],
        },
        "conditions": plan["operation_conditions"],
        "primary_states": len(dev),
        "secondary_feedback_states": len(feedback),
        "scope": "All7 compact CPU candidates; primary operation-dev selection, earliest tie, "
        "update0 eligible. Original16 feedback states remain diagnostic. No Host/test selection "
        "or comparison to the baseline's historical masked64 gap is imputed.",
    }


def selected_train_job(plan: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    if selection["status"] != "COMPACT_OPERATION_SAVED_CURVE_VERIFIED;MATCHING_TRAIN_PENDING":
        raise ValueError("Selected train evaluation follows actual full saved operation selection")
    job: dict[str, Any] = copy.deepcopy(plan["operation_selected_train_template"])
    if job["checkpoint"] is not None or job["argv"][job["checkpoint_argument_index"]] is not None:
        raise ValueError("Selected train template must not contain an invented checkpoint")
    checkpoint = selection["selection"]["checkpoint"]
    job["checkpoint"] = job["argv"][job["checkpoint_argument_index"]] = checkpoint
    job["status"] = "BOUND_NOT_EXECUTED"
    return job


def verify_selected_train(
    study: dict[str, Any], job: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    recipe = recipe_from_plan(study["operation"])
    if job["checkpoint"] != selection["selection"]["checkpoint"]:
        raise ValueError("Matching train evaluation changed the saved selected checkpoint")
    rows = [r for r in read_jsonl(Path(recipe["data"]) / "train.jsonl") if r["gold"]]
    lengths = read_json(Path(recipe["output"]) / "lengths.json")["train"]
    predictions, compute = check_job(job, recipe, rows, lengths)
    return {
        "status": "COMPACT_OPERATION_MATCHING_SELECTED_TRAIN_VERIFIED",
        "checkpoint": job["checkpoint"],
        "update": selection["selection"]["update"],
        "conditions": selection["conditions"],
        "rows": len(rows),
        "metrics": operation_diagnostics(rows, predictions, lengths, {}),
        "native_compute_already_recorded": compute,
        "scope": "Actual full labelled train at the independently selected compact checkpoint. "
        "No train/feedback/Host reselection or unseen-generalization claim.",
    }


def bind_feedback(
    study: dict[str, Any],
    saved_plan: dict[str, Any],
    selection: dict[str, Any],
    train: dict[str, Any],
    tokenizer_audit: dict[str, Any],
) -> dict[str, Any]:
    checkpoint = selection["selection"]["checkpoint"]
    expected_recipe = recipe_from_plan(study["operation"])
    if (
        selection["status"] != "COMPACT_OPERATION_SAVED_CURVE_VERIFIED;MATCHING_TRAIN_PENDING"
        or selection["recipe"] != expected_recipe
        or train["status"] != "COMPACT_OPERATION_MATCHING_SELECTED_TRAIN_VERIFIED"
        or train["checkpoint"] != checkpoint
        or train["conditions"] != selection["conditions"]
        or selection["conditions"]["operation_state"] != "compact_actions"
        or tokenizer_audit["status"]
        != "ACTUAL_ORIGINAL_EXPOSURE_AND_COMPACT_SDK_INPUTS_VERIFIED;NO_MODEL_RUN"
        or tokenizer_audit["stage"] != "feedback"
        or not tokenizer_audit["explicit_tokenizer_binding"]
        or Path(tokenizer_audit["runtime"]).resolve()
        != Path(study["runtime_overlays"]["feedback"]["runtime"]).resolve()
        or Path(tokenizer_audit["original_run"]).resolve()
        != Path(study["original_feedback_control"]["output"]).resolve()
        or Path(tokenizer_audit["tokenizer_used"]).resolve()
        != (Path(checkpoint) / "tokenizer").resolve()
    ):
        raise ValueError(
            "Feedback requires actual compact selection/train and selected-tokenizer audit"
        )
    spec = copy.deepcopy(study["feedback_template"])
    entry = next(
        i
        for i, value in enumerate(spec["argv"])
        if isinstance(value, str) and Path(value).name == "train_bounded_laya.py"
    )
    if not spec["initialization_pending"] or spec["argv"][entry + 2] is not None:
        raise ValueError("Bind only the original uninitialized compact feedback template")
    spec["argv"][entry + 2] = checkpoint
    spec.update(initialization_pending=False, status="BOUND_NOT_EXECUTED")
    original_plan = read_json(Path(study["source_nine_plan"]))
    fit_plan = {
        "source_version": spec["source_version"],
        "protocol": original_plan["protocol"],
        "plans": [spec],
    }
    feedback_plan = copy.deepcopy(saved_plan["feedback_saved_template"])
    feedback_plan["status"] = "COMPACT_FEEDBACK_SAVED_PLAN_BOUND_NOT_EXECUTED"
    feedback_plan["common_base"]["checkpoint"] = checkpoint
    feedback_plan["common_base"]["status"] = "BOUND_NOT_EXECUTED"
    index = feedback_plan["common_base"]["checkpoint_argument_index"]
    feedback_plan["common_base"]["argv"][index] = checkpoint
    feedback_plan["fits"][0]["candidates"][0]["checkpoint"] = checkpoint
    return {
        "status": "COMPACT_FEEDBACK_INITIALIZATION_BOUND_NOT_EXECUTED",
        "selected_compact_operation": selection["selection"],
        "fit_plan": fit_plan,
        "saved_plan": feedback_plan,
        "scope": "Only the actually selected compact operation model is used. This is the "
        "matched-format training chain, not an inference-only or pure-loss contrast. Native/saved "
        "feedback curves, selected old retention and actual Host comparison remain required.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    select = modes.add_parser("select-operation")
    select.add_argument("study", type=Path)
    select.add_argument("saved_plan", type=Path)
    select.add_argument("native", type=Path)
    train_job = modes.add_parser("bind-train")
    train_job.add_argument("saved_plan", type=Path)
    train_job.add_argument("selection", type=Path)
    train_verify = modes.add_parser("verify-train")
    train_verify.add_argument("study", type=Path)
    train_verify.add_argument("job", type=Path)
    train_verify.add_argument("selection", type=Path)
    bind = modes.add_parser("bind-feedback")
    for field in ("study", "saved_plan", "selection", "train", "tokenizer_audit"):
        bind.add_argument(field, type=Path)
    for sub in (select, train_job, train_verify, bind):
        sub.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    if args.mode == "select-operation":
        result = select_operation(
            read_json(args.study), read_json(args.saved_plan), read_json(args.native)
        )
    elif args.mode == "bind-train":
        result = selected_train_job(read_json(args.saved_plan), read_json(args.selection))
    elif args.mode == "verify-train":
        result = verify_selected_train(
            read_json(args.study), read_json(args.job), read_json(args.selection)
        )
    else:
        result = bind_feedback(
            *(
                read_json(getattr(args, field))
                for field in ("study", "saved_plan", "selection", "train", "tokenizer_audit")
            )
        )
    result.update(
        cpu_seconds_pending=time.process_time() - started,
        ledger_recorded=False,
        model_calls=0,
        no_sha_validation=True,
    )
    if args.mode == "bind-feedback":
        fit_path = args.output.with_name(args.output.stem + "-fit-plan.json")
        saved_path = args.output.with_name(args.output.stem + "-saved-plan.json")
        result["saved_plan"]["fit_plan"] = str(fit_path.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    if args.mode == "bind-feedback":
        for path, value in [(fit_path, result["fit_plan"]), (saved_path, result["saved_plan"])]:
            with path.open("x") as stream:
                json.dump(value, stream, indent=2)
                stream.write("\n")
    print(result["status"])


if __name__ == "__main__":
    main()
