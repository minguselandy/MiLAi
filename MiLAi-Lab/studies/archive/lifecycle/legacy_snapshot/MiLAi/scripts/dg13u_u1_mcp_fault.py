#!/usr/bin/env python3
"""Run-owned newline-delimited MCP-over-UDS fault endpoint for DG13U U1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import stat
import tempfile
import threading
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import FrameType
from typing import Any, Literal, Self

FaultMode = Literal["MALFORMED", "TIMEOUT"]
_LEDGER_SCHEMA = "milai.dg13u.u1-mcp-fault-ledger.v1"
_READY_SCHEMA = "milai.dg13u.u1-mcp-fault-ready.v1"
_MALFORMED_FRAME = b'{"jsonrpc":"2.0","id":\n'


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
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


def _identity(path: Path) -> tuple[int, int, int] | None:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return None
    return current.st_dev, current.st_ino, current.st_mode


def _identity_receipt(identity: tuple[int, int, int] | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    device, inode, mode = identity
    return {
        "device": device,
        "inode": inode,
        "is_socket": stat.S_ISSOCK(mode),
        "mode": f"{stat.S_IMODE(mode):04o}",
    }


def _frame_inventory(raw: bytes) -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "frame_bytes": len(raw) + 1,
        "frame_sha256": hashlib.sha256(raw + b"\n").hexdigest(),
        "json_kind": "invalid",
        "method": None,
        "params_keys": [],
        "request_id_sha256": None,
        "top_level_keys": [],
    }
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return inventory
    if not isinstance(value, dict):
        inventory["json_kind"] = type(value).__name__
        return inventory
    inventory["json_kind"] = "object"
    inventory["top_level_keys"] = sorted(key for key in value if isinstance(key, str))
    method = value.get("method")
    inventory["method"] = method if isinstance(method, str) else None
    params = value.get("params")
    if isinstance(params, dict):
        inventory["params_keys"] = sorted(key for key in params if isinstance(key, str))
    if "id" in value:
        inventory["request_id_sha256"] = hashlib.sha256(
            _canonical_bytes(value["id"])
        ).hexdigest()
    return inventory


def _secure_socket_parent(path: Path) -> None:
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    current = parent.lstat()
    if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise ValueError("socket parent must be a real directory")
    if stat.S_IMODE(current.st_mode) & 0o022:
        raise ValueError("socket parent must not be group/world writable")


class McpFaultEndpoint(AbstractContextManager["McpFaultEndpoint"]):
    """Single-connection UDS endpoint that terminates the real MCP client wire."""

    def __init__(
        self,
        mode: FaultMode,
        *,
        socket_path: str | Path,
        ledger_path: str | Path,
        timeout_delay_seconds: float = 1.0,
        frame_read_timeout_seconds: float = 5.0,
        max_frame_bytes: int = 65_536,
    ) -> None:
        if mode not in {"MALFORMED", "TIMEOUT"}:
            raise ValueError("mode must be MALFORMED or TIMEOUT")
        candidate = Path(socket_path)
        if not candidate.is_absolute():
            raise ValueError("socket_path must be absolute")
        ledger = Path(ledger_path)
        if candidate == ledger:
            raise ValueError("socket_path and ledger_path must differ")
        if not 0.01 <= timeout_delay_seconds <= 5.0:
            raise ValueError("timeout_delay_seconds must be in [0.01, 5.0]")
        if not 0.01 <= frame_read_timeout_seconds <= 5.0:
            raise ValueError("frame_read_timeout_seconds must be in [0.01, 5.0]")
        if (
            not isinstance(max_frame_bytes, int)
            or not 1_024 <= max_frame_bytes <= 2_097_152
        ):
            raise ValueError("max_frame_bytes must be in [1024, 2097152]")

        self.mode = mode
        self.socket_path = candidate
        self.ledger_path = ledger
        self.timeout_delay_seconds = float(timeout_delay_seconds)
        self.frame_read_timeout_seconds = float(frame_read_timeout_seconds)
        self.max_frame_bytes = max_frame_bytes
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._listener: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._socket_identity: tuple[int, int, int] | None = None
        self._events: list[dict[str, Any]] = []
        self._active = False
        self._cleanup: dict[str, Any] = {
            "attempted": False,
            "identity_match": None,
            "observed_identity": None,
            "owned_inode_removed": False,
            "path_absent": False,
        }

    @property
    def native_attempts(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def socket_identity(self) -> Mapping[str, Any]:
        with self._lock:
            receipt = _identity_receipt(self._socket_identity)
            if receipt is None:
                raise RuntimeError("MCP fault endpoint has not started")
            return receipt

    def _ledger(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "automatic_retries": 0,
            "cleanup": dict(self._cleanup),
            "connection_limit": 1,
            "connections_accepted": len(self._events),
            "events": list(self._events),
            "mode": self.mode,
            "native_attempts": len(self._events),
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
            "schema": _LEDGER_SCHEMA,
            "socket_identity": _identity_receipt(self._socket_identity),
            "socket_path_sha256": hashlib.sha256(
                os.fsencode(self.socket_path)
            ).hexdigest(),
            "wire": "newline-delimited-json-rpc-2.0",
        }

    def _persist_locked(self) -> None:
        _atomic_private_json(self.ledger_path, self._ledger())

    def _begin_attempt(self) -> int:
        with self._lock:
            attempt = len(self._events) + 1
            self._events.append(
                {
                    "native_attempt": attempt,
                    "outcome": "AWAITING_FRAME",
                    "request": {
                        "frame_sha256": None,
                        "json_kind": "unread",
                        "observed_bytes": 0,
                    },
                }
            )
            self._persist_locked()
            return attempt

    def _finish_attempt(
        self,
        attempt: int,
        outcome: str,
        request: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            event = self._events[attempt - 1]
            event["outcome"] = outcome
            if request is not None:
                event["request"] = dict(request)
            self._persist_locked()

    def _read_frame(
        self, connection: socket.socket, attempt: int
    ) -> tuple[bytes | None, str | None]:
        connection.settimeout(self.frame_read_timeout_seconds)
        buffer = bytearray()
        while not self._stop_event.is_set():
            try:
                block = connection.recv(min(4_096, self.max_frame_bytes + 1))
            except (TimeoutError, OSError):
                return None, "REQUEST_READ_TIMEOUT"
            if not block:
                return None, "CLIENT_CLOSED_BEFORE_FRAME"
            buffer.extend(block)
            if b"\n" in buffer:
                raw, _, _remainder = buffer.partition(b"\n")
                if len(raw) + 1 > self.max_frame_bytes:
                    self._finish_attempt(
                        attempt,
                        "REQUEST_FRAME_TOO_LARGE",
                        {
                            "frame_sha256": None,
                            "json_kind": "not_inspected",
                            "observed_bytes": len(buffer),
                        },
                    )
                    return None, None
                return bytes(raw), None
            if len(buffer) >= self.max_frame_bytes:
                self._finish_attempt(
                    attempt,
                    "REQUEST_FRAME_TOO_LARGE",
                    {
                        "frame_sha256": None,
                        "json_kind": "not_inspected",
                        "observed_bytes": len(buffer),
                    },
                )
                return None, None
        return None, "STOPPED_DURING_READ"

    def _serve_connection(self, connection: socket.socket, attempt: int) -> None:
        raw, read_error = self._read_frame(connection, attempt)
        if read_error is not None:
            self._finish_attempt(attempt, read_error)
            return
        if raw is None:
            return
        inventory = _frame_inventory(raw)
        if self.mode == "MALFORMED":
            try:
                connection.sendall(_MALFORMED_FRAME)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self._finish_attempt(attempt, "CLIENT_DISCONNECTED", inventory)
            else:
                self._finish_attempt(attempt, "MALFORMED_RESPONSE_SENT", inventory)
            return

        self._finish_attempt(attempt, "DELAYING", inventory)
        if self._stop_event.wait(self.timeout_delay_seconds):
            self._finish_attempt(attempt, "STOPPED_DURING_DELAY")
        else:
            self._finish_attempt(attempt, "TIMEOUT_ELAPSED")

    def _run(self) -> None:
        listener = self._listener
        assert listener is not None
        try:
            listener.settimeout(0.1)
        except OSError:
            if self._stop_event.is_set():
                return
            raise
        connection: socket.socket | None = None
        try:
            while not self._stop_event.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        return
                    raise
                break
            if connection is None:
                return
            with self._lock:
                self._connection = connection
                if self._listener is not None:
                    self._listener.close()
                    self._listener = None
            attempt = self._begin_attempt()
            self._serve_connection(connection, attempt)
        finally:
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            with self._lock:
                self._connection = None

    def start(self) -> Self:
        with self._lock:
            if self._active:
                raise RuntimeError("MCP fault endpoint is already running")
            if self._thread is not None:
                raise RuntimeError("MCP fault endpoint instances are single-use")
            if self.socket_path.exists() or self.socket_path.is_symlink():
                raise FileExistsError(self.socket_path)
            if self.ledger_path.exists() or self.ledger_path.is_symlink():
                raise FileExistsError(self.ledger_path)

            _secure_socket_parent(self.socket_path)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            bound_identity: tuple[int, int, int] | None = None
            try:
                old_umask = os.umask(0o177)
                try:
                    listener.bind(str(self.socket_path))
                finally:
                    os.umask(old_umask)
                bound_identity = _identity(self.socket_path)
                if bound_identity is None or not stat.S_ISSOCK(bound_identity[2]):
                    raise RuntimeError("MCP fault socket identity unavailable")
                os.chmod(self.socket_path, 0o600)
                listener.listen(1)
                identity = _identity(self.socket_path)
                if identity != bound_identity or stat.S_IMODE(identity[2]) != 0o600:
                    raise RuntimeError("MCP fault socket identity changed during start")
                self._socket_identity = identity
                self._listener = listener
                self._active = True
                self._persist_locked()
                thread = threading.Thread(
                    target=self._run,
                    name=f"dg13u-mcp-fault-{identity[1]}",
                    daemon=False,
                )
                self._thread = thread
                thread.start()
            except BaseException:
                self._active = False
                listener.close()
                self._listener = None
                if (
                    bound_identity is not None
                    and _identity(self.socket_path) == bound_identity
                ):
                    self.socket_path.unlink()
                raise
        return self

    def _cleanup_owned_socket_locked(self) -> None:
        observed = _identity(self.socket_path)
        identity_match = observed == self._socket_identity and observed is not None
        removed = False
        if identity_match:
            self.socket_path.unlink()
            removed = True
        self._cleanup = {
            "attempted": True,
            "identity_match": identity_match if observed is not None else None,
            "observed_identity": _identity_receipt(observed),
            "owned_inode_removed": removed,
            "path_absent": _identity(self.socket_path) is None,
        }

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._stop_event.set()
            listener = self._listener
            connection = self._connection
            thread = self._thread
            self._listener = None
        if listener is not None:
            listener.close()
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if thread is not None:
            thread.join(timeout=5.5)
            if thread.is_alive():
                raise RuntimeError("MCP fault endpoint thread did not stop")
        with self._lock:
            self._active = False
            self._cleanup_owned_socket_locked()
            self._persist_locked()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("MALFORMED", "TIMEOUT"))
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--timeout-delay-seconds", type=float, default=1.0)
    parser.add_argument("--frame-read-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-frame-bytes", type=int, default=65_536)
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
        with McpFaultEndpoint(
            args.mode,
            socket_path=args.socket,
            ledger_path=args.ledger,
            timeout_delay_seconds=args.timeout_delay_seconds,
            frame_read_timeout_seconds=args.frame_read_timeout_seconds,
            max_frame_bytes=args.max_frame_bytes,
        ) as endpoint:
            readiness = {
                "mode": endpoint.mode,
                "pid": os.getpid(),
                "schema": _READY_SCHEMA,
                "socket_identity": dict(endpoint.socket_identity),
                "socket_path": str(endpoint.socket_path),
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
