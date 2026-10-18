"""Execute shared operations to collect source-family training observations, without gold actions.

The scripted prefixes obtain real evidence and generated views. They are candidate
demonstrations, not authoritative labels, task scores or an independent controller.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, run_memory_control
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.query_structure import cached_structure
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig


class CollectionPrefix:
    def __init__(self, phase: str) -> None:
        self.reuse = phase in {"repeat", "unrelated"}

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if self.reuse:
            use = next((a for a in actions if a.kind == "USE_VIEW"), None)
            return use.id if use else next(a.id for a in actions if a.kind == "HANDOFF")
        for kind in ("SEARCH", "READ", "REFRESH_VIEW", "HANDOFF"):
            action = next((a for a in actions if a.kind == kind
                and not a.parameters.get("history_directory")
                and not a.parameters.get("expand_context")), None)
            if action is not None:
                return action.id
        raise ValueError("No collection operation available")


def capture(service: MemoryService, source: dict[str, Any]) -> str:
    metadata = {"occurred_at": "2032-07-02T09:00:00+08:00", "calendar_context": "Asia/Shanghai"}
    if source["role"] == "tool":
        receipt = service.capture_tool("source-stream", source["id"], source["origin"],
                                       source["content"], None, **metadata)
    else:
        receipt = service.capture_user("source-stream", source["id"], source["content"], **metadata)
    return str(receipt["source_ref"])


def collect_family(
    family: dict[str, Any], root: Path, *, call: Any, token_count: Any,
    material_limit: int, append: Any, source_version: str,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(store, ("operation-collection", "author"), "author", root / "lock",
                                functional_contract="functional_v1")
        mapping = {capture(service, s): s["id"] for s in family["sources"]}
        report: dict[str, Any] = {"family": family["family"],
                                  "split": family["split"], "phases": {}}
        for phase in family["phase_order"]:
            if phase in {"unrelated", "changed"}:
                source = family["unrelated_update" if phase == "unrelated" else "related_update"]
                mapping[capture(service, source)] = source["id"]
            current = service.capture_user("query-stream", phase, family["query"],
                occurred_at="2032-07-02T09:00:00+08:00",
                calendar_context="Asia/Shanghai")["source_ref"]
            mapping[current] = "query:" + phase
            state = MemoryControlState(task={"request": family["query"],
                "query_time": family["query_time"], "calendar_context": "Asia/Shanghai",
                "read_goal": None, "mode": "read", "fresh_observations": []})

            def pool(current: str = current) -> list[dict[str, Any]]:
                refs = [s["event_id"] for s in service.sources() if s["event_id"] != current]
                found = service.search_sources(family["query"], source_refs=refs, limit=20,
                    tokenization="unicode_v1", include_scope=True)
                return build_evidence_packs(service, family["query"], family["query_time"],
                    found["source_materials"], [], source_scope=found["source_scope"])

            def record(event: dict[str, Any], phase: str = phase) -> None:
                Trace(root / f"{phase}-operations.jsonl", "operation_collection")(event)
                if event.get("phase") == "decision_input":
                    append(decision_example(event, {
                        "family": family["family"], "split": family["split"],
                        "row": phase, "training_event": phase,
                        "event_id": f"{family['family']}:{phase}:{event['step']}",
                        "source_version": source_version, "source_id_mapping": dict(mapping),
                        "demonstration": "scripted prefix, not action gold"}))

            operations = EvidenceOperations(service, state, load_pool=pool, refresh_call=call,
                fits=lambda items: token_count(json.dumps(controlled_reader_packet(
                    items, "budget_exhausted"), ensure_ascii=False)) <= material_limit,
                excluded_source_refs=(current,))
            result = run_memory_control(state, CollectionPrefix(phase), operations,
                                        max_steps=8, record=record)
            packet = controlled_reader_packet(operations.reader_evidence(), result["reason"])
            report["phases"][phase] = {"reason": result["reason"],
                "actions": [r["selected"] for r in result["trace"]],
                "view": cached_structure(service),
                "reader_packet": packet, "reader_executed": False}
            write_json(root / "report.json", report)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("families", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = read_json(args.families)
    settings = read_json(args.config)["entrypoints"]["functional"]
    write_json(args.output / "source-families.json", fixture)
    write_json(args.output / "config.json", settings)
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version,
        "families": [], "states": 0, "gold_created": False, "reader_executed": False,
        "automatic_retry": False, "scope": "Scripted observation collection; views require review"}
    write_json(args.output / "run.json", run)
    capacity = HostCapacity(settings["capacity"])
    started, cpu = time.perf_counter(), time.process_time()
    with http_budget_scope(settings) as budget:
        assert budget is not None
        write_json(args.output / "budget-before.json", budget.state)
        try:
            with VLLMClient(VLLMConfig(**settings["host"]), budget=budget, capacity=capacity,
                emit=Trace(args.output / "model-trace.jsonl",
                           "operation_view_collection")) as client:

                def call(messages: Any, schema: Any) -> dict[str, Any]:
                    response = client.chat(messages, response_format={"type": "json_schema",
                        "json_schema": {"name": "query_structure", "schema": schema}},
                        enable_thinking=False)
                    choice = response["choices"][0]
                    if choice["finish_reason"] != "stop":
                        raise IncompleteChatResponse("VIEW_COLLECTION_INCOMPLETE")
                    return parse_object(choice["message"]["content"], reject_duplicate_keys=True)

                def append(row: dict[str, Any]) -> None:
                    row["metadata"]["state_id"] = run["states"]
                    with (args.output / "unlabelled.jsonl").open("a") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    run["states"] += 1

                for family in fixture["families"]:
                    run["active"] = family["family"]
                    write_json(args.output / "run.json", run)
                    report = collect_family(family, args.output / family["family"], call=call,
                        token_count=capacity.text_tokens,
                        material_limit=settings["ordinary_material_tokens"],
                        append=append, source_version=args.source_version)
                    run["families"].append({"family": report["family"], "split": report["split"]})
                    write_json(args.output / "run.json", run)
                    print(json.dumps({"family": report["family"],
                                      "states": run["states"]}), flush=True)
            run["status"] = "COMPLETED"
        except BaseException as error:
            run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            measures = {"wall_including_generation_seconds": time.perf_counter() - started,
                        "local_cpu_seconds": time.process_time() - cpu, "runs": 1,
                        "states": run["states"]}
            budget.record_compute("dynamic_memory_observation_collection", measures)
            write_json(args.output / "compute.json", measures)
            write_json(args.output / "budget-after.json", budget.state)
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
