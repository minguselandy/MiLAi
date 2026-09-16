#!/usr/bin/python3
"""Installed trusted profile-scoped Unix socket broker for a MiLAi MCP child."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SCHEMA = "milai.openworker.mcp-broker-policy.v1"
_PROFILES = frozenset({"reader-lite", "reader-detail", "submitter", "operator"})
_AUTHORITIES = frozenset({"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"})
_CONSISTENCIES = frozenset({"EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"})
_RESOLVE_BUDGET_PROFILES = frozenset(
    {
        "MCP_INTERACTIVE_STANDARD_V01",
        "MCP_INTERACTIVE_WIDE_V01",
        "MCP_RESEARCH_V01",
        "OPENWORKER_USABILITY_WIDE_V01",
        "OPENWORKER_USABILITY_WIDE_V02",
    }
)
_POLICY_FIELDS = frozenset(
    {
        "schema",
        "profile",
        "socket_path",
        "socket_mode",
        "allowed_peer_uids",
        "mcp_executable",
        "mcp_executable_sha256",
        "base_url",
        "scope",
        "required_authority",
        "consistency_floor",
        "max_limit",
        "max_connections",
        "child_shutdown_seconds",
    }
)
_OPTIONAL_POLICY_FIELDS = frozenset({"mcp_max_retries"})
_CHILD_ENV_KEYS = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONNOUSERSITE",
        "MILAI_BASE_URL",
        "MILAI_AGENT_TOKEN",
        "MILAI_AGENT_SCOPE_JSON",
        "MILAI_AGENT_REQUIRED_AUTHORITY",
        "MILAI_AGENT_CONSISTENCY_FLOOR",
        "MILAI_AGENT_MAX_LIMIT",
    }
)
_CHUNK_BYTES = 65_536


class BrokerError(RuntimeError):
    """A privacy-bounded broker failure."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_file(path: Path, *, secret: bool = False) -> os.stat_result:
    if not path.is_absolute():
        raise BrokerError("FILE_PATH_REJECTED")
    try:
        current = path.lstat()
    except OSError as exc:
        raise BrokerError("FILE_UNAVAILABLE") from exc
    if not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise BrokerError("FILE_TYPE_REJECTED")
    mode = stat.S_IMODE(current.st_mode)
    if mode & 0o022 or (secret and mode not in {0o400, 0o600}):
        raise BrokerError("FILE_MODE_REJECTED")
    if current.st_uid not in {0, os.geteuid()}:
        raise BrokerError("FILE_OWNER_REJECTED")
    return current


def _loopback_origin(value: Any) -> str:
    if not isinstance(value, str):
        raise BrokerError("BASE_URL_REJECTED")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.port is None
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BrokerError("BASE_URL_REJECTED")
    try:
        local = (
            parsed.hostname == "localhost"
            or ipaddress.ip_address(parsed.hostname).is_loopback
        )
    except ValueError:
        local = False
    if not local:
        raise BrokerError("BASE_URL_REJECTED")
    return value.rstrip("/")


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise BrokerError("POLICY_VALUE_REJECTED")
    return value


