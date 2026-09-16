"""No-model checks using real public MCP, own PostgreSQL and fresh client processes."""

# Fixed Python worker and run-owned files, never model-generated commands.
# ruff: noqa: S603

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import httpx

import run_v02_memory_flow as base
from check_v02_service_concurrency import clock_identity
from run_v02_local_vllm import assemble_bootstrap, dispatch, manifest, stop_owned
from v02_cgroup_observation import ContainerObservation, host_scheduler_sample
from v02_e2e_state import FileDisclosure, LocalGateError, save_layers, usable_head
from v02_local_provider import write_json
from v02_low_cost_public import observer

CONFIG = base.LAB / "configs/v02-e2e-generality.json"


def mcp_transport_comparison(root: Path, service: Path, config: dict) -> None:
    from check_v02_service_concurrency import compare_mcp_mode

    results = []
    for i, mode in enumerate(config["mcp_transport_comparison"]):
        assert mode in {"sync", "async"}
        directory = root / ("mcp-" + mode)
        directory.mkdir()
        group = base.ProcessGroup(directory)
        env = base._load_environment(service / "runtime.env")
        port, token = base._free_port(), secrets.token_urlsafe(32)
        env.update(
            {
                "MILAI_CODEX_PRINCIPAL_ID": "p1-comparison-host",
                "MILAI_CODEX_TASK_REF": "p1-comparison-task",
                "MILAI_CODEX_SESSION_REF": "p1-comparison-session",
                "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": ["p1-comparison"]}),
                "MILAI_CODEX_TOKEN": token,
                "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
            }
        )
        try:
            server = group.start(
                "comparison-mcp",
                [
                    str(base.MCP / ".venv/bin/milai-mcp"),
                    "--transport",
                    "streamable-http",
                    "--profile",
                    "codex-full",
                    "--port",
                    str(port),
                    "--max-retries",
                    "0",
                    "--working-state-transport",
                    mode,
                ],
                cwd=base.MCP,
                env=base._clean_environment(env),
            )
            base._wait_http(f"http://127.0.0.1:{port}/readyz", server)
            results.append(
                asyncio.run(
                    asyncio.wait_for(
                        compare_mcp_mode(
                            root,
                            f"http://127.0.0.1:{port}/mcp",
                            token,
                            mode,
                            seed=i == 0,
                        ),
                        config["worker_timeout_seconds"],
                    )
                )
            )
        finally:
            group.stop()
    assert sum(r["tool_calls"] for r in results) <= config["maximum_mcp_tool_calls"]
    assert base.read_json(root / "mcp-sync-catalog.json") == base.read_json(
        root / "mcp-async-catalog.json"
    )
    write_json(
        root / "mcp-comparison.json",
        {
            "status": "PAIRED_TRANSPORT_MECHANISM_COMPLETED_NOT_SERVICE_SLO",
            "modes": results,
            "catalog_equal": True,
            "generation_requests": 0,
            "ordering": config["mcp_transport_comparison"],
            "cache_control": "BOTH_WARMED_NO_DATABASE_CACHE_RESET",
        },
    )


