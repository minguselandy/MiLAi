"""Measure native Laya decisions on frozen read prefixes, without generation.

All model-visible requests and first outputs are saved. Reference labels are
used only after the forward pass. The original shared ledger receives CPU cost;
no HTTP request or zero-output-token saving is invented for this local workload.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.providers.laya_local import NativeDecision


def score_applicability_predictions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Published candidate labels measure applicability, not operation sufficiency."""
    counts: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    families: dict[str, list[int]] = {}
    for row, predicted in zip(rows, predictions, strict=True):
        target = row["gold"].get("applicability", {}).get("probabilities", {})
        if not target:
            counts["masked"] += 1
            continue
        expected = max(target, key=target.__getitem__)
        choice = predicted["choice"]
        correct = int(expected == choice)
        confusion[expected, choice] += 1
        counts["labelled"] += 1
        counts["correct"] += correct
        families.setdefault(row["metadata"]["family"], []).append(correct)
    return {"counts": dict(counts), "families": len(families),
            "family_macro_accuracy": (sum(sum(v) / len(v) for v in families.values())
                                      / len(families) if families else None),
            "confusion": [{"expected": e, "predicted": p, "count": n}
                          for (e, p), n in sorted(confusion.items())],
            "scope": "Published candidate applicability labels; not factuality, calibrated "
                     "confidence, operation preference or Host task success"}


def score_predictions(
    rows: list[dict[str, Any]], predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    constant_stops: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    family: dict[str, list[int]] = {}
    for row, predicted in zip(rows, predictions, strict=True):
        target = row.get("gold", {}).get("next", {}).get("probabilities", {})
        if not target:
            counts["masked_reference"] += 1
            continue
        choice = predicted["choice"]
        accepted = int(target.get(choice, 0) > 0)
        for stop in ("stop_sufficient", "stop_exhausted"):
            constant_stops[stop] += int(target.get(stop, 0) > 0)
        counts["labelled"] += 1
        counts["accepted"] += accepted
        status = row["metadata"]["label_status"]
        stats = strata.setdefault(status, Counter())
        stats["labelled"] += 1
        stats["accepted"] += accepted
        group = row["metadata"]["family"]
        family.setdefault(group, []).append(accepted)
        if choice == "stop_sufficient" and target.get(choice, 0) == 0:
            counts["unsupported_sufficient_stop"] += 1
        if choice == "stop_exhausted" and target.get(choice, 0) == 0:
            counts["unsupported_exhaustion_stop"] += 1
        if choice.startswith("open_") and any(k.startswith("stop_") for k in target):
            counts["unnecessary_continue"] += 1
        first = next((k for k in row["questions"]["next"]["criteria"]
                      if k.startswith("open_")), "stop_exhausted")
        counts["first_remaining_candidate_accepted"] += int(target.get(first, 0) > 0)
    return {"counts": dict(counts), "strata": {k: dict(v) for k, v in strata.items()},
            "constant_stop_reference": dict(constant_stops),
            "family_macro_acceptance": sum(sum(v) / len(v) for v in family.values()) / len(family),
            "families": len(family),
            "scope": "Reference-proof prefix decisions; not Reader QA or net pipeline benefit"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--compute-phase", help="Distinct phase in the original shared ledger")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-len", type=int, default=4096)
    parser.add_argument("--head-max-len", type=int, default=384)
    parser.add_argument("--task", choices=("bounded_reader", "memory_operation",
                                           "instruction_applicability", "mixed_retrieval"),
                        default="bounded_reader")
    parser.add_argument("--operation-state", choices=("full", "mechanical", "shared"),
                        default="full")
    args = parser.parse_args()
    import torch

    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in args.data.read_text().splitlines()]
    if args.task == "memory_operation":
        from milai_lab.methods.laya_memory_policy import project_operation_payload

        rows = [project_operation_payload(row, args.operation_state) for row in rows]
    elif args.task == "mixed_retrieval":
        from retrieval_mixture import project_mixed_row

        rows = [project_mixed_row(row, args.operation_state) for row in rows]
    run = {"status": "RUNNING", "pid": os.getpid(), "data": str(args.data.resolve()),
           "checkpoint": str(args.checkpoint.resolve()), "device": args.device,
           "visible_cuda_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
           "threads": args.threads, "max_len": args.max_len,
           "head_max_len": args.head_max_len, "completed_states": 0, "planned_states": len(rows),
           "task": args.task, "operation_state": args.operation_state,
           "calibrated": False, "http_requests": 0}
    write_json(args.output / "run.json", run)
    started, cpu = time.perf_counter(), time.process_time()
    predictions = []
    model = None
    try:
        model = NativeDecision(args.checkpoint, args.max_len, args.head_max_len, args.device)
        run["loaded_weight_dtype"] = str(next(model.model.parameters()).dtype)
        for index, row in enumerate(rows):
            payload = {k: row[k] for k in ("state", "questions")}
            write_json(args.output / "calls" / str(index) / "input.json", payload)
            prediction = model.predict(payload)
            write_json(args.output / "calls" / str(index) / "output.json", prediction)
            predictions.append(prediction)
            run["completed_states"] += 1
            write_json(args.output / "run.json", run)
            print(json.dumps({"completed": len(predictions), "planned": len(rows),
                              "input_tokens": prediction["input_tokens"]}), flush=True)
        from milai_lab.methods.memory_control_learning import score_operation_predictions
        from retrieval_mixture import score_mixed_predictions

        scorer = {"bounded_reader": score_predictions,
                  "memory_operation": score_operation_predictions,
                  "mixed_retrieval": score_mixed_predictions,
                  "instruction_applicability": score_applicability_predictions}[args.task]
        write_json(args.output / "results.json", scorer(rows, predictions))
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"wall_seconds": time.perf_counter() - started,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **(model.counters if model is not None else {})}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "ledger": str(args.budget)})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            phase = args.compute_phase or {
                "bounded_reader": "laya_reader_prefix",
                "memory_operation": "laya_memory_operation_evaluation",
                "mixed_retrieval": "laya_mixed_retrieval_evaluation",
                "instruction_applicability": "laya_candidate_applicability",
            }[args.task]
            budget.record_compute(phase, measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
