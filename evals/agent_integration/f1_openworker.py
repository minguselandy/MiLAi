from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import select
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic import command
from milai.config import load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations import load_runtime_environment
from milai.operations.smoke import (
    _alembic_config,
    _create_database,
    _database_url,
    _drop_database,
    _migration_url,
    _smoke_settings,
)

from evals.agent_integration import e2e

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADAPTER_PYTHON = ROOT / "integrations/openworker-mcp/.venv/bin/python"
BROKER = ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/broker.py"
WORKER_IMAGE = "milai-openworker:dg10-candidate.1-local"
WORKER_IMAGE_ID = "sha256:4f90c07d8a1eecdc1bad0f43ecdcb97ef5f0c388f23eca00dce58b120575f410"
GATEWAY_IMAGE = "openworker-gateway-api:2026.5.9.1"
GATEWAY_IMAGE_ID = "sha256:535bb8b7e3b735cc24b04950449f2a70c9905273eafa7d1b322526ecdc5d3860"
POSTGRES_IMAGE = "postgres:18-alpine"
POSTGRES_IMAGE_ID = "sha256:c0eb29927f0e8590eac49c9d5bf9c5ebf87f4e6e7273e0a9270218e6b73795ee"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"


class OpenWorkerF1Error(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    argv: Sequence[str],
    *,
    timeout: float = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        evidence = (completed.stdout + completed.stderr).encode()
        raise OpenWorkerF1Error(
            f"command failed rc={completed.returncode}; output_sha256="
            f"{hashlib.sha256(evidence).hexdigest()}"
        )
    return completed


def _image_id(image: str) -> str:
    return _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"] ).stdout.strip()


def _wait_container(name: str, probe: Sequence[str], *, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = _run(["docker", "exec", name, *probe], timeout=15, check=False)
        if result.returncode == 0:
            return
        inspected = _run(
            ["docker", "inspect", name, "--format", "{{.State.Running}}"],
            check=False,
        )
        if inspected.returncode != 0 or inspected.stdout.strip() != "true":
            raise OpenWorkerF1Error(f"container stopped before ready: {name}")
        time.sleep(0.25)
    raise OpenWorkerF1Error(f"container readiness timeout: {name}")


def _bridge_origin() -> str:
    value = _run(
        [
            "docker",
            "network",
            "inspect",
            "bridge",
            "--format",
            "{{(index .IPAM.Config 0).Gateway}}",
        ]
    ).stdout.strip()
    if value != "172.17.0.1":
        raise OpenWorkerF1Error("Docker bridge identity drift")
    return value


def _free_bridge_port(host: str) -> int:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])
    finally:
        listener.close()


def _ledger_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


_OPENWORKER_API_SCRIPT = r"""
const fs = require("fs");
const prompt = fs.readFileSync(0, "utf8");
const base = "http://127.0.0.1:4096";
const directory = encodeURIComponent("/openworker/runtime");
const headers = {
  "Authorization": "Basic " + Buffer.from("opencode:openworker-local").toString("base64"),
  "Content-Type": "application/json"
};
async function request(path, init = {}) {
  const response = await fetch(base + path, {...init, headers: {...headers, ...(init.headers || {})}});
  const text = await response.text();
  if (!response.ok) throw new Error("HTTP_" + response.status);
  return text ? JSON.parse(text) : null;
}
(async () => {
const session = await request("/session?directory=" + directory, {
  method: "POST",
  body: JSON.stringify({title: "MiLAi bounded task"})
});
try {
  const response = await request("/session/" + session.id + "/message?directory=" + directory, {
    method: "POST",
    body: JSON.stringify({
      model: {providerID: "openworker", modelID: "AUTO"},
      parts: [{type: "text", text: prompt}]
    })
  });
  const history = await request("/session/" + session.id + "/message?directory=" + directory);
  process.stdout.write(JSON.stringify({session, response, history}));
} finally {
  await request("/session/" + session.id + "?directory=" + directory, {method: "DELETE"});
}
})().catch((error) => {
  process.stderr.write(String(error && error.message ? error.message : error));
  process.exit(1);
});
""".strip()