def _required_int(raw: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = raw.get(key)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise BrokerError("POLICY_VALUE_REJECTED")
    return value


@dataclass(frozen=True, slots=True)
class Policy:
    profile: str
    socket_path: Path
    socket_mode: int
    allowed_peer_uids: frozenset[int]
    mcp_executable: Path
    mcp_executable_sha256: str
    base_url: str
    scope_json: str
    required_authority: str
    consistency_floor: str
    max_limit: int
    max_connections: int
    child_shutdown_seconds: int
    mcp_max_retries: int | None
    digest: str

    @classmethod
    def load(cls, path: Path) -> Policy:
        _strict_file(path)
        encoded = path.read_bytes()
        try:
            raw = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrokerError("POLICY_JSON_REJECTED") from exc
        if (
            not isinstance(raw, dict)
            or not _POLICY_FIELDS <= set(raw)
            or set(raw) - _POLICY_FIELDS - _OPTIONAL_POLICY_FIELDS
        ):
            raise BrokerError("POLICY_FIELDS_REJECTED")
        if raw.get("schema") != _SCHEMA:
            raise BrokerError("POLICY_SCHEMA_REJECTED")
        profile = _required_string(raw, "profile")
        if profile not in _PROFILES:
            raise BrokerError("PROFILE_REJECTED")
        socket_path = Path(_required_string(raw, "socket_path"))
        if not socket_path.is_absolute() or socket_path.name != f"{profile}.sock":
            raise BrokerError("SOCKET_PATH_REJECTED")
        if raw.get("socket_mode") != "0600":
            raise BrokerError("SOCKET_MODE_REJECTED")
        peer_uids = raw.get("allowed_peer_uids")
        if (
            not isinstance(peer_uids, list)
            or not peer_uids
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in peer_uids
            )
        ):
            raise BrokerError("PEER_UIDS_REJECTED")
        mcp_executable = Path(_required_string(raw, "mcp_executable"))
        _strict_file(mcp_executable)
        if not os.access(mcp_executable, os.X_OK):
            raise BrokerError("MCP_EXECUTABLE_REJECTED")
        executable_sha256 = _required_string(raw, "mcp_executable_sha256")
        if len(executable_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in executable_sha256
        ):
            raise BrokerError("MCP_DIGEST_REJECTED")
        if _sha256(mcp_executable) != executable_sha256:
            raise BrokerError("MCP_DIGEST_MISMATCH")
        scope = raw.get("scope")
        if not isinstance(scope, dict):
            raise BrokerError("SCOPE_REJECTED")
        scope_json = json.dumps(
            scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        authority = _required_string(raw, "required_authority")
        consistency = _required_string(raw, "consistency_floor")
        if authority not in _AUTHORITIES or consistency not in _CONSISTENCIES:
            raise BrokerError("HOST_POLICY_REJECTED")
        if authority == "ACTION_SAFE" and not scope:
            raise BrokerError("ACTION_SAFE_SCOPE_REJECTED")
        if profile == "reader-lite" and (
            authority not in {"INFORMATIONAL", "ACTION_SAFE"}
            or consistency != "CANONICAL_REQUIRED"
        ):
            raise BrokerError("READER_LITE_POLICY_REJECTED")
        mcp_max_retries = raw.get("mcp_max_retries")
        if "mcp_max_retries" in raw and (
            not isinstance(mcp_max_retries, int)
            or isinstance(mcp_max_retries, bool)
            or mcp_max_retries != 0
        ):
            raise BrokerError("MCP_MAX_RETRIES_REJECTED")
        return cls(
            profile=profile,
            socket_path=socket_path,
            socket_mode=0o600,
            allowed_peer_uids=frozenset(peer_uids),
            mcp_executable=mcp_executable,
            mcp_executable_sha256=executable_sha256,
            base_url=_loopback_origin(raw.get("base_url")),
            scope_json=scope_json,
            required_authority=authority,
            consistency_floor=consistency,
            max_limit=_required_int(raw, "max_limit", 1, 50),
            max_connections=_required_int(raw, "max_connections", 1, 64),
            child_shutdown_seconds=_required_int(raw, "child_shutdown_seconds", 1, 30),
            mcp_max_retries=mcp_max_retries,
            digest=hashlib.sha256(encoded).hexdigest(),
        )

    def validate_executable(self) -> None:
        _strict_file(self.mcp_executable)
        if _sha256(self.mcp_executable) != self.mcp_executable_sha256:
            raise BrokerError("MCP_DIGEST_MISMATCH")

    def child_argv(self, resolve_budget_profile: str | None = None) -> list[str]:
        argv = [str(self.mcp_executable), "--profile", self.profile]
        if self.mcp_max_retries == 0:
            argv.extend(("--max-retries", "0"))
        if resolve_budget_profile is not None:
            if (
                self.profile != "reader-lite"
                or resolve_budget_profile not in _RESOLVE_BUDGET_PROFILES
            ):
                raise BrokerError("RESOLVE_BUDGET_PROFILE_REJECTED")
            argv.extend(("--resolve-budget-profile", resolve_budget_profile))
        return argv

    def child_environment(self, token: str) -> dict[str, str]:
        result = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "MILAI_BASE_URL": self.base_url,
            "MILAI_AGENT_TOKEN": token,
            "MILAI_AGENT_SCOPE_JSON": self.scope_json,
            "MILAI_AGENT_REQUIRED_AUTHORITY": self.required_authority,
            "MILAI_AGENT_CONSISTENCY_FLOOR": self.consistency_floor,
            "MILAI_AGENT_MAX_LIMIT": str(self.max_limit),
        }
        if set(result) != _CHILD_ENV_KEYS:  # pragma: no cover - source invariant
            raise BrokerError("CHILD_ENV_INVARIANT_FAILED")
        return result


