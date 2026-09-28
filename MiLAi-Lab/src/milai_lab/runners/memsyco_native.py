"""Native MemSyco reader with boundary-Agent formation and a separate MCP query extension."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import FoundationScope
from milai_lab.baselines.langmem_benchmark import (
    FORMATION_INSTRUCTION,
    agent_query,
    archive_input,
    form,
    formation_key,
    raw_dialogue,
    reader_functions,
    retrieved_material,
    scope_config,
)
from milai_lab.baselines.langmem_mcp import MemoryMCP
from milai_lab.datasets.contextual import HistoryMessage, TaskInput
from milai_lab.datasets.memsyco import MemSycoTask, load_memsyco_tasks
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    digest,
    read_json,
    write_json,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.langmem_application_runtime import open_application_runtime
from milai_lab.runners.merit_native import (
    finish_job,
    prepare_manifest,
    sha,
    source_identity,
    start_job,
    trace_costs,
    validate_config,
)

ARMS = {"raw_dialogue", "milai", "milai_agent"}


@contextmanager
def _runtime(config: dict[str, Any], run_id: str, arm: str, root: Path) -> Iterator[Any]:
    if arm == "raw_dialogue":
        budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
            generation_tokens=None, embedding_tokens=None), Path(config["budget_path"]))
        with VLLMClient(VLLMConfig(**config["host"]), budget=budget,
            capacity=HostCapacity(config["capacity"]),
            emit=Trace(root / "trace.jsonl", "unified-memsyco-reader")) as client:
            yield SimpleNamespace(model=SimpleNamespace(client=client))
    else:
        with open_application_runtime(config, run_id, arm, root, "unified-memsyco",
                                      enable_projection=False) as runtime:
            yield runtime


def _config(config: dict[str, Any]) -> None:
    validate_config(config)
    if (config["formation_instruction"] != FORMATION_INSTRUCTION
            or config["reader"] != {"current_date": "2025-06-01", "extra_instruction": ""}
            or type(config["retrieval"]["limit"]) is not int or config["retrieval"]["limit"] <= 0
            or type(config["retrieval"]["material_max_chars"]) is not int
            or config["retrieval"]["material_max_chars"] <= 0
            or not isinstance(config["agent_query"]["system_prompt"], str)
            or not config["agent_query"]["system_prompt"]):
        raise ValueError("MEMSYCO_NATIVE_CONFIG_INVALID")


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, selection = read_json(args.config), read_json(args.selection)
    _config(config)
    if args.arm not in ARMS or (args.arm == "milai_agent" and args.formation_root is None):
        raise ValueError("MEMSYCO_ARM_INVALID")
    tasks = load_memsyco_tasks(args.selection, group=args.group)
    root = Path(selection["external_root"])
    for source in selection["source_files"]:
        if sha(root / source["relative_path"]) != source["sha256"]:
            raise ValueError("MEMSYCO_SOURCE_CHANGED")
    jobs = [{"job_id": row.case_id, "track": row.track, "owner": row.task.user_id,
             "history_id": row.task.history_id, "history_sha256": digest([
                 asdict(item) for item in row.task.history])} for row in tasks]
    runtime_tasks = {"kind": "MILAI_MEMSYCO_RUNTIME_TASKS", "tasks": [asdict(row) for row in tasks]}
    task_bytes = (json.dumps(runtime_tasks, ensure_ascii=False, indent=2) + "\n").encode()
    peer = MemoryMCP(InMemoryStore(), args.run, args.arm, "schema-only",
                     read_only=args.arm == "milai_agent")
    # Tools bind an explicit Store; schema construction does not open the peer or do I/O.
    sources = {"baselines/common.py": sha(root / "baselines/common.py")}
    for track in {row.track for row in tasks}:
        reader_functions(root, track)
        relative = f"evaluation/task_{track}.py"
        sources[relative] = sha(root / relative)
    identity = {**source_identity(lab_root), "benchmark": "memsyco", "run_id": args.run,
        "arm_id": args.arm, "group": args.group, "recipe_id": config["recipe_id"],
        "config": config, "config_path": str(args.config.resolve()),
        "config_sha256": sha(args.config), "selection_path": str(args.selection.resolve()),
        "selection_sha256": sha(args.selection), "source_commit": selection["source_commit"],
        "source_files": selection["source_files"], "external_root": str(root.resolve()),
        "reader_source_sha256": sources,
        "runtime_tasks_sha256": hashlib.sha256(task_bytes).hexdigest(),
        "runtime_input": "prepare-sanitized TaskInput; execution never parses source gold fields",
        "runtime_root": str(args.runtime_root.resolve()), "budget_path": config["budget_path"],
        "memory_tool_catalog": [] if args.arm == "raw_dialogue" else peer.catalog,
        "formation_instruction": config["formation_instruction"],
        "formation_cadence": "archive boundary Agent, not dialogue-as-live replay",
        "formation_cache_excludes": ["question", "answer", "gold"],
        "reader": {**config["reader"], "upstream_temperature": 0.2,
                   "local_temperature": config["host"]["temperature"],
                   "raw_label": "Earlier conversation",
                   "memory_label": "Retrieved memories from earlier conversation"},
        "formation_root": str(args.formation_root.resolve()) if args.formation_root else None,
        "rubric_read_by_runner": False,
        "agent_query_contract": "separate interface; read-only, zero tool calls permitted"}
    if args.arm == "milai_agent":
        formation = read_json(args.formation_root / "run_manifest.json")
        old = formation["identity"]
        if (old["benchmark"] != "memsyco" or old["arm_id"] != "milai"
                or old["selection_sha256"] != identity["selection_sha256"]
                or old["source_sha256"] != identity["source_sha256"]
                or old["config_sha256"] != identity["config_sha256"]):
            raise ValueError("MEMSYCO_FORMATION_IDENTITY_CHANGED")
        identity["formation_identity_sha256"] = digest(old)
    receipt = prepare_manifest(args, identity, jobs)
    task_path = args.runtime_root / "runtime-tasks.json"
    if task_path.exists() and task_path.read_bytes() != task_bytes:
        raise ValueError("MEMSYCO_RUNTIME_TASKS_CHANGED")
    if not task_path.exists():
        write_json(task_path, runtime_tasks)
    return receipt


def _answer(client: Any, system: str, question: str) -> dict[str, Any]:
    receipt = client.chat([{"role": "system", "content": system},
                           {"role": "user", "content": question.strip()}])
    if len(receipt.get("choices", [])) != 1:
        raise ValueError("MEMSYCO_READER_RESPONSE_INVALID")
    choice = receipt["choices"][0]
    message = choice["message"]
    if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
            or not isinstance(message.get("content"), str) or not message["content"].strip()):
        raise ValueError("MEMSYCO_READER_RESPONSE_INCOMPLETE")
    return {"answer": message["content"], "host_receipt": receipt}


def _method(identity: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    config = identity["config"]
    return {"recipe": config["recipe_id"], "host": config["host"],
            "embedding": config["embedding"], "formation": config["formation_instruction"],
            "tool_catalog": catalog, "source_sha256": identity["source_sha256"],
            "memory_contract": "strict", "transport": "mcp_http"}


def run(args: Any, *, lab_root: Path) -> dict[str, Any]:
    current = read_json(args.runtime_root / "run_manifest.json")
    frozen_identity = current["identity"]
    _config(read_json(args.config))
    if (any(frozen_identity.get(key) != value for key, value in source_identity(lab_root).items())
            or frozen_identity["config_sha256"] != sha(args.config)
            or frozen_identity["selection_sha256"] != sha(args.selection)
            or (frozen_identity["run_id"], frozen_identity["arm_id"], frozen_identity["group"],
                frozen_identity["runtime_root"]) != (
                    args.run, args.arm, args.group, str(args.runtime_root.resolve()))):
        raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    source_root = Path(frozen_identity["external_root"])
    source_hashes = {row["relative_path"]: row["sha256"] for row in frozen_identity["source_files"]}
    source_hashes.update(frozen_identity["reader_source_sha256"])
    if any(sha(source_root / relative) != expected for relative, expected in source_hashes.items()):
        raise ValueError("MEMSYCO_SOURCE_CHANGED")
    task_path = args.runtime_root / "runtime-tasks.json"
    if sha(task_path) != frozen_identity["runtime_tasks_sha256"]:
        raise ValueError("MEMSYCO_RUNTIME_TASKS_CHANGED")
    runtime_tasks = read_json(task_path)
    if runtime_tasks["kind"] != "MILAI_MEMSYCO_RUNTIME_TASKS":
        raise ValueError("MEMSYCO_RUNTIME_TASKS_INVALID")
    (raw,) = [value for value in runtime_tasks["tasks"] if value["case_id"] == args.job]
    fields = dict(raw["task"], history=tuple(HistoryMessage(**message)
                                            for message in raw["task"]["history"]))
    row = MemSycoTask(raw["case_id"], raw["track"], TaskInput(**fields))
    manifest, _job, root = start_job(args, identity=current["identity"], jobs=current["jobs"])
    identity, config = current["identity"], current["identity"]["config"]
    task = row.task
    run_id, arm = args.run + ":" + args.job, args.arm
    try:
        if args.arm == "milai_agent":
            if str(args.formation_root.resolve()) != identity["formation_root"]:
                raise ValueError("MEMSYCO_FORMATION_IDENTITY_CHANGED")
            formation_path = args.formation_root / "jobs" / args.job / "formation.json"
            frozen = read_json(formation_path)
            formation_identity = read_json(args.formation_root / "run_manifest.json")["identity"]
            expected_key = formation_key(archive_input(task), _method(formation_identity,
                                        formation_identity["memory_tool_catalog"]))
            if (digest(formation_identity) != identity["formation_identity_sha256"]
                    or frozen["cache_key"] != expected_key or frozen["status"] != "COMPLETED"):
                raise ValueError("MEMSYCO_FORMATION_CACHE_CHANGED")
            run_id, arm = frozen["scope"]["foundation_run_id"], frozen["scope"]["arm_id"]
        # The runtime owns the only RunBudget; formation, embeddings and reader share it.
        with _runtime(config, run_id, arm, root) as runtime:
            stage = "reader"
            original_emit = runtime.model.client.emit

            def emit(event: dict[str, Any]) -> None:
                if original_emit is not None:
                    original_emit({"benchmark_phase": stage, **event})

            runtime.model.client.emit = emit
            budget_before = copy.deepcopy(runtime.model.client.budget.state)
            prompt_fn, format_fn = reader_functions(source_root, row.track)
            if args.arm == "raw_dialogue":
                emit({"event": "benchmark_phase", "phase": stage})
                material, label = raw_dialogue(task), "Earlier conversation"
                result = _answer(runtime.model.client, prompt_fn(config["host"]["model"],
                    config["reader"]["current_date"], material, label), task.question)
            else:
                with MemoryMCP(runtime.store, run_id, arm, task.user_id, emit=emit,
                    read_only=args.arm == "milai_agent", timeout=max(config["host"]["timeout"],
                    config["embedding"].get("timeout", 180))) as peer:
                    if args.arm == "milai_agent":
                        if peer.records(scope_config(FoundationScope(run_id, arm, task.user_id,
                                                       "snapshot-guard"))) != frozen[
                                                           "records_after"]:
                            raise ValueError("MEMSYCO_FORMATION_SNAPSHOT_CHANGED")
                        stage = "agent_query"
                        emit({"event": "benchmark_phase", "phase": stage})
                        result = agent_query(runtime, peer, task, run_id, arm,
                                             config["agent_query"]["system_prompt"])
                    else:
                        stage = "formation"
                        emit({"event": "benchmark_phase", "phase": stage})
                        formation_before = copy.deepcopy(runtime.model.client.budget.state)
                        formed = form(runtime, peer, archive_input(task), run_id, arm,
                                      config["formation_instruction"])
                        formed.update({"cache_key": formation_key(archive_input(task),
                            _method(identity, peer.catalog)), "budget_before": formation_before,
                            "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
                        write_json(root / "formation.json", formed)
                        stage = "retrieval"
                        emit({"event": "benchmark_phase", "phase": stage})
                        retrieve_before = copy.deepcopy(runtime.model.client.budget.state)
                        retrieved = peer.retrieve(task.question, config["retrieval"]["limit"],
                            scope_config(FoundationScope(run_id, arm, task.user_id, "reader")))
                        material, ids, omitted = retrieved_material(retrieved, format_fn,
                            config["retrieval"]["material_max_chars"])
                        emit({"event": "benchmark_retrieval", "query": task.question,
                              "retrieved": retrieved, "delivered_ids": ids, "omitted_ids": omitted,
                              "material": material, "budget_before": retrieve_before,
                              "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
                        stage = "reader"
                        emit({"event": "benchmark_phase", "phase": stage})
                        result = _answer(runtime.model.client, prompt_fn(config["host"]["model"],
                            config["reader"]["current_date"], material,
                            "Retrieved memories from earlier conversation"), task.question)
                        result.update({"retrieved": retrieved, "delivered_ids": ids,
                                       "omitted_ids": omitted, "material": material})
                    result["ordinary_records_after"] = peer.records(scope_config(FoundationScope(
                        run_id, arm, task.user_id, "final-readback")))
            result.update({"status": "COMPLETED", "case_id": row.case_id, "track": row.track,
                "arm": args.arm, "question": task.question, "owner": task.user_id,
                "budget_before": budget_before,
                "budget_after": copy.deepcopy(runtime.model.client.budget.state)})
            write_json(root / "result.json", result)
        result["costs"] = trace_costs(root)
        write_json(root / "result.json", result)
        write_json(args.output, result)
        finish_job(args, manifest, "COMPLETED", root / "result.json")
        return result
    except BaseException as error:
        write_json(root / "failure.json", {"status": "FAILED", "error_type": type(error).__name__,
                                          "message": str(error), "costs": trace_costs(root)})
        finish_job(args, manifest, "FAILED", error=error)
        raise
