"""Complete read-only ReAct turns over one frozen, scoped State bank."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE, FoundationScope, build_agent
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.protocol import state_directory
from milai_lab.methods.local_state_attention.read_probe import (
    enhance_query,
    query_top_two,
    render_view,
    select_directory_a,
    sorted_states,
)
from milai_lab.methods.local_state_attention.writers import create_writer_tools
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.frozen_action_continuation import _history, _sha
from milai_lab.runners.langmem_application_runtime import (
    ApplicationRuntime,
    open_application_runtime,
)
from milai_lab.runners.local_state_attention import _accounting
from milai_lab.runners.writer_policy import _seed

ARMS = {"all", "query", "query_enhanced", "a_selector", "full_history"}
SYSTEM_PROMPT = (
    "Answer the current user's question using the lawful conversation and available "
    "read-only tools. Local States are model-generated working estimates; current user "
    "messages and actual tool results are observations. The directory identifies scoped "
    "States available for exact reads. A preselected view is optional context, not a claim "
    "that a State was read with a tool."
)
DIRECTORY_HEADER = "[Available scoped State directory (id/title/needs/revision):]"


def _cases_and_jobs(inputs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]],
                                                    list[dict[str, str]]]:
    if (inputs.get("kind") != "MILAI_FIXED_READ_INPUTS"
            or not isinstance(inputs.get("cases"), list)
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("FIXED_READ_INPUTS_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in inputs["cases"]:
        if not isinstance(case, dict):
            raise ValueError("FIXED_READ_CASE_INVALID")
        key, owner = case.get("case_id"), case.get("user_id")
        if (not isinstance(key, str) or not key or key in cases
                or not isinstance(owner, str) or not owner
                or not isinstance(case.get("current_task"), str)
                or not isinstance(case.get("raw_history"), list)
                or not isinstance(case.get("states"), list)
                or case.get("memories") != [] or case.get("source_events") != []
                or case.get("pending_event_ids") != []):
            raise ValueError("FIXED_READ_CASE_INVALID")
        history = _history(case["raw_history"])
        if str(history[-1].content) != case["current_task"]:
            raise ValueError("FIXED_READ_CURRENT_TASK_CHANGED")
        for row in case["states"]:
            if (not isinstance(row, dict)
                    or not all(field in row for field in (
                        "id", "title", "content", "needs", "evidence_refs",
                        "revision", "archived"))
                    or type(row["revision"]) is not int or row["revision"] < 1
                    or not isinstance(row["content"], str)):
                raise ValueError("FIXED_READ_STATE_INVALID")
        sorted_states(case["states"])
        cases[key] = case
    jobs: list[dict[str, str]] = []
    seen: set[str] = set()
    for job in inputs["jobs"]:
        if not isinstance(job, dict):
            raise ValueError("FIXED_READ_JOB_INVALID")
        job_id, case_id, arm = (job.get(field) for field in ("job_id", "case_id", "arm"))
        if (not isinstance(job_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in seen or case_id not in cases or arm not in ARMS):
            raise ValueError("FIXED_READ_JOB_INVALID")
        seen.add(job_id)
        jobs.append({"job_id": job_id, "case_id": case_id, "arm": arm})
    if not jobs:
        raise ValueError("FIXED_READ_NO_JOBS")
    return cases, jobs


def _tool_catalog() -> list[dict[str, Any]]:
    bank = LocalStateBank(InMemoryStore())
    toolset = create_writer_tools(bank, MEMORY_NAMESPACE)
    return [convert_to_openai_tool(tool)["function"]
            for tool in (toolset.search_memory, toolset.read_record)]


def _identity(args: Any, config: dict[str, Any], inputs: dict[str, Any], *,
              lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_fixed_state_read.py", lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg", "jsonschema"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "fixed_state_read_v2", "run_id": args.run,
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "inputs_path": str(args.inputs.resolve()), "inputs_sha256": _sha(args.inputs),
        "jobs": inputs["jobs"], "config": config,
        "scope_rule": "run_id:job_id / arm / owner; new Store and checkpoint per job",
        "fixed_bank_no_maintenance": True, "ordinary_memory_fixture": "empty_indexed",
        "full_history_policy": "same_inline_history_directory_and_READ_no_preselected_body",
        "system_prompt": SYSTEM_PROMPT, "directory_header": DIRECTORY_HEADER,
        "read_only_tool_catalog": _tool_catalog(),
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "budget_path": str(Path(config["budget_path"]).resolve()),
        "runtime_root": str(args.runtime_root.resolve()), "rubric_read_by_runner": False,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _cases_and_jobs(inputs)
    if (config.get("memory_contract") != "strict"
            or config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12
            or config["host"]["max_tokens"] != 4096
            or config["control"]["max_calls_per_message"] != 13
            or config["control"]["max_tokens"] != 2048
            or config["host"]["temperature"] != 0
            or config["host"]["enable_thinking"] is not False
            or config["capacity"]["enable_thinking"] is not False):
        raise ValueError("FIXED_READ_CONFIG_INVALID")
    identity = _identity(args, config, inputs, lab_root=lab_root)
    root = args.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != identity:
            raise ValueError("FIXED_READ_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(inputs["jobs"]), "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _prompt(states: list[dict[str, Any]], selected: list[dict[str, Any]]) -> str:
    directory = state_directory(sorted_states(states))
    parts = [SYSTEM_PROMPT, DIRECTORY_HEADER,
             json.dumps(directory, ensure_ascii=False)]
    if selected:
        parts.append(render_view(selected))
    return "\n".join(parts)


def _run_one(case: dict[str, Any], job: dict[str, str], config: dict[str, Any],
             runtime: ApplicationRuntime, root: Path, run_id: str,
             arm_id: str) -> dict[str, Any]:
    owner = case["user_id"]
    state_scope = StateScope(run_id, arm_id, owner)
    bank = LocalStateBank(runtime.store, max_states=config["control"]["max_states"],
                          max_events=config["control"]["max_events"],
                          max_total_content_chars=config["control"].get(
                              "aggregate_content_chars"))
    seed = _seed(case, runtime, bank, state_scope, root, Path(config["budget_path"]))
    states = bank.states(state_scope)
    expected = sorted_states(case["states"])
    if states != expected:
        raise ValueError("FIXED_READ_SEEDED_STATE_CHANGED")
    toolset = create_writer_tools(bank, MEMORY_NAMESPACE)
    host = runtime.model.client
    original_emit = host.emit

    def emit(role: str, event: dict[str, Any]) -> None:
        if original_emit is not None:
            original_emit({**event, "role": role, "job_id": job["job_id"]})

    host.emit = lambda event: emit("task_host", event)
    control_config = replace(VLLMConfig(**config["host"]),
                             max_tokens=config["control"]["max_tokens"])
    embed_config = VLLMConfig(base_url=config["embedding"]["base_url"],
                              model=config["embedding"]["model"],
                              timeout=config["embedding"].get("timeout", 180))
    history = _history(case["raw_history"])
    scope = FoundationScope(run_id, arm_id, owner, "application:fixed-read:" + job["job_id"])
    graph_config = scope.config()
    public_index = sum(isinstance(row, HumanMessage) for row in history) - 1
    message_key = f"{graph_config['configurable']['thread_id']}:{public_index}"
    selected: list[dict[str, Any]] = []
    anchors: list[str] = []
    retrieval_query = case["current_task"]
    if job["arm"] == "all":
        selected = states
    elif job["arm"] in {"query_enhanced", "a_selector"}:
        with VLLMClient(control_config, emit=lambda event: emit(
                "query_enhancer" if job["arm"] == "query_enhanced" else "read_selector",
                event), budget=host.budget, capacity=host.capacity) as selector:
            capacity_path = root / "control-capacity.json"
            count = read_json(capacity_path) if capacity_path.exists() else {}
            if count.get(message_key, 0) >= config["control"]["max_calls_per_message"]:
                raise ValueError("FIXED_READ_CONTROL_CAPACITY_EXCEEDED")
            count[message_key] = count.get(message_key, 0) + 1
            write_json(capacity_path, count)
            if job["arm"] == "query_enhanced":
                retrieval_query, anchors = enhance_query(states, retrieval_query, selector)
            else:
                selected = select_directory_a(states, retrieval_query, selector)
    if job["arm"] in {"query", "query_enhanced"}:
        with VLLMClient(embed_config, emit=lambda event: emit("query_embedding", event),
                        budget=host.budget) as embed:
            selected = query_top_two(states, retrieval_query, embed, embed_config.model)
    prompt = _prompt(states, selected)
    agent = build_agent(runtime.model, runtime.store, runtime.checkpointer,
                        observer=runtime.observer, system_prompt=prompt,
                        memory_contract="strict", writer_tools=toolset,
                        writer_tool_mode="read_only")
    actual_tools = agent.nodes["tools"].bound.tools_by_name
    if set(actual_tools) != {"search_memory", "read_record"} or [
        convert_to_openai_tool(actual_tools[name])["function"]
        for name in ("search_memory", "read_record")] != _tool_catalog():
        raise ValueError("FIXED_READ_TOOL_CATALOG_CHANGED")
    runtime.model.begin_public_message(message_key)
    if runtime.observer is not None:
        runtime.observer.begin_public_message(scope, public_index, case["current_task"])
    failure: BaseException | None = None
    try:
        result = agent.invoke({"messages": history}, config=graph_config)
        messages: list[BaseMessage] = result["messages"]
        if not messages or not isinstance(messages[-1], AIMessage) or messages[-1].tool_calls:
            raise ValueError("FIXED_READ_NO_FINAL_ANSWER")
        status = "COMPLETED"
    except BaseException as error:
        failure = error
        status = "FAILED"
        messages = agent.get_state(graph_config).values.get("messages", [])
    after = bank.states(state_scope)
    if after != states:
        raise ValueError("FIXED_READ_STATE_MUTATED")
    memory_after = runtime.store.search(("langmem", run_id, arm_id, owner), limit=1)
    if memory_after:
        raise ValueError("FIXED_READ_ORDINARY_MEMORY_MUTATED")
    readbacks = [row.model_dump(mode="json") for row in messages
                 if isinstance(row, ToolMessage)]
    output = {
        "status": status,
        "exception": ({"type": type(failure).__name__, "message": str(failure)}
                      if failure is not None else None),
        "job": job, "scope": {"run_id": run_id, "arm_id": arm_id,
                               "user_id": owner, "thread_id": graph_config["configurable"][
                                   "thread_id"], "public_index": public_index},
        "seed": seed, "states_before": states, "states_after": after,
        "ordinary_memory_before": [], "ordinary_memory_after": [],
        "source_events_before": [], "source_events_after": bank.events(state_scope),
        "selected_state_ids": [row["id"] for row in selected],
        "selected_states": selected, "entity_anchors": anchors,
        "retrieval_query": retrieval_query, "system_prompt": prompt,
        "read_only_tool_catalog": _tool_catalog(),
        "messages": [row.model_dump(mode="json") for row in messages],
        "readbacks": readbacks,
        "answer": (str(messages[-1].content) if status == "COMPLETED" else None),
        "host_capacity": (read_json(root / "message-capacity.json")
                          if (root / "message-capacity.json").exists() else {}),
        "control_capacity": (read_json(root / "control-capacity.json")
                             if (root / "control-capacity.json").exists() else {}),
        "state_store_stats": bank.store_stats(),
        "trace_path": str((root / "trace.jsonl").resolve()),
        "checkpoint_path": str((root / "checkpoints.sqlite").resolve()),
        "budget_path": str(Path(config["budget_path"]).resolve()),
    }
    emit("state_store", {"event": "lsa_store_stats", "operations": bank.store_stats()})
    output["accounting"] = _accounting(root, Path(config["budget_path"]))
    write_json(root / "result.json", output)
    if failure is not None:
        raise failure
    return output


def run_job(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    cases, _ = _cases_and_jobs(inputs)
    identity = _identity(args, config, inputs, lab_root=lab_root)
    root = args.runtime_root
    manifest_path = root / "run_manifest.json"
    manifest = read_json(manifest_path)
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()
    if (manifest["identity"] != identity
            or read_json(args.prepared)["identity_sha256"] != expected):
        raise ValueError("FIXED_READ_PREPARED_IDENTITY_CHANGED")
    jobs = inputs["jobs"]
    index = next((position for position, job in enumerate(jobs)
                  if job["job_id"] == args.job), None)
    if index is None:
        raise ValueError("FIXED_READ_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("FIXED_READ_JOB_ALREADY_ATTEMPTED")
    if any(job["job_id"] not in manifest["attempts"] for job in jobs[:index]):
        raise ValueError("FIXED_READ_JOB_OUT_OF_ORDER")
    job = jobs[index]
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    job_root = root / "jobs" / args.job
    run_id, arm_id = args.run + ":" + args.job, job["arm"]
    try:
        job_root.mkdir(parents=True, exist_ok=False)
        with open_application_runtime(config, run_id, arm_id, job_root, args.stage,
                                      enable_projection=False) as runtime:
            output = _run_one(cases[job["case_id"]], job, config, runtime,
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
