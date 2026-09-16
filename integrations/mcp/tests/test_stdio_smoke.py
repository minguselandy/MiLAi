from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from mcp import Client, StdioServerParameters, stdio_client


class _RuntimeHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[tuple[str, dict[str, Any] | None]]] = []

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _reply(self, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        type(self).requests.append((self.path, None))
        assert self.path == "/v1/capabilities"
        self._reply(
            {
                "api_version": "1",
                "contract_version": "agent.v1",
                "runtime_version": "0.1.0",
                "profile": "local",
                "capabilities": ["memory:read"],
                "routes": ["L0", "L1"],
                "consistency_modes": ["EVENTUAL", "CANONICAL_REQUIRED"],
                "agent_profiles": ["reader-lite"],
                "features": {},
                "limits": {},
                "data_mode": "SYNTHETIC_ONLY",
                "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                "implementation_status": "0.1.x CANDIDATE",
            }
        )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        assert isinstance(payload, dict)
        type(self).requests.append((self.path, payload))
        assert self.path == "/v1/memory/resolve"
        request_id = self.headers["X-Request-ID"]
        self._reply(
            {
                "schema_version": "access-outcome-v0.1",
                "status": "HIT",
                "items": [
                    {
                        "claim_id": "11111111-1111-4111-8111-111111111111",
                        "claim_version_id": "22222222-2222-4222-8222-222222222222",
                        "payload": {"value": "synthetic persisted state"},
                        "evidence_ids": ["33333333-3333-4333-8333-333333333333"],
                        "open_issue_ids": [],
                    }
                ],
                "open_issue_ids": [],
                "evidence_refs": ["33333333-3333-4333-8333-333333333333"],
                "consistency": payload["consistency_mode"],
                "canonical_position": {
                    "canonical_outbox_sequence": 7,
                    "fts_watermark": 7,
                    "vector_watermark": 7,
                },
                "trace_id": "44444444-4444-4444-8444-444444444444",
                "degraded_components": [],
                "abstention_reason": None,
                "context_receipt": None,
                "memory_intent": "REQUIRED",
                "requirement": "EXACT",
                "availability": "AVAILABLE",
                "interpretation": {
                    "version": "runtime-query-interpreter-v1",
                    "reason_code": "QUERY_MEMORY_EXACT_SIGNAL",
                    "retrieval_intent": "CURRENT_STATE",
                },
                "access_trace": {
                    "schema_version": "access-trace-v0.1",
                    "retrieval_trace_id": "44444444-4444-4444-8444-444444444444",
                    "runtime_request_id": request_id,
                    "requested_intent": None,
                    "planned_stage": "SEARCH",
                    "attempted_stages": ["EXACT", "FTS", "CANONICAL_GATE"],
                    "terminal_stage": "FTS",
                    "stop_reason": "CANONICAL_RESULTS_RESOLVED",
                    "fallback_reason": None,
                    "canonical_position": 7,
                    "spans": {"runtime_kernel_ms": 1.0},
                    "route_trace_complete": True,
                    "trace_gap_reason": None,
                },
                "request_id": request_id,
                "fallback_used": False,
                "fallback_reason": None,
            }
        )


async def _call(parameters: StdioServerParameters) -> dict[str, Any]:
    async with Client(stdio_client(parameters), mode="2026-07-28") as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "milai_recall",
            "milai_memory_resolve",
        }
        result = await client.call_tool(
            "milai_memory_resolve", {"query": "current project state"}
        )
        assert result.is_error is False
        assert isinstance(result.structured_content, dict)
        return result.structured_content


def test_generic_task_free_stdio_smoke_survives_mcp_process_restart() -> None:
    _RuntimeHandler.requests = []
    runtime = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    try:
        executable = Path(sys.executable).with_name("milai-mcp")
        parameters = StdioServerParameters(
            command=str(executable),
            args=["--profile", "reader-lite", "--max-retries", "0"],
            env={
                "MILAI_BASE_URL": f"http://127.0.0.1:{runtime.server_port}",
                "MILAI_AGENT_TOKEN": "synthetic-reader-token-at-least-32-characters",
                "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["milai"]}',
                "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
                "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            },
        )

        first = asyncio.run(_call(parameters))
        second = asyncio.run(_call(parameters))
    finally:
        runtime.shutdown()
        runtime.server_close()
        thread.join(timeout=5)

    assert first["items"] == second["items"]
    assert first["canonical_position"] == second["canonical_position"]
    assert first["access_trace"]["logical_mcp_calls"] == 1
    assert second["access_trace"]["logical_mcp_calls"] == 1
    assert first["access_trace"]["automatic_retry_count"] == 0
    assert second["access_trace"]["automatic_retry_count"] == 0
    queries = [
        payload for path, payload in _RuntimeHandler.requests if path == "/v1/memory/resolve"
    ]
    assert len(queries) == 2
    assert all(
        payload is not None and set(payload).isdisjoint({"task_id", "active_goal"})
        for payload in queries
    )
