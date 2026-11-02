"""Reconcile retained execution segments into original Host task denominators."""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json
from prepare_optimization_host_continuation import (
    arm_view,
    segment_paths,
    validate_continuation,
)
from summarize_optimization_host import summarize_cohort


def summarize_arm(
    parent_path: Path,
    arm_id: str,
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    parent = read_json(parent_path)
    scopes = [parent_path, *segment_paths(parent_path, arm_id)]
    supplied = [r for r in reviews if r["arm_id"] == arm_id]
    if len(supplied) != len({(r["history"], r["request"]) for r in supplied}):
        raise ValueError("Only one review is allowed for each original arm/task")
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    run_summaries = []
    used_reviews = []
    intervals = []
    for index, path in enumerate(scopes):
        if index:
            validate_continuation(path)
        dispatch = read_json(path)
        view = arm_view(dispatch, arm_id)
        output = Path(view["arms"][0]["output"]).resolve()
        local_reviews = [
            r for r in supplied if Path(r["result_path"]).resolve().is_relative_to(output)
        ]
        result = summarize_cohort(view, local_reviews)
        used_reviews.extend(local_reviews)
        for row in result["positions"]:
            key = row["history"], row["request"]
            if not index:
                merged[key] = copy.deepcopy(row)
            elif row["execution"] != "NOT_EXECUTED":
                if key not in merged or merged[key]["execution"] != "NOT_EXECUTED":
                    raise ValueError("A continuation would replace a retained original attempt")
                merged[key] = {**copy.deepcopy(row), "continuation_dispatch": str(path)}
        arm = result["arms"][0]
        cost = arm["costs"]
        # Preserve real resource vectors; do not add nested message/inference/driver CPU.
        run_summaries.append(
            {
                "dispatch": str(path),
                "output": str(output),
                "native_status": arm["status"],
                "planned_segment_positions": arm["planned_positions"],
                "inference_condition_status": arm["inference_condition_status"],
                "native_costs": (
                    {
                        **cost,
                        "compute": {
                            k: v
                            for k, v in cost["compute"].items()
                            if any(value != 0 for value in v.values())
                        },
                    }
                    if cost is not None
                    else None
                ),
            }
        )
        native_path = output / "driver.json"
        if native_path.exists():
            native = read_json(native_path)
            intervals.append((native["started_epoch"], native["finished_epoch"]))
    if len(used_reviews) != len(supplied):
        raise ValueError("A review is not bound to one actual retained segment result")
    intervals.sort()
    if any(a[1] > b[0] for a, b in pairwise(intervals)):
        raise ValueError("Execution segments overlap; their native costs are not disjoint")
    rows = list(merged.values())
    expected = parent["study"]["positions_per_unique_arm"]
    if len(rows) != expected:
        raise ValueError("Continuation changed the original arm denominator")
    costs = [r["native_costs"] for r in run_summaries if r["native_costs"] is not None]
    totals: dict[str, Any] = {"generation_requests": sum(c["generation_requests"] for c in costs)}
    for kind in ("generation", "embedding"):
        keys = {key for c in costs for key in c[kind]}
        totals[kind] = {key: sum(c[kind].get(key, 0) for c in costs) for key in keys}
    return {
        "status": "ORIGINAL_ARM_RESULTS_WITH_RETAINED_SEGMENTS_RECONCILED",
        "parent_dispatch": str(parent_path),
        "arm_id": arm_id,
        "parent_cohort_planned_positions": parent["planned_positions"],
        "planned_positions": expected,
        "positions": rows,
        "runs": run_summaries,
        "original_native_status": run_summaries[0]["native_status"],
        "attempted_positions": sum(r["execution"] != "NOT_EXECUTED" for r in rows),
        "native_completed": sum(r["result_status"] == "COMPLETED" for r in rows),
        "native_failed": sum(r["result_status"] == "FAILED" for r in rows),
        "execution_counts": dict(Counter(r["execution"] for r in rows)),
        "semantic_counts": dict(Counter(r["semantic_grade"] for r in rows)),
        "delivery_counts": dict(Counter(r["delivery_grade"] for r in rows)),
        "confirmed_task_successes": sum(r["confirmed_task_success"] for r in rows),
        "native_generation_embedding_totals": totals,
        "cost_scope": "Native disjoint request/token deltas sum across retained segments. Local "
        "compute vectors remain per run, with actual extra model loads and recovery "
        "overhead; offline CPU settlements are separate. No peak-memory summation "
        "or rebilling occurs here. Calendar gaps are not per-request latency.",
        "scope": "Original failed batch remains failed. Every original position remains present; "
        "entered/failed attempts are never replaced. This arm-specific report does not "
        "claim the other cohort arms are closed or reviewed.",
        "model_calls": 0,
        "no_sha_validation": True,
    }


def summarize_all(parent_path: Path, reviews: list[dict[str, Any]]) -> dict[str, Any]:
    parent = read_json(parent_path)
    arms = [summarize_arm(parent_path, a["id"], reviews) for a in parent["arms"]]
    rows = [row for arm in arms for row in arm["positions"]]
    if len(rows) != parent["planned_positions"]:
        raise ValueError("Original cohort denominator changed")
    known_arms = {a["arm_id"] for a in arms}
    if any(r["arm_id"] not in known_arms for r in reviews):
        raise ValueError("Review belongs to an undeclared original arm")
    return {
        "status": "ORIGINAL_COHORT_WITH_EXPLICIT_CONTINUATIONS_RECONCILED",
        "parent_dispatch": str(parent_path),
        "planned_positions": len(rows),
        "arms": arms,
        "positions": rows,
        "model_calls": 0,
        "no_sha_validation": True,
        "scope": "All original arms/tasks retained, with explicit segment lineage. Original "
        "batch failures, unknown quality and unexecuted positions are not erased.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arm-id")
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    reviews = read_json(args.reviews)["reviews"] if args.reviews else []
    result = (
        summarize_arm(args.dispatch.resolve(), args.arm_id, reviews)
        if args.arm_id
        else summarize_all(args.dispatch.resolve(), reviews)
    )
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(result["status"], result["planned_positions"])


if __name__ == "__main__":
    main()
