"""Frozen MERIT native references and opt-in Agent/MCP, without replacing its loop."""

from __future__ import annotations

import copy
import sqlite3
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.contracts.benchmark import BenchmarkJob, BenchmarkPreparationReceipt
from milai_lab.datasets.merit import load_native_domain_arc
from milai_lab.harness.benchmark_execution import (
    finish_job as finish_job,
)
from milai_lab.harness.benchmark_execution import (
    prepare_manifest as prepare_manifest,
)
from milai_lab.harness.benchmark_execution import (
    sha as sha,
)
from milai_lab.harness.benchmark_execution import (
    source_identity as source_identity,
)
from milai_lab.harness.benchmark_execution import (
    start_job as start_job,
)
from milai_lab.harness.benchmark_execution import (
    trace_costs as trace_costs,
)
from milai_lab.harness.benchmark_execution import (
    validate_config as validate_config,
)
from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.merit_metered import TRANSPORT_CONTRACT, metered_litellm

ARMS = {"no_memory", "native_full_replay_tail60000", "milai"}
U2_ARMS = {"full_history", "strong_raw_rag", "rolling_summary", "ordinary_milai", "mem0_native",
           "simplemem_text"}


def selection_jobs(path: Path, group: str) -> list[BenchmarkJob]:
    manifest = read_json(path)
    if group not in {"smoke", "development", "confirmation"}:
        raise ValueError("MERIT_GROUP_UNDECLARED")
    result: list[BenchmarkJob] = []
    for row in manifest["groups"][group]["arcs"]:
        selection_path = Path(row["selection_path"])
        if not selection_path.is_absolute():
            selection_path = path.parent / selection_path
        selection, arc, _tools, _metrics, _runner = load_native_domain_arc(selection_path)
        result.append({"job_id": arc.arc_id, "selection_path": str(selection_path.resolve()),
                       "selection_sha256": sha(selection_path), "domain": selection["domain"],
                       "arc_sha256": selection["private_artifacts"]["arc_sha256"],
                       "public_messages": selection["user_message_count"]})
    if not result or len({row["job_id"] for row in result}) != len(result):
        raise ValueError("MERIT_JOBS_INVALID")
    return result


