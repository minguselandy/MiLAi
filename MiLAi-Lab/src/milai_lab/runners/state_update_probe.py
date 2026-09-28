"""One-proposal, isolated State update diagnostics from frozen lawful prefixes."""

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
from typing import Any, Literal, cast

import httpx
from langchain_core.runnables import RunnableConfig

from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    LocalStateController,
)
from milai_lab.methods.local_state_attention.protocol import ControlResponseError
from milai_lab.methods.local_state_attention.writers import (
    WriterProposalContext,
    create_writer_tools,
    execute_writes,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.frozen_action_continuation import _history, _sha
from milai_lab.runners.langmem_application_runtime import open_application_runtime
from milai_lab.runners.local_state_attention import _accounting
from milai_lab.runners.writer_policy import _seed

CONTRACTS = {"replace", "patch_or_replace"}


def _cases_and_jobs(inputs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]],
                                                    list[dict[str, str]]]:
    if (inputs.get("kind") != "MILAI_LOCAL_UPDATE_INPUTS"
            or not isinstance(inputs.get("cases"), list)
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("STATE_UPDATE_INPUTS_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in inputs["cases"]:
        if not isinstance(case, dict):
            raise ValueError("STATE_UPDATE_CASE_INVALID")
        key, owner = case.get("case_id"), case.get("user_id")
        if (not isinstance(key, str) or not key or key in cases
                or not isinstance(owner, str) or not owner
                or not all(isinstance(case.get(name), list) for name in (
                    "states", "source_events", "pending_event_ids", "raw_history"))
                or not isinstance(case.get("current_task"), str)):
            raise ValueError("STATE_UPDATE_CASE_INVALID")
        history = _history(case["raw_history"])
        if not history or str(history[-1].content) != case["current_task"]:
            raise ValueError("STATE_UPDATE_CURRENT_TASK_CHANGED")
        state_ids = [row.get("id") for row in case["states"]]
        event_ids = [row.get("id") for row in case["source_events"]]
        if (not state_ids or any(not isinstance(item, str) or not item
                                  for item in [*state_ids, *event_ids])
                or len(set(state_ids)) != len(state_ids)
                or len(set(event_ids)) != len(event_ids)
                or not set(case["pending_event_ids"]) <= set(event_ids)
                or any(not isinstance(item, str)
                       for item in case["pending_event_ids"])):
            raise ValueError("STATE_UPDATE_PRESTATE_INVALID")
        for row in case["states"]:
            if (not isinstance(row, dict) or not all(name in row for name in (
                    "id", "title", "content", "needs", "evidence_refs", "revision",
                    "archived")) or type(row["revision"]) is not int):
                raise ValueError("STATE_UPDATE_STATE_INVALID")
        for row in case["source_events"]:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "kind", "actor", "tool_call_id", "content"}
                    or row["kind"] not in {"user", "tool"}):
                raise ValueError("STATE_UPDATE_EVENT_INVALID")
        cases[key] = case
    jobs: list[dict[str, str]] = []
    seen: set[str] = set()
    for job in inputs["jobs"]:
        if not isinstance(job, dict):
            raise ValueError("STATE_UPDATE_JOB_INVALID")
        job_id, case_id, contract = (job.get(name) for name in (
            "job_id", "case_id", "update_contract"))
        if (not isinstance(job_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in seen or case_id not in cases or contract not in CONTRACTS):
            raise ValueError("STATE_UPDATE_JOB_INVALID")
        seen.add(job_id)
        jobs.append({"job_id": job_id, "case_id": case_id,
                     "update_contract": contract})
    if not jobs:
        raise ValueError("STATE_UPDATE_NO_JOBS")
    return cases, jobs


def _identity(args: Any, config: dict[str, Any], jobs: list[dict[str, str]], *,
              lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_state_update_probe.py", lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "state_update_probe_v1", "run_id": args.run, "jobs": jobs,
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "inputs_path": str(args.inputs.resolve()), "inputs_sha256": _sha(args.inputs),
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "provider": {key: config[key] for key in ("host", "embedding", "capacity")},
        "control": config["control"], "budget_path": str(Path(
            config["budget_path"]).resolve()),
        "runtime_root": str(args.runtime_root.resolve()),
        "proposal_calls_per_job": 1,
        "state_update_contracts": {"replace": "revision_checked_full_content",
                                   "patch_or_replace": "revision_checked_literal_patch_or_full"},
        "rubric_read_by_runner": False, "host_business_calls": 0,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _, jobs = _cases_and_jobs(inputs)
    if (config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12
            or config["host"]["max_tokens"] != 4096
            or config["control"]["max_calls_per_message"] != 13
            or config["control"]["max_tokens"] != 2048):
        raise ValueError("STATE_UPDATE_CONFIG_INVALID")
    identity = _identity(args, config, jobs, lab_root=lab_root)
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.runtime_root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != identity:
            raise ValueError("STATE_UPDATE_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(jobs), "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _run_one(case: dict[str, Any], job: dict[str, str], config: dict[str, Any],
             runtime: Any, root: Path, run_id: str, arm_id: str) -> dict[str, Any]:
    scope = StateScope(run_id, arm_id, case["user_id"])
    bank = LocalStateBank(runtime.store, max_states=config["control"]["max_states"],
                          max_events=config["control"]["max_events"],
                          max_state_content_chars=4000,
                          max_total_content_chars=config["control"].get(
                              "aggregate_content_chars"))
    seed = _seed({**case, "memories": []}, runtime, bank, scope, root,
                 Path(config["budget_path"]))
    host = runtime.model.client
    original_emit = host.emit

    def control_emit(event: dict[str, Any]) -> None:
        if original_emit is not None:
            original_emit({**event, "role": "state_control",
                           "control_stage": CONTROL_STAGE.get()})

    control_config = replace(VLLMConfig(**config["host"]),
                             max_tokens=config["control"]["max_tokens"])
    with VLLMClient(control_config, emit=control_emit, budget=host.budget,
                    capacity=host.capacity) as control_client:
        controller = LocalStateController(
            bank, control_client, emit=control_emit,
            max_pending_batch=config["control"]["max_pending_batch"],
            capacity_path=root / "control-capacity.json",
            max_calls_per_message=config["control"]["max_calls_per_message"])
        toolset = create_writer_tools(
            bank, MEMORY_NAMESPACE, state_update_contract=cast(
                Literal["replace", "patch_or_replace"], job["update_contract"]))
        context = WriterProposalContext(
            scope, job["job_id"], case["current_task"],
            tuple(case["raw_history"]))
        run_config: RunnableConfig = {"configurable": {
            "foundation_run_id": run_id, "arm_id": arm_id,
            "user_id": scope.user_id, "workspace_id": scope.workspace_id}}
        try:
            proposal = controller.propose_writes(context, [toolset.manage_state])
        except (ControlResponseError, httpx.TimeoutException) as error:
            result: dict[str, Any] = {"status": "PROPOSAL_REJECTED",
                                      "reason": str(error), "proposal": None,
                                      "receipts": []}
        else:
            executed = execute_writes(
                toolset, proposal["calls"], config=run_config, scope=scope,
                batch_id=proposal["batch_id"], event_ids=set(proposal["event_ids"]))
            result = {"status": executed.status, "proposal": proposal,
                      "receipts": [row.model_dump(mode="json")
                                   for row in executed.receipts]}
    result.update({
        "job": job, "seed": seed, "states_after": bank.states(scope),
        "pending_event_ids": [row["id"] for row in bank.pending(scope)],
        "source_events_after": bank.events(scope),
        "store_stats": bank.store_stats(),
        "control_capacity": read_json(root / "control-capacity.json")
        if (root / "control-capacity.json").exists() else {},
        "trace_path": str((root / "trace.jsonl").resolve()),
        "budget_path": str(Path(config["budget_path"]).resolve()),
    })
    control_emit({"event": "lsa_store_stats", "operations": bank.store_stats()})
    result["accounting"] = _accounting(root, Path(config["budget_path"]))
    write_json(root / "result.json", result)
    return result


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
        raise ValueError("STATE_UPDATE_PREPARED_IDENTITY_CHANGED")
    index = next((i for i, item in enumerate(jobs) if item["job_id"] == args.job), None)
    if index is None:
        raise ValueError("STATE_UPDATE_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("STATE_UPDATE_JOB_ALREADY_ATTEMPTED")
    if any(item["job_id"] not in manifest["attempts"] for item in jobs[:index]):
        raise ValueError("STATE_UPDATE_JOB_OUT_OF_ORDER")
    job = jobs[index]
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    root = args.runtime_root / "jobs" / args.job
    run_id, arm_id = args.run + ":" + args.job, job["update_contract"]
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
