"""Synthetic benchmark execution contracts using stdlib and temporary files only."""

from __future__ import annotations

import copy
import importlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


def encode(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def outcome(action: Any) -> dict[str, Any]:
    try:
        return {"returned": encode(action())}
    except Exception as error:
        return {"exception": type(error).__name__, "message": str(error)}


def lifecycle_capture(module: Any, directory: Path) -> dict[str, Any]:
    identity = {"run_id": "synthetic-run", "unknown": {"retained": True}, "source": "fixed"}
    jobs = [
        {"job_id": "first", "unknown": ["kept"]},
        {"job_id": "second", "owner": "synthetic-owner"},
    ]
    result = {}

    def arguments(case: str) -> Any:
        root = directory / case
        root.mkdir()
        return SimpleNamespace(
            runtime_root=root / "run",
            output=root / "prepared.json",
            prepared=root / "prepared.json",
            job="first",
        )

    def files(args: Any) -> dict[str, str]:
        return {
            str(path.relative_to(args.runtime_root.parent)): path.read_text()
            for path in sorted(args.runtime_root.parent.rglob("*"))
            if path.is_file()
        }

    def step(rows: list[Any], args: Any, name: str, action: Any) -> None:
        rows.append({"operation": name, "outcome": outcome(action), "files": files(args)})

    for first, second in (
        ("COMPLETED", "COMPLETED"),
        ("FAILED", "COMPLETED"),
        ("FAILED", "FAILED"),
    ):
        key = "sequence_" + first.lower() + "_" + second.lower()
        args, rows = arguments(key), []
        step(rows, args, "prepare", lambda args=args: module.prepare_manifest(args, identity, jobs))
        args.job = "second"
        step(
            rows,
            args,
            "out_of_order",
            lambda args=args: module.start_job(args, identity=identity, jobs=jobs),
        )
        args.job = "first"
        started = module.start_job(args, identity=identity, jobs=jobs)
        rows.append({"operation": "start_first", "returned": encode(started), "files": files(args)})
        manifest = started[0]
        step(
            rows,
            args,
            "finish_first",
            lambda args=args, manifest=manifest, first=first: module.finish_job(
                args,
                manifest,
                first,
                args.runtime_root / "jobs/first/result.json",
                TimeoutError("synthetic accounted failure") if first == "FAILED" else None,
            ),
        )
        step(
            rows,
            args,
            "already_attempted",
            lambda args=args: module.start_job(args, identity=identity, jobs=jobs),
        )
        args.job = "second"
        started = module.start_job(args, identity=identity, jobs=jobs)
        rows.append(
            {"operation": "start_second", "returned": encode(started), "files": files(args)}
        )
        step(
            rows,
            args,
            "finish_second",
            lambda args=args, started=started, second=second: module.finish_job(
                args,
                started[0],
                second,
                error=ValueError("synthetic second failure") if second == "FAILED" else None,
            ),
        )
        step(
            rows,
            args,
            "reprepare_keeps_finished_manifest",
            lambda args=args: module.prepare_manifest(args, identity, jobs),
        )
        result[key] = rows

    args = arguments("runtime_dirty")
    args.runtime_root.mkdir()
    (args.runtime_root / "existing.txt").write_text("retain")
    result["runtime_dirty"] = {
        "outcome": outcome(lambda: module.prepare_manifest(args, identity, jobs)),
        "files": files(args),
    }

    for case in (
        "identity_change",
        "job_list_change",
        "prepared_digest_change",
        "unknown_job",
        "duplicate_job",
        "started_predecessor",
        "dirty_job_root",
        "unknown_fields",
        "arbitrary_finish_status",
    ):
        args = arguments(case)
        use_jobs = [jobs[0], copy.deepcopy(jobs[0])] if case == "duplicate_job" else jobs
        module.prepare_manifest(args, identity, use_jobs)
        candidate = copy.deepcopy(identity)
        if case == "identity_change":
            candidate["unknown"]["retained"] = False
        if case == "job_list_change":
            use_jobs = [jobs[1], jobs[0]]
        if case == "prepared_digest_change":
            module.write_json(args.prepared, {"identity_sha256": "wrong", "unknown": "keep"})
        if case == "unknown_job":
            args.job = "absent"
        if case == "started_predecessor":
            module.start_job(args, identity=identity, jobs=jobs)
            args.job = "second"
        if case == "dirty_job_root":
            root = args.runtime_root / "jobs/first"
            root.mkdir(parents=True)
            (root / "preserved.txt").write_text("existing job data")
        if case == "unknown_fields":
            manifest = module.read_json(args.runtime_root / "run_manifest.json")
            manifest["unknown_manifest"] = {"retain": "原文"}
            module.write_json(args.runtime_root / "run_manifest.json", manifest)
        observed = outcome(
            lambda args=args, candidate=candidate, use_jobs=use_jobs: module.start_job(
                args, identity=candidate, jobs=use_jobs
            )
        )
        if case == "arbitrary_finish_status":
            manifest = module.read_json(args.runtime_root / "run_manifest.json")
            observed["finish"] = outcome(
                lambda args=args, manifest=manifest: module.finish_job(
                    args, manifest, "synthetic_external_status"
                )
            )
        result[case] = {"outcome": observed, "files": files(args)}
    return result


def costs_capture(module: Any, directory: Path) -> dict[str, Any]:
    root = directory / "costs"
    root.mkdir()
    result = {"missing_trace": module.trace_costs(root)}
    events = [
        {"event": "vllm_response", "path": "chat/completions", "usage": {"total_tokens": 9}},
        {"event": "vllm_error", "path": "chat/completions", "usage": None},
        {"event": "vllm_response", "path": "embeddings", "usage": {"total_tokens": True}},
        {"event": "benchmark_phase", "phase": "formation"},
        {"event": "vllm_response", "path": "embeddings", "usage": {"total_tokens": 5}},
        {"event": "vllm_response", "path": "chat/completions", "usage": {"total_tokens": -2}},
        {"event": "benchmark_phase", "phase": "reader"},
        {"event": "vllm_error", "path": "embeddings", "usage": {}},
        {
            "event": "langmem_mcp",
            "kind": "http",
            "cpu_ns": 11,
            "wall_ns": 21,
            "request_body": "请求",
            "response_body": "response",
        },
        {
            "event": "langmem_mcp",
            "kind": "resource_result",
            "cpu_ns": 3,
            "wall_ns": 8,
            "logical_bytes": 13,
        },
        {"event": "langmem_mcp", "kind": "unaggregated", "unknown": True},
        {"event": "unknown_event", "usage": {"total_tokens": 9000}},
    ]
    names = (
        "benchmark_backend_artifact_io",
        "mem0_native_runtime",
        "mem0_benchmark_archive_add",
        "mem0_benchmark_search",
        "mem0_benchmark_snapshot",
        "persistent_memory_checkpoint_read",
        "lsa_history_checkpoint_read",
        "lsa_history_summary_result",
        "benchmark_summary_update",
        "benchmark_raw_index",
        "benchmark_raw_retrieval",
        "simplemem_observation",
    )
    for name in names:
        events.extend(
            (
                {"event": name, "calls": 2, "logical_bytes": 17, "cpu_ns": 7, "wall_ns": 30},
                {"event": name, "unknown": "retain as observation"},
            )
        )
    path = root / "trace.jsonl"
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
    result["input_trace_bytes"] = path.read_text()
    result["aggregated"] = module.trace_costs(root)
    for case, content in (
        ("invalid_json", "{bad}\n"),
        ("missing_mcp_fields", '{"event":"langmem_mcp","kind":"http"}\n'),
    ):
        path.write_text(content)
        result[case] = outcome(lambda: module.trace_costs(root))
    return result


def config_capture(module: Any, directory: Path) -> dict[str, Any]:
    valid = {
        "host": {
            "tool_mode": "native",
            "max_tokens": 4096,
            "max_calls": 12,
            "temperature": 0,
            "enable_thinking": False,
        },
        "capacity": {"enable_thinking": False},
        "budget_path": str(directory / "budget.json"),
        "memory_contract": "strict",
        "memory_transport": "mcp_http",
        "unknown": {"retain": True},
    }
    result = {"valid": outcome(lambda: module.validate_config(valid)), "input": valid}
    for key, value in (
        ("tool_mode", "json_action"),
        ("max_tokens", 4095),
        ("max_calls", 11),
        ("temperature", 0.2),
        ("enable_thinking", True),
    ):
        changed = copy.deepcopy(valid)
        changed["host"][key] = value
        result["host_" + key] = outcome(lambda changed=changed: module.validate_config(changed))
    for key, value in (
        ("budget_path", "relative.json"),
        ("memory_contract", "other"),
        ("memory_transport", "other"),
    ):
        changed = copy.deepcopy(valid)
        changed[key] = value
        result[key] = outcome(lambda changed=changed: module.validate_config(changed))
    changed = copy.deepcopy(valid)
    del changed["host"]["tool_mode"]
    result["missing_required"] = outcome(lambda: module.validate_config(changed))
    return result


def source_capture(module: Any, directory: Path) -> dict[str, Any]:
    root = directory / "synthetic_source"
    files = {
        "src/milai_lab/z.py": "z = 1\n",
        "src/milai_lab/contracts/a.py": "a = 2\n",
        "tools/run_unified_benchmarks.py": "pass\n",
        "pyproject.toml": "[project]\n",
        "uv.lock": "synthetic lock\n",
        "data/locks/unified-v8-v9-native-transport-20260928.requirements.txt": "synthetic==1\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    calls = []

    def version(name: str) -> str:
        if name in {"openai", "httpx", "jsonschema"}:
            return "synthetic-" + name
        raise importlib.metadata.PackageNotFoundError(name)

    def git(command: list[str], **kwargs: Any) -> str:
        calls.append({"command": command, "cwd": str(kwargs["cwd"]), "text": kwargs["text"]})
        return "f" * 40 + "\n"

    with ExitStack() as stack:
        stack.enter_context(patch.object(importlib.metadata, "version", version))
        stack.enter_context(
            patch.object(
                importlib.metadata,
                "distributions",
                lambda: [
                    SimpleNamespace(metadata={"Name": "z-last"}, version="2"),
                    SimpleNamespace(metadata={}, version="ignored"),
                    SimpleNamespace(metadata={"Name": "a-first"}, version="1"),
                ],
            )
        )
        stack.enter_context(patch.object(shutil, "which", lambda _name: "/usr/bin/git"))
        stack.enter_context(patch.object(subprocess, "check_output", git))
        stack.enter_context(patch.object(sys, "version", "synthetic-python-version"))
        result = {"source_files": files, "original": module.source_identity(root)}
        (root / "src/milai_lab/z.py").write_text("z = 3\n")
        result["tampered_source"] = module.source_identity(root)
        (root / "data/locks/unified-v8-v9-native-transport-20260928.requirements.txt").unlink()
        result["optional_native_lock_absent"] = module.source_identity(root)
        result["git_calls"] = calls
    return result


def capture(canonical: bool) -> dict[str, Any]:
    module = importlib.import_module(
        "milai_lab.harness.benchmark_execution" if canonical else "milai_lab.runners.merit_native"
    )
    with tempfile.TemporaryDirectory(prefix="milai-v12-execution-") as temporary:
        directory = Path(temporary)
        captured = {
            "lifecycle": lifecycle_capture(module, directory),
            "costs": costs_capture(module, directory),
            "config": config_capture(module, directory),
            "source_identity": source_capture(module, directory),
        }
        return json.loads(json.dumps(captured, ensure_ascii=False).replace(str(directory), "<TMP>"))
