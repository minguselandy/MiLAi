"""Evaluate frozen C20 controls, fit on calibration only, then score reserved test.

Known exposed families are removed before model inference. This does not certify
unobserved historical exposure or semantic validity of the source proof labels.
"""

from __future__ import annotations

import argparse
import fcntl
import gc
import json
import os
import resource
import time
from pathlib import Path

from evaluate_bounded_laya import NativeDecision, score_predictions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from reader_calibration import fit_temperature, metrics, paired_family_interval


def eligible_rows(config: dict, split: str) -> tuple[list[dict], dict]:
    rows = [json.loads(line) for line in
            (Path(config["data"]) / f"{split}.jsonl").read_text().splitlines()]
    excluded = set(config["exclude_families"][split])
    selected = [row for row in rows if row["metadata"]["family"] not in excluded]
    return selected, {"original_states": len(rows), "eligible_states": len(selected),
        "eligible_source_rows": len({r["metadata"]["row"] for r in selected}),
        "eligible_families": sorted({r["metadata"]["family"] for r in selected}),
        "excluded_families": sorted(excluded), "exclusion_source": config["exclusion_source"]}


def load_decision(arm: dict, config: dict):
    import torch

    checkpoint = Path(arm["checkpoint"])
    backend = arm["backend"]
    if backend == "native":
        decision = NativeDecision(checkpoint, config["max_len"], config["head_max_len"])
    elif backend == "linear":
        from linear_reader_classifier import LinearDecision

        decision = LinearDecision.load(checkpoint, config["max_len"], config["head_max_len"])
    else:
        from logits_reader import LogitsDecision

        decision = (LogitsDecision(checkpoint, config["max_len"])
                    if backend == "logits_zero" else LogitsDecision.load(checkpoint))
    if backend in {"native", "linear"}:
        decision.model.encoder.config.reference_compile = False
    decision.device = torch.device(f"cuda:{arm['physical_gpu'] - 2}")
    decision.model.float().to(decision.device).eval()
    return decision


def predict_rows(decision, rows: list[dict], output: Path, run: dict, root: Path) -> list[dict]:
    predictions = []
    for index, row in enumerate(rows):
        # Only the same visible state/actions reach any model. Labels stay evaluator-side.
        payload = {key: row[key] for key in ("state", "questions")}
        folder = output / "calls" / row["metadata"]["event_id"]
        write_json(folder / "input.json", payload)
        prediction = decision.predict(payload)
        write_json(folder / "output.json", prediction)
        predictions.append(prediction)
        run["completed_states"] += 1
        write_json(root / "run.json", run)
        if (index + 1) % 25 == 0 or index + 1 == len(rows):
            print(json.dumps({"arm": run["arm"], "split": run["split"],
                              "completed": index + 1, "planned": len(rows)}), flush=True)
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    import torch

    config = read_json(args.config)
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3":
        raise ValueError("This experiment uses only the allocated physical GPUs2,3")
    torch.set_num_threads(4)
    torch.manual_seed(0)
    for device in (0, 1):
        torch.cuda.set_per_process_memory_fraction(0.75, device)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "config.json", config)
    run = {"status": "RUNNING", "pid": os.getpid(), "completed_states": 0,
           "completed_arms": [], "http_requests": 0, "generated_tokens": 0,
           "source_version": config["source_version"], "physical_gpus": [2, 3],
           "torch_version": torch.__version__, "precision": "float32",
           "reference_compile": False, "policy_changed": False}
    write_json(args.output / "run.json", run)
    start, cpu = time.perf_counter(), time.process_time()
    decision, measures = None, {"runs": 1, "forwards": 0, "sequence_rows": 0, "input_tokens": 0}
    try:
        for arm in config["arms"]:
            run.update(arm=arm["name"], split="loading")
            write_json(args.output / "run.json", run)
            arm_start, arm_cpu = time.perf_counter(), time.process_time()
            output = args.output / arm["name"]
            decision = load_decision(arm, config)
            calibration, inventory = eligible_rows(config, "calibration")
            write_json(output / "calibration/inventory.json", inventory)
            run["split"] = "calibration"
            predictions = predict_rows(decision, calibration, output / "calibration", run,
                                       args.output)
            fitted = fit_temperature(calibration, predictions)
            write_json(output / "temperature.json", fitted)
            # The scalar is frozen on disk before this arm opens the test labels.
            test, inventory = eligible_rows(config, "test")
            if {r["metadata"]["family"] for r in test} & {
                    r["metadata"]["family"] for r in calibration}:
                raise ValueError("Calibration and test families overlap")
            write_json(output / "test/inventory.json", inventory)
            run["split"] = "test"
            predictions = predict_rows(decision, test, output / "test", run, args.output)
            results = {"temperature": fitted, "acceptance": score_predictions(test, predictions),
                       "raw": metrics(test, predictions, 1.0),
                       "calibrated": metrics(test, predictions, fitted["temperature"]),
                       "paired_family_interval": paired_family_interval(
                           test, predictions, fitted["temperature"]),
                       "scope": config["scope"], "argmax_unchanged": True}
            write_json(output / "results.json", results)
            arm_measures = {"wall_seconds": time.perf_counter() - arm_start,
                            "cpu_seconds": time.process_time() - arm_cpu, **decision.counters}
            write_json(output / "compute.json", arm_measures)
            for key, value in decision.counters.items():
                measures[key] = measures.get(key, 0) + value
            decision = None
            gc.collect()
            torch.cuda.empty_cache()
            run["completed_arms"].append(arm["name"])
            write_json(args.output / "run.json", run)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        if decision is not None:
            for key, value in decision.counters.items():
                measures[key] = measures.get(key, 0) + value
        measures.update(wall_seconds=time.perf_counter() - start,
                        cpu_seconds=time.process_time() - cpu)
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": [torch.cuda.max_memory_allocated(i) for i in (0, 1)],
            "ledger": config["budget"]})
        decision = None
        gc.collect()
        torch.cuda.empty_cache()
        terminal = dict(run)
        run.update(status="WAITING_LEDGER", terminal_inference_status=terminal["status"])
        write_json(args.output / "run.json", run)
        print("Inference closed; GPUs released; waiting for the original budget lease", flush=True)
        budget_path = Path(config["budget"])
        with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
            budget.record_compute(config["name"], measures)
        write_json(args.output / "run.json", {**terminal, "ledger_recorded": True})


if __name__ == "__main__":
    main()
