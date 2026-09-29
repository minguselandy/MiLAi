"""Exact ordinary-memory reads shared by memory services and agent recipes."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from langgraph.config import get_store
from langgraph.store.base import BaseStore
from langmem.utils import NamespaceTemplate  # type: ignore[import-untyped]


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
