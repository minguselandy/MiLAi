"""Measure frozen CE dependence on read contents at the same recorded prefixes.

This is an input-information perturbation, not a trained stateless comparator or
an on-policy rollout. Full-input first predictions are reused without rerunning.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import gc
import json
import os
import resource
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from evaluate_bounded_laya import NativeDecision
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.methods.bounded_evidence import decision_payload
from reviewed_reader_supervision import reviewed_target
from run_bounded_reader_selection import read_rows

VIEWS = {"titles_only": ("id", "title"), "ids_only": ("id",)}


def project(payload, view):
    result = copy.deepcopy(payload)
    result["state"]["read_evidence"] = [
        {key: item[key] for key in VIEWS[view]} for item in payload["state"]["read_evidence"]]
    return result


def prepare(protocol, output):
    output.mkdir(parents=True, exist_ok=False)
    original = read_json(Path(protocol["selector"]) / "run.json")
    fixed = read_json(Path(protocol["fixed_four"]) / "run.json")
    if original["status"] != "COMPLETED" or fixed["status"] != "COMPLETED":
        raise ValueError("The source selections must be closed")
    cases = read_rows(Path(original["cases"]))
    index = []
    for case in cases:
        chosen = read_json(Path(protocol["fixed_four"]) / case["case_id"] / "k4.json")
        by_id = {item["id"]: item for item in case["candidates"]}
        for step, trace in enumerate(chosen["controller_trace"]):
            source = Path(trace["source"])
            full = read_json(source)
            opened = chosen["selected_ids"][:step]
            expected = decision_payload(case["question"], [by_id[key] for key in opened],
                                       [item for item in case["candidates"]
                                        if item["id"] not in opened])
            if full != expected:
                raise ValueError("Frozen prefix differs from actual full selection")
            key = f"{case['case_id']}/{step}"
            for view in VIEWS:
                write_json(output / "inputs" / key / (view + ".json"), project(full, view))
            index.append({"key": key, "case_id": case["case_id"], "step": step,
                          "full_input": str(source), "full_output": str(source.with_name(
                              "output.json")), "opened_ids": opened})
    write_json(output / "index.json", index)
    write_json(output / "protocol.json", protocol)
    summary = {"status": "PREPARED", "cases": len(cases), "prefixes": len(index),
               "planned_positions": len(index) * len(VIEWS),
               "unchanged_empty_positions": (
                   sum(not row["opened_ids"] for row in index) * len(VIEWS)),
               "maximum_new_forwards": sum(bool(row["opened_ids"]) for row in index) * len(VIEWS),
               "checkpoint": original["checkpoint"], "max_len": original["max_len"],
               "head_max_len": original["head_max_len"], "new_model_calls": 0}
    write_json(output / "preparation.json", summary)
    return summary


def predict(prepared, output, source_version):
    import torch

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3":
        raise ValueError("Use allocated GPUs 2,3 only")
    output.mkdir(parents=True, exist_ok=False)
    protocol = read_json(prepared / "protocol.json")
    config = read_json(prepared / "preparation.json")
    index = read_json(prepared / "index.json")
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.cuda.set_per_process_memory_fraction(.75, 0)
    run = {"status": "RUNNING", "pid": os.getpid(), "source_version": source_version,
           "prepared": str(prepared.resolve()), "checkpoint": config["checkpoint"],
           "physical_gpu": 2, "planned_positions": config["planned_positions"],
           "completed_positions": 0, "reused_positions": 0, "new_forwards": 0,
           "http_requests": 0, "new_weights": False}
    write_json(output / "run.json", run)
    start, cpu = time.perf_counter(), time.process_time()
    decision, cache = None, {}
    try:
        decision = NativeDecision(Path(config["checkpoint"]), config["max_len"],
                                  config["head_max_len"])
        decision.model.encoder.config.reference_compile = False
        decision.device = torch.device("cuda:0")
        decision.model.to(decision.device).eval()
        run["precision"] = str(next(decision.model.parameters()).dtype)
        for row in index:
            full = read_json(Path(row["full_input"]))
            for view in VIEWS:
                payload = read_json(prepared / "inputs" / row["key"] / (view + ".json"))
                identity = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                reused_from = None
                if payload == full:
                    result = read_json(Path(row["full_output"]))
                    reused_from = row["full_output"]
                elif identity in cache:
                    result, reused_from = cache[identity]
                else:
                    result = decision.predict(payload)
                    run["new_forwards"] += 1
                destination = output / "calls" / row["key"] / view
                write_json(destination / "input.json", payload)
                write_json(destination / "output.json", result)
                write_json(destination / "provenance.json", {"reused_from": reused_from})
                cache.setdefault(identity, (result, str((destination / "output.json").resolve())))
                run["reused_positions"] += reused_from is not None
                run["completed_positions"] += 1
            write_json(output / "run.json", run)
            print(json.dumps({"completed": run["completed_positions"],
                              "new_forwards": run["new_forwards"]}), flush=True)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"runs": 1, "wall_seconds": time.perf_counter() - start,
                    "cpu_seconds": time.process_time() - cpu,
                    **(decision.counters if decision is not None else {})}
        write_json(output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(0)})
        terminal = dict(run)
        decision = None
        gc.collect()
        torch.cuda.empty_cache()
        write_json(output / "run.json", {**run, "status": "WAITING_LEDGER",
                                          "terminal_compute_status": terminal["status"]})
        budget_path = Path(protocol["budget"])
        with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
            budget.record_compute("reader_state_information_v1", measures)
        write_json(output / "run.json", {**terminal, "ledger_recorded": True})


def top_open(probabilities):
    return max((key for key in probabilities if key.startswith("open_")),
               key=probabilities.__getitem__)


def score(prepared, output):
    if read_json(output / "run.json")["status"] != "COMPLETED":
        raise ValueError("All first perturbation predictions must be closed")
    protocol = read_json(prepared / "protocol.json")
    labels = {row["case_id"]: row for row in read_rows(Path(protocol["labels"]))}
    reviews = {row["source_row"]: row for row in read_json(Path(protocol["source_review"]))["cases"]
               if row["split"] == "dev"}
    records = []
    for row in read_json(prepared / "index.json"):
        full = read_json(Path(row["full_input"]))
        base = read_json(Path(row["full_output"]))
        label = labels[row["case_id"]]
        target, status = {}, "not_source_reviewed"
        if label["source_row"] in reviews:
            mapping = label["candidate_source_indices"]
            target, status = reviewed_target(reviews[label["source_row"]],
                [mapping[f"p{i}"] for i in range(len(mapping))],
                [mapping[key] for key in row["opened_ids"]])
        record = {**row, "family": label["family"], "reference_target": target,
                  "reference_status": status, "views": {"full": base}}
        for view in VIEWS:
            folder = output / "calls" / row["key"] / view
            if read_json(folder / "input.json") != project(full, view):
                raise ValueError("Observed input differs from frozen perturbation")
            record["views"][view] = read_json(folder / "output.json")
        records.append(record)
    summary, qualified = {}, {}
    for view in VIEWS:
        values = [row for row in records if row["opened_ids"]]
        changes, families = Counter(), defaultdict(list)
        distances, stop_differences = [], []
        for row in values:
            base, changed = row["views"]["full"], row["views"][view]
            p, q = base["probabilities"], changed["probabilities"]
            if p.keys() != q.keys():
                raise ValueError("Perturbation changed offered actions")
            change = base["choice"] != changed["choice"]
            changes["decision_changed"] += change
            changes["top_open_changed"] += top_open(p) != top_open(q)
            families[row["family"]].append(int(change))
            distances.append(sum(abs(p[key] - q[key]) for key in p) / 2)
            stop_differences.append(sum(q[key] - p[key] for key in p
                                        if key.startswith("stop_")))
        summary[view] = {"nonempty_prefixes": len(values), **changes,
            "mean_total_variation": mean(distances),
            "mean_stop_probability_delta": mean(stop_differences),
            "family_macro_decision_change": mean(mean(v) for v in families.values()),
            "per_family_decision_change": {k: mean(v) for k, v in sorted(families.items())}}
    for view in ("full", *VIEWS):
        counts, strata = Counter(), defaultdict(Counter)
        for row in records:
            if not row["reference_target"]:
                counts[row["reference_status"]] += 1
                continue
            accepted = row["views"][view]["choice"] in row["reference_target"]
            counts["labelled"] += 1
            counts["accepted"] += accepted
            strata[row["reference_status"]]["labelled"] += 1
            strata[row["reference_status"]]["accepted"] += accepted
            if row["opened_ids"]:
                counts["nonempty_labelled"] += 1
                counts["nonempty_accepted"] += accepted
        qualified[view] = {"counts": dict(counts),
                           "strata": {k: dict(v) for k, v in strata.items()}}
    result = {"status": "CLOSED_INPUT_SENSITIVITY_REVIEW", "sensitivity": summary,
              "source_qualified": qualified, "records": records,
              "scope": protocol["interpretation_limits"]}
    write_json(output / "review.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "predict", "score"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version")
    args = parser.parse_args()
    if args.phase == "prepare":
        print(json.dumps(prepare(read_json(args.source), args.output)))
    elif args.phase == "predict":
        predict(args.source, args.output, args.source_version)
    else:
        result = score(args.source, args.output)
        print(json.dumps({k: v for k, v in result.items() if k != "records"}))


if __name__ == "__main__":
    main()
