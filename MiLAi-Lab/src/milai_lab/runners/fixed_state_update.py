"""One shared maintenance proposal over fixed, lawful State update candidates."""

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

import httpx

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    LocalStateController,
    request_role,
)
from milai_lab.methods.local_state_attention.protocol import (
    READ_SELECTOR_PROMPT,
    UPDATE_SELECTOR_PROMPT,
    ControlResponseError,
    control_prompt,
    event_view,
    state_directory,
)
from milai_lab.methods.local_state_attention.read_probe import (
    select_directory_a,
    select_directory_u,
    sorted_states,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.frozen_action_continuation import _sha
from milai_lab.runners.langmem_application_runtime import open_application_runtime
from milai_lab.runners.local_state_attention import _accounting
from milai_lab.runners.writer_policy import _seed

ARMS = {"all", "u_selector", "u_equals_a", "oracle_u"}
MAINTENANCE_PROMPT = control_prompt("local", local_granularity=True,
                                    maintenance=True, candidate_only=True)


def _cases_and_jobs(inputs: dict[str, Any]) -> tuple[dict[str, dict[str, Any]],
                                                    list[dict[str, Any]]]:
    if (inputs.get("kind") != "MILAI_FIXED_UPDATE_INPUTS"
            or not isinstance(inputs.get("cases"), list)
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("FIXED_UPDATE_INPUTS_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in inputs["cases"]:
        if not isinstance(case, dict):
            raise ValueError("FIXED_UPDATE_CASE_INVALID")
        key, owner = case.get("case_id"), case.get("user_id")
        if (not isinstance(key, str) or not key or key in cases
                or not isinstance(owner, str) or not owner
                or not isinstance(case.get("query"), str)
                or not all(isinstance(case.get(name), list) for name in (
                    "states", "source_events", "pending_event_ids"))
                or case.get("memories") != []):
            raise ValueError("FIXED_UPDATE_CASE_INVALID")
        for row in case["states"]:
            if (not isinstance(row, dict) or not all(name in row for name in (
                    "id", "title", "content", "needs", "evidence_refs", "revision",
                    "archived")) or type(row["revision"]) is not int
                    or row["revision"] < 1 or not isinstance(row["content"], str)):
                raise ValueError("FIXED_UPDATE_STATE_INVALID")
        sorted_states(case["states"])
        for row in case["source_events"]:
            if (not isinstance(row, dict) or set(row) != {
                    "id", "kind", "actor", "tool_call_id", "content"}
                    or not isinstance(row["id"], str) or not row["id"]
                    or row["kind"] not in {"user", "tool"}
                    or not isinstance(row["content"], str)):
                raise ValueError("FIXED_UPDATE_EVENT_INVALID")
        ids = [row["id"] for row in case["source_events"]]
        pending = case["pending_event_ids"]
        if (len(set(ids)) != len(ids) or not pending
                or any(not isinstance(key, str) for key in pending)
                or len(set(pending)) != len(pending) or not set(pending) <= set(ids)):
            raise ValueError("FIXED_UPDATE_PENDING_INVALID")
        cases[key] = case
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in inputs["jobs"]:
        if not isinstance(job, dict):
            raise ValueError("FIXED_UPDATE_JOB_INVALID")
        job_id, case_id, arm = (job.get(key) for key in ("job_id", "case_id", "arm"))
        if (not isinstance(job_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in seen or case_id not in cases or arm not in ARMS):
            raise ValueError("FIXED_UPDATE_JOB_INVALID")
        job_row: dict[str, Any] = {"job_id": job_id, "case_id": case_id, "arm": arm}
        if arm == "oracle_u":
            mask = job.get("oracle_update_ids")
            if (job.get("diagnostic_only") is not True or not isinstance(mask, list)
                    or any(not isinstance(key, str) for key in mask)
                    or len(set(mask)) != len(mask)
                    or not set(mask) <= {state["id"] for state in cases[case_id]["states"]}):
                raise ValueError("FIXED_UPDATE_ORACLE_MASK_INVALID")
            job_row.update({"diagnostic_only": True, "oracle_update_ids": mask})
        elif "oracle_update_ids" in job:
            raise ValueError("FIXED_UPDATE_ORACLE_MASK_OUTSIDE_DIAGNOSTIC")
        seen.add(job_id)
        jobs.append(job_row)
    if not jobs:
        raise ValueError("FIXED_UPDATE_NO_JOBS")
    return cases, jobs


def _identity(args: Any, config: dict[str, Any], jobs: list[dict[str, Any]], *,
              lab_root: Path) -> dict[str, Any]:
    paths = [*sorted((lab_root / "src/milai_lab").rglob("*.py")),
             lab_root / "tools/run_fixed_state_update.py", lab_root / "pyproject.toml"]
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg", "jsonschema"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "fixed_state_update_v2", "run_id": args.run, "jobs": jobs,
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": {str(path.relative_to(lab_root)): _sha(path) for path in paths},
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "inputs_path": str(args.inputs.resolve()), "inputs_sha256": _sha(args.inputs),
        "config": config, "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "runtime_root": str(args.runtime_root.resolve()),
        "budget_path": str(Path(config["budget_path"]).resolve()),
        "scope_rule": "run_id:job_id / arm / owner; one attempt per job",
        "update_selector_prompt": UPDATE_SELECTOR_PROMPT,
        "read_selector_prompt": READ_SELECTOR_PROMPT,
        "maintenance_prompt": MAINTENANCE_PROMPT,
        "maintenance_proposals_per_job": 1, "host_calls_per_job": 0,
        "ordinary_memory_quality": "NA; controlled empty State-only diagnostic",
        "rubric_read_by_runner": False,
    }


def prepare(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    cases, jobs = _cases_and_jobs(inputs)
    if (config["host"]["tool_mode"] != "json_action"
            or config["host"]["max_calls"] != 12 or config["host"]["max_tokens"] != 4096
            or config["host"]["temperature"] != 0
            or config["host"]["enable_thinking"] is not False
            or config["capacity"]["enable_thinking"] is not False
            or config["control"]["max_calls_per_message"] != 13
            or config["control"]["max_tokens"] != 2048
            or config["control"].get("local_granularity") is not True
            or any(len(case["pending_event_ids"]) > config["control"]["max_pending_batch"]
                   for case in cases.values())):
        raise ValueError("FIXED_UPDATE_CONFIG_INVALID")
    identity = _identity(args, config, jobs, lab_root=lab_root)
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    path = args.runtime_root / "run_manifest.json"
    if path.exists():
        if read_json(path)["identity"] != identity:
            raise ValueError("FIXED_UPDATE_RUN_IDENTITY_CHANGED")
    else:
        write_json(path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                          "attempts": {}, "outputs": {}})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(jobs), "manifest_path": str(path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _run_one(case: dict[str, Any], job: dict[str, Any], config: dict[str, Any],
             runtime: Any, root: Path, run_id: str, arm_id: str) -> dict[str, Any]:
    scope = StateScope(run_id, arm_id, case["user_id"])
    bank = LocalStateBank(runtime.store, max_states=config["control"]["max_states"],
                          max_events=config["control"]["max_events"],
                          max_total_content_chars=config["control"].get(
                              "aggregate_content_chars"))
    seed = _seed(case, runtime, bank, scope, root, Path(config["budget_path"]))
    before, events, pending = bank.states(scope), bank.events(scope), bank.pending(scope)
    if (before != sorted_states(case["states"])
            or {row["id"] for row in pending} != set(case["pending_event_ids"])):
        raise ValueError("FIXED_UPDATE_SEEDED_PRESTATE_CHANGED")
    original_emit = runtime.model.client.emit

    def emit(event: dict[str, Any]) -> None:
        if original_emit is not None:
            original_emit({**event, "role": "state_control", "job_id": job["job_id"],
                           "control_stage": CONTROL_STAGE.get()})

    control_config = replace(VLLMConfig(**config["host"]),
                             max_tokens=config["control"]["max_tokens"])
    selected: list[dict[str, Any]] = []
    result: dict[str, Any] = {"status": "STARTED", "proposal": None, "receipts": []}
    failure: BaseException | None = None
    with VLLMClient(control_config, emit=emit, budget=runtime.model.client.budget,
                    capacity=runtime.model.client.capacity) as client:
        controller = LocalStateController(
            bank, client, emit=emit, representation="local", local_granularity=True,
            max_pending_batch=config["control"]["max_pending_batch"],
            capacity_path=root / "control-capacity.json",
            max_calls_per_message=config["control"]["max_calls_per_message"])
        stage = "selection"
        try:
            if job["arm"] == "all":
                selected = before
            elif job["arm"] == "oracle_u":
                selected = [row for row in before if row["id"] in job["oracle_update_ids"]]
            elif before:
                stage = "update_selector" if job["arm"] == "u_selector" else "read_selector"
                if not controller._reserve_call(job["job_id"]):
                    raise ControlResponseError("LSA_CONTROL_CAPACITY")
                token = CONTROL_STAGE.set(stage)
                try:
                    emit({"event": "lsa_control_stage_call", "stage": stage,
                          "message_key": job["job_id"]})
                    with request_role("state_control"):
                        observations = [event_view(row) for row in pending]
                        selected = (select_directory_u(before, observations, client)
                                    if job["arm"] == "u_selector" else
                                    select_directory_a(before, case["query"], client,
                                                       observations=observations))
                finally:
                    CONTROL_STAGE.reset(token)
            mask = [row["id"] for row in selected]
            maintenance_payload = controller._maintenance_payload(pending, selected, events)
            emit({"event": "fixed_update_selection", "arm": job["arm"],
                  "update_ids": mask, "directory": state_directory(before),
                  "directory_bytes": len(json.dumps(state_directory(before),
                                                     ensure_ascii=False).encode()),
                  "candidate_body_bytes": len(json.dumps(maintenance_payload["states"],
                                                          ensure_ascii=False).encode())})
            stage = "maintenance"
            meta: dict[str, Any] = {}
            plan = controller._stage_call(
                "maintenance", job["job_id"], MAINTENANCE_PROMPT,
                maintenance_payload,
                controller._maintenance_schema(mask), receipt_meta=meta)
            result.update({"proposal": plan, "generation_id": meta.get("generation_id")})
            if set(plan) != {"edits"} or not isinstance(plan["edits"], list):
                raise ControlResponseError("LSA_MAINTENANCE_INVALID_SHAPE")
            receipts, invalid = bank.apply(
                scope, plan["edits"], {row["id"] for row in pending},
                allowed_existing_ids=set(mask), allow_create=True)
            result.update({"status": "PARTIAL_REJECTED" if invalid else
                           "APPLIED" if any(row["status"] in {"created", "updated"}
                                            for row in receipts) else "NO_CHANGE",
                           "receipts": receipts})
        except (ControlResponseError, httpx.TimeoutException) as error:
            result.update({"status": "CONTROL_REJECTED", "stage": stage,
                           "reason": controller._control_reason(error)})
        except ValueError as error:
            if str(error) == "LSA_READ_SELECTION_INVALID":
                result.update({"status": "CONTROL_REJECTED", "stage": stage,
                               "reason": str(error)})
            else:
                failure = error
        except BaseException as error:
            failure = error
    if failure is not None:
        result.update({"status": "FAILED", "exception": {
            "type": type(failure).__name__, "message": str(failure)}})
    after = bank.states(scope)
    pending_after = bank.pending(scope)
    events_after = bank.events(scope)
    result.update({
        "job": job, "scope": {"run_id": run_id, "arm_id": arm_id,
                                "user_id": scope.user_id}, "seed": seed,
        "states_before": before, "states_after": after,
        "selected_update_ids": [row["id"] for row in selected],
        "candidate_states": selected,
        "pending_event_ids_before": [row["id"] for row in pending],
        "pending_event_ids_after": [row["id"] for row in pending_after],
        "acknowledged_event_ids": [row["id"] for row in pending
                                    if row["id"] not in {item["id"] for item in pending_after}],
        "source_events_after": events_after, "store_stats": bank.store_stats(),
        "ordinary_memory_quality": "NA", "host_business_calls": 0,
        "control_capacity": read_json(root / "control-capacity.json")
        if (root / "control-capacity.json").exists() else {},
        "trace_path": str((root / "trace.jsonl").resolve()),
        "budget_path": str(Path(config["budget_path"]).resolve()),
    })
    emit({"event": "lsa_store_stats", "operations": bank.store_stats()})
    result["accounting"] = _accounting(root, Path(config["budget_path"]))
    write_json(root / "result.json", result)
    if failure is not None:
        raise failure
    return result


def run_job(args: Any, *, lab_root: Path) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    cases, jobs = _cases_and_jobs(inputs)
    identity = _identity(args, config, jobs, lab_root=lab_root)
    path = args.runtime_root / "run_manifest.json"
    manifest = read_json(path)
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()
    if (manifest["identity"] != identity
            or read_json(args.prepared)["identity_sha256"] != expected):
        raise ValueError("FIXED_UPDATE_PREPARED_IDENTITY_CHANGED")
    index = next((i for i, job in enumerate(jobs) if job["job_id"] == args.job), None)
    if index is None:
        raise ValueError("FIXED_UPDATE_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("FIXED_UPDATE_JOB_ALREADY_ATTEMPTED")
    if any(job["job_id"] not in manifest["attempts"] for job in jobs[:index]):
        raise ValueError("FIXED_UPDATE_JOB_OUT_OF_ORDER")
    job = jobs[index]
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job}
    manifest["status"] = "RUNNING"
    write_json(path, manifest)
    root = args.runtime_root / "jobs" / args.job
    run_id, arm_id = args.run + ":" + args.job, job["arm"]
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
        write_json(path, manifest)
