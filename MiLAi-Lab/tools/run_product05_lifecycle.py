#!/usr/bin/env python3
"""Run the Product-05 two-tenant OpenWorker persistence lifecycle gate.

The run owns its PostgreSQL container, network, Runtime processes, broker sockets,
Host adapters, and OpenWorker containers.  It preserves the PostgreSQL volume and
private run evidence while stopping ephemeral processes at exit.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

LAB = Path(__file__).resolve().parents[1]
PRODUCT = LAB.parent / "MiLAi-Product"
RUNTIME = PRODUCT / "runtime"
OPENWORKER = PRODUCT / "integrations" / "openworker-mcp"
MCP = PRODUCT / "integrations" / "mcp"
PYTHON_CLIENT = PRODUCT / "integrations" / "python-client"

sys.path.insert(0, str(OPENWORKER / "src"))
sys.path.insert(0, str(PYTHON_CLIENT / "src"))

import psycopg  # noqa: E402
from milai_client import MilaiClient  # noqa: E402
from milai_openworker_mcp.memory_facade import (  # noqa: E402
    OpenWorkerMemoryFacade,
    decode_memory_support_lineage,
)
from milai_openworker_mcp.transport import McpUnixClient  # noqa: E402

MODEL = "Qwen3.6-35B-A3B-FP8"
PROVIDER_ENDPOINT = "http://127.0.0.1:7860"
SCOPE = {"project_ids": ["orchid-release"]}
SUBJECT = "openworker-local-user"
IMAGE = "milai-openworker:dg13u-u1-current-local"
MCP_EXE = MCP / ".venv" / "bin" / "milai-mcp"
BROKER_EXE = OPENWORKER / ".venv" / "bin" / "milai-mcp-broker"
HOST_EXE = OPENWORKER / ".venv" / "bin" / "milai-openworker-adapter"
API_EXE = RUNTIME / ".venv" / "bin" / "milai-api"
WORKER_EXE = RUNTIME / ".venv" / "bin" / "milai-worker"
OPS_EXE = RUNTIME / ".venv" / "bin" / "milai-ops"
ALEMBIC_EXE = RUNTIME / ".venv" / "bin" / "alembic"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
TASK_FIXTURE = PRODUCT / "contracts" / "agent" / "v1" / "dg13u-u1-candidate-fixture.json"
CANONICAL_TABLES = (
    "claim",
    "operation_proposal",
    "steward_decision",
    "open_issue",
    "claim_version",
    "claim_head",
    "version_transition",
    "grounding_relation",
    "grounding_block",
    "open_issue_transition",
)


class LifecycleError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_write(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _replace_private(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    path.chmod(0o600)


def _command(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(  # noqa: S603
        arguments,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace")[-2000:]
        raise LifecycleError(f"command failed ({arguments[0]}): {stderr}")
    return completed


def _free_port() -> int:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.close()
    return port


def _clean_environment(values: dict[str, str]) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items() if not key.startswith("MILAI_")}
    result.update(values)
    return result


def _load_environment(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MILAI_") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _write_environment(path: Path, values: dict[str, str]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("# Product-05 private isolated Runtime environment.\n")
        for key, value in sorted(values.items()):
            handle.write(f"{key}={value}\n")


def _http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: object | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, Any]]:
    data = None
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(  # noqa: S310 - run-owned HTTP origins only
        url, data=data, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        return exc.code, parsed


def _wait_http(url: str, process: subprocess.Popen[bytes] | None = None) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise LifecycleError(f"process exited while waiting for {url}")
        try:
            status, _ = _http_json("GET", url, timeout=2)
            if status == 200:
                return
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.25)
    raise LifecycleError(f"timed out waiting for {url}")


def _wait_port(host: str, port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LifecycleError(f"process exited while waiting for port {port}")
        probe = socket.socket()
        probe.settimeout(0.25)
        try:
            probe.connect((host, port))
            return
        except OSError:
            time.sleep(0.1)
        finally:
            probe.close()
    raise LifecycleError(f"timed out waiting for port {port}")


def _wait_socket(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LifecycleError(f"broker exited while waiting for {path}")
        try:
            mode = path.lstat().st_mode
            if stat.S_ISSOCK(mode) and stat.S_IMODE(mode) == 0o600:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise LifecycleError(f"timed out waiting for broker socket {path}")


@dataclass(slots=True)
class ManagedProcesses:
    entries: list[tuple[subprocess.Popen[bytes], Any]] = field(default_factory=list)

    def start(
        self,
        arguments: list[str],
        log_path: Path,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        handle = os.fdopen(descriptor, "ab", buffering=0)
        process = subprocess.Popen(  # noqa: S603
            arguments,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.entries.append((process, handle))
        return process

    def stop_all(self) -> None:
        for process, _ in reversed(self.entries):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 15
        for process, handle in reversed(self.entries):
            if process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
            handle.close()
        self.entries.clear()


@dataclass(slots=True)
class NativeExchange:
    session_id: str
    user_message_id: str
    assistant_message_id: str
    user_content: str
    assistant_content: str
    user_observed_at: str
    assistant_observed_at: str
    round_ordinal: int


@dataclass(slots=True)
class TenantStack:
    label: str
    root: Path
    environment: dict[str, str]
    api_port: int
    host_port: int
    reader_socket: Path
    submitter_socket: Path
    reader_policy: Path
    submitter_policy: Path
    reader_token_file: Path
    submitter_token_file: Path
    ingress_token_file: Path
    manifest: Path
    ledger: Path
    trace: Path
    container: str
    processes: ManagedProcesses = field(default_factory=ManagedProcesses)


def _policy(
    *,
    profile: str,
    socket_path: Path,
    base_url: str,
    executable_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": profile,
        "socket_path": str(socket_path),
        "socket_mode": "0600",
        "allowed_peer_uids": [os.geteuid()],
        "mcp_executable": str(MCP_EXE),
        "mcp_executable_sha256": executable_sha256,
        "base_url": base_url,
        "scope": SCOPE,
        "required_authority": "INFORMATIONAL",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 50,
        "max_connections": 16,
        "child_shutdown_seconds": 5,
        "mcp_max_retries": 0,
    }


def _make_stack(
    run_root: Path,
    socket_root: Path,
    label: str,
    environment: dict[str, str],
    host_port: int,
    run_id: str,
) -> TenantStack:
    root = run_root / f"tenant-{label.lower()}"
    root.mkdir(mode=0o700)
    (root / "data").mkdir(mode=0o700)
    (root / "blobs").mkdir(mode=0o700)
    reader_root = socket_root / label.lower() / "reader-lite"
    submitter_root = socket_root / label.lower() / "submitter"
    reader_root.mkdir(mode=0o700, parents=True)
    submitter_root.mkdir(mode=0o700, parents=True)
    reader_socket = reader_root / "reader-lite.sock"
    submitter_socket = submitter_root / "submitter.sock"
    reader_policy = root / "reader-lite.policy.json"
    submitter_policy = root / "submitter.policy.json"
    digest = _sha256_file(MCP_EXE)
    _private_write(
        reader_policy,
        _policy(
            profile="reader-lite",
            socket_path=reader_socket,
            base_url=environment["MILAI_BASE_URL"],
            executable_sha256=digest,
        ),
    )
    _private_write(
        submitter_policy,
        _policy(
            profile="submitter",
            socket_path=submitter_socket,
            base_url=environment["MILAI_BASE_URL"],
            executable_sha256=digest,
        ),
    )
    reader_token_file = root / "reader.token"
    submitter_token_file = root / "submitter.token"
    ingress_token_file = root / "ingress.token"
    for path, value in (
        (reader_token_file, environment["MILAI_AGENT_READER_TOKEN"]),
        (submitter_token_file, environment["MILAI_AGENT_SUBMITTER_TOKEN"]),
        (ingress_token_file, "t" + secrets.token_urlsafe(47)),
    ):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
    now = datetime.now(UTC)
    manifest = root / "provider-manifest.json"
    _private_write(
        manifest,
        {
            "schema": "milai.provider.dev-run.v1",
            "run_id": f"{run_id}-{label.lower()}",
            "phase": "dev",
            "provider": "local_vllm",
            "endpoint_identity": PROVIDER_ENDPOINT,
            "model_id": MODEL,
            "dataset_manifest_sha256": _sha256_text("product05-lifecycle-synthetic-v1"),
            "prompt_template_sha256": _sha256_text("product05-lifecycle-prompts-v1"),
            "max_native_requests": 20,
            "max_prompt_tokens": 1_310_720,
            "max_completion_tokens": 40_960,
            "deadline": (now + timedelta(hours=2)).isoformat(),
            "expires_at": (now + timedelta(hours=3)).isoformat(),
            "synthetic_or_deidentified_only": True,
            "closed_test_access": False,
        },
    )
    return TenantStack(
        label=label,
        root=root,
        environment=environment,
        api_port=int(environment["MILAI_BIND_PORT"]),
        host_port=host_port,
        reader_socket=reader_socket,
        submitter_socket=submitter_socket,
        reader_policy=reader_policy,
        submitter_policy=submitter_policy,
        reader_token_file=reader_token_file,
        submitter_token_file=submitter_token_file,
        ingress_token_file=ingress_token_file,
        manifest=manifest,
        ledger=root / "provider-ledger.jsonl",
        trace=root / "host-trace.jsonl",
        container=f"{run_id}-ow-{label.lower()}",
    )


def _host_arguments(stack: TenantStack, listen_host: str) -> list[str]:
    return [
        str(HOST_EXE),
        "--manifest",
        str(stack.manifest),
        "--ledger",
        str(stack.ledger),
        "--trace",
        str(stack.trace),
        "--listen-host",
        listen_host,
        "--listen-port",
        str(stack.host_port),
        "--memory-mode",
        "query-first",
        "--prefetch-socket",
        str(stack.reader_socket),
        "--submitter-socket",
        str(stack.submitter_socket),
        "--memory-subject-id",
        SUBJECT,
        "--memory-data-classification",
        "SYNTHETIC",
        "--evidence-use-mode",
        "direct",
        "--tokenizer-json",
        str(TOKENIZER),
        "--broker-policy",
        str(stack.reader_policy),
        "--task-fixture",
        str(TASK_FIXTURE),
        "--ingress-token-file",
        str(stack.ingress_token_file),
        "--provider-timeout-seconds",
        "300",
    ]


def _start_process_stack(stack: TenantStack, listen_host: str) -> None:
    environment = _clean_environment(stack.environment)
    api = stack.processes.start(
        [str(API_EXE)], stack.root / "api.log", cwd=RUNTIME, env=environment
    )
    worker = stack.processes.start(
        [str(WORKER_EXE)], stack.root / "worker.log", cwd=RUNTIME, env=environment
    )
    _wait_http(f"http://127.0.0.1:{stack.api_port}/health/ready", api)
    if worker.poll() is not None:
        raise LifecycleError(f"tenant {stack.label} worker exited during startup")
    reader = stack.processes.start(
        [
            str(BROKER_EXE),
            "--policy",
            str(stack.reader_policy),
            "--token-file",
            str(stack.reader_token_file),
            "--resolve-budget-profile",
            "OPENWORKER_USABILITY_WIDE_V02",
        ],
        stack.root / "reader-broker.log",
    )
    submitter = stack.processes.start(
        [
            str(BROKER_EXE),
            "--policy",
            str(stack.submitter_policy),
            "--token-file",
            str(stack.submitter_token_file),
        ],
        stack.root / "submitter-broker.log",
    )
    _wait_socket(stack.reader_socket, reader)
    _wait_socket(stack.submitter_socket, submitter)
    host = stack.processes.start(
        _host_arguments(stack, listen_host),
        stack.root / "host.log",
        cwd=OPENWORKER,
    )
    _wait_port(listen_host, stack.host_port, host)


def _container_health(container: str) -> None:
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        completed = _command(
            [
                "docker",
                "exec",
                container,
                "curl",
                "--fail",
                "--silent",
                "--user",
                "opencode:openworker-local",
                "http://127.0.0.1:4096/global/health",
            ],
            timeout=5,
            check=False,
        )
        if completed.returncode == 0:
            return
        status = _command(
            ["docker", "inspect", container, "--format", "{{.State.Status}}"],
            timeout=5,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip() == b"exited":
            raise LifecycleError(f"OpenWorker container {container} exited during startup")
        time.sleep(1)
    raise LifecycleError(f"timed out waiting for OpenWorker {container}")


def _start_container(stack: TenantStack, network: str, gateway: str) -> None:
    token = stack.ingress_token_file.read_text(encoding="utf-8").strip()
    _command(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            stack.container,
            "--network",
            network,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--ulimit",
            "core=0",
            "--mount",
            f"type=bind,src={stack.root / 'data'},dst=/openworker/data",
            "--mount",
            (
                f"type=bind,src={stack.reader_socket},"
                "dst=/run/milai-mcp/reader-lite.sock,readonly"
            ),
            "--env",
            f"OPENWORKER_URL=http://{gateway}:{stack.host_port}/v1",
            "--env",
            f"OPENWORKER_KEY={token}",
            "--env",
            "OPENWORKER_PRINT_LOGS=1",
            IMAGE,
        ],
        timeout=60,
    )
    _container_health(stack.container)


def _restart_container(stack: TenantStack) -> None:
    _command(["docker", "start", stack.container], timeout=30)
    _container_health(stack.container)


def _container_json(container: str, arguments: list[str], timeout: int = 60) -> Any:
    completed = _command(["docker", "exec", container, *arguments], timeout=timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LifecycleError(f"container {container} returned invalid JSON") from exc


def _native_exchange(
    stack: TenantStack,
    *,
    title: str,
    prompt: str,
    session_id: str | None = None,
) -> NativeExchange:
    if session_id is None:
        created = _container_json(
            stack.container,
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--user",
                "opencode:openworker-local",
                "--request",
                "POST",
                "--header",
                "Content-Type: application/json",
                "--data-binary",
                json.dumps({"title": title}, separators=(",", ":")),
                "http://127.0.0.1:4096/session?directory=%2Fopenworker%2Fruntime",
            ],
            timeout=60,
        )
        session_id = created.get("id") if isinstance(created, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise LifecycleError("native OpenCode session identity is missing")
    _command(
        [
            "docker",
            "exec",
            "--workdir",
            "/openworker/runtime",
            "--env",
            "OPENCODE_CONFIG_DIR=/openworker/runtime",
            stack.container,
            "opencode",
            "run",
            "--attach",
            "http://127.0.0.1:4096",
            "--password",
            "openworker-local",
            "--format",
            "json",
            "--model",
            f"openworker/{MODEL}",
            "--session",
            session_id,
            "--dir",
            "/openworker/runtime",
            prompt,
        ],
        timeout=600,
    )
    messages = _container_json(
        stack.container,
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--user",
            "opencode:openworker-local",
            (
                f"http://127.0.0.1:4096/session/{session_id}/message?"
                "directory=%2Fopenworker%2Fruntime"
            ),
        ],
    )
    if not isinstance(messages, list):
        raise LifecycleError("native OpenCode messages response is invalid")
    assistant_rows = [
        row
        for row in messages
        if isinstance(row, dict)
        and isinstance(row.get("info"), dict)
        and row["info"].get("role") == "assistant"
        and isinstance(row["info"].get("parentID"), str)
    ]
    if not assistant_rows:
        raise LifecycleError("native OpenCode operation returned no assistant message")
    assistant = max(
        assistant_rows,
        key=lambda row: int(row["info"].get("time", {}).get("created", 0)),
    )
    user_id = assistant["info"]["parentID"]
    user_rows = [
        row
        for row in messages
        if isinstance(row, dict)
        and isinstance(row.get("info"), dict)
        and row["info"].get("role") == "user"
        and row["info"].get("id") == user_id
    ]
    if len(user_rows) != 1:
        raise LifecycleError("native OpenCode parent user identity is ambiguous")
    user = user_rows[0]

    def text_part(row: dict[str, Any]) -> str:
        parts = row.get("parts")
        if not isinstance(parts, list):
            raise LifecycleError("native OpenCode message parts are invalid")
        texts = [
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        ]
        if not texts:
            raise LifecycleError("native OpenCode message lost text content")
        value = texts[-1]
        if row["info"].get("role") == "user":
            try:
                decoded = json.loads(value.strip())
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, str) and decoded.strip():
                return decoded
            stripped = value.strip()
            if (
                len(stripped) >= 2
                and stripped[0] == stripped[-1] == '"'
                and "\n" in stripped
            ):
                return stripped[1:-1]
        return value

    def timestamp(row: dict[str, Any]) -> str:
        milliseconds = row["info"].get("time", {}).get("created")
        if not isinstance(milliseconds, int) or milliseconds <= 0:
            raise LifecycleError("native OpenCode message timestamp is invalid")
        return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat(timespec="milliseconds")

    user_messages = [
        row
        for row in messages
        if isinstance(row, dict)
        and isinstance(row.get("info"), dict)
        and row["info"].get("role") == "user"
        and int(row["info"].get("time", {}).get("created", 0))
        <= int(user["info"].get("time", {}).get("created", 0))
    ]
    assistant_id = assistant["info"].get("id")
    if not isinstance(assistant_id, str):
        raise LifecycleError("native OpenCode assistant identity is missing")
    return NativeExchange(
        session_id=session_id,
        user_message_id=user_id,
        assistant_message_id=assistant_id,
        user_content=text_part(user),
        assistant_content=text_part(assistant),
        user_observed_at=timestamp(user),
        assistant_observed_at=timestamp(assistant),
        round_ordinal=len(user_messages) - 1,
    )


def _trace_rows(stack: TenantStack) -> list[dict[str, Any]]:
    if not stack.trace.exists():
        return []
    return [
        json.loads(line)
        for line in stack.trace.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _settlement(stack: TenantStack, exchange: NativeExchange) -> dict[str, Any]:
    digest = _sha256_text(exchange.user_message_id)
    matches = [
        row
        for row in _trace_rows(stack)
        if row.get("event") == "HOST_MEMORY_SETTLED"
        and row.get("user_message_sha256") == digest
    ]
    if len(matches) != 1:
        raise LifecycleError("native exchange does not have exactly one Host settlement")
    return matches[0]


def _wait_projection(stack: TenantStack, outbox_ids: list[str]) -> dict[str, Any]:
    client = MilaiClient(
        stack.environment["MILAI_BASE_URL"],
        stack.environment["MILAI_AGENT_READER_TOKEN"],
        timeout_seconds=35,
        max_retries=0,
    )
    try:
        result = client.wait_for_projection_readiness(
            target_outbox_ids=outbox_ids,
            required_projections=["evidence"],
            expected_versions={"evidence": "evidence-search-v1"},
            timeout_ms=30_000,
            poll_interval_ms=50,
        )
    finally:
        client.close()
    if result.get("status") != "READY":
        raise LifecycleError("Evidence projection did not become ready")
    return result


def _get_evidence(stack: TenantStack, evidence_id: str) -> dict[str, Any]:
    status, value = _http_json(
        "GET",
        f"{stack.environment['MILAI_BASE_URL']}/v1/evidence/{evidence_id}",
        token=stack.environment["MILAI_API_TOKEN"],
    )
    if status != 200:
        raise LifecycleError(f"Evidence {evidence_id} could not be read")
    return value


def _same_time(left: str, right: str) -> bool:
    return datetime.fromisoformat(left.replace("Z", "+00:00")) == datetime.fromisoformat(
        right.replace("Z", "+00:00")
    )


def _validate_exchange_identity(
    stack: TenantStack,
    exchange: NativeExchange,
    settlement: dict[str, Any],
) -> list[dict[str, Any]]:
    ids = settlement.get("evidence_ids")
    if not isinstance(ids, list) or len(ids) != 2 or not all(isinstance(item, str) for item in ids):
        raise LifecycleError("Host settlement Evidence identity is invalid")
    user = _get_evidence(stack, ids[0])
    assistant = _get_evidence(stack, ids[1])
    expected = (
        (
            user,
            "OPENWORKER_USER_MESSAGE",
            "user",
            exchange.user_message_id,
            exchange.user_content,
            exchange.user_observed_at,
        ),
        (
            assistant,
            "OPENWORKER_ASSISTANT_MESSAGE",
            "assistant",
            exchange.assistant_message_id,
            exchange.assistant_content,
            exchange.assistant_observed_at,
        ),
    )
    for row, source_type, speaker, message_id, content, observed_at in expected:
        source_context = row.get("source_context")
        if not (
            row.get("tenant_id") == stack.environment["MILAI_TENANT_ID"]
            and row.get("source_type") == source_type
            and row.get("source_ref", "").partition("#")[0]
            == f"openworker://session/{exchange.session_id}/message/{message_id}"
            and row.get("subject_id") == SUBJECT
            and row.get("speaker") == speaker
            and row.get("speaker_source") == "STRUCTURED_TURN_METADATA"
            and row.get("source_context_source") == "STRUCTURED_TURN_METADATA"
            and isinstance(source_context, dict)
            and source_context.get("session_id") == exchange.session_id
            and source_context.get("turn_id") == message_id
            and source_context.get("round_ordinal") == exchange.round_ordinal
            and row.get("content") == content
            and row.get("content_hash") == _sha256_text(content)
            and isinstance(row.get("observed_at"), str)
            and _same_time(row["observed_at"], observed_at)
        ):
            raise LifecycleError("captured Evidence lost exact native source identity")
    if user["source_context"].get("next_turn_id") != exchange.assistant_message_id:
        raise LifecycleError("user Evidence lost the next-turn identity")
    if assistant["source_context"].get("previous_turn_id") != exchange.user_message_id:
        raise LifecycleError("assistant Evidence lost the previous-turn identity")
    return [user, assistant]


def _database_counts(owner_dsn: str) -> dict[str, Any]:
    with psycopg.connect(owner_dsn) as connection:
        evidence = {
            str(tenant): int(count)
            for tenant, count in connection.execute(
                "SELECT tenant_id, count(*) FROM milai.evidence_record GROUP BY tenant_id"
            ).fetchall()
        }
        projections = {
            str(tenant): int(count)
            for tenant, count in connection.execute(
                "SELECT tenant_id, count(*) FROM milai.evidence_search_document GROUP BY tenant_id"
            ).fetchall()
        }
        canonical = {
            table: int(
                connection.execute(
                    f"SELECT count(*) FROM milai.{table}"  # noqa: S608
                ).fetchone()[0]
            )
            for table in CANONICAL_TABLES
        }
    return {"evidence": evidence, "projections": projections, "canonical": canonical}


def _rls_counts(audit_dsn: str, tenant_id: str, actor_id: str) -> dict[str, int]:
    with psycopg.connect(audit_dsn) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (tenant_id,))
        connection.execute("SELECT set_config('milai.actor_id', %s, false)", (actor_id,))
        evidence = int(
            connection.execute("SELECT count(*) FROM milai.evidence_record").fetchone()[0]
        )
        projection = int(
            connection.execute("SELECT count(*) FROM milai.evidence_search_document").fetchone()[0]
        )
    return {"evidence": evidence, "projection": projection}


def _contains(value: object, needle: str) -> bool:
    return needle.casefold() in json.dumps(value, ensure_ascii=False).casefold()


def _cross_write(stack: TenantStack, other_tenant_id: str) -> tuple[int, str | None]:
    payload = {
        "tenant_id": other_tenant_id,
        "source_type": "OPENWORKER_USER_MESSAGE",
        "source_ref": f"openworker://cross-write/{uuid4()}",
        "subject_id": SUBJECT,
        "speaker": "user",
        "source_context": {
            "session_id": "cross-write-rejected",
            "turn_id": "cross-write-rejected",
            "turn_ordinal": 0,
            "round_id": "cross-write-rejected",
            "round_ordinal": 0,
        },
        "observed_at": datetime.now(UTC).isoformat(),
        "content": "synthetic rejected cross-tenant write probe",
        "permission_snapshot": {"readable": True, **SCOPE},
        "retention_state": "READABLE",
        "data_classification": "SYNTHETIC",
    }
    status, body = _http_json(
        "POST",
        f"{stack.environment['MILAI_BASE_URL']}/v1/evidence",
        token=stack.environment["MILAI_AGENT_SUBMITTER_TOKEN"],
        payload=payload,
        headers={"Idempotency-Key": f"p05-cross-{uuid4()}"},
    )
    raw_error = body.get("error")
    code = raw_error.get("code") if isinstance(raw_error, dict) else None
    return status, code if isinstance(code, str) else None


def _replay_exchange(stack: TenantStack, exchange: NativeExchange) -> dict[str, Any]:
    reader = McpUnixClient(stack.reader_socket)
    submitter = McpUnixClient(stack.submitter_socket)
    try:
        facade = OpenWorkerMemoryFacade(
            reader,
            submitter=submitter,
            subject_id=SUBJECT,
            permission_snapshot={"readable": True, **SCOPE},
            data_classification="SYNTHETIC",
        )
        receipt = facade.settle_exchange(
            task_epoch="post-restart-idempotency-replay",
            session_id=exchange.session_id,
            user_message_id=exchange.user_message_id,
            assistant_message_id=exchange.assistant_message_id,
            user_content=exchange.user_content,
            assistant_content=exchange.assistant_content,
            user_observed_at=exchange.user_observed_at,
            assistant_observed_at=exchange.assistant_observed_at,
            round_ordinal=exchange.round_ordinal,
        )
    finally:
        reader.close()
        submitter.close()
    return {
        "evidence_ids": [receipt.user.evidence_id, receipt.assistant.evidence_id],
        "outbox_ids": list(receipt.outbox_ids),
        "deduplicated": [receipt.user.deduplicated, receipt.assistant.deduplicated],
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output = args.output.resolve(strict=False)
    if output.exists():
        raise LifecycleError("output directory already exists")
    output.mkdir(mode=0o700, parents=True)
    run_id = args.run_id
    project = f"{run_id}-pg"
    network = f"{run_id}-net"
    postgres_started = False
    network_started = False
    containers: list[str] = []
    stacks: list[TenantStack] = []
    socket_root = Path(tempfile.mkdtemp(prefix="m5-", dir="/tmp"))
    socket_root.chmod(0o700)
    private: dict[str, Any] = {
        "schema": "milai.product05.lifecycle.private.v1",
        "run_id": run_id,
        "formal_holdout_consumed": False,
    }
    try:
        for path in (
            MCP_EXE,
            BROKER_EXE,
            HOST_EXE,
            API_EXE,
            WORKER_EXE,
            OPS_EXE,
            ALEMBIC_EXE,
            TOKENIZER,
            TASK_FIXTURE,
        ):
            if not path.is_file():
                raise LifecycleError(f"required local artifact is missing: {path}")
        expected_tokenizer = (
            "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
        )
        if _sha256_file(TOKENIZER) != expected_tokenizer:
            raise LifecycleError("frozen tokenizer identity changed")
        provider_status, provider_body = _http_json("GET", PROVIDER_ENDPOINT + "/v1/models")
        if provider_status != 200 or not _contains(provider_body, MODEL):
            raise LifecycleError("shared local Qwen provider is unavailable")

        postgres_port = _free_port()
        api_a_port = _free_port()
        api_b_port = _free_port()
        host_a_port = _free_port()
        host_b_port = _free_port()
        env_a_path = output / "tenant-a.env"
        _command(
            [
                str(OPS_EXE),
                "init",
                "--env-file",
                str(env_a_path),
                "--blob-root",
                str(output / "tenant-a" / "blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(api_a_port),
            ],
            cwd=RUNTIME,
        )
        env_a = _load_environment(env_a_path)
        env_b = dict(env_a)
        env_b.update(
            {
                "MILAI_BLOB_ROOT": str(output / "tenant-b" / "blobs"),
                "MILAI_TENANT_ID": str(uuid4()),
                "MILAI_LOCAL_ACTOR_ID": str(uuid4()),
                "MILAI_API_TOKEN": secrets.token_urlsafe(48),
                "MILAI_CAUSAL_TOKEN_SECRET": secrets.token_urlsafe(48),
                "MILAI_AGENT_READER_TOKEN": secrets.token_urlsafe(48),
                "MILAI_AGENT_SUBMITTER_TOKEN": secrets.token_urlsafe(48),
                "MILAI_AGENT_OPERATOR_TOKEN": secrets.token_urlsafe(48),
                "MILAI_AGENT_REVIEWER_TOKEN": secrets.token_urlsafe(48),
                "MILAI_BLOB_KEK_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
                "MILAI_BIND_PORT": str(api_b_port),
                "MILAI_BASE_URL": f"http://127.0.0.1:{api_b_port}",
            }
        )
        _write_environment(output / "tenant-b.env", env_b)

        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(env_a_path),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        _command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
        postgres_started = True
        deadline = time.monotonic() + 90
        while True:
            migration = _command(
                [str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                cwd=RUNTIME,
                env=_clean_environment(
                    {"MILAI_MIGRATION_DATABASE_URL": env_a["MILAI_MIGRATION_DATABASE_URL"]}
                ),
                timeout=120,
                check=False,
            )
            if migration.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise LifecycleError("fresh Product-05 PostgreSQL migration failed")
            time.sleep(1)

        _command(["docker", "network", "create", network], timeout=30)
        network_started = True
        network_info = json.loads(
            _command(["docker", "network", "inspect", network], timeout=30).stdout
        )
        gateway = network_info[0]["IPAM"]["Config"][0]["Gateway"]
        if not isinstance(gateway, str) or not gateway:
            raise LifecycleError("dedicated Docker bridge gateway is missing")

        stack_a = _make_stack(output, socket_root, "A", env_a, host_a_port, run_id)
        stack_b = _make_stack(output, socket_root, "B", env_b, host_b_port, run_id)
        stacks = [stack_a, stack_b]
        for stack in stacks:
            _start_process_stack(stack, gateway)
            _start_container(stack, network, gateway)
            containers.append(stack.container)

        marker_a = "cobalt-orchid-" + secrets.token_hex(5)
        marker_b = "amber-lantern-" + secrets.token_hex(5)
        private["markers"] = {"A": marker_a, "B": marker_b}

        first_a = _native_exchange(
            stack_a,
            title="Product05 tenant A capture",
            prompt=f"My private marker is {marker_a}. Acknowledge it briefly.",
        )
        first_b = _native_exchange(
            stack_b,
            title="Product05 tenant B capture",
            prompt=f"My private marker is {marker_b}. Acknowledge it briefly.",
        )
        first_a_settlement = _settlement(stack_a, first_a)
        first_b_settlement = _settlement(stack_b, first_b)
        _wait_projection(stack_a, list(first_a_settlement["outbox_ids"]))
        _wait_projection(stack_b, list(first_b_settlement["outbox_ids"]))

        derived_a = _native_exchange(
            stack_a,
            title="unused",
            session_id=first_a.session_id,
            prompt="What is my private marker? Return the exact marker.",
        )
        derived_a_settlement = _settlement(stack_a, derived_a)
        _wait_projection(stack_a, list(derived_a_settlement["outbox_ids"]))
        if marker_a.casefold() not in derived_a.assistant_content.casefold():
            raise LifecycleError("tenant A could not recall its marker before restart")
        if not derived_a_settlement.get("memory_support_refs"):
            raise LifecycleError("memory-derived assistant answer lost support lineage")

        before_restart = _database_counts(env_a["MILAI_MIGRATION_DATABASE_URL"])
        if any(before_restart["canonical"].values()):
            raise LifecycleError("OpenWorker lifecycle mutated Canonical state")

        for stack in stacks:
            _command(["docker", "stop", "--time", "15", stack.container], timeout=30)
        for stack in stacks:
            stack.processes.stop_all()
        for stack in stacks:
            _start_process_stack(stack, gateway)
        for stack in stacks:
            _restart_container(stack)

        post_a = _native_exchange(
            stack_a,
            title="Product05 tenant A restart recall",
            prompt=(
                "What exact private marker did the assistant state in its earlier answer? "
                "Return the marker."
            ),
        )
        post_b = _native_exchange(
            stack_b,
            title="Product05 tenant B restart recall",
            prompt="What is my private marker? Return the exact marker.",
        )
        post_a_settlement = _settlement(stack_a, post_a)
        post_b_settlement = _settlement(stack_b, post_b)
        _wait_projection(stack_a, list(post_a_settlement["outbox_ids"]))
        _wait_projection(stack_b, list(post_b_settlement["outbox_ids"]))
        if marker_a.casefold() not in post_a.assistant_content.casefold():
            raise LifecycleError("tenant A restart recall failed")
        if marker_b.casefold() not in post_b.assistant_content.casefold():
            raise LifecycleError("tenant B restart recall failed")
        if marker_b.casefold() in post_a.assistant_content.casefold():
            raise LifecycleError("tenant A answer leaked tenant B marker")
        if marker_a.casefold() in post_b.assistant_content.casefold():
            raise LifecycleError("tenant B answer leaked tenant A marker")

        with McpUnixClient(stack_a.reader_socket) as reader_a:
            tools_a = reader_a.list_tools()
            own_read_a = reader_a.resolve_memory(marker_a)
            cross_read_a = reader_a.resolve_memory(marker_b)
        with McpUnixClient(stack_b.reader_socket) as reader_b:
            tools_b = reader_b.list_tools()
            own_read_b = reader_b.resolve_memory(marker_b)
            cross_read_b = reader_b.resolve_memory(marker_a)
        forbidden_tools = {
            "milai_evidence_capture",
            "milai_proposal_create",
            "milai_evidence_revoke",
        }
        if forbidden_tools.intersection(tools_a) or forbidden_tools.intersection(tools_b):
            raise LifecycleError("write-capable tool became model-visible")
        if not _contains(own_read_a, marker_a) or not _contains(own_read_b, marker_b):
            raise LifecycleError("post-restart reader lost own tenant Evidence")
        if _contains(cross_read_a, marker_b) or _contains(cross_read_b, marker_a):
            raise LifecycleError("cross-tenant reader returned another tenant marker")

        cross_write_a = _cross_write(stack_a, env_b["MILAI_TENANT_ID"])
        cross_write_b = _cross_write(stack_b, env_a["MILAI_TENANT_ID"])
        if cross_write_a != (403, "TENANT_MISMATCH") or cross_write_b != (
            403,
            "TENANT_MISMATCH",
        ):
            raise LifecycleError("cross-tenant write was not rejected")

        all_exchanges = (
            (stack_a, first_a, first_a_settlement),
            (stack_b, first_b, first_b_settlement),
            (stack_a, derived_a, derived_a_settlement),
            (stack_a, post_a, post_a_settlement),
            (stack_b, post_b, post_b_settlement),
        )
        captured_rows = [
            row
            for stack, exchange, settlement in all_exchanges
            for row in _validate_exchange_identity(stack, exchange, settlement)
        ]
        if len(captured_rows) != 10:
            raise LifecycleError("unexpected lifecycle Evidence cardinality")
        forbidden_content = (
            "MILAI_MEMORY_DATA_BEGIN",
            "MILAI_CONTEXT",
            "postgresql://",
            "Bearer ",
            env_a["MILAI_AGENT_SUBMITTER_TOKEN"],
            env_b["MILAI_AGENT_SUBMITTER_TOKEN"],
        )
        if any(
            needle and needle in str(row.get("content", ""))
            for row in captured_rows
            for needle in forbidden_content
        ):
            raise LifecycleError("captured Evidence contains injected Context or a secret")
        if {row.get("speaker") for row in captured_rows} != {"user", "assistant"}:
            raise LifecycleError("non-conversation content crossed settlement allowlist")

        derived_assistant_id = derived_a_settlement["evidence_ids"][1]
        if derived_assistant_id in post_a_settlement.get("memory_support_refs", []):
            raise LifecycleError("assistant Evidence self-amplified as independent support")
        derived_source_ref = _get_evidence(stack_a, derived_assistant_id)["source_ref"]
        decoded = decode_memory_support_lineage(derived_source_ref)
        if decoded is None or tuple(derived_a_settlement["memory_support_refs"]) != (
            decoded.evidence_ids
        ):
            raise LifecycleError("assistant support lineage could not be replayed")

        counts_before_replay = _database_counts(env_a["MILAI_MIGRATION_DATABASE_URL"])
        replay = _replay_exchange(stack_a, first_a)
        counts_after_replay = _database_counts(env_a["MILAI_MIGRATION_DATABASE_URL"])
        if replay["deduplicated"] != [True, True] or counts_before_replay != counts_after_replay:
            raise LifecycleError("post-restart exact exchange replay created duplicate rows")

        rls_a = _rls_counts(
            env_a["MILAI_AUDIT_DATABASE_URL"],
            env_a["MILAI_TENANT_ID"],
            env_a["MILAI_LOCAL_ACTOR_ID"],
        )
        rls_b = _rls_counts(
            env_a["MILAI_AUDIT_DATABASE_URL"],
            env_b["MILAI_TENANT_ID"],
            env_b["MILAI_LOCAL_ACTOR_ID"],
        )
        final_counts = counts_after_replay
        for stack, rls in ((stack_a, rls_a), (stack_b, rls_b)):
            tenant = stack.environment["MILAI_TENANT_ID"]
            if rls["evidence"] != final_counts["evidence"].get(tenant, 0):
                raise LifecycleError("RLS Evidence visibility did not match the tenant namespace")
            if rls["projection"] != final_counts["projections"].get(tenant, 0):
                raise LifecycleError("RLS projection visibility did not match the tenant namespace")
        if any(final_counts["canonical"].values()):
            raise LifecycleError("read/capture lifecycle changed Canonical state")
        if final_counts["evidence"] != final_counts["projections"]:
            raise LifecycleError("tenant Evidence and projection cardinalities diverged")

        mount_a = json.loads(
            _command(
                ["docker", "inspect", stack_a.container, "--format", "{{json .Mounts}}"]
            ).stdout
        )
        mount_b = json.loads(
            _command(
                ["docker", "inspect", stack_b.container, "--format", "{{json .Mounts}}"]
            ).stdout
        )
        for mounts in (mount_a, mount_b):
            destinations = {item.get("Destination") for item in mounts}
            if "/run/milai-mcp/reader-lite.sock" not in destinations or any(
                destination in destinations
                for destination in (
                    "/run/milai-mcp/submitter.sock",
                    "/var/run/docker.sock",
                )
            ):
                raise LifecycleError("OpenWorker mount boundary is invalid")

        provider_events = [
            row
            for stack in stacks
            for row in _trace_rows(stack)
            if row.get("event") == "PROVIDER_ANSWER" and row.get("provider_call") is True
        ]
        ledger_events = [
            json.loads(line)
            for stack in stacks
            for line in stack.ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if any("retry" in str(row.get("event", "")).casefold() for row in ledger_events):
            raise LifecycleError("provider ledger contains an unexpected retry")

        private.update(
            {
                "native_exchanges": [
                    {
                        "tenant": stack.label,
                        "session_id": exchange.session_id,
                        "user_message_id": exchange.user_message_id,
                        "assistant_message_id": exchange.assistant_message_id,
                        "user_content": exchange.user_content,
                        "assistant_content": exchange.assistant_content,
                        "user_observed_at": exchange.user_observed_at,
                        "assistant_observed_at": exchange.assistant_observed_at,
                        "settlement": settlement,
                    }
                    for stack, exchange, settlement in all_exchanges
                ],
                "reader_tools": {"A": list(tools_a), "B": list(tools_b)},
                "cross_reads": {"A_for_B": cross_read_a, "B_for_A": cross_read_b},
                "database_counts": final_counts,
                "replay": replay,
            }
        )
        _replace_private(output / "lifecycle.private.json", private)

        summary = {
            "schema": "milai.product05.lifecycle.summary.v1",
            "run_id": run_id,
            "status": "PASS",
            "shared_postgresql_database": True,
            "tenant_count": 2,
            "same_subject_id_across_tenants": True,
            "native_openworker_operations": len(all_exchanges),
            "provider_calls": len(provider_events),
            "capture_success_rate": 1.0,
            "source_identity_integrity": 1.0,
            "assistant_support_lineage_rate": 1.0,
            "restart_recall": {"passed": 2, "total": 2},
            "projection_ready_rate": 1.0,
            "idempotent_replay_duplicate_rows": 0,
            "cross_tenant_read_leaks": 0,
            "cross_tenant_write_leaks": 0,
            "cross_tenant_projection_leaks": 0,
            "model_visible_submitter_or_operator_tools": 0,
            "captured_context_system_or_secret_payloads": 0,
            "assistant_self_amplification": 0,
            "unauthorized_canonical_mutations": 0,
            "automatic_semantic_retries": 0,
            "evidence_rows": sum(final_counts["evidence"].values()),
            "projection_rows": sum(final_counts["projections"].values()),
            "marker_sha256": {"A": _sha256_text(marker_a), "B": _sha256_text(marker_b)},
            "tokenizer_sha256": _sha256_file(TOKENIZER),
            "model": MODEL,
            "formal_holdout_consumed": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "postgres_volume_preserved": True,
        }
        _private_write(output / "summary.json", summary)
        return summary
    except Exception as exc:
        private["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        _replace_private(output / "lifecycle.private.json", private)
        raise
    finally:
        cleanup_containers = list(
            dict.fromkeys([*containers, *(stack.container for stack in stacks)])
        )
        for container in cleanup_containers:
            _command(["docker", "stop", "--time", "10", container], timeout=20, check=False)
            _command(["docker", "rm", container], timeout=20, check=False)
        for stack in stacks:
            stack.processes.stop_all()
        if network_started:
            _command(["docker", "network", "rm", network], timeout=30, check=False)
        if postgres_started:
            _command([*compose, "down"], cwd=RUNTIME, timeout=60, check=False)
        for path in sorted(socket_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_socket() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        socket_root.rmdir()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not 8 <= len(args.run_id) <= 48 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in args.run_id
    ):
        raise SystemExit("run-id must contain 8-48 lowercase alphanumeric/hyphen characters")
    try:
        summary = _run(args)
    except LifecycleError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
