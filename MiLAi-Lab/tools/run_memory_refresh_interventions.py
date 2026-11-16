"""Compare refresh inputs from actual frozen before states; never repair an old trajectory."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from langgraph.store.sqlite import SqliteStore

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
from milai_lab.memory.functional_state import FunctionalRejection, canonical
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.evidence_reading import project_packs
from milai_lab.methods.query_structure import build_query_structure, cached_structure
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

ARMS = ("rebuild_all_available", "incremental_all_available", "incremental_old_bindings_only")
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
                 "required": ["answer"], "additionalProperties": False}


def branch_sources(before: dict[str, Any], arm: str) -> tuple[list[str], list[dict[str, Any]]]:
    refs = before["old_binding_refs"] if arm == "incremental_old_bindings_only" else (
        before["all_available_refs"])
    return list(refs), [s for s in before["before_sources"] if s["event_id"] in refs]


def execute_branch(
    before: dict[str, Any], arm: str, output: Path, *, call: Any, token_count: Any,
    material_limit: int,
) -> dict[str, Any]:
    """Restore a real cached view in a separate bank copy and call the shared executor once."""
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(f"file:{before['base_database']}?mode=ro", uri=True) as source:
        with sqlite3.connect(output / "memory.sqlite") as destination:
            source.backup(destination)
    refs, sources = branch_sources(before, arm)
    task, prior = before["actual_before"]["task"], before["actual_prior_view"]
    report: dict[str, Any] = {"arm": arm, "family": before["family"], "step": before["step"],
        "source_refs": refs, "source_cut": before["source_cut"],
        "prior_revision": prior["revision"],
        "generator_attempted": True, "reader_attempted": False, "automatic_retry": False}
    with SqliteStore.from_conn_string(str(output / "memory.sqlite")) as store:
        service = MemoryService(store, tuple(before["namespace"]), before["owner"], output / "lock",
                                functional_contract="functional_v1")
        store.put((*service.namespace, "query_structure_v1"), "current", copy.deepcopy(prior),
                  index=False)
        write_json(output / "before.json", before)
        try:
            view, result = build_query_structure(service, task["request"], task["query_time"], refs,
                policy="rebuild" if arm == "rebuild_all_available" else "incremental",
                call=call, source_events=sources, force_refresh=True)
            result["source_inventory"] = "explicit frozen before-source cut, not final-bank scan"
            report.update(generator_status="completed", executor=result, generated_view=view)
            evidence = project_packs([view], [-1]) if view is not None else []
        except (FunctionalRejection, ValidationError) as error:
            report.update(generator_status="rejected", error_type=type(error).__name__,
                          error=str(error), generated_view=None)
            evidence = []
        packet = controlled_reader_packet(evidence, report["generator_status"])
        if token_count(canonical(packet)) > material_limit:
            report["delivery_status"] = "material_budget_exhausted"
            packet = controlled_reader_packet([], "material_budget_exhausted")
        else:
            report["delivery_status"] = "delivered" if evidence else "no_new_view"
        report.update(reader_packet=packet, actual_cached_after=cached_structure(service))
        write_json(output / "result.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    settings = read_json(args.config)["entrypoints"]["functional"]
    protocol = read_json(args.protocol)
    write_json(args.output / "config.json", settings)
    write_json(args.output / "protocol.json", protocol)
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": args.source_version, "completed": [], "automatic_retry": False}
    capacity = HostCapacity(settings["capacity"])
    started, cpu = time.perf_counter(), time.process_time()
    with http_budget_scope(settings) as budget:
        assert budget is not None
        write_json(args.output / "budget-before.json", budget.state)
        try:
            with VLLMClient(VLLMConfig(**settings["host"]), budget=budget, capacity=capacity,
                           emit=Trace(args.output / "model-trace.jsonl", "refresh_intervention")) \
                    as client:
                for case in protocol["cases"]:
                    before = read_json(Path(case["before"]))
                    for arm in ARMS:
                        output = args.output / case["family"] / arm
                        run["active"] = {"family": case["family"], "arm": arm}
                        write_json(args.output / "run.json", run)

                        def generate(
                            messages: Any, schema: Any, output: Path = output,
                        ) -> dict[str, Any]:
                            write_json(output / "generator-input.json", {
                                "messages": messages, "schema": schema})
                            response = client.chat(messages, response_format={"type": "json_schema",
                                "json_schema": {"name": "query_structure", "schema": schema}},
                                enable_thinking=False)
                            write_json(output / "generator-response.json", response)
                            choice = response["choices"][0]
                            if choice["finish_reason"] != "stop":
                                raise IncompleteChatResponse("REFRESH_INTERVENTION_INCOMPLETE")
                            return parse_object(choice["message"]["content"],
                                                reject_duplicate_keys=True)

                        result = execute_branch(before, arm, output, call=generate,
                            token_count=capacity.text_tokens,
                            material_limit=settings["ordinary_material_tokens"])
                        task = before["actual_before"]["task"]
                        messages = [{"role": "system", "content": settings["system_prompt"]},
                            {"role": "user", "content": json.dumps({"request": task["request"],
                                "query_time": task["query_time"],
                                "memory": result["reader_packet"]}, ensure_ascii=False)}]
                        result["reader_attempted"] = True
                        write_json(output / "reader-input.json", messages)
                        write_json(output / "result.json", result)
                        response = client.chat(messages, response_format={"type": "json_schema",
                            "json_schema": {"name": "answer", "schema": ANSWER_SCHEMA}},
                            enable_thinking=settings["stage_enable_thinking"]["reader"])
                        write_json(output / "reader-response.json", response)
                        choice = response["choices"][0]
                        if choice["finish_reason"] != "stop":
                            result.update(reader_status="incomplete", final_answer=None)
                        else:
                            answer = parse_object(choice["message"]["content"],
                                                  reject_duplicate_keys=True)
                            result.update(reader_status="completed", final_answer=answer["answer"])
                        write_json(output / "result.json", result)
                        run["completed"].append({**run["active"],
                            "result": str(output / "result.json"),
                            "generator_status": result["generator_status"],
                            "reader_status": result["reader_status"]})
                        write_json(args.output / "run.json", run)
            run["status"] = "COMPLETED_WITH_FAILURES" if any(
                r["generator_status"] != "completed" or r["reader_status"] != "completed"
                for r in run["completed"]) else "COMPLETED"
        except BaseException as error:
            run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            measures = {"wall_including_model_seconds": time.perf_counter() - started,
                        "local_cpu_seconds": time.process_time() - cpu, "runs": 1}
            budget.record_compute("dynamic_memory_refresh_interventions_v1", measures)
            write_json(args.output / "compute.json", measures)
            write_json(args.output / "budget-after.json", budget.state)
            write_json(args.output / "run.json", run)


if __name__ == "__main__":
    main()