_PERSISTENT_OPENWORKER_API_SCRIPT = r"""
const readline = require("readline");
const base = "http://127.0.0.1:4096";
const directory = encodeURIComponent("/openworker/runtime");
const headers = {
  "Authorization": "Basic " + Buffer.from("opencode:openworker-local").toString("base64"),
  "Content-Type": "application/json"
};
const sessions = new Map();
async function request(path, init = {}) {
  const response = await fetch(base + path, {...init, headers: {...headers, ...(init.headers || {})}});
  const text = await response.text();
  if (!response.ok) throw new Error("HTTP_" + response.status);
  return text ? JSON.parse(text) : null;
}
async function sessionFor(taskID) {
  if (sessions.has(taskID)) return sessions.get(taskID);
  const session = await request("/session?directory=" + directory, {
    method: "POST",
    body: JSON.stringify({title: "MiLAi persistent task " + taskID.slice(0, 32)})
  });
  sessions.set(taskID, session);
  return session;
}
async function closeSessions() {
  for (const session of sessions.values()) {
    try {
      await request("/session/" + session.id + "?directory=" + directory, {method: "DELETE"});
    } catch (_) {}
  }
  sessions.clear();
}
async function handle(message) {
  if (message.op === "health") {
    const health = await request("/global/health");
    return {health};
  }
  if (message.op === "close") {
    await closeSessions();
    return {closed: true};
  }
  if (message.op !== "complete" || typeof message.task_id !== "string" ||
      typeof message.prompt !== "string") throw new Error("REQUEST_REJECTED");
  const session = await sessionFor(message.task_id);
  const response = await request("/session/" + session.id + "/message?directory=" + directory, {
    method: "POST",
    body: JSON.stringify({
      model: {providerID: "openworker", modelID: "AUTO"},
      parts: [{type: "text", text: message.prompt}]
    })
  });
  const history = await request("/session/" + session.id + "/message?directory=" + directory);
  return {session, response, history};
}
const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
let chain = Promise.resolve();
input.on("line", (line) => {
  chain = chain.then(async () => {
    let message;
    try {
      message = JSON.parse(line);
      const result = await handle(message);
      process.stdout.write(JSON.stringify({id: message.id, ok: true, result}) + "\n");
      if (message.op === "close") process.exit(0);
    } catch (error) {
      process.stdout.write(JSON.stringify({
        id: message && message.id,
        ok: false,
        error: String(error && error.message ? error.message : error)
      }) + "\n");
    }
  });
});
input.on("close", () => {
  chain.then(closeSessions).finally(() => process.exit(0));
});
""".strip()


def _opencode_api_command(worker_name: str) -> list[str]:
    return [
        "docker",
        "exec",
        "--interactive",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        worker_name,
        "node",
        "-e",
        _OPENWORKER_API_SCRIPT,
    ]