def _read_token(path: Path) -> str:
    _strict_file(path, secret=True)
    raw = path.read_bytes()
    if len(raw) > 4097 or b"\0" in raw:
        raise BrokerError("TOKEN_FILE_REJECTED")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if b"\n" in raw or b"\r" in raw:
        raise BrokerError("TOKEN_FILE_REJECTED")
    try:
        token = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BrokerError("TOKEN_FILE_REJECTED") from exc
    if not 32 <= len(token) <= 4096:
        raise BrokerError("TOKEN_FILE_REJECTED")
    return token


def _secure_parent(path: Path) -> None:
    parent = path.parent
    try:
        current = parent.lstat()
    except OSError as exc:
        raise BrokerError("SOCKET_DIRECTORY_UNAVAILABLE") from exc
    if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise BrokerError("SOCKET_DIRECTORY_REJECTED")
    if current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) & 0o022:
        raise BrokerError("SOCKET_DIRECTORY_MODE_REJECTED")
    if path.exists() or path.is_symlink():
        raise BrokerError("SOCKET_ALREADY_EXISTS")


def _socket_identity(path: Path, expected_mode: int) -> tuple[int, int, int, int, int]:
    try:
        current = path.lstat()
    except OSError as exc:
        raise BrokerError("SOCKET_PATH_DRIFT") from exc
    identity = (
        current.st_dev,
        current.st_ino,
        current.st_uid,
        current.st_gid,
        stat.S_IMODE(current.st_mode),
    )
    if (
        not stat.S_ISSOCK(current.st_mode)
        or identity[2] != os.geteuid()
        or identity[4] != expected_mode
    ):
        raise BrokerError("SOCKET_PATH_DRIFT")
    return identity


def _peer_uid(connection: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise BrokerError("PEER_CREDENTIALS_UNAVAILABLE")
    raw = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
    )
    _, uid, _ = struct.unpack("3i", raw)
    return int(uid)


def _copy_socket_to_pipe(connection: socket.socket, pipe: Any) -> None:
    try:
        while True:
            block = connection.recv(_CHUNK_BYTES)
            if not block:
                break
            pipe.write(block)
            pipe.flush()
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _terminate_child(child: subprocess.Popen[bytes], timeout: int) -> None:
    if child.poll() is not None:
        child.wait()
        return
    child.terminate()
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=timeout)


def _log(
    event: str, *, connection_id: int | None = None, policy_digest: str | None = None
) -> None:
    value: dict[str, Any] = {"component": "milai-mcp-broker", "event": event}
    if connection_id is not None:
        value["connection_id"] = connection_id
    if policy_digest is not None:
        value["policy_sha256"] = policy_digest
    sys.stderr.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stderr.flush()


