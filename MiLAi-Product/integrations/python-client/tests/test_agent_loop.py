from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from milai_client import (
    AgentRecallPolicy,
    AsyncAgentContext,
    CallableTokenCounter,
    ModelCallResult,
    ProviderTokenUsage,
    TokenBudget,
    run_agent_turn,
)
from milai_client.models import RecallEnvelope


class _AsyncClient:
    async def recall(self, request: Any) -> RecallEnvelope:
        assert request.consistency == "CANONICAL_REQUIRED"
        assert request.scope == {"project_ids": ["milai"]}
        assert request.authority == "ACTION_SAFE"
        assert request.limit == 5
        return RecallEnvelope.from_api(
            {
                "results": [],
                "abstained": True,
                "abstention_reason": "NO_CANDIDATE",
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-loop",
                "consistency": "CANONICAL_REQUIRED",
            }
        )


def test_generic_async_loop_recalls_before_model_and_keeps_memory_as_data() -> None:
    events: list[str] = []

    async def model(
        user_query: str,
        memory_data: str,
        tools: Sequence[dict[str, Any]],
    ) -> str:
        events.append("model")
        assert user_query == "synthetic query"
        assert 'trust="data-only"' in memory_data
        assert '"status":"ABSTAINED"' in memory_data
        assert tools == ()
        return "safe response without invented memory"

    async def run() -> None:
        events.append("recall-start")
        result = await run_agent_turn(
            client=_AsyncClient(),  # type: ignore[arg-type]
            user_query="synthetic query",
            model_call=model,
            recall_policy=AgentRecallPolicy(scope={"project_ids": ["milai"]}),
        )
        assert result.memory_status == "ABSTAINED"
        assert result.retrieval_trace_id == "trace-loop"
        assert result.memory_was_instruction is False

    asyncio.run(run())
    assert events == ["recall-start", "model"]


class _OptimizedAsyncClient:
    def __init__(self) -> None:
        self.recalls = 0

    async def recall(self, query: str, **options: Any) -> RecallEnvelope:
        self.recalls += 1
        return RecallEnvelope.from_api(
            {
                "results": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "subject_id": "project",
                        "predicate": "project.status",
                        "payload": {"value": "synthetic"},
                        "authority": "INFORMATIONAL",
                        "canonical_commit_seq": 1,
                    }
                ],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-optimized",
                "consistency": options["consistency"],
                "snapshot": {"canonical_outbox_sequence": 1},
            }
        )


def test_optimized_generic_loop_reports_tokens_and_uses_delta_without_extra_model_turn() -> None:
    async def run() -> None:
        client = _OptimizedAsyncClient()
        counter = CallableTokenCounter("chars.v1", len)
        budget = TokenBudget(
            tokenizer_id=counter.tokenizer_id,
            max_memory_tokens=1_500,
            max_tool_schema_tokens=100,
            max_total_milai_tokens=1_600,
            max_bytes=4_096,
            verified=True,
        )
        manager = AsyncAgentContext(
            client,  # type: ignore[arg-type]
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="INFORMATIONAL",
                consistency_floor="EVENTUAL",
            ),
            token_counter=counter,
            token_budget=budget,
        )
        seen_contexts: list[str] = []

        async def model(
            _user_query: str,
            memory_data: str,
            _tools: Sequence[dict[str, Any]],
        ) -> str:
            seen_contexts.append(memory_data)
            return "ok"

        tools = ({"name": "milai_recall", "description": "Recall memory"},)
        first = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="project status",
            model_call=model,
            recall_policy=manager.recall_policy,
            tool_schemas=tools,
            context_manager=manager,
            session_id="session",
        )
        assert first.context_delta_status == "REPLACE"
        assert first.recall_route == "L1"
        assert first.memory_tokens is not None
        assert first.tool_schema_tokens is not None
        assert first.token_budget_verified is True
        assert seen_contexts[-1].startswith("MILAI_CONTEXT_BEGIN\n")
        assert seen_contexts[-1].endswith("\nMILAI_CONTEXT_END")

        second = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="project status",
            model_call=model,
            recall_policy=manager.recall_policy,
            tool_schemas=tools,
            context_manager=manager,
            session_id="session",
            previous_memory_context=first.memory_context,
        )
        assert second.context_delta_status == "UNCHANGED"
        assert seen_contexts[-1] == ""
        assert second.memory_context == first.memory_context

        skipped = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="你好",
            model_call=model,
            recall_policy=manager.recall_policy,
            context_manager=manager,
            session_id="session",
            previous_memory_context=second.memory_context,
        )
        assert skipped.recall_route == "NONE"
        assert skipped.context_delta_status == "REMOVE"
        assert skipped.memory_context == ""
        assert client.recalls == 2
        assert len(seen_contexts) == 3

    asyncio.run(run())


def test_optimized_none_route_hides_only_milai_tools_and_counts_effective_catalog() -> None:
    async def run() -> None:
        client = _OptimizedAsyncClient()
        manager = AsyncAgentContext(
            client,  # type: ignore[arg-type]
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="INFORMATIONAL",
                consistency_floor="EVENTUAL",
            ),
        )
        seen: list[Sequence[dict[str, Any]]] = []

        async def model(
            _query: str,
            _memory: str,
            tools: Sequence[dict[str, Any]],
        ) -> str:
            seen.append(tools)
            return "ok"

        result = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="你好",
            model_call=model,
            recall_policy=manager.recall_policy,
            context_manager=manager,
            tool_schemas=(
                {"type": "function", "function": {"name": "milai_recall"}},
                {"type": "function", "function": {"name": "calculator"}},
            ),
        )
        assert [tool["function"]["name"] for tool in seen[0]] == ["calculator"]
        assert result.visible_tool_count == 1
        assert result.tool_schema_tokens is None
        assert client.recalls == 0

    asyncio.run(run())


def test_provider_usage_is_reported_only_from_provider_returned_counters() -> None:
    async def run() -> None:
        client = _OptimizedAsyncClient()
        manager = AsyncAgentContext(
            client,  # type: ignore[arg-type]
            recall_policy=AgentRecallPolicy(
                scope={"project_ids": ["milai"]},
                authority="INFORMATIONAL",
                consistency_floor="EVENTUAL",
            ),
        )

        async def measured_model(
            _query: str,
            _memory: str,
            _tools: Sequence[dict[str, Any]],
        ) -> ModelCallResult:
            return ModelCallResult(
                "ok",
                ProviderTokenUsage(
                    provider="synthetic-provider",
                    model_id="synthetic-model",
                    input_tokens=123,
                    cached_input_tokens=23,
                    output_tokens=7,
                    request_id="request-1",
                ),
            )

        measured = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="project status",
            model_call=measured_model,
            recall_policy=manager.recall_policy,
            context_manager=manager,
        )
        assert measured.provider_input_tokens == 123
        assert measured.provider_cached_input_tokens == 23
        assert measured.provider_output_tokens == 7
        assert measured.provider_usage_verified is True

        async def unmeasured_model(
            _query: str,
            _memory: str,
            _tools: Sequence[dict[str, Any]],
        ) -> str:
            return "ok"

        unmeasured = await run_agent_turn(
            client=client,  # type: ignore[arg-type]
            user_query="你好",
            model_call=unmeasured_model,
            recall_policy=manager.recall_policy,
            context_manager=manager,
        )
        assert unmeasured.provider_input_tokens is None
        assert unmeasured.provider_usage_verified is False

    asyncio.run(run())
