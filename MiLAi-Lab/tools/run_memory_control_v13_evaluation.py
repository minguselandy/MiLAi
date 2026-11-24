"""Register V13 development cohorts and run a frozen policy through the native Reader."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from contextlib import closing
from itertools import pairwise
from pathlib import Path

from milai_lab.datasets.memory_control_episode_archive import (
    compact_scored_episode_packets,
    read_episode_packet,
)
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


def durable_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as handle:
        json.dump(value, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def recorded_windows(path, *, repair=False):
    if not path.is_file():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        pos = data.rfind(b"\n") + 1
        if repair:
            lost = path.with_name(f"interrupted-window-{time.time_ns()}.tail")
            lost.write_bytes(data[pos:])
            with path.open("rb+") as handle:
                handle.truncate(pos)
                os.fsync(handle.fileno())
        data = data[:pos]
    return [json.loads(line) for line in data.splitlines() if line]


def append_window(path, receipt):
    with path.open("a") as handle:
        handle.write(json.dumps(receipt, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def recovered_window(marker, population, output):
    """Settle exactly the local generation reservations present in this invocation's packets."""
    tasks = population["tasks"]
    if marker.get("v13_task_span"):
        tasks = tasks[slice(*marker["v13_task_span"])]
    intervals = []
    unknown = attempts = 0
    for item in tasks:
        packet = read_episode_packet(output / "episodes" / f"{item['task_id']}.json")
        charge = (packet or {}).get("reader_charge", {})
        if charge.get("invocation_id") != marker["invocation_id"]:
            continue
        before, after = charge["ledger_before"], charge.get("ledger_after")
        attempts += int(packet["costs"].get("reader_request_attempted") is True)
        if type(before) is not int or type(after) is not int:
            unknown += 1
        elif before < 0 or after < before:
            raise ValueError("Invalid persisted native charge interval")
        elif after > before:
            intervals.append([before, after])
    intervals.sort()
    if any(left[1] > right[0] for left, right in pairwise(intervals)):
        raise ValueError("Overlapping recovered packet reservations")
    return {
        **marker,
        "status": "PARTIAL",
        "window_complete": False,
        "reader_requests_this_invocation": sum(b - a for a, b in intervals),
        "reader_attempts_this_invocation": attempts,
        "reader_charge_unknown_records": unknown,
        "ledger_intervals": intervals,
        "recovered_from_packets": True,
        "policy_load_ms_this_invocation": None,
        "reader_scope_wall_seconds": None,
        "cpu_seconds": None,
        "wall_seconds": None,
        "reader_engine": {},
    }


def reconcile_window(output, population):
    log = output / "windows.jsonl"
    rows = recorded_windows(log, repair=True)
    pending = output / ".window-inflight.json"
    if pending.exists():
        marker = json.loads(pending.read_text())
        if not any(r.get("invocation_id") == marker["invocation_id"] for r in rows):
            final = output / "run.json"
            settled = json.loads(final.read_text()) if final.exists() else {}
            if settled.get("invocation_id") == marker["invocation_id"]:
                receipt = {**marker, **settled, "wrapper_settlement_recovered": True}
            else:
                receipt = recovered_window(marker, population, output)
            append_window(log, receipt)
            rows.append(receipt)
        pending.unlink()
    return rows


