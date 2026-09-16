#!/usr/bin/env python3
"""Run-owned loopback OpenAI-compatible provider fault injector for DG13U U1."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import signal
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import FrameType
from typing import Any, Literal, Self

FaultMode = Literal["MALFORMED", "TIMEOUT"]
_COMPLETIONS_PATH = "/v1/chat/completions"
_HEALTH_PATH = "/health"
_LEDGER_SCHEMA = "milai.dg13u.u1-provider-fault-ledger.v1"
_READY_SCHEMA = "milai.dg13u.u1-provider-fault-ready.v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    """Replace one JSON artifact atomically while preserving owner-only mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _request_inventory(
    raw: bytes | None,
    *,
    declared_bytes: int | None,
    authorization_present: bool,
    status: str,
) -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "authorization_present": authorization_present,
        "body_bytes": len(raw) if raw is not None else declared_bytes,
        "body_sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "json_kind": status,
        "message_count": None,
        "message_roles": [],
        "top_level_keys": [],
    }
    if raw is None:
        return inventory
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        inventory["json_kind"] = "invalid"
        return inventory
    if not isinstance(value, dict):
        inventory["json_kind"] = type(value).__name__
        return inventory
    inventory["json_kind"] = "object"
    inventory["top_level_keys"] = sorted(key for key in value if isinstance(key, str))
    messages = value.get("messages")
    if isinstance(messages, list):
        inventory["message_count"] = len(messages)
        inventory["message_roles"] = [
            item["role"]
            for item in messages
            if isinstance(item, dict) and isinstance(item.get("role"), str)
        ]
    return inventory


class _OwnedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True