class Broker:
    def __init__(
        self,
        policy: Policy,
        token: str,
        resolve_budget_profile: str | None = None,
    ) -> None:
        self.policy = policy
        self._token = token
        # Validate the host-selected profile before the socket becomes ready.
        policy.child_argv(resolve_budget_profile)
        self._resolve_budget_profile = resolve_budget_profile
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._identity: tuple[int, int, int, int, int] | None = None
        self._sessions: set[threading.Thread] = set()
        self._sessions_lock = threading.Lock()
        self._resources_lock = threading.Lock()
        self._connections: set[socket.socket] = set()
        self._children: set[subprocess.Popen[bytes]] = set()
        self._semaphore = threading.BoundedSemaphore(policy.max_connections)
        self._sequence = 0

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        with self._resources_lock:
            connections = list(self._connections)
            children = list(self._children)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for child in children:
            if child.poll() is None:
                try:
                    child.terminate()
                except OSError:
                    pass

    def _serve_connection(self, connection: socket.socket, connection_id: int) -> None:
        child: subprocess.Popen[bytes] | None = None
        try:
            if self._stop.is_set():
                return
            if _peer_uid(connection) not in self.policy.allowed_peer_uids:
                _log("PEER_REJECTED", connection_id=connection_id)
                return
            self.policy.validate_executable()
            child = subprocess.Popen(  # noqa: S603 - executable is digest-bound by policy
                self.policy.child_argv(self._resolve_budget_profile),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self.policy.child_environment(self._token),
                close_fds=True,
                start_new_session=True,
            )
            with self._resources_lock:
                self._children.add(child)
                stopped = self._stop.is_set()
            if stopped:
                _terminate_child(child, self.policy.child_shutdown_seconds)
                return
            if (
                child.stdin is None or child.stdout is None
            ):  # pragma: no cover - Popen invariant
                raise BrokerError("CHILD_PIPE_FAILED")
            inbound = threading.Thread(
                target=_copy_socket_to_pipe,
                args=(connection, child.stdin),
                name=f"milai-broker-in-{connection_id}",
                daemon=True,
            )
            inbound.start()
            while True:
                block = os.read(child.stdout.fileno(), _CHUNK_BYTES)
                if not block:
                    break
                connection.sendall(block)
            try:
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            inbound.join(timeout=1.0)
            _terminate_child(child, self.policy.child_shutdown_seconds)
            _log("SESSION_CLOSED", connection_id=connection_id)
        except (BrokerError, OSError, subprocess.SubprocessError):
            _log("SESSION_FAILED", connection_id=connection_id)
        finally:
            if child is not None:
                try:
                    _terminate_child(child, self.policy.child_shutdown_seconds)
                except (OSError, subprocess.SubprocessError):
                    _log("CHILD_STOP_FAILED", connection_id=connection_id)
                with self._resources_lock:
                    self._children.discard(child)
            connection.close()
            with self._resources_lock:
                self._connections.discard(connection)
            self._semaphore.release()
            with self._sessions_lock:
                self._sessions.discard(threading.current_thread())

    def run(self) -> None:
        _secure_parent(self.policy.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener = listener
        old_umask = os.umask(0o177)
        try:
            listener.bind(str(self.policy.socket_path))
        finally:
            os.umask(old_umask)
        os.chmod(self.policy.socket_path, self.policy.socket_mode)
        self._identity = _socket_identity(
            self.policy.socket_path, self.policy.socket_mode
        )
        listener.listen(self.policy.max_connections)
        listener.settimeout(0.25)
        _log("READY", policy_digest=self.policy.digest)
        try:
            while not self._stop.is_set():
                if (
                    _socket_identity(self.policy.socket_path, self.policy.socket_mode)
                    != self._identity
                ):
                    raise BrokerError("SOCKET_PATH_DRIFT")
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                if (
                    _socket_identity(self.policy.socket_path, self.policy.socket_mode)
                    != self._identity
                ):
                    connection.close()
                    raise BrokerError("SOCKET_PATH_DRIFT")
                if not self._semaphore.acquire(blocking=False):
                    connection.close()
                    _log("OVERLOAD_REJECTED")
                    continue
                with self._resources_lock:
                    self._connections.add(connection)
                self._sequence += 1
                connection_id = self._sequence
                session = threading.Thread(
                    target=self._serve_connection,
                    args=(connection, connection_id),
                    name=f"milai-broker-session-{connection_id}",
                    daemon=True,
                )
                with self._sessions_lock:
                    self._sessions.add(session)
                session.start()
        finally:
            self.stop()
            with self._sessions_lock:
                sessions = list(self._sessions)
            for session in sessions:
                session.join(timeout=self.policy.child_shutdown_seconds + 1)
            if any(session.is_alive() for session in sessions):
                raise BrokerError("SESSION_STOP_TIMEOUT")
            try:
                if (
                    self._identity is not None
                    and _socket_identity(
                        self.policy.socket_path, self.policy.socket_mode
                    )
                    == self._identity
                ):
                    self.policy.socket_path.unlink()
            except BrokerError:
                pass
            _log("STOPPED", policy_digest=self.policy.digest)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MiLAi trusted profile-scoped MCP UDS broker"
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--resolve-budget-profile",
        choices=tuple(sorted(_RESOLVE_BUDGET_PROFILES)),
        default=None,
        help="host-owned fixed resolve budget profile; never exposed to the Worker",
    )
    args = parser.parse_args()
    try:
        policy = Policy.load(args.policy.resolve())
        token = _read_token(args.token_file.resolve())
        broker = Broker(policy, token, args.resolve_budget_profile)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: broker.stop())
        signal.signal(signal.SIGINT, lambda _signum, _frame: broker.stop())
        broker.run()
    except BrokerError as exc:
        _log(str(exc))
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
