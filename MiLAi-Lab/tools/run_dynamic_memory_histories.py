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
        source.setdefault("session_id", "source-stream")
    return {"bank": bank, "owner": "development-user",
            "session": "session-1" if step["session"].endswith("-reopened") else "session-0",
            "message_id": step["id"], "content": step["content"],
            "occurred_at": step["occurred_at"], "query_time": step["query_time"],
            "calendar_context": "Asia/Shanghai", "incoming_sources": sources,
            **{key: copy.deepcopy(step[key]) for key in (
                "workflow", "initial_world", "evaluator_control", "message_index") if key in step}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("histories", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--policies", nargs="+", choices=(
        "fixed", "fixed_context", "rules", "laya", "linear", "generative"),
                        default=["fixed", "rules", "laya", "generative"])
    parser.add_argument("--history", action="append", help="Explicit development subset")
    parser.add_argument("--continue-from", type=Path,
                        help="New dispatch record for unexecuted positions after a reviewed exit")
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
    prior = read_json(args.continue_from / "driver.json") if args.continue_from else None
    runtime_root = (Path(prior.get("runtime_root", str(args.continue_from)))
                    if prior else args.output)
    completed = copy.deepcopy(prior["completed"]) if prior else []
    closed = {(r["policy"], r["history"], r["step"]) for r in completed}
    if prior is not None:
        if prior["status"] == "RUNNING":
            raise ValueError("Inspect the live coordinator; do not duplicate a running dispatch")
        if read_json(args.continue_from / "fixture.json") != fixture:
            raise ValueError("Continuation requires the same actual fixture")
        if prior["histories"] != [h["id"] for h in histories] or prior["policies"] != args.policies:
            raise ValueError("Continuation keeps the declared bank and policy allocation")
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "histories": [h["id"] for h in histories],
        "policies": args.policies, "completed": completed, "automatic_retry": False,
        "runtime_root": str(runtime_root), "continuation_of": str(args.continue_from)
        if args.continue_from else None, "inherited_positions": len(completed),
        "coordinator_source": str(Path(__file__).resolve()),
        "planned_messages": sum(len(h["steps"]) for h in histories) * len(args.policies),
        "planned_tasks": sum(h["task_count"] for h in histories) * len(args.policies),
        "started_epoch": time.time()}
    write_json(args.output / "driver.json", run)
    write_json(args.output / "budget-before.json", read_json(budget_path))
    write_json(args.output / "fixture.json", fixture)
    started = time.perf_counter()
    try:
        for policy in args.policies:
            if prior is not None:
                continue
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
                root = runtime_root / policy
                for step in history["steps"]:
                    if (policy, history["id"], step["id"]) in closed:
                        continue
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
                    known_length_failure = (result.get("error") in {
                            "VLLM_CHAT_TRUNCATED",
                            "Finite decision input exceeds declared complete-input capacity"}
                        and all(result["budget_after"][kind]["unknown_usage"]
                                == result["budget_before"][kind]["unknown_usage"]
                                for kind in ("generation", "embedding")))
                    if result["status"] != "COMPLETED" and not known_length_failure:
                        raise RuntimeError("First Host failure retained; inspect before a new run")
        run["status"] = ("COMPLETED_WITH_FAILURES" if any(r["status"] != "COMPLETED"
                         for r in run["completed"]) else "COMPLETED")
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        run.update(wall_seconds=time.perf_counter() - started, finished_epoch=time.time())
        write_json(args.output / "budget-after.json", read_json(budget_path))
        write_json(args.output / "driver.json", run)


if __name__ == "__main__":
    main()
