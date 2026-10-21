"""Serial saved-checkpoint CPU evaluation using the existing metered evaluator."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from analyze_operation_curve import choose_checkpoint, operation_diagnostics, validate_prediction
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.laya_memory_policy import project_operation_payload
from retrieval_feedback import score_feedback


def evaluate_file(data: Path, checkpoint: Path, output: Path, recipe: dict[str, Any],
                  phase: str) -> None:
    args = [*recipe["execution_prefix"], str(Path(__file__).with_name("evaluate_bounded_laya.py")),
        str(data), str(checkpoint), str(output), "--budget", recipe["ledger"],
        "--compute-phase", phase, "--task", "memory_operation", "--device", "cpu",
        "--operation-state", recipe["operation_state"], "--max-len", str(recipe["max_len"]),
        "--head-max-len", str(recipe["head_max_len"]), "--disable-reference-compile"]
    environment = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "TOKENIZERS_PARALLELISM": "false"}
    # The caller's frozen PYTHONPATH and declared attention wrapper are retained.
    with output.with_suffix(".log").open("w") as stream:
        subprocess.run(  # noqa: S603 -- declared local interpreter/wrapper and audited fit recipe
            args, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True)


def verified_predictions(output: Path, rows: list[dict[str, Any]], lengths: list[dict[str, Any]],
                         recipe: dict[str, Any], checkpoint: Path) -> list[dict[str, Any]]:
    run = read_json(output / "run.json")
    if (run["status"] != "COMPLETED" or run["completed_states"] != len(rows)
            or run["operation_state"] != recipe["operation_state"] or run["device"] != "cpu"
            or run["reference_compile_override"] is not False or run["mha_fastpath_enabled"]
            or run["loaded_weight_dtype"] != "torch.float32" or run["calibrated"]
            or run["max_len"] != recipe["max_len"]
            or run["head_max_len"] != recipe["head_max_len"]
            or Path(run["checkpoint"]).resolve() != checkpoint.resolve()):
        raise ValueError("Saved-model evaluation differs from the declared inference condition")
    if sorted(int(p.name) for p in (output / "calls").iterdir()) != list(range(len(rows))):
        raise ValueError("Saved-model evaluation has incomplete planned coverage")
    predictions = []
    for i, (row, length) in enumerate(zip(rows, lengths, strict=True)):
        projected = project_operation_payload(row, recipe["operation_state"])
        expected = {k: projected[k] for k in ("state", "questions")}
        actual = read_json(output / "calls" / str(i) / "input.json")
        # JSON comparison preserves key order/types while normalizing Python tuple pairs.
        if json.dumps(actual, ensure_ascii=False) != json.dumps(expected, ensure_ascii=False):
            raise ValueError("Saved-model evaluation did not receive the same literal input")
        result = read_json(output / "calls" / str(i) / "output.json")
        validate_prediction(row, result, length)
        predictions.append(result)
    return predictions


def verified_compute(output: Path, recipe: dict[str, Any], phase: str,
                     predictions: list[dict[str, Any]]) -> dict[str, Any]:
    compute: dict[str, Any] = read_json(output / "compute.json")
    recorded = read_json(Path(recipe["ledger"]))["compute"][phase]
    measures = {k: v for k, v in compute.items() if k not in ("ledger", "peak_rss_kib")}
    if (Path(compute["ledger"]).resolve() != Path(recipe["ledger"]).resolve()
            or any(recorded[k] != value for k, value in measures.items())
            or compute["sequence_rows"] != len(predictions)
            or compute["input_tokens"] != sum(p["input_tokens"] for p in predictions)):
        raise ValueError("Saved-model compute differs from actual rows or its ledger phase")
    return compute


def run_saved_curve(analysis: dict[str, Any], output: Path,
                    *, evaluate_train: bool = True) -> dict[str, Any]:
    if analysis["status"] != "COMPLETE_IN_MEMORY_CURVE_AUDITED;PERSISTED_SELECTION_PENDING":
        raise ValueError("A fully audited terminal curve is required for saved evaluation")
    recipe = analysis["recipe"]
    root, data = Path(recipe["output"]), Path(recipe["data"])
    if read_json(root / "run.json")["status"] != "COMPLETED":
        raise ValueError("The original training run is not complete")
    if [c["update"] for c in analysis["saved_checkpoints"]] != recipe["evaluation_updates"]:
        raise ValueError("Saved candidates differ from the complete declared evaluation schedule")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    dev = read_jsonl(data / "dev.jsonl")
    feedback = (read_jsonl(Path(recipe["feedback_dev_source"]))
                if recipe["feedback_dev_source"] is not None else [])
    combined = output / "dev-and-feedback.jsonl"
    paths = [data / "dev.jsonl", *([Path(recipe["feedback_dev_source"])] if feedback else [])]
    with combined.open("wb") as combined_stream:
        for path in paths:
            with path.open("rb") as source:
                for line in source:
                    if line.strip():
                        combined_stream.write(line if line.endswith(b"\n") else line + b"\n")
    combined_rows = [*dev, *feedback]
    if read_jsonl(combined) != combined_rows:
        raise ValueError("Combined inference blocks changed their literal rows or order")
    lengths = read_json(root / "lengths.json")
    combined_lengths = [*lengths["dev"], *(lengths["feedback-dev"] if feedback else [])]
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "original_run": str(root), "planned_candidates": len(analysis["saved_checkpoints"]),
        "primary_dev_rows": len(dev), "secondary_feedback_rows": len(feedback),
        "evaluate_selected_train": evaluate_train, "completed": [], "automatic_retry": False,
        "inference": {"device": "cpu", "loaded_dtype": "float32", "reference_compile": False,
                      "mha_fastpath": False},
        "selection_rule": "operation-dev family macro,earliest tie,0eligible;feedback secondary"}
    write_json(output / "driver.json", driver)
    points = []
    try:
        for candidate in analysis["saved_checkpoints"]:
            update, checkpoint = candidate["update"], Path(candidate["path"])
            target = output / f"update-{update}"
            driver["active"] = {"update": update, "output": str(target)}
            write_json(output / "driver.json", driver)
            phase = recipe["compute_phase"] + f"_saved_cpu_u{update}"
            evaluate_file(combined, checkpoint, target, recipe, phase)
            predictions = verified_predictions(target, combined_rows, combined_lengths,
                                                recipe, checkpoint)
            primary = predictions[:len(dev)]
            point = {"update": update, "checkpoint": str(checkpoint),
                "dev": operation_diagnostics(dev, primary, lengths["dev"], {}),
                "feedback-dev": {name: score_feedback(feedback, predictions[len(dev):], name)
                                 for name in ("answer", "delivery")} if feedback else {},
                "compute_already_recorded": verified_compute(target, recipe, phase, predictions)}
            old = [read_json(root / "dev" / str(update) / f"{i}.json") for i in range(len(dev))]
            changed = [i for i, (left, right) in enumerate(zip(old, primary, strict=True))
                       if left["choice"] != right["choice"]]
            point["in_memory_gpu_vs_saved_cpu"] = {
                "choice_changes": len(changed), "total_states": len(dev),
                "kind_changes": sum(dev[i]["metadata"]["action_kinds"][old[i]["choice"]]
                                    != dev[i]["metadata"]["action_kinds"][primary[i]["choice"]]
                                    for i in changed),
                "scope": "Serialization and inference-device differences together;"
                         "not isolated quantization"}
            points.append(point)
            write_json(target / "partitioned-results.json", point)
            driver["completed"].append({"update": update, "status": "COMPLETED",
                "dev_macro": point["dev"]["family_macro_acceptance"]})
            write_json(output / "driver.json", driver)
        selected = choose_checkpoint(points)
        result: dict[str, Any] = {"status": "ALL_SAVED_CANDIDATES_EVALUATED", "recipe": recipe,
            "curve": points, "original_in_memory_selection": analysis["in_memory_selection"],
            "deployment_selection": {"update": selected["update"],
                "checkpoint": selected["checkpoint"],
                "metric": selected["dev"]["family_macro_acceptance"],
                "condition": driver["inference"],
                "rule": driver["selection_rule"]},
            "scope": "Saved checkpoint predictions,static reviewed preferences,not Host success. "
                     "Original in-memory results retained. No feedback/test/Host selection."}
        write_json(output / "selection.json", result["deployment_selection"])
        if evaluate_train:
            train = [r for r in read_jsonl(data / "train.jsonl") if r["gold"]]
            train_path = output / "selected-train.jsonl"
            with train_path.open("w") as stream:
                for row in train:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            target = output / "selected-train"
            driver["active"] = {"update": selected["update"], "split": "train",
                                "output": str(target)}
            write_json(output / "driver.json", driver)
            phase = recipe["compute_phase"] + f"_saved_cpu_selected_train_u{selected['update']}"
            evaluate_file(train_path, Path(selected["checkpoint"]), target, recipe, phase)
            predictions = verified_predictions(target, train, lengths["train"], recipe,
                                                Path(selected["checkpoint"]))
            result["selected_train"] = operation_diagnostics(
                train, predictions, lengths["train"], {})
            result["selected_train_dev_family_gap"] = (
                result["selected_train"]["family_macro_acceptance"]
                - selected["dev"]["family_macro_acceptance"])
            result["selected_train_compute_already_recorded"] = verified_compute(
                target, recipe, phase, predictions)
        driver["status"] = "COMPLETED"
        result["status"] = (
            "COMPLETE_SAVED_MODEL_SELECTION_AND_DECLARED_EVALUATIONS" if evaluate_train
            else "SAVED_SELECTION_COMPLETE_SELECTED_TRAIN_PENDING")
        write_json(output / "results.json", result)
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter()-started,
            orchestration_cpu_seconds=time.process_time()-cpu, ledger_recorded=False,
            accounting="Child model compute already recorded once by the existing evaluator. "
                       "Parent process CPU only is pending;wall is nested and must not be added.")
        write_json(output / "driver.json", driver)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--skip-selected-train", action="store_true",
                        help="Staged execution;matching selected train evaluation remains pending")
    args = parser.parse_args()
    report = run_saved_curve(read_json(args.analysis), args.output,
                             evaluate_train=not args.skip_selected_train)
    print({"status": report["status"], "selection": report["deployment_selection"]})


if __name__ == "__main__":
    main()
