"""Replay the same actual native TRAIN branch bindings under repaired executor semantics."""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore  # type: ignore[import-not-found]

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields
from native_qa_control import actual_packet, environment
from prepare_collected_operation_feedback import execute_branch
from small_control_branches import copy_source_bank


def replay(args: Any) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    parent = read_json(args.prepared / "run.json")
    if parent["status"] != "COMPLETED":
        raise ValueError("Replay requires a closed actual branch preparation")
    collection = Path(parent["collection"])
    histories = {h["source_group"]: h for h in read_json(
        Path(parent["sources"]) / "sources.json")["histories"]}
    originals = read_json(args.prepared / "cases.json")
    if any(histories[case["family"]]["split"] != "train" for case in originals):
        raise ValueError("Feedback replay is limited to assigned TRAIN sources")
    settings = read_json(Path(parent["config"]))["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    cases: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    captures: dict[tuple[str, str], list[dict[str, Any]]] = {}
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "config": parent["config"], "sources": parent["sources"], "collection": str(collection),
        "replayed_from": str(args.prepared), "planned_cases": len(originals), "closed_cases": 0,
        "Reader_calls": 0, "sha_validation": False,
        "execution_contract": "stable_material_indices_search_scope_sync_v2",
        "continuation_policy": parent["continuation_policy"],
        "scope": "Exact saved safe QueryOnce before/menu/first binding/horizon/remainingbudget. "
                 "New actual branches; no copied labels or own-state aggregation."}
    write_json(args.output / "run.json", run)
    try:
        for ci, old in enumerate(originals):
            history = histories[old["family"]]
            request = next(row for row in history["requests"] if row["id"] == old["request_id"])
            bank = collection / "banks" / history["id"]
            mapping = read_json(bank / "source-map.json")
            key = (history["id"], request["id"])
            if key not in captures:
                captures[key] = read_jsonl(bank / f"{request['id']}-query_once4-checkpoints.jsonl")
            matching = [row for row in captures[key]
                if row["decision"]["before"] == old["before"]
                and row["decision"]["actions"] == old["actions"]]
            if len(matching) != 1:
                raise ValueError("Original actual before/menu is not uniquely captured")
            saved = matching[0]
            step = saved["decision"]["step"]
            case = {**copy.deepcopy(old), "branches": []}
            for bi, branch in enumerate(old["branches"]):
                destination = args.output / f"case-{ci:03d}-branch-{bi}"
                copy_source_bank(bank / "memory.sqlite", destination)
                with SqliteStore.from_conn_string(str(destination / "memory.sqlite")) as store:
                    service = MemoryService(store,
                        ("small-control-native", history["id"], "author"), "author",
                        destination / "lock", functional_contract="functional_v1")
                    state = MemoryControlState(**copy.deepcopy(old["before"]))
                    state, operations = environment(service, request, capacity,
                        args.material_tokens, state=state,
                        checkpoint=saved["executor_checkpoint"])
                    if ([asdict(a) for a in operations.actions(state)] != old["actions"]
                            or state.project() != old["before"]):
                        raise ValueError("Repaired executor differs at the saved safe before/menu")
                    result = execute_branch(operations, old["before"],
                        MemoryAction(**branch["action"]), step, old["horizon"],
                        terminal_handoff=branch["continuation"]["terminal_handoff"],
                        policy_name=branch["continuation"]["continuation_policy"])
                    packet, delivered = actual_packet(operations, mapping)
                    task = old["before"]["task"]
                    wire = separate_answer_fields(given_packet_request({
                        "content": request["content"], "query_time": task["query_time"],
                        "calendar_context": task["calendar_context"]},
                        request["retrieval_request"], packet, settings))
                    capacity.check(wire["messages"])
                    replayed = {**copy.deepcopy(branch), "packet": packet,
                        "actual_delivered_source_ranges": delivered, "readout_request": wire,
                        "continuation": result,
                        "body_tokens": capacity.text_tokens(json.dumps(packet)),
                        "execution_result": {"ok": result["reason"] != "operation_outcome_unknown",
                                             "status": result["reason"]}}
                    replayed["condition_provenance"].update(
                        execution_contract=run["execution_contract"],
                        replayed_from=str(args.prepared))
                    case["branches"].append(replayed)
                    checks.append({"event_id": old["event_id"], "horizon": old["horizon"],
                        "action_id": branch["action"]["id"],
                        "before_menu_first_binding_equal": True,
                        "old_Host_wire_equal": wire == branch["readout_request"],
                        "old_delivered_ranges_equal": delivered ==
                                                     branch["actual_delivered_source_ranges"]})
            cases.append(case)
            run["closed_cases"] += 1
            write_json(args.output / "cases.json", cases)
            write_json(args.output / "replay-checks.json", checks)
            write_json(args.output / "run.json", run)
            if run["closed_cases"] % 8 == 0:
                print(json.dumps({"closed_cases": run["closed_cases"]}), flush=True)
        run.update(status="COMPLETED", branches=len(checks),
                   changed_Host_wires=sum(not row["old_Host_wire_equal"] for row in checks))
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter()-tick, cpu_seconds=time.process_time()-cpu,
                   compute_ledger_status="pending_idle_settlement")
        write_json(args.output / "run.json", run)
