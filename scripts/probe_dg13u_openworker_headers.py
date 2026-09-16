#!/usr/bin/env python3
"""Capture OpenCode chat.headers metadata against a local canned provider.

The probe starts only run-owned resources. Raw session, message, host-instance,
prompt, and credential values are never written to durable artifacts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROBE_SOURCE = Path(__file__).resolve()
RUNS_ROOT = ROOT / "var/dg13/runs"
TMP_ROOT = ROOT / "var/dg13/tmp"
CONTRACT = ROOT / "contracts/agent/v1/openworker-task-metadata-headers.md"
IMAGE = "milai-openworker:dg13u-u0-current-local"
HEADER_NAMES = (
    "X-MiLAi-Host-Instance",
    "X-MiLAi-Task-Session",
    "X-MiLAi-Task-Operation",
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


class ProbeError(RuntimeError):
    """Bounded probe failure."""


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


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _is_cra_path(path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(Path("/cra").resolve())
    except ValueError:
        return False
    return True


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID.fullmatch(run_id):
        raise ProbeError("invalid run_id")


def _prepare_paths(run_id: str) -> tuple[Path, Path]:
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


def _render_plugin() -> str:
    return """
import crypto from "node:crypto"

const hostInstance = crypto.randomUUID()

export const DG13UMetadataHeaders = async () => ({
  "chat.headers": async (input, output) => {
    output.headers["X-MiLAi-Host-Instance"] = hostInstance
    output.headers["X-MiLAi-Task-Session"] = input.sessionID
    output.headers["X-MiLAi-Task-Operation"] = input.message.id
  },
})
""".lstrip()


def _run_command(command: list[str], *, timeout: int = 60) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"command failed: {command[0]}") from exc
    if completed.returncode != 0:
        raise ProbeError(f"command returned nonzero: {command[0]}")
    return completed.stdout.strip()


def _image_identity() -> dict[str, Any]:
    raw = _run_command(["docker", "image", "inspect", IMAGE])
    try:
        values = json.loads(raw)
        value = values[0]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ProbeError("exact image identity is invalid") from exc
    if not isinstance(value, dict) or not str(value.get("Id", "")).startswith(
        "sha256:"
    ):
        raise ProbeError("exact image identity is absent")
    config = value.get("Config") if isinstance(value.get("Config"), dict) else {}
    return {
        "reference": IMAGE,
        "id": value["Id"],
        "repo_digests": sorted(value.get("RepoDigests") or []),
        "entrypoint": config.get("Entrypoint"),
        "working_dir": config.get("WorkingDir"),
    }


@dataclass
class _SinkState:
    port: int
    request_count: int = 0
    non_generation_requests: int = 0
    captured_headers: dict[str, str] = field(default_factory=dict)
    captured_request_inventory: dict[str, Any] = field(default_factory=dict)


def _request_inventory(raw: bytes) -> dict[str, Any]:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError("canned sink received invalid JSON") from exc
    if not isinstance(body, dict):
        raise ProbeError("canned sink request body is not an object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not all(
        isinstance(message, dict) for message in messages
    ):
        raise ProbeError("canned sink messages are invalid")
    stream_options = body.get("stream_options")
    if stream_options is not None and not isinstance(stream_options, dict):
        raise ProbeError("canned sink stream_options are invalid")
    return {
        "schema": "milai.dg13u.openworker-request-inventory.v1",
        "status": "PASS",
        "top_level_keys": sorted(body),
        "model": body.get("model"),
        "stream": body.get("stream"),
        "stream_option_keys": (
            sorted(stream_options) if isinstance(stream_options, dict) else []
        ),
        "message_roles": [message.get("role") for message in messages],
        "message_count": len(messages),
        "raw_content_persisted": False,
        "credentials_persisted": False,
    }


def _chat_completion_events() -> bytes:
    created = 1_700_000_000
    chunks = [
        {
            "id": "chatcmpl-dg13u-canned",
            "object": "chat.completion.chunk",
            "created": created,
            "model": "AUTO",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "capture-ok"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "chatcmpl-dg13u-canned",
            "object": "chat.completion.chunk",
            "created": created,
            "model": "AUTO",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    ]
    return (
        b"".join(b"data: " + _canonical_bytes(chunk) + b"\n\n" for chunk in chunks)
        + b"data: [DONE]\n\n"
    )


@contextmanager
def _fake_provider_sink(gateway: str) -> Iterator[_SinkState]:
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
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            state.non_generation_requests += 1
            if self.path.rstrip("/").endswith("/models"):
                self._send_json(
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": "AUTO",
                                "object": "model",
                                "owned_by": "local-canned",
                            }
                        ],
                    }
                )
            else:
                self._send_json({"status": "ok"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            if not self.path.rstrip("/").endswith("/chat/completions"):
                self._send_json({"error": {"message": "unsupported canned path"}}, 404)
                return
            state.request_count += 1
            state.captured_headers = {
                name: self.headers.get(name, "") for name in HEADER_NAMES
            }
            state.captured_request_inventory = _request_inventory(raw)
            raw = _chat_completion_events()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("x-request-id", "fake-dg13u-canned-request")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

    server = ThreadingHTTPServer((gateway, 0), Handler)
    state = _SinkState(port=int(server.server_address[1]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _basic_headers() -> dict[str, str]:
    encoded = base64.b64encode(b"opencode:openworker-local").decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _http_json(
    port: int,
    method: str,
    path: str,
    body: Mapping[str, Any] | None = None,
    *,
    timeout: float = 90,
) -> Any:
    raw = None if body is None else _canonical_bytes(body)
    headers = _basic_headers()
    if raw is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=raw,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise ProbeError("OpenCode HTTP request failed") from exc
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProbeError("OpenCode HTTP response was not JSON") from exc


def _wait_ready(port: int, container_name: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            health = _http_json(port, "GET", "/global/health", timeout=3)
        except ProbeError:
            time.sleep(0.5)
            continue
        logs = _run_command(["docker", "logs", container_name], timeout=10)
        if isinstance(health, dict) and "OC config schema OK" in logs:
            return
        time.sleep(0.5)
    raise ProbeError("OpenWorker/OpenCode readiness timeout")


def _message_id(history: Any, session_id: str) -> str:
    if not isinstance(history, list):
        raise ProbeError("OpenCode history is invalid")
    candidates: list[str] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        info = row.get("info") if isinstance(row.get("info"), dict) else row
        if (
            info.get("role") == "user"
            and info.get("sessionID") == session_id
            and isinstance(info.get("id"), str)
        ):
            candidates.append(info["id"])
    if len(candidates) != 1:
        raise ProbeError("one native user message identity was not observed")
    return candidates[0]


def _exercise_opencode(port: int) -> tuple[str, str]:
    directory = urllib.parse.quote("/openworker/runtime", safe="")
    session = _http_json(
        port,
        "POST",
        f"/session?directory={directory}",
        {"title": "DG13U metadata capture"},
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
                "model": {"providerID": "openworker", "modelID": "AUTO"},
                "parts": [{"type": "text", "text": "Return capture-ok."}],
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


def _redacted_header_evidence(
    headers: Mapping[str, str], *, session_id: str, message_id: str
) -> dict[str, Any]:
    if set(headers) != set(HEADER_NAMES):
        raise ProbeError("captured header set is incomplete")
    values = {name: headers[name] for name in HEADER_NAMES}
    if not all(
        value and value.isascii() and len(value) <= 256 for value in values.values()
    ):
        raise ProbeError("captured header value is invalid")
    try:
        uuid.UUID(values["X-MiLAi-Host-Instance"])
    except ValueError as exc:
        raise ProbeError("host instance is not a UUID") from exc
    if values["X-MiLAi-Task-Session"] != session_id:
        raise ProbeError("captured session header does not match native session")
    if values["X-MiLAi-Task-Operation"] != message_id:
        raise ProbeError("captured operation header does not match native message")
    hashes = {name: _sha256_bytes(values[name].encode()) for name in HEADER_NAMES}
    return {
        "schema": "milai.dg13u.openworker-header-capture.v1",
        "status": "PASS",
        "header_names": list(HEADER_NAMES),
        "value_sha256": hashes,
        "native_alignment": {
            "task_session": "MATCHED_OPENCODE_SESSION_ID",
            "task_operation": "MATCHED_OPENCODE_USER_MESSAGE_ID",
            "host_instance": "VALID_PROCESS_UUID",
        },
        "raw_values_persisted": False,
    }


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
    _validate_run_id(run_id)
    run_dir, temp_dir = _prepare_paths(run_id)
    suffix = _sha256_bytes(run_id.encode())[:16]
    container_name = f"milai-dg13u-headers-{suffix}"
    network_name = f"milai-dg13u-headers-net-{suffix}"
    plugin_path = temp_dir / "data/plugins/dg13u-metadata-headers.js"
    plugin_path.parent.mkdir(parents=True, mode=0o700)
    plugin_path.write_text(_render_plugin(), encoding="utf-8")
    os.chmod(plugin_path, 0o600)

    image: dict[str, Any] | None = None
    capture: dict[str, Any] | None = None
    request_inventory: dict[str, Any] | None = None
    error: Exception | None = None
    network_created = False
    container_created = False
    container_removed = False
    network_removed = False
    temp_removed = False
    cleanup_errors: list[str] = []
    fake_provider_requests = 0
    non_generation_requests = 0
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
            raise ProbeError("owned network gateway is absent")
        with _fake_provider_sink(gateway) as sink:
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
                    "OPENWORKER_KEY=dg13u-local-canned-only",
                    "--env",
                    f"OPENWORKER_URL=http://{gateway}:{sink.port}/v1",
                    "--mount",
                    f"type=bind,src={temp_dir / 'data'},dst=/openworker/data",
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
                raise ProbeError("OpenCode random host port is invalid") from exc
            _wait_ready(opencode_port, container_name)
            session_id, message_id = _exercise_opencode(opencode_port)
            fake_provider_requests = sink.request_count
            non_generation_requests = sink.non_generation_requests
            if fake_provider_requests != 1:
                raise ProbeError("expected exactly one canned provider request")
            capture = _redacted_header_evidence(
                sink.captured_headers,
                session_id=session_id,
                message_id=message_id,
            )
            request_inventory = sink.captured_request_inventory
    except Exception as exc:  # noqa: BLE001 - all failures need cleanup evidence
        error = exc
    finally:
        if "sink" in locals():
            fake_provider_requests = sink.request_count
            non_generation_requests = sink.non_generation_requests
        if container_created:
            try:
                _run_command(["docker", "rm", "-f", container_name], timeout=30)
                container_removed = True
            except Exception as exc:  # noqa: BLE001 - continue resource reconciliation
                cleanup_errors.append(type(exc).__name__)
        if network_created:
            try:
                _run_command(["docker", "network", "rm", network_name], timeout=30)
                network_removed = True
            except Exception as exc:  # noqa: BLE001 - continue resource reconciliation
                cleanup_errors.append(type(exc).__name__)
        try:
            temp_removed = _safe_remove_temp(temp_dir)
        except Exception as exc:  # noqa: BLE001 - durable cleanup failure receipt
            cleanup_errors.append(type(exc).__name__)
        try:
            remaining = _label_reconciliation(run_id)
            if remaining["container_count"] or remaining["network_count"]:
                cleanup_errors.append("OWNED_RESOURCE_REMAINS")
        except Exception as exc:  # noqa: BLE001 - reconciliation is part of cleanup
            remaining = {"container_count": -1, "network_count": -1}
            cleanup_errors.append(type(exc).__name__)

    cleanup = {
        "schema": "milai.dg13u.headers-probe-cleanup.v1",
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
        "existing_vllm_preserved": True,
        "external_vllm_lifecycle_mutations": 0,
        "cleanup_error_types": cleanup_errors,
        "finished_at": _now(),
    }
    ledger = {
        "schema": "milai.dg13u.headers-probe-calls.v1",
        "fake_provider_requests": fake_provider_requests,
        "real_provider_calls": 0,
        "mcp_calls": 0,
        "vllm_calls": 0,
        "automatic_retries": 0,
    }
    if capture is None:
        capture = {
            "schema": "milai.dg13u.openworker-header-capture.v1",
            "status": "FAIL",
            "header_names": list(HEADER_NAMES),
            "value_sha256": {},
            "raw_values_persisted": False,
        }
    if request_inventory is None:
        request_inventory = {
            "schema": "milai.dg13u.openworker-request-inventory.v1",
            "status": "FAIL",
            "top_level_keys": [],
            "message_roles": [],
            "raw_content_persisted": False,
            "credentials_persisted": False,
        }
    manifest = {
        "schema": "milai.dg13u.headers-probe-manifest.v1",
        "run_id": run_id,
        "probe_source": {
            "path": PROBE_SOURCE.relative_to(ROOT).as_posix(),
            "bytes": PROBE_SOURCE.stat().st_size,
            "sha256": _sha256_file(PROBE_SOURCE),
        },
        "image": image,
        "plugin": {
            "sha256": _sha256_bytes(_render_plugin().encode()),
            "mount": "/openworker/data/plugins/dg13u-metadata-headers.js",
        },
        "contract": {
            "path": CONTRACT.relative_to(ROOT).as_posix(),
            "sha256": _sha256_file(CONTRACT),
        },
        "ports": {"opencode_random_host_port": opencode_port, "fake_sink": sink_port},
        "fake_sink_non_generation_requests": non_generation_requests,
        "formal_evaluation_input": False,
        "raw_identifiers_persisted": False,
        "owner_acceptance": None,
    }
    _atomic_write(run_dir / "manifest.json", manifest)
    _atomic_write(run_dir / "header-capture.json", capture)
    _atomic_write(run_dir / "request-inventory.json", request_inventory)
    _atomic_write(run_dir / "call-ledger.json", ledger)
    _atomic_write(run_dir / "cleanup-receipt.json", cleanup)

    status = (
        "PASS"
        if error is None
        and capture["status"] == "PASS"
        and request_inventory["status"] == "PASS"
        and cleanup["status"] == "PASS"
        else "FAIL"
    )
    report = {
        "schema": "milai.dg13u.headers-probe-report.v1",
        "run_id": run_id,
        "status": status,
        "image_reference": IMAGE,
        "capture_status": capture["status"],
        "request_inventory_status": request_inventory["status"],
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
        description="Capture DG13U OpenWorker task metadata headers with a canned sink"
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    report = run_probe(args.run_id)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
