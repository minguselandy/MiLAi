"""Verify declared CPU/CUDA reloads before checkpoint selection or retention reporting."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import (
    choose_feedback_checkpoint,
    feedback_partitions,
    validate_quality_metric,
)
from analyze_operation_curve import (
    read_predictions,
    saved_tensor_dtypes,
    validate_feedback_metric,
    validate_metric,
)
from evaluate_saved_operation_curve import verified_compute, verified_predictions
from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.methods.memory_control_learning import score_operation_predictions
from quality_feedback import QUALITY_MODES, choose_quality_checkpoint, score_quality_feedback
from retrieval_feedback import score_feedback


def saved_backend(plan: dict[str, Any]) -> str:
    device = plan["conditions"]["device"]
    if device == "cpu":
        return "CPU"
    if device.startswith("cuda"):
        return "GPU"
    raise ValueError("Saved feedback protocol requires an explicit CPU or CUDA device")


def inputs_for_fit(plan: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    if native["status"] not in {
        "TERMINAL_NATIVE_FEEDBACK_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING",
        "TERMINAL_NATIVE_QUALITY_CURVE_VERIFIED;SAVED_RELOAD_SELECTION_PENDING",
    }:
        raise ValueError("Saved feedback selection requires the verified terminal native fit")
    fit, = [f for f in plan["fits"] if f["run_id"] == native["run_id"]]
    if [p["update"] for p in fit["candidates"]] != [p["update"] for p in native["curve"]]:
        raise ValueError("Saved candidates differ from the complete native schedule")
    recipe = native["recipe"]
    run = read_json(Path(recipe["output"]) / "run.json")
    quality_mode = native.get("pair_supervision")
    quality_status = native["status"].startswith("TERMINAL_NATIVE_QUALITY_")
    if (quality_status != (quality_mode in QUALITY_MODES)
            or (not quality_status and (quality_mode is not None
                or run.get("pair_supervision", "legacy-direction") != "legacy-direction"
                or fit.get("pair_supervision") in QUALITY_MODES))
            or (quality_status and (fit.get("pair_supervision") != quality_mode
                or run.get("pair_supervision") != quality_mode
                or recipe.get("pair_supervision") != quality_mode
                or fit.get("pair_label_smoothing", 0.0) != run.get("pair_label_smoothing", 0.0)
                or recipe.get("pair_label_smoothing", 0.0) != run.get("pair_label_smoothing", 0.0)
                or fit.get("selection_rule") != "pure_quality_directional"))):
        raise ValueError("Saved quality selection requires its declared supervision and metric")
    if (fit.get("replay_objective", "soft-ce") != run.get("replay_objective", "soft-ce")
            or recipe.get("replay_objective", "soft-ce") != run.get("replay_objective", "soft-ce")):
        raise ValueError("Saved selection requires the declared replay objective")
    process = Path("/proc", str(run["pid"]), "cmdline")
    if (run["status"] != "COMPLETED"
            or run["optimizer_updates"] != recipe["planned_optimizer_updates"]
            or (process.exists() and recipe["output"].encode()
                in process.read_bytes().split(b"\0"))):
        raise ValueError("Native fit is no longer a closed declared run")
    if any(plan["conditions"][k] != recipe[k]
           for k in ("operation_state", "max_len", "head_max_len")):
        raise ValueError("Saved inference representation differs from the fitted representation")
    old = read_jsonl(Path(recipe["data"]) / "dev.jsonl")
    feedback = read_jsonl(Path(recipe["feedback_dev_source"]))
    inputs = plan["inputs"]
    if (old != read_jsonl(Path(inputs["old_operations"]))
            or feedback != read_jsonl(Path(inputs["feedback"]))
            or [*old, *feedback] != read_jsonl(Path(inputs["combined"]))
            or len(old) != inputs["old_operation_states"]
            or len(feedback) != inputs["feedback_states"]
            or sum(bool(r["gold"].get("next", {}).get("probabilities")) for r in old)
            != inputs["old_operation_labelled"]):
        raise ValueError("Common saved-evaluation inputs differ from the actual fit")
    fit_plan = read_json(Path(plan["fit_plan"]))
    protocol = read_json(Path(fit_plan["protocol"]))
    legacy = read_jsonl(Path(protocol["feedback_dev"]["old_file"]))
    if feedback[:len(legacy)] != legacy or len(legacy) != inputs["legacy_feedback_states"]:
        raise ValueError("Legacy feedback rows changed")
    lengths = read_json(Path(recipe["output"]) / "lengths.json")
    return {"fit": fit, "old": old, "feedback": feedback, "lengths": lengths,
            "legacy_ids": {r["metadata"]["event_id"] for r in legacy}}


def verify_job(
    plan: dict[str, Any], job: dict[str, Any], rows: list[dict[str, Any]],
    lengths: list[dict[str, Any]], checkpoint: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Require the same bytes-as-JSON input, actual output coverage and recorded compute."""
    root = Path(job["output"])
    run = read_json(root / "run.json")
    if (job["states"] != len(rows) or run["planned_states"] != len(rows)
            or Path(job["checkpoint"]).resolve() != checkpoint.resolve()
            or Path(run["data"]).resolve() != Path(job["data"]).resolve()
            or read_jsonl(Path(job["data"])) != rows
            or run["task"] != job["task"] or run["http_requests"] != 0
            or any(run[k] != v for k, v in plan["conditions"].items())):
        raise ValueError("Saved job data, checkpoint or inference conditions changed")
    process = Path("/proc", str(run["pid"]), "cmdline")
    if process.exists() and str(root).encode() in process.read_bytes().split(b"\0"):
        raise ValueError("Saved evaluator still owns its output")
    recipe = {**plan["conditions"], "ledger": plan["original_ledger"]}
    predictions = verified_predictions(root, rows, lengths, recipe, checkpoint)
    compute = verified_compute(root, recipe, job["phase"], predictions)
    if compute["forwards"] != len(rows) or compute["state_tokenizations"] != len(rows):
        raise ValueError("Saved model calls differ from actual prediction coverage")
    saved = read_json(root / "results.json")
    if job["task"] == "memory_feedback":
        # Combined jobs also forward old-operation rows. Their coverage summary
        # includes replay rows, unlike the feedback-only selection denominator.
        for target in ("answer", "delivery"):
            validate_feedback_metric(saved[target], score_feedback(rows, predictions, target))
    elif job["task"] == "memory_operation":
        validate_metric(saved, score_operation_predictions(rows, predictions))
    else:
        raise ValueError("Undeclared saved-feedback evaluation task")
    return predictions, compute


