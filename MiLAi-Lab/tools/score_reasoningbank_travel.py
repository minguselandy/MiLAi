"""Native travel scores with complete planned-group denominators, including failures.

Run in the external travel environment. Only this evaluator process reads answers;
no memory or model-generation client is imported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def score(config: dict) -> dict:
    root = Path(config["output_root"])
    checkout = Path(config["benchmark_root"]) / "MemoryArena"
    sys.path.insert(0, str(checkout))
    from env.env_systems.travel_planner_env import eval as native
    from env.env_systems.travel_planner_env.combination import parse_plan_text
    from env.env_systems.travel_planner_env.data_loader import _convert_row
    from run_travel import format_person_plan, parse_all_plans

    data = json.loads((Path(config["split_manifest"]).parent / "native/travel.json").read_text())
    selected = [_convert_row(row) for row in data if str(row["id"]) in config["ids"]]
    native.load_travel_data = lambda: selected
    gt, base_plans, _ = native.load_ground_truth()
    submissions = []
    groups = []
    for row in selected:
        identifier = str(row["id"])
        group_root = root / f"group-{identifier}"
        completed = []
        nonempty = set()
        accumulated = format_person_plan(
            row["base_person"]["name"], row["base_person"]["daily_plans"]
        )
        for question in row["questions"]:
            path = group_root / f"person-{question['round_idx']}.json"
            if path.exists():
                result = json.loads(path.read_text())
                completed.append(question)
                if result["final_plan"].strip():
                    nonempty.add(question["round_idx"])
                accumulated += "\n\n" + result["final_plan"]
        parsed = parse_all_plans(accumulated, row["questions"])
        predictions = {person["person_idx"]: parse_plan_text(person["result"]) for person in parsed}
        completed_ids = {question["round_idx"] for question in completed}
        if completed:
            submissions.append(
                {
                    "id": row["id"],
                    "persons": [
                        {"person_idx": i, "plan": plan}
                        for i, plan in predictions.items()
                        if i in completed_ids
                    ],
                }
            )
        persons = []
        for question in row["questions"]:
            index = question["round_idx"]
            ground_truth = gt[(row["id"], index)]
            prediction = predictions.get(index) if index in completed_ids else None
            constraints = native.find_constraint_slots(gt, base_plans, row["id"], index)
            passed = sum(
                native.check_slot_pass(ground_truth, prediction, day, slot)
                for day, slot in constraints
            )
            persons.append(
                {
                    "position": index,
                    "delivered": index in completed_ids,
                    "terminal": index in completed_ids,
                    "nonempty_final_plan": index in nonempty,
                    "full_pass": native.check_person_full_pass(ground_truth, prediction),
                    "constraint_passed": passed,
                    "constraint_total": len(constraints),
                }
            )
        rates = [
            p["constraint_passed"] / p["constraint_total"] for p in persons if p["constraint_total"]
        ]
        groups.append(
            {
                "id": identifier,
                "planned_sessions": len(persons),
                "delivered_sessions": len(completed),
                "terminal_sessions": len(completed),
                "nonempty_final_plans": len(nonempty),
                "persons": persons,
                "full_pass": all(p["full_pass"] for p in persons),
                "constraint_rate": sum(rates) / len(rates) if rates else None,
            }
        )
    raw_file = root / "coverage-raw-submission.jsonl"
    raw_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in submissions))
    raw = native.evaluate(str(raw_file), model_name=config["model"], memory_system=config["method"])
    people = [p for group in groups for p in group["persons"]]
    rates = [g["constraint_rate"] for g in groups if g["constraint_rate"] is not None]
    result = {
        "raw_native_metrics": raw,
        "coverage_corrected_metrics": {
            "ps": 100 * sum(p["full_pass"] for p in people) / len(people),
            "sps": 100 * sum(rates) / len(rates) if rates else 0,
            "sr": 100 * sum(g["full_pass"] for g in groups) / len(groups),
        },
        "planned_groups": len(groups),
        "complete_groups": sum(g["delivered_sessions"] == g["planned_sessions"] for g in groups),
        "planned_sessions": len(people),
        "delivered_sessions": sum(p["delivered"] for p in people),
        "terminal_sessions": sum(p["terminal"] for p in people),
        "nonempty_final_plans": sum(p["nonempty_final_plan"] for p in people),
        "legacy_field_note": "delivered_sessions counts terminal records, including empty plans",
        "groups": groups,
    }
    (root / "coverage-scores.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    score(json.loads(args.config.read_text()))


if __name__ == "__main__":
    main()