class ProviderFaultInjector(AbstractContextManager["ProviderFaultInjector"]):
    """One loopback fault endpoint with an atomic, content-redacted attempt ledger."""

    def __init__(
        self,
        mode: FaultMode,
        *,
        ledger_path: str | Path,
        host: str = "127.0.0.1",
        port: int = 0,
        timeout_delay_seconds: float = 1.0,
        max_body_bytes: int = 1_048_576,
    ) -> None:
        if mode not in {"MALFORMED", "TIMEOUT"}:
            raise ValueError("mode must be MALFORMED or TIMEOUT")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("host must be loopback IPv4") from None
        if address.version != 4 or not address.is_loopback:
            raise ValueError("host must be loopback IPv4")
        if not isinstance(port, int) or not 0 <= port <= 65_535:
            raise ValueError("port must be in [0, 65535]")
        if not 0.01 <= timeout_delay_seconds <= 5.0:
            raise ValueError("timeout_delay_seconds must be in [0.01, 5.0]")
        if not isinstance(max_body_bytes, int) or not 1 <= max_body_bytes <= 8_388_608:
            raise ValueError("max_body_bytes must be in [1, 8388608]")

        self.mode = mode
        self.ledger_path = Path(ledger_path)
        self.host = str(address)
        self._requested_port = port
        self.timeout_delay_seconds = float(timeout_delay_seconds)
        self.max_body_bytes = max_body_bytes
        self._port: int | None = None
        self._server: _OwnedThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._active = False

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("provider fault injector has not started")
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def endpoint(self) -> str:
        return self.base_url + _COMPLETIONS_PATH

    @property
    def health_url(self) -> str:
        return self.base_url + _HEALTH_PATH

    @property
    def native_attempts(self) -> int:
        with self._lock:
            return len(self._events)

    def _ledger(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "automatic_retries": 0,
            "endpoint_path": _COMPLETIONS_PATH,
            "events": list(self._events),
            "mode": self.mode,
            "native_attempts": len(self._events),
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
            "schema": _LEDGER_SCHEMA,
        }

    def _persist_locked(self) -> None:
        _atomic_private_json(self.ledger_path, self._ledger())

    def _begin_attempt(self, request: Mapping[str, Any], outcome: str) -> int:
        with self._lock:
            attempt = len(self._events) + 1
            self._events.append(
                {
                    "native_attempt": attempt,
                    "outcome": outcome,
                    "request": dict(request),
                }
            )
            self._persist_locked()
            return attempt

    def _finish_attempt(self, attempt: int, outcome: str) -> None:
        with self._lock:
            event = self._events[attempt - 1]
            event["outcome"] = outcome
            self._persist_locked()

    def _finish_attempt_with_request(
        self, attempt: int, request: Mapping[str, Any], outcome: str
    ) -> None:
        with self._lock:
            event = self._events[attempt - 1]
            event["outcome"] = outcome
            event["request"] = dict(request)
            self._persist_locked()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _send_bytes(self, raw: bytes, status: int, content_type: str) -> bool:
                try:
                    self.send_response(status)
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

            def _send_json(self, value: Mapping[str, Any], status: int) -> bool:
                return self._send_bytes(
                    _canonical_bytes(value), status, "application/json"
                )

            def do_GET(self) -> None:
                if self.path != _HEALTH_PATH:
                    self._send_json({"error": "NOT_FOUND"}, 404)
                    return
                self._send_json(
                    {
                        "mode": owner.mode,
                        "native_attempts": owner.native_attempts,
                        "status": "ok",
                    },
                    200,
                )

            def do_POST(self) -> None:
                if self.path != _COMPLETIONS_PATH:
                    self._send_json({"error": "NOT_FOUND"}, 404)
                    return

                authorization_present = self.headers.get("Authorization") is not None
                declared_header = self.headers.get("Content-Length")
                try:
                    declared_bytes = (
                        int(declared_header) if declared_header is not None else None
                    )
                except ValueError:
                    declared_bytes = None
                if declared_bytes is None or declared_bytes < 0:
                    inventory = _request_inventory(
                        None,
                        declared_bytes=declared_bytes,
                        authorization_present=authorization_present,
                        status="length_invalid",
                    )
                    owner._begin_attempt(inventory, "CONTENT_LENGTH_REQUIRED")
                    self.close_connection = True
                    self._send_json({"error": "CONTENT_LENGTH_REQUIRED"}, 411)
                    return
                if declared_bytes > owner.max_body_bytes:
                    inventory = _request_inventory(
                        None,
                        declared_bytes=declared_bytes,
                        authorization_present=authorization_present,
                        status="too_large",
                    )
                    owner._begin_attempt(inventory, "BODY_TOO_LARGE")
                    self.close_connection = True
                    self._send_json({"error": "BODY_TOO_LARGE"}, 413)
                    return

                pending_inventory = _request_inventory(
                    None,
                    declared_bytes=declared_bytes,
                    authorization_present=authorization_present,
                    status="reading",
                )
                attempt = owner._begin_attempt(pending_inventory, "READING_BODY")
                self.connection.settimeout(5.0)
                try:
                    raw = self.rfile.read(declared_bytes)
                except (TimeoutError, OSError):
                    owner._finish_attempt(attempt, "BODY_READ_FAILED")
                    self.close_connection = True
                    return
                inventory = _request_inventory(
                    raw,
                    declared_bytes=declared_bytes,
                    authorization_present=authorization_present,
                    status="unparsed",
                )
                if len(raw) != declared_bytes:
                    owner._finish_attempt_with_request(
                        attempt, inventory, "BODY_READ_INCOMPLETE"
                    )
                    self.close_connection = True
                    self._send_json({"error": "BODY_READ_INCOMPLETE"}, 400)
                    return
                if owner.mode == "MALFORMED":
                    owner._finish_attempt_with_request(
                        attempt, inventory, "MALFORMED_RESPONSE"
                    )
                    sent = self._send_bytes(
                        b"data: {invalid-json\n\n",
                        200,
                        "text/event-stream",
                    )
                    if not sent:
                        owner._finish_attempt(attempt, "CLIENT_DISCONNECTED")
                    return

                owner._finish_attempt_with_request(attempt, inventory, "DELAYING")
                time.sleep(owner.timeout_delay_seconds)
                sent = self._send_json({"error": "SYNTHETIC_TIMEOUT"}, 504)
                owner._finish_attempt(
                    attempt,
                    "TIMEOUT_RESPONSE_SENT" if sent else "CLIENT_DISCONNECTED",
                )

        return Handler

    def start(self) -> Self:
        with self._lock:
            if self._active:
                raise RuntimeError("provider fault injector is already running")
            if self._server is not None:
                raise RuntimeError("provider fault injector instances are single-use")
            if self.ledger_path.exists():
                raise FileExistsError(self.ledger_path)

            server = _OwnedThreadingHTTPServer(
                (self.host, self._requested_port), self._handler_type()
            )
            self._server = server
            self._port = int(server.server_address[1])
            self._active = True
            try:
                self._persist_locked()
                thread = threading.Thread(
                    target=server.serve_forever,
                    name=f"dg13u-provider-fault-{self._port}",
                    daemon=False,
                )
                self._thread = thread
                thread.start()
            except BaseException:
                self._active = False
                server.server_close()
                self._persist_locked()
                raise
        return self

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            server = self._server
            thread = self._thread
        assert server is not None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5.5)
            if thread.is_alive():
                raise RuntimeError("provider fault server thread did not stop")
        with self._lock:
            self._active = False
            self._persist_locked()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("MALFORMED", "TIMEOUT"))
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-body-bytes", type=int, default=1_048_576)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ready_file: Path | None = args.ready_file
    if ready_file is not None and ready_file.exists():
        raise FileExistsError(ready_file)

    stopped = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stopped.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    try:
        with ProviderFaultInjector(
            args.mode,
            ledger_path=args.ledger,
            host=args.host,
            port=args.port,
            timeout_delay_seconds=args.timeout_delay_seconds,
            max_body_bytes=args.max_body_bytes,
        ) as injector:
            readiness = {
                "endpoint": injector.endpoint,
                "health_url": injector.health_url,
                "mode": injector.mode,
                "pid": os.getpid(),
                "schema": _READY_SCHEMA,
            }
            if ready_file is not None:
                _atomic_private_json(ready_file, readiness)
            print(_canonical_bytes(readiness).decode("utf-8"), flush=True)
            while not stopped.wait(0.2):
                pass
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
