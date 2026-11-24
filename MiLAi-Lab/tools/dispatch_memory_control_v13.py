"""Interleave registered V13 comparators on identical bounded slices of the protected roster."""

from __future__ import annotations

import fcntl
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from milai_lab.datasets.memory_control_protocols import DELTA_NAVIGATION
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.scorers.memory_control_episode_metrics import percentiles
from run_memory_control_v13_evaluation import (
    append_window,
    durable_json,
    evaluate_window,
    reconcile_window,
    recorded_windows,
)


def order_contract(arms, width, seed):
    if width < 1:
        raise ValueError("Positive number of registered tasks per window required")
    names = [a["name"] for a in arms]
    if len(names) < 2 or len(names) != len(set(names)):
        raise ValueError("Distinct comparison arms required")
    random.Random(seed).shuffle(names)  # noqa: S311 -- frozen experimental order
    return {
        "protocol": "native_task_windows_balanced_order_v1",
        "window_tasks": width,
        "base_arms": names,
        "order_seed": seed,
    }


def schedule(contract, n):
    """Balanced Latin-square rows; reverse the next square for an odd number of arms."""
    base = contract["base_arms"]
    if contract["protocol"] != "native_task_windows_balanced_order_v1":
        raise ValueError("Unknown confirmation order")
    k = len(base)
    sequence = []
    first = [0] + [(i + 1) // 2 if i % 2 else k - i // 2 for i in range(1, k)]
    width = contract["window_tasks"]
    for block, start in enumerate(range(0, n, width)):
        names = [base[(j + block) % k] for j in first]
        if k % 2 and (block // k) % 2:
            names.reverse()
        for position, name in enumerate(names):
            sequence.append(
                {
                    "slot": len(sequence),
                    "block": block,
                    "position": position,
                    "arm": name,
                    "span": [start, min(start + width, n)],
                }
            )
    return sequence


def measured_overhead(runs, reg):
    """Keep measured scheduler, model setup and native times in their original scopes."""
    by_arm = {}
    interrupted_slots = set()
    for name, directory in reg["run_directories"].items():
        rows = recorded_windows(runs / directory / "windows.jsonl")
        incomplete_costs = [
            r
            for r in rows
            if r.get("recovered_from_packets")
            or r.get("wrapper_settlement_recovered")
            or r.get("finished_ns") is None
        ]
        interrupted_slots.update(r["dispatch_slot"] for r in incomplete_costs)
        info = {
            "invocations": len(rows),
            "interruptions_with_incomplete_wrapper_timing": len(incomplete_costs),
        }
        for key in (
            "policy_load_ms_this_invocation",
            "phase_wait_ms",
            "wall_seconds",
            "cpu_seconds",
        ):
            values = [r[key] for r in rows if type(r.get(key)) in (int, float)]
            info[key] = {
                "known_sum": sum(values),
                "observed": len(values),
                "unknown": len(rows) - len(values),
            }
        by_arm[name] = info
    events = recorded_windows(runs / "dispatch-windows.jsonl")
    by_block = defaultdict(list)
    driver = defaultdict(list)
    positions = defaultdict(Counter)
    missing = Counter()
    for r in events:
        by_block[r["block"]].append(r)
        positions[r["arm"]][r["position"]] += 1
        if r["recovered_cursor"] or r["slot"] in interrupted_slots:
            missing[r["arm"]] += 1
        else:
            driver[r["arm"]].append(r["current_dispatcher_elapsed_ms"])
    intervals = []
    for rows in by_block.values():
        if (
            len(rows) == len(by_arm)
            and not any(r["slot"] in interrupted_slots for r in rows)
            and all(r["native_started_ns"] and r["native_finished_ns"] for r in rows)
        ):
            intervals.append(
                (
                    max(r["native_finished_ns"] for r in rows)
                    - min(r["native_started_ns"] for r in rows)
                )
                / 1e6
            )
    for name, info in by_arm.items():
        info["driver_slot_ms"] = {
            "known_sum": sum(driver[name]),
            "observed": len(driver[name]),
            "unknown_precrash": missing[name],
        }
        info["completed_positions"] = dict(positions[name])
    setups = recorded_windows(runs / "dispatch-setup.jsonl")
    return {
        "by_arm": by_arm,
        "dataset_setup_invocations": len(setups),
        "dataset_setup_ms": sum(r["dataset_setup_ms"] for r in setups),
        "observed_complete_block_spans": len(intervals),
        "block_wall_span_ms_p50": percentiles(intervals, 0.5) if intervals else None,
        "block_wall_span_ms_p95": percentiles(intervals, 0.95) if intervals else None,
        "scope": (
            "Driver slot wall includes native execution and packaging. "
            "Phase wait, policy load and native wall overlap."
        ),
    }


def dispatch(args, *, evaluator=evaluate_window, dataset_factory=MemoryControlDataset):
    pop_path = args.registration / "population.json"
    pop = json.loads(pop_path.read_text())
    reg = json.loads((args.registration / "registration.json").read_text())
    order = json.loads((args.registration / "dispatch-schedule.json").read_text())
    contract = pop.get("v13_dispatch")
    if (
        pop.get("v13_role") != "confirm_fresh"
        or not contract
        or contract != reg.get("dispatch")
        or order != schedule(contract, len(pop["tasks"]))
    ):
        raise ValueError("The frozen fresh roster and dispatch schedule disagree")
    arms = {a["name"]: a for a in pop["arms"]}
    if set(arms) != set(contract["base_arms"]) or set(arms) != set(reg["run_directories"]):
        raise ValueError("Interleaved arm set differs from the registered comparison")
    data = Path(pop["dataset_path"])
    runs = args.runs
    runs.mkdir(parents=True, exist_ok=True)
    protocol = {
        "population": pop,
        "registered_order": order,
        "max_reader_calls": reg["max_reader_calls"],
    }
    with (runs / ".dispatch-owner.lock").open("a") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = runs / "dispatch-protocol.json"
        if frozen.is_file():
            if json.loads(frozen.read_text()) != protocol:
                raise ValueError("This run directory already has a different dispatch plan")
        else:
            durable_json(frozen, protocol)
        events = runs / "dispatch-windows.jsonl"
        completed = {}
        for record in recorded_windows(events, repair=True):
            slot = record["slot"]
            if (
                slot in completed
                or not 0 <= slot < len(order)
                or any(record[k] != v for k, v in order[slot].items())
            ):
                raise ValueError("Invalid or duplicated dispatch position")
            completed[slot] = record
        if set(completed) != set(range(len(completed))):
            raise ValueError("A prior dispatch position is missing")
        # Window receipts outlive the shared cursor and can settle a lost final append.
        closed = {}
        charged = unknown = 0
        for name, dirname in reg["run_directories"].items():
            out = runs / dirname
            if not out.is_dir():
                continue
            with (out / ".v13-window.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                windows = reconcile_window(out, pop)
            for row in windows:
                slot = row.get("dispatch_slot")
                if (
                    type(slot) is not int
                    or not 0 <= slot < len(order)
                    or order[slot]["arm"] != name
                    or row.get("v13_task_span") != order[slot]["span"]
                ):
                    raise ValueError("Unregistered evaluation window in the fresh run directory")
                charged += row["reader_requests_this_invocation"]
                unknown += row.get("reader_charge_unknown_records", 0)
                if row.get("window_complete"):
                    if slot in closed:
                        raise ValueError("A registered window was finalized twice")
                    closed[slot] = row
        if not set(completed) <= closed.keys():
            raise ValueError("Dispatch progress lacks its native completed window")
        if any(i > len(completed) for i in closed if i not in completed):
            raise ValueError("Prior work occurred outside the next registered slot")
        start = time.perf_counter()
        ds = None
        advanced = 0
        for entry in order[len(completed) :]:
            if args.limit_windows is not None and advanced >= args.limit_windows:
                break
            slot = entry["slot"]
            wrapper_start = time.perf_counter()
            if slot in closed:
                receipt = closed[slot]
                recovered = True
            else:
                if ds is None:
                    tick = time.perf_counter()
                    setup_start = time.time_ns()
                    ds = dataset_factory(
                        data, observation_protocol=DELTA_NAVIGATION, numeric_observation=True
                    )
                    append_window(
                        runs / "dispatch-setup.jsonl",
                        {
                            "started_ns": setup_start,
                            "dataset_setup_ms": (time.perf_counter() - tick) * 1000,
                            "next_slot": slot,
                        },
                    )
                remaining = reg["max_reader_calls"] - charged - unknown
                if remaining < 0:
                    raise ValueError("Previous known or unconfirmed reservations exceed the cap")
                receipt = evaluator(
                    data,
                    pop_path,
                    arms[entry["arm"]],
                    runs / reg["run_directories"][entry["arm"]],
                    device=args.device,
                    window=contract["window_tasks"],
                    dataset=ds,
                    task_span=tuple(entry["span"]),
                    dispatch_slot=slot,
                    max_paid_requests=remaining,
                )
                recovered = bool(receipt.get("cached_window"))
                if not recovered:
                    charged += receipt["reader_requests_this_invocation"]
                    unknown += receipt.get("reader_charge_unknown_records", 0)
                if not receipt.get("window_complete"):
                    raise RuntimeError(
                        "Fixed window incomplete; its native packets remain resumable"
                    )
                if charged + unknown > reg["max_reader_calls"]:
                    raise ValueError("Window exceeds registered total Reader capacity")
            event = {
                **entry,
                "invocation_id": receipt["invocation_id"],
                "recovered_cursor": recovered,
                "known_cumulative_calls": charged,
                "uncertain_reservations": unknown,
                "current_dispatcher_elapsed_ms": (time.perf_counter() - wrapper_start) * 1000,
                "native_started_ns": receipt.get("started_ns"),
                "native_finished_ns": receipt.get("finished_ns"),
            }
            append_window(events, event)
            completed[slot] = event
            advanced += 1
        result = {
            "status": "COMPLETED" if len(completed) == len(order) else "PARTIAL",
            "completed_slots": len(completed),
            "registered_slots": len(order),
            "known_reader_calls": charged,
            "unknown_packet_charges": unknown,
            "registered_cap": reg["max_reader_calls"],
            "windows_advanced": advanced,
            "invocation_wall_seconds": time.perf_counter() - start,
        }
        result["overheads"] = measured_overhead(runs, reg)
        durable_json(runs / "dispatch-summary.json", result)
        return result
