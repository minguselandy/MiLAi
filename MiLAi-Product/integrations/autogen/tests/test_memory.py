from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from autogen_core.memory import MemoryContent
from autogen_core.model_context import BufferedChatCompletionContext, UnboundedChatCompletionContext
from autogen_core.models import UserMessage
from milai_client import AgentRecallPolicy, CallableTokenCounter, TokenBudget
from milai_client.models import EvidenceReceipt, RecallEnvelope

from milai_autogen import MilaiMemory


class _AsyncClient:
    def __init__(self) -> None:
        self.captures: list[tuple[Any, str]] = []
        self.recalls: list[tuple[str, dict[str, Any]]] = []
        self.exact_recalls: list[Any] = []
        self.closed = False

    async def recall(self, query: str, **options: Any) -> RecallEnvelope:
        self.recalls.append((query, options))
        return RecallEnvelope.from_api(
            {
                "results": [{"claim_id": "c1", "payload": {"value": "synthetic"}}],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-1",
                "consistency": options["consistency"],
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    async def system_watermarks(self) -> Any:
        return SimpleNamespace(canonical_snapshot=7)

    async def recall_exact(self, request: Any) -> RecallEnvelope:
        self.exact_recalls.append(request)
        return RecallEnvelope.from_api(
            {
                "results": [{"claim_id": request.claim_id, "payload": {"value": "synthetic"}}],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-exact",
                "consistency": request.consistency,
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    async def list_open_issues(self, status: str | None = None) -> list[Any]:
        return []

    async def capture_evidence(self, payload: Any, *, operation_id: str) -> EvidenceReceipt:
        self.captures.append((payload, operation_id))
        return EvidenceReceipt("e1", "b1", "o1", False, {"evidence_id": "e1"})

    async def close(self) -> None:
        self.closed = True


def test_official_autogen_memory_query_and_update_context_use_data_message() -> None:
    async def run() -> None:
        client = _AsyncClient()
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(scope={"project_ids": ["milai"]}),
        )
        context = BufferedChatCompletionContext(buffer_size=10)
        await context.add_message(UserMessage(content="query", source="user"))
        result = await memory.update_context(context)
        assert result.memories.results[0].metadata["trace_id"] == "trace-1"
        messages = await context.get_messages()
        assert messages[-1].source == "milai-memory-data"
        assert "RULE=data_only preserve_authority_scope_uncertainty" in str(
            messages[-1].content
        )
        assert client.recalls == [
            (
                "query",
                {
                    "requested_scope": {"project_ids": ["milai"]},
                    "required_authority": "ACTION_SAFE",
                    "consistency": "CANONICAL_REQUIRED",
                    "limit": 3,
                },
            )
        ]

    asyncio.run(run())


def test_add_requires_confirmation_redaction_and_never_accepts_model_output() -> None:
    async def run() -> None:
        client = _AsyncClient()
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(scope={"project_ids": ["milai"]}),
        )
        with pytest.raises(PermissionError, match="model"):
            await memory.add(
                MemoryContent(
                    content="model answer", mime_type="text/plain", metadata={"source": "model"}
                )
            )
        with pytest.raises(PermissionError, match="sensitive"):
            await memory.add(
                MemoryContent(
                    content="password=hunter2",
                    mime_type="text/plain",
                    metadata={
                        "source": "user",
                        "capture_confirmed": True,
                        "redaction_status": "SAFE",
                    },
                )
            )
        await memory.add(
            MemoryContent(
                content="synthetic preference",
                mime_type="text/plain",
                metadata={
                    "source": "user",
                    "capture_confirmed": True,
                    "redaction_status": "SAFE",
                    "source_ref": "session:1/turn:1",
                    "subject_id": "subject",
                    "observed_at": "2026-08-17T00:00:00Z",
                    "operation_id": "stable-operation",
                    "permission_snapshot": {"scope": "local"},
                    "source_context": {
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "turn_ordinal": 1,
                        "round_id": "round-1",
                        "round_ordinal": 1,
                    },
                },
            )
        )
        assert client.captures[0][1] == "stable-operation"
        assert client.captures[0][0].speaker == "user"
        assert client.captures[0][0].source_context.turn_id == "turn-1"
        assert memory.last_write_receipt == {"evidence_id": "e1"}
        await memory.close()
        assert client.closed is True

    asyncio.run(run())


def test_query_cannot_override_host_scope_authority_consistency_or_limit() -> None:
    async def run() -> None:
        client = _AsyncClient()
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="ACTION_SAFE",
                consistency_floor="CANONICAL_REQUIRED",
                max_limit=5,
            ),
        )
        with pytest.raises(PermissionError, match="cannot override"):
            await memory.query(
                "synthetic",
                scope={"project_ids": ["all"]},
                authority="USER_CONFIRMED",
                consistency="EVENTUAL",
                limit=20,
            )
        assert client.recalls == []

    asyncio.run(run())


def test_query_typed_claim_uuid_uses_exact_transport() -> None:
    async def run() -> None:
        client = _AsyncClient()
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(scope={"project_ids": ["milai"]}),
        )
        claim_id = "11111111-1111-4111-8111-111111111111"
        result = await memory.query(f"read Claim {claim_id}")
        assert result.results
        assert client.exact_recalls[0].claim_id == claim_id
        assert client.recalls == []

    asyncio.run(run())


def test_update_context_cache_is_bound_to_current_host_policy() -> None:
    async def run() -> None:
        client = _AsyncClient()
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="INFORMATIONAL",
                consistency_floor="EVENTUAL",
            ),
        )
        context = UnboundedChatCompletionContext()
        await context.add_message(UserMessage(content="project status", source="user"))
        await memory.update_context(context)
        memory.recall_policy = AgentRecallPolicy(
            scope={"project_ids": ["other"]},
            authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
        )
        await memory.update_context(context)
        assert len(client.recalls) == 2

    asyncio.run(run())


def test_500_updates_replace_one_slot_then_none_route_removes_it() -> None:
    async def run() -> None:
        client = _AsyncClient()
        counter = CallableTokenCounter("chars.v1", len)
        memory = MilaiMemory(  # type: ignore[arg-type]
            client,
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="INFORMATIONAL",
                consistency_floor="EVENTUAL",
            ),
            token_counter=counter,
            token_budget=TokenBudget(
                tokenizer_id=counter.tokenizer_id,
                max_memory_tokens=1_600,
                max_bytes=4_096,
                verified=True,
            ),
        )
        context = UnboundedChatCompletionContext()
        await context.add_message(UserMessage(content="project status", source="user"))
        for _ in range(500):
            await memory.update_context(context)
        messages = await context.get_messages()
        assert len(messages) == 2
        assert sum(message.source == "milai-memory-data" for message in messages) == 1
        assert len(memory.slot_registry) == 1
        assert len(client.recalls) == 1

        await context.add_message(UserMessage(content="你好", source="user"))
        removed = await memory.update_context(context)
        assert removed.memories.results == []
        messages = await context.get_messages()
        assert len(messages) == 2
        assert all(message.source != "milai-memory-data" for message in messages)
        assert len(memory.slot_registry) == 0
        assert len(client.recalls) == 1

    asyncio.run(run())