def prepare(args: Any, *, lab_root: Path) -> BenchmarkPreparationReceipt:
    config = read_json(args.config)
    validate_config(config)
    if args.arm not in ARMS | U2_ARMS:
        raise ValueError("MERIT_ARM_INVALID")
    if args.arm in U2_ARMS:
        from milai_lab.baselines.benchmark_memories import validate_u2

        validate_u2(config)
    jobs = selection_jobs(args.selection, args.group)
    identity = {**source_identity(lab_root), "benchmark": "merit", "run_id": args.run,
        "arm_id": args.arm, "recipe_id": config["recipe_id"], "group": args.group,
        "selection_path": str(args.selection.resolve()), "selection_sha256": sha(args.selection),
        "config_path": str(args.config.resolve()), "config_sha256": sha(args.config),
        "config": config, "budget_path": config["budget_path"],
        "runtime_root": str(args.runtime_root.resolve()), "transport": TRANSPORT_CONTRACT,
        "memory_cadence": "Host direct MCP CRUD" if args.arm == "milai" else
            "official native episode-end write",
        "native_replay": "tail60000; includes prior [memory shown]; no deduplication",
        "native_read_context": "official joins all current episode user_messages; native U1 refs "
            "ignore this query; not a legal future-turn query for query-based U2 controls",
        "history_policy": "complete visited owner checkpoint history" if args.arm == "milai"
            else "official episode-local context plus selected native memory",
        "scorer": "official native checker; pre_satisfied distinct from success",
        "rubric_read_by_runner": False}
    if args.arm in U2_ARMS:
        from milai_lab.baselines.benchmark_memories import backend_identity
        from milai_lab.integrations.memory.mem0 import mem0_dependency_identity

        identity.update({"backend": backend_identity(args.arm),
            "transport": "common public LangGraph/v1/native ToolNode; same native business schemas",
            "history_policy": "common lawful Archive-access/read_history; backend projection",
            "memory_cadence": "Host direct strict MCP CRUD" if args.arm == "ordinary_milai" else
                "native Mem0 ADD-only after closed public turn" if args.arm == "mem0_native" else
                "automatic archive projection/update; no ordinary write tools",
            "native_read_context": "current public Human only; no future episode messages",
            "native_replay": "not used; raw checkpoints exclude injected memory shown"})
        if args.arm == "mem0_native":
            identity["mem0_dependency"] = mem0_dependency_identity()
    if args.arm == "simplemem_text":
        from milai_lab.integrations.memory.simplemem import dependency_identity, validate_simplemem

        identity["simplemem_dependency"] = dependency_identity(validate_simplemem(config))
        identity["memory_cadence"] = (
            "pinned core ingest/flush complete closed public turn; native short-flush limits")
    catalogs = []
    for job in jobs:
        selection, _arc, tools, _metrics, runner = load_native_domain_arc(
            Path(job["selection_path"]))
        catalogs.append({"job_id": job["job_id"], "source": selection["source_sha256"],
                         "business_tools": tools.TOOL_SCHEMAS,
                         "system_prompt": runner.SYSTEM_PROMPT})
    identity["native_contracts"] = catalogs
    if args.arm in {"no_memory", "native_full_replay_tail60000"} and (
            identity["dependencies"]["litellm"] is None):
        raise ValueError("MERIT_LITELLM_DEPENDENCY_UNAVAILABLE")
    if args.arm == "milai" or args.arm in U2_ARMS:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from langgraph.store.memory import InMemoryStore

        from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE, create_history_read_tool
        from milai_lab.memory.mcp import MemoryMCP

        peer = MemoryMCP(InMemoryStore(), args.run, args.arm, "schema-only",
                         history_tool=create_history_read_tool(None),
                         read_only=args.arm in U2_ARMS - {"ordinary_milai"})
        identity["memory_tools"] = peer.catalog
        if args.arm in {"full_history", "rolling_summary", "strong_raw_rag"}:
            identity["memory_tools"] = [tool for tool in peer.catalog
                                        if tool["function"]["name"] == "read_history"]
        if args.arm == "mem0_native":
            from milai_lab.integrations.memory.mem0 import (
                MEM0_SEARCH_DESCRIPTION,
                MEM0_SEARCH_SCHEMA,
            )

            identity["memory_tools"] = [{"type": "function", "function": {
                "name": "search_memory", "description": MEM0_SEARCH_DESCRIPTION,
                "parameters": MEM0_SEARCH_SCHEMA}},
                convert_to_openai_tool(create_history_read_tool(None))]
        if args.arm == "simplemem_text":
            from milai_lab.integrations.memory.simplemem import SEARCH_DESCRIPTION, SEARCH_SCHEMA

            identity["memory_tools"] = [{"type": "function", "function": {
                "name": "search_memory", "description": SEARCH_DESCRIPTION,
                "parameters": SEARCH_SCHEMA}},
                convert_to_openai_tool(create_history_read_tool(None))]
        identity["namespace_template"] = list(MEMORY_NAMESPACE)
        identity["history_read_tool"] = convert_to_openai_tool(create_history_read_tool(None))
    return prepare_manifest(args, identity, jobs)


