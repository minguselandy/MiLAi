"""Evaluate frozen V0214 stage gates from completed evidence, without any model calls."""

import argparse
from pathlib import Path

from replay_v0213_cost import read, save
from summarize_v0214_e2e import summarize
from v02_local_provider import read_events


def phase_path(root, row):
    return root / "runs" / row["key"] / row["arm"] / f"phase-{row['phase']}"


def development(root: Path) -> dict:
    summary = summarize(root)
    rows = summary["phases"]
    h = [row for row in rows if row["arm"] == "H"]
    lookup = {(row["key"], row["phase"]): row for row in h}
    expected = {(f"dev-{index:02}", phase) for index in range(1, 9) for phase in (0, 1)}
    checks = {
        "all_16_declared_H_phases_present": set(lookup) == expected,
        "all_H_outcomes_correct": all(row["outcome"] in (
            "CORRECT", "CORRECT_CLARIFICATION") for row in h),
        "no_accounting_gaps": not summary["violations"],
        "no_unknown_usage": summary["unknown_provider_requests"] == 0,
        "no_external_business_execution": all(row["external_business_actions"] == 0 for row in h),
        "all_cold_processes_now_exited": all(not Path(f"/proc/{row['pid']}").exists() for row in h),
        "cold_identity_and_empty_messages": all(pair["distinct_pid"] and
            pair["same_binding"] and pair["inherited_messages"] == 0
            for pair in summary["cold_pairs"] if pair["arm"] == "H"),
    }
    if set(lookup) == expected:
        checks["no_memory_needed_skips_source_and_save"] = all(
            lookup[("dev-01", phase)]["acquisition"]["calls"] == 0 and
            lookup[("dev-01", phase)]["memory_mutations"] == 0 for phase in (0, 1))
        checks["clarification_then_current_choice"] = (
            lookup[("dev-04", 0)]["outcome"] == "CORRECT_CLARIFICATION" and
            lookup[("dev-04", 1)]["outcome"] == "CORRECT")
        checks["selective_long_not_full_scan"] = all(read(phase_path(root,
            lookup[("dev-03", phase)]) / "acquisition-plan.json")["mode"] == "LEXICAL_SEARCH"
            for phase in (0, 1))
        saved, resumed = lookup[("dev-06", 0)], lookup[("dev-06", 1)]
        checks["real_note_save_then_cold_recovery"] = (
            saved["memory_mutations"] == 1 and saved["save"].get("commit_status") == "COMMITTED"
            and resumed["cold"]["notes"]["items"] != [] and resumed["outcome"] == "CORRECT"
            and not read(phase_path(root, resumed) / "source-binding.json")["sources"]
            and any(event["purpose"] == "COLD_CURRENT_NOTE_READ" for event in read_events(
                phase_path(root, resumed) / "public-calls.jsonl")))
        checks["all_other_saves_NO_CHANGE"] = all(row["memory_mutations"] == 0 and
            row["save"] == "NO_CHANGE" for row in h if (row["key"], row["phase"]) != ("dev-06", 0))
        checks["two_task_overlap_each_phase"] = all(
            max(lookup[("dev-07", phase)]["started_monotonic"],
                lookup[("dev-08", phase)]["started_monotonic"]) <
            min(lookup[("dev-07", phase)]["ended_monotonic"],
                lookup[("dev-08", phase)]["ended_monotonic"]) for phase in (0, 1))
        checks["independent_binding_and_source_receipts"] = all(
            item["page"]["binding"] == row["cold"]["binding"] for row in h for item in read(
                phase_path(root, row) / "acquisition-calls.json")) and len({
                    tuple(row["cold"]["binding"].values()) for row in h}) == 8
    return {"status": "D5_REAL_HOST_E2E_DEV_PASS" if all(checks.values()) else "D5_NOT_PASS",
            "checks": checks, "root": str(root), "requests": summary["actual"],
            "scope": "Eight synthetic development lineages, not independent confirmation",
            "confirmation_bodies_read": False}


