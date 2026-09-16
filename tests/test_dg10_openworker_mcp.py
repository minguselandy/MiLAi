from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import stat
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELAY_PATH = ROOT / "integrations/openworker-mcp/relay/milai_mcp_relay.py"
BROKER_PATH = ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/broker.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relay_module() -> ModuleType:
    return _load("milai_mcp_relay_test", RELAY_PATH)


@pytest.fixture
def broker_module() -> ModuleType:
    return _load("milai_mcp_broker_test", BROKER_PATH)


def _fake_mcp(path: Path) -> str:
    path.write_text(
        """#!/usr/bin/python3
import json
import os
import sys

safe = {
    "environment_keys": sorted(os.environ),
    "profile_args": sys.argv[1:],
    "token_length": len(os.environ.get("MILAI_AGENT_TOKEN", "")),
    "scope": json.loads(os.environ["MILAI_AGENT_SCOPE_JSON"]),
    "authority": os.environ["MILAI_AGENT_REQUIRED_AUTHORITY"],
    "consistency": os.environ["MILAI_AGENT_CONSISTENCY_FLOOR"],
    "limit": os.environ["MILAI_AGENT_MAX_LIMIT"],
}
sys.stdout.write(json.dumps(safe, sort_keys=True) + "\\n")
sys.stdout.flush()
while True:
    block = sys.stdin.buffer.read(3)
    if not block:
        break
    sys.stdout.buffer.write(block)
    sys.stdout.buffer.flush()
""",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy(
    tmp_path: Path,
    executable: Path,
    executable_digest: str,
    **updates: Any,
) -> Path:
    socket_directory = tmp_path / "reader-lite"
    socket_directory.mkdir(mode=0o700)
    raw: dict[str, Any] = {
        "allowed_peer_uids": [os.geteuid()],
        "base_url": "http://127.0.0.1:18080",
        "child_shutdown_seconds": 2,
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_connections": 2,
        "max_limit": 3,
        "mcp_executable": str(executable),
        "mcp_executable_sha256": executable_digest,
        "profile": "reader-lite",
        "required_authority": "ACTION_SAFE",
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "scope": {"project_ids": ["milai"]},
        "socket_mode": "0600",
        "socket_path": str(socket_directory / "reader-lite.sock"),
    }
    raw.update(updates)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
    policy_path.chmod(0o600)
    return policy_path


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _recv_line(connection: socket.socket) -> bytes:
    value = bytearray()
    while not value.endswith(b"\n"):
        block = connection.recv(1)
        if not block:
            break
        value.extend(block)
    return bytes(value)


def test_openworker_template_has_only_credential_free_reader_lite_relay() -> None:
    path = ROOT / "integrations/openworker-mcp/openworker/opencode.json"
    raw = path.read_text(encoding="utf-8")
    config = json.loads(raw)
    assert config["mcp"] == {
        "milai": {
            "type": "local",
            "command": [
                "/usr/local/bin/milai-mcp-relay",
                "/run/milai-mcp/reader-lite.sock",
            ],
            "enabled": True,
            "timeout": 10000,
        }
    }
    forbidden = (
        "MILAI_AGENT_TOKEN",
        "MILAI_AGENT_READER_TOKEN",
        "MILAI_BASE_URL",
        "DATABASE_URL",
        "POSTGRES",
        "Runtime .env",
    )
    assert all(value not in raw for value in forbidden)


def test_derived_image_is_local_id_pinned_and_adds_only_relay_and_template() -> None:
    dockerfile = (ROOT / "integrations/openworker-mcp/openworker/Dockerfile").read_text(
        encoding="utf-8"
    )
    assert (
        "sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
        in dockerfile
    )
    assert dockerfile.count("COPY ") == 2
    assert "milai_mcp_broker" not in dockerfile
    assert "curl " not in dockerfile and "wget " not in dockerfile
    build_script = (
        ROOT / "integrations/openworker-mcp/build_local_candidate.sh"
    ).read_text(encoding="utf-8")
    assert "--pull=false --network none" in build_script
    assert (
        "derived image does not preserve the locked base layer prefix" in build_script
    )


def test_relay_rejects_path_profile_symlink_and_wide_socket_mode(
    relay_module: ModuleType, tmp_path: Path
) -> None:
    relay_module._SOCKET_ROOT = PurePosixPath(str(tmp_path))
    tmp_path.chmod(0o755)
    with pytest.raises(relay_module.RelayError, match="SOCKET_PATH_REJECTED"):
        relay_module._validate_path(str(tmp_path.parent / "reader-lite.sock"))
    with pytest.raises(relay_module.RelayError, match="SOCKET_PROFILE_REJECTED"):
        relay_module._validate_path(str(tmp_path / "operator-copy.sock"))

    target = tmp_path / "target"
    target.write_text("not a socket", encoding="utf-8")
    link = tmp_path / "reader-lite.sock"
    link.symlink_to(target)
    with pytest.raises(relay_module.RelayError, match="SOCKET_TYPE_REJECTED"):
        relay_module._socket_identity(str(link))
    link.unlink()

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(link))
    link.chmod(0o666)
    try:
        with pytest.raises(relay_module.RelayError, match="SOCKET_MODE_REJECTED"):
            relay_module._socket_identity(str(link))
    finally:
        listener.close()


