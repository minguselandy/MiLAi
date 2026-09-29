"""Run ordered, isolated writer-policy turns from lawful frozen prefixes."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.analysis.trace_accounting import _accounting
from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.tools import BUSINESS_NAMES, _business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    SYSTEM_PROMPT,
    build_agent,
)
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    LocalStateController,
)
from milai_lab.methods.local_state_attention.protocol import ControlResponseError
from milai_lab.methods.local_state_attention.writers import (
    WriterProposalContext,
    WriterTools,
    create_writer_tools,
    make_maintenance_trigger,
    run_writer_boundary,
    scoped_memory_records,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.frozen_action_continuation import _history, _memory_snapshot, _sha
from milai_lab.runners.langmem_application_runtime import (
    ApplicationRuntime,
    open_application_runtime,
)

WriterPolicy = Literal["native_host", "host_both", "boundary_both", "overlap"]
WRITER_POLICY_INSTRUCTIONS = {
    "host_both": ("You own ordinary-memory and local-State writes through the available "
                  "tools. Read actual scoped records and source events; use exact record ids "
                  "for updates or deletions. Tool receipts, including errors, describe what "
                  "actually occurred."),
    "boundary_both": ("An automatic writer boundary ran before this turn; its actual result "
                      "appears in the working view. You may read both record types and request "
                      "maintenance with maintain_records when needed. A trigger request is not "
                      "a new fact; use its returned receipts to judge what occurred."),
    "overlap": ("During this turn you own ordinary-memory writes through the available tools "
                "and may read local State. One separate local-State maintenance boundary runs "
                "after your final answer. Do not report that later boundary as already done."),
}


def run_writer_policy_turn(
    policy: WriterPolicy, messages: list[BaseMessage],
    raw_history: tuple[dict[str, Any], ...], runtime: ApplicationRuntime,
    scope: FoundationScope, world: ApplicationWorld, journal: BusinessActionJournal,
    bank: LocalStateBank, toolset: WriterTools,
    controller: LocalStateController, *, source_view_max_bytes: int = 16384,
) -> dict[str, Any]:
    """Execute one real Host turn and the selected, explicit writer cadence."""
    if policy not in {"native_host", "host_both", "boundary_both", "overlap"}:
        raise ValueError("LSA_WRITER_POLICY_UNKNOWN")
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise ValueError("LSA_WRITER_CURRENT_USER_MISSING")
    graph_config: RunnableConfig = cast(RunnableConfig, scope.config())
    state_scope = StateScope(scope.run_id, scope.arm_id, scope.user_id)
    thread_id = str(graph_config["configurable"]["thread_id"])
    public_index = sum(isinstance(row, HumanMessage) for row in messages) - 1
    message_key = f"{thread_id}:{public_index}"
    current_task = str(messages[-1].content)
    original_history = tuple(raw_history)
    boundary_receipt_history: list[dict[str, Any]] = []

    def remember_boundary_receipts(result: Any) -> None:
        boundary_receipt_history.extend({
            "origin": "boundary_executor", "name": row.name,
            "tool_call_id": row.tool_call_id, "status": row.status,
            "content": str(row.content)} for row in result.receipts)

    def proposal_context(_reason: str = "", _config: RunnableConfig | None = None,
                         ) -> WriterProposalContext:
        events = bank.events(state_scope)
        # The trigger reason is a request by Host, not a new source observation.
        receipts = tuple({"origin": "source_event", **{key: row.get(key) for key in (
            "id", "kind", "actor", "tool_call_id", "content", "status")}}
            for row in events if row.get("kind") == "tool") + tuple(
                boundary_receipt_history)
        return WriterProposalContext(
            state_scope, message_key, current_task,
            original_history, actual_receipts=receipts,
            maintenance_request_reason=_reason)

    def boundary(allowed: tuple[Any, ...]) -> dict[str, Any]:
        events = bank.pending(state_scope)
        latest_user = next((row["id"] for row in reversed(events)
                            if row.get("kind") == "user"), None)
        try:
            result = run_writer_boundary(
                controller, toolset, proposal_context(), allowed,
                config=graph_config, query_source_id=latest_user)
            remember_boundary_receipts(result)
            return {"status": result.status, "proposals": result.proposals,
                    "receipts": [row.model_dump(mode="json") for row in result.receipts],
                    "pending_event_ids": result.pending_event_ids,
                    "acknowledged_event_ids": result.acknowledged_event_ids}
        except (ControlResponseError, httpx.TimeoutException) as error:
            return {"status": "DEGRADED", "reason": str(error),
                    "receipts": [], "pending_event_ids": [row["id"]
                                                     for row in bank.pending(state_scope)],
                    "acknowledged_event_ids": []}

    initial_boundary: dict[str, Any] | None = None
    if policy == "boundary_both" and any(
        row.get("kind") == "user" for row in bank.pending(state_scope)
    ):
        initial_boundary = boundary(toolset.host_tools())

    trigger = (make_maintenance_trigger(controller, toolset, proposal_context,
                                        remember_boundary_receipts)
               if policy == "boundary_both" else None)
    tool_mode: Literal["full", "read_only", "memory_only"] = (
        "full" if policy == "host_both" else
        "read_only" if policy == "boundary_both" else "memory_only")
    agent = build_agent(
        runtime.model, runtime.store, runtime.checkpointer,
        _business_tools(world, scope.user_id), business_call_wrapper=journal,
        observer=runtime.observer, memory_contract="strict",
        system_prompt=(SYSTEM_PROMPT + "\n" + WRITER_POLICY_INSTRUCTIONS[policy]
                       if policy != "native_host" else SYSTEM_PROMPT),
        writer_tools=(toolset if policy != "native_host" else None),
        writer_tool_mode=(tool_mode if policy != "native_host" else "full"),
        writer_maintenance_trigger=trigger,
        writer_view_bank=(bank if policy != "native_host" else None),
        writer_initial_boundary=initial_boundary,
        writer_known_prefix_messages=len(messages),
        source_view_max_bytes=(source_view_max_bytes if policy != "native_host" else None))
    runtime.model.begin_public_message(message_key)
    if runtime.observer is not None:
        runtime.observer.begin_public_message(scope, public_index, current_task)
    result = agent.invoke({"messages": messages}, config=graph_config)
    final_messages: list[BaseMessage] = result["messages"]
    if policy != "native_host":
        from milai_lab.methods.local_state_attention.integration import collect_observations

        collect_observations(bank, state_scope, thread_id, final_messages,
                             skip_before=len(messages), include_tool_status=True)
    host_acknowledged_event_ids: list[str] = []
    if policy == "host_both":
        # Terminal Host turn has seen these actual sources, including its tool receipts.
        # This records consumption only; it certifies no semantic correctness.
        host_acknowledged_event_ids = [row["id"] for row in bank.pending(state_scope)]
        bank.acknowledge_events(state_scope, set(host_acknowledged_event_ids))
    final = next((row for row in reversed(final_messages)
                  if isinstance(row, AIMessage) and not row.tool_calls), None)
    post_turn_boundary = (boundary((toolset.manage_state, toolset.read_record,
                                     toolset.search_memory))
                          if policy == "overlap" else None)
    return {
        "status": "COMPLETED", "writer_policy": policy,
        "scope": {"run_id": scope.run_id, "arm_id": scope.arm_id,
                  "user_id": scope.user_id, "thread_id": thread_id,
                  "public_index": public_index},
        "answer": str(final.content) if final is not None else "",
        "messages": [row.model_dump(mode="json") for row in final_messages],
        "initial_boundary": initial_boundary,
        "post_turn_boundary": post_turn_boundary,
        "host_acknowledged_event_ids": host_acknowledged_event_ids,
        "host_tool_receipts": [row.model_dump(mode="json") for row in final_messages
                               if isinstance(row, ToolMessage)][len([
                                   row for row in messages if isinstance(row, ToolMessage)]):],
        "business_calls": journal.calls_for_thread(thread_id),
        "world": world.snapshot(),
        "states": bank.states(state_scope),
        "pending_event_ids": [row["id"] for row in bank.pending(state_scope)],
        "state_store_stats": bank.store_stats(),
        "host_capacity": (read_json(runtime.model.capacity_path)
                          if runtime.model.capacity_path is not None else None),
    }


POLICIES = {"native_host", "host_both", "boundary_both", "overlap"}


def _cases_and_jobs(inputs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]],
                                                    list[dict[str, str]]]:
    if (inputs.get("kind") != "MILAI_WRITER_POLICY_INPUTS"
            or not isinstance(inputs.get("cases"), list)
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("WRITER_POLICY_INPUTS_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in inputs["cases"]:
        if not isinstance(case, dict):
            raise ValueError("WRITER_POLICY_CASE_INVALID")
        key, owner = case.get("case_id"), case.get("user_id")
        if (not isinstance(key, str) or not key or key in cases
                or not isinstance(owner, str) or not owner
                or not all(isinstance(case.get(name), list) for name in (
                    "raw_history", "states", "memories", "source_events",
                    "pending_event_ids"))
                or not isinstance(case.get("current_task"), str)):
            raise ValueError("WRITER_POLICY_CASE_INVALID")
        history = _history(case["raw_history"])
        if str(history[-1].content) != case["current_task"]:
            raise ValueError("WRITER_POLICY_CURRENT_TASK_CHANGED")
        state_ids = [row.get("id") for row in case["states"]]
        event_ids = [row.get("id") for row in case["source_events"]]
        memory_keys = [(row.get("owner"), row.get("key")) for row in case["memories"]]
        if (any(not isinstance(item, str) or not item for item in
                [*state_ids, *event_ids])
                or len(set(state_ids)) != len(state_ids)
                or len(set(event_ids)) != len(event_ids)
                or len(set(memory_keys)) != len(memory_keys)
                or any(not isinstance(row.get("value"), dict)
                       or not isinstance(row.get("owner"), str)
                       or not isinstance(row.get("key"), str)
                       for row in case["memories"])
                or not set(case["pending_event_ids"]) <= set(event_ids)
                or any(not isinstance(item, str)
                       for item in case["pending_event_ids"])):
            raise ValueError("WRITER_POLICY_PRESTATE_INVALID")
        for row in case["states"]:
            if (not isinstance(row, dict) or not all(name in row for name in (
                    "id", "title", "content", "needs", "evidence_refs", "revision",
                    "archived"))):
                raise ValueError("WRITER_POLICY_STATE_INVALID")
        for row in case["source_events"]:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "kind", "actor", "tool_call_id", "content"}
                    or row["kind"] not in {"user", "tool"}):
                raise ValueError("WRITER_POLICY_EVENT_INVALID")
        if case.get("business_world", {"reservations": [], "attempts": []}) != {
            "reservations": [], "attempts": []}:
            raise ValueError("WRITER_POLICY_WORLD_NONEMPTY_UNSUPPORTED")
        if type(case.get("initial_label_available", False)) is not bool:
            raise ValueError("WRITER_POLICY_WORLD_SETTING_INVALID")
        cases[key] = case
    jobs: list[dict[str, str]] = []
    seen: set[str] = set()
    for job in inputs["jobs"]:
        if not isinstance(job, dict):
            raise ValueError("WRITER_POLICY_JOB_INVALID")
        job_id, case_id, policy = (job.get(name) for name in (
            "job_id", "case_id", "writer_policy"))
        if (not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in seen or case_id not in cases or policy not in POLICIES):
            raise ValueError("WRITER_POLICY_JOB_INVALID")
        seen.add(job_id)
        jobs.append({"job_id": job_id, "case_id": case_id,
                     "writer_policy": policy})
    if not jobs:
        raise ValueError("WRITER_POLICY_NO_JOBS")
    return cases, jobs


def _identity(args: Any, config: dict[str, Any], jobs: list[dict[str, str]], *,
              lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_writer_policy.py", lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "writer_policy_v1", "run_id": args.run,
        "jobs": jobs, "config_path": str(args.config.resolve()),
        "config_sha256": _sha(args.config), "inputs_path": str(args.inputs.resolve()),
        "inputs_sha256": _sha(args.inputs),
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "provider": {key: config[key] for key in ("host", "embedding", "capacity")},
        "control": config["control"], "source_view_max_bytes":
            config["source_view_max_bytes"],
        "host_tools_by_policy": {
            "native_host": "strict_memory_business",
            "host_both": "strict_memory_state_read_business",
            "boundary_both": "memory_state_read_maintenance_trigger_business",
            "overlap": "strict_memory_state_read_business_then_state_boundary"},
        "ordinary_memory_indexed": True, "state_indexed": False,
        "ordinary_memory_contract": "strict",
        "source_catalog_policy": "all_owner_events_no_truncation_host_capacity",
        "host_max_calls_per_public_message": config["host"]["max_calls"],
        "control_max_calls_per_public_message": config["control"][
            "max_calls_per_message"],
        "budget_path": str(Path(config["budget_path"]).resolve()),
        "runtime_root": str(args.runtime_root.resolve()),
        "rubric_read_by_runner": False,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _, jobs = _cases_and_jobs(inputs)
    if (config.get("memory_contract") != "strict"
            or config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12
            or config["host"]["max_tokens"] != 4096
            or config["control"]["max_calls_per_message"] != 13
            or config["control"]["max_tokens"] != 2048
            or type(config.get("source_view_max_bytes")) is not int
            or config["source_view_max_bytes"] <= 0):
        raise ValueError("WRITER_POLICY_CONFIG_INVALID")
    identity = _identity(args, config, jobs, lab_root=lab_root)
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.runtime_root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != identity:
            raise ValueError("WRITER_POLICY_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(jobs), "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _seed(case: dict[str, Any], runtime: Any, bank: LocalStateBank,
          scope: StateScope, root: Path, budget_path: Path,
          ) -> dict[str, Any]:
    owners = {scope.user_id, *(row["owner"] for row in case["memories"])}
    before = _memory_snapshot(runtime.store, scope.run_id, scope.arm_id, owners)
    if any(before.values()) or any(runtime.store.search(scope.namespace(kind), limit=1)
                                   for kind in ("states", "events", "meta")):
        raise ValueError("WRITER_POLICY_NAMESPACE_DIRTY")
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    budget_before = read_json(budget_path) if budget_path.exists() else None
    for row in case["memories"]:
        runtime.store.put(("langmem", scope.run_id, scope.arm_id, row["owner"]),
                          row["key"], row["value"])
    for row in case["source_events"]:
        bank.record_event(scope, row)
    bank.acknowledge_events(scope, {row["id"] for row in case["source_events"]}
                            - set(case["pending_event_ids"]))
    for row in case["states"]:
        runtime.store.put(scope.namespace("states"), row["id"], row, index=False)
    after = _memory_snapshot(runtime.store, scope.run_id, scope.arm_id, owners)
    receipt = {"memory_before": before,
               "memory_after": after,
               "state_ids": [row["id"] for row in bank.states(scope)],
               "pending_event_ids": [row["id"] for row in bank.pending(scope)],
               "seed_memory_puts": len(case["memories"]),
               "seed_state_puts": len(case["states"]),
               "seed_event_puts": len(case["source_events"]),
               "memory_snapshot_search_calls": sum(
                   len(rows) // 64 + 1 for snapshot in (before, after)
                   for rows in snapshot.values()),
               "namespace_guard_search_calls": 3,
               "memory_record_put_calls": len(case["memories"]),
               "memory_snapshot_result_bytes": len(json.dumps(
                   [before, after], ensure_ascii=False).encode("utf-8")),
               "state_event_store_stats": bank.store_stats(),
               "budget_before": budget_before,
               "budget_after": read_json(budget_path) if budget_path.exists() else None,
               "wall_ns": time.perf_counter_ns() - start_wall,
               "cpu_ns": time.process_time_ns() - start_cpu}
    write_json(root / "seed-receipt.json", receipt)
    return receipt


def _run_one(case: dict[str, Any], job: dict[str, str], config: dict[str, Any],
             runtime: Any, root: Path, run_id: str, arm_id: str) -> dict[str, Any]:
    owner = case["user_id"]
    scope = StateScope(run_id, arm_id, owner)
    bank = LocalStateBank(runtime.store, max_states=config["control"]["max_states"],
                          max_events=config["control"]["max_events"],
                          max_state_content_chars=4000,
                          max_total_content_chars=config["control"].get(
                              "aggregate_content_chars"))
    seed = _seed(case, runtime, bank, scope, root, Path(config["budget_path"]))
    host = runtime.model.client
    original_emit = host.emit

    def host_emit(event: dict[str, Any]) -> None:
        if original_emit is not None:
            original_emit({**event, "role": "task_host"})

    def control_emit(event: dict[str, Any]) -> None:
        if original_emit is not None:
            original_emit({**event, "role": "state_control",
                           "control_stage": CONTROL_STAGE.get()})

    host.emit = host_emit
    control_config = replace(VLLMConfig(**config["host"]),
                             max_tokens=config["control"]["max_tokens"])
    world = ApplicationWorld(root / "business-world.sqlite",
                             case.get("initial_label_available", False))
    journal = BusinessActionJournal(root / "business-journal.json", BUSINESS_NAMES)
    try:
        with VLLMClient(control_config, emit=control_emit, budget=host.budget,
                        capacity=host.capacity) as control_client:
            controller = LocalStateController(
                bank, control_client, emit=control_emit,
                max_pending_batch=config["control"]["max_pending_batch"],
                capacity_path=root / "control-capacity.json",
                max_calls_per_message=config["control"]["max_calls_per_message"])
            toolset = create_writer_tools(bank, MEMORY_NAMESPACE)
            result = run_writer_policy_turn(
                cast(WriterPolicy, job["writer_policy"]), _history(case["raw_history"]),
                tuple(case["raw_history"]), runtime,
                FoundationScope(run_id, arm_id, owner, "application:writer:" +
                                job["job_id"]), world, journal, bank, toolset,
                controller, source_view_max_bytes=config["source_view_max_bytes"])
        result.update({"job": job, "seed": seed,
                       "memory_after": scoped_memory_records(toolset, scope,
                                                              emit=control_emit),
                       "control_capacity": (read_json(root / "control-capacity.json")
                                            if (root / "control-capacity.json").exists()
                                            else {}),
                       "trace_path": str((root / "trace.jsonl").resolve()),
                       "checkpoint_path": str((root / "checkpoints.sqlite").resolve()),
                       "budget_path": str(Path(config["budget_path"]).resolve())})
        control_emit({"event": "lsa_store_stats", "operations": bank.store_stats()})
        result["accounting"] = _accounting(root, Path(config["budget_path"]))
        write_json(root / "result.json", result)
        return result
    finally:
        world.close()


def run_job(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    cases, jobs = _cases_and_jobs(inputs)
    identity = _identity(args, config, jobs, lab_root=lab_root)
    manifest_path = args.runtime_root / "run_manifest.json"
    manifest = read_json(manifest_path)
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()
    if (manifest["identity"] != identity
            or read_json(args.prepared)["identity_sha256"] != expected):
        raise ValueError("WRITER_POLICY_PREPARED_IDENTITY_CHANGED")
    index = next((i for i, item in enumerate(jobs) if item["job_id"] == args.job), None)
    if index is None:
        raise ValueError("WRITER_POLICY_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("WRITER_POLICY_JOB_ALREADY_ATTEMPTED")
    if any(item["job_id"] not in manifest["attempts"] for item in jobs[:index]):
        raise ValueError("WRITER_POLICY_JOB_OUT_OF_ORDER")
    job = jobs[index]
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    root = args.runtime_root / "jobs" / args.job
    run_id, arm_id = args.run + ":" + args.job, job["writer_policy"]
    try:
        root.mkdir(parents=True, exist_ok=False)
        with open_application_runtime(config, run_id, arm_id, root, args.stage,
                                      enable_projection=False) as runtime:
            result = _run_one(cases[job["case_id"]], job, config, runtime,
                              root, run_id, arm_id)
        manifest["attempts"][args.job]["status"] = "COMPLETED"
        manifest["outputs"][args.job] = str((root / "result.json").resolve())
        manifest["status"] = "TERMINAL" if len(manifest["attempts"]) == len(jobs) else "RUNNING"
        return result
    except BaseException as error:
        manifest["attempts"][args.job].update({
            "status": "FAILED", "exception": {"type": type(error).__name__,
                                                "message": str(error)}})
        manifest["status"] = "FAILED"
        raise
    finally:
        write_json(manifest_path, manifest)
