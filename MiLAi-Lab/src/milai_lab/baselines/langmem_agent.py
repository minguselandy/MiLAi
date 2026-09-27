"""Fixed LangMem hot-path tools in a LangGraph ReAct agent."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.tool_node import ToolCallWrapper, ToolNode
from langgraph.store.base import BaseStore
from langgraph.store.postgres import PostgresStore
from langmem import (  # type: ignore[import-untyped]
    create_manage_memory_tool,
    create_search_memory_tool,
)

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.history import (
    HISTORY_TOOL_DESCRIPTION,
    HistoryAccess,
)
from milai_lab.methods.local_state_attention.integration import (
    make_full_history_hook,
    make_pre_model_hook,
    make_window_summary_hook,
)
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.providers.langmem_chat import VLLMChatModel

RECIPE_ID = "langmem-hotpath-react-json-action-v1"
SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the available business tools when a task requires "
    "an action, and report their actual results. You can manage and search long-term "
    "memories with the provided tools."
)
MEMORY_NAMESPACE = ("langmem", "{foundation_run_id}", "{arm_id}", "{user_id}")


@dataclass(frozen=True)
class FoundationScope:
    run_id: str
    arm_id: str
    user_id: str
    episode_id: str

    def config(self) -> dict[str, Any]:
        parts = [self.run_id, self.arm_id, self.user_id, self.episode_id]
        if not all(parts):
            raise ValueError("FOUNDATION_SCOPE_EMPTY_PART")
        thread_id = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()
        return {
            "configurable": {
                "thread_id": thread_id,
                "foundation_run_id": self.run_id,
                "arm_id": self.arm_id,
                "user_id": self.user_id,
            },
            "max_concurrency": 1,
            # The model's own counter enforces the 12-request public-message limit.
            "recursion_limit": 128,
        }


class VLLMEmbeddings(Embeddings):
    def __init__(self, client: VLLMClient, model: str) -> None:
        self.client = client
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed(texts, self.model)

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed([text], self.model)[0]


@contextmanager
def open_persistent_state(
    postgres_dsn: str,
    sqlite_path: Path,
    embeddings: Embeddings,
    *,
    embedding_dimensions: int = 1024,
) -> Iterator[tuple[BaseStore, BaseCheckpointSaver[str]]]:
    """Keep long-term Store and per-thread checkpoint in distinct durable backends."""
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with PostgresStore.from_conn_string(
        postgres_dsn,
        index={"dims": embedding_dimensions, "embed": embeddings, "fields": ["content"]},
    ) as store:
        store.setup()
        with SqliteSaver.from_conn_string(str(sqlite_path)) as saver:
            yield store, saver


def build_agent(
    model: VLLMChatModel,
    store: BaseStore | None,
    checkpointer: BaseCheckpointSaver[str],
    business_tools: Sequence[BaseTool] = (),
    business_call_wrapper: ToolCallWrapper | None = None,
    environment_rules: str = "",
    observer: ProvenanceObserver | None = None,
    memory_tools: Sequence[BaseTool] | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    local_state_controller: LocalStateController | None = None,
    local_state_read_policy: str = "focus",
    source_view_max_bytes: int | None = None,
    local_state_update_epoch: str = "pre_model",
    history_access: HistoryAccess | None = None,
    full_history: bool = False,
    history_summary_controller: HistorySummaryController | None = None,
    memory_contract: Literal["native", "strict"] = "native",
) -> Any:
    """Select the native or strict memory mutation contract for Host tools."""
    if type(memory_contract) is not str or memory_contract not in {"native", "strict"}:
        raise ValueError("LANGMEM_MEMORY_CONTRACT_UNKNOWN")
    if memory_contract == "strict" and memory_tools is not None:
        raise ValueError("LANGMEM_STRICT_CUSTOM_MEMORY_TOOLS_CONFLICT")
    selected_memory_tools: Sequence[BaseTool]
    if memory_tools is None:
        owned_manage = (create_manage_memory_tool(namespace=MEMORY_NAMESPACE)
                        if memory_contract == "native" else
                        create_strict_manage_memory_tool(namespace=MEMORY_NAMESPACE))
        selected_memory_tools = (owned_manage,
                                 create_search_memory_tool(namespace=MEMORY_NAMESPACE))
    else:
        owned_manage = None
        selected_memory_tools = memory_tools
    history_tools: list[BaseTool] = []
    if history_access is not None:
        @tool("read_history", description=HISTORY_TOOL_DESCRIPTION)
        def read_history(cursor: int = 0, max_bytes: int | None = None) -> str:
            try:
                result = history_access.page(cursor, max_bytes)
            except ValueError as error:
                if str(error) not in {"HISTORY_CURSOR_INVALID", "HISTORY_CURSOR_OUT_OF_RANGE",
                                      "HISTORY_PAGE_BUDGET_INVALID"}:
                    raise
                result = {"status": str(error), "records": []}
            return json.dumps(result, ensure_ascii=False)

        history_tools.append(read_history)
    if full_history and history_access is None:
        raise ValueError("HISTORY_ACCESS_MISSING")
    if history_summary_controller is not None and history_access is None:
        raise ValueError("HISTORY_ACCESS_MISSING")
    tools = [*selected_memory_tools, *history_tools, *business_tools]
    parameter_schemas = {
        tool.name: convert_to_openai_tool(tool)["function"]["parameters"]
        for tool in tools
    }

    def validate_then_execute(
        request: Any, execute: Any,
    ) -> Any:
        def original(current: Any) -> Any:
            call = current.tool_call
            if schema := parameter_schemas.get(call["name"]):
                try:
                    validate(call["args"], schema)
                except ValidationError as error:
                    return ToolMessage(
                        content=f"Tool input validation error: {error.message}",
                        name=call["name"],
                        tool_call_id=call["id"],
                        status="error",
                    )
            if owned_manage is not None and current.tool is owned_manage:
                action = call["args"].get("action", "create")
                memory_id = call["args"].get("id")
                if action in {"update", "delete"} and not memory_id:
                    return ToolMessage(
                        content="Tool input validation error: update and delete require an id",
                        name=call["name"], tool_call_id=call["id"], status="error")
                if action == "create" and memory_id is not None:
                    return ToolMessage(
                        content="Tool input validation error: create must omit id",
                        name=call["name"], tool_call_id=call["id"], status="error")
            if business_call_wrapper is not None:
                return business_call_wrapper(current, execute)
            return execute(current)
        return (observer.run_tool(request, original, business_call_wrapper)
                if observer is not None else original(request))

    prompt = system_prompt + ("\n" + environment_rules if environment_rules else "")
    return create_react_agent(
        model,
        tools=ToolNode(tools, wrap_tool_call=validate_then_execute),
        prompt=(prompt if local_state_controller is None and not full_history
                and history_summary_controller is None else None),
                        pre_model_hook=(make_pre_model_hook(local_state_controller, prompt,
                                            read_policy=local_state_read_policy,
                                            source_view_max_bytes=source_view_max_bytes,
                                            update_epoch=local_state_update_epoch)
                        if local_state_controller is not None else
                        make_full_history_hook(history_access, prompt)
                        if full_history and history_access is not None else
                        make_window_summary_hook(history_access,
                                                 history_summary_controller, prompt)
                        if history_access is not None
                        and history_summary_controller is not None else None),
        store=store,
        checkpointer=checkpointer,
        version="v1",
    )


def invoke_public_message(
    agent: Any,
    model: VLLMChatModel,
    scope: FoundationScope,
    content: str,
    task_id: str | None = None,
) -> list[BaseMessage]:
    """A later message in the same episode extends its checkpointed thread exactly once."""
    config = scope.config()
    snapshot = agent.get_state(config)
    public_index = sum(isinstance(item, HumanMessage)
                       for item in snapshot.values.get("messages", [])) if snapshot.values else 0
    _emit_public_context(model, scope, public_index)
    if model.observer is not None:
        model.observer.begin_public_message(scope, public_index, content)
    if model.m1 is not None:
        if task_id is None:
            raise ValueError("M1_TASK_ID_MISSING")
        model.m1.begin_public_message(scope, task_id, public_index)
    if model.odr is not None:
        model.odr.begin_public_message(scope, public_index)
    model.begin_public_message(f"{config['configurable']['thread_id']}:{public_index}")
    result = agent.invoke(
        {"messages": [HumanMessage(content=content)]},
        config=config,
    )
    if model.observer is not None:
        model.observer.assert_healthy()
    return cast(list[BaseMessage], result["messages"])


def resume_public_message(
    agent: Any, model: VLLMChatModel, scope: FoundationScope,
    task_id: str | None = None,
) -> list[BaseMessage]:
    """Continue a checkpointed public message without adding a second user message."""
    config = scope.config()
    snapshot = agent.get_state(config)
    if not snapshot.values:
        raise ValueError("PUBLIC_MESSAGE_CHECKPOINT_MISSING")
    if (model.m1 is not None or model.odr is not None
            or model.projection is not None) and not snapshot.next:
        if model.observer is not None:
            model.observer.assert_healthy()
        return cast(list[BaseMessage], snapshot.values["messages"])
    after_user = []
    for message in reversed(snapshot.values["messages"]):
        if isinstance(message, HumanMessage):
            break
        after_user.append(message)
    public_index = sum(isinstance(item, HumanMessage)
                       for item in snapshot.values["messages"]) - 1
    _emit_public_context(model, scope, public_index)
    if model.observer is not None:
        prior_user = next(message for message in reversed(snapshot.values["messages"])
                          if isinstance(message, HumanMessage))
        model.observer.begin_public_message(scope, public_index, str(prior_user.content))
    if model.m1 is not None:
        if task_id is None:
            raise ValueError("M1_TASK_ID_MISSING")
        model.m1.begin_public_message(scope, task_id, public_index)
    if model.odr is not None:
        model.odr.begin_public_message(scope, public_index)
    model.begin_public_message(
        f"{config['configurable']['thread_id']}:{public_index}",
        checkpoint_calls=sum(isinstance(message, AIMessage) for message in after_user),
    )
    if snapshot.next:
        result = agent.invoke(None, config=config)
        if model.observer is not None:
            model.observer.assert_healthy()
        return cast(list[BaseMessage], result["messages"])
    if model.observer is not None:
        model.observer.assert_healthy()
    return cast(list[BaseMessage], snapshot.values["messages"])


def _emit_public_context(
    model: VLLMChatModel, scope: FoundationScope, public_index: int,
) -> None:
    if model.client.emit is not None:
        model.client.emit({
            "event": "foundation_context",
            "run_id": scope.run_id,
            "arm_id": scope.arm_id,
            "user_id": scope.user_id,
            "episode_id": scope.episode_id,
            "public_index": public_index,
        })


def invoke_or_resume_public_message(
    agent: Any, model: VLLMChatModel, scope: FoundationScope, content: str,
    public_index: int, pending: bool, task_id: str | None = None,
) -> list[BaseMessage]:
    if pending:
        snapshot = agent.get_state(scope.config())
        prior_users = sum(isinstance(item, HumanMessage)
                          for item in snapshot.values.get("messages", [])) if snapshot.values else 0
        if prior_users >= public_index + 1:
            return resume_public_message(agent, model, scope, task_id)
    return invoke_public_message(agent, model, scope, content, task_id)
