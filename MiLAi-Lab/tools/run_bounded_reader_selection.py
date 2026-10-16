"""Prepare source-bound MuSiQue cases and run finite selectors before Reader QA.

The runtime case file contains no answers, support labels or answerability.
Labels are separate evaluation data. Fixed-k and adaptive policies reuse an
identical-prefix prediction within each model/case, without subset enumeration.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import time
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import NativeDecision
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.methods.bounded_evidence import select_bounded
from ordinary_reader_reranker import OrdinaryDecision


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def prepare(decisions: Path, families: Path, output: Path) -> dict:
    from prepare_musique_decisions import ranked_pool

    output.mkdir(parents=True, exist_ok=False)
    initial = {row["metadata"]["row"]: row for row in read_rows(decisions)
               if not row["state"]["read_evidence"]}
    originals = {row["metadata"]["row"]: row["source"] for row in read_rows(families)
                 if row["metadata"]["row"] in initial}
    cases, labels, retrieval = [], [], []
    for source_row, row in sorted(initial.items()):
        source = originals[source_row]
        candidates = row["state"]["candidates"]
        mapping = dict(zip((p["id"] for p in candidates),
                           row["metadata"]["pool_source_indices"], strict=True))
        visible = {"question": source["question"], "paragraphs": [
            {k: p[k] for k in ("title", "paragraph_text")} for p in source["paragraphs"]]}
        started, cpu = time.perf_counter(), time.process_time()
        indices = ranked_pool(visible, len(candidates))
        retrieval.append({"case_id": f"row-{source_row}",
                          "wall_seconds": time.perf_counter() - started,
                          "cpu_seconds": time.process_time() - cpu,
                          "source_paragraphs": len(source["paragraphs"]), "selected": len(indices)})
        if indices != row["metadata"]["pool_source_indices"]:
            raise ValueError("Measured retrieval differs from the frozen candidate pool")
        cases.append({"case_id": f"row-{source_row}", "question": row["state"]["question"],
                      "candidates": candidates})
        labels.append({"case_id": f"row-{source_row}", "family": row["metadata"]["family"],
                       "source_row": source_row, "source": source,
                       "candidate_source_indices": mapping})
    for name, rows in (("cases", cases), ("labels", labels)):
        (output / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    result = {"cases": len(cases), "families": len({r["family"] for r in labels}),
              "source_decisions": str(decisions.resolve()),
              "source_families": str(families.resolve()),
              "pool_sizes": sorted({len(case["candidates"]) for case in cases}),
              "fixed_k": [2, 4, "full_pool"], "adaptive_read_limit": 4,
              "scope": "Existing dev families; two preview-exposed families; not blind benchmark"}
    write_json(output / "preparation.json", result)
    write_json(output / "common-retrieval-costs.json", retrieval)
    return result


def policies(case: dict[str, Any], predict: Any, output: Path) -> dict:
    cache: dict[tuple[str, ...], dict[str, Any]] = {}
    results = {}
    for policy, limit in (("k2", 2), ("adaptive", 4)):
        used = []
        fresh_wall = []

        def decide(payload, policy=policy, used=used, fresh_wall=fresh_wall):
            key = tuple(p["id"] for p in payload["state"]["read_evidence"])
            reused = key in cache
            if key not in cache:
                call_start = time.perf_counter()
                prediction = predict(payload)
                folder = output / "calls" / ("-".join(key) or "empty")
                write_json(folder / "input.json", payload)
                write_json(folder / "output.json", prediction)
                elapsed = time.perf_counter() - call_start
                cache[key] = {"prediction": prediction, "fresh_call_wall_seconds": elapsed}
                fresh_wall.append(elapsed)
            prediction = cache[key]["prediction"]
            used.append({"prefix": list(key), "input_tokens": prediction["input_tokens"],
                         "wall_seconds": prediction["wall_seconds"],
                         "fresh_call_wall_seconds": cache[key]["fresh_call_wall_seconds"],
                         "reused": reused,
                         "sequence_rows": prediction.get("sequence_rows", 1)})
            probabilities = prediction["probabilities"]
            options = probabilities if policy == "adaptive" else {
                key: p for key, p in probabilities.items() if key.startswith("open_")}
            return max(options, key=options.get)

        start = time.perf_counter()
        result = select_bounded(case["question"], case["candidates"], decide,
                                max_candidates=len(case["candidates"]), max_reads=limit)
        elapsed = time.perf_counter() - start
        result.update(policy=policy, case_id=case["case_id"], controller_trace=used,
                      control_wall_seconds=elapsed,
                      reconstructed_standalone_wall_seconds=elapsed - sum(fresh_wall)
                      + sum(r["fresh_call_wall_seconds"] for r in used),
                      standalone_model_wall_seconds=sum(r["wall_seconds"] for r in used),
                      standalone_model_input_tokens=sum(r["input_tokens"] for r in used),
                      standalone_model_sequence_rows=sum(r["sequence_rows"] for r in used))
        write_json(output / f"{policy}.json", result)
        results[policy] = result
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("decisions", type=Path)
    prep.add_argument("families", type=Path)
    prep.add_argument("output", type=Path)
    select = sub.add_parser("select")
    select.add_argument("cases", type=Path)
    select.add_argument("output", type=Path)
    select.add_argument("--backend", choices=("bm25", "laya", "ordinary", "linear"), required=True)
    select.add_argument("--checkpoint", type=Path)
    select.add_argument("--budget", type=Path, required=True)
    select.add_argument("--max-len", type=int, default=4096)
    select.add_argument("--head-max-len", type=int, default=384)
    args = parser.parse_args()
    if args.phase == "prepare":
        print(json.dumps(prepare(args.decisions, args.families, args.output)))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    cases = read_rows(args.cases)
    run = {"status": "RUNNING", "pid": os.getpid(), "backend": args.backend,
           "checkpoint": str(args.checkpoint.resolve()) if args.checkpoint else None,
           "max_len": args.max_len, "head_max_len": args.head_max_len,
           "cases": str(args.cases.resolve()), "planned_cases": len(cases), "completed_cases": 0}
    write_json(args.output / "run.json", run)
    decision = None
    try:
        if args.backend != "bm25":
            import torch

            if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3":
                raise ValueError("Use the allocated physical GPUs 2,3")
            torch.set_num_threads(4)
            torch.cuda.set_per_process_memory_fraction(0.75, 0)
            device = torch.device("cuda:0")
            if args.backend in {"laya", "linear"}:
                if args.backend == "linear":
                    from linear_reader_classifier import LinearDecision

                    decision = LinearDecision.load(args.checkpoint, args.max_len, args.head_max_len)
                else:
                    decision = NativeDecision(args.checkpoint, args.max_len, args.head_max_len)
                decision.model.encoder.config.reference_compile = False
                decision.model.to(device).eval()
                decision.device = device
            else:
                decision = OrdinaryDecision.load(args.checkpoint, device)
        results = []
        for case in cases:
            if args.backend == "bm25":
                # Prepared pool already records the original lexical retrieval order.
                result = {f"k{k}": {"case_id": case["case_id"], "selected_ids": [
                    p["id"] for p in case["candidates"][:k]], "policy": f"k{k}",
                    "stop_reason": "fixed_k", "decision_calls": 0}
                    for k in (2, 4, len(case["candidates"]))}
                for policy, row in result.items():
                    write_json(args.output / case["case_id"] / f"{policy}.json", row)
            else:
                result = policies(case, decision.predict, args.output / case["case_id"])
            results.append(result)
            run["completed_cases"] += 1
            write_json(args.output / "run.json", run)
            print(json.dumps({"completed": run["completed_cases"], "cases": len(cases)}),
                  flush=True)
        write_json(args.output / "results.json", results)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measures = {"wall_seconds": time.perf_counter() - start,
                    "cpu_seconds": time.process_time() - cpu, "runs": 1,
                    **(decision.counters if decision is not None else {})}
        write_json(args.output / "compute.json", {**measures,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "scope": "Incremental actual work; standalone policies add cached work separately"})
        with args.budget.with_name("budget.json.http-owner.lock").open("a+b") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            budget = RunBudget(RunLimits(**read_json(args.budget)["limits"]), args.budget)
            budget.record_compute("bounded_reader_selection_" + args.backend, measures)
        write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
