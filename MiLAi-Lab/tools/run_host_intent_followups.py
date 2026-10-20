"""Collect new source-check requests on copies of closed actual Host histories."""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_retrieval import copy_call_root

FOLLOWUP = (
    "Please inspect the stored reports that arrived after your first answer in this conversation "
    "before answering again. Use them to verify whether the earlier answer is still supported; "
    "do not assume a previously returned interpretation covers those reports.\n\n"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True,
                        help="Version of the execution modules on PYTHONPATH")
    parser.add_argument("--runner-version", required=True)
    args = parser.parse_args()
    from milai_lab.runners.functional import message

    started, cpu = time.perf_counter(), time.process_time()
    plan = read_json(args.plan)
    cases: list[dict[str, Any]] = []
    for spec in plan["cases"]:
        root = Path(spec["run"])
        source_driver = read_json(root / "driver.json")
        if source_driver["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Finish the source flow before followup collection")
        history = next(h for h in read_json(root / "fixture.json")["histories"]
                       if h["id"] == spec["history"])
        if not history.get("continuous"):
            raise ValueError("Source-check followups require an actual continuous history")
        completed = [row for row in source_driver["completed"]
                     if row["history"] == history["id"] and row["status"] == "COMPLETED"]
        previous = completed[-1]
        profile_root = root / previous["profile"]
        path, previous_result = next(
            (path, value) for path in (profile_root / "banks").glob("*/*-result.json")
            for value in [read_json(path)]
            if value["bank"] == history["id"] and value["message_id"] == previous["request"])
        cases.append({"spec": spec, "history": history, "previous": previous,
                      "profile_root": profile_root, "bank_root": path.parent,
                      "owner": previous_result["owner"], "session": previous_result["session"],
                      "workflow": previous_result["workflow"]})
    args.output.mkdir(parents=True, exist_ok=False)
    fixture: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        history = case["history"]
        request = {"id": "source-check-followup",
                   "content": FOLLOWUP + history["requests"][-1]["content"],
                   "incoming_sources": []}
        fixture.append({**copy.deepcopy(history),
                        "requests": [*copy.deepcopy(history["requests"]), request]})
        rows.append({"case": case, "request": request, "profile": f"case-{index:02d}/runtime"})
    write_json(args.output / "fixture.json", {
        "schema": "actual_history_source_check_followups_v1", "histories": fixture,
        "scope": "New normal requests on copied histories; not retries or repaired old results.",
    })
    first_config = read_json(cases[0]["profile_root"] / "input-freeze.json")["config"]
    ledger = Path(first_config["budget_path"])
    driver: dict[str, Any] = {
        "status": "RUNNING", "pid": os.getpid(), "source_version": args.source_version,
        "runner_version": args.runner_version, "planned_positions": len(rows), "completed": [],
        "transport": "json_action", "automatic_retry": False, "capture_retrieval_calls": True,
        "continue_host_history": True, "source_groups": [
            case["history"]["source_group"] for case in cases],
        "scope": "Explicit source-check followups; original positions and outcomes are retained.",
    }
    write_json(args.output / "driver.json", driver)
    write_json(args.output / "budget-before.json", read_json(ledger))
    models: dict[tuple[Any, ...], Any] = {}
    try:
        for row in rows:
            case, request, profile = row["case"], row["request"], row["profile"]
            history, previous = case["history"], case["previous"]
            runtime = args.output / profile
            copy_call_root(case["profile_root"], case["bank_root"], runtime)
            settings = read_json(runtime / "input-freeze.json")["config"]
            if Path(settings["budget_path"]) != ledger:
                raise ValueError("All followups retain the original shared ledger")
            write_json(runtime.parent / "source.json", {
                "run": case["spec"]["run"], "history": history["id"],
                "previous_completed_message": previous["request"],
                "source_profile": str(case["profile_root"]),
                "source_bank_root": str(case["bank_root"]),
                "original_request": history["requests"][-1]["content"],
                "new_request": request,
            })
            driver["active"] = {"history": history["id"], "request": request["id"],
                                "profile": profile, "policy": previous["policy"],
                                "interface": previous.get("interface", "rich")}
            write_json(args.output / "driver.json", driver)
            message_start, message_cpu = time.perf_counter(), time.process_time()
            result = message(
                runtime, bank=history["id"], owner=case["owner"], session=case["session"],
                message_id=request["id"], content=request["content"], incoming_sources=[],
                workflow=case["workflow"],
                previous_host_message=previous["request"],
                retrieval_snapshots=args.output / "frozen-retrieval-calls",
                control_models=models,
            )
            outcome = {**driver["active"], "status": result["status"],
                       "answer": result.get("final_answer"), "error": result.get("error"),
                       "wall_seconds": time.perf_counter() - message_start,
                       "cpu_seconds": time.process_time() - message_cpu}
            driver["completed"].append(outcome)
            write_json(args.output / "driver.json", driver)
            print(json.dumps(outcome, ensure_ascii=False), flush=True)
            known_failure = (
                result.get("error_type") == "IncompleteChatResponse"
                and result.get("error_category") == "provider_protocol"
                and all(result["budget_before"][kind]["unknown_usage"]
                        == result["budget_after"][kind]["unknown_usage"]
                        for kind in ("generation", "embedding")))
            if result["status"] != "COMPLETED" and not known_failure:
                raise RuntimeError("First unexplained failure retained; no automatic retry")
        driver["status"] = ("COMPLETED_WITH_FAILURES" if any(
            row["status"] != "COMPLETED" for row in driver["completed"]) else "COMPLETED")
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu)
        write_json(args.output / "driver.json", driver)
        write_json(args.output / "budget-after.json", read_json(ledger))


if __name__ == "__main__":
    main()