def service_calibration(root: Path, config_path: Path | None = None) -> None:
    """Initial bounded State baseline; broader service acceptance remains separate."""
    config_path = config_path or base.LAB / "configs/v02-service-calibration.json"
    config = base.read_json(config_path)
    pin = base.pin(config_path)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    service = root / (root.name + "-product")
    project = service.name + "-pg"
    existing = base._command(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + project]
    ).stdout.strip()
    volumes = base._command(
        ["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + project]
    ).stdout.strip()
    if existing or volumes:
        raise RuntimeError("SERVICE_NAMESPACE_ALREADY_EXISTS")
    write_json(root / "config.json", config)
    cpus = sorted(os.sched_getaffinity(0))[: config["runtime_cpu_affinity_count"]]
    write_json(
        root / "preflight.json",
        {
            "pin": pin,
            "cpu_affinity": cpus,
            "cpu_count": os.cpu_count(),
            "measurement": config["measurement"],
            "shared_services": "UNTOUCHED",
            "code_sha256": {
                str(p.relative_to(base.LAB)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (
                    Path(__file__), base.LAB / "tools/check_v02_service_concurrency.py",
                    *([base.LAB / "tools/check_v02_scoped_recall.py"]
                      if config.get("scoped_recall") else []),
                )
            },
        },
    )
    override = root / "compose-limits.yaml"
    override.write_text(
        "services:\n  postgres:\n    network_mode: bridge\n"
        f"    cpus: {config['postgres_cpu_limit']}\n"
        f"    mem_limit: {config['postgres_memory_limit']}\n"
    )
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, cpus)
    mixed_mcp_group = None
    try:
        base.prepare(
            service,
            config_path=config_path,
            compose_override=override,
            runtime_overrides={
                "MILAI_DATA_MODE": "SYNTHETIC_ONLY",
                "MILAI_API_THREADS": str(config["api_threads"]),
                "MILAI_REQUEST_TIMING_ENABLED": str(
                    config.get("request_timing_enabled", False)
                ).lower(),
                "MILAI_DATABASE_POOL_MAX_SIZE": str(config["database_pool_max_size"]),
                "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
                "MILAI_EMBEDDING_MODEL_ID": "deterministic-hash-v1",
                "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
                "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
                "MILAI_RETRIEVAL_RERANKER_PROVIDER": "none",
                **({
                    "MILAI_FEATURE_PROFILE": "BASELINE",
                    "MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED": "false",
                } if config.get("scoped_recall") else {}),
            },
        )
        env = base._load_environment(service / "runtime.env")
        write_json(
            root / "deployment.json",
            {
                "postgres": json.loads(
                    base._command(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            '{"image":{{json .Image}},"memory":{{.HostConfig.Memory}},'
                            '"nano_cpus":{{.HostConfig.NanoCpus}}}',
                            project + "-postgres-1",
                        ]
                    ).stdout
                ),
                "uname": list(os.uname()),
                "meminfo": Path("/proc/meminfo").read_text(),
                "pool_wait_observer": "NOT_AVAILABLE_IN_PUBLIC_STATE_RESPONSE",
            },
        )
        command = [
            str(base.MCP / ".venv/bin/python"),
            str(base.LAB / "tools/check_v02_service_concurrency.py"),
            "--root",
            str(root),
        ]
        if config.get("mixed_load_arm") or config.get("scoped_recall"):
            directory = root / "mixed-mcp"
            directory.mkdir()
            mixed_mcp_group = base.ProcessGroup(directory)
            port = base._free_port()
            env.update(
                {
                    "MILAI_CODEX_PRINCIPAL_ID": "mixed-host",
                    "MILAI_CODEX_TASK_REF": "mixed-task",
                    "MILAI_CODEX_SESSION_REF": "mixed-session",
                    "MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": ["mixed-project"]}),
                    "MILAI_CODEX_TOKEN": secrets.token_urlsafe(32),
                    "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
                }
            )
            mcp_command = [
                    str(base.MCP / ".venv/bin/milai-mcp"),
                    "--transport",
                    "streamable-http",
                    "--profile",
                    "codex-full",
                    "--port",
                    str(port),
                    "--max-retries",
                    "0",
                    "--working-state-transport",
                    "async",
                ]
            if config.get("observe_mcp_gc", False):
                mcp_command = [
                    str(base.MCP / ".venv/bin/python"),
                    str(base.LAB / "tools/observe_v02_mcp_cli_gc.py"),
                    "--output", str(directory), *mcp_command,
                ]
            mcp = mixed_mcp_group.start(
                "mixed-mcp", mcp_command,
                cwd=base.MCP,
                env=base._clean_environment(env),
            )
            base._wait_http(f"http://127.0.0.1:{port}/readyz", mcp)
            env["MILAI_MIXED_MCP_URL"] = f"http://127.0.0.1:{port}/mcp"
            command[1] = str(base.LAB / "tools" / (
                "check_v02_scoped_recall.py" if config.get("scoped_recall")
                else "check_v02_mixed_load.py"
            ))
        pg_observer = None
        sample_interval = config.get("resource_sample_interval_seconds", 0.5)
        assert 0.05 <= sample_interval <= 0.5
        if config.get("observe_pg_cgroup", False):
            container = json.loads(base._command([
                "docker", "inspect", "--format",
                '{"id":{{json .Id}},"pid":{{.State.Pid}}}', project + "-postgres-1",
            ]).stdout)
            pg_observer = ContainerObservation.bind(container["pid"], container["id"])
            write_json(root / "postgres-cgroup-binding.json", {
                **container, "path": str(pg_observer.cgroup), "start_ticks": pg_observer.start,
                "sample_interval_seconds": sample_interval,
            })
        with (root / "sdk-worker.log").open("w") as log:
            process = subprocess.Popen(
                command, cwd=base.LAB, env=base._clean_environment(env), stdout=log, stderr=log
            )
            samples = []
            sizes, next_storage_check = 0, 0.0
            deadline = time.monotonic() + config["worker_timeout_seconds"]
            try:
                if config.get("require_shared_monotonic_clock", False):
                    identity = clock_identity()
                    namespaces = {
                        "load_client": os.readlink(f"/proc/{process.pid}/ns/time"),
                        "mcp": os.readlink(f"/proc/{mcp.pid}/ns/time"),
                    }
                    if set(namespaces.values()) != {identity["time_namespace"]}:
                        raise RuntimeError("MONOTONIC_CLOCK_NAMESPACE_NOT_SHARED")
                    write_json(root / "clock-binding.json", {
                        "status": "LOCAL_SHARED_TIME_NAMESPACE_VERIFIED",
                        "identity": identity, "namespaces": namespaces,
                        "pids": {"load_client": process.pid, "mcp": mcp.pid},
                    })
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise TimeoutError("CALIBRATION_WORKER_DEADLINE")
                    if time.monotonic() >= next_storage_check:
                        sizes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
                        next_storage_check = time.monotonic() + 0.5
                    if sizes > config["total_artifact_storage_stop_bytes"]:
                        raise RuntimeError("ARTIFACT_STORAGE_LIMIT")
                    samples.append(
                        {
                            "monotonic": time.monotonic(),
                            "artifact_bytes": sizes,
                            **({"postgres_cgroup": pg_observer.sample()} if pg_observer else {}),
                            **({"host_scheduler": host_scheduler_sample({
                                **base.read_json(service / "services.json"),
                                "load_client": process.pid,
                                **({"mcp": mcp.pid} if mixed_mcp_group else {}),
                            })} if config.get("observe_host_scheduler", False) else {}),
                            "processes": {
                                name: {
                                    k: Path(f"/proc/{pid}/{k}").read_text()
                                    for k in ("stat", "status", "io")
                                }
                                for name, pid in base.read_json(service / "services.json").items()
                            },
                        }
                    )
                    time.sleep(sample_interval)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                write_json(root / "resource-samples.json", samples)
            if process.returncode:
                raise RuntimeError("SDK_CALIBRATION_FAILED_SEE_PRESERVED_LOG")
        if config.get("mixed_load_arm") or config.get("scoped_recall"):
            return
        if config.get("mcp_transport_comparison"):
            mcp_transport_comparison(root, service, config)
            if config.get("postgres_regression_after_measurement"):
                result = base._command(
                    [
                        str(base.MCP / ".venv/bin/python"),
                        "-m",
                        "pytest",
                        "-q",
                        "tests/test_codex_full_postgres_e2e.py",
                    ],
                    cwd=base.MCP,
                    env=base._clean_environment(
                        {
                            **env,
                            "MILAI_MCP_BASELINE_E2E": "1",
                        }
                    ),
                    timeout=180,
                    check=False,
                )
                (root / "postgres-regression.log").write_text(result.stdout + result.stderr)
                assert result.returncode == 0, "POSTGRES_REGRESSION_FAILED_SEE_LOG"
            if config.get("runtime_regression_after_measurement"):
                result = base._command(
                    [
                        str(base.RUNTIME / ".venv/bin/python"),
                        "-m",
                        "pytest",
                        "-q",
                    ],
                    cwd=base.RUNTIME,
                    env=base._clean_environment(
                        {
                            **env,
                            "MILAI_TEST_DATABASE_URL": env["MILAI_MIGRATION_DATABASE_URL"],
                            "MILAI_TEST_API_DATABASE_URL": env["MILAI_DATABASE_URL"],
                            "MILAI_TEST_STEWARD_DATABASE_URL": env["MILAI_STEWARD_DATABASE_URL"],
                            "MILAI_TEST_WORKER_DATABASE_URL": env["MILAI_WORKER_DATABASE_URL"],
                            "MILAI_TEST_AUDIT_DATABASE_URL": env["MILAI_AUDIT_DATABASE_URL"],
                        }
                    ),
                    timeout=300,
                    check=False,
                )
                (root / "runtime-regression.log").write_text(result.stdout + result.stderr)
                assert result.returncode == 0, "RUNTIME_REGRESSION_FAILED_SEE_LOG"
            return
        directory = root / "mcp"
        directory.mkdir()
        with observer(service, directory, "p1-mcp", "p1-task") as (call, _):
            receipts = {}
            for scope in ("TASK", "SESSION"):
                receipts[scope] = call(
                    "milai_working_state_update",
                    {
                        "scope": scope,
                        "operation_id": "seed-" + scope,
                        "expected_version": 0,
                        "payload": {"marker": scope, "text": "x" * 512},
                    },
                )
                assert receipts[scope].get("version") == 1

            def read(scope):
                started = time.monotonic()
                value = call("milai_working_state_get", {"scope": scope})
                assert value["payload"] == receipts[scope]["payload"]
                return {
                    "scope": scope,
                    "elapsed_ms": (time.monotonic() - started) * 1000,
                    "state_version_id": value["state_version_id"],
                }

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(read, ["TASK", "SESSION"] * 3))
            write_json(
                root / "mcp-result.json",
                {
                    "status": "READ_BINDINGS_CORRECT",
                    "requests": 8,
                    "reads": results,
                    "measurement": "FRESH_LEGACY_MCP_CLIENT_PER_CALL_INCLUDES_HANDSHAKE",
                    "not_sdk_latency_equivalent": True,
                    "runtime_retry_policy": 0,
                },
            )
    finally:
        if mixed_mcp_group is not None:
            mixed_mcp_group.stop()
        os.sched_setaffinity(0, affinity)
        cleanup = stop_owned(service)
        time.sleep(0.5)
        cleanup["remaining_live_processes"] = (
            [
                {"name": name, "pid": pid}
                for name, pid in base.read_json(service / "services.json").items()
                if Path(f"/proc/{pid}/stat").exists()
                and Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
            ]
            if (service / "services.json").exists()
            else []
        )
        cleanup["running_containers"] = base._command(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + project,
            ]
        ).stdout.strip()
        write_json(root / "cleanup.json", cleanup)
        assert not cleanup["remaining_live_processes"] and not cleanup["running_containers"]


