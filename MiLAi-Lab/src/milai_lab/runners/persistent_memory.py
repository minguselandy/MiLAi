"""Opt-in v3 ordinary-memory recipes over the existing application ReAct runtime."""

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
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt.tool_node import ToolCallWrapper
from langgraph.store.base import BaseStore

from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    SYSTEM_PROMPT,
    FoundationScope,
    build_agent,
    create_history_read_tool,
    create_memory_read_tool,
)
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.history import HistoryAccess, _turn
from milai_lab.methods.local_state_attention.writers import (
    create_writer_tools,
    scoped_memory_records,
)
from milai_lab.methods.memory_result import RESPONSIBILITY_PROMPT, turn_receipts
from milai_lab.providers.langmem_chat import VLLMChatModel, _action_prompt, _action_schema
from milai_lab.runners.frozen_action_continuation import _sha
from milai_lab.runners.langmem_application import ApplicationWorld, _business_tools, run_phase
from milai_lab.runners.langmem_application_runtime import (
    ApplicationRuntime,
    open_application_runtime,
)
from milai_lab.runners.shared_record_use import _empty_namespace, _observations

ARMS = {"B0", "B1", "C"}


def system_prompt(arm: str) -> str:
    return SYSTEM_PROMPT if arm == "B0" else SYSTEM_PROMPT + "\n" + RESPONSIBILITY_PROMPT


def _script(inputs: dict[str, Any]) -> dict[str, Any]:
    if (
        inputs.get("kind") != "MILAI_PERSISTENT_MEMORY_INPUTS"
        or inputs.get("workload") != "application"
        or not isinstance(inputs.get("script"), dict)
    ):
        raise ValueError("PERSISTENT_MEMORY_INPUTS_INVALID")
    script = inputs["script"]
    owners, phases = script.get("users"), script.get("phases")
    if (
        not isinstance(owners, list)
        or not owners
        or any(not isinstance(owner, str) or not owner for owner in owners)
        or len(set(owners)) != len(owners)
        or not isinstance(phases, list)
        or not phases
        or type(script.get("initial_label_available")) is not bool
    ):
        raise ValueError("PERSISTENT_MEMORY_SCRIPT_INVALID")
    indices: dict[tuple[str, str], int] = {}
    seen: set[str] = set()
    for phase_id, phase in enumerate(phases):
        if (
            not isinstance(phase, dict)
            or phase.get("id") != phase_id
            or phase.get("operator_memory") != []
            or phase.get("world_events") != []
            or not isinstance(phase.get("messages"), list)
        ):
            raise ValueError("PERSISTENT_MEMORY_PHASE_INVALID")
        for row in phase["messages"]:
            if not isinstance(row, dict):
                raise ValueError("PERSISTENT_MEMORY_MESSAGE_INVALID")
            owner, session, key = (
                row.get(field) for field in ("user_id", "session_id", "message_id")
            )
            if (
                not isinstance(owner, str)
                or owner not in owners
                or not isinstance(session, str)
                or not session
                or not isinstance(key, str)
                or not key
                or key in seen
                or not isinstance(row.get("text"), str)
                or type(row.get("public_index")) is not int
                or row["public_index"] != indices.get((owner, session), 0)
            ):
                raise ValueError("PERSISTENT_MEMORY_MESSAGE_ORDER_INVALID")
            seen.add(key)
            indices[owner, session] = row["public_index"] + 1
    return cast(dict[str, Any], script)


def _validate(config: dict[str, Any], arm: str) -> None:
    if (
        arm not in ARMS
        or config.get("memory_contract") != "strict"
        or config.get("history_mode") not in {"archive", "retained"}
        or config.get("memory_result", {}).get("correction_entries") != 1
        or config["host"]["tool_mode"] != "json_action"
        or config["host"]["max_calls"] != 12
        or config["host"]["max_tokens"] != 4096
        or config["host"]["temperature"] != 0
        or config["host"]["enable_thinking"] is not False
        or config["capacity"]["enable_thinking"] is not False
        or config["history"]["enabled"] != (config["history_mode"] == "archive")
        or type(config["history"]["page_max_bytes"]) is not int
        or config["history"]["page_max_bytes"] <= 0
        or not Path(config["budget_path"]).is_absolute()
    ):
        raise ValueError("PERSISTENT_MEMORY_CONFIG_INVALID")


