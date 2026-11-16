"""Audit the complete E1 fits and nominate two saved candidates, never a task winner."""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import analyze
from milai_lab.harness.artifact_io import read_json, write_json

ARMS = ("delivery-only", "answer-first-full", "answer-first-head")


def nominate(analyses: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One delivery control and one masked candidate; common metric and earliest ties."""
    if set(analyses) != set(ARMS):
        raise ValueError("E1 nomination requires all three declared terminal analyses")
    candidates = {}
    for arm in ARMS:
        report = analyses[arm]
        if report["recipe"]["planned_optimizer_updates"] != report["curve"][-1]["update"]:
            raise ValueError("An incomplete curve cannot nominate a final E1 candidate")
        eligible = [p for p in report["curve"] if p["update"] > 0
                    and p["answer_first"]["coverage"].get("target_pairs", 0)]
        if not eligible or any(not math.isfinite(p["answer_first"]["weighted_task_pair_loss"])
                               for p in eligible):
            raise ValueError("E1 nomination needs observed finite common-metric support")
        point = min(eligible, key=lambda p: (p["answer_first"]["weighted_task_pair_loss"],
                                            p["update"]))
        candidates[arm] = {"arm": arm, "update": point["update"],
            "checkpoint": point["checkpoint"],
            "common_masked_loss": point["answer_first"]["weighted_task_pair_loss"]}
    masked = min((candidates[a] for a in ARMS[1:]), key=lambda c: (
        c["common_masked_loss"], c["update"], ARMS.index(c["arm"])))
    return [candidates["delivery-only"], masked]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    start = time.process_time()
    plan = read_json(args.plan)
    if [p["condition"] for p in plan["plans"]] != list(ARMS):
        raise ValueError("E1 arm identities or order changed")
    analyses = {arm: analyze(plan, arm, quality_mode="quality-tie" if arm == ARMS[0] else None,
        answer_first=arm != ARMS[0], component_sum=True, replay_objective="set") for arm in ARMS}
    nominees = nominate(analyses)
    args.output.mkdir(parents=True, exist_ok=False)
    for arm, report in analyses.items():
        write_json(args.output / (arm + "-native.json"), report)
    write_json(args.output / "nomination.json", {
        "status": "TWO_OFFLINE_E1_NOMINEES;SAVED_AND_ACTUAL_TASK_SELECTION_PENDING",
        "fit_plan": str(args.plan.resolve()), "protocol": plan["protocol"],
        "nominees": nominees, "mandatory_update0": plan["common_initialization"],
        "deployment_selection": None, "actual_task_dev_completed": False,
        "scope": "Common old64 feedback diagnostic only. Delivery control is retained even if "
            "another masked checkpoint ranks lower. Update0 remains a separate mandatory control. "
            "Native logits and saved FP16 weights differ; saved loading and the fixed32 actual "
            "full-menu outcomes, including unexecuted/failed cases, still determine selection.",
        "model_calls": 0, "ledger_recorded": False, "no_sha_validation": True,
        "cpu_seconds_pending": time.process_time()-start})
    print(nominees)


if __name__ == "__main__":
    main()
