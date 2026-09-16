from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from milai_client import MemoryTransportUnavailableError
from milai_client.models import PrepareContextRequest

from milai_openworker_mcp import McpPrepareContextClient, TargetTokenizerCounter


class _Mcp:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def prepare_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "route": "CACHE",
            "status": "UNCHANGED",
            "reason": "VALIDATED_TASK_SLOT_REUSE",
            "context_capsule": None,
            "context_delta": {"status": "UNCHANGED"},
            "relevant_open_issue_closure": [],
            "canonical_position": 7,
            "validation_token": "validation-token",
            "recall_execution_trace": {
                "need_signature_id": None,
                "requested_route": "CACHE",
                "planned_route": "CACHE",
                "attempted_routes": ["CACHE"],
                "terminal_route": "CACHE",
                "result": "HIT",
                "policy_override_reason": None,
                "fallback_reason": None,
                "next_route_recommended": None,
                "route_trace_complete": True,
                "trace_gap_reason": None,
                "query_embedding_calls": 0,
                "vector_calls": 0,
                "reranker_calls": 0,
                "exact_calls": 0,
                "fts_calls": 0,
                "l0_calls": 0,
            },
        }

    def prepare_memory_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.prepare_context(payload)


def _request() -> PrepareContextRequest:
    return PrepareContextRequest(
        query="tool result",
        active_goal="finish project",
        session_id="session-1",
        agent_id="openworker",
        profile_id="reader-lite",
        task_epoch="task-1",
        event="TOOL_RESULT",
        scope={"host_policy": "reader-lite"},
        authority="INFORMATIONAL",
        consistency="CANONICAL_REQUIRED",
        compiler_digest="a" * 64,
        router_digest="b" * 64,
        tokenizer_digest="c" * 64,
        policy_digest="d" * 64,
    )


def test_mcp_bridge_strips_server_owned_policy_fields() -> None:
    mcp = _Mcp()
    result = McpPrepareContextClient(mcp).prepare_context(_request())  # type: ignore[arg-type]

    assert result.status == "UNCHANGED"
    assert result.recall_execution_trace is not None
    assert result.recall_execution_trace.planned_route == "CACHE"
    assert result.recall_execution_trace.to_api()["planned_route"] == "CACHE"
    assert len(mcp.payloads) == 1
    payload = mcp.payloads[0]
    assert payload["query"] == "tool result"
    assert payload["event"] == "TOOL_RESULT"
    assert payload["requested_route"] == "L1"
    assert {
        "profile_id",
        "requested_scope",
        "required_authority",
        "consistency",
    }.isdisjoint(payload)


def test_target_tokenizer_counter_uses_exact_tokenizer_bytes(tmp_path: Path) -> None:
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "truncation": None,
                "padding": None,
                "added_tokens": [],
                "normalizer": None,
                "pre_tokenizer": {"type": "Whitespace"},
                "post_processor": None,
                "decoder": None,
                "model": {
                    "type": "WordLevel",
                    "vocab": {"[UNK]": 0, "hello": 1, "world": 2},
                    "unk_token": "[UNK]",
                },
            }
        ),
        encoding="utf-8",
    )
    counter = TargetTokenizerCounter(tokenizer_path)

    assert counter.count_text("hello world") == 2
    assert counter.count_tools([{"name": "hello"}]) > 0
    assert counter.tokenizer_id.startswith("tokenizer-json-sha256:")


def test_mcp_bridge_maps_transport_failure_once_to_shared_unavailable_type() -> None:
    from milai_openworker_mcp.transport import McpUnixClientError

    class FailingMcp:
        def __init__(self) -> None:
            self.calls = 0

        def prepare_memory_context(self, _payload: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1
            raise McpUnixClientError("MCP_SOCKET_UNAVAILABLE")

    mcp = FailingMcp()
    with pytest.raises(MemoryTransportUnavailableError, match="MCP_SOCKET_UNAVAILABLE"):
        McpPrepareContextClient(mcp).prepare_context(_request())  # type: ignore[arg-type]
    assert mcp.calls == 1
