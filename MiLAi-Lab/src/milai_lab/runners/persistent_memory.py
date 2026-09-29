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
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt.tool_node import ToolCallWrapper
from langgraph.store.base import BaseStore

from milai_lab.application.tools import _business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    SYSTEM_PROMPT,
    build_agent,
    create_history_read_tool,
)
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.memory.read_tools import create_memory_read_tool
from milai_lab.memory.strict_tools import create_strict_manage_memory_tool
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel as VLLMChatModel
from milai_lab.methods.langmem_recipe import _recipe_action_prompt as _action_prompt
from milai_lab.methods.langmem_recipe import _recipe_action_schema as _action_schema
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    ControlResponseError,
    LocalStateController,
)
from milai_lab.methods.local_state_attention.history import HistoryAccess, _turn
from milai_lab.methods.local_state_attention.writers import (
    create_writer_tools,
    scoped_memory_records,
)
from milai_lab.methods.memory_boundaries import (
    BOUNDARY_PROTOCOL,
    NATIVE_BOUNDARY_PROTOCOL,
    READ_SELECTION_PROMPT,
    MemoryBoundaryView,
    boundary_policy,
    operation_audit,
)
from milai_lab.methods.memory_result import RESPONSIBILITY_PROMPT, turn_receipts
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.runners.frozen_action_continuation import _sha
from milai_lab.runners.langmem_application import run_phase
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
    transport = config.get("memory_transport", "direct")
    if type(transport) is not str or transport not in {"direct", "mcp_http"}:
        raise ValueError("PERSISTENT_MEMORY_TRANSPORT_INVALID")
    policy = boundary_policy(config.get("memory_boundaries", {}))
    enabled = policy is not None
    correction_entries = config.get("memory_result", {}).get(
        "correction_entries", 0 if enabled else None)
    profile = config.get("research_profile")
    if profile is not None and profile != "protocol_calibration_v7":
        raise ValueError("PERSISTENT_MEMORY_RESEARCH_PROFILE_INVALID")
    if profile is not None and (arm != "B0" or policy is None
        or policy["memory_placement"] != "current_request"
        or policy["model_view"] != "compact_v6" or policy["attention_enabled"]
        or config["host"].get("response_format") is not None):
        raise ValueError("PERSISTENT_MEMORY_RESEARCH_PROFILE_INVALID")
    if (
        arm not in ARMS
        or config.get("memory_contract") != "strict"
        or config.get("history_mode") not in {"archive", "retained"}
        or correction_entries != (0 if enabled else 1)
        or (enabled and arm != "B0")
        or config["host"]["tool_mode"] not in (
            {"json_action", "native"} if profile is not None else {"json_action"})
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
    if policy is not None and policy["attention_enabled"] and (
        config.get("control", {}).get("max_tokens") != 2048
        or config.get("control", {}).get("max_calls_per_message") != 13
    ):
        raise ValueError("MEMORY_BOUNDARY_CONTROL_CONFIG_INVALID")


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
    identity = {
        "method": ("persistent-memory-boundaries-v4" if config.get("memory_boundaries", {}).get(
            "enabled", False) else "persistent-memory-react-v3"),
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
    if config.get("memory_boundaries", {}).get("enabled", False):
        policy = boundary_policy(config["memory_boundaries"])
        assert policy is not None
        identity.update({"memory_boundaries": policy,
                         "boundary_protocol": BOUNDARY_PROTOCOL,
                         "read_selection_prompt": READ_SELECTION_PROMPT,
                         "common_receipt_projection": (
                             "request copy: actual ref/name/hash-bound receipt time; "
                             "missing or historical time unknown; original ToolMessage unchanged"),
                         "candidate_token_policy": "all-to-query trigger; not query hard cap",
                         "selection_calls": "conditional; at most one per public turn"
                         if policy["attention_enabled"] else False,
                         "selection_cache": (
                             "ephemeral current-turn IDs only; Store bodies resolved per request; "
                             "no crash-resume cache guarantee"),
                         "program_operation_audit": True,
                         "working_state_persistence": False})
    if config.get("research_profile") is not None:
        native = config["host"]["tool_mode"] == "native"
        identity.update({"method": "persistent-memory-protocol-calibration-v7",
            "research_profile": config["research_profile"],
            "tool_protocol": config["host"]["tool_mode"],
            "action_prompt": None if native else identity["action_prompt"],
            "action_schema": None if native else identity["action_schema"],
            "boundary_protocol": NATIVE_BOUNDARY_PROTOCOL if native else BOUNDARY_PROTOCOL,
            "tool_execution": "synchronous ToolNode executor.map; max_concurrency=1",
            "final_reply": "native natural text" if native else "decoded JSON answer",
            "native_service_verified_by_runner": False})
    if config.get("memory_transport", "direct") == "mcp_http":
        from milai_lab.memory.mcp import MCP_PROTOCOL, RECORDS_RESOURCE

        identity.update({"method": "persistent-memory-mcp-v8-v9",
            "memory_transport": "mcp_http", "mcp_protocol": MCP_PROTOCOL,
            "mcp_sdk": importlib.metadata.version("mcp"),
            "mcp_endpoint": "scope-bound loopback HTTP; ephemeral authenticated endpoint",
            "mcp_material": {"records_resource": RECORDS_RESOURCE,
                "search": "program-origin search_memory over MCP",
                "active_refs": "resolve against current resource response; no body cache"},
            "mcp_accounting": "same runtime Store, embedding client and RunBudget instance"})
        identity["mcp_timeout"] = max(config["host"].get("timeout", 120),
                                      config["embedding"].get("timeout", 180))
    return identity


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
    *, selector_client: VLLMClient | None = None,
    mcp_stack: ExitStack | None = None,
) -> tuple[Callable[..., Any], Callable[..., None]]:
    # Only reuse the existing ordinary-record reader; these State tools are never exposed.
    record_reader = create_writer_tools(bank, MEMORY_NAMESPACE)
    policy = boundary_policy(config.get("memory_boundaries", {}))
    views: dict[str, MemoryBoundaryView] = {}
    selector = (LocalStateController(bank, selector_client, emit=selector_client.emit,
                                    capacity_path=root / "control-capacity.json",
                                    max_calls_per_message=13)
                if selector_client is not None else None)

    def select(message_key: str, query: str, candidates: list[dict[str, Any]]) -> list[str]:
        if selector is None:
            raise ValueError("MEMORY_BOUNDARY_ATTENTION_UNAVAILABLE")
        path = root / "control-capacity.json"
        if path.exists():
            used = read_json(path).get(message_key, 0)
            if used >= 13:
                raise ControlResponseError("LSA_CONTROL_CAPACITY")
            if used >= 1:
                raise ValueError("MEMORY_BOUNDARY_ATTENTION_ALREADY_ATTEMPTED")
        ids = [row["id"] for row in candidates]
        schema = {"type": "object", "properties": {"record_ids": {"type": "array",
                  "items": {"type": "string", "enum": ids}, "uniqueItems": True}},
                  "required": ["record_ids"], "additionalProperties": False}
        plan = selector._stage_call("memory_read_selection", message_key, READ_SELECTION_PROMPT,
                                    {"current_query": query, "candidates": candidates}, schema)
        if (set(plan) != {"record_ids"} or not isinstance(plan["record_ids"], list)
                or any(not isinstance(key, str) or key not in ids for key in plan["record_ids"])
                or len(plan["record_ids"]) != len(set(plan["record_ids"]))):
            raise ValueError("MEMORY_BOUNDARY_ATTENTION_INVALID_IDS")
        return cast(list[str], plan["record_ids"])

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
        model.research_profile = config.get("research_profile")
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
        peer = None
        if config.get("memory_transport", "direct") == "mcp_http":
            from milai_lab.memory.mcp import MemoryMCP

            if mcp_stack is None:
                raise ValueError("PERSISTENT_MEMORY_MCP_LIFECYCLE_MISSING")
            peer = mcp_stack.enter_context(MemoryMCP(store, run_id, arm, user_id,
                emit=model.client.emit,
                timeout=max(model.client.config.timeout, config["embedding"].get("timeout", 180)),
                history_tool=create_history_read_tool(history) if history is not None else None))

        def records(current: Any) -> list[dict[str, Any]]:
            cfg = current["configurable"]
            if (cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"]) != (run_id, arm, user_id):
                raise ValueError("PERSISTENT_MEMORY_RECORD_OWNER_CHANGED")
            return (peer.records(current) if peer is not None else
                    scoped_memory_records(record_reader, scope, emit=model.client.emit))

        def retrieve(query: str, limit: int) -> list[dict[str, Any]]:
            namespace = ("langmem", run_id, arm, user_id)
            start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
            event: dict[str, Any] = {"event": "memory_boundary_retrieval", "user_id": user_id,
                "calls": 1, "query": query, "limit": limit, "logical_bytes": None}
            try:
                if peer is not None:
                    rows = peer.retrieve(query, limit, {"configurable": peer.scope})
                    scores = None
                else:
                    page = store.search(namespace, query=query, limit=limit)
                    if any(tuple(item.namespace) != namespace for item in page):
                        raise ValueError("MEMORY_BOUNDARY_RETRIEVAL_SCOPE_CHANGED")
                    rows = [{"id": item.key, "value": item.value} for item in page]
                    scores = [item.score for item in page]
                event.update({"status": "completed", "returned_ids": [row["id"] for row in rows],
                    "scores": scores,
                    "logical_bytes": len(json.dumps(rows, ensure_ascii=False).encode("utf-8"))})
                return rows
            except Exception as error:
                event.update({"status": "failed", "error_type": type(error).__name__})
                raise
            finally:
                event.update({"cpu_ns": time.process_time_ns() - start_cpu,
                              "wall_ns": time.perf_counter_ns() - start_wall})
                if model.client.emit is not None:
                    model.client.emit(event)

        view = (MemoryBoundaryView(
            emit=model.client.emit, policy=policy, capacity=model.client.capacity,
            capacity_error=CapacityExceeded, output_tokens=model.client.config.max_tokens,
            retrieve=retrieve, select=select if policy["attention_enabled"] else None)
            if policy is not None else None)
        if view is not None:
            views[user_id] = view
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
            memory_boundaries=view,
            memory_mcp=peer,
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
        if config.get("memory_boundaries", {}).get("enabled", False):
            start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
            receipt["operation_audit"] = operation_audit(
                [row.model_dump(mode="json") for row in messages], context, thread,
                views[scope.user_id].receipt_metadata if views[scope.user_id].scope == context
                else {})
            receipt["operation_audit_cost"] = {
                "cpu_ns": time.process_time_ns() - start_cpu,
                "wall_ns": time.perf_counter_ns() - start_wall,
                "logical_bytes": len(json.dumps(receipt["operation_audit"],
                                                ensure_ascii=False).encode("utf-8")),
                "additional_checkpoint_reads": 0,
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
    boundary_costs: dict[str, Any] = {}
    routes, deliveries = [], []
    mcp_costs: dict[str, Any] = {}
    for line in trace.read_text().splitlines() if trace.exists() else []:
        event = json.loads(line)
        name = event.get("event")
        if name == "langmem_mcp" and event.get("kind") in {"http", "resource_result"}:
            category = event["kind"]
            measured = mcp_costs.setdefault(category, {"calls": 0, "cpu_ns": 0, "wall_ns": 0})
            measured["calls"] += 1
            for key in ("cpu_ns", "wall_ns"):
                measured[key] += event[key]
            if category == "http":
                for key in ("request", "response"):
                    size = len(event[key + "_body"].encode("utf-8"))
                    measured[key + "_bytes"] = measured.get(key + "_bytes", 0) + size
            else:
                measured["logical_bytes"] = measured.get("logical_bytes", 0) + event[
                    "logical_bytes"]
        if name == "persistent_memory_checkpoint_read":
            for key in costs[name]:
                costs[name][key] += event[key]
        elif name == "memory_result_correction" and event.get("status") == "ENTERED":
            cost = costs["correction_checkpoint_write"]
            cost["calls"] += event["checkpoint_writes"]
            for key in ("logical_bytes", "cpu_ns", "wall_ns"):
                cost[key] += event[key]
        if name == "memory_boundary_retrieval" or (
            name == "persistent_memory_turn" and "operation_audit_cost" in event
        ):
            category = "retrieval" if name == "memory_boundary_retrieval" else "operation_audit"
            observed = event if category == "retrieval" else event["operation_audit_cost"]
            cost = boundary_costs.setdefault(category, {"calls": 0, "logical_bytes": 0,
                "unknown_logical_bytes": 0, "cpu_ns": 0, "wall_ns": 0})
            cost["calls"] += observed.get("calls", 1)
            for key in ("logical_bytes", "cpu_ns", "wall_ns"):
                if type(observed.get(key)) is int:
                    cost[key] += observed[key]
                elif key == "logical_bytes":
                    cost["unknown_logical_bytes"] += 1
        elif name == "memory_boundary_route":
            routes.append(event)
        elif name == "memory_boundary_delivery":
            deliveries.append(event)
    output = {**result, "v3_checkpoint_costs": costs}
    if mcp_costs:
        output["mcp_observation_costs"] = {"measurements": mcp_costs,
            "timing_scope": "inclusive transport/service; overlaps existing material/Store timing",
            "model_or_embedding_charge": "same RunBudget; never added again here",
            "physical_io": None}
    if boundary_costs or routes or deliveries:
        output.update({"boundary_observation_costs": boundary_costs,
            "boundary_routes": routes, "boundary_deliveries": deliveries,
            "boundary_route_timing": {"cpu_ns": sum(row["cpu_ns"] for row in routes),
                "wall_ns": sum(row["wall_ns"] for row in routes),
                "scope": "inclusive; do not add retrieval/selector timings again"}})
    return output


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
                with ExitStack() as controls:
                    policy = boundary_policy(config.get("memory_boundaries", {}))
                    control = (controls.enter_context(VLLMClient(
                        replace(runtime.model.client.config, max_tokens=2048),
                        emit=lambda event: original_emit({**event, "role": "state_control",
                            "control_stage": "memory_read_selection"})
                        if original_emit is not None else None,
                        budget=runtime.model.client.budget, capacity=runtime.model.client.capacity))
                        if policy is not None and policy["attention_enabled"] else None)
                    factory, callback = _adapters(runtime, bank, root, args.run, args.arm, config,
                                                   selector_client=control, mcp_stack=controls)
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
                    capture_interrupted_turn=config.get("memory_boundaries", {}).get(
                        "enabled", False),
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
