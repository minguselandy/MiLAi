"""Fixed LangMem hot-path tools in a LangGraph ReAct agent."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool, tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.config import get_store
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.tool_node import ToolCallWrapper, ToolNode
from langgraph.store.base import BaseStore
from langgraph.store.postgres import PostgresStore
from langmem import (  # type: ignore[import-untyped]
    create_manage_memory_tool,
    create_search_memory_tool,
)
from langmem.utils import NamespaceTemplate  # type: ignore[import-untyped]

from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool
from milai_lab.methods.local_state_attention.controller import LocalStateController
from milai_lab.methods.local_state_attention.history import (
    HISTORY_TOOL_DESCRIPTION,
    HistoryAccess,
)
from milai_lab.methods.local_state_attention.integration import (
    make_full_history_hook,
    make_persistent_memory_hook,
    make_pre_model_hook,
    make_window_summary_hook,
    make_writer_view_hook,
)
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.methods.memory_boundaries import MemoryBoundaryView
from milai_lab.methods.memory_result import CORRECTION_TOOLS, correction_marker
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.providers.langmem_chat import VLLMChatModel

if TYPE_CHECKING:
    from milai_lab.baselines.langmem_mcp import MemoryMCP
    from milai_lab.methods.local_state_attention.writers import WriterTools

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


def create_history_read_tool(history: HistoryAccess | None) -> BaseTool:
    """One shared history tool; None permits schema inspection without reading history."""
    @tool("read_history", description=HISTORY_TOOL_DESCRIPTION)
    def read_history(cursor: int = 0, max_bytes: int | None = None) -> str:
        if history is None:
            raise ValueError("HISTORY_ACCESS_MISSING")
        try:
            result = history.page(cursor, max_bytes)
        except ValueError as error:
            if str(error) not in {"HISTORY_CURSOR_INVALID", "HISTORY_CURSOR_OUT_OF_RANGE",
                                  "HISTORY_PAGE_BUDGET_INVALID"}:
                raise
            result = {"status": str(error), "records": []}
        return json.dumps(result, ensure_ascii=False)

    return read_history


def create_memory_read_tool(namespace: tuple[str, ...], store: BaseStore | None = None,
                            ) -> BaseTool:
    """Exact ordinary-memory READ with the same public namespace contract as CRUD."""
    namespacer = NamespaceTemplate(namespace)

    def receipt(row: Any, memory_id: uuid.UUID, call_id: str) -> ToolMessage:
        return ToolMessage(name="read_memory", tool_call_id=call_id,
            status="success" if row is not None else "error",
            content=json.dumps({"ok": row is not None,
                                "status": "found" if row is not None else "not_found",
                                "id": str(memory_id),
                                **({"value": row.value} if row is not None else {})},
                               ensure_ascii=False))

    def read_memory(id: uuid.UUID, *,
                    tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        current = store if store is not None else get_store()
        return receipt(current.get(namespacer(), str(id)), id, tool_call_id)

    async def aread_memory(id: uuid.UUID, *,
                          tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        current = store if store is not None else get_store()
        return receipt(await current.aget(namespacer(), str(id)), id, tool_call_id)

    return StructuredTool.from_function(read_memory, coroutine=aread_memory,
        name="read_memory", description="Read one ordinary memory by its exact id in this "
                                        "user's namespace. This makes no write.")


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
    writer_tools: WriterTools | None = None,
    writer_tool_mode: Literal["full", "read_only", "memory_only"] = "full",
    writer_maintenance_trigger: BaseTool | None = None,
    writer_view_bank: Any = None,
    writer_known_prefix_messages: int = 0,
    writer_initial_boundary: dict[str, Any] | None = None,
    writer_history_projection: bool = False,
    writer_state_body_prefill: Literal["all", "none"] = "all",
    persistent_memory_arm: Literal["B0", "B1", "C"] | None = None,
    persistent_memory_records: Callable[[RunnableConfig], list[dict[str, Any]]] | None = None,
    memory_boundaries: MemoryBoundaryView | None = None,
    memory_mcp: MemoryMCP | None = None,
) -> Any:
    """Select the native or strict memory mutation contract for Host tools."""
    if type(memory_contract) is not str or memory_contract not in {"native", "strict"}:
        raise ValueError("LANGMEM_MEMORY_CONTRACT_UNKNOWN")
    if memory_contract == "strict" and memory_tools is not None:
        raise ValueError("LANGMEM_STRICT_CUSTOM_MEMORY_TOOLS_CONFLICT")
    if memory_mcp is not None and (memory_contract != "strict" or memory_tools is not None
            or memory_mcp.store is not store or writer_tools is not None
            or local_state_controller is not None or history_summary_controller is not None
            or (history_access is not None) != ("read_history" in memory_mcp.local_tools)):
        raise ValueError("LANGMEM_MCP_TOOLSET_CONFLICT")
    if writer_tools is not None and (
        memory_contract != "strict" or memory_tools is not None
        or writer_tools.memory_namespace != MEMORY_NAMESPACE
        or writer_tools.bank.store is not store
    ):
        raise ValueError("LANGMEM_WRITER_TOOLSET_CONFLICT")
    if writer_tool_mode not in {"full", "read_only", "memory_only"} or (
        writer_tools is None and (writer_tool_mode != "full"
                                  or writer_maintenance_trigger is not None)
    ) or (writer_tool_mode != "read_only" and writer_maintenance_trigger is not None):
        raise ValueError("LANGMEM_WRITER_TOOL_MODE_INVALID")
    if writer_view_bank is not None and (
        writer_tools is None or writer_view_bank is not writer_tools.bank
        or local_state_controller is not None or full_history
        or history_summary_controller is not None
    ):
        raise ValueError("LANGMEM_WRITER_VIEW_CONFLICT")
    if (type(writer_state_body_prefill) is not str
            or writer_state_body_prefill not in {"all", "none"}
            or (writer_state_body_prefill != "all" and writer_view_bank is None)
            or type(writer_history_projection) is not bool
            or (writer_history_projection and (
                writer_view_bank is None or history_access is None))):
        raise ValueError("LANGMEM_WRITER_HISTORY_VIEW_INVALID")
    if persistent_memory_arm is not None and (
        persistent_memory_arm not in {"B0", "B1", "C"} or memory_contract != "strict"
        or store is None or persistent_memory_records is None or writer_tools is not None
        or local_state_controller is not None or history_summary_controller is not None
        or model.m1 is not None or model.odr is not None or model.projection is not None
    ):
        raise ValueError("PERSISTENT_MEMORY_RECIPE_CONFLICT")
    if persistent_memory_arm is None and persistent_memory_records is not None:
        raise ValueError("PERSISTENT_MEMORY_RECIPE_CONFLICT")
    if memory_boundaries is not None and (
        persistent_memory_arm != "B0" or (model.request_view is not None
                                         and not isinstance(model.request_view, MemoryBoundaryView))
    ):
        raise ValueError("MEMORY_BOUNDARY_RECIPE_CONFLICT")
    if persistent_memory_arm is not None:
        model.memory_protocol = persistent_memory_arm
    selected_memory_tools: Sequence[BaseTool]
    if memory_mcp is not None:
        owned_manage = None
        selected_memory_tools = memory_mcp.tools
    elif writer_tools is not None:
        owned_manage = writer_tools.manage_memory
        selected_memory_tools = ((writer_tools.search_memory,) if writer_tool_mode ==
                                 "read_only" else
                                 (owned_manage, writer_tools.search_memory))
    elif memory_tools is None:
        owned_manage = (create_manage_memory_tool(namespace=MEMORY_NAMESPACE)
                        if memory_contract == "native" else
                        create_strict_manage_memory_tool(namespace=MEMORY_NAMESPACE))
        selected_memory_tools = (owned_manage,
                                 create_search_memory_tool(namespace=MEMORY_NAMESPACE))
    else:
        owned_manage = None
        selected_memory_tools = memory_tools
    history_tools: list[BaseTool] = []
    if history_access is not None and memory_mcp is None:
        history_tools.append(create_history_read_tool(history_access))
    if full_history and history_access is None:
        raise ValueError("HISTORY_ACCESS_MISSING")
    if history_summary_controller is not None and history_access is None:
        raise ValueError("HISTORY_ACCESS_MISSING")
    writer_extra = (
        [writer_tools.manage_state, writer_tools.read_record]
        if writer_tools is not None and writer_tool_mode == "full" else
        [writer_tools.read_record, *([writer_maintenance_trigger]
                                    if writer_maintenance_trigger is not None else [])]
        if writer_tools is not None else [])
    ordinary_read = ([create_memory_read_tool(MEMORY_NAMESPACE, store)]
                     if persistent_memory_arm is not None and memory_mcp is None else [])
    tools = [*selected_memory_tools, *ordinary_read, *history_tools, *writer_extra, *business_tools]
    parameter_schemas = {
        tool.name: convert_to_openai_tool(tool)["function"]["parameters"]
        for tool in tools
    }

    def validate_then_execute(
        request: Any, execute: Any,
    ) -> Any:
        def original(current: Any) -> Any:
            call = current.tool_call
            if model.research_profile is not None and current.runtime.config.get(
                "max_concurrency"
            ) != 1:
                raise ValueError("PROTOCOL_PROFILE_TOOL_CONCURRENCY_UNSUPPORTED")
            if persistent_memory_arm == "C" and correction_marker([
                row.model_dump(mode="json") for row in current.state["messages"]
            ], model.active_message_key or "") is not None and call["name"] not in CORRECTION_TOOLS:
                return ToolMessage(content="Tool unavailable during memory-only correction",
                    name=call["name"], tool_call_id=call["id"], status="error")
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
        result = (observer.run_tool(request, original, business_call_wrapper)
                  if observer is not None else original(request))
        if memory_boundaries is not None and isinstance(result, ToolMessage):
            memory_boundaries.observe_receipt(result, model.memory_turn)
        return result

    prompt = system_prompt + ("\n" + environment_rules if environment_rules else "")
    return create_react_agent(
        model,
        tools=ToolNode(tools, wrap_tool_call=validate_then_execute),
        prompt=(prompt if persistent_memory_arm is None
                and local_state_controller is None and not full_history
                and history_summary_controller is None and writer_view_bank is None
                else None),
                        pre_model_hook=(make_persistent_memory_hook(
                            prompt, persistent_memory_records,
                            history=history_access if full_history else None,
                            emit=model.client.emit, boundary_view=memory_boundaries, model=model)
                        if persistent_memory_arm is not None
                        and persistent_memory_records is not None else
                        make_pre_model_hook(local_state_controller, prompt,
                                            read_policy=local_state_read_policy,
                                            source_view_max_bytes=source_view_max_bytes,
                                            update_epoch=local_state_update_epoch)
                        if local_state_controller is not None else
                        make_full_history_hook(history_access, prompt)
                        if full_history and history_access is not None else
                        make_window_summary_hook(history_access,
                                                 history_summary_controller, prompt)
                        if history_access is not None
                        and history_summary_controller is not None else
                        make_writer_view_hook(
                            writer_tools, prompt,
                            source_view_max_bytes=source_view_max_bytes,
                            known_prefix_messages=writer_known_prefix_messages,
                            initial_boundary=writer_initial_boundary,
                            history=(history_access if writer_history_projection else None),
                            state_body_prefill=writer_state_body_prefill,
                            emit=model.client.emit)
                        if writer_view_bank is not None else None),
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
    _set_memory_turn(model, scope, public_index)
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
    return _finalize_memory_result(agent, model, scope,
                                   cast(list[BaseMessage], result["messages"]))


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
    _set_memory_turn(model, scope, public_index)
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
        return _finalize_memory_result(agent, model, scope,
                                       cast(list[BaseMessage], result["messages"]))
    if model.observer is not None:
        model.observer.assert_healthy()
    return _finalize_memory_result(agent, model, scope,
                                   cast(list[BaseMessage], snapshot.values["messages"]))


def _set_memory_turn(model: VLLMChatModel, scope: FoundationScope, public_index: int) -> None:
    if model.memory_protocol is not None:
        model.memory_turn = {"run_id": scope.run_id, "arm_id": scope.arm_id,
                             "user_id": scope.user_id, "message_key":
                             f"{scope.config()['configurable']['thread_id']}:{public_index}"}


def _finalize_memory_result(agent: Any, model: VLLMChatModel, scope: FoundationScope,
                            messages: list[BaseMessage]) -> list[BaseMessage]:
    if model.memory_protocol != "C" or not messages or not isinstance(messages[-1], AIMessage):
        return messages
    final = messages[-1]
    verification = final.response_metadata.get("memory_result_verification")
    if not isinstance(verification, dict):
        return messages
    key = model.active_message_key or ""
    marker = correction_marker([row.model_dump(mode="json") for row in messages], key)
    emit = model.client.emit
    entered = marker is not None
    capacity = model.calls_in_message < model.max_calls_per_message
    if emit is not None:
        emit({"event": "memory_result_verification", "message_key": key,
              "generation_id": final.id, "memory_result": final.response_metadata.get(
                  "memory_result"), "verification": verification,
              "correction_already_entered": entered, "remaining_host_calls":
              model.max_calls_per_message - model.calls_in_message})
    if not verification["needs_correction"] or entered or not capacity:
        if verification["needs_correction"] and emit is not None:
            emit({"event": "memory_result_correction", "message_key": key,
                  "status": "EXHAUSTED" if entered else "NO_REMAINING_CAPACITY"})
        return messages
    metadata = {**final.response_metadata, "memory_correction": {
        "message_key": key, "memory_result": final.response_metadata.get("memory_result"),
        "verification": verification}}
    marked = final.model_copy(update={"response_metadata": metadata})
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    agent.update_state(scope.config(), {"messages": [marked]}, as_node="tools")
    if emit is not None:
        emit({"event": "memory_result_correction", "message_key": key, "status": "ENTERED",
              "checkpoint_writes": 1,
              "logical_bytes": len(marked.model_dump_json().encode("utf-8")),
              "wall_ns": time.perf_counter_ns() - start_wall,
              "cpu_ns": time.process_time_ns() - start_cpu})
    result = agent.invoke(None, config=scope.config())
    if model.observer is not None:
        model.observer.assert_healthy()
    return _finalize_memory_result(agent, model, scope,
                                   cast(list[BaseMessage], result["messages"]))


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
