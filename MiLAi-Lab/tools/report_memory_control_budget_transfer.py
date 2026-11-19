"""Compare one fixed DEV cohort across material budgets using actual Reader replies."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.scorers.memory_control_episode_metrics import (
    input_result,
    paired_budget_response_metrics,
)

CaseKey = tuple[str, int, int]
TERMINAL = {
    "scored", "scored_format_failure", "reader_interrupted", "reader_error", "scorer_error",
    "action_failed",
}


def _wire_and_task_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(left.get("reader_wire")) and all(
        left[key] == right[key] for key in ("reader_wire", "task_id", "dataset", "native_group")
    )


def budget_transfer_report(root: Path) -> dict[str, Any]:
    design = read_json(root / "design.json")
    preparation = read_json(root / "preparation-receipt.json")
    if preparation["status"] != "PREPARED_HELD_BUDGET_TRAJECTORIES":
        raise ValueError("The held-budget program requires completed actual local trajectories")
    plan = read_json(Path(design["reference_population"]))
    base_budget = design["reference_budget"]
    budgets = design["control_budgets"]
    cases: dict[CaseKey, dict[str, Any]] = {}
    for row in read_json(root / "case-bindings.json"):
        key = (row["arm"], row["budget"], row["task_id"])
        if key in cases or row["disposition"] not in {"fresh", "shared"}:
            raise ValueError("Use one exact dispatch or shared-response binding per held case")
        cases[key] = row
    arms = design["reported_arms"]
    by_id = {row["task_id"]: row for row in plan["tasks"]}
    roster = {(arm, cap, tid) for arm in arms for cap in budgets for tid in by_id}
    if set(cases) != roster or len(by_id) != len(plan["tasks"]):
        raise ValueError("Held budgets must cover the complete registered DEV cohort")
    for key, case in cases.items():
        if any(case[k] != by_id[key[2]][k] for k in ("dataset", "native_group")):
            raise ValueError("Held case and native group declaration disagree")

    baseline = {
        name: input_result(Path(path)) for name, path in design["reference_reader_runs"].items()
    }
    if set(baseline) != set(arms) or any(
        protocol["population"] != plan or protocol["arm"]["name"] != name
        or plan["role"] != "dev" or plan["material_budget"] != base_budget
        or set(records) != set(by_id)
        for name, (protocol, records) in baseline.items()
    ):
        raise ValueError("Reference runs must match the registered DEV tasks and arm bindings")
    fresh_by_run: dict[tuple[str, int], set[int]] = defaultdict(set)
    for (arm, budget, tid), row in cases.items():
        if row["disposition"] == "fresh":
            if row["origin_budget"] != budget:
                raise ValueError("A fresh response must be collected at its declared budget")
            fresh_by_run[arm, budget].add(tid)

    observed: dict[CaseKey, dict[str, Any]] = {}
    fresh_statuses: Counter[str] = Counter()
    for (arm, budget), expected in fresh_by_run.items():
        directory = root / "actual" / str(budget) / arm
        protocol, records = input_result(directory)
        ref, _ = baseline[arm]
        declared = [row for row in plan["tasks"] if row["task_id"] in expected]
        if (
            protocol["comparison"] != ref["comparison"] or protocol["arm"] != ref["arm"]
            or protocol["population"]["role"] != "dev"
            or protocol["population"]["dataset_run_id"] != plan["dataset_run_id"]
            or protocol["population"]["material_budget"] != budget
            or protocol["population"]["tasks"] != declared or set(records) != expected
            or read_json(directory / "run.json", {}).get("status") != "COMPLETED"
            or any(row["status"] not in TERMINAL for row in records.values())
        ):
            raise ValueError("Actual Reader dispatch differs from the registered fresh requests")
        for tid, record in records.items():
            observed[arm, budget, tid] = record
            fresh_statuses[record["status"]] += 1

    packet_root = Path(preparation["scratch"])
    payloads: dict[tuple[str, int], dict[int, dict[str, Any]]] = defaultdict(dict)
    scopes: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for (arm, cap, tid), case in cases.items():
        prepared_path = packet_root / str(cap) / arm / "episodes" / f"{tid}.json"
        if Path(case["prepared_episode"]) != prepared_path:
            raise ValueError("The stored prepared request belongs to a different case")
        prepared = read_json(prepared_path)
        if prepared["status"] != "ready" or prepared["costs"]["reader_material_tokens"] > cap:
            raise ValueError("A prepared request exceeds its held budget or lacks execution")
        origin = case["origin_budget"]
        kind = case["disposition"]
        if origin == base_budget and kind == "shared":
            reply = baseline[arm][1][tid]
            binding = "same_wire_reference_response"
        else:
            key = (arm, origin, tid)
            if key not in observed or (kind == "shared" and origin == cap):
                raise ValueError("A held case lacks its own or its declared shared Reader reply")
            reply = observed[key]
            binding = "fresh_response" if kind == "fresh" else "same_wire_other_held_response"
        if not _wire_and_task_match(prepared, reply):
            raise ValueError("An observed reply belongs to a different request or native task")
        if "grade" in reply and reply["reader_result"]["status"] != "reader_completed":
            raise ValueError("An observed score requires an actual completed Reader reply")
        payloads[arm, cap][tid] = reply
        scopes[arm, cap][binding] += 1
        if reply.get("costs", {}).get("reader_usage_source") == "provider":
            scopes[arm, cap]["positions_with_observed_provider_input_usage"] += 1

    report: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for (arm, budget), replies in payloads.items():
        protocol, reference = baseline[arm]
        cap_plan = read_json(root / f"population-{budget}.json")
        summary = paired_budget_response_metrics(
            protocol, {**protocol, "population": cap_plan}, reference, replies,
            repeats=plan["bootstrap_repeats"], seed=plan["seed"],
        )
        report[arm][budget] = {**summary, "response_bindings": scopes[arm, budget]}
    return {
        "status": "REPORTED_ACTUAL_HELD_BUDGET_READOUTS",
        "reference_budget": base_budget,
        "held_budgets": budgets,
        "registered_tasks_per_arm": len(by_id),
        "new_reader_dispatch_positions": len(observed),
        "new_reader_terminal_statuses": fresh_statuses,
        "new_provider_metered_responses": sum(
            row.get("costs", {}).get("reader_usage_source") == "provider"
            for row in observed.values()
        ),
        "shared_response_rule": design["shared_request_rule"],
        "resource_scope": "observed input tokens of the bound request; shared timing excluded",
        "comparisons_vs_reference": report,
        "reader_requests_during_report": 0,
        "sha_validation": False,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    write_json(args.output, budget_transfer_report(args.root))


if __name__ == "__main__":
    main()
