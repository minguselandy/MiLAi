"""Execute every captured actual request under declared policies from the same before.

The JSON recipe is a list of {"name": ..., "policy": {...}} arms. All captures,
including original failures and zero-decision requests, stay in the cohort.
This runner measures tool execution only; it does not score downstream answers.
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
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "cohort.json", {
        "calls": [{"capture": str(path), "bank": call["bank"], "call_id": call["call_id"],
                   "original_status": call["status"],
                   "host_request_generated": call["host_request_generated"]}
                  for path, call in calls],
        "policies": policies})
    driver: dict[str, Any] = {
        "status": "RUNNING", "pid": os.getpid(), "source_version": args.source_version,
        "planned_positions": len(calls) * len(policies), "completed": [], "automatic_retry": False,
        "scope": "Tool evidence/cost comparison; fixed Host downstream effects remain separate.",
    }
    write_json(args.output / "driver.json", driver)
    models: dict[tuple[Any, ...], Any] = {}
    cases = []
    try:
        for arm_index, arm in enumerate(policies):
            for index, (captured, _) in enumerate(calls):
                case = args.output / f"arm-{arm_index:02d}" / f"call-{index:05d}"
                driver["active"] = {"arm": arm["name"], "index": index, "path": str(case)}
                write_json(args.output / "driver.json", driver)
                cases.append(case)
                result = replay_call(captured, case, arm["policy"],
                                     source_version=args.source_version, models=models)
                row = {**driver["active"], "status": result["status"],
                       "error": result.get("error"),
                       "before_equal": result.get("frozen_initial_observation_and_actions_equal")}
                driver["completed"].append(row)
                write_json(args.output / "driver.json", driver)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if result["status"] != "COMPLETED":
                    raise RuntimeError("First failed comparison retained; no automatic retry")
        driver["status"] = "COMPLETED"
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        measured = [read_json(case / "replay.json") for case in cases
                    if (case / "replay.json").exists()]
        elapsed_cpu = time.process_time() - cpu
        driver.update(wall_seconds=time.perf_counter() - started,
            cpu_seconds_nested=elapsed_cpu,
            orchestration_cpu_seconds_not_yet_recorded=elapsed_cpu - sum(
                row.get("cpu_seconds_nested", 0) for row in measured),
            ledger_recorded=False,
            accounting="Per-case replay.json separates ledger CPU and pending CPU; "
                       "outer orchestration CPU is additional, driver total is nested.")
        write_json(args.output / "driver.json", driver)


if __name__ == "__main__":
    main()