def evaluate_window(
    data,
    population_path,
    arm,
    output,
    *,
    device,
    window,
    dataset=None,
    task_span=None,
    dispatch_slot=None,
    max_paid_requests=None,
):
    """Execute at most one admitted native window; never dispatch outside a supplied task span."""
    if (
        arm.get("environment") != "qrag_milai_v13"
        or arm.get("observation_protocol") != DELTA_NAVIGATION
        or window < 1
    ):
        raise ValueError("Expected a positive V13 common-environment window")
    pop = json.loads(population_path.read_text())
    if pop.get("v13_dispatch") and dispatch_slot is None:
        raise ValueError("Use the registered interleaved dispatcher for this confirmation")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".v13-window.lock").open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protocol_path = output / "protocol.json"
        if protocol_path.exists():
            proto = json.loads(protocol_path.read_text())
            if (
                proto["arm"] != arm
                or proto["population"] != pop
                or proto["readout_schedule"] != "inline"
                or Path(pop["dataset_path"]).resolve()
                != (data / "memory_control.sqlite3" if data.is_dir() else data).resolve()
            ):
                raise ValueError("Saved output belongs to a different evaluation")
        rows = reconcile_window(output, pop)
        closed = next(
            (
                r
                for r in reversed(rows)
                if dispatch_slot is not None
                and r.get("dispatch_slot") == dispatch_slot
                and r.get("window_complete")
            ),
            None,
        )
        finished = output / "run.json"
        done = json.loads(finished.read_text()) if finished.is_file() else {}
        if closed is not None or done.get("status") == "COMPLETED":
            if done.get("status") == "COMPLETED" and not (output / "summary.json").is_file():
                save(output / "summary.json", summarize(output))
                compact_scored_episode_packets(output)
            prior = closed or done
            return {
                **prior,
                "cached_window": True,
                "window_complete": True,
                "prior_settled_requests": prior["reader_requests_this_invocation"],
                "reader_requests_this_invocation": 0,
                "reader_attempts_this_invocation": 0,
                "policy_load_ms_this_invocation": 0.0,
            }
        setup = time.perf_counter()
        ds = dataset or MemoryControlDataset(
            data, observation_protocol=DELTA_NAVIGATION, numeric_observation=True
        )
        setup_ms = (time.perf_counter() - setup) * 1000 if dataset is None else 0.0
        waiting = time.perf_counter()
        while True:
            try:
                with phase_unit(
                    phase_directory(output),
                    "qr" if task_span is None and arm["policy"] == "qrag_milai" else "evaluate",
                ):
                    marker = {
                        "invocation_id": uuid.uuid4().hex,
                        "dispatch_slot": dispatch_slot,
                        "v13_task_span": list(task_span) if task_span is not None else None,
                        "started_ns": time.time_ns(),
                        "dataset_setup_ms": setup_ms,
                        "phase_wait_ms": (time.perf_counter() - waiting) * 1000,
                    }
                    durable_json(output / ".window-inflight.json", marker)
                    receipt = evaluate_episodes(
                        data,
                        population_path,
                        arm,
                        output,
                        device=device,
                        max_reader_requests=window,
                        inline_readout=True,
                        prepared_dataset=ds,
                        task_span=task_span,
                        invocation_id=marker["invocation_id"],
                        max_paid_requests=max_paid_requests,
                    )
                break
            except HttpOwnershipError as exc:
                if str(exc) != "HTTP_OWNER_BUSY":
                    raise
                # No Reader lease was acquired. Preserve wait duration, not a paid invocation.
                (output / ".window-inflight.json").unlink(missing_ok=True)
                time.sleep(2)
        receipt = {**marker, **receipt, "finished_ns": time.time_ns()}
        append_window(output / "windows.jsonl", receipt)
        (output / ".window-inflight.json").unlink(missing_ok=True)
        if receipt["status"] == "COMPLETED":
            save(output / "summary.json", summarize(output))
        compact_scored_episode_packets(output)
        return receipt


def evaluate(args):
    arm = json.loads(args.arm.read_text())
    final = args.output / "run.json"
    if final.is_file() and json.loads(final.read_text()).get("status") == "COMPLETED":
        evaluate_window(
            args.data, args.population, arm, args.output, device=args.device, window=args.window
        )
        return
    ds = MemoryControlDataset(
        args.data, observation_protocol=DELTA_NAVIGATION, numeric_observation=True
    )
    while True:
        receipt = evaluate_window(
            args.data,
            args.population,
            arm,
            args.output,
            device=args.device,
            window=args.window,
            dataset=ds,
        )
        if receipt["status"] == "COMPLETED":
            return
        if not receipt["reader_attempts_this_invocation"]:
            raise RuntimeError("No further Reader episode dispatched. Inspect run.json")
        time.sleep(0.5)


def transfer(args):
    """Evaluate a frozen readout on smaller material budgets and fixed legal levels."""
    from copy import copy

    arm = json.loads(args.arm.read_text())
    conditions = [(2048, "frozen", arm)]
    if (
        arm["policy"] in {"pretrained_checkpoint", "qrag_milai"}
        and arm.get("precision", "learned") == "learned"
    ):
        conditions.extend((2048, level, dict(arm, precision=level)) for level in ("R2", "R3_only"))
    conditions.extend((budget, "frozen", arm) for budget in (1024, 512))
    results = {}
    for budget, level, policy in conditions:
        peer = copy(args)
        peer.population = args.rosters / f"curve-{budget}.json"
        peer.output = args.output / f"{budget}-{level}"
        peer.arm = peer.output / "arm.json"
        if peer.arm.exists() and json.loads(peer.arm.read_text()) != policy:
            raise ValueError("Transfer arm differs from the frozen readout")
        save(peer.arm, policy)
        if budget == 2048 and level == "frozen" and args.reference_run is not None:
            existing = json.loads((args.reference_run / "protocol.json").read_text())
            if (
                existing["population"] != json.loads(peer.population.read_text())
                or existing["arm"] != arm
                or existing.get("readout_schedule") != "inline"
                or json.loads((args.reference_run / "run.json").read_text())["status"]
                != "COMPLETED"
            ):
                raise ValueError("Reference readout differs from the exact frozen natural DEV arm")
            results[f"{budget}-{level}"] = str(args.reference_run.resolve())
        else:
            evaluate(peer)
            results[f"{budget}-{level}"] = str(peer.output.resolve())
    save(args.output / "readouts.json", results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--tune", required=True, type=Path)
    ev = sub.add_parser("evaluate")
    tr = sub.add_parser("transfer")
    tr.add_argument("--rosters", type=Path, required=True)
    tr.add_argument(
        "--reference-run",
        type=Path,
        help="Already completed identical 2,048-token arm on this curve roster",
    )
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