def metadata(env: dict, ref: str) -> dict:
    from uuid import UUID

    with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
        response = client.get(
            env["MILAI_BASE_URL"] + "/v1/evidence/" + str(UUID(ref)),
            headers={"Authorization": "Bearer " + env["MILAI_API_TOKEN"]},
        )
        response.raise_for_status()
        return response.json()


def capture(call, project: str, marker: str) -> dict:
    result = call(
        "milai_evidence_capture",
        {
            "operation_id": project + "-capture-" + marker,
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": "engineering://" + project + "/" + marker,
            "subject_id": "memory-engineering",
            "speaker": "user",
            "observed_at": "2026-09-06T10:00:00+08:00",
            "content": marker,
            "confirmation": "CAPTURE",
        },
    )
    assert not result.get("mcp_error"), result
    return result


def cold_worker(root: Path, request: Path) -> None:
    params = base.read_json(request)
    directory = request.parent / "cold-client"
    directory.mkdir()
    with observer(root / "product", directory, params["project"], params["task"]) as (call, _):
        head = call("milai_working_state_get", {"scope": "TASK"})
        if params.get("expect_withheld"):
            assert head["payload"] == {} and head["payload_withheld"]
            try:
                usable_head(head)
            except LocalGateError:
                write_json(
                    request.parent / "cold-result.json",
                    {"pid": os.getpid(), "head": head, "assembly_refused": True},
                )
                return
            raise AssertionError("Revoked State accepted for cold assembly")
        output = {
            "pid": os.getpid(),
            "head": head,
            "A": assemble_bootstrap(head, Path(params["workspace"]), "A", params["config"]),
            "B": assemble_bootstrap(head, Path(params["workspace"]), "B", params["config"]),
        }
        write_json(request.parent / "cold-result.json", output)