def run_native_arc(selection_path: Path, root: Path, arm: str, client: VLLMClient,
                   ) -> dict[str, Any]:
    selection, arc, tools, metrics, runner = load_native_domain_arc(selection_path)
    memory = (runner.memory_module.NoMemory() if arm == "no_memory" else
              runner.memory_module.FullReplay())
    world = arc.make_world()
    rows = []
    try:
        with metered_litellm(client) as calls:
            for episode in arc.episodes:
                task = episode.task
                checker = getattr(metrics, task.checker)
                before = world.snapshot()
                pre = bool(checker(before, **task.checker_args))
                budget_before = copy.deepcopy(client.budget.state) if client.budget else None
                call_start = len(calls)
                result = runner.run_episode(world, memory, task.user_messages, task.task_id,
                    model=client.config.model, log_dir=root, api_base=client.config.base_url,
                    tool_funcs=tools.TOOL_FUNCS, tool_schemas=tools.TOOL_SCHEMAS,
                    system_prompt=runner.SYSTEM_PROMPT)
                after = world.snapshot()
                post = bool(checker(after, **task.checker_args))
                # Evaluator-only golds: never passed to completion or the memory writer.
                golds = task.golds()
                shown = bool(task.dependent and golds
                             and all(gold in result.memory_block for gold in golds))
                utilized = bool(golds and metrics.memory_utilized(result.tool_calls, golds))
                memory.write(result.episode_id, result.transcript)
                episode_calls = calls[call_start:]
                public_turns = [{"public_index": index,
                    "generations": [call for call in episode_calls
                                    if call["public_index"] == index],
                    "status": "COMPLETED" if any(call["public_index"] == index and
                        call["final_reply"] for call in episode_calls) else
                        "PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED"}
                    for index in range(len(task.user_messages))]
                row = {"episode_index": episode.index, "task_id": task.task_id,
                       "dependent": task.dependent, "before_world": before, "after_world": after,
                       "native_score": {"pre_satisfied": pre, "checker_after": post,
                           "success": not pre and post, "memory_had_fact": shown,
                           "argument_value_match": utilized, "memory_utilized": shown and utilized},
                       "native_result": asdict(result), "budget_before": budget_before,
                       "public_turns": public_turns,
                       "host_status": "COMPLETED" if all(turn["status"] == "COMPLETED"
                           for turn in public_turns) else "INCOMPLETE_NATIVE_TURN",
                       "budget_after": (copy.deepcopy(client.budget.state)
                                        if client.budget else None),
                       "memory_records": [asdict(record) for record in memory.records]}
                write_json(root / f"episode-{episode.index}.json", row)
                rows.append(row)
        result = {"status": "COMPLETED", "arc_id": arc.arc_id, "domain": selection["domain"],
                  "arm": arm, "episodes": rows,
                  "native_denominator": len(arc.episodes),
                  "native_successes": sum(row["native_score"]["success"] for row in rows)}
        write_json(root / "result.json", result)
        return result
    finally:
        with sqlite3.connect(root / "world.sqlite") as disk:
            world.conn.backup(disk)
        write_json(root / "final-world.json", world.snapshot())
        world.conn.close()


def run(args: Any, *, lab_root: Path) -> dict[str, Any]:
    # Rebuild the zero-model identity without overwriting the original prepared receipt.
    original_output = args.output
    args.output = args.runtime_root / "identity-recheck.json"
    prepare(args, lab_root=lab_root)
    args.output = original_output
    current = read_json(args.runtime_root / "run_manifest.json")
    manifest, job, root = start_job(args, identity=current["identity"], jobs=current["jobs"])
    config = current["identity"]["config"]
    run_id = args.run + ":" + args.job
    write_json(root / "run_manifest.json", {"identity": {"run_id": run_id, "arm_id": args.arm}})
    try:
        if args.arm == "milai" or args.arm in U2_ARMS:
            from milai_lab.baselines.langmem_benchmark import merit_adapters
            from milai_lab.runners.langmem_application_runtime import open_application_runtime
            from milai_lab.runners.langmem_merit import _run_merit_arc

            with open_application_runtime(config, run_id, args.arm, root, "unified-merit",
                                          enable_projection=False) as runtime, ExitStack() as stack:
                factory, completed = merit_adapters(runtime, root, run_id, args.arm, config, stack,
                    backend=args.arm if args.arm in U2_ARMS else None)
                result = _run_merit_arc(Path(job["selection_path"]), root, run_id, runtime.model,
                    runtime.store, runtime.checkpointer, config, arm_id=args.arm,
                    observer=runtime.observer, arc_loader=load_native_domain_arc,
                    agent_factory=factory, public_turn_callback=completed)
        else:
            trace = Trace(root / "trace.jsonl", "unified-merit-native")
            budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                        generation_tokens=None, embedding_tokens=None),
                               Path(config["budget_path"]))
            with VLLMClient(VLLMConfig(**config["host"]), budget=budget, emit=lambda event:
                           trace({"role": "task_host", **event}),
                           capacity=HostCapacity(config["capacity"])) as client:
                result = run_native_arc(Path(job["selection_path"]), root, args.arm, client)
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