def select(plan: dict[str, Any], native: dict[str, Any]) -> dict[str, Any]:
    context = inputs_for_fit(plan, native)
    fit, old, feedback, lengths = (context[k] for k in ("fit", "old", "feedback", "lengths"))
    curve = []
    quality = native.get("pair_supervision") in QUALITY_MODES
    backend = saved_backend(plan)
    for candidate, native_point in zip(fit["candidates"], native["curve"], strict=True):
        update = candidate["update"]
        job = plan["common_base"] if update == 0 else candidate
        if update == 0 and candidate["shared_job"] != job["job_id"]:
            raise ValueError("Shared initialization job changed")
        combined = update in (0, native["recipe"]["planned_optimizer_updates"])
        rows = [*old, *feedback] if combined else feedback
        actual_lengths = ([*lengths["dev"], *lengths["feedback-dev"]]
                          if combined else lengths["feedback-dev"])
        checkpoint = Path(native_point["checkpoint"])
        predictions, compute = verify_job(plan, job, rows, actual_lengths, checkpoint)
        feedback_predictions = predictions[len(old):] if combined else predictions
        partitions = feedback_partitions(feedback, feedback_predictions, context["legacy_ids"])
        original = read_predictions(Path(native["recipe"]["output"]) / "feedback-dev" / str(update),
                                    feedback, lengths["feedback-dev"])
        for target in ("answer", "delivery"):
            validate_feedback_metric(native_point["feedback-dev"][target],
                                     score_feedback(feedback, original, target))
        differences = sum(a["choice"] != b["choice"] for a, b in zip(
            original, feedback_predictions, strict=True))
        dtypes = saved_tensor_dtypes(checkpoint / "model.safetensors")
        if dtypes != native_point["saved_tensor_dtypes"]:
            raise ValueError("Stored tensor format differs from the native checkpoint audit")
        point: dict[str, Any] = {"update": update, "checkpoint": str(checkpoint),
            "feedback-dev": partitions["combined"]["targets"], "partitions": partitions,
            "old_operation": score_operation_predictions(old, predictions[:len(old)])
                if combined else None,
            "evaluation_job": job["job_id"], "compute_phase": job["phase"],
            "native_compute_already_recorded": compute, "stored_tensor_dtypes": dtypes,
            f"in_memory_gpu_vs_saved_{backend.lower()}_choice_changes": differences}
        if quality:
            point["quality_partitions"] = feedback_partitions(
                feedback, feedback_predictions, context["legacy_ids"], score_quality_feedback)
            point["pure_quality"] = point["quality_partitions"]["combined"]["targets"]
            point["quality_cost"] = {target: score_quality_feedback(
                feedback, feedback_predictions, target, "quality-cost")
                for target in ("answer", "delivery")}
            for target in ("answer", "delivery"):
                validate_quality_metric(native_point["pure_quality"][target],
                    score_quality_feedback(feedback, original, target))
                validate_quality_metric(native_point["quality_cost"][target],
                    score_quality_feedback(feedback, original, target, "quality-cost"))
        curve.append(point)
    chooser = choose_quality_checkpoint if quality else choose_feedback_checkpoint
    chosen = {target: chooser(curve, target)
              for target in fit["selection_targets"]}
    selected = {target: {"update": point["update"], "checkpoint": point["checkpoint"],
        "metric": (point["pure_quality"][target]["directional"] if quality else
                   point["feedback-dev"][target])["family_macro_state_pair_accuracy"],
        "condition": plan["conditions"]} for target, point in chosen.items()}
    pending = sorted({p["update"] for p in chosen.values() if p["old_operation"] is None})
    return {"status": f"SAVED_{backend}_{'QUALITY' if quality else 'FEEDBACK'}_SELECTION_VERIFIED",
        "run_id": native["run_id"],
        **({"pair_supervision": native["pair_supervision"],
            "selection_rule": "pure_quality_directional"} if quality else {}),
        **({"pair_label_smoothing": native["recipe"]["pair_label_smoothing"]}
           if "pair_label_smoothing" in native["recipe"] else {}),
        **({"replay_objective": native["recipe"]["replay_objective"]}
           if "replay_objective" in native["recipe"] else {}),
        "conditions": plan["conditions"], "curve": curve, "deployment_selection": selected,
        "native_in_memory_selection": native["in_memory_selection"],
        "pending_retention_updates": pending,
        "retention_status": "SELECTED_EARLY_OLD_OPERATION_JOBS_PENDING" if pending else
                            "BASE_AND_ENDPOINT_ALREADY_COVER_SELECTED_UPDATES",
        "actual_Host_status": "PENDING", "shared_base_job": plan["common_base"]["job_id"],
        "scope": ("Checkpoint selection requires every declared saved feedback candidate. "
                 "Combined jobs' old-operation rows are excluded from feedback scoring. "
                 "Old/new and collector-phase results retain their original masks. "
                 + ("GPU/CPU differences combine serialization and device, "
                    "not isolated quantization. "
                    if backend == "CPU" else
                    "GPU saved selection does not establish the best CPU checkpoint; selected "
                    "CPU deployment confirmation is separate. No isolated quantization claim. ")
                 + "Copied native costs and the shared base are not additional billable phases.")}


