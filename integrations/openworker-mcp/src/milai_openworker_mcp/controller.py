from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from milai_client import (
    GovernedContextCompiler,
    MemoryTransportUnavailableError,
    TaskMemoryController,
)
from milai_client.models import PrepareContextEnvelope, PrepareContextRequest
from tokenizers import Tokenizer

from milai_openworker_mcp.transport import McpUnixClient, McpUnixClientError

_HOST_TOOL_FIELDS = frozenset(
    {
        "query",
        "active_goal",
        "session_id",
        "agent_id",
        "task_epoch",
        "event",
        "requested_route",
        "need_signature_id",
        "memory_need_signature",
        "state_key_ref",
        "compiler_digest",
        "router_digest",
        "tokenizer_digest",
        "policy_digest",
        "limit",
        "constraints",
        "byte_budget",
        "memory_token_budget",
        "slot_ttl_seconds",
        "budget",
        "previous_validation_token",
        "known_claim_id",
        "action_digest",
    }
)


class McpPrepareContextClient:
    """Typed bridge from the product TaskMemoryController to MCP-over-UDS."""

    def __init__(self, client: McpUnixClient) -> None:
        self._client = client

    def prepare_context(self, request: PrepareContextRequest) -> PrepareContextEnvelope:
        payload = request.to_api()
        try:
            return PrepareContextEnvelope.from_api(
                self._client.prepare_memory_context(
                    {key: value for key, value in payload.items() if key in _HOST_TOOL_FIELDS}
                )
            )
        except McpUnixClientError as exc:
            raise MemoryTransportUnavailableError(exc.code) from exc


class TargetTokenizerCounter:
    """Exact text/tool counter backed by the target model's tokenizer.json bytes."""

    def __init__(self, tokenizer_json: Path) -> None:
        raw = tokenizer_json.read_bytes()
        self._tokenizer = Tokenizer.from_buffer(raw)
        self._tokenizer_id = "tokenizer-json-sha256:" + hashlib.sha256(raw).hexdigest()

    @property
    def tokenizer_id(self) -> str:
        return self._tokenizer_id

    def count_text(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids)

    def count_tools(self, tools: Sequence[Mapping[str, object]]) -> int:
        encoded = json.dumps(list(tools), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return self.count_text(encoded)


def build_task_memory_controller(
    client: McpUnixClient,
    *,
    compiler_digest: str,
    router_digest: str,
    policy_digest: str,
    compiler: GovernedContextCompiler | None = None,
) -> TaskMemoryController:
    """Compose the shipped controller with the host-only composite MCP transport."""
    return TaskMemoryController(
        McpPrepareContextClient(client),  # type: ignore[arg-type]
        compiler=compiler,
        compiler_digest=compiler_digest,
        router_digest=router_digest,
        policy_digest=policy_digest,
    )