def test_policy_rejects_unknown_fields_remote_runtime_and_weak_reader_policy(
    broker_module: ModuleType, tmp_path: Path
) -> None:
    executable = tmp_path / "fake-mcp"
    digest = _fake_mcp(executable)
    policy_path = _policy(tmp_path, executable, digest)
    policy = broker_module.Policy.load(policy_path)
    assert policy.profile == "reader-lite"
    assert policy.scope_json == '{"project_ids":["milai"]}'
    assert policy.mcp_max_retries is None
    assert policy.child_argv() == [str(executable), "--profile", "reader-lite"]

    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    cases = (
        {**raw, "unexpected": True},
        {**raw, "base_url": "http://172.17.0.1:18080"},
        {**raw, "scope": {}},
        {**raw, "required_authority": "USER_CONFIRMED"},
        {**raw, "consistency_floor": "EVENTUAL"},
        {**raw, "socket_path": str(tmp_path / "reader-lite/operator.sock")},
        {**raw, "mcp_max_retries": 1},
        {**raw, "mcp_max_retries": -1},
        {**raw, "mcp_max_retries": True},
        {**raw, "mcp_max_retries": "0"},
        {**raw, "mcp_max_retries": None},
    )
    for index, candidate in enumerate(cases):
        candidate_path = tmp_path / f"invalid-{index}.json"
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        candidate_path.chmod(0o600)
        with pytest.raises(broker_module.BrokerError):
            broker_module.Policy.load(candidate_path)

    informational_path = tmp_path / "informational.json"
    informational_path.write_text(
        json.dumps({**raw, "required_authority": "INFORMATIONAL"}),
        encoding="utf-8",
    )
    informational_path.chmod(0o600)
    assert broker_module.Policy.load(informational_path).required_authority == (
        "INFORMATIONAL"
    )

    zero_retry_path = tmp_path / "zero-retry.json"
    zero_retry_path.write_text(
        json.dumps({**raw, "mcp_max_retries": 0}),
        encoding="utf-8",
    )
    zero_retry_path.chmod(0o600)
    zero_retry = broker_module.Policy.load(zero_retry_path)
    assert zero_retry.mcp_max_retries == 0
    assert zero_retry.child_argv() == [
        str(executable),
        "--profile",
        "reader-lite",
        "--max-retries",
        "0",
    ]


