"""Execute every captured actual request under declared policies from the same before.

The JSON recipe is a list of {"name": ..., "policy": {...}} arms. An optional
"capture" selects its actual capture directory name. "intervention" supplies an
exact captured first_action and continuation_steps. Unselected captures stay
listed in the cohort; they are not executed or assigned outcome labels.
With --host-readout, substitute each target receipt in the original complete
Host context and request one final answer. Semantic scoring remains separate.
"""
from __future__ import annotations

import argparse
import json
import os
import site
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    started, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("policies", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--host-site-packages", type=Path)
    parser.add_argument("--host-readout", action="store_true",
                        help="One conditional final Host answer using the original post-tool input")
    args = parser.parse_args()
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    from milai_lab.runners.frozen_retrieval import replay_call

    calls = [(path.parent, read_json(path)) for path in args.captures.glob("*/call.json")]
    calls.sort(key=lambda item: item[1]["captured_epoch"])
    policies = read_json(args.policies)
    if not calls or not policies or len({arm["name"] for arm in policies}) != len(policies):
        raise ValueError("Frozen comparison needs a nonempty cohort and uniquely named policies")
    if any(call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"} for _, call in calls):
        raise ValueError("All original captures must be closed, including original failures")
    capture_names = {path.name for path, _ in calls}
    if any(arm["capture"] not in capture_names for arm in policies if "capture" in arm):
        raise ValueError("A declared branch capture is missing from the input cohort")
    jobs = [(arm_index, index) for arm_index, arm in enumerate(policies)
            for index, (captured, _) in enumerate(calls)
            if "capture" not in arm or arm["capture"] == captured.name]
    selected = {index for _, index in jobs}
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cohort.json", {
        "calls": [{"capture": str(path), "bank": call["bank"], "call_id": call["call_id"],
                   "original_status": call["status"],
                   "host_request_generated": call["host_request_generated"]}
                  for path, call in calls],
        "policies": policies,
        "selected_capture_indices": sorted(selected),
        "unselected_capture_indices": sorted(set(range(len(calls))) - selected)})
    driver: dict[str, Any] = {
        "status": "RUNNING", "pid": os.getpid(), "source_version": args.source_version,
        "planned_positions": len(jobs), "completed": [], "automatic_retry": False,
        "host_readout": args.host_readout,
        "scope": "Frozen tool comparison; optional conditional single-receipt Host readout.",
    }
    write_json(args.output / "driver.json", driver)
    models: dict[tuple[Any, ...], Any] = {}
    cases = []
    frames: dict[int, dict[str, Any]] = {}
    try:
        if args.host_readout:
            from milai_lab.runners.frozen_host_readout import prepare_readout, run_readout

            (args.output / "readout-frames").mkdir()
            for index in sorted(selected):
                captured = calls[index][0]
                frames[index] = prepare_readout(captured)
                write_json(args.output / "readout-frames" / f"{index:05d}.json", frames[index])
        for arm_index, index in jobs:
            arm, captured = policies[arm_index], calls[index][0]
            case = args.output / f"arm-{arm_index:02d}" / f"call-{index:05d}"
            driver["active"] = {"arm": arm["name"], "index": index, "path": str(case)}
            write_json(args.output / "driver.json", driver)
            cases.append(case)
            result = replay_call(captured, case, arm["policy"],
                source_version=args.source_version, models=models,
                intervention=arm.get("intervention"))
            row = {**driver["active"], "status": result["status"],
                   "error": result.get("error"),
                   "before_equal": result.get("frozen_initial_observation_and_actions_equal")}
            driver["completed"].append(row)
            write_json(args.output / "driver.json", driver)
            if args.host_readout:
                try:
                    readout = run_readout(captured, case, case / "host-readout",
                                         frames[index], source_version=args.source_version)
                    row["host_readout_status"] = readout["status"]
                    row["host_readout_reason"] = readout.get("reason")
                except BaseException:
                    row["host_readout_status"] = "FAILED"
                    write_json(args.output / "driver.json", driver)
                    raise
                write_json(args.output / "driver.json", driver)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if result["status"] != "COMPLETED":
                raise RuntimeError("First failed comparison retained; no automatic retry")
        driver["status"] = ("COMPLETED_WITH_MISSING_READOUTS" if args.host_readout and any(
            row["host_readout_status"] != "COMPLETED" for row in driver["completed"])
            else "COMPLETED")
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measured = [read_json(case / "replay.json") for case in cases
                    if (case / "replay.json").exists()]
        readouts = [read_json(case / "host-readout/readout.json") for case in cases
                    if (case / "host-readout/readout.json").exists()]
        elapsed_cpu = time.process_time() - cpu
        driver.update(wall_seconds=time.perf_counter() - started,
            cpu_seconds_nested=elapsed_cpu,
            orchestration_cpu_seconds_not_yet_recorded=elapsed_cpu - sum(
                row.get("cpu_seconds_nested", 0) for row in measured) - sum(
                row["cpu_seconds"] for row in readouts),
            ledger_recorded=False,
            accounting="Per-case replay.json separates ledger CPU and pending CPU; "
                       "readout CPU and outer orchestration CPU are additional. "
                       "Driver total is nested; readout HTTP uses the original ledger.")
        write_json(args.output / "driver.json", driver)


if __name__ == "__main__":
    main()
