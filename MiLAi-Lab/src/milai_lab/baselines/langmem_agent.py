"""Fixed LangMem hot-path tools in a LangGraph ReAct agent."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
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
    store: BaseStore,
    checkpointer: BaseCheckpointSaver[str],
    business_tools: Sequence[BaseTool] = (),
    business_call_wrapper: ToolCallWrapper | None = None,
    environment_rules: str = "",
) -> Any:
    """Use upstream tool schema and instructions without a local memory policy."""
    tools = [
        create_manage_memory_tool(namespace=MEMORY_NAMESPACE),
        create_search_memory_tool(namespace=MEMORY_NAMESPACE),
        *business_tools,
    ]
    parameter_schemas = {
        tool.name: convert_to_openai_tool(tool)["function"]["parameters"]
        for tool in tools
    }

    def validate_then_execute(
        request: Any, execute: Any,
    ) -> Any:
        call = request.tool_call
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
        if business_call_wrapper is not None:
            return business_call_wrapper(request, execute)
        return execute(request)

    return create_react_agent(
        model,
        tools=ToolNode(tools, wrap_tool_call=validate_then_execute),
        prompt=SYSTEM_PROMPT + ("\n" + environment_rules if environment_rules else ""),
        store=store,
        checkpointer=checkpointer,
        version="v1",
    )


def invoke_public_message(
    agent: Any,
    model: VLLMChatModel,
    scope: FoundationScope,
    content: str,
) -> list[BaseMessage]:
    """A later message in the same episode extends its checkpointed thread exactly once."""
    config = scope.config()
    snapshot = agent.get_state(config)
    public_index = sum(isinstance(item, HumanMessage)
                       for item in snapshot.values.get("messages", [])) if snapshot.values else 0
    _emit_public_context(model, scope, public_index)
    model.begin_public_message(f"{config['configurable']['thread_id']}:{public_index}")
    result = agent.invoke(
        {"messages": [HumanMessage(content=content)]},
        config=config,
    )
    return cast(list[BaseMessage], result["messages"])


def resume_public_message(
    agent: Any, model: VLLMChatModel, scope: FoundationScope,
) -> list[BaseMessage]:
    """Continue a checkpointed public message without adding a second user message."""
    config = scope.config()
    snapshot = agent.get_state(config)
    if not snapshot.values:
        raise ValueError("PUBLIC_MESSAGE_CHECKPOINT_MISSING")
    after_user = []
    for message in reversed(snapshot.values["messages"]):
        if isinstance(message, HumanMessage):
            break
        after_user.append(message)
    public_index = sum(isinstance(item, HumanMessage)
                       for item in snapshot.values["messages"]) - 1
    _emit_public_context(model, scope, public_index)
    model.begin_public_message(
        f"{config['configurable']['thread_id']}:{public_index}",
        checkpoint_calls=sum(isinstance(message, AIMessage) for message in after_user),
    )
    if snapshot.next:
        result = agent.invoke(None, config=config)
        return cast(list[BaseMessage], result["messages"])
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
    public_index: int, pending: bool,
) -> list[BaseMessage]:
    if pending:
        snapshot = agent.get_state(scope.config())
        prior_users = sum(isinstance(item, HumanMessage)
                          for item in snapshot.values.get("messages", [])) if snapshot.values else 0
        if prior_users >= public_index + 1:
            return resume_public_message(agent, model, scope)
    return invoke_public_message(agent, model, scope, content)
