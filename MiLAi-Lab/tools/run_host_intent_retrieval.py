"""Run development requests through the existing persistent Host and retrieval tool."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("histories", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--policies", nargs="+", choices=("fixed", "fixed_context", "rules",
                        "laya", "generative"), default=["rules", "laya"])
    parser.add_argument("--history", action="append")
    parser.add_argument("--host-site-packages", type=Path)
    parser.add_argument("--native-probe", action="store_true", help=(
        "E0 only: one named native retrieval call then the original Host answer. "
        "This is interface validation, not autonomous tool-use evaluation."))
    args = parser.parse_args()
    if args.host_site_packages:
        site.addsitedir(str(args.host_site_packages))
    from langchain_core.messages import ToolMessage

    from milai_lab.runners.functional import message, prepare

    def native_probe(messages: list[Any]) -> Any:
        if any(isinstance(row, ToolMessage) and row.name == "milai_retrieve" for row in messages):
            return "none"
        return {"type": "function", "function": {"name": "milai_retrieve"}}

    args.output.mkdir(parents=True, exist_ok=False)
    fixture = read_json(args.histories)
    histories = [h for h in fixture["histories"] if not args.history or h["id"] in args.history]
    config = read_json(args.config)
    budget_path = Path(config["entrypoints"]["functional"]["budget_path"])
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "started_epoch": time.time(),
        "native_probe": args.native_probe, "planned_positions": sum(
            len(h["requests"]) for h in histories) * len(args.policies), "completed": [],
        "automatic_retry": False, "source_groups": [h["source_group"] for h in histories],
        "costs": "original continuous ledger; provider and local model traces retained"}
    write_json(args.output / "fixture.json", fixture)
    write_json(args.output / "driver.json", driver)
    write_json(args.output / "budget-before.json", read_json(budget_path))
    models: dict[tuple[Any, ...], Any] = {}
    started = time.perf_counter()
    try:
        for policy in args.policies:
            recipe = copy.deepcopy(config)
            settings = recipe["entrypoints"]["functional"]
            settings["memory_control"]["policy"] = policy
            settings["config_version"] += "-" + policy
            path = args.output / f"{policy}-config.json"
            write_json(path, recipe)
            prepare(args.output / policy, path, source_version=args.source_version)
        for history in histories:
            for policy in args.policies:
                for request in history["requests"]:
                    driver["active"] = {"history": history["id"], "policy": policy,
                                        "request": request["id"]}
                    write_json(args.output / "driver.json", driver)
                    # Distinct banks retain identical pre-query sources across the paired goals.
                    # Review annotations and the other requests never enter Host input.
                    result = message(args.output / policy,
                        bank=history["id"] + "-" + request["id"], owner="development-user",
                        session="host", message_id="request", content=request["content"],
                        incoming_sources=copy.deepcopy(history["sources"]),
                        control_models=models,
                        model_tool_choice=native_probe if args.native_probe else None)
                    row = {**driver["active"], "status": result["status"],
                           "answer": result.get("final_answer"), "error": result.get("error")}
                    driver["completed"].append(row)
                    write_json(args.output / "driver.json", driver)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    if result["status"] != "COMPLETED":
                        raise RuntimeError(
                            "First failed position retained; inspect before continuing")
        driver["status"] = "COMPLETED"
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter() - started, finished_epoch=time.time())
        write_json(args.output / "driver.json", driver)
        write_json(args.output / "budget-after.json", read_json(budget_path))


if __name__ == "__main__":
    main()