def confirmation(root: Path, dev_root: Path) -> dict:
    dev = read(dev_root / "stage-gate.json")
    if dev["status"] != "D5_REAL_HOST_E2E_DEV_PASS":
        raise ValueError("D5_PASS_REQUIRED")
    summary = summarize(root, allow_confirmation_after_result=True)
    config = read(root / "manifest.json")["config"]
    limits = config["productization_gate"]
    rows = summary["phases"]
    lookup = {(row["key"], row["arm"]): row for row in rows}
    h = [row for row in rows if row["arm"] == "H"]
    baseline = [row for row in rows if row["arm"] == "A0"]
    raw_h = sum(row["accounting"]["raw_tokens"] for row in h)
    raw_a0 = sum(row["accounting"]["raw_tokens"] for row in baseline)
    latency = [{"key": row["key"], "H_seconds": row["seconds"],
        "A0_seconds": lookup[(row["key"], "A0")]["seconds"]} for row in h]
    expected = {(key, arm) for key in config["tasks"] for arm in ("A0", "H")} | {
        (key, "LX") for key in config["lexical_task_keys"]}
    checks = {
        "fixed_allocation_no_replacement": set(lookup) == expected and len(rows) == len(expected),
        "all_four_H_correct": len(h) == 4 and all(row["outcome"] in (
            "CORRECT", "CORRECT_CLARIFICATION") for row in h),
        "no_negative_transfer": all(row["outcome"] not in (
            "CORRECT", "CORRECT_CLARIFICATION") or lookup[(row["key"], "H")]["outcome"] in (
                "CORRECT", "CORRECT_CLARIFICATION") for row in baseline),
        "no_memory_needed": lookup[("confirm-01", "H")]["outcome"] == "CORRECT" and
            lookup[("confirm-01", "H")]["acquisition"]["calls"] == 0,
        "ambiguity_negative_control": lookup[("confirm-02", "H")]["outcome"] ==
            "CORRECT_CLARIFICATION",
        "long_selective_and_bounded": all(read(phase_path(root, lookup[(key, "H")]) /
            "acquisition-plan.json")["mode"] == "LEXICAL_SEARCH" and
            lookup[(key, "H")]["acquisition"]["calls"] <= 12
            for key in config["lexical_task_keys"]),
        "D5_scope_and_cold_pass": dev["status"] == "D5_REAL_HOST_E2E_DEV_PASS",
        "total_token_ratio_within_frozen_boundary": raw_h <= raw_a0 * limits[
            "max_total_H_to_A0_raw_token_ratio"],
        "per_task_latency_within_frozen_boundary": all(item["H_seconds"] <= max(
            4 * item["A0_seconds"], item["A0_seconds"] + 10) for item in latency),
        "no_unknown_or_accounting_gaps": not summary["violations"] and
            summary["unknown_provider_requests"] == 0,
        "no_external_actions_or_memory_writes": all(row["external_business_actions"] == 0 and
            row["memory_mutations"] == 0 for row in rows),
    }
    return {"status": "PRODUCT_INTEGRATION_CANDIDATE" if all(checks.values()) else
            "KEEP_A0_HOST_CANDIDATE_REJECTED", "checks": checks, "root": str(root),
            "raw_H": raw_h, "raw_A0": raw_a0, "raw_ratio": raw_h / raw_a0 if raw_a0 else None,
            "latency": latency, "outcomes": summary["outcomes_by_arm"],
            "scope": "Four synthetic independent lineages, no external generalization",
            "default_flip": False, "schema_freeze": False}


def all_allocations(root: Path) -> dict:
    allocations = []
    for directory in sorted(root.iterdir()):
        if not directory.name.startswith(("d5-", "d6-")) or not (
                directory / "result.json").exists():
            continue
        summary = summarize(directory, allow_confirmation_after_result=True)
        allocations.append({"allocation": directory.name, **summary["actual"],
            "public_calls": summary["public_calls_total"],
            "host_cpu_seconds": summary["host_cpu_seconds_observed"],
            "unknown_provider_requests": summary["unknown_provider_requests"],
            "accounting_violations": summary["violations"], "cleanup": summary["cleanup"]})
    return {"status": "ALL_V0214_MODEL_ALLOCATIONS_RECONCILED", "allocations": allocations,
        "requests": sum(item["requests"] for item in allocations),
        "raw_tokens": sum(item["raw_tokens"] for item in allocations),
        "public_calls_d5_d6": sum(item["public_calls"] for item in allocations),
        "D0_public_calls_additional": read(root / "d0-live-summary.json").get(
            "actual_public_calls_total", 517),
        "failed_attempts_included": True, "cumulative_raw_cap": None,
        "cost_not_included_in_raw_tokens": ["agent reasoning and preparation labor",
            "CPU/GPU/disk/network/currency not inferred from token counts"],
        "previous_goals_excluded": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--development-root", type=Path)
    parser.add_argument("--all-allocations", action="store_true")
    args = parser.parse_args()
    result = (all_allocations(args.root) if args.all_allocations else
              confirmation(args.root, args.development_root) if args.development_root else
              development(args.root))
    output_name = "final-accounting.json" if args.all_allocations else "stage-gate.json"
    save(args.root / output_name, result)
    print(result["status"])
