"""Offline native slot/coverage diagnostics; never return evaluator details to an agent."""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


def diagnose(config: dict) -> dict:
    root = Path(config["output_root"])
    sys.path.insert(0, str(Path(config["benchmark_root"]) / "MemoryArena"))
    from env.env_systems.travel_planner_env import eval as native
    from env.env_systems.travel_planner_env.combination import parse_plan_text
    from env.env_systems.travel_planner_env.data_loader import _convert_row
    from run_travel import format_person_plan, parse_all_plans

    data = json.loads((Path(config["split_manifest"]).parent / "native/travel.json").read_text())
    selected = [_convert_row(row) for row in data if str(row["id"]) in config["ids"]]
    native.load_travel_data = lambda: selected
    gt, bases, _ = native.load_ground_truth()
    coverage = json.loads((root / "coverage-scores.json").read_text())
    saved_groups = {g["id"]: g for g in coverage["groups"]}
    counts = collections.Counter()
    examples = []
    for row in selected:
        group_root = root / f"group-{row['id']}"
        accumulated = format_person_plan(
            row["base_person"]["name"], row["base_person"]["daily_plans"]
        )
        results = {}
        for q in row["questions"]:
            path = group_root / f"person-{q['round_idx']}.json"
            if path.exists():
                results[q["round_idx"]] = json.loads(path.read_text())
                accumulated += "\n\n" + results[q["round_idx"]]["final_plan"]
        parsed = parse_all_plans(accumulated, row["questions"])
        predictions = {p["person_idx"]: parse_plan_text(p["result"]) for p in parsed}
        scored = {p["position"]: p for p in saved_groups[str(row["id"])]["persons"]}
        for q in row["questions"]:
            index = q["round_idx"]
            result = results.get(index)
            prediction = predictions.get(index) if result is not None else None
            truth = gt[row["id"], index]
            assert native.check_person_full_pass(truth, prediction) == scored[index]["full_pass"]
            counts["planned_sessions"] += 1
            counts["full_pass_sessions"] += int(scored[index]["full_pass"])
            if result is not None:
                counts["terminal_sessions"] += 1
                calls = sum(len(step.get("tool_calls") or []) for step in result["scratchpad"])
                counts["native_tool_calls"] += calls
                counts["sessions_with_tool_calls"] += int(calls > 0)
                if result["final_plan"].strip() and not calls:
                    counts["nonempty_final_without_tool_calls"] += 1
                if not result["final_plan"].strip() and result["steps"] >= 30:
                    counts["empty_final_at_native_step_limit"] += 1
            if result is None:
                counts["no_terminal_record"] += 1
            elif not result["final_plan"].strip():
                counts["empty_final_plan"] += 1
            elif not prediction:
                counts["nonempty_but_unparsed_plan"] += 1
            changed = native.find_constraint_slots(gt, bases, row["id"], index)
            for day in truth:
                day_index = day.get("days") or day.get("day")
                if prediction and native.get_day(prediction, day_index) is None:
                    counts["missing_day_in_nonempty_plan"] += 1
                for slot in native.SLOTS:
                    counts["planned_slots"] += 1
                    if native.check_slot_pass(truth, prediction, day_index, slot):
                        counts["passed_slots"] += 1
                        continue
                    counts[f"mismatch_{slot}"] += 1
                    counts[
                        "mismatch_changed_slot"
                        if (day_index, slot) in changed
                        else "mismatch_unchanged_slot"
                    ] += 1
                    if result and prediction and len(examples) < 4:
                        actual_day = native.get_day(prediction, day_index) or {}
                        examples.append(
                            {
                                "group": str(row["id"]),
                                "person": index,
                                "day": day_index,
                                "slot": slot,
                                "query": q["query"],
                                "expected": day.get(slot, "-"),
                                "actual": actual_day.get(slot, "-"),
                            }
                        )
    output = {
        "counts": dict(counts),
        "examples": examples,
        "interpretation": (
            "Uses the pinned native fuzzy slot checker. Changed slots are differences from "
            "the supplied base plan, not a causal test of memory or cross-person reasoning. "
            "These counts do not independently verify monetary budgets or flight feasibility."
        ),
    }
    (root / "failure-diagnostics.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(json.loads(args.config.read_text()))["counts"]))
