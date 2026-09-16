"""One isolated native Codex session through the observed, budgeted Unix gateway."""

# ruff: noqa: S603,S607 -- Operator-owned isolated Docker launch and exact-name cleanup.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socketserver
import subprocess
import time
import tomllib
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from check_v02_native_protocol import CODEX, config, container_command
from v02_deadline import DeadlineExpired
from v02_local_provider import LocalGateError, accounting, read_events, write_json
from v02_native_bridge import socket_path
from v02_native_mcp import connection
from v02_responses_budget import ResponsesBudget


def run(root: Path, allocation: dict, prompt: str, session: str, *, transport=None,
        mcp: dict | None = None, workspace: Path | None = None,
        resume_home: Path | None = None, resume_thread: str | None = None) -> dict:
    ledger_root = root
    if allocation.get("run_root"):
        expected = Path(__file__).resolve().parents[1] / allocation["run_root"]
        directory = allocation.get("session_directories", {}).get(session, session)
        allowed = {expected.resolve(), (expected / directory).resolve()}
        if root.resolve() not in allowed:
            raise LocalGateError("ALLOCATION_RUN_ROOT_MISMATCH_NO_REPLAY")
        ledger_root = expected.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for directory in ("home", "workspace", "sockets"):
        (root / directory).mkdir()
    if workspace:
        shutil.copytree(workspace, root / "workspace", dirs_exist_ok=True, symlinks=True)
    if resume_home:
        shutil.copytree(resume_home, root / "home", dirs_exist_ok=True, symlinks=True)
    initial_files = {}
    for path in sorted((root / "workspace").rglob("*")):
        if path.is_symlink():
            initial_files[str(path.relative_to(root / "workspace"))] = {
                "symlink": str(path.readlink())}
        elif path.is_file():
            initial_files[str(path.relative_to(root / "workspace"))] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(root / "initial-files.json", initial_files)
    started = time.monotonic()
    end = started + allocation["session_deadline_seconds"]
    native_config = config()
    instructions = []
    if allocation.get("workflow_profile"):
        profile = Path(__file__).resolve().parents[1] / allocation["workflow_profile"]
        instruction = tomllib.loads(profile.read_text())["developer_instructions"]
        instructions.append(instruction)
    if allocation.get("host_bootstrap"):
        if mcp is None:
            raise LocalGateError("HOST_BOOTSTRAP_REQUIRES_EXISTING_MCP")
        lab = Path(__file__).resolve().parents[1]
        product_python = lab.parent / "MiLAi-Product/integrations/mcp/.venv/bin/python"
        output = root / "host-bootstrap.json"
        began = time.monotonic()
        prepared = subprocess.run([str(product_python), str(lab / "tools/v06_http_bootstrap.py"),
            "--url", mcp["url"], "--output", str(output)], capture_output=True, text=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "MILAI_MCP_BEARER_TOKEN": mcp["token"]}, timeout=22, check=False)
        write_json(root / "host-bootstrap-status.json", {
            "trigger": "HOST_LIFECYCLE", "returncode": prepared.returncode,
            "seconds": time.monotonic() - began, "stderr": prepared.stderr})
        if prepared.returncode:
            raise LocalGateError("PUBLIC_HOST_BOOTSTRAP_NOT_CONFIRMED")
        instructions.append(json.loads(output.read_text())["context"])
    if instructions:
        native_config = ("developer_instructions = " + json.dumps("\n\n".join(instructions))
                         + "\n" + native_config)
    if mcp:
        # Only this synthetic test user's credential enters its private client home.
        native_config += ('\n[mcp_servers.milai]\nurl = ' + json.dumps(mcp["url"]) + '\n'
                          'startup_timeout_sec = 20\ntool_timeout_sec = 20\n'
                          '[mcp_servers.milai.http_headers]\nAuthorization = '
                          + json.dumps("Bearer " + mcp["token"]) + '\n')
    config_file = root / "home/config.toml"
    config_file.touch(mode=0o600)
    config_file.write_text(native_config)
    write_json(root / "allocation.json", allocation)
    (root / "prompt.txt").write_text(prompt)
    budget = ResponsesBudget(ledger_root, allocation, session, transport=transport, session_end=end)
    implementation = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [Path(__file__), *[Path(__file__).with_name(name) for name in (
            "v02_native_bridge.py", "v02_native_mcp.py", "v02_qwen_response.py",
            "v02_responses_budget.py", "v02_local_provider.py", "v02_deadline.py",
            "check_v02_native_protocol.py")]]}
    write_json(root / "implementation.json", implementation)
    report = {"status": "STARTED", "session": session, "requests": [],
              "resume_thread": resume_thread,
              "provider_kind": "FIXED_TRANSPORT" if transport else "REAL_LOCAL_VLLM",
              "codex_sha256": hashlib.sha256(CODEX.read_bytes()).hexdigest()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            self.request.settimeout(max(0.01, min(1, end - time.monotonic())))
            super().setup()

        def do_POST(self):
            number = len(report["requests"]) + 1
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            (root / f"native-request-{number}.bin").write_bytes(raw)
            observation = {"path": self.path, "sha256": hashlib.sha256(raw).hexdigest(),
                           "started_seconds": time.monotonic() - started}
            report["requests"].append(observation)
            try:
                if self.path != "/v1/responses" or self.headers.get("Content-Encoding"):
                    raise LocalGateError("UNSUPPORTED_NATIVE_REQUEST_TRANSPORT")
                code, body, content_type = budget.forward(json.loads(raw))
                if time.monotonic() >= end:
                    raise DeadlineExpired("SESSION_DEADLINE_BEFORE_DELIVERY")
                observation["status"] = "DELIVERED"
            except (Exception, DeadlineExpired) as exc:
                observation.update(status="STOPPED", error_type=type(exc).__name__)
                if isinstance(exc, (LocalGateError, DeadlineExpired)):
                    observation["reason"] = str(exc)
                report["status"] = "STOPPED_WITH_FAILURE"
                code, content_type = 400, "application/json"
                message = observation.get("reason", "LOCAL_FORWARDING_FAILED_NO_RETRY")
                body = json.dumps({"error": {"type": "invalid_request_error",
                                            "message": message}}).encode()
            observation["finished_seconds"] = time.monotonic() - started
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    name = "milai-native-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    report["container_name"] = name
    process = None
    try:
        with socket_path(root / "sockets", "provider.sock") as address, (
            connection(root, mcp["url"]) if mcp else nullcontext()
        ), (
            socketserver.UnixStreamServer(address, Handler)
        ) as server, (
            root / "client-events.jsonl"
        ).open("w") as stdout, (root / "client-stderr.txt").open("w") as stderr:
            server.timeout = 0.1
            mcp_port = urlsplit(mcp["url"]).port if mcp else None
            command = container_command(root, name, prompt=prompt, mcp_port=mcp_port,
                                        resume_thread=resume_thread)
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
            report["launcher_pid"] = process.pid
            while process.poll() is None and report["status"] == "STARTED":
                if time.monotonic() >= end:
                    raise DeadlineExpired("SESSION_DEADLINE_NATIVE_TOOLS_OR_DELIVERY")
                server.handle_request()
            report["client_exit_code"] = process.poll()
            if report["status"] == "STARTED":
                report["status"] = "COMPLETED" if process.returncode == 0 else "CLIENT_FAILED"
    except (Exception, DeadlineExpired) as exc:
        report.update(status="STOPPED_WITH_FAILURE", error_type=type(exc).__name__)
        if isinstance(exc, (LocalGateError, DeadlineExpired)):
            report["reason"] = str(exc)
    finally:
        report["online_seconds"] = time.monotonic() - started
        budget.close()
        subprocess.run(["docker", "stop", "--time", "1", name], capture_output=True,
                       timeout=10, check=False)
        if process is not None:
            report["terminal_launcher_exit"] = process.wait(timeout=10)
        terminal = subprocess.run(["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
                                  capture_output=True, timeout=10, check=False)
        report["container_absent"] = terminal.returncode == 0 and not terminal.stdout.strip()
        report["accounting"] = accounting(read_events(ledger_root / "provider-ledger.jsonl"))
        report["total_seconds_including_cleanup"] = time.monotonic() - started
        write_json(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), json.loads(args.allocation.read_text()),
                         args.prompt.read_text(), args.session)))
