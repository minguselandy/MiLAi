"""Resume a frozen JSON-action Host reply at the ordinary LangGraph tools node."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_openai_messages,
)
from langchain_core.utils.function_calling import convert_to_openai_tool
from langmem import create_search_memory_tool  # type: ignore[import-untyped]

from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.tools import (
    BUSINESS_NAMES,
    BUSINESS_SCHEMAS,
    _business_tools,
    native_business_tools,
)
from milai_lab.application.world import ApplicationWorld
from milai_lab.baselines.langmem_agent import (
    MEMORY_NAMESPACE,
    build_agent,
)
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.memory.strict_tools import create_strict_manage_memory_tool
from milai_lab.methods.local_state_attention.read_probe import first_action
from milai_lab.providers.contextual_vllm import generation_schema
from milai_lab.providers.langmem_chat import (
    _action_prompt,
    _action_schema,
    _json_action_history,
)
from milai_lab.runners.langmem_application_runtime import (
    ApplicationRuntime,
    open_application_runtime,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog() -> list[dict[str, Any]]:
    # The executable graph independently verifies this catalog before dispatch.
    functions = {row["function"]["name"]: lambda *_args, **_kwargs: ""
                 for row in BUSINESS_SCHEMAS}
    tools = [create_strict_manage_memory_tool(MEMORY_NAMESPACE),
             create_search_memory_tool(namespace=MEMORY_NAMESPACE),
             *native_business_tools(None, BUSINESS_SCHEMAS, functions)]
    return [convert_to_openai_tool(tool) for tool in tools]


def _history(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    index = 0
    while index < len(messages):
        row = messages[index]
        role, content = row.get("role"), row.get("content")
        if not isinstance(content, str):
            raise ValueError("FROZEN_HISTORY_CONTENT_INVALID")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            upcoming = index + 1
            while upcoming < len(messages) and messages[upcoming].get("role") == "tool":
                upcoming += 1
            if upcoming == index + 1:
                result.append(AIMessage(content=content))
            else:
                try:
                    action = json.loads(content)
                    calls = action["calls"]
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError("FROZEN_HISTORY_ACTION_INVALID") from error
                tool_rows = messages[index + 1:upcoming]
                if not isinstance(calls, list) or len(calls) != len(tool_rows):
                    raise ValueError("FROZEN_HISTORY_TOOL_PAIRING_INVALID")
                first_id = tool_rows[0].get("tool_call_id")
                if not isinstance(first_id, str) or not first_id.endswith(":tool:0"):
                    raise ValueError("FROZEN_HISTORY_TOOL_ID_INVALID")
                generation_id = first_id.removesuffix(":tool:0")
                parsed_calls = []
                for slot, (call, tool_row) in enumerate(zip(calls, tool_rows, strict=True)):
                    if (not isinstance(call, dict)
                            or tool_row.get("name") != call.get("name")
                            or tool_row.get("tool_call_id") != f"{generation_id}:tool:{slot}"
                            or not isinstance(call.get("arguments"), dict)
                            or not isinstance(tool_row.get("content"), str)):
                        raise ValueError("FROZEN_HISTORY_TOOL_PAIRING_INVALID")
                    parsed_calls.append({"name": call["name"],
                                         "args": call["arguments"],
                                         "id": tool_row["tool_call_id"]})
                result.append(AIMessage(id=generation_id, content="",
                                        tool_calls=parsed_calls))
                result.extend(ToolMessage(
                    content=tool_row["content"], name=tool_row["name"],
                    tool_call_id=tool_row["tool_call_id"]) for tool_row in tool_rows)
                index = upcoming - 1
        else:
            raise ValueError("FROZEN_HISTORY_ROLE_INVALID")
        index += 1
    if not result or not isinstance(result[-1], HumanMessage):
        raise ValueError("FROZEN_CURRENT_USER_MISSING")
    return result


def validate_frozen_job(result: dict[str, Any], config: dict[str, Any]
                        ) -> tuple[str, list[BaseMessage], AIMessage]:
    """Prove the frozen first request is exactly the current graph's JSON-action wire."""
    request, receipt = result["host_request"], result["host_receipt"]
    catalog = _catalog()
    schema = {"type": "json_schema", "json_schema": {
        "name": "langmem_json_action_v1", "strict": True,
        "schema": _action_schema(catalog, generation_only=True)}}
    expected = {"model": config["host"]["model"],
                "temperature": config["host"]["temperature"],
                "max_tokens": config["host"]["max_tokens"],
                "chat_template_kwargs": {"enable_thinking":
                    config["capacity"]["enable_thinking"]},
                "response_format": generation_schema(schema)}
    if (config.get("memory_contract") != "strict"
            or config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12
            or set(request) != {*expected, "messages"}
            or any(request[key] != value for key, value in expected.items())):
        raise ValueError("FROZEN_HOST_CONTRACT_CHANGED")
    wire = request["messages"]
    if not isinstance(wire, list) or not wire or wire[0].get("role") != "system":
        raise ValueError("FROZEN_SYSTEM_MISSING")
    prefix = _action_prompt(catalog) + "\n"
    original_system = wire[0].get("content")
    if not isinstance(original_system, str) or not original_system.startswith(prefix):
        raise ValueError("FROZEN_CATALOG_PREFIX_CHANGED")
    system_prompt = original_system[len(prefix):]
    messages = _history(wire[1:])
    rebuilt = convert_to_openai_messages([SystemMessage(content=system_prompt), *messages])
    if not isinstance(rebuilt, list):
        raise TypeError("FROZEN_REBUILT_WIRE_INVALID")
    rebuilt = _json_action_history(rebuilt)
    rebuilt[0]["content"] = prefix + str(rebuilt[0]["content"])
    if rebuilt != wire:
        raise ValueError("FROZEN_REQUEST_PREFIX_CHANGED")
    action = first_action(receipt, request)
    if action != result["first_action"] or not isinstance(action.get("calls"), list):
        raise ValueError("FROZEN_FIRST_ACTION_CHANGED_OR_NOT_A_CALL")
    generation_id = receipt.get("id")
    if not isinstance(generation_id, str) or not generation_id:
        raise ValueError("FROZEN_FIRST_GENERATION_ID_MISSING")
    calls = [{"name": call["name"], "args": call["arguments"],
              "id": f"{generation_id}:tool:{index}"}
             for index, call in enumerate(action["calls"])]
    if len(calls) != 1:
        raise ValueError("FROZEN_FIRST_ACTION_CARDINALITY_UNSUPPORTED")
    usage = receipt.get("usage") or {}
    prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
    usage_metadata = ({"input_tokens": prompt_tokens, "output_tokens": completion_tokens,
                       "total_tokens": prompt_tokens + completion_tokens}
                      if type(prompt_tokens) is int and type(completion_tokens) is int else None)
    frozen_ai = AIMessage(
        id=generation_id, content="", tool_calls=calls, usage_metadata=usage_metadata,
        response_metadata={"finish_reason": receipt["choices"][0]["finish_reason"],
                           "model": receipt.get("model")})
    return system_prompt, messages, frozen_ai


