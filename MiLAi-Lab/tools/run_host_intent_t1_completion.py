"""Run the remaining registered T1 fits and export checks in strict sequence.

The plan names immutable training/evaluation entrypoints and the original
ledger. This runner never retries a failed model job or selects a checkpoint.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from retrieval_mixture import project_mixed_row, score_mixed_predictions


def rows_at(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def compute_matches(stage: dict[str, Any], ledger: Path) -> dict[str, Any]:
    compute = read_json(Path(stage["output"]) / "compute.json")
    charged = read_json(ledger)["compute"][stage["phase"]]
    excluded = {"peak_rss_kib", "peak_cuda_allocated_bytes", "ledger"}
    if any(charged[key] != value for key, value in compute.items() if key not in excluded):
        raise ValueError("Stage compute does not match its original-ledger phase")
    return dict(compute)


def audit_fit(stage: dict[str, Any], ledger: Path) -> dict[str, Any]:
    root = Path(stage["output"])
    run = read_json(root / "run.json")
    if (run["status"] != "COMPLETED" or run["seed"] != stage["seed"]
            or run["optimizer_updates"] != 524 or run["train_sequence_rows"] != 8384):
        raise ValueError("The registered T1 fitting budget did not complete")
    probes = read_json(root / "parameter-probes.json")
    if not all(row["changed_elements"] > 0 for row in probes.values()):
        raise ValueError("Both encoder and head must have trained")
    for split, count in (("train", run["train_states"]), ("dev", run["dev_states"])):
        predictions = root / split / "524"
        if {p.stem for p in predictions.glob("*.json") if p.stem.isdigit()} != {
                str(i) for i in range(count)}:
            raise ValueError("Final diagnostic prediction coverage is incomplete")
    report = {
        "status": "FIT_CLOSED_AND_RECONCILED", "run": run, "parameter_probes": probes,
        "compute": compute_matches(stage, ledger),
        "dev_final": read_json(root / "dev/524/summary.json"),
        "train_final": read_json(root / "train/524/summary.json"),
        "selection": "Predetermined final524, not best development checkpoint.",
    }
    write_json(root / "completion-audit.json", report)
    return report


def audit_export(stage: dict[str, Any], ledger: Path) -> dict[str, Any]:
    root, fitted = Path(stage["output"]), Path(stage["fit_output"])
    run = read_json(root / "run.json")
    common = rows_at(Path(stage["data"]))
    old_rows = rows_at(Path(read_json(fitted / "run.json")["dev_source"]))
    old_by_id = {row["metadata"]["state_id"]: (i, row) for i, row in enumerate(old_rows)}
    if run["status"] != "COMPLETED" or run["completed_states"] != len(common):
        raise ValueError("Persisted checkpoint evaluation did not cover the common development set")
    predictions, shared_rows, shared_predictions = [], [], []
    changed, max_delta = [], 0.0
    for index, row in enumerate(common):
        call = root / "calls" / str(index)
        projected = project_mixed_row(row, "shared")
        if read_json(call / "input.json") != {
                key: projected[key] for key in ("state", "questions")}:
            raise ValueError("Exported checkpoint received a different model-visible input")
        prediction = read_json(call / "output.json")
        if prediction["truncated"] or not all(
            math.isfinite(value) for value in prediction["logits"].values()
        ):
            raise ValueError("Persisted output is truncated or nonfinite")
        predictions.append(prediction)
        previous = old_by_id.get(row["metadata"]["state_id"])
        if previous is None:
            continue
        old_index, old_row = previous
        if row != old_row:
            raise ValueError("Common source state, label or metadata changed")
        before = read_json(fitted / "dev/524" / f"{old_index}.json")
        if before["input_tokens"] != prediction["input_tokens"]:
            raise ValueError("Common input token count changed")
        max_delta = max(max_delta, *(abs(value - before["logits"][key])
                                    for key, value in prediction["logits"].items()))
        if before["choice"] != prediction["choice"]:
            changed.append({"state_id": row["metadata"]["state_id"],
                            "in_process": before["choice"], "persisted": prediction["choice"]})
        shared_rows.append(row)
        shared_predictions.append(prediction)
    metrics = score_mixed_predictions(common, predictions)
    if metrics != read_json(root / "results.json"):
        raise ValueError("Stored common metrics differ from recomputed predictions")
    if len(shared_rows) != len(old_rows):
        raise ValueError("Missing in-process comparison states")
    shared_metrics = score_mixed_predictions(shared_rows, shared_predictions)
    compute = compute_matches(stage, ledger)
    if (compute["forwards"] != len(common)
            or compute["input_tokens"] != sum(row["input_tokens"] for row in predictions)):
        raise ValueError("Common evaluation counters do not match actual predictions")
    report = {
        "status": "PERSISTED_CHECKPOINT_VALIDATED", "public_inputs_equal": len(common),
        "in_process_comparison_rows": len(shared_rows),
        "additional_common_dev_rows": len(common) - len(shared_rows),
        "choices_unchanged": len(shared_rows) - len(changed), "changed_choices": changed,
        "max_logit_absolute_delta": max_delta, "loaded_weight_dtype": run["loaded_weight_dtype"],
        "shared_metrics_equal": shared_metrics == read_json(fitted / "dev/524/summary.json"),
        "common_metrics": metrics, "shared_metrics": shared_metrics, "compute": compute,
        "precision": "SDK saves FP16 and loads FP32. All differences are retained; "
                     "persisted common metrics describe the deployable final524 checkpoint.",
    }
    write_json(root / "completion-audit.json", report)
    return report


def summarize(plan: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in plan["conditions"]:
        fitted = Path(item["fit_output"])
        exported = Path(item["validation_output"])
        row = {**item, "fit": read_json(fitted / "run.json"),
               "fit_compute": read_json(fitted / "compute.json"),
               "validation": read_json(exported / "completion-audit.json")}
        if row["fit"]["status"] != "COMPLETED":
            raise ValueError("A declared T1 condition is not complete")
        rows.append(row)
    means: dict[str, dict[str, Any]] = {}
    for arm in ("main", "operation_control"):
        conditions = [r for r in rows if r["arm"] == arm]
        if sorted(r["seed"] for r in conditions) != [0, 1, 2]:
            raise ValueError("All three registered seeds are required for each arm")
        means[arm] = {}
        for task, metric in (("memory_operation", "family_macro_acceptance"),
                             ("instruction_applicability", "family_macro_accuracy")):
            values = [r["validation"]["common_metrics"]["by_task"][task][metric]
                      for r in conditions]
            means[arm][task] = {"seeds_0_1_2": values, "mean": statistics.mean(values),
                               "sample_sd": statistics.stdev(values)}
    return {
        "status": "T1_SIX_FITS_AND_COMMON_EXPORT_EVALUATIONS_COMPLETE",
        "conditions": rows, "across_seed_descriptive_summary": means,
        "scope": "Native/static development diagnostics of final524 persisted checkpoints. "
                 "Matched updates/draws, different task exposure and token costs. "
                 "Not Host end-to-end efficacy, T2, E1 confirmation or external evaluation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plan = read_json(args.plan)
    ledger = Path(plan["ledger"])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "logs").mkdir()
    write_json(args.output / "plan.json", plan)
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "started_epoch": time.time(), "source_version": plan["source_version"],
        "completed": [], "actual_models_serialized": True, "automatic_retry": False}
    path = args.output / "driver.json"
    write_json(path, driver)
    cpu = time.process_time()
    try:
        for stage in plan["jobs"]:
            if (args.output / "stop-after-current").exists():
                driver["status"] = "STOPPED_AFTER_CURRENT_BY_REQUEST"
                return
            if Path(stage["output"]).exists():
                raise ValueError("A model output already exists; do not replay an earlier attempt")
            if stage["phase"] in read_json(ledger).get("compute", {}):
                raise ValueError("The model phase already has a ledger entry")
            environment = {**os.environ, **stage["environment"]}
            log = args.output / "logs" / (stage["name"] + ".log")
            with log.open("x") as stream:
                child = subprocess.Popen(  # noqa: S603 -- explicit local experiment argv, no shell
                    stage["argv"], env=environment, stdout=stream,
                                         stderr=subprocess.STDOUT)
                driver["active"] = {**stage, "pid": child.pid, "log": str(log),
                                    "started_epoch": time.time()}
                write_json(path, driver)
                print(json.dumps({"event": "stage_started", **driver["active"]}), flush=True)
                code = child.wait()
            driver["active"].update(exit_code=code, finished_epoch=time.time())
            write_json(path, driver)
            if code:
                raise RuntimeError("First failed model stage retained; sequence stopped")
            audit = (audit_fit(stage, ledger) if stage["kind"] == "fit"
                     else audit_export(stage, ledger))
            driver["completed"].append({**driver.pop("active"), "audit_status": audit["status"]})
            # Only this parent's CPU is recorded, after its model child has exited.
            now = time.process_time()
            with ledger.with_name("budget.json.http-owner.lock").open("a+b") as lease:
                fcntl.flock(lease, fcntl.LOCK_EX)
                budget = RunBudget(RunLimits(**read_json(ledger)["limits"]), ledger)
                budget.record_compute("host_intent_t1_completion_orchestration_v1",
                                      {"cpu_seconds": now - cpu})
            cpu = now
            write_json(path, driver)
            print(json.dumps({"event": "stage_closed", "name": stage["name"],
                              "audit_status": audit["status"]}), flush=True)
        write_json(args.output / "results.json", summarize(plan))
        driver["status"] = "COMPLETED"
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(finished_epoch=time.time(),
                      final_cpu_seconds_not_yet_recorded=time.process_time() - cpu)
        write_json(path, driver)


if __name__ == "__main__":
    main()
