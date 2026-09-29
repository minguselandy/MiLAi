"""Continuous Host-owned records with one optional State-body prefill difference."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt.tool_node import ToolCallWrapper
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from milai_lab.analysis.trace_accounting import _accounting
from milai_lab.application.tools import _business_tools, native_business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    SYSTEM_PROMPT,
    build_agent,
    create_history_read_tool,
)
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.contracts.scope import FoundationScope
from milai_lab.datasets.merit import load_exposed_arc, load_frozen_arc
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel as VLLMChatModel
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.history import HistoryAccess, _turn
from milai_lab.methods.local_state_attention.integration import collect_observations
from milai_lab.methods.local_state_attention.writers import (
    create_writer_tools,
    scoped_memory_records,
)
from milai_lab.runners import langmem_merit
from milai_lab.runners.frozen_action_continuation import _sha
from milai_lab.runners.langmem_application import run_phase
from milai_lab.runners.langmem_application_runtime import (
    ApplicationRuntime,
    open_application_runtime,
)
from milai_lab.runners.writer_policy import WRITER_POLICY_INSTRUCTIONS

ARMS = {"H_shared": "none", "all_shared": "all"}
SHARED_PROMPT = SYSTEM_PROMPT + "\n" + WRITER_POLICY_INSTRUCTIONS["host_both"]


def _workload(inputs: dict[str, Any], lab_root: Path) -> dict[str, Any]:
    if inputs.get("kind") != "MILAI_SHARED_RECORD_USE_INPUTS":
        raise ValueError("SHARED_USE_INPUTS_INVALID")
    if inputs.get("workload") == "merit":
        if (inputs.get("selection_mode") not in {"frozen", "exposed"}
                or not isinstance(inputs.get("selection_path"), str)):
            raise ValueError("SHARED_USE_MERIT_SELECTION_INVALID")
        path = (lab_root / inputs["selection_path"]).resolve()
        loader = load_frozen_arc if inputs["selection_mode"] == "frozen" else load_exposed_arc
        selection, arc, native_tools, _, native_runner = loader(path)
        return {"kind": "merit", "selection_path": path, "loader": loader,
                "selection": selection, "arc": arc, "owners": [f"merit:{arc.arc_id}"],
                "business_tools": native_business_tools(
                    None, native_tools.TOOL_SCHEMAS, native_tools.TOOL_FUNCS),
                "environment_rules": native_runner.SYSTEM_PROMPT.split(
                    "{memory_block}", 1)[0].strip(),
                "public_messages": sum(len(row.task.user_messages) for row in arc.episodes)}
    if inputs.get("workload") != "application" or not isinstance(inputs.get("script"), dict):
        raise ValueError("SHARED_USE_WORKLOAD_INVALID")
    script = inputs["script"]
    owners, phases = script.get("users"), script.get("phases")
    if (not isinstance(owners, list) or not owners
            or any(not isinstance(owner, str) or not owner for owner in owners)
            or len(set(owners)) != len(owners)
            or not isinstance(phases, list) or not phases
            or type(script.get("initial_label_available")) is not bool):
        raise ValueError("SHARED_USE_APPLICATION_INVALID")
    indices: dict[tuple[str, str], int] = {}
    message_ids: set[str] = set()
    count = 0
    for phase_id, phase in enumerate(phases):
        if (not isinstance(phase, dict) or phase.get("id") != phase_id
                or phase.get("operator_memory") != [] or phase.get("world_events") != []
                or not isinstance(phase.get("messages"), list)):
            raise ValueError("SHARED_USE_PHASE_INVALID")
        for message in phase["messages"]:
            if not isinstance(message, dict):
                raise ValueError("SHARED_USE_MESSAGE_INVALID")
            owner, session, key = (message.get(field) for field in (
                "user_id", "session_id", "message_id"))
            if (not isinstance(owner, str) or owner not in owners
                    or not isinstance(session, str) or not session
                    or not isinstance(key, str) or not key or key in message_ids
                    or not isinstance(message.get("text"), str)
                    or type(message.get("public_index")) is not int
                    or message["public_index"] != indices.get((owner, session), 0)):
                raise ValueError("SHARED_USE_MESSAGE_ORDER_INVALID")
            indices[owner, session] = message["public_index"] + 1
            message_ids.add(key)
            count += 1
    return {"kind": "application", "script": script, "owners": owners,
            # Only inspect these actual tools' schemas here; closures are not executed.
            "business_tools": _business_tools(cast(ApplicationWorld, None), "schema-only"),
            "environment_rules": "", "public_messages": count}


def _validate_config(config: dict[str, Any], arm: str) -> None:
    if (arm not in ARMS or config.get("memory_contract") != "strict"
            or config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12 or config["host"]["max_tokens"] != 4096
            or config["host"]["temperature"] != 0
            or config["host"]["enable_thinking"] is not False
            or config["capacity"]["enable_thinking"] is not False
            or config["control"]["max_calls_per_message"] != 13
            or config["control"]["max_tokens"] != 2048
            or config["history"]["enabled"] is not True
            or type(config["history"]["page_max_bytes"]) is not int
            or config["history"]["page_max_bytes"] <= 0
            or type(config.get("source_view_max_bytes")) is not int
            or config["source_view_max_bytes"] <= 0
            or not Path(config["budget_path"]).is_absolute()):
        raise ValueError("SHARED_USE_CONFIG_INVALID")


def _catalog(business_tools: Sequence[BaseTool]) -> list[dict[str, Any]]:
    tools = create_writer_tools(LocalStateBank(InMemoryStore()), MEMORY_NAMESPACE)
    return [convert_to_openai_tool(tool) for tool in (
        tools.manage_memory, tools.search_memory, create_history_read_tool(None),
        tools.manage_state, tools.read_record, *business_tools)]


def _identity(args: Any, config: dict[str, Any], inputs: dict[str, Any],
              workload: dict[str, Any], lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_shared_record_use.py", lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg", "jsonschema"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {"method": "shared_record_use_v2", "recipe_id": config["recipe_id"],
            "run_id": args.run, "arm_id": args.arm, "workload": workload["kind"],
            "state_body_prefill": ARMS[args.arm], "writer_policy": "host_both",
            "memory_contract": "strict", "state_update_contract": "legacy",
            "automatic_maintenance": False, "selection_calls": False,
            "archive_access": "all_visited_owner_checkpoint_history_plus_read_history",
            "source_catalog": "actual_scoped_user_and_tool_events_pending_vs_acknowledged",
            "ordinary_prefill": "same_actual_scoped_records",
            "record_deletion": "exact_saved_record_only_original_history_retained",
            "resume_boundary": "completed_public_turn_process_reopen",
            "host_create_exactly_once": False, "rubric_read_by_runner": False,
            "public_messages": workload["public_messages"],
            "owners": workload["owners"], "system_prompt": SHARED_PROMPT,
            "environment_rules": workload["environment_rules"],
            "tool_catalog": _catalog(workload["business_tools"]),
            "selection_sha256": (_sha(workload["selection_path"])
                                 if workload["kind"] == "merit" else None),
            "selection": workload.get("selection"),
            "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
            "inputs_path": str(args.inputs.resolve()), "inputs_sha256": _sha(args.inputs),
            "config": config, "runtime_root": str(args.runtime_root.resolve()),
            "budget_path": str(Path(config["budget_path"]).resolve()),
            "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
            "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
                [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
                cwd=lab_root, text=True).strip(),
            "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
            "python": sys.version, "dependencies": dependencies}


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _validate_config(config, args.arm)
    workload = _workload(inputs, lab_root)
    identity = _identity(args, config, inputs, workload, lab_root)
    root = args.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != identity:
            raise ValueError("SHARED_USE_RUN_IDENTITY_CHANGED")
    else:
        if any((root / name).exists() for name in (
            "checkpoints.sqlite", "business-world.sqlite", "world.sqlite", "phase-progress.json"
        )):
            raise ValueError("SHARED_USE_RUNTIME_DIRTY")
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run, "arm_id": args.arm,
               "workload": workload["kind"], "public_messages": workload["public_messages"],
               "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _adapters(runtime: ApplicationRuntime, bank: LocalStateBank, root: Path,
              run_id: str, arm_id: str, config: dict[str, Any], workload: str,
              ) -> tuple[Callable[..., Any], Callable[..., None]]:
    tools = create_writer_tools(bank, MEMORY_NAMESPACE)
    prefix = "application:" if workload == "application" else ""
    body_prefill: Literal["all", "none"] = "all" if ARMS[arm_id] == "all" else "none"

    def factory(model: VLLMChatModel, store: BaseStore,
                checkpointer: BaseCheckpointSaver[str], business_tools: Sequence[BaseTool] = (),
                *, user_id: str, business_call_wrapper: ToolCallWrapper | None = None,
                environment_rules: str = "", observer: ProvenanceObserver | None = None) -> Any:
        graph: dict[str, Any] = {}
        scope = StateScope(run_id, arm_id, user_id)

        def scope_for_session(session: str) -> FoundationScope:
            return FoundationScope(run_id, arm_id, user_id, prefix + session)

        history = HistoryAccess(
            root, scope, bank,
            get_state=lambda session: graph["agent"].get_state(scope_for_session(session).config()),
            thread_id_for_session=lambda session: str(scope_for_session(session).config()[
                "configurable"]["thread_id"]),
            page_max_bytes=config["history"]["page_max_bytes"], emit=runtime.model.client.emit)
        agent = build_agent(
            model, store, checkpointer, business_tools,
            business_call_wrapper=business_call_wrapper, environment_rules=environment_rules,
            observer=observer, system_prompt=SHARED_PROMPT, memory_contract="strict",
            writer_tools=tools, writer_view_bank=bank, writer_history_projection=True,
            writer_state_body_prefill=body_prefill, history_access=history,
            source_view_max_bytes=config["source_view_max_bytes"])
        graph["agent"] = agent
        return agent

    def completed(agent: Any, scope: FoundationScope, public_index: int,
                  status: str, business_calls: list[dict[str, Any]]) -> None:
        if (scope.run_id, scope.arm_id) != (run_id, arm_id):
            raise ValueError("SHARED_USE_CALLBACK_SCOPE_CHANGED")
        thread = str(scope.config()["configurable"]["thread_id"])
        message_key = f"{thread}:{public_index}"
        emit = runtime.model.client.emit
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        checkpoint = agent.get_state(scope.config())
        messages = list(checkpoint.values.get("messages", []))
        if emit is not None:
            emit({"event": "shared_turn_checkpoint_read", "message_key": message_key,
                  "calls": 1, "logical_bytes": len(json.dumps([
                      row.model_dump(mode="json") for row in messages],
                      ensure_ascii=False).encode("utf-8")),
                  "wall_ns": time.perf_counter_ns() - start_wall,
                  "cpu_ns": time.process_time_ns() - start_cpu})
        turn = _turn(messages, public_index)
        if not turn or (status == "COMPLETED" and (
            not isinstance(turn[-1], AIMessage) or turn[-1].tool_calls
        )):
            raise ValueError("SHARED_USE_COMPLETED_CHECKPOINT_INVALID")
        state_scope = StateScope(run_id, arm_id, scope.user_id)
        collect_observations(bank, state_scope, thread, messages, include_tool_status=True)
        pending_before = [row["id"] for row in bank.pending(state_scope)]
        acknowledged = pending_before if status == "COMPLETED" else []
        bank.acknowledge_events(state_scope, set(acknowledged))
        session = scope.episode_id.removeprefix(prefix)
        if workload == "merit":
            path = root / "phase-progress.json"
            progress = read_json(path) if path.exists() else {"messages": {}}
            previous = progress["messages"].get(message_key)
            ordinal = previous["visited_ordinal"] if previous else len(progress["messages"])
            progress["messages"][message_key] = {
                "message_id": message_key, "user_id": scope.user_id, "session_id": session,
                "public_index": public_index, "status": status,
                "visited_ordinal": ordinal, "business_calls": business_calls}
            write_json(path, progress)
        receipt = {"message_key": message_key, "user_id": scope.user_id,
                   "session_id": session, "public_index": public_index, "status": status,
                   "states": bank.states(state_scope),
                   "ordinary_records": scoped_memory_records(tools, state_scope, emit=emit),
                   "pending_event_ids_before_ack": pending_before,
                   "acknowledged_event_ids": acknowledged,
                   "pending_event_ids": [row["id"] for row in bank.pending(state_scope)],
                   "source_event_ids": [row["id"] for row in bank.events(state_scope)],
                   "tool_receipts": [row.model_dump(mode="json") for row in turn
                                     if isinstance(row, ToolMessage)],
                   "business_calls": business_calls,
                   "state_store_stats_cumulative": bank.store_stats()}
        write_json(root / "turns" / f"{thread}-{public_index}.json", receipt)
        if emit is not None:
            emit({"event": "shared_record_turn", **receipt})

    return factory, completed


def _empty_namespace(runtime: ApplicationRuntime, bank: LocalStateBank,
                     run_id: str, arm_id: str, owners: list[str]) -> None:
    tools = create_writer_tools(bank, MEMORY_NAMESPACE)
    for owner in owners:
        scope = StateScope(run_id, arm_id, owner)
        memories = scoped_memory_records(tools, scope, emit=runtime.model.client.emit)
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        namespaces = [runtime.store.search(scope.namespace(kind), limit=1)
                      for kind in ("states", "events", "meta")]
        if runtime.model.client.emit is not None:
            runtime.model.client.emit({
                "event": "shared_namespace_guard", "user_id": owner, "calls": 3,
                "logical_bytes": len(json.dumps([[row.dict() for row in rows]
                    for rows in namespaces], ensure_ascii=False, default=str).encode("utf-8")),
                "wall_ns": time.perf_counter_ns() - start_wall,
                "cpu_ns": time.process_time_ns() - start_cpu})
        if memories or any(namespaces):
            raise ValueError("SHARED_USE_NAMESPACE_DIRTY")


def _observations(root: Path, budget_path: Path) -> dict[str, Any]:
    result = _accounting(root, budget_path)
    costs = {name: {key: 0 for key in ("calls", "logical_bytes", "cpu_ns", "wall_ns")}
             for name in ("shared_turn_checkpoint_read", "lsa_writer_memory_read",
                          "shared_namespace_guard")}
    path = root / "trace.jsonl"
    for line in path.read_text().splitlines() if path.exists() else []:
        event = json.loads(line)
        if event.get("event") in costs:
            for key in costs[event["event"]]:
                costs[event["event"]][key] += event[key]
    return {**result, "record_observation_costs": costs,
            "physical_store_io": None, "ordinary_write_cpu_ns": None}


def run(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _validate_config(config, args.arm)
    workload = _workload(inputs, lab_root)
    identity = _identity(args, config, inputs, workload, lab_root)
    root = args.runtime_root
    manifest_path = root / "run_manifest.json"
    manifest, prepared = read_json(manifest_path), read_json(args.prepared)
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode())
    if manifest["identity"] != identity or prepared["identity_sha256"] != expected.hexdigest():
        raise ValueError("SHARED_USE_PREPARED_IDENTITY_CHANGED")
    if args.command == "run-merit" and workload["kind"] == "merit":
        attempt = "merit"
    elif (args.command == "run-phase" and workload["kind"] == "application"
          and type(args.phase) is int and 0 <= args.phase < len(workload["script"]["phases"])):
        attempt = f"phase:{args.phase}"
        for phase in range(args.phase):
            if manifest["attempts"].get(f"phase:{phase}", {}).get("status") != "COMPLETED":
                raise ValueError("SHARED_USE_PHASE_OUT_OF_ORDER")
    else:
        raise ValueError("SHARED_USE_COMMAND_WORKLOAD_MISMATCH")
    if attempt in manifest["attempts"]:
        raise ValueError("SHARED_USE_ATTEMPT_ALREADY_STARTED")
    manifest["attempts"][attempt] = {"status": "STARTED"}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    try:
        with open_application_runtime(config, args.run, args.arm, root, args.stage,
                                      enable_projection=False) as runtime:
            original_emit = runtime.model.client.emit
            runtime.model.client.emit = (lambda event: original_emit({
                **event, "role": "task_host"}) if original_emit is not None else None)
            bank = LocalStateBank(
                runtime.store, max_states=config["control"]["max_states"],
                max_events=config["control"]["max_events"],
                max_total_content_chars=config["control"].get("aggregate_content_chars"))
            try:
                if attempt in {"merit", "phase:0"}:
                    _empty_namespace(runtime, bank, args.run, args.arm, workload["owners"])
                factory, callback = _adapters(runtime, bank, root, args.run, args.arm,
                                              config, workload["kind"])
                if workload["kind"] == "merit":
                    result = langmem_merit._run_merit_arc(
                        workload["selection_path"], root, args.run, runtime.model,
                        runtime.store, runtime.checkpointer, config, args.arm,
                        runtime.observer, continue_on_local_capacity=True,
                        arc_loader=workload["loader"],
                        frozen_identity={"method": identity["method"],
                                         "prepared_identity_sha256": expected.hexdigest()},
                        agent_factory=factory, public_turn_callback=callback)
                else:
                    result = run_phase(workload["script"], root, args.run, args.arm,
                                       args.phase, runtime, memory_contract="strict",
                                       agent_factory=factory, public_turn_callback=callback)
            finally:
                if runtime.model.client.emit is not None:
                    runtime.model.client.emit({"event": "lsa_store_stats", "attempt": attempt,
                                               "operations": bank.store_stats()})
        capacity_failed = (any(row["host_status"] == "LOCAL_CAPACITY_EXCEEDED"
                               for row in result["episodes"])
                           if workload["kind"] == "merit" else
                           result["status"] == "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE")
        manifest["attempts"][attempt] = {"status": "COMPLETED",
                                         "local_capacity_failure": capacity_failed}
        terminal = (workload["kind"] == "merit"
                    or args.phase == len(workload["script"]["phases"]) - 1)
        manifest["status"] = (
            "TERMINAL_WITH_LOCAL_CAPACITY_FAILURE" if terminal and any(
                row.get("local_capacity_failure") for row in manifest["attempts"].values())
            else "TERMINAL" if terminal else "PHASE_COMPLETED")
        manifest["outputs"][attempt] = ("result.json" if workload["kind"] == "merit" else
                                         f"phase-{args.phase}-result.json")
        manifest["accounting"] = _observations(root, Path(config["budget_path"]))
        write_json(manifest_path, manifest)
        return result
    except Exception as error:
        manifest["attempts"][attempt] = {"status": "FAILED", "error_type": type(error).__name__}
        manifest["status"] = "FAILED"
        manifest["accounting"] = _observations(root, Path(config["budget_path"]))
        write_json(manifest_path, manifest)
        raise
