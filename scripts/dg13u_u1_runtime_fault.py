#!/usr/bin/env python3
"""Run-owned loopback Runtime prepare-context fault injector for DG13-U1."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import stat
import tempfile
import threading
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import FrameType
from typing import Any, Literal, Self

FaultMode = Literal["UNAVAILABLE", "MALFORMED", "TIMEOUT"]
_SCHEMA = "milai.dg13u.u1-runtime-fault-receipt.v1"
_PREPARE_PATH = "/v1/memory/prepare-context"
_CAPABILITIES_PATH = "/v1/capabilities"
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{7,95}$")
_SECRET_PATH_COMPONENTS = frozenset(
    {
        "api-key",
        "credential",
        "credentials",
        "key",
        "keys",
        "password",
        "passwords",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)
_MALFORMED_CONTEXT = b'{"status":"READY","context_capsule":'
_UNAVAILABLE_CONTEXT = {
    "route": "L0",
    "status": "DEGRADED",
    "reason": "CANONICAL_UNAVAILABLE",
    "context_capsule": None,
    "context_delta": {"status": "UNCHANGED"},
    "relevant_open_issue_closure": [],
    "canonical_position": None,
    "validation_token": None,
    "memory_slot_coverage": None,
    "prepared_detail_level": None,
    "requested_detail_level": None,
    "trace_pointer": "dg13u-runtime-unavailable",
    "usage": {"prepare_context_calls": 1},
    "current_state_envelope": {
        "status": "CANONICAL_UNAVAILABLE",
        "claims": [],
        "open_issues": [],
        "canonical_position": None,
        "slot_validation_handle": None,
        "trace_id": "dg13u-runtime-unavailable",
    },
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(_canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _artifact_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("artifact_path must be absolute")
    if path.suffix != ".json" or path.name in {"", ".json"}:
        raise ValueError("artifact_path must name a JSON file")
    if any(part.casefold() in _SECRET_PATH_COMPONENTS for part in path.parts):
        raise ValueError("artifact_path is secret-like")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise ValueError("artifact parent must already exist") from exc
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise ValueError("artifact parent must be a real directory")
    if parent.st_uid != os.geteuid():
        raise ValueError("artifact parent owner is unsafe")
    if stat.S_IMODE(parent.st_mode) & 0o077:
        raise ValueError("artifact parent mode is unsafe")
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    return path


def _valid_run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ValueError("run_id is invalid")
    lowered = value.casefold()
    if any(marker in lowered.split("-") for marker in _SECRET_PATH_COMPONENTS):
        raise ValueError("run_id is secret-like")
    return value


def _loopback_host(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("host must be loopback IPv4")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("host must be loopback IPv4") from None
    if address.version != 4 or not address.is_loopback:
        raise ValueError("host must be loopback IPv4")
    return str(address)


@dataclass(frozen=True, slots=True)
class ClosedEndpointIdentity:
    """A loopback origin whose pre-bound listener has already been closed."""

    base_url: str
    endpoint_sha256: str
    port: int
    prebound_then_closed: Literal[True]


def closed_loopback_endpoint_identity(
    *, host: str = "127.0.0.1"
) -> ClosedEndpointIdentity:
    """Reserve, identify, and close a loopback port for the Runtime-DOWN case."""

    bounded_host = _loopback_host(host)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((bounded_host, 0))
        port = int(listener.getsockname()[1])
    finally:
        listener.close()
    base_url = f"http://{bounded_host}:{port}"
    return ClosedEndpointIdentity(
        base_url=base_url,
        endpoint_sha256=hashlib.sha256(base_url.encode()).hexdigest(),
        port=port,
        prebound_then_closed=True,
    )


class _OwnedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True


class RuntimeFaultInjector(AbstractContextManager["RuntimeFaultInjector"]):
    """One-attempt fault endpoint for the Runtime composite Context boundary."""

    def __init__(
        self,
        mode: FaultMode,
        *,
        artifact_path: str | Path,
        run_id: str,
        delay_seconds: float,
        host: str = "127.0.0.1",
        port: int = 0,
        max_body_bytes: int = 1_048_576,
    ) -> None:
        if mode not in {"UNAVAILABLE", "MALFORMED", "TIMEOUT"}:
            raise ValueError("mode must be UNAVAILABLE, MALFORMED, or TIMEOUT")
        bounded_run_id = _valid_run_id(run_id)
        if not isinstance(delay_seconds, (int, float)) or isinstance(delay_seconds, bool):
            raise TypeError("delay_seconds must be in [0.01, 15.0]")
        if not 0.01 <= float(delay_seconds) <= 15.0:
            raise ValueError("delay_seconds must be in [0.01, 15.0]")
        bounded_host = _loopback_host(host)
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65_535:
            raise ValueError("port must be in [0, 65535]")
        if (
            not isinstance(max_body_bytes, int)
            or isinstance(max_body_bytes, bool)
            or not 1 <= max_body_bytes <= 8_388_608
        ):
            raise ValueError("max_body_bytes must be in [1, 8388608]")
        bounded_artifact = _artifact_path(artifact_path)

        self.mode = mode
        self.artifact_path = bounded_artifact
        self.run_id = bounded_run_id
        self.delay_seconds = float(delay_seconds)
        self.host = bounded_host
        self.requested_port = port
        self.max_body_bytes = max_body_bytes
        self._port: int | None = None
        self._server: _OwnedThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._active = False
        self._request_count = 0
        self._capability_request_count = 0
        self._rejected_request_count = 0
        self._faults_injected = 0
        self._last_outcome: str | None = None
        self._cleanup = {
            "attempted": False,
            "listener_closed": False,
            "server_stopped": False,
            "worker_threads_stopped": False,
        }

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("Runtime fault injector has not started")
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def prepare_context_url(self) -> str:
        return self.base_url + _PREPARE_PATH

    @property
    def request_count(self) -> int:
        with self._lock:
            return self._request_count

    def _receipt(self) -> dict[str, Any]:
        origin = self.base_url
        return {
            "schema": _SCHEMA,
            "run_id": self.run_id,
            "mode": self.mode,
            "delay_seconds": self.delay_seconds,
            "active": self._active,
            "endpoint": {
                "origin_sha256": hashlib.sha256(origin.encode()).hexdigest(),
                "port": self.port,
                "prepare_path_sha256": hashlib.sha256(_PREPARE_PATH.encode()).hexdigest(),
            },
            "request_count": self._request_count,
            "capability_request_count": self._capability_request_count,
            "rejected_request_count": self._rejected_request_count,
            "faults_injected": self._faults_injected,
            "automatic_retries": 0,
            "last_outcome": self._last_outcome,
            "cleanup": dict(self._cleanup),
            "reconciliation": {
                "single_request": self._request_count == 1,
                "no_additional_request_observed": self._rejected_request_count == 0,
                "raw_request_persisted": False,
                "credential_material_persisted": False,
                "prompt_material_persisted": False,
                "response_is_valid_context": (
                    self.mode == "UNAVAILABLE" and self._faults_injected == 1
                ),
            },
        }

    def _persist_locked(self) -> None:
        _atomic_private_json(self.artifact_path, self._receipt())

    def _claim_capability(self) -> bool:
        with self._lock:
            if self._capability_request_count >= 1:
                self._rejected_request_count += 1
                self._last_outcome = "ADDITIONAL_CAPABILITY_REQUEST_REJECTED"
                self._persist_locked()
                return False
            self._capability_request_count = 1
            self._last_outcome = "CAPABILITY_NEGOTIATED"
            self._persist_locked()
            return True

    def _claim_prepare(self) -> bool:
        with self._lock:
            if self._request_count >= 1:
                self._rejected_request_count += 1
                self._last_outcome = "ADDITIONAL_PREPARE_REQUEST_REJECTED"
                self._persist_locked()
                return False
            self._request_count = 1
            self._last_outcome = "PREPARE_REQUEST_CLAIMED"
            self._persist_locked()
            return True

    def _set_outcome(self, outcome: str, *, injected: bool = False) -> None:
        with self._lock:
            self._last_outcome = outcome
            if injected:
                self._faults_injected += 1
            self._persist_locked()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _send(self, status_code: int, raw: bytes, content_type: str) -> bool:
                try:
                    self.send_response(status_code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    self.close_connection = True
                    return False
                return True

            def _send_json(self, status_code: int, value: Mapping[str, Any]) -> bool:
                return self._send(status_code, _canonical_bytes(value), "application/json")

            def do_GET(self) -> None:
                if self.path != _CAPABILITIES_PATH:
                    self._send_json(404, {"error": "NOT_FOUND"})
                    return
                if not owner._claim_capability():
                    self.close_connection = True
                    self._send_json(409, {"error": "CAPABILITY_REQUEST_LIMIT"})
                    return
                self._send_json(
                    200,
                    {
                        "api_version": "1",
                        "contract_version": "agent.v1",
                        "runtime_version": "dg13u-fault-v1",
                        "profile": "reader",
                        "capabilities": ["memory:read"],
                        "routes": ["L0", "L1"],
                        "consistency_modes": ["CANONICAL_REQUIRED"],
                        "agent_profiles": ["reader"],
                        "features": {"context_capsule": True, "remote_access": False},
                        "limits": {"query_chars": 2_000, "max_results": 3},
                        "data_mode": "SYNTHETIC_ONLY",
                        "schema_status": "FAULT_FIXTURE",
                        "implementation_status": "FAULT_FIXTURE",
                    },
                )

            def do_POST(self) -> None:
                if self.path != _PREPARE_PATH:
                    self._send_json(404, {"error": "NOT_FOUND"})
                    return
                if not owner._claim_prepare():
                    self.close_connection = True
                    self._send_json(409, {"error": "FAULT_ATTEMPT_LIMIT"})
                    return
                declared = self.headers.get("Content-Length")
                try:
                    declared_bytes = int(declared) if declared is not None else None
                except ValueError:
                    declared_bytes = None
                if declared_bytes is None or declared_bytes < 0:
                    owner._set_outcome("CONTENT_LENGTH_REJECTED")
                    self.close_connection = True
                    self._send_json(411, {"error": "CONTENT_LENGTH_REQUIRED"})
                    return
                if declared_bytes > owner.max_body_bytes:
                    owner._set_outcome("REQUEST_TOO_LARGE")
                    self.close_connection = True
                    self._send_json(413, {"error": "REQUEST_TOO_LARGE"})
                    return
                self.connection.settimeout(2.0)
                try:
                    raw = self.rfile.read(declared_bytes)
                except (TimeoutError, OSError):
                    owner._set_outcome("REQUEST_READ_FAILED")
                    self.close_connection = True
                    return
                if len(raw) != declared_bytes:
                    owner._set_outcome("REQUEST_READ_INCOMPLETE")
                    self.close_connection = True
                    return
                del raw
                if owner.mode == "UNAVAILABLE":
                    owner._set_outcome("CANONICAL_UNAVAILABLE_SENT", injected=True)
                    self._send_json(503, _UNAVAILABLE_CONTEXT)
                    return
                if owner.mode == "MALFORMED":
                    owner._set_outcome("MALFORMED_CONTEXT_SENT", injected=True)
                    self._send(200, _MALFORMED_CONTEXT, "application/json")
                    return

                owner._set_outcome("TIMEOUT_DELAY_STARTED", injected=True)
                if owner._stop_event.wait(owner.delay_seconds):
                    owner._set_outcome("STOPPED_DURING_TIMEOUT_DELAY")
                    self.close_connection = True
                    return
                sent = self._send_json(504, {"error": "SYNTHETIC_RUNTIME_TIMEOUT"})
                owner._set_outcome(
                    "TIMEOUT_RESPONSE_SENT" if sent else "CLIENT_DISCONNECTED"
                )

        return Handler

    def start(self) -> Self:
        with self._lock:
            if self._active:
                raise RuntimeError("Runtime fault injector is already running")
            if self._server is not None:
                raise RuntimeError("Runtime fault injector instances are single-use")
            if self.artifact_path.exists() or self.artifact_path.is_symlink():
                raise FileExistsError(self.artifact_path)
            server = _OwnedThreadingHTTPServer(
                (self.host, self.requested_port), self._handler_type()
            )
            self._server = server
            self._port = int(server.server_address[1])
            self._active = True
            try:
                self._persist_locked()
                thread = threading.Thread(
                    target=server.serve_forever,
                    name=f"dg13u-runtime-fault-{self._port}",
                    daemon=False,
                )
                self._thread = thread
                thread.start()
            except Exception:
                self._active = False
                server.server_close()
                self._server = None
                raise
        return self

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._cleanup["attempted"] = True
            self._stop_event.set()
            server = self._server
            thread = self._thread
        assert server is not None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5.5)
            if thread.is_alive():
                raise RuntimeError("Runtime fault server thread did not stop")
        with self._lock:
            self._active = False
            self._cleanup = {
                "attempted": True,
                "listener_closed": True,
                "server_stopped": True,
                "worker_threads_stopped": True,
            }
            self._persist_locked()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--mode", choices=("UNAVAILABLE", "MALFORMED", "TIMEOUT"), required=True
    )
    parser.add_argument("--delay-seconds", type=float, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--max-body-bytes", type=int, default=1_048_576)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stopped = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stopped.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    try:
        with RuntimeFaultInjector(
            args.mode,
            artifact_path=args.artifact,
            run_id=args.run_id,
            delay_seconds=args.delay_seconds,
            host=args.host,
            port=args.port,
            max_body_bytes=args.max_body_bytes,
        ) as injector:
            print(
                _canonical_bytes(
                    {
                        "endpoint": injector.base_url,
                        "mode": injector.mode,
                        "pid": os.getpid(),
                        "schema": _SCHEMA,
                    }
                ).decode(),
                flush=True,
            )
            while not stopped.wait(0.2):
                pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