def run(root: Path) -> None:
    config = base.read_json(CONFIG)
    assert config["model_transport_enabled"] is False
    results = {
        "status": "RUNNING",
        "model_requests": 0,
        "checks": {},
        "pin": base.pin(CONFIG),
        "parent_pid": os.getpid(),
    }
    checks = results["checks"]
    directory = root / "live-after"
    directory.mkdir(exist_ok=False)
    cases = [
        ("text", "  中文\r\n\t正文\n"),
        (
            "json",
            json.dumps(
                {"last": None, " 空键 ": [False, 0, "", {"k": " v \n"}], "first": "正文"},
                ensure_ascii=False,
            ),
        ),
    ]
    try:
        for kind, content in cases:
            case = directory / kind
            case.mkdir()
            workspace = case / "workspace"
            workspace.mkdir()
            (workspace / "handoff.md").write_bytes(content.encode())
            (workspace / "details.md").write_text("COMPLETE_DETAIL_" + kind + "\n")
            local = {**config, "l1_format": kind}
            project, task = "eng-live-" + kind, "eng-live-task-" + kind
            with observer(root / "product", case, project, task) as (call, _):
                cap = capture(call, project, "SHARED_SOURCE_" + kind)
                old = call(
                    "milai_working_state_update",
                    {
                        "scope": "TASK",
                        "state_id": None,
                        "expected_version": 0,
                        "operation_id": project + "-old",
                        "payload": {
                            "unrelated": {
                                "text": " retain \n",
                                "evidence_refs": [cap["evidence_id"]],
                            }
                        },
                    },
                )
                assert old.get("version") == 1
                saved = save_layers(
                    call,
                    workspace,
                    local,
                    manifest(workspace),
                    project + "-save",
                    [cap["evidence_id"]],
                )
                write_json(case / "save.json", saved)
                assert saved["operation"]["outcome"] == "CONFIRMED"
                assert saved["comparison_opportunity"]
                assert saved["payload"]["unrelated"] == old["payload"]["unrelated"]
                repeat = save_layers(
                    call,
                    workspace,
                    local,
                    manifest(workspace),
                    project + "-noop",
                    [cap["evidence_id"]],
                )
                assert (
                    repeat["selection_reason"] == "NO_CHANGE"
                    and not repeat["operation"]["attempted"]
                )
                replay = call("milai_working_state_update", saved["request"])
                assert (
                    replay["replayed"]
                    and replay["state_version_id"] == saved["operation"]["version_id"]
                )
                stale = call(
                    "milai_working_state_update",
                    {**saved["request"], "operation_id": project + "-stale"},
                )
                assert "STALE_WORKING_STATE" in json.dumps(stale)
                conflict = call("milai_working_state_update", {**saved["request"], "payload": {}})
                assert "OPERATION_CONFLICT" in json.dumps(conflict)
                write_json(
                    case / "checks.json",
                    {"noop": repeat, "replay": replay, "stale": stale, "conflict": conflict},
                )
            request = case / "cold-request.json"
            write_json(
                request,
                {"project": project, "task": task, "workspace": str(workspace), "config": local},
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--root",
                    str(root),
                    "--cold-worker",
                    str(request),
                ],
                cwd=base.LAB,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            (case / "cold-worker.log").write_text(completed.stdout + completed.stderr)
            assert completed.returncode == 0, completed.stderr
            cold = base.read_json(case / "cold-result.json")
            assert cold["pid"] != os.getpid() and cold["head"]["payload"] == saved["payload"]
            assert "unrelated" not in cold["B"]["payload"]
            a = cold["A"].copy()
            assert a.pop("prefetched_detail")["text"] == (workspace / "details.md").read_text()
            assert a == cold["B"]
            checks[kind + "_public_roundtrip_noop_cas_replay_cold_assembly"] = True

        faults = directory / "faults"
        faults.mkdir()
        workspace = faults / "workspace"
        workspace.mkdir()
        (workspace / "handoff.md").write_text("New state")
        (workspace / "details.md").write_text("Persisted detail")
        with observer(root / "product", faults, "eng-faults", "eng-faults") as (call, _):
            for mode in ("lost", "confirmed_advanced"):
                writes = []

                def faulty(tool, args, mode=mode, writes=writes):
                    response = call(tool, args)
                    if tool == "milai_working_state_update":
                        writes.append(response)
                        advanced = call(
                            tool,
                            {
                                "scope": "TASK",
                                "state_id": response["state_id"],
                                "expected_version": response["version"],
                                "operation_id": "advance-" + mode,
                                "payload": {"newer": mode},
                            },
                        )
                        assert advanced["version"] == response["version"] + 1
                        if mode == "lost":
                            raise TimeoutError(
                                "Injected response loss after confirmed server commit"
                            )
                    return response

                result = save_layers(faulty, workspace, config, {}, "fault-" + mode)
                write_json(
                    faults / (mode + ".json"), {"adapter": result, "observer_receipts": writes}
                )
                assert len(writes) == 1 and not result["comparison_opportunity"]
                expected = "UNKNOWN" if mode == "lost" else "CONFIRMED"
                assert result["operation"]["outcome"] == expected
                assert result["head_observation"]["value"]["version"] == writes[0]["version"] + 1
                checks[mode + "_op_head_separated"] = True

        branches = {}
        for arm in ("a", "b"):
            branch = directory / ("isolation-" + arm)
            branch.mkdir()
            project = "eng-isolation-" + arm
            workspace = branch / "workspace"
            workspace.mkdir()
            marker = "E2E_PRIVATE_CANARY_" + arm + "_6fe902"
            (workspace / "private.txt").write_text(marker)
            (workspace / "independent.txt").write_text("Independent allowed file")
            with observer(root / "product", branch, project, project) as (call, env):
                cap = capture(call, project, marker)
                receipt = call(
                    "milai_working_state_update",
                    {
                        "state_id": None,
                        "expected_version": 0,
                        "operation_id": project + "-save",
                        "scope": "TASK",
                        "payload": {"text": marker, "evidence_refs": [cap["evidence_id"]]},
                    },
                )
                assert receipt.get("version") == 1
                info = metadata(env, cap["evidence_id"])
                assert info["speaker"] == "user" and info["observed_at"].startswith(
                    "2026-09-06T02:00:00"
                )
                branches[arm] = {
                    "project": project,
                    "ref": cap["evidence_id"],
                    "marker": marker,
                    "receipt": receipt,
                    "metadata": info,
                    "workspace": str(workspace),
                }
        write_json(directory / "branch-mapping.json", branches)
        for arm, other in (("a", "b"), ("b", "a")):
            b, foreign = branches[arm], branches[other]
            check_dir = directory / ("check-" + arm)
            check_dir.mkdir()
            workspace = Path(b["workspace"])
            with observer(root / "product", check_dir, b["project"], b["project"]) as (call, env):
                result = call("milai_memory_resolve", {"query": foreign["marker"]})
                assert foreign["marker"] not in json.dumps(result, ensure_ascii=False)
                head = call("milai_working_state_get", {})
                denied = call(
                    "milai_working_state_update",
                    {
                        "scope": "TASK",
                        "state_id": head["state_id"],
                        "expected_version": head["version"],
                        "operation_id": b["project"] + "-foreign",
                        "payload": {"evidence_refs": [foreign["ref"]]},
                    },
                )
                assert "EVIDENCE_REFERENCE_INVALID" in json.dumps(denied)
                guard = FileDisclosure(
                    b["project"],
                    {"private.txt": [b["ref"]], "independent.txt": []},
                    partial(metadata, env),
                )
                action = {"tool": "read_file", "arguments_json": '{"path":"private.txt"}'}
                assert (
                    b["marker"]
                    in dispatch(workspace, manifest(workspace), {}, call, action, guard)["text"]
                )
                revoke = call(
                    "milai_evidence_revoke",
                    {
                        "evidence_id": b["ref"],
                        "operation_id": b["project"] + "-revoke",
                        "reason_code": "USER_REQUEST",
                        "confirmation": "REVOKE",
                    },
                )
                assert not revoke.get("mcp_error")
                withheld = call("milai_working_state_get", {})
                assert withheld["payload"] == {} and withheld["payload_withheld"]
                replay = call(
                    "milai_working_state_update",
                    {
                        "scope": "TASK",
                        "state_id": None,
                        "expected_version": 0,
                        "operation_id": b["project"] + "-save",
                        "payload": {"text": b["marker"], "evidence_refs": [b["ref"]]},
                    },
                )
                assert replay["replayed"] and replay["payload"] == {} and replay["payload_withheld"]
                for attempt in (
                    partial(dispatch, workspace, manifest(workspace), {}, call, action, guard),
                    guard.before_request,
                ):
                    try:
                        attempt()
                    except LocalGateError:
                        pass
                    else:
                        raise AssertionError("Revoked derived content could be disclosed")
                fresh = FileDisclosure(
                    b["project"],
                    {"private.txt": [b["ref"]], "independent.txt": []},
                    partial(metadata, env),
                )
                assert "private.txt" not in fresh.visible(manifest(workspace))
                independent = dispatch(
                    workspace,
                    {},
                    {},
                    call,
                    {"tool": "read_file", "arguments_json": '{"path":"independent.txt"}'},
                    fresh,
                )
                assert independent["text"] == "Independent allowed file"
                try:
                    dispatch(
                        workspace,
                        {},
                        {},
                        call,
                        {
                            "tool": "read_file",
                            "arguments_json": '{"path":"../isolation-'
                            + other
                            + '/workspace/private.txt"}',
                        },
                        fresh,
                    )
                except LocalGateError:
                    pass
                else:
                    raise AssertionError("Cross-workspace path accepted")
                write_json(
                    check_dir / "result.json",
                    {
                        "search": result,
                        "foreign_reference": denied,
                        "get_after_revoke": withheld,
                        "replay_after_revoke": replay,
                        "independent_read": independent,
                        "file_and_context_denied": True,
                    },
                )
                checks[arm + "_cross_project_revocation_and_file_guard"] = True
        results["status"] = "PARTIAL_ENGINEERING_CHECKS_PASS"
    except Exception as exc:
        results.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        write_json(directory / "result.json", results)
        print(
            json.dumps({"status": results["status"], "checks": checks, "model_requests": 0}),
            flush=True,
        )


