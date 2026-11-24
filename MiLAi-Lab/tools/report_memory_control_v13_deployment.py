"""Summarize native quality, observed-resource coverage and measured end-to-end costs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.scorers.memory_control_episode_metrics import (
    QUALITY_AXES,
    SOURCES,
    input_result,
    percentiles,
)
from milai_lab.scorers.memory_control_native import musique_pair


def measured(values):
    if not values:
        return {"n": 0, "total": None, "p50": None, "p95": None}
    return {
        "n": len(values),
        "total": sum(values),
        "p50": percentiles(values, 0.50),
        "p95": percentiles(values, 0.95),
    }


def summarize_run(path):
    closed = json.loads((path / "run.json").read_text())
    if closed["status"] != "COMPLETED":
        raise ValueError(f"Evaluation still open at {path}")
    protocol, episodes = input_result(path)
    pop = protocol["population"]
    if len(pop["tasks"]) != len(episodes):
        raise ValueError(f"Incomplete evaluation packets at {path}")
    groups = defaultdict(list)
    costs = defaultdict(list)
    statuses = Counter()
    unavailable = pop.get("predeclared_unevaluable_tasks", {})
    for r in episodes.values():
        statuses[r["status"]] += 1
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
    windows = [json.loads(line) for line in (path / "windows.jsonl").read_text().splitlines()]
    calls = sum(w["reader_requests_this_invocation"] for w in windows)
    load_ms = sum(w["policy_load_ms_this_invocation"] for w in windows)
    eligible_times = costs["episode_live_readout_ms"]
    load_per_attempt = load_ms / calls if calls else None
    times = [t + load_per_attempt for t in eligible_times] if load_per_attempt is not None else []
    return dict(
        path=str(path.resolve()),
        arm=protocol["arm"],
        cohort=pop.get("v13_role", pop["role"]),
        registered_tasks=len(episodes),
        registered_groups=len({(t["dataset"], t["native_group"]) for t in pop["tasks"]}),
        material_budget=pop["material_budget"],
        native=by_source,
        macro_range_points=[
            100 * fmean(d["full_range"][k] for d in by_source.values()) for k in (0, 1)
        ],
        status=dict(statuses),
        predeclared_unscorable=len(unavailable),
        actual_reader_calls=calls,
        policy_load_ms=load_ms,
        policy_load_ms_per_attempt=load_per_attempt,
        live_readout_plus_load_ms=measured(times),
        resources={k: measured(v) for k, v in costs.items()},
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
        server_gpu_time=None,
        charged_currency=None,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    args.output.write_text(
        json.dumps([summarize_run(path) for path in args.runs], indent=2, allow_nan=False) + "\n"
    )
