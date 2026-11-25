"""Summarize native quality, observed-resource coverage and measured end-to-end costs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.runners.memory_control_reader_timing import FINISHED_HISTOGRAMS
from milai_lab.scorers.memory_control_episode_metrics import (
    QUALITY_AXES,
    SOURCES,
    input_result,
    paired_inline_latency,
    percentiles,
    select_dev_records,
)
from milai_lab.scorers.memory_control_native import musique_pair
from report_memory_control_v13_project_cost import readout_charge_evidence, window_records


def measured(values):
    if not values:
        return {"n": 0, "total": None, "p50": None, "p95": None}
    return {
        "n": len(values),
        "total": sum(values),
        "p50": percentiles(values, 0.50),
        "p95": percentiles(values, 0.95),
    }


def annotation_diagnostics(groups):
    covered = defaultdict(Counter)
    quality = defaultdict(list)
    for (source, _), members in groups.items():
        for row in members:
            cov = row["annotation_coverage"]
            if cov["delivered_complete_set"] is None:
                covered[source]["unknown_or_no_annotated_set"] += 1
                continue
            covered[source]["tasks_with_annotated_set"] += 1
            covered[source]["reachable_before_budget"] += cov["available_before_budget"]
            covered[source]["delivered"] += cov["delivered_complete_set"]
            if cov["delivered_complete_set"] and "grade" in row:
                if source == MUSIQUE:
                    if len(members) == 2 and all("grade" in r for r in members):
                        metric = musique_pair([r["grade"]["native_metrics"] for r in members])
                        quality[source].append(metric[QUALITY_AXES[source]])
                else:
                    quality[source].append(row["grade"]["native_metrics"][QUALITY_AXES[source]])
    return {
        s: dict(
            counts,
            measured_native_units=len(quality[s]),
            quality_given_annotated_set=fmean(quality[s]) if quality[s] else None,
        )
        for s, counts in covered.items()
    }


def action_counts(packet):
    trace = packet.get("control", {}).get("trace")
    prefix = packet.get("actual_cold_prefix", [])
    if trace is None:
        return None
    common_search = int(bool(prefix) and prefix[0] == "search")
    counts = dict(
        operations=common_search + len(trace),
        common_search=common_search,
        reads=0,
        handoffs=0,
        repeated_object_reads=0,
        r3_after_r2=0,
    )
    opened = {}
    for step in trace:
        choice = next((a for a in step["actions"] if a["id"] == step["selected"]), None)
        if choice is None:
            return None
        if choice["kind"] == "HANDOFF":
            counts["handoffs"] += 1
        if choice["kind"] != "READ" or not (step.get("result") or {}).get("ok", False):
            continue
        index = choice["parameters"]["index"]
        expanded = bool(choice["parameters"].get("expand_context"))
        counts["reads"] += 1
        counts["repeated_object_reads"] += index in opened
        counts["r3_after_r2"] += expanded and opened.get(index) is False
        opened[index] = expanded
    return counts


def packet_measurements(arm, pop, episodes, load_per_attempt):
    groups = defaultdict(list)
    costs = defaultdict(list)
    statuses = Counter()
    operations = defaultdict(list)
    unavailable = pop.get("predeclared_unevaluable_tasks", {})
    for r in episodes.values():
        statuses[r["status"]] += 1
        counts = action_counts(r)
        if counts is not None:
            for axis, number in counts.items():
                operations[axis].append(number)
        if str(r["task_id"]) not in unavailable:
            groups[r["dataset"], r["native_group"]].append(r)
        for k in (
            "reader_input_tokens",
            "reader_output_tokens",
            "reader_cached_tokens",
            "reader_material_tokens",
            "controller_wall_ms",
            "controller_gpu_ms",
            "pool_and_bm25_wall_ms",
            "navigation_and_admission_wall_ms",
            "preflight_wall_ms",
            "read_operation_wall_ms",
            "reader_client_wall_ms",
            "episode_live_readout_ms",
            "encoder_input_tokens",
            "encoder_forwards",
        ):
            v = r["costs"].get(k)
            if type(v) in (int, float):
                costs[k].append(v)
    by_source = {}
    for source in SOURCES:
        scores = []
        unknown = 0
        for (s, _), members in groups.items():
            if s != source:
                continue
            grades = [r["grade"]["native_metrics"] for r in members if "grade" in r]
            if source == MUSIQUE:
                if len(members) != 2:
                    raise ValueError("Incomplete MuSiQue pair")
                if len(grades) == 2:
                    scores.append(musique_pair(grades)[QUALITY_AXES[s]])
                else:
                    unknown += 1
            else:
                scores.extend(v[QUALITY_AXES[s]] for v in grades)
                unknown += len(members) - len(grades)
        total = len(scores) + unknown
        if total == 0:
            raise ValueError("A macro comparison needs all three sources")
        by_source[source] = dict(
            observed=len(scores),
            unknown=unknown,
            mean=fmean(scores) if scores else None,
            full_range=[sum(scores) / total, (sum(scores) + unknown) / total],
        )
    times = (
        [t + load_per_attempt for t in costs["episode_live_readout_ms"]]
        if load_per_attempt is not None
        else []
    )
    return dict(
        arm=arm,
        cohort=pop.get("v13_role", pop["role"]),
        **(
            {"annotation_diagnostics": annotation_diagnostics(groups)}
            if arm.get("policy") == "G"
            and all("annotation_coverage" in r for r in episodes.values())
            else {}
        ),
        registered_tasks=len(episodes),
        registered_groups=len({(t["dataset"], t["native_group"]) for t in pop["tasks"]}),
        material_budget=pop["material_budget"],
        native=by_source,
        macro_range_points=[
            100 * fmean(d["full_range"][k] for d in by_source.values()) for k in (0, 1)
        ],
        status=dict(statuses),
        predeclared_unscorable=len(unavailable),
        action_counts={k: measured(v) for k, v in operations.items()},
        live_readout_plus_load_ms=measured(times),
        resources={k: measured(v) for k, v in costs.items()},
    )


def run_accounting(path, episodes):
    windows, partial_log = window_records(path / "windows.jsonl")
    billing, _ = readout_charge_evidence(windows, episodes)
    calls = billing["settled_new_requests"]
    loads = [w.get("policy_load_ms_this_invocation") for w in windows]
    load_known = sum(v for v in loads if v is not None)
    load_complete = (
        all(v is not None for v in loads)
        and not partial_log
        and not billing["packet_only_new_requests"]
    )
    load_ms = load_known if load_complete else None
    load_per_attempt = (
        load_ms / calls
        if calls and load_ms is not None and not billing["unknown_charge_records"]
        else None
    )
    return dict(
        actual_reader_calls=calls,
        reader_charge_coverage=dict(billing),
        reader_charge_lower_bound_only=bool(billing["unknown_charge_records"] or partial_log),
        bounded_window_ledger_coverage_complete=not bool(
            billing["window_charges_without_bounded_slots"]
        ),
        known_policy_load_ms=load_known,
        policy_load_complete=load_complete,
        policy_load_ms=load_ms,
        policy_load_ms_per_attempt=load_per_attempt,
        vllm_running_seconds=measured(
            [
                w["reader_engine"]["vllm_running_seconds"]
                for w in windows
                if w.get("reader_engine", {}).get("matched_requests", 0)
            ]
        ),
        vllm_matched_requests=sum(
            w.get("reader_engine", {}).get("matched_requests", 0) for w in windows
        ),
        vllm_components={
            axis: {
                "known_total": sum(v["vllm_" + axis] for v in observed),
                "matched_requests": sum(v["matched_requests"] for v in observed),
            }
            for axis in (*FINISHED_HISTOGRAMS.values(), "cached_prompt_tokens")
            if (
                observed := [
                    w["reader_engine"]
                    for w in windows
                    if w.get("reader_engine", {}).get("matched_requests", 0)
                    and w["reader_engine"].get("vllm_" + axis) is not None
                ]
            )
        },
        server_gpu_time=None,
        charged_currency=None,
    )


def summarize_run(path):
    if json.loads((path / "run.json").read_text())["status"] != "COMPLETED":
        raise ValueError(f"Evaluation still open at {path}")
    protocol, episodes = input_result(path)
    pop = protocol["population"]
    if len(pop["tasks"]) != len(episodes):
        raise ValueError(f"Incomplete evaluation packets at {path}")
    billing = run_accounting(path, episodes)
    results = packet_measurements(
        protocol["arm"], pop, episodes, billing["policy_load_ms_per_attempt"]
    )
    return dict(path=str(path.resolve()), **results, **billing)


def summarize_dev_subset(path, roster, arm, *, expected_comparison=None):
    """Select entire groups from an already paid natural DEV run of this frozen policy."""
    if json.loads((path / "run.json").read_text())["status"] != "COMPLETED":
        raise ValueError("Reference readout is incomplete")
    protocol, packets = input_result(path)
    parent = protocol["population"]
    if (
        protocol.get("readout_schedule") != "inline"
        or (expected_comparison is not None and protocol["comparison"] != expected_comparison)
        or {k: v for k, v in protocol["arm"].items() if k != "name"}
        != {k: v for k, v in arm.items() if k != "name"}
    ):
        raise ValueError("Reference readout differs from the bound policy or Reader")
    _, selected = select_dev_records(protocol, packets, roster)
    accounting = run_accounting(path, packets)
    results = packet_measurements(arm, roster, selected, accounting["policy_load_ms_per_attempt"])
    return dict(
        kind="existing_dev_native_group_subset",
        source_run=str(path.resolve()),
        source_tasks=len(parent["tasks"]),
        source_settled_calls=accounting["actual_reader_calls"],
        source_policy_load_ms_per_attempt=accounting["policy_load_ms_per_attempt"],
        new_reader_calls=0,
        task_ids=list(selected),
        **results,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--latency-baseline", type=Path, help="Reference run for paired task latency")
    p.add_argument("--dev-roster", type=Path, help="Whole DEV groups for the latency comparison")
    args = p.parse_args()
    if args.dev_roster and not args.latency_baseline:
        p.error("--dev-roster requires --latency-baseline")
    if args.latency_baseline:
        offsets = {
            path: summarize_run(path)["policy_load_ms_per_attempt"]
            for path in [*args.runs, args.latency_baseline]
        }
        report = paired_inline_latency(
            args.runs, args.latency_baseline, repeats=5000, seed=20261125,
            policy_load_ms_per_task=offsets,
            dev_roster=json.loads(args.dev_roster.read_text()) if args.dev_roster else None,
        )
        report.update(
            candidate_runs=[str(path) for path in args.runs],
            baseline_run=str(args.latency_baseline),
            dev_roster=str(args.dev_roster) if args.dev_roster else None,
        )
    else:
        report = [summarize_run(path) for path in args.runs]
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
