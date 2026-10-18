"""Drive authored arriving events through the normal Host; policies live in methods/."""
from __future__ import annotations

import argparse
import copy
import json
import os
import site
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def host_input(step: dict[str, Any], *, bank: str) -> dict[str, Any]:
    """Project caller input explicitly; offline labels and future steps never pass through."""
    sources = copy.deepcopy(step["incoming_sources"])
    for source in sources:
        source["session_id"] = "source-stream"
    return {"bank": bank, "owner": "development-user",
            "session": "session-1" if step["session"].endswith("-reopened") else "session-0",
            "message_id": step["id"], "content": step["content"],
            "occurred_at": step["occurred_at"], "query_time": step["query_time"],
            "calendar_context": "Asia/Shanghai", "incoming_sources": sources}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("histories", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--policies", nargs="+", choices=("fixed", "rules", "laya", "generative"),
                        default=["fixed", "rules", "laya", "generative"])
    parser.add_argument("--history", action="append", help="Explicit development subset")
    parser.add_argument("--host-site-packages", type=Path,
                        help="Reuse the existing Host environment's optional SDK packages")
    args = parser.parse_args()
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    from milai_lab.runners.functional import message, prepare

    args.output.mkdir(parents=True, exist_ok=False)
    fixture = read_json(args.histories)
    histories = [h for h in fixture["histories"] if not args.history or h["id"] in args.history]
    config = read_json(args.config)
    budget_path = Path(config["entrypoints"]["functional"]["budget_path"])
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "histories": [h["id"] for h in histories],
        "policies": args.policies, "completed": [], "automatic_retry": False,
        "planned_messages": sum(len(h["steps"]) for h in histories) * len(args.policies),
        "planned_tasks": sum(h["task_count"] for h in histories) * len(args.policies),
        "started_epoch": time.time()}
    write_json(args.output / "driver.json", run)
    write_json(args.output / "budget-before.json", read_json(budget_path))
    write_json(args.output / "fixture.json", fixture)
    started = time.perf_counter()
    try:
        for policy in args.policies:
            recipe = copy.deepcopy(config)
            settings = recipe["entrypoints"]["functional"]
            settings["memory_control"]["policy"] = policy
            settings["config_version"] += "-" + policy
            config_path = args.output / f"{policy}-config.json"
            write_json(config_path, recipe)
            root = args.output / policy
            prepare(root, config_path, source_version=args.source_version)
        for number, history in enumerate(histories):
            for policy in args.policies:
                root = args.output / policy
                for step in history["steps"]:
                    run["active"] = {"policy": policy, "history": history["id"],
                                     "step": step["id"]}
                    write_json(args.output / "driver.json", run)
                    call_started = time.perf_counter()
                    result = message(root, **host_input(step, bank=f"bank-{number}"))
                    row = {**run["active"], "kind": step["kind"], "status": result["status"],
                        "error": result.get("error"), "final_answer": result.get("final_answer"),
                        "wall_seconds": time.perf_counter() - call_started}
                    run["completed"].append(row)
                    write_json(args.output / "driver.json", run)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    if result["status"] != "COMPLETED":
                        raise RuntimeError("First Host failure retained; inspect before a new run")
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run.update(wall_seconds=time.perf_counter() - started, finished_epoch=time.time())
        write_json(args.output / "budget-after.json", read_json(budget_path))
        write_json(args.output / "driver.json", run)


if __name__ == "__main__":
    main()
