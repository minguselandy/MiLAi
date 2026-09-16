from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milai_mcp.http_transport import HttpPrincipalBinding, StaticBearerTokenVerifier

_INBOUND_TOKEN = secrets.token_urlsafe(32)


def _isolated_server_environment() -> dict[str, str]:
    """Keep ambient MiLAi service configuration out of child-process tests."""

    return {
        key: value for key, value in os.environ.items() if not key.startswith("MILAI_")
    }


class _RuntimeHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _reply(self, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path != "/v1/capabilities":
            self.send_error(404)
            return
        self._reply(
            {
                "api_version": "1",
                "contract_version": "agent.v1",
                "runtime_version": "0.1.0",
                "profile": "local",
                "capabilities": ["memory:read"],
                "routes": ["L0", "L1"],
                "consistency_modes": ["CANONICAL_REQUIRED"],
                "agent_profiles": ["agent-memory"],
                "features": {},
                "limits": {},
                "data_mode": "SYNTHETIC_ONLY",
                "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                "implementation_status": "0.1.x CANDIDATE",
            }
        )

    def do_POST(self) -> None:
        if self.path != "/v1/memory/resolve":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        assert isinstance(payload, dict)
        type(self).requests.append(payload)
        evidence_id = "11111111-1111-4111-8111-111111111111"
        self._reply(
            {
                "schema_version": "access-outcome-v0.1",
                "status": "PARTIAL",
                "availability": "AVAILABLE",
                "items": [],
                "open_issue_ids": [],
                "evidence_refs": [evidence_id],
                "canonical_position": {"canonical_outbox_sequence": 9},
                "trace_id": "22222222-2222-4222-8222-222222222222",
                "degraded_components": [],
                "abstention_reason": "SEMANTIC_COMPLETENESS_NOT_ASSERTED",
                "context_receipt": None,
                "context_id": "33333333-3333-4333-8333-333333333333",
                "continuation": None,
                "memory_context": {
                    "schema_version": "memory-context-v0.1",
                    "authority_class": "EVIDENCE_ONLY",
                    "text": "[E1] The HTTP deployment marker is P08-HTTP-731.",
                    "selected_evidence_ids": [evidence_id],
                    "selected_source_turn_refs": ["agent-session:p08/turn:1"],
                    "windows": [
                        {
                            "window_id": "p08-window-1",
                            "session_id": "p08-session",
                            "evidence_ids": [evidence_id],
                            "source_turn_refs": ["agent-session:p08/turn:1"],
                            "text": "The HTTP deployment marker is P08-HTTP-731.",
                            "observed_at": "2026-09-03T10:00:00Z",
                        }
                    ],
                },
                "memory_intent": "REQUIRED",
                "requirement": "SEARCH",
                "consistency": payload.get("consistency_mode"),
                "access_trace": {
                    "schema_version": "access-trace-v0.1",
                    "runtime_request_id": "p08-runtime-request",
                    "retrieval_trace_id": "22222222-2222-4222-8222-222222222222",
                    "spans": {"runtime_kernel_ms": 1.0},
                },
                "request_id": "p08-runtime-request",
                "fallback_used": False,
                "fallback_reason": None,
            }
        )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_ready(url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                body = json.load(response)
                assert isinstance(body, dict)
                return body
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise AssertionError("HTTP MCP server did not become ready")


async def _call(url: str) -> dict[str, Any]:
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {_INBOUND_TOKEN}"}
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            mode="2026-07-28",
        ) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == ["milai_memory_resolve"]
            assert set(tools.tools[0].input_schema["properties"]) == {
                "query",
                "previous_context_id",
            }
            result = await client.call_tool(
                "milai_memory_resolve", {"query": "HTTP deployment marker"}
            )
            assert result.is_error is False
            assert isinstance(result.structured_content, dict)
            return result.structured_content


def test_static_http_principal_binds_token_and_scope() -> None:
    binding = HttpPrincipalBinding.create(
        bearer_token=_INBOUND_TOKEN,
        principal_id="codex-local-p08",
        issuer_url="http://127.0.0.1:7337",
        resource_url="http://127.0.0.1:7337/mcp",
        scope={"project_ids": ["p08-http"]},
    )
    verifier = StaticBearerTokenVerifier(binding)

    accepted = asyncio.run(verifier.verify_token(_INBOUND_TOKEN))
    rejected = asyncio.run(verifier.verify_token("x" * 40))

    assert accepted is not None
    assert accepted.subject == "codex-local-p08"
    assert accepted.scopes == ["memory:read"]
    assert accepted.claims == {
        "milai_scope_sha256": binding.scope_digest,
        "milai_access_profile": "agent-memory",
        "milai_governance_mode": "SEPARATED_AUTHORITY",
    }
    assert rejected is None


def test_codex_full_http_principal_declares_full_control_without_independent_review() -> None:
    binding = HttpPrincipalBinding.create(
        bearer_token=_INBOUND_TOKEN,
        principal_id="codex-full-local",
        issuer_url="http://127.0.0.1:7337",
        resource_url="http://127.0.0.1:7337/mcp",
        scope={"project_ids": ["one-project"]},
        access_profile="codex-full",
    )
    accepted = asyncio.run(StaticBearerTokenVerifier(binding).verify_token(_INBOUND_TOKEN))

    assert accepted is not None
    assert set(accepted.scopes) == {
        "memory:read",
        "evidence:capture",
        "proposal:create",
        "proposal:review",
        "evidence:revoke",
        "operations:admin",
        "working-state:read",
        "working-state:write",
    }
    assert accepted.claims["milai_access_profile"] == "codex-full"
    assert accepted.claims["milai_governance_mode"] == "SINGLE_HOST_FULL_CONTROL"


def test_agent_memory_streamable_http_requires_auth_and_returns_facade() -> None:
    _RuntimeHandler.requests = []
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    runtime_thread.start()
    port = _free_port()
    executable = Path(sys.executable).with_name("milai-agent-memory-mcp")
    environment = _isolated_server_environment()
    environment.update(
        {
            "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
            "MILAI_AGENT_TOKEN": "synthetic-runtime-token-at-least-32-characters",
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["p08-http"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_MCP_HTTP_BEARER_TOKEN": _INBOUND_TOKEN,
            "MILAI_MCP_HTTP_PRINCIPAL_ID": "codex-local-p08",
        }
    )
    process = subprocess.Popen(  # noqa: S603 - exact installed test executable
        [
            str(executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        assert _wait_ready(f"http://127.0.0.1:{port}/readyz") == {
            "status": "ready",
            "service": "milai-mcp",
        }
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=2
        ) as health:
            assert json.load(health)["status"] == "ok"
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/mcp", timeout=2
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("unauthenticated MCP request was accepted")

        result = asyncio.run(_call(f"http://127.0.0.1:{port}/mcp"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        runtime.shutdown()
        runtime.server_close()
        runtime_thread.join(timeout=5)

    assert result["schema_version"] == "memory-evidence-context-v1"
    assert result["retrieval_status"] == "HIT"
    assert result["evidence"][0]["text"] == (
        "The HTTP deployment marker is P08-HTTP-731."
    )
    assert len(_RuntimeHandler.requests) == 1
    assert _RuntimeHandler.requests[0]["requested_scope"] == {
        "project_ids": ["p08-http"]
    }
