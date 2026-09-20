from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from milai_openworker_mcp.host import orchestrator
from milai_openworker_mcp.host.orchestrator import Handler, _load_ingress_token

OLD_CAPABILITY = "synthetic-process-capability-old"
NEW_CAPABILITY = "synthetic-process-capability-new"
WILDCARD_IPV4 = "0.0.0.0"  # noqa: S104 - the diagnosis intentionally exercises wildcard bind


def _start_server(host: str, token: str) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, 0), Handler)
    server.ingress_token = token  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(
    server: ThreadingHTTPServer, thread: threading.Thread
) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _get_models(host: str, port: int, token: str) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection(host, port, timeout=2)
    connection.request(
        "GET",
        "/v1/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    response = connection.getresponse()
    status = response.status
    payload = json.loads(response.read())
    connection.close()
    return status, payload


def _non_loopback_ipv4() -> str:
    candidates: list[str] = []
    try:
        route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            route_probe.connect(("192.0.2.1", 9))
            candidates.append(str(route_probe.getsockname()[0]))
        finally:
            route_probe.close()
    except OSError:
        pass
    try:
        candidates.extend(
            str(address[4][0])
            for address in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
            )
        )
    except OSError:
        pass
    for candidate in candidates:
        if not candidate.startswith("127.") and candidate != WILDCARD_IPV4:
            return candidate
    pytest.skip("runner exposes no routable non-loopback IPv4 address")


def test_loopback_ingress_accepts_exact_bearer() -> None:
    server, thread = _start_server("127.0.0.1", OLD_CAPABILITY)
    try:
        status, payload = _get_models("127.0.0.1", server.server_port, OLD_CAPABILITY)
        assert status == 200
        assert payload["data"][0]["owned_by"] == "milai-local"
    finally:
        _stop_server(server, thread)


def test_authentication_precedes_body_parse_and_rejects_duplicate_bearer() -> None:
    server, thread = _start_server("127.0.0.1", OLD_CAPABILITY)
    try:
        for authorization in (None, "Bearer wrong-token"):
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            headers = {} if authorization is None else {"Authorization": authorization}
            connection.request(
                "POST", "/v1/chat/completions", body=b"not-json", headers=headers
            )
            response = connection.getresponse()
            assert response.status == 401
            assert json.loads(response.read())["error"]["reason_code"] == (
                "AUTHENTICATION_REQUIRED"
            )
            connection.close()

        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=2
        )
        connection.putrequest("POST", "/v1/chat/completions")
        connection.putheader("Authorization", f"Bearer {OLD_CAPABILITY}")
        connection.putheader("Authorization", f"Bearer {OLD_CAPABILITY}")
        connection.putheader("Content-Length", "8")
        connection.endheaders(b"not-json")
        response = connection.getresponse()
        assert response.status == 401
        assert json.loads(response.read())["error"]["reason_code"] == (
            "AUTHENTICATION_REQUIRED"
        )
        connection.close()
    finally:
        _stop_server(server, thread)


def test_executable_accepts_explicit_wildcard_listen_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def close(self) -> None:
            captured["adapter_closed"] = True

    class FakeServer:
        def __init__(self, address: tuple[str, int], handler: object) -> None:
            captured["address"] = address
            captured["handler"] = handler

        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["server_closed"] = True

    token_file = tmp_path / "ingress-token"
    token_file.write_text(OLD_CAPABILITY, encoding="ascii")
    token_file.chmod(0o600)
    monkeypatch.setattr(orchestrator, "OpenWorkerProviderAdapter", FakeAdapter)
    monkeypatch.setattr(orchestrator, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "milai-openworker-adapter",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--trace",
            str(tmp_path / "trace.jsonl"),
            "--listen-host",
            WILDCARD_IPV4,
            "--listen-port",
            "19090",
            "--memory-mode",
            "none",
            "--ingress-token-file",
            str(token_file),
        ],
    )

    orchestrator.main()

    assert captured == {
        "address": (WILDCARD_IPV4, 19090),
        "handler": Handler,
        "served": True,
        "adapter_closed": True,
        "server_closed": True,
    }


def test_plain_http_with_bearer_is_accepted_over_non_loopback_interface() -> None:
    non_loopback = _non_loopback_ipv4()
    server, thread = _start_server(WILDCARD_IPV4, OLD_CAPABILITY)
    try:
        status, payload = _get_models(non_loopback, server.server_port, OLD_CAPABILITY)
        assert status == 200
        assert payload["data"][0]["owned_by"] == "milai-local"
    finally:
        _stop_server(server, thread)


def test_token_file_replacement_does_not_revoke_process_token(tmp_path: Path) -> None:
    token_file = tmp_path / "ingress-token"
    token_file.write_text(OLD_CAPABILITY, encoding="ascii")
    token_file.chmod(0o600)
    server, thread = _start_server("127.0.0.1", _load_ingress_token(token_file))
    try:
        assert _get_models("127.0.0.1", server.server_port, OLD_CAPABILITY)[0] == 200

        token_file.write_text(NEW_CAPABILITY, encoding="ascii")
        token_file.chmod(0o600)

        assert _get_models("127.0.0.1", server.server_port, OLD_CAPABILITY)[0] == 200
        status, payload = _get_models("127.0.0.1", server.server_port, NEW_CAPABILITY)
        assert status == 401
        assert payload["error"]["reason_code"] == "AUTHENTICATION_REQUIRED"
    finally:
        _stop_server(server, thread)
