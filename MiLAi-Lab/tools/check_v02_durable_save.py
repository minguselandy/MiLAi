"""Bounded public HTTP save -> worker-off read -> cold restart -> projection check."""

from __future__ import annotations

import argparse
import hashlib
import os
import signal
import time
from pathlib import Path

import httpx

import run_v02_memory_flow as base
from run_v02_local_vllm import stop_owned
from v02_inflight_request import interrupt_after_forward, verify_unknown_boundary

CONFIG = base.LAB / "configs/v02-durable-save.json"


def stop_process(service: Path, name: str, sig: int) -> dict:
    services = base.read_json(service / "services.json")
    pid = services[name]
    proc = Path(f"/proc/{pid}")
    assert str(service).encode() in (proc / "environ").read_bytes()
    assert f"milai-{name}".encode() in (proc / "cmdline").read_bytes()
    os.killpg(pid, sig)
    deadline = time.monotonic() + 10
    while proc.exists():
        os.waitpid(pid, os.WNOHANG)
        if time.monotonic() > deadline:
            raise TimeoutError("OWN_PROCESS_STOP_NOT_CONFIRMED")
        time.sleep(0.05)
    services.pop(name)
    base.write_json(service / "services.json", services)
    return {"pid": pid, "signal": sig, "terminal_confirmed": True}


