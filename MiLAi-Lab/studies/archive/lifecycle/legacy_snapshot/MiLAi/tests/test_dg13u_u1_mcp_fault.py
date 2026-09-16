from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from scripts.dg13u_u1_mcp_fault import McpFaultEndpoint

PRIVATE_PROMPT = "private MCP prompt that must never enter evidence"
PRIVATE_TOKEN = "private MCP token that must never enter evidence"


def _transport_module() -> ModuleType:
    source = (
        Path(__file__).parents[1]
        / "integrations/openworker-mcp/src/milai_openworker_mcp/transport.py"
    )
    spec = importlib.util.spec_from_file_location("dg13u_test_transport", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_terminal(ledger_path: Path) -> dict[str, object]:
    deadline = time.monotonic() + 2
    while True:
        ledger = _ledger(ledger_path)
        events = ledger["events"]
        if events and events[0]["outcome"] not in {"AWAITING_FRAME", "DELAYING"}:
            return ledger
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_malformed_endpoint_drives_actual_client_json_terminal(tmp_path: Path) -> None:
    transport = _transport_module()
    socket_path = tmp_path / "malformed.sock"
    ledger_path = tmp_path / "malformed-ledger.json"

    with McpFaultEndpoint(
        "MALFORMED", socket_path=socket_path, ledger_path=ledger_path
    ) as endpoint:
        client = transport.McpUnixClient(socket_path, request_timeout_seconds=1)
        with pytest.raises(
            transport.McpUnixClientError, match="MCP_RESPONSE_JSON_REJECTED"
        ):
            client.list_tools()
        client.close()
        ledger = _wait_terminal(ledger_path)

        assert endpoint.native_attempts == 1
        assert stat.S_ISSOCK(socket_path.lstat().st_mode)
        assert stat.S_IMODE(socket_path.lstat().st_mode) == 0o600
        assert ledger["events"][0]["request"]["method"] == "initialize"
        assert ledger["events"][0]["outcome"] == "MALFORMED_RESPONSE_SENT"
        with (
            socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as second,
            pytest.raises(OSError),
        ):
            second.connect(str(socket_path))
        assert endpoint.native_attempts == 1

    ledger = _ledger(ledger_path)
    assert ledger["active"] is False
    assert ledger["connections_accepted"] == 1
    assert ledger["native_attempts"] == 1
    assert ledger["automatic_retries"] == 0
    assert ledger["cleanup"]["owned_inode_removed"] is True
    assert ledger["cleanup"]["path_absent"] is True
    assert not socket_path.exists()
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600


def test_timeout_endpoint_drives_actual_prepare_context_deadline(
    tmp_path: Path,
) -> None:
    transport = _transport_module()
    socket_path = tmp_path / "timeout.sock"
    ledger_path = tmp_path / "timeout-ledger.json"

    with McpFaultEndpoint(
        "TIMEOUT",
        socket_path=socket_path,
        ledger_path=ledger_path,
        timeout_delay_seconds=0.15,
    ):
        client = transport.McpUnixClient(socket_path, request_timeout_seconds=1)
        started = time.monotonic()
        with pytest.raises(transport.McpUnixClientError, match="MCP_DEADLINE_EXCEEDED"):
            client.prepare_context(
                {
                    "query": PRIVATE_PROMPT,
                    "budget": {"memory_deadline_ms": 50},
                }
            )
        client.close()
        assert time.monotonic() - started < 0.5
        ledger = _wait_terminal(ledger_path)
        assert ledger["events"][0]["outcome"] == "TIMEOUT_ELAPSED"

    assert _ledger(ledger_path)["native_attempts"] == 1


def test_ledger_keeps_frame_hash_and_shape_but_no_values(tmp_path: Path) -> None:
    socket_path = tmp_path / "redaction.sock"
    ledger_path = tmp_path / "redaction-ledger.json"
    request = {
        "jsonrpc": "2.0",
        "id": f"id-{PRIVATE_TOKEN}",
        "method": "tools/call",
        "params": {
            "name": "milai_prepare_context",
            "arguments": {"query": PRIVATE_PROMPT, "token": PRIVATE_TOKEN},
        },
    }

    with McpFaultEndpoint(
        "MALFORMED", socket_path=socket_path, ledger_path=ledger_path
    ):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(str(socket_path))
            connection.sendall(json.dumps(request).encode() + b"\n")
            assert connection.recv(4096).endswith(b"\n")
        ledger = _wait_terminal(ledger_path)

    encoded = json.dumps(ledger, sort_keys=True)
    inventory = ledger["events"][0]["request"]
    assert inventory["json_kind"] == "object"
    assert inventory["method"] == "tools/call"
    assert inventory["params_keys"] == ["arguments", "name"]
    assert len(inventory["frame_sha256"]) == 64
    assert len(inventory["request_id_sha256"]) == 64
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert "arguments" in encoded
    assert "query" not in encoded
    assert not list(tmp_path.glob(".redaction-ledger.json.*.tmp"))


def test_frame_boundary_counts_one_attempt_and_closes_without_response(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "bounded.sock"
    ledger_path = tmp_path / "bounded-ledger.json"
    with McpFaultEndpoint(
        "MALFORMED",
        socket_path=socket_path,
        ledger_path=ledger_path,
        max_frame_bytes=1_024,
    ) as endpoint:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1)
            connection.connect(str(socket_path))
            connection.sendall(b"x" * 1_025)
            assert connection.recv(1) == b""
        ledger = _wait_terminal(ledger_path)
        assert endpoint.native_attempts == 1
        assert ledger["events"][0]["outcome"] == "REQUEST_FRAME_TOO_LARGE"
        assert ledger["events"][0]["request"]["frame_sha256"] is None
        assert ledger["events"][0]["request"]["observed_bytes"] == 1_025


def test_existing_socket_and_ledger_are_never_overwritten(tmp_path: Path) -> None:
    socket_path = tmp_path / "existing.sock"
    ledger_path = tmp_path / "existing.json"
    socket_path.write_text("other owner", encoding="utf-8")
    ledger_path.write_text("other ledger", encoding="utf-8")

    endpoint = McpFaultEndpoint(
        "MALFORMED", socket_path=socket_path, ledger_path=ledger_path
    )
    with pytest.raises(FileExistsError):
        endpoint.start()

    assert socket_path.read_text(encoding="utf-8") == "other owner"
    assert ledger_path.read_text(encoding="utf-8") == "other ledger"


def test_cleanup_never_unlinks_replacement_inode(tmp_path: Path) -> None:
    socket_path = tmp_path / "drift.sock"
    ledger_path = tmp_path / "drift-ledger.json"
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint = McpFaultEndpoint(
        "MALFORMED", socket_path=socket_path, ledger_path=ledger_path
    ).start()
    try:
        socket_path.unlink()
        replacement.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        endpoint.stop()

        assert socket_path.exists()
        cleanup = _ledger(ledger_path)["cleanup"]
        assert cleanup["identity_match"] is False
        assert cleanup["owned_inode_removed"] is False
        assert cleanup["path_absent"] is False
    finally:
        endpoint.stop()
        replacement.close()
        socket_path.unlink(missing_ok=True)


@pytest.mark.parametrize("stopping", (True, False))
def test_listener_close_is_only_normal_during_requested_stop(
    tmp_path: Path,
    stopping: bool,
) -> None:
    endpoint = McpFaultEndpoint(
        "MALFORMED",
        socket_path=tmp_path / "listener-close.sock",
        ledger_path=tmp_path / "listener-close.json",
    )

    class ClosedListener:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            raise OSError("synthetic EBADF")

    endpoint._listener = ClosedListener()  # type: ignore[assignment]
    if stopping:
        endpoint._stop_event.set()
        endpoint._run()
    else:
        with pytest.raises(OSError, match="synthetic EBADF"):
            endpoint._run()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "DOWN"}, "mode must be MALFORMED or TIMEOUT"),
        (
            {"mode": "TIMEOUT", "timeout_delay_seconds": 5.01},
            "timeout_delay_seconds must be in",
        ),
        (
            {"mode": "TIMEOUT", "frame_read_timeout_seconds": 5.01},
            "frame_read_timeout_seconds must be in",
        ),
        ({"mode": "MALFORMED", "socket_name": "relative.sock"}, "must be absolute"),
    ],
)
def test_invalid_configuration_fails_before_mutation(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    socket_path = Path(str(kwargs.pop("socket_name", tmp_path / "new/socket.sock")))
    ledger_path = tmp_path / "new/ledger.json"
    with pytest.raises(ValueError, match=message):
        McpFaultEndpoint(
            socket_path=socket_path,
            ledger_path=ledger_path,
            **kwargs,
        )
    assert not ledger_path.parent.exists()


def test_start_failure_removes_only_newly_bound_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.dg13u_u1_mcp_fault as fault

    socket_path = tmp_path / "failed-start.sock"
    ledger_path = tmp_path / "failed-start.json"
    endpoint = McpFaultEndpoint(
        "MALFORMED", socket_path=socket_path, ledger_path=ledger_path
    )

    def fail_ledger(_path: Path, _value: object) -> None:
        raise OSError("synthetic ledger failure")

    monkeypatch.setattr(fault, "_atomic_private_json", fail_ledger)
    with pytest.raises(OSError, match="synthetic ledger failure"):
        endpoint.start()

    assert not socket_path.exists()


def test_cli_ready_file_and_sigterm_write_inode_cleanup_receipt(tmp_path: Path) -> None:
    socket_path = tmp_path / "cli.sock"
    ledger_path = tmp_path / "cli-ledger.json"
    ready_path = tmp_path / "cli-ready.json"
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_mcp_fault.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--mode",
            "MALFORMED",
            "--socket",
            str(socket_path),
            "--ledger",
            str(ledger_path),
            "--ready-file",
            str(ready_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        assert ready["socket_path"] == str(socket_path)
        assert stat.S_IMODE(ready_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(socket_path.lstat().st_mode) == 0o600
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    assert not socket_path.exists()
    ledger = _ledger(ledger_path)
    assert ledger["active"] is False
    assert ledger["cleanup"]["owned_inode_removed"] is True
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