def test_broker_forwards_fragmented_stream_with_exact_child_policy_and_no_inherited_env(
    broker_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MILAI_PROVIDER_CREDENTIAL_TEST", "must-not-propagate")
    monkeypatch.setenv("DATABASE_URL", "must-not-propagate")
    monkeypatch.setenv("HTTP_PROXY", "must-not-propagate")
    executable = tmp_path / "fake-mcp"
    digest = _fake_mcp(executable)
    policy = broker_module.Policy.load(
        _policy(tmp_path, executable, digest, mcp_max_retries=0)
    )
    token_path = tmp_path / "reader.token"
    token_path.write_text("synthetic-token-value-that-is-long-enough", encoding="utf-8")
    token_path.chmod(0o600)
    token = broker_module._read_token(token_path)
    broker = broker_module.Broker(policy, token)
    failures: list[BaseException] = []

    def run() -> None:
        try:
            broker.run()
        except broker_module.BrokerError as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    _wait_for(policy.socket_path)

    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(str(policy.socket_path))
    announced = json.loads(_recv_line(connection))
    assert announced == {
        "authority": "ACTION_SAFE",
        "consistency": "CANONICAL_REQUIRED",
        "environment_keys": sorted(broker_module._CHILD_ENV_KEYS),
        "limit": "3",
        "profile_args": [
            "--profile",
            "reader-lite",
            "--max-retries",
            "0",
        ],
        "scope": {"project_ids": ["milai"]},
        "token_length": len(token),
    }
    payload = (
        b'{"jsonrpc":"2.0","fragmented":true,'
        b'"params":{"mcp_max_retries":99}}\n'
    )
    for byte in payload:
        connection.send(bytes([byte]))
    connection.shutdown(socket.SHUT_WR)
    echoed = bytearray()
    while True:
        block = connection.recv(7)
        if not block:
            break
        echoed.extend(block)
    connection.close()
    assert bytes(echoed) == payload

    broker.stop()
    thread.join(timeout=5)
    assert failures == []
    assert not thread.is_alive()
    assert not policy.socket_path.exists()


def test_executable_drift_and_socket_replacement_fail_closed(
    broker_module: ModuleType, tmp_path: Path
) -> None:
    executable = tmp_path / "fake-mcp"
    digest = _fake_mcp(executable)
    policy = broker_module.Policy.load(_policy(tmp_path, executable, digest))
    executable.write_text(
        executable.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8"
    )
    executable.chmod(0o700)
    with pytest.raises(broker_module.BrokerError, match="MCP_DIGEST_MISMATCH"):
        policy.validate_executable()

    digest = _fake_mcp(executable)
    policy_path = tmp_path / "policy.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    raw["mcp_executable_sha256"] = digest
    policy_path.write_text(json.dumps(raw), encoding="utf-8")
    policy_path.chmod(0o600)
    policy = broker_module.Policy.load(policy_path)
    broker = broker_module.Broker(policy, "synthetic-token-value-that-is-long-enough")
    failures: list[BaseException] = []

    def run() -> None:
        try:
            broker.run()
        except broker_module.BrokerError as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    _wait_for(policy.socket_path)
    original = policy.socket_path.with_suffix(".original")
    policy.socket_path.rename(original)
    attacker = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    attacker.bind(str(policy.socket_path))
    policy.socket_path.chmod(0o600)
    thread.join(timeout=3)
    attacker.close()
    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], broker_module.BrokerError)
    assert str(failures[0]) == "SOCKET_PATH_DRIFT"
    assert policy.socket_path.exists()
    assert stat.S_ISSOCK(policy.socket_path.lstat().st_mode)
    policy.socket_path.unlink()
    original.unlink()


def test_broker_stop_closes_active_connection_and_child(
    broker_module: ModuleType, tmp_path: Path
) -> None:
    executable = tmp_path / "fake-mcp"
    digest = _fake_mcp(executable)
    policy = broker_module.Policy.load(_policy(tmp_path, executable, digest))
    broker = broker_module.Broker(
        policy, "synthetic-token-value-that-is-long-enough"
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            broker.run()
        except broker_module.BrokerError as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    _wait_for(policy.socket_path)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(3)
    connection.connect(str(policy.socket_path))
    assert json.loads(_recv_line(connection))["profile_args"] == [
        "--profile",
        "reader-lite",
    ]

    broker.stop()
    assert connection.recv(1) == b""
    connection.close()
    thread.join(timeout=5)
    assert failures == []
    assert not thread.is_alive()
    assert broker._connections == set()
    assert broker._children == set()


def test_token_source_requires_private_regular_single_line_file(
    broker_module: ModuleType, tmp_path: Path
) -> None:
    token = tmp_path / "token"
    token.write_text("synthetic-token-value-that-is-long-enough", encoding="utf-8")
    token.chmod(0o644)
    with pytest.raises(broker_module.BrokerError, match="FILE_MODE_REJECTED"):
        broker_module._read_token(token)
    token.chmod(0o600)
    token.write_text(
        "synthetic-token-value-that-is-long-enough\nsecond", encoding="utf-8"
    )
    with pytest.raises(broker_module.BrokerError, match="TOKEN_FILE_REJECTED"):
        broker_module._read_token(token)