def run(root: Path, config_path: Path = CONFIG) -> None:
    config = base.read_json(config_path)
    assert not config["model_transport_enabled"] and config["retries"] == 0
    assert config["evidence_count"] == len(config["payload_bytes"])
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(root / "config.json", config)
    base.write_json(root / "preflight.json", {
        "pin": base.pin(config_path),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fault_transport_sha256": hashlib.sha256(
            Path(__file__).with_name("v02_inflight_request.py").read_bytes()).hexdigest(),
    })
    service = root / (root.name + "-product")
    override = root / "compose-limits.yaml"
    override.write_text(
        "services:\n  postgres:\n    mem_limit: "
        + config["postgres_memory_limit"]
        + "\n    cpus: "
        + str(config["postgres_cpu_limit"])
        + "\n    network_mode: "
        + config["postgres_network_mode"]
        + "\n"
    )
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[: config["runtime_cpu_affinity_count"]])
    events: list[dict] = []
    report: dict = {"status": "RUNNING", "model_calls": 0, "tokenize_calls": 0}
    try:
        base.prepare(
            service,
            config_path=config_path,
            compose_override=override,
            runtime_overrides={
                "MILAI_DATA_MODE": config["data_mode"],
                "MILAI_API_THREADS": str(config["api_threads"]),
                "MILAI_DATABASE_POOL_MAX_SIZE": str(config["database_pool_max_size"]),
                "MILAI_FEATURE_PROFILE": config["feature_profile"],
                "MILAI_EMBEDDING_PROVIDER": config["embedding_provider"],
                "MILAI_RETRIEVAL_RERANKER_PROVIDER": config["retrieval_reranker_provider"],
                "MILAI_REQUEST_TIMING_ENABLED": "true",
            },
        )
        env = base._load_environment(service / "runtime.env")
        compose = base.read_json(service / "compose-command.json")
        report["worker_stop"] = stop_process(service, "worker", signal.SIGTERM)
        started = time.monotonic()

        def call(client, phase, method, path, payload=None, operation=None, expected=200):
            assert len(events) < config["max_http_calls"]
            assert time.monotonic() - started < config["max_measurement_seconds"]
            assert (
                sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
                < (config["max_artifact_bytes"])
            )
            begin = time.monotonic()
            event = {"phase": phase, "method": method, "path": path, "start_s": begin - started}
            events.append(event)
            try:
                response = client.request(
                    method,
                    path,
                    json=payload,
                    headers={"Idempotency-Key": operation} if operation else {},
                )
                event.update(status=response.status_code, response=response.json())
                assert response.status_code == expected, (phase, response.status_code)
                return response.json()
            finally:
                event["elapsed_ms"] = (time.monotonic() - begin) * 1000
                base.write_json(root / "http-events.json", events)

        def client():
            return httpx.Client(
                base_url=env["MILAI_BASE_URL"],
                headers={"Authorization": "Bearer " + env["MILAI_API_TOKEN"]},
                timeout=config["http_timeout_seconds"],
                trust_env=False,
            )

        def readiness(c, phase, targets, expected):
            return call(
                c,
                phase,
                "POST",
                "/v1/system/projection-readiness",
                {
                    "target_outbox_ids": targets,
                    "required_projections": ["evidence"],
                    "expected_versions": {"evidence": "evidence-search-v1"},
                    "timeout_ms": 0,
                },
                expected=expected,
            )

        payloads, receipts = [], []
        binding = {
            "principal_binding_digest": hashlib.sha256(b"durable-host").hexdigest(),
            "project_id": "durable-project",
            "scope_type": "TASK",
            "scope_ref": "resume",
        }
        with client() as c:
            for i, size in enumerate(config["payload_bytes"]):
                marker = "durablepublication" + str(i)
                content = marker + "\nfirst\n" + "x" * (size - len(marker) - 13) + "\nlast\n"
                assert len(content.encode()) == size
                payload = {
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": "durable://" + marker,
                    "subject_id": "durable-subject",
                    "content": content,
                    "observed_at": "2026-09-06T10:00:00+08:00",
                    "permission_snapshot": {"readable": True, "project_ids": ["durable-project"]},
                    "data_classification": "SYNTHETIC",
                }
                payloads.append(payload)
                saved = call(
                    c,
                    "save-worker-off",
                    "POST",
                    "/v1/evidence",
                    payload,
                    operation="capture-" + str(i),
                    expected=201,
                )
                receipts.append(saved)
                direct = call(c, "direct-worker-off", "GET", "/v1/evidence/" + saved["evidence_id"])
                assert direct["content"] == content
            targets = [r["outbox_id"] for r in receipts]
            pending = readiness(c, "pending-before-restart", targets, 408)
            assert pending["projection_work_started"] is False
            state_request = {
                **binding,
                "expected_version": 0,
                "payload": {
                    "first": "preserved",
                    "next": "recheck sources",
                    "last": "preserved",
                    "evidence_refs": [r["evidence_id"] for r in receipts],
                },
            }
            first = call(
                c,
                "state-v1",
                "POST",
                "/v1/working-state/update",
                state_request,
                operation="state-v1",
                expected=201,
            )
            second = call(
                c,
                "state-v2",
                "POST",
                "/v1/working-state/update",
                {
                    **state_request,
                    "state_id": first["state_id"],
                    "expected_version": 1,
                    "payload": {**state_request["payload"], "next": "continue task"},
                },
                operation="state-v2",
            )
            assert first["version"] == 1 and second["version"] == 2
        fault_request = None
        if config.get("interrupt_unacknowledged_state_update", False):
            fault_request = {**state_request, "state_id": first["state_id"],
                             "expected_version": 2,
                             "payload": {**state_request["payload"],
                                         "next": "resume interrupted operation"}}
            fault = interrupt_after_forward(
                env["MILAI_BASE_URL"], env["MILAI_API_TOKEN"], fault_request,
                "state-v3-interrupted",
                lambda: stop_process(service, "api", signal.SIGKILL),
                timeout=config["http_timeout_seconds"],
                phase=config.get("fault_phase", "AFTER_FORWARD"))
            base.write_json(root / "inflight-fault.json", fault)
            verify_unknown_boundary(fault, fault_request)
            report["api_crash"] = fault["fault"]
        else:
            report["api_crash"] = stop_process(service, "api", signal.SIGKILL)
        stopped = base._command([*compose, "stop", "postgres"], timeout=45)
        restarted = base._command([*compose, "up", "--detach", "--wait", "postgres"], timeout=60)
        (root / "postgres-restart.log").write_text(
            stopped.stdout + stopped.stderr + restarted.stdout + restarted.stderr
        )
        group = base.ProcessGroup(root)
        api = group.start(
            "cold-api", [str(base.API_EXE)], cwd=base.RUNTIME, env=base._clean_environment(env)
        )
        base.write_json(service / "services.json", {"api": api.pid})
        base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        report["cold_api_pid"] = api.pid
        with client() as c:
            assert (
                readiness(c, "pending-after-restart", targets, 408)["projection_work_started"]
                is False
            )
            for i, saved in enumerate(receipts):
                direct = call(c, "cold-direct", "GET", "/v1/evidence/" + saved["evidence_id"])
                assert direct["content"] == payloads[i]["content"]
                replay = call(
                    c,
                    "cold-capture-replay",
                    "POST",
                    "/v1/evidence",
                    payloads[i],
                    operation="capture-" + str(i),
                )
                assert replay["replayed"] is True
                assert all(replay[k] == saved[k] for k in ("evidence_id", "blob_id", "outbox_id"))
            replay = call(
                c,
                "old-state-operation-replay",
                "POST",
                "/v1/working-state/update",
                state_request,
                operation="state-v1",
            )
            head = call(c, "current-state-head", "POST", "/v1/working-state/get", binding)
            assert replay["version"] == 1 and replay["payload"] == first["payload"]
            assert head["version"] in ({2, 3} if fault_request else {2})
            assert head["payload"] == (
                fault_request["payload"] if head["version"] == 3 else second["payload"])
            if fault_request:
                # Explicit recovery exercise, not an implicit transport retry. GET alone
                # remains insufficient to attribute a commit to this operation identity.
                confirmed = call(c, "explicit-interrupted-operation-recovery", "POST",
                                 "/v1/working-state/update", fault_request,
                                 operation="state-v3-interrupted")
                assert confirmed["version"] == 3
                assert confirmed["payload"] == fault_request["payload"]
                assert confirmed["replayed"] is (head["version"] == 3)
                if config.get("fault_phase") == "AFTER_UPSTREAM_RESPONSE":
                    assert confirmed["replayed"]
                repeat = call(c, "confirmed-operation-idempotency", "POST",
                              "/v1/working-state/update", fault_request,
                              operation="state-v3-interrupted")
                current = call(c, "head-after-explicit-recovery", "POST",
                               "/v1/working-state/get", binding)
                assert repeat["replayed"]
                assert repeat["state_version_id"] == confirmed["state_version_id"]
                assert current["state_version_id"] == confirmed["state_version_id"]
                assert current["payload"] == fault_request["payload"]
                report["interrupted_recovery"] = {
                    "initial_client_outcome": "UNKNOWN", "head_before_recovery": head["version"],
                    "confirmed_by": "EXPLICIT_IDENTICAL_OPERATION_RECEIPT",
                    "previous_commit_confirmed_by_replay": confirmed["replayed"],
                    "recovered_version": 3, "repeat_did_not_increment": True,
                    "server_transaction_stage_at_kill": "NOT_OBSERVED"}
            for cycle in (1, 2):
                worker = base._command(
                    [str(base.WORKER_EXE), "--once"],
                    cwd=base.RUNTIME,
                    env=base._clean_environment(env),
                    timeout=config["worker_once_timeout_seconds"],
                )
                (root / f"worker-once-{cycle}.log").write_text(worker.stdout + worker.stderr)
                ready = readiness(c, "ready-cycle-" + str(cycle), targets, 200)
                assert ready["status"] == "READY" and not ready["projection_work_started"]
            for i, saved in enumerate(receipts):
                found = call(
                    c,
                    "indexed-recall",
                    "POST",
                    "/v1/memory/resolve",
                    {
                        "query": "durablepublication" + str(i),
                        "requested_scope": {"project_ids": ["durable-project"]},
                        "required_authority": "INFORMATIONAL",
                        "budget": {"max_results": 3, "max_context_tokens": 4096},
                    },
                )
                assert any(
                    item.get("evidence_id") == saved["evidence_id"]
                    and item.get("canonical") is False
                    for item in found["items"]
                )
        report.update(
            status="MECHANISM_CHECK_PASSED_NOT_P2_SLO",
            http_calls=len(events),
            state_index_status="NOT_APPLICABLE",
            evidence_projection="PENDING_THEN_READY",
            operation_replay_version=1,
            current_head_version=3 if fault_request else 2,
            power_loss="NOT_TESTED",
            mixed_load="NOT_TESTED",
            model_effect="NOT_TESTED",
        )
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        base.write_json(root / "result.json", report)
        cleanup = stop_owned(service)
        # Reap owned children so a zombie is not mistaken for a live service.
        for stopped in cleanup["stop_signals"]:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    done, _ = os.waitpid(stopped["pid"], os.WNOHANG)
                except ChildProcessError:
                    break
                if done:
                    break
                time.sleep(0.05)
        cleanup["running_containers"] = base._command(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + service.name + "-pg",
            ]
        ).stdout.strip()
        services = service / "services.json"
        cleanup["remaining_live_processes"] = [
            p
            for p in (base.read_json(services) if services.exists() else {}).values()
            if Path(f"/proc/{p}").exists()
        ]
        base.write_json(root / "cleanup.json", cleanup)
        os.sched_setaffinity(0, affinity)
        assert not cleanup["running_containers"] and not cleanup["remaining_live_processes"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    run(args.root.resolve(), args.config.resolve())
