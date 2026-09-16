#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

MARKER = "P08-CEDAR-731"
FIRST_PART = "P08-PART-A"
SECOND_PART = "P08-PART-B"
FIRST_CONTEXT_ID = "33333333-3333-4333-8333-333333333333"


class _RuntimeHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []
    paths: ClassVar[list[str]] = []
    scenario: ClassVar[str] = "memory-required"

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _reply(self, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        type(self).paths.append(self.path)
        if self.path != "/v1/capabilities":
            self.send_error(404)
            return
        self._reply(
            {
                "api_version": "1",
                "contract_version": "agent.v1",
                "runtime_version": "0.1.0",
                "profile": "local",
                "capabilities": ["memory:read"],
                "routes": ["L0", "L1"],
                "consistency_modes": ["EVENTUAL", "CANONICAL_REQUIRED"],
                "agent_profiles": ["agent-memory"],
                "features": {},
                "limits": {},
                "data_mode": "SYNTHETIC_ONLY",
                "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                "implementation_status": "0.1.x CANDIDATE",
            }
        )

    def do_POST(self) -> None:
        type(self).paths.append(self.path)
        if self.path != "/v1/memory/resolve":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            self.send_error(400)
            return
        type(self).requests.append(payload)
        previous_context_id = payload.get("previous_context_id")
        if type(self).scenario == "continuation" and previous_context_id is None:
            marker = FIRST_PART
            context_id: str | None = FIRST_CONTEXT_ID
            continuation: dict[str, object] | None = {
                "available": True,
                "reason": "UNEXPANDED_FRONTIER",
            }
        elif type(self).scenario == "continuation":
            marker = SECOND_PART
            context_id = "44444444-4444-4444-8444-444444444444"
            continuation = {
                "available": False,
                "reason": "FRONTIER_EXHAUSTED",
            }
        else:
            marker = MARKER
            context_id = None
            continuation = None
        evidence_id = (
            "55555555-5555-4555-8555-555555555555"
            if marker == SECOND_PART
            else "11111111-1111-4111-8111-111111111111"
        )
        body = {
            "schema_version": "access-outcome-v0.1",
            "status": "PARTIAL",
            "availability": "AVAILABLE",
            "items": [],
            "open_issue_ids": [],
            "evidence_refs": [evidence_id],
            "canonical_position": {"canonical_outbox_sequence": 9},
            "trace_id": "22222222-2222-4222-8222-222222222222",
            "degraded_components": [],
            "abstention_reason": "SEMANTIC_COMPLETENESS_NOT_ASSERTED",
            # This black-box E2E tests the MCP facade rather than Runtime receipt
            # parsing. A partial receipt would be invalid and obscure the boundary
            # under test, so the synthetic Runtime truthfully provides none.
            "context_receipt": None,
            "context_id": context_id,
            "continuation": continuation,
            "memory_context": {
                "schema_version": "memory-context-v0.1",
                "authority_class": "EVIDENCE_ONLY",
                "text": f"[E1] The synthetic deployment marker part is {marker}.",
                "selected_evidence_ids": [evidence_id],
                "selected_source_turn_refs": ["agent-session:p08/turn:1"],
                "windows": [
                    {
                        "window_id": "p08-window-1",
                        "session_id": "p08-session",
                        "evidence_ids": [evidence_id],
                        "source_turn_refs": ["agent-session:p08/turn:1"],
                        "text": f"The synthetic deployment marker part is {marker}.",
                        "observed_at": "2026-09-03T10:00:00Z",
                    }
                ],
            },
            "memory_intent": "REQUIRED",
            "requirement": "SEARCH",
            "consistency": payload.get("consistency_mode"),
            "access_trace": {
                "schema_version": "access-trace-v0.1",
                "runtime_request_id": "p08-runtime-request",
                "retrieval_trace_id": "22222222-2222-4222-8222-222222222222",
                "spans": {"runtime_kernel_ms": 1.0},
            },
            "request_id": "p08-runtime-request",
            "fallback_used": False,
            "fallback_reason": None,
        }
        self._reply(body)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_http_server(process: subprocess.Popen[str], url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("MiLAi HTTP MCP process exited before readiness")
        try:
            with urllib.request.urlopen(  # noqa: S310 -- URL is harness-built loopback
                url, timeout=1
            ) as response:
                payload = json.load(response)
                if isinstance(payload, dict) and payload.get("status") == "ready":
                    return payload
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise TimeoutError("MiLAi HTTP MCP readiness deadline exceeded")


def run(
    codex: Path,
    mcp: Path,
    *,
    scenario: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    _RuntimeHandler.requests = []
    _RuntimeHandler.paths = []
    _RuntimeHandler.scenario = scenario
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    mcp_port = _free_port()
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
    inbound_token = secrets.token_urlsafe(32)
    mcp_environment = dict(os.environ)
    mcp_environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
            "MILAI_AGENT_TOKEN": "synthetic-p08-runtime-token-at-least-32-characters",
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["p08-synthetic"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_MCP_HTTP_BEARER_TOKEN": inbound_token,
            "MILAI_MCP_HTTP_PRINCIPAL_ID": "codex-p08-e2e",
        }
    )
    mcp_process = subprocess.Popen(  # noqa: S603 - explicit harness executable
        [
            str(mcp),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(mcp_port),
            "--profile",
            "agent-memory",
            "--max-retries",
            "0",
            "--resolve-budget-profile",
            "MCP_INTERACTIVE_STANDARD_V01",
        ],
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=mcp_environment,
    )
    mcp_stdout = ""
    mcp_stderr = ""
    readiness: dict[str, Any] | None = None
    try:
        readiness = _wait_for_http_server(
            mcp_process, f"http://127.0.0.1:{mcp_port}/readyz"
        )
        with tempfile.TemporaryDirectory(prefix="milai-p08-codex-") as temporary:
            last_message = Path(temporary) / "last-message.txt"
            host_environment = dict(os.environ)
            host_environment["MILAI_MCP_CODEX_TOKEN"] = inbound_token
            prompts = {
                "memory-required": (
                    "This is a synthetic MCP integration check. Use the MiLAi MCP server and call "
                    "milai_memory_resolve exactly once to retrieve the deployment marker. Do not "
                    "use shell, files, web, or prior knowledge. Return only the marker string "
                    "contained in the returned evidence."
                ),
                "no-memory": (
                    "This is a synthetic MCP integration control. Compute 2 + 2 without using any "
                    "tool or historical memory. Return only the decimal result."
                ),
                "continuation": (
                    "Use only MiLAi memory evidence to retrieve the complete two-part synthetic "
                    "deployment marker. Call milai_memory_resolve first. Make a focused second "
                    "call with previous_context_id only if MiLAi explicitly reports an available "
                    "continuation. Return only PART-A and PART-B joined by a vertical bar."
                ),
            }
            prompt = prompts[scenario]
            command = [
                str(codex),
                "--approve-for-me",
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--sandbox",
                "read-only",
                "--json",
                "--output-last-message",
                str(last_message),
                "-c",
                f"mcp_servers.milai.url={json.dumps(mcp_url)}",
                "-c",
                'mcp_servers.milai.bearer_token_env_var="MILAI_MCP_CODEX_TOKEN"',
                "-c",
                "mcp_servers.milai.required=true",
                "-c",
                'mcp_servers.milai.enabled_tools=["milai_memory_resolve"]',
                prompt,
            ]
            codex_started = time.perf_counter()
            completed = subprocess.run(  # noqa: S603 - explicit harness executable
                command,
                text=True,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                env=host_environment,
                timeout=timeout_seconds,
                check=False,
            )
            codex_latency_ms = round((time.perf_counter() - codex_started) * 1_000, 3)
            answer = (
                last_message.read_text(encoding="utf-8").strip() if last_message.exists() else ""
            )
    finally:
        mcp_process.terminate()
        try:
            mcp_stdout, mcp_stderr = mcp_process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            mcp_process.kill()
            mcp_stdout, mcp_stderr = mcp_process.communicate(timeout=5)
        runtime.shutdown()
        runtime.server_close()
        thread.join(timeout=5)

    tool_arguments: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if (
            isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("tool") == "milai_memory_resolve"
            and item.get("status") in {"completed", "failed"}
            and isinstance(item.get("arguments"), dict)
        ):
            tool_arguments.append(item["arguments"])
    model_argument_keys = [sorted(arguments) for arguments in tool_arguments]
    tool_event_seen = bool(tool_arguments)
    arguments_are_narrow = all(
        set(arguments) <= {"query", "previous_context_id"} for arguments in tool_arguments
    )
    if scenario == "memory-required":
        expected_answer = MARKER
        scenario_passed = (
            answer == expected_answer
            and len(_RuntimeHandler.requests) == 1
            and len(tool_arguments) == 1
        )
    elif scenario == "no-memory":
        expected_answer = "4"
        scenario_passed = (
            answer == expected_answer and not _RuntimeHandler.requests and not tool_arguments
        )
    else:
        expected_answer = f"{FIRST_PART}|{SECOND_PART}"
        scenario_passed = (
            answer == expected_answer
            and len(_RuntimeHandler.requests) == 2
            and len(tool_arguments) == 2
            and _RuntimeHandler.requests[1].get("previous_context_id") == FIRST_CONTEXT_ID
        )
    passed = completed.returncode == 0 and arguments_are_narrow and scenario_passed
    return {
        "schema_version": "milai-product08-codex-http-mcp-e2e-v1",
        "scenario": scenario,
        "passed": passed,
        "codex_version": _version(codex),
        "mcp_command": str(mcp),
        "mcp_transport": "streamable-http",
        "mcp_url": mcp_url,
        "mcp_ready": readiness == {"status": "ready", "service": "milai-mcp"},
        "mcp_process_returncode": mcp_process.returncode,
        "runtime_request_count": len(_RuntimeHandler.requests),
        "runtime_paths": list(_RuntimeHandler.paths),
        "runtime_query_present": all(
            isinstance(request.get("query"), str) and bool(request["query"].strip())
            for request in _RuntimeHandler.requests
        ),
        "model_argument_keys": model_argument_keys,
        "tool_event_seen": tool_event_seen,
        "answer_exact": answer == expected_answer,
        "answer": answer,
        "returncode": completed.returncode,
        "codex_latency_ms": codex_latency_ms,
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-2_000:],
        "mcp_stdout_tail": mcp_stdout[-2_000:],
        "mcp_stderr_tail": mcp_stderr[-2_000:],
    }


def _version(command: Path) -> str:
    completed = subprocess.run(  # noqa: S603 - explicit harness executable
        [str(command), "--version"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return (completed.stdout or completed.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one real Codex → MiLAi Streamable HTTP MCP E2E"
    )
    parser.add_argument("--codex", type=Path, default=Path(shutil.which("codex") or "codex"))
    parser.add_argument("--mcp", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("memory-required", "no-memory", "continuation"),
        default="memory-required",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(
        args.codex,
        args.mcp,
        scenario=args.scenario,
        timeout_seconds=args.timeout_seconds,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