def _catalog(history_mode: str) -> list[dict[str, Any]]:
    from langmem import create_search_memory_tool  # type: ignore[import-untyped]

    tools = [
        create_strict_manage_memory_tool(MEMORY_NAMESPACE),
        create_search_memory_tool(namespace=MEMORY_NAMESPACE),
        create_memory_read_tool(MEMORY_NAMESPACE),
        *([create_history_read_tool(None)] if history_mode == "archive" else []),
        *_business_tools(cast(ApplicationWorld, None), "schema-only"),
    ]
    return [convert_to_openai_tool(tool) for tool in tools]


def _identity(
    args: Any, config: dict[str, Any], script: dict[str, Any], lab_root: Path
) -> dict[str, Any]:
    catalog = _catalog(config["history_mode"])
    paths = [
        *sorted((lab_root / "src/milai_lab").rglob("*.py")),
        lab_root / "tools/run_persistent_memory.py",
        lab_root / "pyproject.toml",
    ]
    dependencies = {
        name: importlib.metadata.version(name)
        for name in (
            "langchain-core",
            "langgraph",
            "langgraph-checkpoint-postgres",
            "langgraph-checkpoint-sqlite",
            "langmem",
            "psycopg",
            "jsonschema",
        )
    }
    return {
        "method": "persistent-memory-react-v3",
        "recipe_id": config["recipe_id"],
        "run_id": args.run,
        "arm_id": args.arm,
        "history_mode": config["history_mode"],
        "memory_contract": "strict",
        "persistent_representation": "ordinary_memory",
        "automatic_maintenance": False,
        "selection_calls": False,
        "correction_entries": 1 if args.arm == "C" else 0,
        "correction_capacity": "same public-message Host12; memory/read only",
        "semantic_saved_certification": False,
        "rubric_read_by_runner": False,
        "system_prompt": system_prompt(args.arm),
        "tool_catalog": catalog,
        "action_prompt": _action_prompt(catalog, memory_result=args.arm == "C"),
        "action_schema": _action_schema(
            catalog, generation_only=True, memory_result=args.arm == "C"
        ),
        "common_receipt_projection": "actual current-owner-turn ref/name/status in tool copy",
        "public_messages": sum(len(row["messages"]) for row in script["phases"]),
        "owners": script["users"],
        "config_path": str(args.config.resolve()),
        "config_sha256": _sha(args.config),
        "inputs_path": str(args.inputs.resolve()),
        "inputs_sha256": _sha(args.inputs),
        "config": config,
        "runtime_root": str(args.runtime_root.resolve()),
        "budget_path": config["budget_path"],
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"], cwd=lab_root, text=True
        ).strip(),
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "python": sys.version,
        "dependencies": dependencies,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _validate(config, args.arm)
    script = _script(inputs)
    identity = _identity(args, config, script, lab_root)
    root = args.runtime_root
    path = root / "run_manifest.json"
    if path.exists():
        if read_json(path)["identity"] != identity:
            raise ValueError("PERSISTENT_MEMORY_IDENTITY_CHANGED")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("PERSISTENT_MEMORY_RUNTIME_DIRTY")
        write_json(
            path,
            {"identity": identity, "status": "PREPARED_ZERO_MODEL", "attempts": {}, "outputs": {}},
        )
    receipt = {
        "status": "PREPARED_ZERO_MODEL",
        "manifest_path": str(path.resolve()),
        "identity_sha256": hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "public_messages": identity["public_messages"],
    }
    write_json(args.output, receipt)
    return receipt


