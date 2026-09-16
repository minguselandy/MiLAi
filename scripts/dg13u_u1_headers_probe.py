#!/usr/bin/env python3
"""Probe the U1 OpenWorker provider ingress without reaching MCP or vLLM.

Only run-owned Docker/network resources are created. Native identifiers, request
content, and the random ingress credential remain process-local; durable output
contains structural inventories and SHA-256 digests only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import sys
import threading
import urllib.parse
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from scripts import probe_dg13u_openworker_headers as u0_probe

ROOT = _SCRIPT_ROOT
PROBE_SOURCE = Path(__file__).resolve()
RUNS_ROOT = ROOT / "var/dg13/runs"
TMP_ROOT = ROOT / "var/dg13/tmp"
IMAGE = "milai-openworker:dg13u-u1-current-local"
EXACT_MODEL_ID = "Qwen3.6-35B-A3B-FP8"
HEADER_NAMES = (
    "X-MiLAi-Host-Instance",
    "X-MiLAi-Task-Session",
    "X-MiLAi-Task-Operation",
)
PROVIDER_FIELDS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "stream_options",
        "tools",
        "tool_choice",
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "response_format",
    }
)
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")

ProbeError = u0_probe.ProbeError
_atomic_write = u0_probe._atomic_write
_canonical_bytes = u0_probe._canonical_bytes
_http_json = u0_probe._http_json
_message_id = u0_probe._message_id
_run_command = u0_probe._run_command
_wait_ready = u0_probe._wait_ready


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_cra_path(path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(Path("/cra").resolve())
    except ValueError:
        return False
    return True


def _prepare_paths(run_id: str) -> tuple[Path, Path]:
    if _RUN_ID.fullmatch(run_id) is None:
        raise ProbeError("invalid run_id")
    run_dir = RUNS_ROOT / run_id
    temp_dir = TMP_ROOT / run_id
    if run_dir.exists() or temp_dir.exists():
        raise ProbeError("run or temporary path already exists")
    if not _is_cra_path(run_dir) or not _is_cra_path(temp_dir):
        raise ProbeError("probe paths must be on /cra")
    run_dir.mkdir(parents=True, mode=0o700)
    temp_dir.mkdir(parents=True, mode=0o700)
    os.chmod(run_dir, 0o700)
    os.chmod(temp_dir, 0o700)
    return run_dir, temp_dir


def _image_identity() -> dict[str, Any]:
    raw = _run_command(["docker", "image", "inspect", IMAGE])
    try:
        values = json.loads(raw)
        value = values[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ProbeError("U1 image identity is invalid") from exc
    if not isinstance(value, dict) or not str(value.get("Id", "")).startswith("sha256:"):
        raise ProbeError("U1 image identity is absent")
    config = value.get("Config") if isinstance(value.get("Config"), dict) else {}
    return {
        "reference": IMAGE,
        "id": value["Id"],
        "repo_digests": sorted(value.get("RepoDigests") or []),
        "entrypoint": config.get("Entrypoint"),
        "working_dir": config.get("WorkingDir"),
    }


def _tool_name(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    function = value.get("function")
    name = function.get("name") if isinstance(function, Mapping) else None
    return name if isinstance(name, str) else None


def _request_inventory(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError("fake Host received invalid JSON") from exc
    if not isinstance(body, dict):
        raise ProbeError("fake Host request body is not an object")
    unsupported = set(body) - PROVIDER_FIELDS
    if unsupported:
        raise ProbeError("unsupported provider request field")
    if body.get("model") != EXACT_MODEL_ID:
        raise ProbeError("provider request model is not the frozen model")
    if "messages" not in body or "stream" not in body:
        raise ProbeError("provider request required field is absent")
    messages = body.get("messages")
    if (
        not isinstance(messages, list)
        or not messages
        or any(
            not isinstance(message, dict) or message.get("role") not in MESSAGE_ROLES
            for message in messages
        )
    ):
        raise ProbeError("provider request messages are invalid")
    if body.get("stream") is not True:
        raise ProbeError("provider ingress preflight requires stream=true")
    if body.get("stream_options") != {"include_usage": True}:
        raise ProbeError("provider stream_options contract is invalid")
    tools = body.get("tools")
    if tools is not None and (
        not isinstance(tools, list) or any(not isinstance(tool, dict) for tool in tools)
    ):
        raise ProbeError("provider tools contract is invalid")
    tool_choice = body.get("tool_choice")
    if tool_choice is not None and not isinstance(tool_choice, (str, dict)):
        raise ProbeError("provider tool_choice contract is invalid")
    for name in ("temperature", "top_p"):
        value = body.get(name)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ProbeError("provider generation field is invalid")
    max_tokens = body.get("max_tokens")
    if max_tokens is not None and (
        not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1
    ):
        raise ProbeError("provider max_tokens is invalid")
    seed = body.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise ProbeError("provider seed is invalid")
    response_format = body.get("response_format")
    if response_format is not None and not isinstance(response_format, dict):
        raise ProbeError("provider response_format is invalid")

    tool_names = [_tool_name(tool) for tool in tools or []]
    memory_tool_count = sum(
        name == "milai_recall" or bool(name and name.endswith("_milai_recall"))
        for name in tool_names
    )
    return {
        "schema": "milai.dg13u.u1-provider-ingress-request.v1",
        "status": "PASS",
        "request_sha256": _sha256_bytes(raw),
        "top_level_keys": sorted(body),
        "accepted_field_subset": True,
        "model": body["model"],
        "stream": body["stream"],
        "stream_options": body["stream_options"],
        "message_roles": [message["role"] for message in messages],
        "message_count": len(messages),
        "tool_count": len(tools or []),
        "tool_names": sorted(name for name in tool_names if name is not None),
        "memory_tool_count": memory_tool_count,
        "generation_fields": sorted(
            set(body)
            & {"temperature", "top_p", "max_tokens", "seed", "response_format"}
        ),
        "raw_content_persisted": False,
        "credentials_persisted": False,
    }


def _redacted_ingress_evidence(
    headers: Mapping[str, Sequence[str]],
    *,
    expected_token: str,
    session_id: str,
    message_id: str,
) -> dict[str, Any]:
    authorization = tuple(headers.get("Authorization", ()))
    expected = f"Bearer {expected_token}"
    if len(authorization) != 1 or not hmac.compare_digest(authorization[0], expected):
        raise ProbeError("ingress Bearer authentication mismatch")
    selected = {name: tuple(headers.get(name, ())) for name in HEADER_NAMES}
    if any(len(values) != 1 for values in selected.values()):
        raise ProbeError("native metadata header cardinality is invalid")
    values = {name: selected[name][0] for name in HEADER_NAMES}
    if any(
        not value.isascii() or _IDENTIFIER.fullmatch(value) is None
        for value in values.values()
    ):
        raise ProbeError("native metadata header value is invalid")
    try:
        host_instance = uuid.UUID(values["X-MiLAi-Host-Instance"])
    except ValueError as exc:
        raise ProbeError("host instance is not a UUID") from exc
    if str(host_instance) != values["X-MiLAi-Host-Instance"].lower():
        raise ProbeError("host instance UUID is not canonical")
    if values["X-MiLAi-Task-Session"] != session_id:
        raise ProbeError("session header does not match native session")
    if values["X-MiLAi-Task-Operation"] != message_id:
        raise ProbeError("operation header does not match native user message")
    return {
        "schema": "milai.dg13u.u1-provider-ingress-capture.v1",
        "status": "PASS",
        "authorization": "EXACT_SINGLE_BEARER_MATCH",
        "authorization_sha256": _sha256_bytes(authorization[0].encode()),
        "header_names": list(HEADER_NAMES),
        "header_cardinality": {name: len(selected[name]) for name in HEADER_NAMES},
        "value_sha256": {
            name: _sha256_bytes(values[name].encode()) for name in HEADER_NAMES
        },
        "native_alignment": {
            "task_session": "MATCHED_OPENCODE_SESSION_ID",
            "task_operation": "MATCHED_OPENCODE_USER_MESSAGE_ID",
            "host_instance": "VALID_PROCESS_UUID",
        },
        "raw_values_persisted": False,
        "credential_persisted": False,
    }


def _chat_completion_events() -> bytes:
    chunks = [
        {
            "id": "chatcmpl-dg13u-u1-ingress",
            "object": "chat.completion.chunk",
            "created": 1_700_000_000,
            "model": EXACT_MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "u1-ingress-ok"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-dg13u-u1-ingress",
            "object": "chat.completion.chunk",
            "created": 1_700_000_000,
            "model": EXACT_MODEL_ID,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    ]
    return (
        b"".join(b"data: " + _canonical_bytes(chunk) + b"\n\n" for chunk in chunks)
        + b"data: [DONE]\n\n"
    )


@dataclass
class _SinkState:
    port: int
    expected_token: str
    request_count: int = 0
    non_generation_requests: int = 0
    rejected_requests: int = 0
    captured_headers: dict[str, list[str]] = field(default_factory=dict)
    captured_request_inventory: dict[str, Any] = field(default_factory=dict)
    capture_error: ProbeError | None = None


@contextmanager
def _fake_host_sink(gateway: str, expected_token: str) -> Iterator[_SinkState]:
    state: _SinkState

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(self, value: Any, status: int = 200) -> None:
            raw = _canonical_bytes(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            values = self.headers.get_all("Authorization", [])
            expected = f"Bearer {state.expected_token}"
            valid = len(values) == 1 and hmac.compare_digest(values[0], expected)
            if not valid:
                state.rejected_requests += 1
                self._send_json({"error": {"reason_code": "AUTHENTICATION_REQUIRED"}}, 401)
            return valid

        def do_GET(self) -> None:
            if not self._authorized():
                return
            state.non_generation_requests += 1
            if self.path.rstrip("/").endswith("/models"):
                self._send_json(
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": EXACT_MODEL_ID,
                                "object": "model",
                                "owned_by": "milai-u1-fake-host",
                            }
                        ],
                    }
                )
            else:
                self._send_json({"status": "ok"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if not self.path.rstrip("/").endswith("/chat/completions"):
                self._send_json({"error": {"reason_code": "PATH_UNSUPPORTED"}}, 404)
                return
            state.request_count += 1
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            state.captured_headers = {
                "Authorization": self.headers.get_all("Authorization", []),
                **{name: self.headers.get_all(name, []) for name in HEADER_NAMES},
            }
            try:
                state.captured_request_inventory = _request_inventory(raw)
            except ProbeError as exc:
                state.capture_error = exc
                self._send_json({"error": {"reason_code": "REQUEST_INVALID"}}, 400)
                return
            response = _chat_completion_events()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            self.close_connection = True

    server = ThreadingHTTPServer((gateway, 0), Handler)
    state = _SinkState(
        port=int(server.server_address[1]),
        expected_token=expected_token,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _exercise_opencode(port: int) -> tuple[str, str]:
    directory = urllib.parse.quote("/openworker/runtime", safe="")
    session = _http_json(
        port,
        "POST",
        f"/session?directory={directory}",
        {"title": "DG13U U1 provider ingress preflight"},
    )
    if not isinstance(session, dict) or not isinstance(session.get("id"), str):
        raise ProbeError("OpenCode session identity is absent")
    session_id = session["id"]
    try:
        _http_json(
            port,
            "POST",
            f"/session/{session_id}/message?directory={directory}",
            {
                "model": {"providerID": "openworker", "modelID": EXACT_MODEL_ID},
                "parts": [
                    {
                        "type": "text",
                        "text": "Synthetic NONE preflight: reply u1-ingress-ok.",
                    }
                ],
            },
        )
        history = _http_json(
            port,
            "GET",
            f"/session/{session_id}/message?directory={directory}",
        )
        return session_id, _message_id(history, session_id)
    finally:
        try:
            _http_json(
                port,
                "DELETE",
                f"/session/{session_id}?directory={directory}",
                timeout=10,
            )
        except ProbeError:
            pass


def _write_mcp_disabled_config(path: Path) -> str:
    source = ROOT / "integrations/openworker-mcp/openworker/opencode.json"
    try:
        value = json.loads(source.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeError("U1 OpenCode config is unreadable") from exc
    if not isinstance(value, dict) or value.get("model") != f"openworker/{EXACT_MODEL_ID}":
        raise ProbeError("U1 OpenCode config model is invalid")
    mcp = value.get("mcp")
    if not isinstance(mcp, dict) or not isinstance(mcp.get("milai"), dict):
        raise ProbeError("U1 OpenCode MiLA MCP config is absent")
    value["mcp"] = {"milai": {**mcp["milai"], "enabled": False}}
    raw = _canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    os.chmod(path, 0o400)
    return _sha256_bytes(raw)


def _safe_remove_temp(temp_dir: Path) -> bool:
    resolved = temp_dir.resolve(strict=False)
    if resolved.parent != TMP_ROOT.resolve(strict=False) or not _is_cra_path(resolved):
        raise ProbeError("refusing cleanup outside exact temporary root")
    if resolved.exists():
        shutil.rmtree(resolved)
    return not resolved.exists()


def _artifact_hashes(run_dir: Path) -> dict[str, str]:
    for path in run_dir.rglob("*"):
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.is_file():
            os.chmod(path, 0o600)
    return {
        path.name: _sha256_file(path)
        for path in sorted(run_dir.iterdir())
        if path.is_file() and path.name != "report.json"
    }


def _label_reconciliation(run_id: str) -> dict[str, int]:
    label = f"label=io.milai.dg13u.run-id={run_id}"
    containers = _run_command(
        ["docker", "ps", "-a", "--filter", label, "--format", "{{.ID}}"],
        timeout=10,
    ).splitlines()
    networks = _run_command(
        ["docker", "network", "ls", "--filter", label, "--format", "{{.ID}}"],
        timeout=10,
    ).splitlines()
    return {
        "container_count": len([value for value in containers if value]),
        "network_count": len([value for value in networks if value]),
    }


def run_probe(run_id: str) -> dict[str, Any]:
    run_dir, temp_dir = _prepare_paths(run_id)
    suffix = _sha256_bytes(run_id.encode())[:16]
    container_name = f"milai-dg13u-u1-headers-{suffix}"
    network_name = f"milai-dg13u-u1-headers-net-{suffix}"
    ingress_token = secrets.token_urlsafe(32)
    override_config = temp_dir / "opencode.u1-ingress.json"
    override_sha256 = _write_mcp_disabled_config(override_config)
    data_dir = temp_dir / "data"
    data_dir.mkdir(mode=0o700)

    image: dict[str, Any] | None = None
    capture: dict[str, Any] | None = None
    inventory: dict[str, Any] | None = None
    error: Exception | None = None
    network_created = False
    container_created = False
    container_removed = False
    network_removed = False
    temp_removed = False
    cleanup_errors: list[str] = []
    fake_host_requests = 0
    non_generation_requests = 0
    rejected_requests = 0
    opencode_port: int | None = None
    sink_port: int | None = None

    try:
        image = _image_identity()
        _run_command(
            [
                "docker",
                "network",
                "create",
                "--label",
                f"io.milai.dg13u.run-id={run_id}",
                network_name,
            ]
        )
        network_created = True
        gateway = _run_command(
            [
                "docker",
                "network",
                "inspect",
                network_name,
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ]
        )
        if not gateway:
            raise ProbeError("owned Docker bridge gateway is absent")
        with _fake_host_sink(gateway, ingress_token) as sink:
            sink_port = sink.port
            _run_command(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    container_name,
                    "--network",
                    network_name,
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--ulimit",
                    "core=0:0",
                    "--publish",
                    "127.0.0.1::4096",
                    "--env",
                    f"OPENWORKER_KEY={ingress_token}",
                    "--env",
                    f"OPENWORKER_URL=http://{gateway}:{sink.port}/v1",
                    "--mount",
                    f"type=bind,src={data_dir},dst=/openworker/data",
                    "--mount",
                    (
                        f"type=bind,src={override_config},"
                        "dst=/openworker/image/config/opencode.json,readonly"
                    ),
                    "--label",
                    f"io.milai.dg13u.run-id={run_id}",
                    IMAGE,
                ],
                timeout=120,
            )
            container_created = True
            port_text = _run_command(
                ["docker", "port", container_name, "4096/tcp"], timeout=10
            )
            try:
                opencode_port = int(port_text.rsplit(":", 1)[1])
            except (IndexError, ValueError) as exc:
                raise ProbeError("OpenCode random loopback port is invalid") from exc
            _wait_ready(opencode_port, container_name)
            session_id, message_id = _exercise_opencode(opencode_port)
            fake_host_requests = sink.request_count
            non_generation_requests = sink.non_generation_requests
            rejected_requests = sink.rejected_requests
            if sink.capture_error is not None:
                raise sink.capture_error
            if fake_host_requests != 1:
                raise ProbeError("expected exactly one fake Host generation request")
            if rejected_requests != 0:
                raise ProbeError("fake Host rejected an ingress request")
            capture = _redacted_ingress_evidence(
                sink.captured_headers,
                expected_token=ingress_token,
                session_id=session_id,
                message_id=message_id,
            )
            inventory = sink.captured_request_inventory
    except Exception as exc:  # noqa: BLE001 - cleanup receipt must cover every failure
        error = exc
    finally:
        if "sink" in locals():
            fake_host_requests = sink.request_count
            non_generation_requests = sink.non_generation_requests
            rejected_requests = sink.rejected_requests
        if container_created:
            try:
                _run_command(["docker", "rm", "-f", container_name], timeout=30)
                container_removed = True
            except Exception as exc:  # noqa: BLE001 - continue owned cleanup
                cleanup_errors.append(type(exc).__name__)
        if network_created:
            try:
                _run_command(["docker", "network", "rm", network_name], timeout=30)
                network_removed = True
            except Exception as exc:  # noqa: BLE001 - continue owned cleanup
                cleanup_errors.append(type(exc).__name__)
        try:
            temp_removed = _safe_remove_temp(temp_dir)
        except Exception as exc:  # noqa: BLE001 - durable cleanup evidence
            cleanup_errors.append(type(exc).__name__)
        try:
            remaining = _label_reconciliation(run_id)
            if remaining["container_count"] or remaining["network_count"]:
                cleanup_errors.append("OWNED_RESOURCE_REMAINS")
        except Exception as exc:  # noqa: BLE001 - reconciliation is mandatory
            remaining = {"container_count": -1, "network_count": -1}
            cleanup_errors.append(type(exc).__name__)

    cleanup = {
        "schema": "milai.dg13u.u1-provider-ingress-cleanup.v1",
        "status": "PASS" if not cleanup_errors else "FAIL",
        "container": {
            "name": container_name,
            "created": container_created,
            "removed": container_removed if container_created else None,
        },
        "network": {
            "name": network_name,
            "created": network_created,
            "removed": network_removed if network_created else None,
        },
        "temporary_directory": {"removed": temp_removed},
        "label_reconciliation": remaining,
        "existing_containers_targeted": 0,
        "existing_vllm_preserved": True,
        "external_vllm_lifecycle_mutations": 0,
        "cleanup_error_types": cleanup_errors,
        "finished_at": _now(),
    }
    ledger = {
        "schema": "milai.dg13u.u1-provider-ingress-calls.v1",
        "fake_host_requests": fake_host_requests,
        "fake_host_non_generation_requests": non_generation_requests,
        "fake_host_rejected_requests": rejected_requests,
        "real_provider_calls": 0,
        "mcp_calls": 0,
        "vllm_calls": 0,
        "automatic_retries": 0,
    }
    if capture is None:
        capture = {
            "schema": "milai.dg13u.u1-provider-ingress-capture.v1",
            "status": "FAIL",
            "authorization": "NOT_PROVEN",
            "header_names": list(HEADER_NAMES),
            "value_sha256": {},
            "raw_values_persisted": False,
            "credential_persisted": False,
        }
    if inventory is None:
        inventory = {
            "schema": "milai.dg13u.u1-provider-ingress-request.v1",
            "status": "FAIL",
            "top_level_keys": [],
            "message_roles": [],
            "raw_content_persisted": False,
            "credentials_persisted": False,
        }
    manifest = {
        "schema": "milai.dg13u.u1-provider-ingress-manifest.v1",
        "run_id": run_id,
        "probe_source": {
            "path": PROBE_SOURCE.relative_to(ROOT).as_posix(),
            "bytes": PROBE_SOURCE.stat().st_size,
            "sha256": _sha256_file(PROBE_SOURCE),
        },
        "image": image,
        "topology": {
            "docker_bridge": "RUN_OWNED_DEDICATED",
            "opencode_api_publish": "RANDOM_LOOPBACK_PORT",
            "fake_host_bind": "RUN_OWNED_BRIDGE_GATEWAY",
            "historical_gateway_in_path": False,
            "real_provider_endpoint_provisioned": False,
            "mcp_endpoint_provisioned": False,
        },
        "mcp_disabled_override_sha256": override_sha256,
        "ingress_token_sha256": _sha256_bytes(ingress_token.encode()),
        "ports": {"opencode_random_host_port": opencode_port, "fake_host": sink_port},
        "formal_evaluation_input": False,
        "raw_identifiers_persisted": False,
        "credentials_persisted": False,
    }
    _atomic_write(run_dir / "manifest.json", manifest)
    _atomic_write(run_dir / "ingress-capture.json", capture)
    _atomic_write(run_dir / "request-inventory.json", inventory)
    _atomic_write(run_dir / "call-ledger.json", ledger)
    _atomic_write(run_dir / "cleanup-receipt.json", cleanup)

    status = (
        "PASS"
        if error is None
        and capture["status"] == "PASS"
        and inventory["status"] == "PASS"
        and cleanup["status"] == "PASS"
        else "FAIL"
    )
    report = {
        "schema": "milai.dg13u.u1-provider-ingress-report.v1",
        "run_id": run_id,
        "status": status,
        "image_reference": IMAGE,
        "capture_status": capture["status"],
        "request_inventory_status": inventory["status"],
        "calls": ledger,
        "cleanup_status": cleanup["status"],
        "error": (
            None
            if error is None and not cleanup_errors
            else {
                "type": type(error).__name__ if error is not None else "CleanupError",
                "message_sha256": _sha256_bytes(str(error).encode()) if error else None,
            }
        ),
        "artifact_sha256": _artifact_hashes(run_dir),
        "finished_at": _now(),
    }
    _atomic_write(run_dir / "report.json", report)
    os.chmod(run_dir, 0o700)
    for path in run_dir.iterdir():
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe DG13U U1 OpenWorker provider ingress with a fake Host"
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = run_probe(args.run_id)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
