from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from milai_openworker_mcp.transport import McpUnixClient, McpUnixClientError


def _response(request_id: object, result: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _fake_mcp_server(
    path: Path,
    ready: threading.Event,
    requests: list[dict[str, Any]],
) -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o600)
    listener.listen(1)
    ready.set()
    connection, _ = listener.accept()
    with listener, connection, connection.makefile("rb") as source:
        for raw in source:
            request = json.loads(raw)
            requests.append(request)
            if request.get("method") == "initialize":
                connection.sendall(
                    _response(
                        request["id"],
                        {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "fake", "version": "1"},
                        },
                    )
                )
            elif request.get("method") == "tools/list":
                connection.sendall(
                    _response(
                        request["id"],
                        {
                            "tools": [
                                {"name": "milai_memory_resolve"},
                                {"name": "milai_recall"},
                            ]
                        },
                    )
                )
            elif request.get("method") == "tools/call":
                arguments = request["params"]["arguments"]
                tool_name = request["params"]["name"]
                if tool_name == "milai_prepare_context":
                    structured = {
                        "route": "CACHE",
                        "status": "UNCHANGED",
                        "reason": "VALIDATED_TASK_SLOT_REUSE",
                        "context_capsule": None,
                        "context_delta": {"status": "UNCHANGED"},
                        "relevant_open_issue_closure": [],
                        "canonical_position": 7,
                        "validation_token": "next-validation-token",
                        "trace_pointer": None,
                        "usage": {"prepare_context_calls": 2},
                        "recall_execution_trace": {
                            "requested_route": "CACHE",
                            "planned_route": "CACHE",
                            "attempted_routes": ["CACHE"],
                            "terminal_route": "CACHE",
                        },
                    }
                elif tool_name == "milai_recall":
                    query = arguments["query"]
                    structured = {
                        "status": "OK",
                        "items": [{"payload": {"query": query}}],
                        "open_issue_ids": [],
                        "trace_id": f"trace-{query}",
                    }
                elif tool_name == "milai_memory_resolve":
                    query = arguments["query"]
                    structured = {
                        "schema_version": "access-outcome-v0.1",
                        "status": "HIT",
                        "items": [{"payload": {"query": query}}],
                        "open_issue_ids": [],
                        "availability": "AVAILABLE",
                        "trace_id": f"resolve-trace-{query}",
                    }
                elif tool_name == "milai_evidence_capture":
                    structured = {"evidence_id": "evidence-1", "canonical_changed": False}
                else:
                    structured = {
                        "proposal_id": "proposal-1",
                        "confirmation_summary": {"canonical_changed": False},
                    }
                connection.sendall(
                    _response(
                        request["id"],
                        {
                            "isError": False,
                            "structuredContent": structured,
                        },
                    )
                )


def test_reuses_one_initialized_uds_session_for_multiple_recalls(tmp_path: Path) -> None:
    socket_path = tmp_path / "reader-lite.sock"
    requests: list[dict[str, Any]] = []
    ready = threading.Event()
    server = threading.Thread(
        target=_fake_mcp_server,
        args=(socket_path, ready, requests),
        daemon=True,
    )
    server.start()
    assert ready.wait(timeout=2)

    client = McpUnixClient(socket_path)
    first = client.recall("first")
    second = client.recall("second")
    client.close()
    server.join(timeout=2)

    assert first["trace_id"] == "trace-first"
    assert second["trace_id"] == "trace-second"
    assert [request.get("method") for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
        "tools/call",
    ]
    assert not server.is_alive()


def test_query_first_resolve_reuses_one_initialized_uds_session(tmp_path: Path) -> None:
    socket_path = tmp_path / "reader-lite.sock"
    requests: list[dict[str, Any]] = []
    ready = threading.Event()
    server = threading.Thread(
        target=_fake_mcp_server,
        args=(socket_path, ready, requests),
        daemon=True,
    )
    server.start()
    assert ready.wait(timeout=2)

    client = McpUnixClient(socket_path)
    first = client.resolve_memory("first")
    second = client.resolve_memory(
        "second", previous_context_id="11111111-1111-4111-8111-111111111111"
    )
    client.close()
    server.join(timeout=2)

    assert first["trace_id"] == "resolve-trace-first"
    assert second["trace_id"] == "resolve-trace-second"
    assert first["host_transport"]["uds_roundtrip_ms"] >= 0
    assert [
        request["params"]["name"]
        for request in requests
        if request.get("method") == "tools/call"
    ] == ["milai_memory_resolve", "milai_memory_resolve"]
    calls = [request for request in requests if request.get("method") == "tools/call"]
    assert calls[0]["params"]["arguments"] == {"query": "first"}
    assert calls[1]["params"]["arguments"] == {
        "query": "second",
        "previous_context_id": "11111111-1111-4111-8111-111111111111",
    }
    assert not server.is_alive()


