"""Frozen ordinary workspaces and native sessions; public private MCP, no state seeding."""

# ruff: noqa: S603,S607 -- Fixed local tools, isolated evaluator and exact owned cleanup.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

from check_v02_native_mcp import state_records
from check_v02_native_protocol import IMAGE
from run_v02_native_session import run as native_session
from v02_local_provider import accounting, read_events, write_json


def evaluate(root: Path, phase: str, checker: Path) -> dict:
    name = "milai-eval-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory", "1g", "--cpus", "2",
        "--tmpfs", "/tmp:rw,nosuid,size=128m",  # noqa: S108 -- private container
        "--mount", f"type=bind,src={root / 'workspace'},dst=/workspace,readonly",
        "--mount", f"type=bind,src={checker},dst=/check_delivery.py,readonly",
        "--workdir", "/workspace", "--entrypoint", "/usr/bin/python3", IMAGE,
        "/check_delivery.py", phase]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        value = {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        write_json(root / "delivery-check.json", value)
        return value
    finally:
        subprocess.run(["docker", "stop", "--time", "1", name],
                       capture_output=True, timeout=10, check=False)


def observe(root: Path, phase: str, *, directory: Path | None = None, cold: bool = True) -> dict:
    directory = directory or root / phase
    calls, presented = [], []
    for path in sorted(directory.glob("native-request-*.bin")):
        request = json.loads(path.read_bytes())
        for item in request["input"]:
            if item.get("type") == "function_call_output":
                presented.extend({"request": path.name, "call_id": item["call_id"], "state": state}
                                 for state in state_records(item["output"]))
    for path in sorted(root.glob(phase + "-*-decoded.json")):
        response = json.loads(path.read_text())
        calls.extend({"response": path.name, **item} for item in response["output"]
                     if item["type"] == "function_call")
    first = json.loads((directory / "native-request-1.bin").read_bytes())
    clean = not any(item.get("type") in {"function_call", "function_call_output"}
                    for item in first["input"])
    if cold:
        assert clean
    return {"calls": calls, "presented_states": presented,
            "cold_first_request_has_no_prior_tool_history": clean}


def run(root: Path, config_path: Path) -> dict:
    import run_v02_memory_flow as base
    from run_v02_local_vllm import stop_owned

    config = base.read_json(config_path)
    assert root == (base.LAB / config["run_root"]).resolve()
    fixture = base.LAB / config["task_fixture"]
    resuming = config.get("resume_G_thread")
    reopening = bool(resuming or config.get("reuse_service"))
    if resuming:
        previous = base.read_json(root / "G/result.json")
        assert previous["status"] == "STOPPED_WITH_FAILURE" and previous["container_absent"]
        assert previous["requests"][-1]["reason"] == "TOKEN_LIMIT_BEFORE_DISPATCH"
    if reopening:
        for phase in config["local_sessions"]:
            directory = root / config["session_directories"][phase]
            if directory.exists():
                raise FileExistsError("Execution segment already exists: " + str(directory))
    else:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    prefix = (config.get("execution_prefix") or config["session_directories"]["G"]) + "-" \
        if reopening else ""
    write_json(root / (prefix + "allocation.json"), config)
    manifest = {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(fixture.rglob("*")) if path.is_file()}
    if reopening:
        assert manifest == base.read_json(root / "frozen-task-manifest.json")
    else:
        write_json(root / "frozen-task-manifest.json", manifest)
    service = root / (root.name + "-product")
    group = base.ProcessGroup(root)
    report = {"status": "STARTED", "sessions": {},
              "arm": "NATIVE_CODEX_REAL_LOCAL_VLLM_PRIVATE_MCP",
              "authentication": "SYNTHETIC_AS_REAL_SIGNATURE_NOT_PUBLIC_OAUTH"}
    started = time.monotonic()
    try:
        if reopening:
            base.pin(config_path)
            ledger = accounting(read_events(root / "provider-ledger.jsonl"))
            assert not ledger["pending"] and not ledger["violations"]
            compose = base.read_json(service / "compose-command.json")
            base._command([*compose, "up", "--detach", "--wait", "postgres"], cwd=base.RUNTIME)
            env = base._clean_environment(base._load_environment(service / "runtime.env"))
            api = group.start("api", [str(base.API_EXE)], cwd=base.RUNTIME, env=env)
            worker = group.start("worker", [str(base.WORKER_EXE)], cwd=base.RUNTIME, env=env)
            write_json(service / "services.json", {"api": api.pid, "worker": worker.pid})
            base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        else:
            base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "SYNTHETIC_ONLY",
                                        "MILAI_REQUEST_TIMING_ENABLED": "true"})
        env = base._clean_environment(base._load_environment(service / "runtime.env"))
        port = base.read_json(root / "gateway.json")["port"] if reopening else base._free_port()
        url = f"http://127.0.0.1:{port}/mcp"
        write_json(root / "gateway.json", {"port": port, "url": url,
                   "resource": f"https://127.0.0.1:{port}/mcp", "scope_refs": {}})
        if reopening:
            # Only this fixture AS is reissued; issuer/sub and private State binding remain stable.
            (root / "synthetic-auth.json").rename(root / (prefix + "synthetic-auth-previous.json"))
        gateway_script = str(base.LAB / "tools/check_v02_private_http_load.py")
        gateway = group.start("private-mcp", [str(base.MCP / ".venv/bin/python"),
            gateway_script, "--gateway", "--root", str(root)], cwd=base.MCP, env=env)
        base._wait_http(f"http://127.0.0.1:{port}/readyz", gateway)
        token = base.read_json(root / "synthetic-auth.json")["tokens"]["ordinary"]
        resume_source = root / config.get("resume_source_directory",
                                          config.get("source_directory", "G"))
        workspace = resume_source / "workspace" if reopening else fixture / "G"
        if config.get("verify_source_head"):
            expected = base.read_json(resume_source / "public-state-after.json")
            actual = base.structured(asyncio.run(base.mcp_call(
                url, token, "milai_working_state_get", {"scope": "TASK"})))
            assert actual["state_version_id"] == expected["state_version_id"]
            write_json(root / (prefix + "baseline-head.json"), actual)
        for phase in config["local_sessions"]:
            prior = accounting(read_events(root / "provider-ledger.jsonl"))
            assert not prior["pending"] and not prior["violations"]
            continuing_g = bool(resuming and phase == "G")
            logical_phase = config.get("phase_roles", {}).get(phase, phase)
            directory = root / config.get("session_directories", {}).get(phase, phase)
            prompt = (config["resume_prompt"] if continuing_g
                      else (fixture / (logical_phase + "-prompt.txt")).read_text())
            current = native_session(directory, config, prompt, phase,
                mcp={"url": url, "token": token}, workspace=workspace,
                resume_home=resume_source / "home" if continuing_g else None,
                resume_thread=resuming if continuing_g else None)
            report["sessions"][phase] = current
            if current["status"] != "COMPLETED":
                report["status"] = "NATIVE_SESSION_NOT_COMPLETED"
                break
            delivery = evaluate(directory, logical_phase, fixture / "check_delivery.py")
            observed = observe(root, phase, directory=directory, cold=not continuing_g)
            write_json(directory / "memory-observation.json", observed)
            current["delivery_check_exit"] = delivery["exit_code"]
            current["memory_calls"] = [c["name"] for c in observed["calls"] if "milai" in c["name"]]
            if delivery["exit_code"]:
                report["status"] = "TASK_NECESSARY_CONDITIONS_FAILED"
                break
            after = base.structured(asyncio.run(base.mcp_call(
                url, token, "milai_working_state_get", {"scope": "TASK"})))
            write_json(directory / "public-state-after.json", after)
            if logical_phase == "G":
                saved_calls = {c["call_id"] for c in observed["calls"]
                               if c["name"].endswith("milai_working_state_update")}
                saved = [p["state"] for p in observed["presented_states"]
                         if p["call_id"] in saved_calls and not p["state"].get("payload_withheld")]
                if not saved:
                    report["status"] = "TASK_PASSED_NO_CONFIRMED_MEMORY_SAVE"
                    break
                assert any(v["state_version_id"] == after["state_version_id"] for v in saved)
            else:
                restored_calls = {c["call_id"] for c in observed["calls"]
                                  if c["name"].endswith("milai_working_state_get")}
                model_restored = any(p["call_id"] in restored_calls
                                     for p in observed["presented_states"])
                if config.get("host_bootstrap"):
                    prepared = base.read_json(directory / "host-bootstrap.json")
                    first = base.read_json(directory / "native-request-1.bin")
                    texts = [part["text"] for item in first["input"]
                             for part in item.get("content", []) if isinstance(part, dict)
                             and isinstance(part.get("text"), str)]
                    assert any(prepared["context"] in text for text in texts)
                    assert prepared["state"].get("status") == "ACTIVE"
                    current["recovery_trigger"] = "HOST_LIFECYCLE"
                    current["model_selected_state_get"] = model_restored
                    current["bootstrap_in_first_request"] = True
                elif not model_restored:
                    report["status"] = "TASK_PASSED_MEMORY_ACTIVATION_NOT_ESTABLISHED"
                    break
            workspace = directory / "workspace"
        else:
            report["status"] = "G_R_CHAIN_EXECUTED_PENDING_FIRST_ACTION_AND_DOCUMENTATION_AUDIT"
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        group.stop()
        report["cleanup"] = stop_owned(service)
        report["accounting"] = accounting(read_events(root / "provider-ledger.jsonl"))
        report["seconds_including_cleanup"] = time.monotonic() - started
        write_json(root / (prefix + "result.json"), report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = Path(__file__).resolve().parents[1] / config["run_root"]
    report = run(root.resolve(), args.config.resolve())
    print(json.dumps({k: v for k, v in report.items() if k != "sessions"}))
