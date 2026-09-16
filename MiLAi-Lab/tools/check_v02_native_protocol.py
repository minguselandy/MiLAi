"""Observe the real Codex request in a networkless container; Provider is a fixed fixture."""

# ruff: noqa: S603,S607 -- Fixed operator-owned Docker command, no model shell expansion.

from __future__ import annotations

import argparse
import hashlib
import json
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from v02_local_provider import write_json

LAB = Path(__file__).resolve().parents[1]
CODEX = Path("/root/.local/bin/codex").resolve()
IMAGE = "milai-lab-readable:v0204"


def container_command(root: Path, name: str, *, prompt: str | None = None,
                      mcp_port: int | None = None, resume_thread: str | None = None) -> list[str]:
    command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
        "--label", f"milai.native_run_root={root}",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory", "2g", "--cpus", "2",
        "--tmpfs", "/tmp:rw,nosuid,size=128m",  # noqa: S108 -- private container
        "--mount", f"type=bind,src={root / 'home'},dst=/codex-home",
        "--mount", f"type=bind,src={root / 'workspace'},dst=/workspace",
        "--mount", f"type=bind,src={root / 'sockets'},dst=/bridge,readonly",
        "--mount", f"type=bind,src={CODEX},dst=/usr/local/bin/codex,readonly",
        "--mount", f"type=bind,src={LAB / 'tools/v02_native_bridge.py'},dst=/relay.py,readonly",
        "--env", "CODEX_HOME=/codex-home", "--workdir", "/workspace",
        "--entrypoint", "/usr/bin/python3", IMAGE, "/relay.py",
        "--provider-socket", "/bridge/provider.sock"]
    if mcp_port:
        command.extend(["--mcp-socket", "/bridge/mcp.sock", "--mcp-port", str(mcp_port)])
    return [*command, "--", "/usr/local/bin/codex",
        "exec", *(["resume"] if resume_thread else []),
        "--strict-config", "--skip-git-repo-check", "--ignore-rules",
        "--dangerously-bypass-approvals-and-sandbox", "--json",
        *([resume_thread] if resume_thread else []),
        prompt or "Report the current directory name. This is an offline protocol check."]


def config() -> str:
    return '''model = "Qwen3.6-35B-A3B-FP8"
model_provider = "local_observed"
approval_policy = "never"
sandbox_mode = "danger-full-access"
web_search = "disabled"
model_reasoning_summary = "none"
[model_providers.local_observed]
name = "Pinned local Responses through observer"
base_url = "http://127.0.0.1:18080/v1"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
supports_websockets = false
stream_idle_timeout_ms = 90000
[analytics]
enabled = false
[features]
multi_agent = false
goals = false
'''


def fixture_events(number: int) -> bytes:
    item = ({"type": "function_call", "id": "fc_offline", "call_id": "offline_call_1",
             "name": "exec_command", "arguments": json.dumps({"cmd": "pwd"}),
             "status": "completed"} if number == 1 else {
        "type": "message", "id": "msg_offline", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Offline protocol check completed.",
                     "annotations": []}]})
    response = {"id": "resp_offline_" + str(number), "object": "response",
        "created_at": int(time.time()), "model": "Qwen3.6-35B-A3B-FP8", "status": "completed",
        "output": [item], "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}
    events = [
        {"type": "response.created",
         "response": {**response, "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "output_index": 0, "item": item},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]
    return b"".join(("event: " + event["type"] + "\ndata: " + json.dumps(
        {**event, "sequence_number": i}) + "\n\n").encode() for i, event in enumerate(events))


def run(root: Path, *, roundtrip: bool = False) -> dict:
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name in ("home", "workspace", "sockets"):
        (root / name).mkdir()
    (root / "home/config.toml").write_text(config())
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            number = len(seen) + 1
            (root / f"request-{number}.bin").write_bytes(raw)
            body = json.loads(raw)
            write_json(root / f"request-{number}.json", body)
            seen.append({"path": self.path, "sha256": hashlib.sha256(raw).hexdigest(),
                         "content_encoding": self.headers.get("Content-Encoding")})
            if roundtrip and number <= 2:
                response = fixture_events(number)
                (root / f"response-{number}.sse").write_bytes(response)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            # A deliberate terminal fixture, never forwarded to a real model.
            response = json.dumps({"error": {"message": "OFFLINE_CAPTURE_COMPLETE",
                                             "type": "invalid_request_error"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    socket_path = str(root / "sockets/provider.sock")
    with socketserver.ThreadingUnixStreamServer(socket_path, Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        name = root.name
        try:
            with (root / "client-events.jsonl").open("w") as stdout, (
                root / "client-stderr.txt"
            ).open("w") as stderr:
                result = subprocess.run(container_command(root, name), stdout=stdout,
                    stderr=stderr, timeout=60, check=False)
            report = {"client_exit_code": result.returncode, "requests": seen,
                      "actual_model_requests": 0, "kind": "NATIVE_CODEX_OFFLINE_REQUEST_CAPTURE"}
            if roundtrip:
                second = json.loads((root / "request-2.json").read_text())
                outputs = [v for v in second["input"] if v.get("type") == "function_call_output"]
                report["tool_result_in_next_request"] = any(
                    v["call_id"] == "offline_call_1" and "/workspace" in str(v["output"])
                    for v in outputs)
                report["kind"] = "NATIVE_CODEX_FIXED_PROVIDER_TOOL_ROUNDTRIP"
        finally:
            subprocess.run(["docker", "stop", "--time", "1", name], capture_output=True,
                           timeout=10, check=False)
            server.shutdown()
        report["codex_sha256"] = hashlib.sha256(CODEX.read_bytes()).hexdigest()
        write_json(root / "result.json", report)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--roundtrip", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), roundtrip=args.roundtrip)))