def _validate_prestates(prestates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (prestates.get("kind") != "MILAI_FROZEN_ACTION_PRESTATES"
            or not isinstance(prestates.get("cases"), list)):
        raise ValueError("FROZEN_PRESTATES_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in prestates["cases"]:
        case_id, owner = case.get("case_id"), case.get("user_id")
        if (not isinstance(case_id, str) or not case_id or case_id in cases
                or not isinstance(owner, str) or not owner
                or type(case.get("initial_label_available")) is not bool
                or not isinstance(case.get("memory_records"), list)):
            raise ValueError("FROZEN_PRESTATE_CASE_INVALID")
        world = case.get("business_world")
        if (world != "empty reservations and attempts"
                and world != {"reservations": [], "attempts": []}):
            raise ValueError("FROZEN_PRESTATE_WORLD_UNSUPPORTED")
        seen: set[tuple[str, str]] = set()
        for row in case["memory_records"]:
            identity = (row.get("user_id"), row.get("key"))
            if (any(not isinstance(part, str) or not part for part in identity)
                    or identity in seen or not isinstance(row.get("value"), dict)):
                raise ValueError("FROZEN_PRESTATE_MEMORY_INVALID")
            seen.add(identity)
        cases[case_id] = case
    return cases


def _memory_snapshot(store: Any, run_id: str, arm_id: str,
                     owners: set[str]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for owner in sorted(owners):
        namespace = ("langmem", run_id, arm_id, owner)
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = store.search(namespace, limit=64, offset=offset)
            rows.extend({"key": row.key, "value": row.value}
                        for row in page if tuple(row.namespace) == namespace)
            if len(page) < 64:
                break
            offset += len(page)
        output[owner] = sorted(rows, key=lambda row: row["key"])
    return output


def continue_job(result: dict[str, Any], prestate: dict[str, Any],
                 config: dict[str, Any], runtime: ApplicationRuntime,
                 root: Path, run_id: str, arm_id: str) -> dict[str, Any]:
    """Seed real prior memory, then resume ToolNode from the frozen first AI reply."""
    system_prompt, history, first_ai = validate_frozen_job(result, config)
    owner = prestate["user_id"]
    scope = FoundationScope(run_id, arm_id, owner, "application:frozen:" + result["job"]["job_id"])
    owners = {owner}
    budget_path = Path(config["budget_path"])
    budget_before_seed = read_json(budget_path) if budget_path.exists() else None
    for row in prestate["memory_records"]:
        record_owner, key, value = row["user_id"], row["key"], row["value"]
        if (not isinstance(record_owner, str) or not record_owner
                or not isinstance(key, str) or not key or not isinstance(value, dict)):
            raise ValueError("FROZEN_PRESTATE_MEMORY_INVALID")
        owners.add(record_owner)
    if any(_memory_snapshot(runtime.store, run_id, arm_id, owners).values()):
        raise ValueError("FROZEN_PRESTATE_NAMESPACE_DIRTY")
    for row in prestate["memory_records"]:
        record_owner, key, value = row["user_id"], row["key"], row["value"]
        namespace = ("langmem", run_id, arm_id, record_owner)
        runtime.store.put(namespace, key, value)
    seeded = _memory_snapshot(runtime.store, run_id, arm_id, owners)
    budget_after_seed = read_json(budget_path) if budget_path.exists() else None
    world = ApplicationWorld(root / "business-world.sqlite",
                             prestate["initial_label_available"])
    journal = BusinessActionJournal(root / "business-journal.json", BUSINESS_NAMES)
    try:
        agent = build_agent(
            runtime.model, runtime.store, runtime.checkpointer,
            _business_tools(world, owner), business_call_wrapper=journal,
            observer=runtime.observer, system_prompt=system_prompt,
            memory_contract="strict")
        tools = agent.nodes["tools"].bound.tools_by_name
        actual_catalog = [convert_to_openai_tool(tool) for tool in tools.values()]
        if actual_catalog != _catalog():
            raise ValueError("FROZEN_ACTUAL_TOOL_CATALOG_CHANGED")
        graph_config = scope.config()
        thread_id = graph_config["configurable"]["thread_id"]
        current_index = sum(isinstance(message, HumanMessage) for message in history) - 1
        message_key = f"{thread_id}:{current_index}"
        capacity_path = runtime.model.capacity_path
        if capacity_path is None or capacity_path.exists():
            raise ValueError("FROZEN_CAPACITY_STATE_NOT_EMPTY")
        write_json(capacity_path, {message_key: 1})
        runtime.model.begin_public_message(message_key, checkpoint_calls=1)
        if runtime.observer is not None:
            runtime.observer.begin_public_message(scope, current_index,
                                                  str(history[-1].content))
        updated = agent.update_state(graph_config,
                                     {"messages": [*history, first_ai]}, as_node="agent")
        before = agent.get_state(updated)
        if before.next != ("tools",):
            raise ValueError("FROZEN_GRAPH_NOT_AT_TOOLS")
        write_json(root / "frozen-first-response.json", {
            "host_request": result["host_request"],
            "host_receipt": result["host_receipt"],
            "receipt_canonical_json_sha256": hashlib.sha256(json.dumps(
                result["host_receipt"], sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode()).hexdigest(),
            "first_action": result["first_action"],
            "mapped_ai_message": first_ai.model_dump(mode="json"),
            "message_key": message_key, "checkpoint_next": list(before.next)})
        try:
            resumed = agent.invoke(None, config=updated)
            status, failure, failure_error = "COMPLETED", None, None
        except BaseException as error:
            status, failure = "FAILED", {"type": type(error).__name__,
                                          "message": str(error)}
            failure_error = error
            resumed = agent.get_state(graph_config).values
        messages = resumed.get("messages", [])
        output = {
            "status": status, "exception": failure,
            "job": result["job"], "scope": {"run_id": run_id, "arm_id": arm_id,
                "user_id": owner, "thread_id": thread_id,
                "public_index": current_index},
            "first_generation_id": first_ai.id,
            "first_tool_call_ids": [call["id"] for call in first_ai.tool_calls],
            "first_response_path": str((root / "frozen-first-response.json").resolve()),
            "checkpoint_next": list(agent.get_state(graph_config).next),
            "messages": [message.model_dump(mode="json") for message in messages],
            "business_calls": journal.calls_for_thread(thread_id),
            "world": world.snapshot(), "memory_before_action": seeded,
            "memory_after": _memory_snapshot(runtime.store, run_id, arm_id, owners),
            "seed_budget_before": budget_before_seed,
            "seed_budget_after": budget_after_seed,
            "capacity": read_json(capacity_path),
            "trace_path": str((root / "trace.jsonl").resolve()),
            "checkpoint_path": str((root / "checkpoints.sqlite").resolve()),
            "budget_path": str(Path(config["budget_path"]).resolve()),
        }
        write_json(root / "result.json", output)
        if failure_error is not None:
            raise failure_error
        return output
    finally:
        world.close()


def identity(args: Any, config: dict[str, Any], inputs: dict[str, Any],
             prestates: dict[str, Any], *, lab_root: Path) -> dict[str, Any]:
    source_paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
                    lab_root / "tools/run_frozen_action_continuation.py",
                    lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "frozen_action_continuation", "run_id": args.run,
        "arm_id": args.arm, "job_scope_rule": "run_id:job_id with fixed arm_id",
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path)
                          for path in source_paths},
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "inputs_path": str(args.inputs.resolve()), "inputs_sha256": _sha(args.inputs),
        "first_run_root": str(args.first_run_root.resolve()),
        "first_jobs_sha256": {job["job_id"]: _sha(
            args.first_run_root / "jobs" / f"{job['job_id']}.json")
            for job in inputs["jobs"]},
        "prestates_path": str(args.prestates.resolve()),
        "prestates_sha256": _sha(args.prestates), "jobs": inputs["jobs"],
        "config": config, "prestate_case_ids": sorted(
            case["case_id"] for case in prestates["cases"]),
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "budget_path": str(Path(config["budget_path"]).resolve()),
        "runtime_root": str(args.runtime_root.resolve()),
        "rubric_read_by_runner": False,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs, prestates = (read_json(path) for path in
                                 (args.config, args.inputs, args.prestates))
    if (inputs.get("kind") != "LSA_READ_PROBE_INPUTS"
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("FROZEN_INPUTS_INVALID")
    cases = _validate_prestates(prestates)
    seen: set[str] = set()
    for job in inputs["jobs"]:
        job_id = job["job_id"]
        if (not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in seen or job["case_id"] not in cases):
            raise ValueError("FROZEN_JOB_INVALID")
        seen.add(job_id)
        result = read_json(args.first_run_root / "jobs" / f"{job_id}.json")
        if (result.get("job") != job or result.get("case_id") != job["case_id"]
                or result.get("status") != "COMPLETED_FIRST_REQUEST_ONLY"
                or result.get("business_tools_executed") != 0):
            raise ValueError("FROZEN_FIRST_RESULT_CHANGED")
        validate_frozen_job(result, config)
    locked = identity(args, config, inputs, prestates, lab_root=lab_root)
    root = args.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != locked:
            raise ValueError("FROZEN_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": locked,
                                   "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(inputs["jobs"]),
               "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   locked, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def run_job(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs, prestates = (read_json(path) for path in
                                 (args.config, args.inputs, args.prestates))
    cases = _validate_prestates(prestates)
    locked = identity(args, config, inputs, prestates, lab_root=lab_root)
    manifest_path = args.runtime_root / "run_manifest.json"
    manifest = read_json(manifest_path)
    prepared = read_json(args.prepared)
    expected = hashlib.sha256(json.dumps(
        locked, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if manifest["identity"] != locked or prepared["identity_sha256"] != expected:
        raise ValueError("FROZEN_PREPARED_IDENTITY_CHANGED")
    jobs = inputs["jobs"]
    index = next((i for i, job in enumerate(jobs) if job["job_id"] == args.job), None)
    if index is None:
        raise ValueError("FROZEN_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("FROZEN_JOB_ALREADY_ATTEMPTED")
    if any(job["job_id"] not in manifest["attempts"] for job in jobs[:index]):
        raise ValueError("FROZEN_JOB_OUT_OF_ORDER")
    job = jobs[index]
    prestate = cases[job["case_id"]]
    source_path = args.first_run_root / "jobs" / f"{args.job}.json"
    result = read_json(source_path)
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job,
                                      "first_result_sha256": _sha(source_path)}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    job_root = args.runtime_root / "jobs" / args.job
    run_id, arm_id = args.run + ":" + args.job, args.arm
    try:
        job_root.mkdir(parents=True, exist_ok=False)
        with open_application_runtime(config, run_id, arm_id, job_root, args.stage,
                                      enable_projection=False) as runtime:
            output = continue_job(result, prestate, config, runtime,
                                  job_root, run_id, arm_id)
        manifest["attempts"][args.job]["status"] = "COMPLETED"
        manifest["outputs"][args.job] = str((job_root / "result.json").resolve())
        manifest["status"] = ("TERMINAL" if len(manifest["attempts"]) == len(jobs)
                              else "RUNNING")
        return output
    except BaseException as error:
        manifest["attempts"][args.job].update({
            "status": "FAILED", "exception": {"type": type(error).__name__,
                                                "message": str(error)}})
        manifest["status"] = "FAILED"
        raise
    finally:
        write_json(manifest_path, manifest)