def test_composite_prepare_context_reuses_initialized_uds_session(tmp_path: Path) -> None:
    socket_path = tmp_path / "reader-lite.sock"
    requests: list[dict[str, Any]] = []
    ready = threading.Event()
    server = threading.Thread(
        target=_fake_mcp_server,
        args=(socket_path, ready, requests),
        daemon=True,
    )
    server.start()
    assert ready.wait(timeout=2)

    client = McpUnixClient(socket_path)
    client.recall("first")
    prepared = client.prepare_context(
        {
            "query": "tool result",
            "active_goal": "finish project",
            "event": "TOOL_RESULT",
            "budget": {"memory_deadline_ms": 5_000},
        }
    )
    client.close()
    server.join(timeout=2)

    assert prepared["status"] == "UNCHANGED"
    assert prepared["validation_token"] == "next-validation-token"  # noqa: S105
    assert prepared["recall_execution_trace"]["planned_route"] == "CACHE"
    assert prepared["timing"]["uds_roundtrip_ms"] >= 0
    tool_calls = [
        request["params"]["name"] for request in requests if request.get("method") == "tools/call"
    ]
    assert tool_calls == ["milai_recall", "milai_prepare_context"]
    assert not server.is_alive()


def test_catalog_and_submitter_calls_are_exact_and_share_one_session(tmp_path: Path) -> None:
    socket_path = tmp_path / "submitter.sock"
    requests: list[dict[str, Any]] = []
    ready = threading.Event()
    server = threading.Thread(
        target=_fake_mcp_server,
        args=(socket_path, ready, requests),
        daemon=True,
    )
    server.start()
    assert ready.wait(timeout=2)

    client = McpUnixClient(socket_path)
    assert client.list_tools() == ("milai_memory_resolve", "milai_recall")
    evidence = client.capture_evidence(
        {
            "operation_id": "evidence-op",
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": "synthetic://tool",
            "subject_id": "project",
            "observed_at": "2026-08-23T12:00:00+08:00",
            "content": "Python 3.11",
            "permission_snapshot": {"readable": True},
            "confirmation": "CAPTURE",
            "retention_state": "READABLE",
            "data_classification": "SYNTHETIC",
        }
    )
    proposal = client.create_proposal(
        {
            "operation_id": "proposal-op",
            "proposal": {"operation": "CREATE"},
            "confirmation": "SUBMIT",
        }
    )
    client.close()
    server.join(timeout=2)

    assert evidence["evidence_id"] == "evidence-1"
    assert proposal["proposal_id"] == "proposal-1"
    assert [request.get("method") for request in requests].count("initialize") == 1
    assert [
        request["params"]["name"] for request in requests if request.get("method") == "tools/call"
    ] == ["milai_evidence_capture", "milai_proposal_create"]
    assert not server.is_alive()


def test_rejects_non_socket_capability(tmp_path: Path) -> None:
    path = tmp_path / "reader-lite.sock"
    path.write_text("not a socket", encoding="utf-8")
    os.chmod(path, 0o600)

    with pytest.raises(McpUnixClientError, match="MCP_SOCKET_IDENTITY_REJECTED"):
        McpUnixClient(path).recall("query")


def test_prepare_context_deadline_bounds_a_stalled_warm_session(tmp_path: Path) -> None:
    socket_path = tmp_path / "reader-lite.sock"
    ready = threading.Event()
    tool_received = threading.Event()
    release = threading.Event()

    def stalled_server() -> None:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        listener.listen(1)
        ready.set()
        connection, _ = listener.accept()
        with listener, connection, connection.makefile("rb") as source:
            for raw in source:
                request = json.loads(raw)
                if request.get("method") == "initialize":
                    connection.sendall(
                        _response(
                            request["id"],
                            {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "serverInfo": {"name": "stalled", "version": "1"},
                            },
                        )
                    )
                elif request.get("method") == "tools/call":
                    tool_received.set()
                    release.wait(timeout=2)
                    break

    server = threading.Thread(target=stalled_server, daemon=True)
    server.start()
    assert ready.wait(timeout=2)
    client = McpUnixClient(socket_path, request_timeout_seconds=2)
    started = time.monotonic()
    try:
        with pytest.raises(McpUnixClientError, match="MCP_DEADLINE_EXCEEDED"):
            client.prepare_context(
                {
                    "query": "bounded request",
                    "active_goal": "finish project",
                    "event": "TASK_START",
                    "budget": {"memory_deadline_ms": 50},
                }
            )
    finally:
        release.set()
        client.close()
    elapsed = time.monotonic() - started
    server.join(timeout=2)
    assert tool_received.is_set()
    assert elapsed < 0.5
    assert not server.is_alive()


def test_prepare_context_malformed_terminal_is_one_logical_call_without_retry(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "reader-lite.sock"
    requests: list[dict[str, Any]] = []
    ready = threading.Event()

    def malformed_server() -> None:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        listener.listen(1)
        ready.set()
        connection, _ = listener.accept()
        with listener, connection, connection.makefile("rb") as source:
            for raw in source:
                request = json.loads(raw)
                requests.append(request)
                if request.get("method") == "initialize":
                    connection.sendall(
                        _response(
                            request["id"],
                            {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "serverInfo": {"name": "malformed", "version": "1"},
                            },
                        )
                    )
                elif request.get("method") == "tools/call":
                    connection.sendall(
                        _response(
                            request["id"],
                            {"isError": False, "structuredContent": {"status": "UNKNOWN"}},
                        )
                    )
                    break

    server = threading.Thread(target=malformed_server, daemon=True)
    server.start()
    assert ready.wait(timeout=2)
    client = McpUnixClient(socket_path)
    with pytest.raises(McpUnixClientError, match="MCP_PREPARE_CONTEXT_CONTRACT_REJECTED"):
        client.prepare_context(
            {
                "query": "current release target",
                "budget": {"memory_deadline_ms": 5_000},
            }
        )
    client.close()
    server.join(timeout=2)
    assert [request.get("method") for request in requests].count("tools/call") == 1
    assert not server.is_alive()
