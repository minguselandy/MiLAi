from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from milai_client.async_context import AsyncAgentContext
from milai_client.client import AsyncMilaiClient
from milai_client.formatting import format_memory_for_prompt
from milai_client.models import AgentRecallPolicy, RecallRequest
from milai_client.optimization import ModelCallResult, ProviderTokenUsage, measure_tool_schemas

ModelCall = Callable[[str, str, Sequence[dict[str, Any]]], Awaitable[str | ModelCallResult]]


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    answer: str
    memory_status: str
    retrieval_trace_id: str | None
    open_issue_ids: tuple[str, ...]
    memory_was_instruction: bool = False
    recall_route: str = "L1"
    context_delta_status: str = "LEGACY_REPLACE"
    memory_tokens: int | None = None
    tool_schema_tokens: int | None = None
    token_budget_verified: bool = False
    memory_context: str = ""
    visible_tool_count: int = 0
    provider_input_tokens: int | None = None
    provider_cached_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    provider_usage_verified: bool = False


async def run_agent_turn(
    *,
    client: AsyncMilaiClient,
    user_query: str,
    model_call: ModelCall,
    recall_policy: AgentRecallPolicy,
    tool_schemas: Sequence[dict[str, Any]] = (),
    context_manager: AsyncAgentContext | None = None,
    session_id: str = "generic-default",
    active_goal: str | None = None,
    context_constraints: tuple[str, ...] = (),
    previous_memory_context: str = "",
    persistent_memory_slot: bool = True,
    dynamic_milai_tools: bool = True,
) -> AgentTurnResult:
    """Framework-neutral mandatory pre-model recall; never performs implicit writes."""
    if context_manager is not None:
        prepared = await context_manager.prepare(
            user_query,
            session_id=session_id,
            active_goal=active_goal,
            context_constraints=context_constraints,
        )
        delta = prepared.compiled.delta
        if delta.status == "REPLACE" and delta.rendered_context is None:
            raise RuntimeError("REPLACE delta returned no rendered context")
        active_context = (
            delta.rendered_context or ""
            if delta.status == "REPLACE"
            else (previous_memory_context if delta.status == "UNCHANGED" else "")
        )
        model_context = (
            "" if delta.status == "UNCHANGED" and persistent_memory_slot else active_context
        )
        effective_tools = _tools_for_route(
            tool_schemas,
            prepared.routing.route,
            dynamic=dynamic_milai_tools,
        )
        tool_usage = measure_tool_schemas(effective_tools, context_manager.token_counter)
        budget = context_manager.token_budget
        if (
            budget is not None
            and budget.max_tool_schema_tokens is not None
            and tool_usage.actual_tokens is not None
            and tool_usage.actual_tokens > budget.max_tool_schema_tokens
        ):
            raise ValueError("TOOL_SCHEMA_BUDGET_INFEASIBLE")
        memory_tokens = prepared.compiled.metrics.actual_tokens
        if (
            budget is not None
            and budget.max_total_milai_tokens is not None
            and memory_tokens is not None
            and tool_usage.actual_tokens is not None
            and memory_tokens + tool_usage.actual_tokens > budget.max_total_milai_tokens
        ):
            raise ValueError("TOTAL_MILAI_BUDGET_INFEASIBLE")
        model_result = await model_call(user_query, model_context, effective_tools)
        answer, provider_usage = _model_output(model_result)
        envelope = prepared.recall_envelope
        return AgentTurnResult(
            answer=answer,
            memory_status=envelope.status if envelope is not None else "SKIPPED",
            retrieval_trace_id=envelope.trace_id if envelope is not None else None,
            open_issue_ids=tuple(envelope.issues) if envelope is not None else (),
            recall_route=prepared.routing.route,
            context_delta_status=delta.status,
            memory_tokens=memory_tokens,
            tool_schema_tokens=tool_usage.actual_tokens,
            token_budget_verified=(
                prepared.compiled.metrics.token_budget_verified and tool_usage.verified
            ),
            memory_context=active_context,
            visible_tool_count=len(effective_tools),
            provider_input_tokens=(
                provider_usage.input_tokens if provider_usage is not None else None
            ),
            provider_cached_input_tokens=(
                provider_usage.cached_input_tokens if provider_usage is not None else None
            ),
            provider_output_tokens=(
                provider_usage.output_tokens if provider_usage is not None else None
            ),
            provider_usage_verified=provider_usage is not None,
        )
    memory = await client.recall(
        RecallRequest(
            query=user_query,
            scope=recall_policy.scope,
            authority=recall_policy.authority,
            consistency=recall_policy.consistency_floor,
            limit=recall_policy.max_limit,
        )
    )
    data_block = format_memory_for_prompt(memory)
    model_result = await model_call(user_query, data_block, tuple(tool_schemas))
    answer, provider_usage = _model_output(model_result)
    return AgentTurnResult(
        answer=answer,
        memory_status=memory.status,
        retrieval_trace_id=memory.trace_id,
        open_issue_ids=tuple(memory.issues),
        memory_context=data_block,
        visible_tool_count=len(tool_schemas),
        provider_input_tokens=(provider_usage.input_tokens if provider_usage is not None else None),
        provider_cached_input_tokens=(
            provider_usage.cached_input_tokens if provider_usage is not None else None
        ),
        provider_output_tokens=(
            provider_usage.output_tokens if provider_usage is not None else None
        ),
        provider_usage_verified=provider_usage is not None,
    )


def _model_output(value: str | ModelCallResult) -> tuple[str, ProviderTokenUsage | None]:
    if isinstance(value, ModelCallResult):
        return value.text, value.usage
    return value, None


def _tools_for_route(
    tools: Sequence[dict[str, Any]],
    route: str,
    *,
    dynamic: bool,
) -> tuple[dict[str, Any], ...]:
    values = tuple(tools)
    if not dynamic or route not in {"NONE", "CACHE"}:
        return values
    return tuple(tool for tool in values if not _tool_name(tool).startswith("milai_"))


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function")
    function_name = function.get("name") if isinstance(function, dict) else None
    if isinstance(function_name, str):
        return function_name
    name = tool.get("name")
    return name if isinstance(name, str) else ""
