"""Scoped memory and State tools shared by Host and explicit writer proposals."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Literal, cast

from jsonschema import FormatChecker, ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_config
from langmem import create_search_memory_tool  # type: ignore[import-untyped]
from langmem.utils import NamespaceTemplate  # type: ignore[import-untyped]

from milai_lab.baselines.langmem_strict_tools import create_strict_manage_memory_tool
from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope


@dataclass(frozen=True)
class WriterTools:
    bank: LocalStateBank
    memory_namespace: tuple[str, ...]
    manage_memory: BaseTool
    search_memory: BaseTool
    manage_state: BaseTool
    read_record: BaseTool

    def host_tools(self) -> tuple[BaseTool, ...]:
        return (self.manage_memory, self.search_memory,
                self.manage_state, self.read_record)


@dataclass(frozen=True)
class WriterProposalContext:
    scope: StateScope
    message_key: str
    current_task: str = ""


@dataclass(frozen=True)
class WriterExecution:
    status: Literal["NO_CHANGE", "APPLIED", "PARTIAL_REJECTED"]
    receipts: list[ToolMessage]
    pending_event_ids: list[str]


@dataclass(frozen=True)
class _StateWriteContext:
    batch_id: str
    event_ids: frozenset[str]
    slot: int
    query_source_id: str | None


_STATE_WRITE: ContextVar[_StateWriteContext | None] = ContextVar(
    "lsa_state_writer_batch", default=None)


def _scope(config: RunnableConfig | None = None) -> StateScope:
    values = (config if config is not None else get_config()).get("configurable", {})
    parts = [values.get(key) for key in ("foundation_run_id", "arm_id", "user_id")]
    workspace = values.get("workspace_id", "default")
    if any(not isinstance(value, str) or not value for value in [*parts, workspace]):
        raise ValueError("LSA_WRITER_SCOPE_INVALID")
    return StateScope(cast(str, parts[0]), cast(str, parts[1]),
                      cast(str, parts[2]), cast(str, workspace))


def _receipt(call_id: str, name: str, *, ok: bool, status: str,
             **fields: Any) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"ok": ok, "status": status, **fields}, ensure_ascii=False),
        name=name, tool_call_id=call_id, status="success" if ok else "error")


def create_writer_tools(bank: LocalStateBank,
                        memory_namespace: tuple[str, ...]) -> WriterTools:
    """Build one toolset; the memory mutator is the exact C2 strict tool."""
    namespacer = NamespaceTemplate(memory_namespace)

    def manage_state(
        action: Literal["create", "update", "delete"],
        id: str | None = None,
        title: str | None = None,
        content: str | None = None,
        needs: list[str] | None = None,
        evidence: list[str] | None = None,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        scope = _scope()
        context = _STATE_WRITE.get()
        if action == "delete":
            if not id or any(value is not None for value in
                             (title, content, needs, evidence)):
                return _receipt(tool_call_id, "manage_state", ok=False,
                                status="invalid_arguments")
            deleted = bank.delete_state(scope, id)
            return _receipt(tool_call_id, "manage_state", ok=deleted,
                            status="deleted" if deleted else "not_found", id=id)
        if (action == "create" and id is not None) or (action == "update" and not id):
            return _receipt(tool_call_id, "manage_state", ok=False,
                            status="invalid_arguments")
        edit: dict[str, Any] = {"id": id, "content": content}
        if title is not None:
            edit["title"] = title
        if needs is not None:
            edit["needs"] = needs
        if evidence is not None:
            edit["evidence"] = evidence
        receipts, invalid = bank.apply(
            scope, [edit], set(context.event_ids) if context else set(),
            query_source_id=context.query_source_id if context else None,
            batch_id=context.batch_id if context else None,
            edit_slots=[context.slot] if context else None,
            ack_events=False)
        result = receipts[0]
        if invalid:
            return _receipt(tool_call_id, "manage_state", ok=False,
                            status="invalid_edit", id=id, reason=result.get("reason"))
        return _receipt(tool_call_id, "manage_state", ok=True,
                        status=result["status"], id=result["id"],
                        revision=result["revision"],
                        replayed=result.get("replayed", False))

    def read_record(
        target_kind: Literal["memory", "state"], id: str,
        *, tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        scope = _scope()
        if target_kind == "state":
            row = bank.state(scope, id)
            if row is None:
                return _receipt(tool_call_id, "read_record", ok=False,
                                status="not_found", target_kind="state", id=id)
            public = {key: row[key] for key in (
                "id", "title", "content", "needs", "evidence_refs",
                "revision", "archived")}
            return _receipt(tool_call_id, "read_record", ok=True,
                            status="found", target_kind="state", record=public)
        try:
            memory_id = str(uuid.UUID(id))
        except ValueError:
            return _receipt(tool_call_id, "read_record", ok=False,
                            status="invalid_id", target_kind="memory", id=id)
        memory_row = bank.store.get(namespacer(), memory_id)
        if memory_row is None:
            return _receipt(tool_call_id, "read_record", ok=False,
                            status="not_found", target_kind="memory", id=memory_id)
        return _receipt(tool_call_id, "read_record", ok=True,
                        status="found", target_kind="memory", id=memory_id,
                        value=memory_row.value)

    state_tool = StructuredTool.from_function(
        manage_state, name="manage_state",
        description=("Create, update, or delete one scoped local State. Create omits id and "
                     "requires title and content; update requires an existing id and content; "
                     "delete requires an existing id. Evidence cites actual source ids."))
    read_tool = StructuredTool.from_function(
        read_record, name="read_record",
        description="Read one existing memory or State by its exact scoped id.")
    return WriterTools(
        bank=bank, memory_namespace=memory_namespace,
        manage_memory=create_strict_manage_memory_tool(memory_namespace, bank.store),
        search_memory=create_search_memory_tool(namespace=memory_namespace,
                                                store=bank.store),
        manage_state=state_tool, read_record=read_tool)


def execute_writes(
    toolset: WriterTools, calls: Sequence[dict[str, Any]], *,
    config: RunnableConfig, scope: StateScope, batch_id: str,
    event_ids: set[str], query_source_id: str | None = None,
    ack_events: bool = True,
) -> WriterExecution:
    """Execute in order; optionally acknowledge after all receipts succeed."""
    if not isinstance(batch_id, str) or not batch_id:
        raise ValueError("LSA_WRITER_BATCH_ID_MISSING")
    if _scope(config) != scope:
        raise ValueError("LSA_WRITER_SCOPE_MISMATCH")
    available = {row["id"] for row in toolset.bank.events(scope)}
    if not event_ids <= available or (query_source_id is not None
                                      and query_source_id not in available):
        raise ValueError("LSA_WRITER_SOURCE_IDS_UNAVAILABLE")
    tools = {tool.name: tool for tool in toolset.host_tools()}
    schemas = {name: convert_to_openai_tool(tool)["function"]["parameters"]
               for name, tool in tools.items()}
    receipts: list[ToolMessage] = []
    for slot, call in enumerate(calls):
        name, arguments = ((call.get("name"), call.get("arguments"))
                           if isinstance(call, dict) else (None, None))
        call_id = f"{batch_id}:tool:{slot}"
        if not isinstance(name, str) or name not in tools or not isinstance(arguments, dict):
            receipts.append(_receipt(call_id, str(name), ok=False,
                                     status="invalid_call"))
            continue
        try:
            validate(arguments, schemas[name], format_checker=FormatChecker())
        except ValidationError as error:
            receipts.append(ToolMessage(
                content=f"Tool input validation error: {error.message}",
                name=name, tool_call_id=call_id, status="error"))
            continue
        token = _STATE_WRITE.set(_StateWriteContext(
            batch_id, frozenset(event_ids), slot, query_source_id))
        try:
            result = tools[name].invoke({"type": "tool_call", "name": name,
                                         "args": arguments, "id": call_id}, config=config)
        finally:
            _STATE_WRITE.reset(token)
        if not isinstance(result, ToolMessage):
            raise TypeError("LSA_WRITER_NON_TOOL_RECEIPT")
        receipts.append(result)
    failed = any(row.status == "error" for row in receipts)
    if not failed and ack_events:
        toolset.bank.acknowledge_events(scope, event_ids)
    return WriterExecution(
        "PARTIAL_REJECTED" if failed else "NO_CHANGE" if not calls else "APPLIED",
        receipts, [row["id"] for row in toolset.bank.pending(scope)])
