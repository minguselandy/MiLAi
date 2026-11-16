"""Extend the frozen C20 CE selector to four opens, reusing identical first inputs.

This prepares the missing matched-cap STOP control. It performs no Reader/Judge
HTTP and does not change weights, ranking, source pools, or previous outputs.
"""

from __future__ import annotations

import argparse
import fcntl
import gc
import json
import os
import resource
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import NativeDecision
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.methods.bounded_evidence import select_bounded


def fixed_four(case: dict[str, Any], old_calls: Path, output: Path,
               predict: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    old = {}
    for path in old_calls.glob("*/input.json"):
        payload = read_json(path)
        key = tuple(p["id"] for p in payload["state"]["read_evidence"])
        old[key] = (payload, read_json(path.with_name("output.json")), path)
    trace = []

    def decide(payload: dict[str, Any]) -> str:
        key = tuple(p["id"] for p in payload["state"]["read_evidence"])
        if key in old:
            original, prediction, source = old[key]
            if original != payload:
                raise ValueError("Cached prefix has different model-visible input")
            reused = True
        else:
            source = output / "calls" / ("-".join(key) or "empty") / "input.json"
            write_json(source, payload)
            prediction = predict(payload)
            write_json(source.with_name("output.json"), prediction)
            reused = False
        trace.append({"source": str(source.resolve()), "reused": reused,
                      "input_tokens": prediction["input_tokens"],
                      "wall_seconds": prediction["wall_seconds"]})
        opens: dict[str, float] = {
            k: p for k, p in prediction["probabilities"].items() if k.startswith("open_")}
        return max(opens, key=lambda key: opens[key])

    result = select_bounded(case["question"], case["candidates"], decide,
                            max_candidates=len(case["candidates"]), max_reads=4)
    result.update(case_id=case["case_id"], policy="k4", controller_trace=trace,
                  standalone_model_input_tokens=sum(r["input_tokens"] for r in trace),
                  standalone_model_wall_seconds=sum(r["wall_seconds"] for r in trace))
    write_json(output / "k4.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    import torch

    prior = read_json(args.source / "run.json")
    if prior["status"] != "COMPLETED" or prior["backend"] not in {"laya", "linear"}:
        raise ValueError("This extension requires a closed native or linear selector")
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3":
        raise ValueError("Only allocated physical GPUs2,3 may be visible")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    torch.cuda.set_per_process_memory_fraction(0.75, 0)
    cases = [json.loads(x) for x in Path(prior["cases"]).read_text().splitlines()]
    run = {"status": "RUNNING", "pid": os.getpid(), "source_version": args.source_version,
           "source": str(args.source.resolve()), "planned_cases": len(cases), "completed_cases": 0,
           "checkpoint": prior["checkpoint"], "backend": prior["backend"],
           "physical_gpu": 2, "new_http_calls": 0}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    decision: NativeDecision | None = None
    try:
        if prior["backend"] == "linear":
            from linear_reader_classifier import LinearDecision

            decision = LinearDecision.load(Path(prior["checkpoint"]), prior["max_len"],
                                           prior["head_max_len"])
        else:
            decision = NativeDecision(Path(prior["checkpoint"]), prior["max_len"],
                                      prior["head_max_len"])
        decision.device = torch.device("cuda:0")
        decision.model.encoder.config.reference_compile = False
        decision.model.to(decision.device).eval()
        results = []
        for case in cases:
            result = fixed_four(case, args.source / case["case_id"] / "calls",
                                args.output / case["case_id"], decision.predict)
            original = read_json(args.source / case["case_id"] / "k2.json")
            if result["selected_ids"][:2] != original["selected_ids"]:
                raise ValueError("Fixed-four changed the original fixed-two prefix")
            results.append(result)
            run["completed_cases"] += 1
            write_json(args.output / "run.json", run)
        write_json(args.output / "results.json", results)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"runs": 1, "wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu,
                    **(decision.counters if decision is not None else {})}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(0)})
        terminal = dict(run)
        decision = None
        gc.collect()
        torch.cuda.empty_cache()
        write_json(args.output / "run.json", {**run, "status": "WAITING_LEDGER",
                                              "terminal_compute_status": terminal["status"]})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            phase = ("reader_ce_fixed4_extension_v1" if prior["backend"] == "laya"
                     else "reader_linear_fixed4_extension_v1")
            budget.record_compute(phase, measures)
        write_json(args.output / "run.json", {**terminal, "ledger_recorded": True})


if __name__ == "__main__":
    main()