def _adapters(
    runtime: ApplicationRuntime,
    bank: LocalStateBank,
    root: Path,
    run_id: str,
    arm: str,
    config: dict[str, Any],
) -> tuple[Callable[..., Any], Callable[..., None]]:
    # Only reuse the existing ordinary-record reader; these State tools are never exposed.
    record_reader = create_writer_tools(bank, MEMORY_NAMESPACE)

    def factory(
        model: VLLMChatModel,
        store: BaseStore,
        checkpointer: BaseCheckpointSaver[str],
        business_tools: Sequence[BaseTool] = (),
        *,
        user_id: str,
        business_call_wrapper: ToolCallWrapper | None = None,
        environment_rules: str = "",
        observer: ProvenanceObserver | None = None,
    ) -> Any:
        scope = StateScope(run_id, arm, user_id)
        graph: dict[str, Any] = {}

        def session_scope(session: str) -> FoundationScope:
            return FoundationScope(run_id, arm, user_id, "application:" + session)

        history = (
            HistoryAccess(
                root,
                scope,
                bank,
                get_state=lambda session: graph["agent"].get_state(session_scope(session).config()),
                thread_id_for_session=lambda session: str(
                    session_scope(session).config()["configurable"]["thread_id"]
                ),
                page_max_bytes=config["history"]["page_max_bytes"],
                emit=model.client.emit,
            )
            if config["history_mode"] == "archive"
            else None
        )

        def records(current: Any) -> list[dict[str, Any]]:
            cfg = current["configurable"]
            if (cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"]) != (run_id, arm, user_id):
                raise ValueError("PERSISTENT_MEMORY_RECORD_OWNER_CHANGED")
            return scoped_memory_records(record_reader, scope, emit=model.client.emit)

        graph["agent"] = build_agent(
            model,
            store,
            checkpointer,
            business_tools,
            business_call_wrapper=business_call_wrapper,
            environment_rules=environment_rules,
            observer=observer,
            system_prompt=system_prompt(arm),
            memory_contract="strict",
            persistent_memory_arm=cast(Any, arm),
            persistent_memory_records=records,
            history_access=history,
            full_history=history is not None,
        )
        return graph["agent"]

    def completed(
        agent: Any,
        scope: FoundationScope,
        public_index: int,
        status: str,
        business_calls: list[dict[str, Any]],
    ) -> None:
        thread = str(scope.config()["configurable"]["thread_id"])
        message_key = f"{thread}:{public_index}"
        start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
        checkpoint = agent.get_state(scope.config())
        messages: list[BaseMessage] = list(checkpoint.values.get("messages", []))
        checkpoint_cost = {
            "calls": 1,
            "logical_bytes": len(
                json.dumps(
                    [row.model_dump(mode="json") for row in messages], ensure_ascii=False
                ).encode("utf-8")
            ),
            "wall_ns": time.perf_counter_ns() - start_wall,
            "cpu_ns": time.process_time_ns() - start_cpu,
        }
        turn = _turn(messages, public_index)
        context = {
            "run_id": run_id,
            "arm_id": arm,
            "user_id": scope.user_id,
            "message_key": message_key,
        }
        receipt = {
            "message_key": message_key,
            "user_id": scope.user_id,
            "status": status,
            "history_mode": config["history_mode"],
            "actual_tool_receipts": turn_receipts(
                [row.model_dump(mode="json") for row in turn], context
            ),
            "business_calls": business_calls,
            "ordinary_records": scoped_memory_records(
                record_reader,
                StateScope(run_id, arm, scope.user_id),
                emit=runtime.model.client.emit,
            ),
            "final_attempts": [
                row.model_dump(mode="json")
                for row in turn
                if isinstance(row, AIMessage) and not row.tool_calls
            ],
            "checkpoint_read": checkpoint_cost,
        }
        write_json(root / "turns" / f"{thread}-{public_index}.json", receipt)
        if runtime.model.client.emit is not None:
            runtime.model.client.emit(
                {
                    "event": "persistent_memory_checkpoint_read",
                    "message_key": message_key,
                    **checkpoint_cost,
                }
            )
            runtime.model.client.emit({"event": "persistent_memory_turn", **receipt})

    return factory, completed


def _accounting(root: Path, budget: Path) -> dict[str, Any]:
    result = _observations(root, budget)
    costs = {
        name: {key: 0 for key in ("calls", "logical_bytes", "cpu_ns", "wall_ns")}
        for name in ("persistent_memory_checkpoint_read", "correction_checkpoint_write")
    }
    trace = root / "trace.jsonl"
    for line in trace.read_text().splitlines() if trace.exists() else []:
        event = json.loads(line)
        name = event.get("event")
        if name == "persistent_memory_checkpoint_read":
            for key in costs[name]:
                costs[name][key] += event[key]
        elif name == "memory_result_correction" and event.get("status") == "ENTERED":
            cost = costs["correction_checkpoint_write"]
            cost["calls"] += event["checkpoint_writes"]
            for key in ("logical_bytes", "cpu_ns", "wall_ns"):
                cost[key] += event[key]
    return {**result, "v3_checkpoint_costs": costs}


def run(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _validate(config, args.arm)
    script = _script(inputs)
    identity = _identity(args, config, script, lab_root)
    root = args.runtime_root
    path = root / "run_manifest.json"
    manifest = read_json(path)
    prepared = read_json(args.prepared)
    expected = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if manifest["identity"] != identity or prepared["identity_sha256"] != expected:
        raise ValueError("PERSISTENT_MEMORY_PREPARED_IDENTITY_CHANGED")
    if type(args.phase) is not int or not 0 <= args.phase < len(script["phases"]):
        raise ValueError("PERSISTENT_MEMORY_PHASE_INVALID")
    attempt = f"phase:{args.phase}"
    if any(
        manifest["attempts"].get(f"phase:{i}", {}).get("status") != "COMPLETED"
        for i in range(args.phase)
    ):
        raise ValueError("PERSISTENT_MEMORY_PHASE_OUT_OF_ORDER")
    if attempt in manifest["attempts"]:
        raise ValueError("PERSISTENT_MEMORY_ATTEMPT_ALREADY_STARTED")
    manifest["attempts"][attempt] = {"status": "STARTED"}
    manifest["status"] = "RUNNING"
    write_json(path, manifest)
    try:
        with open_application_runtime(
            config, args.run, args.arm, root, args.stage, enable_projection=False
        ) as runtime:
            original_emit = runtime.model.client.emit
            runtime.model.client.emit = lambda event: (
                original_emit({**event, "role": "task_host"}) if original_emit is not None else None
            )
            bank = LocalStateBank(runtime.store)
            try:
                if args.phase == 0:
                    _empty_namespace(runtime, bank, args.run, args.arm, script["users"])
                factory, callback = _adapters(runtime, bank, root, args.run, args.arm, config)
                result = run_phase(
                    script,
                    root,
                    args.run,
                    args.arm,
                    args.phase,
                    runtime,
                    memory_contract="strict",
                    agent_factory=factory,
                    public_turn_callback=callback,
                )
            finally:
                if runtime.model.client.emit is not None:
                    runtime.model.client.emit(
                        {
                            "event": "lsa_store_stats",
                            "attempt": attempt,
                            "operations": bank.store_stats(),
                        }
                    )
        manifest["attempts"][attempt] = {"status": "COMPLETED"}
        manifest["status"] = (
            result["status"] if args.phase == len(script["phases"]) - 1 else "PHASE_COMPLETED"
        )
        manifest["outputs"][attempt] = f"phase-{args.phase}-result.json"
        manifest["accounting"] = _accounting(root, Path(config["budget_path"]))
        write_json(path, manifest)
        return result
    except Exception as error:
        manifest["attempts"][attempt] = {"status": "FAILED", "error_type": type(error).__name__}
        manifest["status"] = "FAILED"
        manifest["accounting"] = _accounting(root, Path(config["budget_path"]))
        write_json(path, manifest)
        raise
