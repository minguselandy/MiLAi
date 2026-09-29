"""Common benchmark manifest, attempt ordering, source identity and cost aggregation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from milai_lab.contracts.benchmark import (
    BenchmarkFinishArguments,
    BenchmarkJob,
    BenchmarkManifest,
    BenchmarkPreparationReceipt,
    BenchmarkPrepareArguments,
    BenchmarkSourceIdentity,
    BenchmarkStartArguments,
)
from milai_lab.harness.artifact_io import digest, read_json, write_json

__all__ = [
    "finish_job",
    "prepare_manifest",
    "sha",
    "source_identity",
    "start_job",
    "trace_costs",
    "validate_config",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_costs(root: Path) -> dict[str, Any]:
    """Disjoint request/usage categories; inclusive MCP timing is not added to model wall time."""
    roles: dict[str, Any] = {}
    mcp: dict[str, Any] = {}
    observations: dict[str, Any] = {}
    phase = "task_host"
    path = root / "trace.jsonl"
    for line in path.read_text().splitlines() if path.exists() else []:
        event = json.loads(line)
        if event.get("event") == "benchmark_phase":
            phase = event["phase"]
        if event.get("event") in {"vllm_response", "vllm_error"}:
            role = "embedding:" + phase if event.get("path") == "embeddings" else phase
            row = roles.setdefault(role, {"requests": 0, "known_tokens": 0, "unknown_usage": 0})
            row["requests"] += 1
            usage = event.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(tokens) is int:
                row["known_tokens"] += tokens
            else:
                row["unknown_usage"] += 1
        if event.get("event") == "langmem_mcp" and event.get("kind") in {"http", "resource_result"}:
            row = mcp.setdefault(
                event["kind"], {"calls": 0, "cpu_ns": 0, "wall_ns": 0, "logical_bytes": 0}
            )
            row["calls"] += 1
            for key in ("cpu_ns", "wall_ns"):
                row[key] += event[key]
            row["logical_bytes"] += (
                len(event["request_body"].encode()) + len(event["response_body"].encode())
                if event["kind"] == "http"
                else event["logical_bytes"]
            )
        if event.get("event") in {
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
        }:
            row = observations.setdefault(event["event"], {"observations": 0})
            row["observations"] += 1
            for key in ("calls", "logical_bytes", "cpu_ns", "wall_ns"):
                if key in event:
                    row[key] = row.get(key, 0) + event[key]
    return {
        "roles": roles,
        "mcp_inclusive_observation_costs": mcp,
        **({"backend_observation_costs": observations} if observations else {}),
        "physical_io": None,
        "store_net_cpu_ns": None,
        "timing_scope": "transport/service/material timings overlap; not additive",
        "ledger_owner": "single runtime RunBudget; no second charge here",
    }


def validate_config(config: dict[str, Any]) -> None:
    host = config["host"]
    if (
        host["tool_mode"] != "native"
        or host["max_tokens"] != 4096
        or host["max_calls"] != 12
        or host["temperature"] != 0
        or host["enable_thinking"] is not False
        or config["capacity"]["enable_thinking"] is not False
        or not Path(config["budget_path"]).is_absolute()
        or config["memory_contract"] != "strict"
        or config.get("memory_transport") != "mcp_http"
    ):
        raise ValueError("UNIFIED_BENCHMARK_CONFIG_INVALID")


def source_identity(lab_root: Path) -> BenchmarkSourceIdentity:
    paths = [
        *sorted((lab_root / "src/milai_lab").rglob("*.py")),
        lab_root / "tools/run_unified_benchmarks.py",
        lab_root / "pyproject.toml",
    ]
    dependencies: dict[str, str | None] = {}
    native_lock = lab_root / "data/locks/unified-v8-v9-native-transport-20260928.requirements.txt"
    for name in (
        "openai",
        "litellm",
        "langchain-core",
        "langgraph",
        "langmem",
        "mcp",
        "httpx",
        "transformers",
        "tokenizers",
        "psycopg",
        "jsonschema",
    ):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    return {
        "source_sha256": {str(path.relative_to(lab_root)): sha(path) for path in paths},
        "dependency_lock_sha256": sha(lab_root / "uv.lock"),
        "native_transport_requirements_sha256": (
            sha(native_lock) if native_lock.exists() else None
        ),
        "dependencies": dependencies,
        "python": sys.version,
        "environment_packages": dict(
            sorted(
                (dist.metadata["Name"], dist.version)
                for dist in importlib.metadata.distributions()
                if "Name" in dist.metadata
            )
        ),
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed read-only command
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"], cwd=lab_root, text=True
        ).strip(),
    }


def prepare_manifest(
    args: BenchmarkPrepareArguments,
    identity: dict[str, Any],
    jobs: list[BenchmarkJob],
) -> BenchmarkPreparationReceipt:
    path = args.runtime_root / "run_manifest.json"
    value: BenchmarkManifest = {
        "identity": identity,
        "jobs": jobs,
        "attempts": {},
        "status": "PREPARED_ZERO_MODEL",
    }
    if path.exists():
        old = read_json(path)
        if old["identity"] != identity or old["jobs"] != jobs:
            raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    else:
        if args.runtime_root.exists() and any(args.runtime_root.iterdir()):
            raise ValueError("UNIFIED_BENCHMARK_RUNTIME_DIRTY")
        write_json(path, value)
    receipt: BenchmarkPreparationReceipt = {
        "status": "PREPARED_ZERO_MODEL",
        "jobs": jobs,
        "manifest_path": str(path.resolve()),
        "identity_sha256": digest(identity),
    }
    write_json(args.output, receipt)
    return receipt


def start_job(
    args: BenchmarkStartArguments,
    *,
    identity: dict[str, Any],
    jobs: list[BenchmarkJob],
) -> tuple[BenchmarkManifest, BenchmarkJob, Path]:
    manifest_path = args.runtime_root / "run_manifest.json"
    manifest: BenchmarkManifest = read_json(manifest_path)
    if (
        manifest["identity"] != identity
        or manifest["jobs"] != jobs
        or read_json(args.prepared)["identity_sha256"] != digest(identity)
    ):
        raise ValueError("UNIFIED_BENCHMARK_IDENTITY_CHANGED")
    matches = [job for job in jobs if job["job_id"] == args.job]
    if len(matches) != 1:
        raise ValueError("UNIFIED_BENCHMARK_JOB_UNKNOWN")
    index = jobs.index(matches[0])
    if args.job in manifest["attempts"]:
        raise ValueError("UNIFIED_BENCHMARK_JOB_ALREADY_ATTEMPTED")
    if any(
        manifest["attempts"].get(job["job_id"], cast(dict[str, Any], {})).get("status")
        not in {"COMPLETED", "FAILED"}
        for job in jobs[:index]
    ):
        raise ValueError("UNIFIED_BENCHMARK_JOB_ORDER")
    manifest["attempts"][args.job] = {"status": "STARTED"}
    manifest["status"] = "RUNNING"
    write_json(manifest_path, manifest)
    root = args.runtime_root / "jobs" / args.job
    if root.exists():
        raise ValueError("UNIFIED_BENCHMARK_JOB_RUNTIME_DIRTY")
    root.mkdir(parents=True)
    return manifest, matches[0], root


def finish_job(
    args: BenchmarkFinishArguments,
    manifest: BenchmarkManifest,
    status: str,
    output: Path | None = None,
    error: BaseException | None = None,
) -> None:
    manifest["attempts"][args.job] = {
        "status": status,
        "output": str(output) if output else None,
        "error_type": type(error).__name__ if error else None,
    }
    manifest["status"] = (
        (
            "COMPLETED"
            if all(row["status"] == "COMPLETED" for row in manifest["attempts"].values())
            else "COMPLETED_WITH_FAILURES"
        )
        if len(manifest["attempts"]) == len(manifest["jobs"])
        else "FAILED"
        if status == "FAILED"
        else "PARTIALLY_COMPLETED"
    )
    write_json(args.runtime_root / "run_manifest.json", manifest)