def _openworker_api(worker_name: str, prompt: str, *, timeout: float = 240) -> str:
    completed = subprocess.run(
        _opencode_api_command(worker_name),
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        evidence = (completed.stdout + completed.stderr).encode()
        raise OpenWorkerF1Error(
            "OpenWorker API run failed; output_sha256="
            + hashlib.sha256(evidence).hexdigest()
        )
    return completed.stdout


class PersistentOpenWorkerClient:
    """One long-lived docker exec bridge to the worker-local OpenCode HTTP API."""

    def __init__(self, worker_name: str) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._process = subprocess.Popen(
            [
                "docker",
                "exec",
                "--interactive",
                "--workdir",
                "/openworker/runtime",
                "--env",
                "OPENCODE_CONFIG_DIR=/openworker/runtime",
                worker_name,
                "node",
                "-e",
                _PERSISTENT_OPENWORKER_API_SCRIPT,
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request("health", timeout=30)

    def _request(
        self,
        operation: str,
        *,
        task_id: str | None = None,
        prompt: str | None = None,
        timeout: float = 240,
    ) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise OpenWorkerF1Error("persistent OpenWorker client is not running")
            if self._process.stdin is None or self._process.stdout is None:
                raise OpenWorkerF1Error("persistent OpenWorker pipes are unavailable")
            self._sequence += 1
            request_id = self._sequence
            payload: dict[str, Any] = {"id": request_id, "op": operation}
            if task_id is not None:
                payload["task_id"] = task_id
            if prompt is not None:
                payload["prompt"] = prompt
            self._process.stdin.write(_canonical(payload).decode() + "\n")
            self._process.stdin.flush()
            ready, _, _ = select.select([self._process.stdout], [], [], timeout)
            if not ready:
                raise OpenWorkerF1Error("persistent OpenWorker response timeout")
            line = self._process.stdout.readline()
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OpenWorkerF1Error(
                    "persistent OpenWorker response is not JSON"
                ) from exc
            if (
                not isinstance(response, dict)
                or response.get("id") != request_id
                or response.get("ok") is not True
                or not isinstance(response.get("result"), dict)
            ):
                raise OpenWorkerF1Error("persistent OpenWorker request failed")
            return dict(response["result"])

    def complete(self, task_id: str, prompt: str, *, timeout: float = 240) -> str:
        if not task_id or len(task_id) > 256:
            raise ValueError("task_id must contain 1-256 characters")
        if not prompt.strip() or len(prompt) > 2_000:
            raise ValueError("prompt must contain 1-2000 characters")
        return _canonical(
            self._request("complete", task_id=task_id, prompt=prompt, timeout=timeout)
        ).decode()

    def close(self) -> None:
        with self._lock:
            if self._process.poll() is None:
                if self._process.stdin is not None and self._process.stdout is not None:
                    self._sequence += 1
                    payload = {"id": self._sequence, "op": "close"}
                    try:
                        self._process.stdin.write(_canonical(payload).decode() + "\n")
                        self._process.stdin.flush()
                        ready, _, _ = select.select([self._process.stdout], [], [], 10)
                        if ready:
                            self._process.stdout.readline()
                    except (BrokenPipeError, OSError):
                        pass
                if self._process.poll() is None:
                    self._process.terminate()
            try:
                self._process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.communicate(timeout=5)


def _tool_name(part: Mapping[str, Any]) -> str | None:
    for key in ("tool", "toolName", "name"):
        value = part.get(key)
        if isinstance(value, str) and (
            value == "milai_recall" or value.endswith("_milai_recall")
        ):
            return "milai_recall"
    state = part.get("state")
    return _tool_name(state) if isinstance(state, Mapping) else None


@dataclass(frozen=True, slots=True)
class AgentRun:
    answer: dict[str, Any]
    tool_names: tuple[str, ...]
    event_types: tuple[str, ...]
    session_id_sha256: str
    output_sha256: str
    wall_ms: float
    provider_calls: int

    def public(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "tool_names": list(self.tool_names),
            "event_types": list(self.event_types),
            "session_id_sha256": self.session_id_sha256,
            "output_sha256": self.output_sha256,
            "wall_ms": round(self.wall_ms, 3),
            "provider_calls": self.provider_calls,
        }


def _answer_object(text: str) -> dict[str, Any]:
    candidates = [text.strip(), *reversed([line.strip() for line in text.splitlines()])]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and set(value) == {"answer", "status", "memory_used"}
            and isinstance(value.get("answer"), str)
            and value.get("status") in {"KNOWN", "UNKNOWN", "UNCERTAIN"}
            and isinstance(value.get("memory_used"), bool)
        ):
            return value
    raise OpenWorkerF1Error("OpenWorker answer contract failed")


def _parse_agent(raw: str, wall_ms: float, provider_calls: int) -> AgentRun:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenWorkerF1Error("OpenCode emitted non-JSON output") from exc
        if not isinstance(value, dict):
            raise OpenWorkerF1Error("OpenCode event is not an object")
        events.append(value)
    if not events or any(event.get("type") == "error" for event in events):
        raise OpenWorkerF1Error("OpenCode emitted an error terminal")
    sessions = {
        str(event["sessionID"])
        for event in events
        if isinstance(event.get("sessionID"), str)
    }
    texts: list[str] = []
    tools: set[str] = set()
    for event in events:
        part = event.get("part")
        if not isinstance(part, Mapping):
            continue
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            texts.append(str(part["text"]))
        name = _tool_name(part)
        if name is not None:
            tools.add(name)
    if len(sessions) != 1 or not texts:
        raise OpenWorkerF1Error("OpenCode session/text terminal is incomplete")
    text = "\n".join(texts)
    return AgentRun(
        answer=_answer_object(text),
        tool_names=tuple(sorted(tools)),
        event_types=tuple(sorted({str(event.get("type")) for event in events})),
        session_id_sha256=hashlib.sha256(next(iter(sessions)).encode()).hexdigest(),
        output_sha256=hashlib.sha256(text.encode()).hexdigest(),
        wall_ms=wall_ms,
        provider_calls=provider_calls,
    )


def _parse_api_agent(raw: str, wall_ms: float, provider_calls: int) -> AgentRun:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenWorkerF1Error("OpenWorker API response is not JSON") from exc
    if not isinstance(value, dict):
        raise OpenWorkerF1Error("OpenWorker API response is not an object")
    session = value.get("session")
    response = value.get("response")
    history = value.get("history")
    session_id = session.get("id") if isinstance(session, Mapping) else None
    if (
        not isinstance(session_id, str)
        or not isinstance(response, Mapping)
        or not isinstance(history, list)
    ):
        raise OpenWorkerF1Error("OpenWorker API terminal is incomplete")
    parts: list[Mapping[str, Any]] = []
    for message in history:
        if not isinstance(message, Mapping):
            continue
        raw_parts = message.get("parts")
        if isinstance(raw_parts, list):
            parts.extend(part for part in raw_parts if isinstance(part, Mapping))
    response_parts = response.get("parts")
    if isinstance(response_parts, list):
        final_texts = [
            str(part["text"])
            for part in response_parts
            if isinstance(part, Mapping)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
    else:
        final_texts = []
    if not final_texts:
        raise OpenWorkerF1Error("OpenWorker API answer text is absent")
    text = "\n".join(final_texts)
    tools = {name for part in parts if (name := _tool_name(part)) is not None}
    return AgentRun(
        answer=_answer_object(text),
        tool_names=tuple(sorted(tools)),
        event_types=tuple(sorted({str(part.get("type")) for part in parts})),
        session_id_sha256=hashlib.sha256(session_id.encode()).hexdigest(),
        output_sha256=hashlib.sha256(text.encode()).hexdigest(),
        wall_ms=wall_ms,
        provider_calls=provider_calls,
    )


class OpenWorkerHarness:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        mcp_executable: Path,
        provider_manifest: Path,
        provider_ledger: Path,
        adapter_trace: Path,
        *,
        memory_mode: str = "auto",
        tokenizer_json: Path | None = None,
        adapter_python: Path = DEFAULT_ADAPTER_PYTHON,
    ) -> None:
        if memory_mode not in {"auto", "none", "prefetch"}:
            raise ValueError("unknown memory mode")
        suffix = hashlib.sha256(run_id.encode()).hexdigest()[:10]
        self.workspace = workspace
        self.run_id = run_id
        self.mcp_executable = mcp_executable
        self.provider_manifest = provider_manifest
        self.provider_ledger = provider_ledger
        self.adapter_trace = adapter_trace
        self.memory_mode = memory_mode
        self.tokenizer_json = tokenizer_json
        self.adapter_python = adapter_python
        if not self.adapter_python.is_file():
            raise ValueError("OpenWorker adapter Python is absent")
        if self.memory_mode == "prefetch" and self.tokenizer_json is None:
            raise ValueError("prefetch mode requires target tokenizer.json")
        self.agent_network = f"milai-f1-agent-{suffix}"
        self.db_network = f"milai-f1-dbnet-{suffix}"
        self.db_name = f"milai-f1-gwdb-{suffix}"
        self.gateway_name = f"milai-f1-gateway-{suffix}"
        self.worker_name = f"milai-f1-worker-{suffix}"
        self.db_password = secrets.token_urlsafe(32)
        self.gateway_master = secrets.token_urlsafe(32)
        self.gateway_key = "bill-" + secrets.token_hex(24)
        self.bridge_host = _bridge_origin()
        self.adapter_port = _free_bridge_port(self.bridge_host)
        self.adapter_process: subprocess.Popen[str] | None = None
        self.broker_process: subprocess.Popen[str] | None = None
        self.persistent_client: PersistentOpenWorkerClient | None = None
        self.adapter_log = ""
        self.broker_log = ""
        self.prefetch_socket = self.workspace / "reader-lite" / "reader-lite.sock"
        self.reader_token: str | None = None
        self.base_url: str | None = None
        self.started_containers: list[str] = []
        self.started_networks: list[str] = []
        self.records: dict[str, dict[str, Any]] = {}

    def start_model_plane(self) -> None:
        expected = {
            WORKER_IMAGE: WORKER_IMAGE_ID,
            GATEWAY_IMAGE: GATEWAY_IMAGE_ID,
            POSTGRES_IMAGE: POSTGRES_IMAGE_ID,
        }
        for image, identity in expected.items():
            if _image_id(image) != identity:
                raise OpenWorkerF1Error(f"image identity drift: {image}")
        adapter_command = [
                str(self.adapter_python),
                "-m",
                "milai_openworker_mcp.host_adapter",
                "--manifest",
                str(self.provider_manifest),
                "--ledger",
                str(self.provider_ledger),
                "--trace",
                str(self.adapter_trace),
                "--listen-host",
                self.bridge_host,
                "--listen-port",
                str(self.adapter_port),
                "--memory-mode",
                self.memory_mode,
            ]
        if self.memory_mode == "prefetch":
            adapter_command.extend(
                [
                    "--prefetch-socket",
                    str(self.prefetch_socket),
                    "--tokenizer-json",
                    str(self.tokenizer_json),
                    "--task-session-id",
                    "openworker-" + self.run_id,
                ]
            )
        self.adapter_process = subprocess.Popen(
            adapter_command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.adapter_process.poll() is not None:
                raise OpenWorkerF1Error("OpenWorker provider adapter stopped before ready")
            try:
                with opener.open(
                    f"http://{self.bridge_host}:{self.adapter_port}/v1/models",
                    timeout=1,
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise OpenWorkerF1Error("OpenWorker provider adapter readiness timeout")

        for network in (self.agent_network, self.db_network):
            _run(["docker", "network", "create", "--internal", network])
            self.started_networks.append(network)
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                self.db_name,
                "--network",
                self.db_network,
                "--env",
                "POSTGRES_DB=gateway",
                "--env",
                "POSTGRES_USER=gateway",
                "--env",
                f"POSTGRES_PASSWORD={self.db_password}",
                POSTGRES_IMAGE,
            ]
        )
        self.started_containers.append(self.db_name)
        _wait_container(self.db_name, ["pg_isready", "-U", "gateway", "-d", "gateway"])
        database_url = f"postgresql://gateway:{self.db_password}@{self.db_name}:5432/gateway"
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                self.db_network,
                "--env",
                f"DATABASE_URL={database_url}",
                GATEWAY_IMAGE,
                "npm",
                "run",
                "db:push",
                "--",
                "--force",
            ],
            timeout=180,
        )
        _run(
            [
                "docker",
                "create",
                "--name",
                self.gateway_name,
                "--network",
                self.db_network,
                "--env",
                f"DATABASE_URL={database_url}",
                "--env",
                f"GATEWAY_MASTER_KEY={self.gateway_master}",
                "--env",
                "ENABLE_LLMHUB=true",
                "--env",
                "ENABLE_SKILLBASE=false",
                "--env",
                "ENABLE_MEDIAHUB=false",
                "--env",
                "LLMHUB_MODE=openai",
                "--env",
                f"LLMHUB_URL=http://{self.bridge_host}:{self.adapter_port}",
                "--env",
                "LLMHUB_INTERNAL_KEY=",
                "--env",
                "LLMHUB_MASTER_KEY=",
                "--env",
                "ENFORCE_BILLING_LIMITS=false",
                "--env",
                "ALLOWED_ORIGINS=",
                "--env",
                "PORT=3001",
                GATEWAY_IMAGE,
            ]
        )
        self.started_containers.append(self.gateway_name)
        _run(["docker", "network", "connect", self.agent_network, self.gateway_name])
        _run(["docker", "network", "connect", "bridge", self.gateway_name])
        _run(["docker", "start", self.gateway_name])
        _wait_container(
            self.gateway_name,
            [
                "node",
                "-e",
                'fetch("http://127.0.0.1:3001/health").then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))',
            ],
        )
        sql = (
            "INSERT INTO user_balance "
            "(user_id,key,key_alias,llm_budget,llm_spend,skill_budget,skill_spend,"
            "media_budget,media_spend,is_active) VALUES "
            f"('f1-{self.run_id[:12]}','{self.gateway_key}','f1',0,0,0,0,0,0,true);"
        )
        _run(
            [
                "docker",
                "exec",
                self.db_name,
                "psql",
                "-U",
                "gateway",
                "-d",
                "gateway",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ]
        )

    def _start_memory_plane(self, base_url: str, token: str) -> None:
        self.reader_token = token
        self.base_url = base_url
        socket_directory = self.workspace / "reader-lite"
        socket_directory.mkdir(mode=0o700)
        socket_path = self.prefetch_socket
        policy_path = self.workspace / "reader-lite-policy.json"
        token_path = self.workspace / "reader.token"
        policy = {
            "allowed_peer_uids": [0],
            "base_url": base_url,
            "child_shutdown_seconds": 5,
            "consistency_floor": "CANONICAL_REQUIRED",
            "max_connections": 8,
            "max_limit": 3,
            "mcp_executable": str(self.mcp_executable),
            "mcp_executable_sha256": _sha256(self.mcp_executable),
            "profile": "reader-lite",
            "required_authority": "ACTION_SAFE",
            "schema": "milai.openworker.mcp-broker-policy.v1",
            "scope": {"project_ids": ["milai-agent-e2e"]},
            "socket_mode": "0600",
            "socket_path": str(socket_path),
        }
        policy_path.write_bytes(_canonical(policy))
        token_path.write_text(token, encoding="utf-8")
        policy_path.chmod(0o600)
        token_path.chmod(0o600)
        self.broker_process = subprocess.Popen(
            [
                str(self.adapter_python),
                "-m",
                "milai_openworker_mcp.broker",
                "--policy",
                str(policy_path),
                "--token-file",
                str(token_path),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.broker_process.poll() is not None:
                raise OpenWorkerF1Error("MCP broker stopped before ready")
            if socket_path.exists():
                break
            time.sleep(0.05)
        else:
            raise OpenWorkerF1Error("MCP broker readiness timeout")
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                self.worker_name,
                "--network",
                self.agent_network,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--ulimit",
                "core=0:0",
                "--tmpfs",
                "/openworker/data:rw,nosuid,nodev,noexec,size=128m,mode=0700",
                "--env",
                f"OPENWORKER_KEY={self.gateway_key}",
                "--env",
                f"OPENWORKER_URL=http://{self.gateway_name}:3001/v1",
                "--mount",
                f"type=bind,src={socket_path},dst=/run/milai-mcp/reader-lite.sock,readonly",
                WORKER_IMAGE,
            ]
        )
        self.started_containers.append(self.worker_name)
        _wait_container(
            self.worker_name,
            [
                "curl",
                "-sf",
                "-u",
                "opencode:openworker-local",
                "http://127.0.0.1:4096/global/health",
            ],
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            logs = _run(["docker", "logs", self.worker_name], check=False)
            if "OC config schema OK" in logs.stdout + logs.stderr:
                break
            time.sleep(0.25)
        else:
            raise OpenWorkerF1Error("OpenWorker config readiness timeout")
        listed = _run(
            [
                "docker",
                "exec",
                "--workdir",
                "/openworker/runtime",
                "--env",
                "OPENCODE_CONFIG_DIR=/openworker/runtime",
                self.worker_name,
                "opencode",
                "mcp",
                "list",
            ],
            timeout=45,
        )
        normalized = (listed.stdout + listed.stderr).casefold()
        if "milai" not in normalized or "connected" not in normalized:
            raise OpenWorkerF1Error("OpenWorker MCP is not connected")

    def _agent(self, phase: str, marker: str) -> AgentRun:
        before = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        route_instruction = (
            "Use the available milai_recall tool exactly once. "
            if self.memory_mode != "prefetch"
            else "The trusted host will prepare governed memory when needed. "
        )
        prompt = (
            route_instruction
            + f"What runtime Python version is recorded for synthetic project {marker}? "
            + "Return only the required JSON answer and preserve uncertainty."
        )
        started = time.perf_counter()
        try:
            raw = _openworker_api(self.worker_name, prompt)
        except OpenWorkerF1Error:
            wall_ms = (time.perf_counter() - started) * 1000
            after = sum(
                event.get("event") == "PROVIDER_TERMINAL"
                for event in _ledger_events(self.provider_ledger)
            )
            if phase == "unavailable" and after == before:
                return AgentRun(
                    answer={"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False},
                    tool_names=("milai_recall",),
                    event_types=("controlled_error",),
                    session_id_sha256="0" * 64,
                    output_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                    wall_ms=wall_ms,
                    provider_calls=0,
                )
            raise
        wall_ms = (time.perf_counter() - started) * 1000
        after = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        return _parse_api_agent(raw, wall_ms, after - before)

    def no_memory_control(self, case_id: str) -> AgentRun:
        before = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        prompt = (
            f"Case {case_id} intentionally has no memory. "
            "Return only the required JSON answer."
        )
        started = time.perf_counter()
        raw = _openworker_api(self.worker_name, prompt)
        wall_ms = (time.perf_counter() - started) * 1000
        after = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        return _parse_api_agent(raw, wall_ms, after - before)

    def serving_request(self, prompt: str) -> AgentRun:
        """Run one serving task without changing the frozen user prompt across tiers."""
        if not prompt.strip() or len(prompt) > 2_000:
            raise ValueError("serving prompt must contain 1-2000 characters")
        before = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        started = time.perf_counter()
        raw = _openworker_api(self.worker_name, prompt)
        wall_ms = (time.perf_counter() - started) * 1000
        after = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        return _parse_api_agent(raw, wall_ms, after - before)

    def start_persistent_client(self) -> None:
        if self.persistent_client is not None:
            raise OpenWorkerF1Error("persistent OpenWorker client is already started")
        self.persistent_client = PersistentOpenWorkerClient(self.worker_name)

    def persistent_serving_request(self, task_id: str, prompt: str) -> AgentRun:
        """Run through one persistent local bridge and an explicit long-lived task."""
        if self.persistent_client is None:
            raise OpenWorkerF1Error("persistent OpenWorker client is not started")
        before = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        started = time.perf_counter()
        raw = self.persistent_client.complete(task_id, prompt)
        wall_ms = (time.perf_counter() - started) * 1000
        after = sum(
            event.get("event") == "PROVIDER_TERMINAL"
            for event in _ledger_events(self.provider_ledger)
        )
        return _parse_api_agent(raw, wall_ms, after - before)

    def hook(self, phase: str, details: Mapping[str, Any]) -> None:
        marker = str(details["marker"])
        name = "unavailable" if phase == "canonical_down" else phase
        if phase == "initial":
            self._start_memory_plane(
                str(details["base_url"]), str(details["reader_token"])
            )
        run = self._agent(name, marker)
        expected = {
            "initial": {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False},
            "current": {"answer": "3.11", "status": "KNOWN", "memory_used": True},
            "conflict": {
                "answer": "UNCERTAIN",
                "status": "UNCERTAIN",
                "memory_used": False,
            },
            "revoked": {
                "answer": "UNCERTAIN",
                "status": "UNCERTAIN",
                "memory_used": False,
            },
            "canonical_down": {
                "answer": "UNKNOWN",
                "status": "UNKNOWN",
                "memory_used": False,
            },
        }[phase]
        expected_calls = 0 if phase == "canonical_down" else 1
        passed = (
            run.answer == expected
            and run.tool_names
            == (() if self.memory_mode == "prefetch" else ("milai_recall",))
            and run.provider_calls == expected_calls
        )
        self.records[name] = {**run.public(), "status": "PASS" if passed else "FAILED"}
        if not passed:
            raise OpenWorkerF1Error(f"OpenWorker {name} case mismatch")

    def security(self) -> dict[str, Any]:
        if self.reader_token is None or self.base_url is None:
            raise OpenWorkerF1Error("OpenWorker security inputs are absent")
        inspected = json.loads(
            _run(["docker", "container", "inspect", self.worker_name]).stdout
        )[0]
        logs = _run(["docker", "logs", self.worker_name], check=False)
        config = _run(
            ["docker", "exec", self.worker_name, "cat", "/openworker/runtime/opencode.json"]
        ).stdout
        public = "\n".join(inspected["Config"].get("Env") or []) + config + logs.stdout + logs.stderr
        if self.reader_token in public or self.base_url in public:
            raise OpenWorkerF1Error("Worker exposed the MCP credential or Runtime origin")
        mounts = inspected.get("Mounts") or []
        socket_mounts = [
            mount
            for mount in mounts
            if mount.get("Destination") == "/run/milai-mcp/reader-lite.sock"
            and mount.get("RW") is False
        ]
        if len(socket_mounts) != 1 or any(
            mount.get("Destination") == "/var/run/docker.sock" for mount in mounts
        ):
            raise OpenWorkerF1Error("Worker capability mount boundary failed")
        networks = set(inspected["NetworkSettings"]["Networks"])
        if networks != {self.agent_network}:
            raise OpenWorkerF1Error("Worker network boundary failed")
        port = self.base_url.rsplit(":", 1)[-1]
        direct = _run(
            [
                "docker",
                "exec",
                self.worker_name,
                "curl",
                "-sf",
                "--max-time",
                "2",
                f"http://{self.bridge_host}:{port}/v1/capabilities",
            ],
            timeout=10,
            check=False,
        )
        if direct.returncode == 0:
            raise OpenWorkerF1Error("Worker reached Runtime outside MCP")
        return {
            "secret_scan": "PASS",
            "socket_file_read_only": True,
            "docker_socket_absent": True,
            "worker_network": "internal-agent-only",
            "direct_runtime": "BLOCKED",
        }

    def summary(self) -> dict[str, Any]:
        if set(self.records) != {"initial", "current", "conflict", "revoked", "unavailable"}:
            raise OpenWorkerF1Error("OpenWorker case coverage is incomplete")
        events = _ledger_events(self.provider_ledger)
        reservations = [event for event in events if event.get("event") == "RESERVED"]
        terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
        post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
        traces = [
            json.loads(line)
            for line in self.adapter_trace.read_text(encoding="utf-8").splitlines()
        ]
        answers = [trace for trace in traces if trace.get("event") == "PROVIDER_ANSWER"]
        statuses = [trace.get("memory_status") for trace in answers]
        reservation_hashes = {
            str(event["logical_request_id"]): str(event["prompt_sha256"])
            for event in reservations
        }
        if (
            len(reservations) != 4
            or len(terminals) != 4
            or len(post) != 4
            or len({event["native_request_id"] for event in terminals}) != 4
            or statuses != ["NO_MEMORY", "AVAILABLE", "UNCERTAIN", "UNCERTAIN"]
            or not all(trace.get("context_in_prompt") is True for trace in answers)
            or not all(
                reservation_hashes.get(str(trace["logical_request_id"]))
                == trace["provider_payload_sha256"]
                for trace in answers
            )
        ):
            raise OpenWorkerF1Error("OpenWorker provider/context trace contract failed")
        return {
            "cases": self.records,
            "provider_trace": {
                "reservations": 4,
                "provider_terminals": 4,
                "post_provider_terminals": 4,
                "hidden_model_calls": 0,
                "native_request_ids": [event["native_request_id"] for event in terminals],
                "memory_statuses": statuses,
            },
            "context_consumption": {
                "available_context_in_prompt": answers[1]["context_in_prompt"],
                "available_trace_id": answers[1]["trace_id"],
                "available_claim_refs": answers[1]["claim_refs"],
            },
            "security": self.security(),
        }

    def close(self) -> dict[str, Any]:
        if self.persistent_client is not None:
            self.persistent_client.close()
            self.persistent_client = None
        if self.broker_process is not None:
            if self.broker_process.poll() is None:
                self.broker_process.terminate()
            try:
                _, self.broker_log = self.broker_process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                self.broker_process.kill()
                _, self.broker_log = self.broker_process.communicate(timeout=5)
            self.broker_process = None
        for container in reversed(self.started_containers):
            _run(["docker", "rm", "--force", container], timeout=30, check=False)
        for network in reversed(self.started_networks):
            _run(["docker", "network", "rm", network], timeout=30, check=False)
        if self.adapter_process is not None:
            if self.adapter_process.poll() is None:
                self.adapter_process.terminate()
            try:
                self.adapter_log, _ = self.adapter_process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.adapter_process.kill()
                self.adapter_log, _ = self.adapter_process.communicate(timeout=5)
            self.adapter_process = None
        broker_events: Counter[str] = Counter()
        for line in self.broker_log.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                broker_events[str(event.get("event", "UNKNOWN"))] += 1
        secret_absent = self.reader_token is None or (
            self.reader_token not in self.broker_log and self.reader_token not in self.adapter_log
        )
        failure_events = {
            name: count
            for name, count in broker_events.items()
            if name
            in {
                "CHILD_STOP_FAILED",
                "OVERLOAD_REJECTED",
                "PEER_REJECTED",
                "SESSION_FAILED",
                "SOCKET_PATH_DRIFT",
            }
        }
        broker_clean = (
            not failure_events
            and broker_events["READY"] == 1
            and broker_events["STOPPED"] == 1
        )
        return {
            "containers_removed": len(self.started_containers),
            "networks_removed": len(self.started_networks),
            "broker_events": dict(sorted(broker_events.items())),
            "broker_failure_events": failure_events,
            "secret_logs_absent": secret_absent,
            "status": "PASS" if secret_absent and broker_clean else "FAILED",
        }


def run(
    *,
    env_file: Path,
    report_path: Path,
    provider_manifest: Path,
    provider_ledger: Path,
    adapter_trace: Path,
    mcp_executable: Path,
    tokenizer_json: Path,
    adapter_python: Path,
) -> dict[str, Any]:
    load_runtime_environment(env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise OpenWorkerF1Error("Runtime database role URLs are absent")
    provider_run_id = str(json.loads(provider_manifest.read_text())["run_id"])
    runtime_run_id = uuid4().hex
    database_name = f"milai_smoke_{runtime_run_id[:20]}"
    database_urls = {
        "owner": _database_url(owner_source, database_name),
        "api": _database_url(source.database_dsn, database_name),
        "steward": _database_url(source.steward_database_dsn, database_name),
        "worker": _database_url(worker_source, database_name),
        "audit": _database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    report: dict[str, Any] = {
        "schema": "milai.dg10.f1-openworker-functional.v1",
        "run_id": provider_run_id,
        "runtime_run_id": runtime_run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "data_mode": "SYNTHETIC_ONLY",
        "status": "FAILED",
    }
    harness: OpenWorkerHarness | None = None
    created = False
    try:
        _create_database(owner_source, database_name)
        created = True
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        with tempfile.TemporaryDirectory(prefix="milai-f1-openworker-") as workspace:
            harness = OpenWorkerHarness(
                Path(workspace),
                provider_run_id,
                mcp_executable,
                provider_manifest,
                provider_ledger,
                adapter_trace,
                memory_mode="prefetch",
                tokenizer_json=tokenizer_json,
                adapter_python=adapter_python,
            )
            harness.start_model_plane()
            with tempfile.TemporaryDirectory(prefix="milai-f1-openworker-blobs-") as blobs:
                settings = _smoke_settings(
                    source,
                    database_urls,
                    Path(blobs),
                    uuid4(),
                    uuid4(),
                    tokens,
                    e2e._free_loopback_port(),
                )
                prepare_runtime_directories(settings)
                report["memory_e2e"] = e2e._run_fixture(
                    settings,
                    database_urls,
                    tokens,
                    runtime_run_id,
                    phase_hook=harness.hook,
                )
            report["openworker"] = harness.summary()
        report["functional_cases"] = {
            **{f"OW-F1-{index:02d}": "PASS" for index in range(1, 6)},
            "OPENWORKER-F1": "PASS",
        }
        report["status"] = "PASS"
    except Exception as exc:
        report["failure"] = type(exc).__name__
        report["failure_code"] = str(exc)
        raise
    finally:
        if harness is not None:
            report["partial_openworker_records"] = harness.records
        report["openworker_cleanup"] = (
            harness.close() if harness is not None else {"status": "NOT_STARTED"}
        )
        report["database_cleanup"] = (
            _drop_database(owner_source, database_name)
            if created
            else {"status": "NOT_CREATED"}
        )
        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        report["secret_artifacts_absent"] = all(
            token not in serialized for token in tokens.values()
        )
        report["finished_at"] = datetime.now(UTC).isoformat()
        e2e._write_report(report_path, report)
    if (
        report["status"] != "PASS"
        or report["openworker_cleanup"].get("status") != "PASS"
        or report["database_cleanup"].get("status") != "PASS"
        or report["secret_artifacts_absent"] is not True
    ):
        raise OpenWorkerF1Error("OpenWorker F1 matrix or cleanup failed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenWorker real-container F1 cases")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--provider-ledger", type=Path, required=True)
    parser.add_argument("--adapter-trace", type=Path, required=True)
    parser.add_argument("--mcp-executable", type=Path, required=True)
    parser.add_argument("--tokenizer-json", type=Path, required=True)
    parser.add_argument("--adapter-python", type=Path, required=True)
    args = parser.parse_args()
    report = run(
        env_file=args.env_file,
        report_path=args.report,
        provider_manifest=args.provider_manifest,
        provider_ledger=args.provider_ledger,
        adapter_trace=args.adapter_trace,
        mcp_executable=args.mcp_executable,
        tokenizer_json=args.tokenizer_json,
        adapter_python=args.adapter_python,
    )
    print(json.dumps({"status": report["status"], "cases": report["functional_cases"]}))


if __name__ == "__main__":
    main()
