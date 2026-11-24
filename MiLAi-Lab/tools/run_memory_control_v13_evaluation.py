"""Register V13 development cohorts and run a frozen policy through the native Reader."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from milai_lab.datasets.memory_control_episode_archive import compact_scored_episode_packets
from milai_lab.datasets.memory_control_protocols import DELTA_NAVIGATION
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import (
    allocate_native_groups,
    episode_population,
    evaluate_episodes,
)
from milai_lab.runners.v13_phase import phase_directory, phase_unit
from milai_lab.scorers.memory_control_episode_metrics import summarize


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    pending.replace(path)


def register(data, tune, output):
    parent = json.loads(tune.read_text())
    if parent["role"] != "dev" or parent["material_budget"] != 2048:
        raise ValueError("Expected original 2,048-token development roster")
    tune_groups = {(t["dataset"], t["native_group"]) for t in parent["tasks"]}
    calibration = episode_population(
        data, role="dev", target_tasks=96, seed=1311, allowed_arms=[], excluded_groups=tune_groups
    )
    if calibration["dataset_run_id"] != parent["dataset_run_id"]:
        raise ValueError("Development population refers to a different release")
    # Older DEV files predate the explicit invalid-MCQ and terminal-failure fields.
    with closing(sqlite3.connect(data.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        invalid = {
            i
            for (i,) in db.execute(
                "SELECT DISTINCT task_id FROM anomalies WHERE dataset='personamem_v2' "
                "AND reason IN ('null_incorrect_option','offline_field_incorrect_answers')"
            )
        }
    parent["predeclared_unevaluable_tasks"] = {
        str(t["task_id"]): "invalid_options" for t in parent["tasks"] if t["task_id"] in invalid
    }
    parent["terminal_quality_failures"] = "score_zero_keep_unknown_resource"
    sizes = defaultdict(Counter)
    for t in parent["tasks"]:
        sizes[t["dataset"]][t["native_group"]] += 1
    selected = set(allocate_native_groups(sizes, target_tasks=150, seed=1311))
    curve_tasks = [t for t in parent["tasks"] if (t["dataset"], t["native_group"]) in selected]
    curve_ids = {str(t["task_id"]) for t in curve_tasks}
    curve = dict(
        parent,
        tasks=curve_tasks,
        target_tasks=150,
        task_counts=dict(Counter(t["dataset"] for t in curve_tasks)),
        predeclared_unevaluable_tasks={
            k: v for k, v in parent["predeclared_unevaluable_tasks"].items() if k in curve_ids
        },
    )
    for name, cohort in (("calibration", calibration), ("tune", parent), ("curve", curve)):
        for budget in (512, 1024, 2048):
            path = output / f"{name}-{budget}.json"
            payload = dict(cohort, material_budget=budget, v13_role=name)
            if path.exists() and json.loads(path.read_text()) != payload:
                raise ValueError(f"Existing roster differs: {path}")
            save(path, payload)


def evaluate(args):
    arm = json.loads(args.arm.read_text())
    if (
        arm.get("environment") != "qrag_milai_v13"
        or arm.get("observation_protocol") != DELTA_NAVIGATION
    ):
        raise ValueError("Expected V13 common environment and observation")
    if args.window < 1:
        raise ValueError("Window must be positive")
    protocol_path = args.output / "protocol.json"
    if (args.output / "summary.json").is_file() and protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text())
        if (
            protocol["arm"] != arm
            or protocol["population"] != json.loads(args.population.read_text())
            or protocol["readout_schedule"] != "inline"
            or Path(protocol["population"]["dataset_path"]).resolve()
            != (args.data / "memory_control.sqlite3" if args.data.is_dir() else args.data).resolve()
        ):
            raise ValueError("Completed output belongs to a different experiment")
        if json.loads((args.output / "run.json").read_text())["status"] == "COMPLETED":
            return
    ds = MemoryControlDataset(
        args.data, observation_protocol=DELTA_NAVIGATION, numeric_observation=True
    )
    args.output.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            unit = "qr" if arm["policy"] == "qrag_milai" else "evaluate"
            with phase_unit(phase_directory(args.output), unit):
                receipt = evaluate_episodes(
                    args.data,
                    args.population,
                    arm,
                    args.output,
                    device=args.device,
                    max_reader_requests=args.window,
                    inline_readout=True,
                    prepared_dataset=ds,
                )
        except HttpOwnershipError as exc:
            if str(exc) != "HTTP_OWNER_BUSY":
                raise
            time.sleep(2)
            continue
        with (args.output / "windows.jsonl").open("a") as f:
            f.write(json.dumps(receipt, allow_nan=False) + "\n")
        if receipt["status"] == "COMPLETED":
            save(args.output / "summary.json", summarize(args.output))
            compact_scored_episode_packets(args.output)
            return
        compact_scored_episode_packets(args.output)
        if not receipt["reader_attempts_this_invocation"]:
            raise RuntimeError("No further Reader episode dispatched. Inspect run.json")
        time.sleep(0.5)


def transfer(args):
    """Evaluate a frozen readout on smaller material budgets and fixed legal levels."""
    from copy import copy

    arm = json.loads(args.arm.read_text())
    for budget, level in (
        (2048, "learned"),
        (2048, "R2"),
        (2048, "R3_only"),
        (1024, "learned"),
        (512, "learned"),
    ):
        peer = copy(args)
        peer.population = args.rosters / f"curve-{budget}.json"
        peer.output = args.output / f"{budget}-{level}"
        peer.arm = peer.output / "arm.json"
        policy = dict(arm, precision=level)
        if peer.arm.exists() and json.loads(peer.arm.read_text()) != policy:
            raise ValueError("Transfer arm differs from the frozen readout")
        save(peer.arm, policy)
        evaluate(peer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--tune", required=True, type=Path)
    ev = sub.add_parser("evaluate")
    tr = sub.add_parser("transfer")
    tr.add_argument("--rosters", type=Path, required=True)
    for p in (reg, ev, tr):
        p.add_argument("--data", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
    ev.add_argument("--population", type=Path, required=True)
    for p in (ev, tr):
        p.add_argument("--arm", type=Path, required=True)
        p.add_argument("--device", default="cpu")
        p.add_argument("--window", type=int, default=16)
    args = parser.parse_args()
    if args.command == "register":
        register(args.data, args.tune, args.output)
    elif args.command == "transfer":
        transfer(args)
    else:
        evaluate(args)