def verify_retention(
    plan: dict[str, Any], native: dict[str, Any], selection: dict[str, Any],
) -> dict[str, Any]:
    context = inputs_for_fit(plan, native)
    fit, old, lengths = (context[k] for k in ("fit", "old", "lengths"))
    quality = native.get("pair_supervision") in QUALITY_MODES
    backend = saved_backend(plan)
    status = f"SAVED_{backend}_{'QUALITY' if quality else 'FEEDBACK'}_SELECTION_VERIFIED"
    if (selection["status"] != status
            or (quality and (selection.get("pair_supervision") != native["pair_supervision"]
                             or selection.get("selection_rule") != "pure_quality_directional"
                             or selection.get("pair_label_smoothing", 0.0)
                             != native["recipe"].get("pair_label_smoothing", 0.0)))
            or selection.get("replay_objective", "soft-ce")
            != native["recipe"].get("replay_objective", "soft-ce")
            or selection["run_id"] != native["run_id"]
            or selection["conditions"] != plan["conditions"]
            or set(selection["deployment_selection"]) != set(fit["selection_targets"])
            or [p["update"] for p in selection["curve"]]
            != [p["update"] for p in fit["candidates"]]):
        raise ValueError("Retention requires this fit's verified saved selection")
    selected = selection["deployment_selection"]
    by_update = {p["update"]: p for p in selection["curve"]}
    retention = {u: {"old_operation": p["old_operation"], "reused_evaluation_job":
                    p["evaluation_job"]} for u, p in by_update.items()
                 if p["old_operation"] is not None}
    for target, selected_point in selected.items():
        expected = (choose_quality_checkpoint(selection["curve"], target) if quality else
                    choose_feedback_checkpoint(selection["curve"], target))
        metric = (expected["pure_quality"][target]["directional"] if quality else
                  expected["feedback-dev"][target])["family_macro_state_pair_accuracy"]
        if (any(selected_point[k] != expected[k] for k in ("update", "checkpoint"))
                or selected_point["metric"] != metric
                or selected_point["condition"] != plan["conditions"]):
            raise ValueError("Selection changed after observing retention")
        update = selected_point["update"]
        if update in retention:
            continue
        job, = [j for j in fit["conditional_retention_jobs"] if j["update"] == update]
        predictions, compute = verify_job(plan, job, old, lengths["dev"],
                                         Path(selected_point["checkpoint"]))
        retention[update] = {"old_operation": score_operation_predictions(old, predictions),
                             "evaluation_job": job["job_id"],
                             "native_compute_already_recorded": compute}
    prefix = f"SAVED_{backend}_" + ("QUALITY_" if quality else "")
    return {"status": prefix + "SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING",
        **({"pair_supervision": native["pair_supervision"]} if quality else {}),
        **({"pair_label_smoothing": native["recipe"]["pair_label_smoothing"]}
           if "pair_label_smoothing" in native["recipe"] else {}),
        **({"replay_objective": native["recipe"]["replay_objective"]}
           if "replay_objective" in native["recipe"] else {}),
        "run_id": native["run_id"], "conditions": plan["conditions"],
        "deployment_selection": selected, "old_operation_by_update": retention,
        "selected_old_operation": {t: retention[p["update"]]["old_operation"]
                                    for t, p in selected.items()},
        "scope": "Old skills are reported at base, endpoint and each selected checkpoint; "
                 "they do not retroactively change target-specific selection. One verified job "
                 "serves both CE views if they select the same update. Host remains unevaluated."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("select", "retention"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("native_analysis", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    plan, native = read_json(args.plan), read_json(args.native_analysis)
    if args.mode == "select":
        result = select(plan, native)
        name = "selection.json"
    else:
        result = verify_retention(plan, native, read_json(args.output / "selection.json"))
        name = "retention.json"
    result.update(plan=str(args.plan.resolve()),
                  native_analysis=str(args.native_analysis.resolve()),
                  cpu_seconds_pending=time.process_time() - started, ledger_recorded=False,
                  model_calls=0, no_sha_validation=True)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / name).open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(result["status"], result["deployment_selection"])


if __name__ == "__main__":
    main()
