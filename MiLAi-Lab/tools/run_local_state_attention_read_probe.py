"""Run frozen, read-only first-request Local State diagnostics."""

from __future__ import annotations

import argparse
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

from milai_lab.harness.contextual_artifacts import (
    RunBudget,
    RunLimits,
    Trace,
    read_json,
    write_json,
)
from milai_lab.methods.local_state_attention.read_probe import (
    first_action,
    query_top_two,
    render_view,
    replace_view,
    select_focus,
    sorted_states,
)
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

LAB = Path(__file__).resolve().parents[1]
ARMS = {"all", "query", "focus", "diagnostic"}
SOURCE_PATHS = (*sorted(
    str(path.relative_to(LAB)) for path in (LAB / "src/milai_lab").rglob("*.py")
), "tools/run_local_state_attention_read_probe.py", "pyproject.toml")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _budget_path(config: dict[str, Any]) -> Path:
    return (LAB / Path(str(config["budget_path"]))).resolve()


def _cases(inputs: dict[str, Any], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (inputs.get("kind") != "LSA_READ_PROBE_INPUTS"
            or not isinstance(inputs.get("cases"), list)
            or not isinstance(inputs.get("jobs"), list)):
        raise ValueError("LSA_PROBE_INPUTS_INVALID")
    cases: dict[str, dict[str, Any]] = {}
    for case in inputs["cases"]:
        case_id = case["case_id"]
        if (not isinstance(case_id, str) or not case_id or case_id in cases
                or not isinstance(case.get("query"), str)
                or not isinstance(case.get("bank"), list)):
            raise ValueError("LSA_PROBE_CASE_INVALID")
        sorted_states(case["bank"])
        request = case["host_request"]
        if (request.get("model") != config["host"]["model"]
                or request.get("temperature") != config["host"]["temperature"]
                or request.get("max_tokens") != config["host"]["max_tokens"]
                or request.get("chat_template_kwargs", {}).get("enable_thinking")
                != config["capacity"]["enable_thinking"]
                or "response_format" not in request):
            raise ValueError("LSA_PROBE_HOST_PARAMETERS_CHANGED")
        replace_view(request, "")
        for variant in case.get("variants", {}).values():
            if (variant.get("diagnostic_only") is not True
                    or sum(key in variant for key in (
                        "bank", "context_text", "view_text")) != 1):
                raise ValueError("LSA_PROBE_VARIANT_INVALID")
            if "bank" in variant:
                sorted_states(variant["bank"])
            elif not isinstance(variant.get("context_text", variant.get("view_text")), str):
                raise ValueError("LSA_PROBE_VARIANT_INVALID")
        cases[case_id] = case
    job_ids: set[str] = set()
    for job in inputs["jobs"]:
        job_id = job["job_id"]
        if (not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None
                or job_id in job_ids or job.get("arm") not in ARMS
                or job.get("case_id") not in cases):
            raise ValueError("LSA_PROBE_JOB_INVALID")
        variant = job.get("variant")
        if ((job["arm"] == "diagnostic") != (isinstance(variant, str)
                and variant in cases[job["case_id"]].get("variants", {}))):
            raise ValueError("LSA_PROBE_JOB_VARIANT_INVALID")
        job_ids.add(job_id)
    return cases


def _identity(args: argparse.Namespace, config: dict[str, Any],
              inputs: dict[str, Any]) -> dict[str, Any]:
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langmem", "httpx", "jsonschema",
                 "transformers", "tokenizers"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "local_state_attention_read_probe", "run_id": args.run,
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=LAB, text=True).strip(),
        "source_sha256": {path: _sha(LAB / path) for path in SOURCE_PATHS},
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "config": config, "input_path": str(args.inputs.resolve()),
        "input_sha256": _sha(args.inputs), "jobs": inputs["jobs"],
        "case_model_parameters": {case["case_id"]: {
            key: value for key, value in case["host_request"].items()
            if key not in {"messages", "tools", "response_format"}}
            for case in inputs["cases"]},
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(LAB / "uv.lock"),
        "budget_path": str(_budget_path(config)),
        "runtime_root": str(args.runtime_root.resolve()),
        "rubric_read_by_runner": False,
    }


def _accounting(root: Path, budget_path: Path) -> dict[str, Any]:
    roles: dict[str, dict[str, int | float]] = {}
    trace_path = root / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text().splitlines():
            event = json.loads(line)
            kind = event.get("event")
            if kind not in {"vllm_response", "vllm_error", "vllm_budget_rejected",
                            "vllm_capacity_rejected"}:
                continue
            role = event["role"]
            row = roles.setdefault(role, {"attempts": 0, "completed_http": 0,
                                          "known_tokens": 0, "unknown_usage": 0,
                                          "errors": 0, "wall_seconds": 0.0})
            row["attempts"] += 1
            if kind == "vllm_response":
                row["completed_http"] += 1
            else:
                row["errors"] += 1
            usage = event.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(tokens) is int:
                row["known_tokens"] += tokens
            else:
                row["unknown_usage"] += 1
            row["wall_seconds"] += event.get("wall_seconds", 0.0)
    return {"by_role": roles, "trace_path": str(trace_path.resolve()),
            "continuous_budget": read_json(budget_path) if budget_path.exists() else None}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    _cases(inputs, config)
    identity = _identity(args, config, inputs)
    root = args.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "run_manifest.json"
    if manifest_path.exists():
        if read_json(manifest_path)["identity"] != identity:
            raise ValueError("LSA_PROBE_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "attempts": {}, "outputs": {},
                                   "accounting": _accounting(root, _budget_path(config))})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "jobs": len(inputs["jobs"]), "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def _emit(trace: Trace, role: str, job_id: str) -> Any:
    def emit(event: dict[str, Any]) -> None:
        trace({**event, "role": role, "job_id": job_id})
    return emit


