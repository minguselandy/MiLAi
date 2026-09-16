from __future__ import annotations

import importlib
import json
import socket
import socketserver
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
native = importlib.import_module("check_v02_native_protocol")
checker = importlib.import_module("check_v02_native_mcp")
runner = importlib.import_module("run_v02_native_session")
mcp = importlib.import_module("v02_native_mcp")


def test_port_relay_keeps_mcp_authority_identical(tmp_path):
    command = native.container_command(tmp_path, "run-owned", mcp_port=34567)
    assert command[command.index("--mcp-port") + 1] == "34567"
    assert "milai.native_run_root=" + str(tmp_path) in command
    assert command[command.index("--network") + 1] == "none"


def test_only_explicit_g_continuation_uses_resume(tmp_path):
    resumed = native.container_command(tmp_path, "owned", prompt="continue",
                                       resume_thread="thread-id")
    assert resumed[resumed.index("exec") + 1] == "resume"
    assert resumed[-2:] == ["thread-id", "continue"]
    cold = native.container_command(tmp_path, "owned", prompt="new task")
    assert "resume" not in cold and "thread-id" not in cold


def test_native_output_envelope_and_mcp_error_are_distinguished():
    state = {"state_id": "s", "version": 1, "payload": checker.PAYLOAD}
    output = "Wall time: 0.0155 seconds\nOutput:\n" + json.dumps(state, ensure_ascii=False)
    assert list(checker.state_records(output)) == [state]
    assert list(checker.state_records("Wall time: 1 seconds\nOutput:\nerror: denied")) == []
    assert list(checker.state_records("arbitrary prose\n" + json.dumps(state))) == []


def test_allocation_cannot_be_replayed_in_a_fresh_directory(tmp_path):
    with pytest.raises(runner.LocalGateError, match="RUN_ROOT_MISMATCH"):
        runner.run(tmp_path / "other", {"run_root": "artifacts/authorized"}, "task", "probe")
    assert not (tmp_path / "other").exists()


@contextmanager
def _owned_test_upstream(seen):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            chunks = []
            while chunk := self.request.recv(4096):
                chunks.append(chunk)
            seen.append(b"".join(chunks))
            self.request.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 4\r\n\r\ntail")

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
        thread.start()
        try:
            yield server, thread
        finally:
            # Also runs when client setup/connect fails before reaching upstream.
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive(), "Owned test upstream did not exit"


@pytest.mark.parametrize("deep", [False, True], ids=["ordinary", "deep"])
def test_unix_mcp_hop_preserves_http_bytes_and_closes_connections(tmp_path, deep):
    root = tmp_path / ("long" * 20) / ("long" * 20) if deep else tmp_path
    (root / "sockets").mkdir(parents=True)
    seen = []
    with _owned_test_upstream(seen) as (server, thread):
        port = server.server_address[1]
        raw = f"POST /mcp HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode()
        with mcp.connection(root, f"http://127.0.0.1:{port}/mcp"), (
            mcp.socket_path(root / "sockets", "mcp.sock")
        ) as address, (
            socket.socket(socket.AF_UNIX)
        ) as client:
            client.settimeout(2)
            client.connect(address)
            client.sendall(raw)
            client.shutdown(socket.SHUT_WR)
            data = bytearray()
            while chunk := client.recv(4096):
                data.extend(chunk)
            assert data.endswith(b"tail")
    assert not thread.is_alive() and seen == [raw]


def test_mcp_upstream_closes_when_client_setup_fails(tmp_path):
    (tmp_path / "sockets").mkdir()
    seen = []
    with pytest.raises(RuntimeError, match="intentional client setup failure"):
        with _owned_test_upstream(seen) as (server, thread):
            port = server.server_address[1]
            with mcp.connection(tmp_path, f"http://127.0.0.1:{port}/mcp"):
                raise RuntimeError("intentional client setup failure")
    assert not thread.is_alive()
    assert seen == []
    assert server.socket.fileno() == -1


def test_deep_artifact_directory_can_bind_unix_socket(tmp_path):
    bridge = importlib.import_module("v02_native_bridge")
    directory = tmp_path / ("long" * 20) / ("long" * 20)
    directory.mkdir(parents=True)
    with bridge.socket_path(directory, "provider.sock") as address, (
        socket.socket(socket.AF_UNIX)
    ) as server:
        server.bind(address)
        server.listen(1)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(address)
            connection, _ = server.accept()
            with connection:
                client.sendall(b"exact")
                assert connection.recv(5) == b"exact"
        assert (directory / "provider.sock").is_socket()
