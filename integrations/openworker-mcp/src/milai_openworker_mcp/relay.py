#!/usr/bin/python3
"""Credential-free stdio relay to one profile-scoped MiLAi MCP socket."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
from pathlib import PurePosixPath

_SOCKET_ROOT = PurePosixPath("/run/milai-mcp")
_ALLOWED_SOCKET_NAMES = frozenset(
    {"reader-lite.sock", "reader-detail.sock", "submitter.sock", "operator.sock"}
)
_CHUNK_BYTES = 65_536


class RelayError(RuntimeError):
    """A privacy-bounded relay failure."""


def _socket_identity(path: str) -> tuple[int, int, int, int, int]:
    try:
        current = os.lstat(path)
    except OSError as exc:
        raise RelayError("SOCKET_UNAVAILABLE") from exc
    if not stat.S_ISSOCK(current.st_mode):
        raise RelayError("SOCKET_TYPE_REJECTED")
    mode = stat.S_IMODE(current.st_mode)
    if mode != 0o600:
        raise RelayError("SOCKET_MODE_REJECTED")
    return (current.st_dev, current.st_ino, current.st_uid, current.st_gid, mode)


def _validate_path(path: str) -> None:
    candidate = PurePosixPath(path)
    if not candidate.is_absolute() or candidate.parent != _SOCKET_ROOT:
        raise RelayError("SOCKET_PATH_REJECTED")
    if candidate.name not in _ALLOWED_SOCKET_NAMES:
        raise RelayError("SOCKET_PROFILE_REJECTED")
    try:
        parent = os.lstat(str(_SOCKET_ROOT))
    except OSError as exc:
        raise RelayError("SOCKET_ROOT_UNAVAILABLE") from exc
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise RelayError("SOCKET_ROOT_REJECTED")
    if stat.S_IMODE(parent.st_mode) & 0o022:
        raise RelayError("SOCKET_ROOT_MODE_REJECTED")


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RelayError("STDOUT_CLOSED")
        view = view[written:]


def relay(path: str) -> None:
    _validate_path(path)
    before = _socket_identity(path)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(path)
        if _socket_identity(path) != before:
            raise RelayError("SOCKET_IDENTITY_CHANGED")

        writer_failed = threading.Event()

        def stdin_to_socket() -> None:
            try:
                while True:
                    block = os.read(sys.stdin.fileno(), _CHUNK_BYTES)
                    if not block:
                        connection.shutdown(socket.SHUT_WR)
                        return
                    connection.sendall(block)
            except (BrokenPipeError, ConnectionError, OSError):
                writer_failed.set()
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        writer = threading.Thread(target=stdin_to_socket, name="milai-relay-stdin", daemon=True)
        writer.start()
        while True:
            block = connection.recv(_CHUNK_BYTES)
            if not block:
                break
            _write_all(sys.stdout.fileno(), block)
        writer.join(timeout=1.0)
        if writer_failed.is_set():
            raise RelayError("STREAM_FORWARD_FAILED")
    except RelayError:
        raise
    except (ConnectionError, OSError) as exc:
        raise RelayError("SOCKET_CONNECT_FAILED") from exc
    finally:
        connection.close()


def _diagnostic(reason: str) -> None:
    value = {
        "component": "milai-mcp-relay",
        "status": "FAIL",
        "reason": reason,
    }
    sys.stderr.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    if len(sys.argv) != 2:
        _diagnostic("ARGUMENTS_REJECTED")
        return 64
    try:
        relay(sys.argv[1])
    except RelayError as exc:
        _diagnostic(str(exc))
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
