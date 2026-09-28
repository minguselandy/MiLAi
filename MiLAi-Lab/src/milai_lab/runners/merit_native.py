"""Frozen MERIT native references and opt-in Agent/MCP, without replacing its loop."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.merit import load_native_domain_arc
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
from milai_lab.providers.merit_metered import TRANSPORT_CONTRACT, metered_litellm

ARMS = {"no_memory", "native_full_replay_tail60000", "milai"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_costs(root: Path) -> dict[str, Any]:
    """Disjoint request/usage categories; inclusive MCP timing is not added to model wall time."""
    roles: dict[str, Any] = {}
    mcp: dict[str, Any] = {}
    phase = "task_host"
    path = root / "trace.jsonl"
    for line in path.read_text().splitlines() if path.exists() else []:
        event = json.loads(line)
        if event.get("event") == "benchmark_phase":
            phase = event["phase"]
        if event.get("event") in {"vllm_response", "vllm_error"}:
            role = "embedding:" + phase if event.get("path") == "embeddings" else phase
            row = roles.setdefault(role, {"requests": 0, "known_tokens": 0, "unknown_usage": 0})
            row["requests"] += 1
            usage = event.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(tokens) is int:
                row["known_tokens"] += tokens
            else:
                row["unknown_usage"] += 1
        if event.get("event") == "langmem_mcp" and event.get("kind") in {"http", "resource_result"}:
            row = mcp.setdefault(event["kind"], {"calls": 0, "cpu_ns": 0, "wall_ns": 0,
                                                "logical_bytes": 0})
            row["calls"] += 1
            for key in ("cpu_ns", "wall_ns"):
                row[key] += event[key]
            row["logical_bytes"] += (len(event["request_body"].encode()) +
                len(event["response_body"].encode()) if event["kind"] == "http" else
                event["logical_bytes"])
    return {"roles": roles, "mcp_inclusive_observation_costs": mcp,
            "physical_io": None, "store_net_cpu_ns": None,
            "timing_scope": "transport/service/material timings overlap; not additive",
            "ledger_owner": "single runtime RunBudget; no second charge here"}


def validate_config(config: dict[str, Any]) -> None:
    host = config["host"]
    if (host["tool_mode"] != "native" or host["max_tokens"] != 4096
            or host["max_calls"] != 12 or host["temperature"] != 0
            or host["enable_thinking"] is not False
            or config["capacity"]["enable_thinking"] is not False
            or not Path(config["budget_path"]).is_absolute()
            or config["memory_contract"] != "strict"
            or config.get("memory_transport") != "mcp_http"):
        raise ValueError("UNIFIED_BENCHMARK_CONFIG_INVALID")


def source_identity(lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_unified_benchmarks.py", lab_root / "pyproject.toml"]
    dependencies: dict[str, str | None] = {}
    native_lock = lab_root / "data/locks/unified-v8-v9-native-transport-20260928.requirements.txt"
    for name in ("openai", "litellm", "langchain-core", "langgraph", "langmem", "mcp",
                 "httpx", "transformers", "tokenizers", "psycopg", "jsonschema"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    return {"source_sha256": {str(path.relative_to(lab_root)): sha(path) for path in paths},
            "dependency_lock_sha256": sha(lab_root / "uv.lock"),
            "native_transport_requirements_sha256": (
                sha(native_lock) if native_lock.exists() else None),
            "dependencies": dependencies, "python": sys.version,
            "environment_packages": dict(sorted((dist.metadata["Name"], dist.version)
                for dist in importlib.metadata.distributions() if "Name" in dist.metadata)),
            "git_sha": subprocess.check_output(  # noqa: S603 - fixed read-only command
                [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
                cwd=lab_root, text=True).strip()}


def prepare_manifest(args: Any, identity: dict[str, Any], jobs: list[dict[str, Any]],
                     ) -> dict[str, Any]:
    path = args.runtime_root / "run_manifest.json"
    value = {"identity": identity, "jobs": jobs, "attempts": {},
             "status": "PREPARED_ZERO_MODEL"}
    if path.exists():
        old = read_json(path)
        if old["identity"] != identity or old["jobs"] != jobs:
            raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    else:
        if args.runtime_root.exists() and any(args.runtime_root.iterdir()):
            raise ValueError("UNIFIED_BENCHMARK_RUNTIME_DIRTY")
        write_json(path, value)
    receipt = {"status": "PREPARED_ZERO_MODEL", "jobs": jobs,
               "manifest_path": str(path.resolve()), "identity_sha256": digest(identity)}
    write_json(args.output, receipt)
    return receipt


def selection_jobs(path: Path, group: str) -> list[dict[str, Any]]:
    manifest = read_json(path)
    if group not in {"smoke", "development", "confirmation"}:
        raise ValueError("MERIT_GROUP_UNDECLARED")
    result = []
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


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config = read_json(args.config)
    validate_config(config)
    if args.arm not in ARMS:
        raise ValueError("MERIT_ARM_INVALID")
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
    catalogs = []
    for job in jobs:
        selection, _arc, tools, _metrics, runner = load_native_domain_arc(
            Path(job["selection_path"]))
        catalogs.append({"job_id": job["job_id"], "source": selection["source_sha256"],
                         "business_tools": tools.TOOL_SCHEMAS,
                         "system_prompt": runner.SYSTEM_PROMPT})
    identity["native_contracts"] = catalogs
    if args.arm != "milai" and identity["dependencies"]["litellm"] is None:
        raise ValueError("MERIT_LITELLM_DEPENDENCY_UNAVAILABLE")
    if args.arm == "milai":
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from langgraph.store.memory import InMemoryStore

        from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE, create_history_read_tool
        from milai_lab.baselines.langmem_mcp import MemoryMCP

        peer = MemoryMCP(InMemoryStore(), args.run, args.arm, "schema-only",
                         history_tool=create_history_read_tool(None))
        identity["memory_tools"] = peer.catalog
        identity["namespace_template"] = list(MEMORY_NAMESPACE)
        identity["history_read_tool"] = convert_to_openai_tool(create_history_read_tool(None))
    return prepare_manifest(args, identity, jobs)


def start_job(args: Any, *, identity: dict[str, Any], jobs: list[dict[str, Any]],
              ) -> tuple[dict[str, Any], dict[str, Any], Path]:
    manifest_path = args.runtime_root / "run_manifest.json"
    manifest = read_json(manifest_path)
    if (manifest["identity"] != identity or manifest["jobs"] != jobs
            or read_json(args.prepared)["identity_sha256"] != digest(identity)):
        raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    matches = [job for job in jobs if job["job_id"] == args.job]
    if len(matches) != 1:
        raise ValueError("UNIFIED_BENCHMARK_JOB_UNKNOWN")
    index = jobs.index(matches[0])
    if args.job in manifest["attempts"]:
        raise ValueError("UNIFIED_BENCHMARK_JOB_ALREADY_ATTEMPTED")
    if any(manifest["attempts"].get(job["job_id"], {}).get("status") not in {"COMPLETED", "FAILED"}
           for job in jobs[:index]):
        raise ValueError("UNIFIED_BENCHMARK_JOB_ORDER")
    manifest["attempts"][args.job] = {"status": "STARTED"}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    root = args.runtime_root / "jobs" / args.job
    if root.exists():
        raise ValueError("UNIFIED_BENCHMARK_JOB_RUNTIME_DIRTY")
    root.mkdir(parents=True)
    return manifest, matches[0], root


def finish_job(args: Any, manifest: dict[str, Any], status: str,
               output: Path | None = None, error: BaseException | None = None) -> None:
    manifest["attempts"][args.job] = {"status": status, "output": str(output) if output else None,
                                     "error_type": type(error).__name__ if error else None}
    manifest["status"] = (("COMPLETED" if all(row["status"] == "COMPLETED"
        for row in manifest["attempts"].values()) else "COMPLETED_WITH_FAILURES")
        if len(manifest["attempts"]) == len(manifest["jobs"]) else
        "FAILED" if status == "FAILED" else "PARTIALLY_COMPLETED")
    write_json(args.runtime_root / "run_manifest.json", manifest)


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
        if args.arm == "milai":
            from milai_lab.baselines.langmem_benchmark import merit_adapters
            from milai_lab.runners.langmem_application_runtime import open_application_runtime
            from milai_lab.runners.langmem_merit import _run_merit_arc

            with open_application_runtime(config, run_id, args.arm, root, "unified-merit",
                                          enable_projection=False) as runtime, ExitStack() as stack:
                factory, completed = merit_adapters(runtime, root, run_id, args.arm, config, stack)
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