def _host_once(client: VLLMClient, capacity: HostCapacity,
               request: dict[str, Any]) -> dict[str, Any]:
    try:
        capacity_receipt = capacity.check(request["messages"], request["max_tokens"],
                                          request.get("tools"))
    except CapacityExceeded as error:
        if client.emit is not None:
            client.emit({"event": "vllm_capacity_rejected", "path": "chat/completions",
                         "capacity": error.receipt})
        raise
    return client._post("chat/completions", request,
                        capacity_receipt=capacity_receipt)


def _execute(job: dict[str, Any], case: dict[str, Any], config: dict[str, Any],
             root: Path, trace: Trace, budget: RunBudget) -> dict[str, Any]:
    job_id, arm = job["job_id"], job["arm"]
    capacity = HostCapacity(config["capacity"])
    host_config = VLLMConfig(**config["host"])
    bank = sorted_states(case["bank"])
    context_text = None
    view_text = None
    selected: list[dict[str, Any]]
    if arm == "all":
        selected = bank
    elif arm == "diagnostic":
        variant = case["variants"][job["variant"]]
        selected = sorted_states(variant["bank"]) if "bank" in variant else []
        context_text = variant.get("context_text")
        view_text = variant.get("view_text")
    elif arm == "query":
        embed_cfg = VLLMConfig(base_url=config["embedding"]["base_url"],
                               model=config["embedding"]["model"],
                               timeout=config["embedding"].get("timeout", 180))
        with VLLMClient(embed_cfg, emit=_emit(trace, "query_embedding", job_id),
                        budget=budget) as embed:
            selected = query_top_two(bank, case["query"], embed, embed_cfg.model)
    elif arm == "focus":
        selector_cfg = replace(host_config, max_tokens=config["control"]["max_tokens"])
        with VLLMClient(selector_cfg, emit=_emit(trace, "read_selector", job_id),
                        budget=budget, capacity=capacity) as selector:
            selected = select_focus(bank, case["query"], selector)
    else:
        raise ValueError("LSA_PROBE_ARM_UNKNOWN")
    view = view_text if view_text is not None else render_view(selected, context_text)
    request = replace_view(case["host_request"], view)
    with VLLMClient(host_config, emit=_emit(trace, "task_host", job_id),
                    budget=budget, capacity=capacity) as host:
        receipt = _host_once(host, capacity, request)
    action = first_action(receipt, request)
    result = {"status": "COMPLETED_FIRST_REQUEST_ONLY", "job": job,
              "case_id": case["case_id"], "arm": arm,
              "diagnostic_only": arm == "diagnostic",
              "selected_state_ids": [row["id"] for row in selected],
              "selected_states": selected, "view": view,
              "host_request": request, "host_receipt": receipt,
              "first_action": action, "business_tools_executed": 0,
              "store_writes": 0}
    write_json(root / "jobs" / f"{job_id}.json", result)
    return result


def run_job(args: argparse.Namespace) -> dict[str, Any]:
    config, inputs = read_json(args.config), read_json(args.inputs)
    cases = _cases(inputs, config)
    identity = _identity(args, config, inputs)
    root = args.runtime_root
    manifest_path = root / "run_manifest.json"
    manifest = read_json(manifest_path)
    prepared = read_json(args.prepared)
    expected = hashlib.sha256(json.dumps(
        identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if (manifest["identity"] != identity
            or prepared["identity_sha256"] != expected):
        raise ValueError("LSA_PROBE_PREPARED_IDENTITY_CHANGED")
    jobs = inputs["jobs"]
    index = next((position for position, job in enumerate(jobs)
                  if job["job_id"] == args.job), None)
    if index is None:
        raise ValueError("LSA_PROBE_JOB_UNKNOWN")
    if args.job in manifest["attempts"]:
        raise ValueError("LSA_PROBE_JOB_ALREADY_ATTEMPTED")
    if any(job["job_id"] not in manifest["attempts"] for job in jobs[:index]):
        raise ValueError("LSA_PROBE_JOB_OUT_OF_ORDER")
    job = jobs[index]
    manifest["attempts"][args.job] = {"status": "STARTED", "job": job}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    try:
        trace = Trace(root / "trace.jsonl", args.stage)
        budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                     generation_tokens=None, embedding_tokens=None),
                           _budget_path(config))
        result = _execute(job, cases[job["case_id"]], config, root, trace, budget)
        manifest["attempts"][args.job]["status"] = "COMPLETED"
        manifest["outputs"][args.job] = str((root / "jobs" / f"{args.job}.json").resolve())
        manifest["status"] = ("TERMINAL" if len(manifest["attempts"]) == len(jobs)
                              else "RUNNING")
        return result
    except Exception as error:
        manifest["attempts"][args.job].update({
            "status": "FAILED", "exception": {"type": type(error).__name__,
                                                 "message": str(error)}})
        manifest["status"] = "FAILED"
        raise
    finally:
        manifest["accounting"] = _accounting(root, _budget_path(config))
        write_json(manifest_path, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run-job"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path,
                             default=LAB / "configs/local-state-attention.json")
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--run", required=True)
        command.add_argument("--runtime-root", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--job", required=True)
            command.add_argument("--stage", required=True)
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else run_job(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