def followup(root: Path) -> None:
    directory = root / "live-followup"
    directory.mkdir(exist_ok=False)
    config = base.read_json(CONFIG)
    mapping = []
    # Same historical content/attribution/time in independently permitted project scopes.
    for arm in ("a", "b"):
        branch = directory / arm
        branch.mkdir()
        project = "eng-common-" + arm
        with observer(root / "product", branch, project, project) as (call, env):
            cap = capture(call, project, "COMMON_HISTORY_ORIGINAL_TIME_NO_FUTURE_ANSWER")
            record = metadata(env, cap["evidence_id"])
            mapping.append({"arm": arm, "project": project, "receipt": cap, "source": record})
    for key in (
        "content",
        "speaker",
        "subject_id",
        "observed_at",
        "source_type",
        "retention_state",
    ):
        assert mapping[0]["source"][key] == mapping[1]["source"][key]
    for entry in mapping:
        permission = entry["source"]["permission_snapshot"]
        assert permission["readable"] is True
        assert permission["project_ids"] == [entry["project"]]
    write_json(directory / "same-source-mapping.json", mapping)

    case = directory / "orphan-detail"
    case.mkdir()
    workspace = case / "workspace"
    workspace.mkdir()
    (workspace / "handoff.md").write_text("Candidate reusable content")
    (workspace / "details.md").write_text("Detail successfully written before L1 attempt")
    with observer(root / "product", case, "eng-orphan", "eng-orphan") as (call, _):
        intervening = []

        def stale(tool, args):
            if tool == "milai_working_state_update":
                intervening.append(
                    call(
                        tool,
                        {
                            **args,
                            "operation_id": "eng-orphan-other",
                            "payload": {"keep": "newer work"},
                        },
                    )
                )
            return call(tool, args)

        outcome = save_layers(stale, workspace, config, {}, "eng-orphan-candidate")
        assert outcome["operation"]["outcome"] == "REJECTED"
        assert outcome["head_observation"]["value"]["payload"] == {"keep": "newer work"}
        assert outcome["detail_observation"]["sha256"] == manifest(workspace)["details.md"]
        write_json(
            case / "result.json",
            {
                "adapter": outcome,
                "intervening": intervening,
                "unreferenced_detail": outcome["detail_observation"],
            },
        )

    branches = base.read_json(root / "live-after/branch-mapping.json")
    for arm in ("a", "b"):
        case = directory / ("revoked-cold-" + arm)
        case.mkdir()
        b = branches[arm]
        request = case / "cold-request.json"
        write_json(
            request, {"project": b["project"], "task": b["project"], "expect_withheld": True}
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--root",
                str(root),
                "--cold-worker",
                str(request),
            ],
            cwd=base.LAB,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        (case / "worker.log").write_text(completed.stdout + completed.stderr)
        assert completed.returncode == 0, completed.stderr
        assert base.read_json(case / "cold-result.json")["pid"] != os.getpid()
    write_json(
        directory / "result.json",
        {
            "status": "FOLLOWUP_ENGINEERING_CHECKS_PASS",
            "model_requests": 0,
            "checks": {
                "public_single_source_remap": True,
                "l2_success_l1_cas_failure": True,
                "revoked_state_new_process_a_b": True,
            },
            "limits": [
                "Single-source mapping only; full-history ordering not yet verified",
                "JSON-action Host only; native Host sandbox and billing not established",
            ],
        },
    )
    print("FOLLOWUP_ENGINEERING_CHECKS_PASS", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cold-worker", type=Path)
    parser.add_argument("--followup", action="store_true")
    parser.add_argument("--service-calibration", action="store_true")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.service_calibration:
        service_calibration(args.root.resolve(), args.config.resolve() if args.config else None)
    elif args.cold_worker:
        cold_worker(args.root.resolve(), args.cold_worker.resolve())
    elif args.followup:
        followup(args.root.resolve())
    else:
        run(args.root.resolve())


if __name__ == "__main__":
    main()
