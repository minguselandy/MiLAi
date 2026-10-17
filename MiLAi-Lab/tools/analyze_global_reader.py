"""Separate broad reference learning, source semantics and actual compute.

This reads saved first predictions only. A partial matrix is explicitly interim;
it never selects a seed, modifies training, or dispatches another model call.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluate_bounded_laya import score_predictions
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits


def action_kind(action: str) -> str:
    return "open" if action.startswith("open_") else action


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def diagnostics(rows: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, Counter[str]] = defaultdict(Counter)
    counts: Counter[str] = Counter()
    by_source: dict[int, dict[str, tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(dict)
    pairs: dict[str, dict[bool, bool]] = defaultdict(dict)
    for row, prediction in zip(rows, predictions, strict=True):
        meta = row["metadata"]
        gold = row["gold"].get("next", {}).get("probabilities", {})
        if not gold:
            counts["masked_reference"] += 1
            continue
        choice = prediction["choice"]
        accepted = int(gold.get(choice, 0) > 0)
        counts["selected_" + action_kind(choice)] += 1
        dimensions = [
            f"steps/{meta['steps']}",
            f"family/{meta['family']}",
            *[f"origin/{origin}" for origin in meta["prefix_origins"]],
        ]
        for key in dimensions:
            strata[key]["labelled"] += 1
            strata[key]["accepted"] += accepted
        open_scores = {
            k: v for k, v in prediction["probabilities"].items() if k.startswith("open_")
        }
        if any(k.startswith("open_") for k in gold):
            counts["complement_states"] += 1
            best = max(open_scores, key=lambda k: open_scores[k])
            counts["best_open_accepted"] += int(gold.get(best, 0) > 0)
        remaining = [
            i for i in meta["bm25_source_indices"] if i not in meta["opened_source_indices"]
        ]
        if remaining:
            lexical = f"open_p{meta['pool_source_indices'].index(remaining[0])}"
            counts["bm25_next_accepted"] += int(gold.get(lexical, 0) > 0)
        for origin in meta["prefix_origins"]:
            by_source[meta["row"]][origin] = row, prediction
        if "reference_complete" in meta["prefix_origins"]:
            pairs[meta["question_id"]][meta["answerable_full_context"]] = bool(accepted)
    transitions: dict[str, Counter[str]] = defaultdict(Counter)
    for views in by_source.values():
        for before in ("empty", "reference_leave_one_out"):
            if before not in views or "reference_complete" not in views:
                continue
            left, lp = views[before]
            right, rp = views["reference_complete"]
            lg = left["gold"]["next"]["probabilities"]
            rg = right["gold"]["next"]["probabilities"]
            if set(lg) == set(rg):
                continue
            stats = transitions[before + "_to_reference_complete"]
            stats["pairs"] += 1
            stats["both_accepted"] += int(
                lg.get(lp["choice"], 0) > 0 and rg.get(rp["choice"], 0) > 0
            )
            stats["semantic_action_kind_changed"] += int(
                action_kind(lp["choice"]) != action_kind(rp["choice"])
            )
    matched = [pair for pair in pairs.values() if set(pair) == {False, True}]
    return {
        "reference": score_predictions(rows, predictions),
        "counts": dict(counts),
        "strata": {k: dict(v) for k, v in strata.items()},
        "state_transitions": {k: dict(v) for k, v in transitions.items()},
        "paired_native_reference_complete": {
            "question_pairs": len(matched),
            "both_correct": sum(all(p.values()) for p in matched),
        },
        "origin_denominators_overlap": True,
        "bm25_scope": "Best remaining lexical candidate; candidate presentation itself is shuffled",
    }


def source_diagnostics(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    reviews: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Only recorded reviewed proofs determine positive action correctness.

    For insufficient pools, count claims of sufficiency without inventing a
    unique partial-evidence policy. Ambiguous cases retain their denominator.
    """
    counts: Counter[str] = Counter()
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    for row, prediction in zip(rows, predictions, strict=True):
        meta = row["metadata"]
        review = reviews[meta["row"]]
        disposition = review["disposition"]
        counts[disposition + "_states"] += 1
        if disposition == "masked":
            continue
        if disposition == "pool_insufficient":
            counts["strict_pool_insufficient_selected_sufficient"] += int(
                prediction["choice"] == "stop_sufficient"
            )
            continue
        opened = set(meta["opened_source_indices"])
        proofs = [set(path) for path in review["complete_proofs"]]
        if any(proof <= opened for proof in proofs):
            accepted = prediction["choice"] == "stop_sufficient"
            label = "source_proof_complete"
        else:
            useful = set().union(*(proof - opened for proof in proofs))
            actions = {f"open_p{meta['pool_source_indices'].index(i)}" for i in useful}
            accepted = prediction["choice"] in actions
            label = "source_missing_complement"
            open_scores = {
                k: v for k, v in prediction["probabilities"].items() if k.startswith("open_")
            }
            counts["source_best_open_accepted"] += int(
                max(open_scores, key=lambda k: open_scores[k]) in actions
            )
        counts[label + "_states"] += 1
        counts[label + "_accepted"] += int(accepted)
        by_family[meta["family"]]["states"] += 1
        by_family[meta["family"]]["accepted"] += int(accepted)
    return {
        "counts": dict(counts),
        "supported_family_results": {k: dict(v) for k, v in by_family.items()},
        "supported_family_macro_acceptance": sum(
            v["accepted"] / v["states"] for v in by_family.values()
        )
        / len(by_family)
        if by_family
        else None,
        "scope": "Author source review with recorded qualifications; not independent gold. "
        "No exhaustive open/STOP labels fabricated for insufficient or masked pools.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    driver = read_json(args.root / "driver.json")
    protocol = read_json(args.root / "protocol.json")
    reviews = {r["source_row"]: r for r in read_json(args.reviews)["cases"]}
    jobs, compact = [], []
    total_compute: Counter[str] = Counter()
    for job in driver["jobs"]:
        folder = Path(job["output"])
        run = read_json(folder / "run.json")
        if run["status"] != "COMPLETED":
            jobs.append({"job": job, "run": run, "status": "FAILED_OR_INCOMPLETE"})
            continue
        result = {"job": job, "optimizer_updates": run["optimizer_updates"], "splits": {}}
        for split in ("train", "dev"):
            rows = read_rows(Path(run["data"]) / f"{split}.jsonl")
            rows = [r for r in rows if r["gold"]] if split == "train" else rows
            predictions = [
                read_json(folder / split / str(run["epochs"]) / f"{i}.json")
                for i in range(len(rows))
            ]
            metrics = diagnostics(rows, predictions)
            if split == "dev":
                metrics["source_semantics"] = source_diagnostics(rows, predictions, reviews)
            result["splits"][split] = metrics
        compute = read_json(folder / "compute.json")
        measures = {
            k: v
            for k, v in compute.items()
            if k not in ("peak_rss_kib", "peak_cuda_allocated_bytes", "ledger")
        }
        total_compute.update(measures)
        result["compute_already_in_ledger"] = compute
        before = read_json(
            args.root / f"{job['cohort']}-{job['seed']}-{job['backend']}-budget-before.json"
        )
        after = read_json(
            args.root / f"{job['cohort']}-{job['seed']}-{job['backend']}-budget-after.json"
        )
        phase = "laya_reader_ce" if job["backend"] == "native" else "linear_reader_ce"
        result["original_ledger_delta_matches"] = all(
            abs(after["compute"][phase].get(k, 0) - before["compute"].get(phase, {}).get(k, 0) - v)
            < 1e-6
            for k, v in measures.items()
        )
        jobs.append(result)
        dev = result["splits"]["dev"]
        compact.append(
            {
                "cohort": job["cohort"],
                "seed": job["seed"],
                "backend": job["backend"],
                "train_accepted": result["splits"]["train"]["reference"]["counts"]["accepted"],
                "dev_accepted": dev["reference"]["counts"]["accepted"],
                "dev_macro": dev["reference"]["family_macro_acceptance"],
                "best_open": dev["counts"].get("best_open_accepted", 0),
                "source": dev["source_semantics"]["counts"],
            }
        )
    complete = driver["status"] == "COMPLETED" and len(jobs) == protocol["planned_jobs"]
    write_json(
        args.output / "report.json",
        {
            "status": "CLOSED_TRAINING_MATRIX" if complete else "INTERIM",
            "training_source_version": driver["source_version"],
            "planned_jobs": protocol["planned_jobs"],
            "closed_jobs": len(jobs),
            "jobs": jobs,
            "table": compact,
            "actual_training_compute_already_charged": dict(total_compute),
            "new_model_forwards": 0,
            "checkpoint_rule": protocol["checkpoint_rule"],
            "scope": "Prefix learning and annotated source semantics only; "
            "own-policyQA/transfer still required.",
        },
    )
    measures = {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "analyses": 1,
        "jobs_reviewed": len(jobs),
    }
    budget_path = Path(protocol["budget"])
    with budget_path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(budget_path)["limits"]), budget_path)
        budget.record_compute("global_reader_reference_v1_analysis", measures)
    write_json(args.output / "compute.json", measures)
    print(json.dumps(compact))


if __name__ == "__main__":
    main()
