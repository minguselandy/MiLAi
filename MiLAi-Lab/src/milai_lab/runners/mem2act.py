"""GivenTool evaluation through the normal persistent Host and retrieval tool."""
from __future__ import annotations

import json
import os
import shutil
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from milai_lab.datasets.mem2act import given_tool_input, history_sources, score_business_calls
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.action_intents import proposed_business_calls
from milai_lab.runners.functional import frozen, message, prepare
from milai_lab.runners.retrieval_histories import prepare_history_bank


def run_given_tool(
    config: Path, rows: list[dict[str, Any]], sessions: list[dict[str, Any]], output: Path,
    *, source_version: str,
) -> dict[str, Any]:
    """One released corpus, fresh counterfactual Store copy for every query.

    Query/answer sources from one evaluation task cannot become another task's
    memory. The local decision model pool persists across tasks; its load and
    inference remain metered by the existing runner. Source setup/copy/scoring
    overhead is measured separately and left for settlement after this job closes.
    """
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    template = output / "template"
    bank, owner = "released-memory", "mem2act-evaluation"
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": source_version, "started_epoch": time.time(),
        "planned_positions": len(rows), "released_sessions": len(sessions),
        "completed": [], "automatic_retry": False, "business_execution": False,
        "history_protocol": "All released sessions in release order. Each query gets an "
                            "independent copy of the same initial Store; no gold source filter.",
        "shared_bank_count": 1, "model_pool": "Same process, reused across query copies."}
    write_json(output / "driver.json", driver)
    overhead_wall = overhead_cpu = 0.0
    budget_path = None
    models: dict[tuple[Any, ...], Any] = {}

    @contextmanager
    def overhead() -> Iterator[None]:
        nonlocal overhead_wall, overhead_cpu
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            yield
        finally:
            overhead_wall += time.perf_counter() - wall
            overhead_cpu += time.process_time() - cpu

    try:
        with overhead():
            with (output / "references.jsonl").open("w") as stream:
                for row in rows:
                    stream.write(json.dumps({key: row[key] for key in (
                        "qa_id", "tool_call", "source_conversation_ids", "complexity_metadata")},
                        ensure_ascii=False) + "\n")
            prepare(template, config, source_version=source_version)
            budget_path = Path(frozen(template)["config"]["budget_path"])
            write_json(output / "budget-before.json", read_json(budget_path))
            setup = prepare_history_bank(template, bank=bank, owner=owner, history={
                "source_group": "mem2act-released-common-history",
                "sources": history_sources(sessions)})
            write_json(output / "source-setup.json", setup)
        for index, row in enumerate(rows):
            with overhead():
                driver["active"] = {"row": index, "qa_id": row["qa_id"]}
                write_json(output / "driver.json", driver)
                case_root = output / "cases" / f"{index:04d}"
                shutil.copytree(template, case_root)
                public = given_tool_input(row)
            task_started = time.perf_counter()
            result = message(case_root, bank=bank, owner=owner, session="evaluation",
                message_id=row["qa_id"], content=public["query"],
                recorded_tool_schemas=[public["target_tool_schema"]], control_models=models)
            task_wall = time.perf_counter() - task_started
            with overhead():
                proposals = proposed_business_calls(result["messages"],
                                                     memory_tool_names={"milai_retrieve"})
                score = score_business_calls(row["tool_call"], proposals)
                case = {"row": index, "qa_id": row["qa_id"], "status": result["status"],
                    "error": result.get("error"), "host_wall_seconds": task_wall,
                    "proposed_business_calls": proposals,
                    "executed_intent_records": result.get("recorded_tool_calls", []),
                    "metrics": score,
                    "completed_strict_call_match": result["status"] == "COMPLETED"
                                                   and score["strict_call_match"]}
                write_json(case_root / "evaluation.json", case)
                driver["completed"].append(case)
                write_json(output / "driver.json", driver)
            print(json.dumps({"completed": len(driver["completed"]), "planned": len(rows),
                              "status": result["status"]}), flush=True)
            known_failure = ((result.get("error_type") == "IncompleteChatResponse"
                and result.get("error_category") == "provider_protocol")
                or result.get("error") == "FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED")
            known_failure = known_failure and all(
                result["budget_after"][kind]["unknown_usage"]
                == result["budget_before"][kind]["unknown_usage"]
                for kind in ("generation", "embedding"))
            if result["status"] != "COMPLETED" and not known_failure:
                raise RuntimeError("First failed position retained; inspect before continuing")
        driver["status"] = ("COMPLETED_WITH_FAILURES" if any(
            case["status"] != "COMPLETED" for case in driver["completed"]) else "COMPLETED")
        driver["program_counts"] = dict(Counter(case["status"] for case in driver["completed"]))
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter() - started, finished_epoch=time.time())
        write_json(output / "driver.json", driver)
        write_json(output / "orchestration-compute.json", {
            "wall_seconds": overhead_wall, "cpu_seconds": overhead_cpu,
            "scope": "Source preparation, Store copies and scoring only; excludes Host/native "
                     "model work already measured by functional runner. Includes partial "
                     "orchestration stages that fail; never count this as the whole job cost.",
            "model_calls": 0, "ledger_recorded": False,
            "ledger": str(budget_path) if budget_path is not None else None})
        if budget_path is not None:
            write_json(output / "budget-after.json", read_json(budget_path))
    return driver
