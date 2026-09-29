"""Optional strict CRUD for the ordinary LangMem memory namespace."""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Literal, cast

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.config import get_store
from langgraph.store.base import BaseStore
from langmem import create_manage_memory_tool  # type: ignore[import-untyped]
from langmem.utils import NamespaceTemplate  # type: ignore[import-untyped]


def _receipt(call_id: str, status: str, memory_id: uuid.UUID, *, ok: bool) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"ok": ok, "status": status, "id": str(memory_id)}),
        name="manage_memory", tool_call_id=call_id,
        status="success" if ok else "error",
    )


def _invalid_receipt(call_id: str, reason: str) -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"ok": False, "status": "invalid_arguments",
                            "reason": reason}),
        name="manage_memory", tool_call_id=call_id, status="error")


def create_strict_manage_memory_tool(
    namespace: tuple[str, ...], store: BaseStore | None = None,
) -> StructuredTool:
    """Keep the native arguments while rejecting absent update/delete targets."""
    native = create_manage_memory_tool(namespace=namespace)
    namespacer = NamespaceTemplate(namespace)

    def manage_memory(
        content: str | None = None,
        action: Literal["create", "update", "delete"] = "create",
        *,
        id: uuid.UUID | None = None,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        current_store = store if store is not None else get_store()
        current_namespace = namespacer()
        if action == "create":
            if id is not None:
                return _invalid_receipt(tool_call_id, "create_must_omit_id")
            if content is None:
                return _invalid_receipt(tool_call_id, "content_required")
            memory_id = uuid.uuid4()
            current_store.put(current_namespace, str(memory_id), {"content": content})
            return _receipt(tool_call_id, "created", memory_id, ok=True)
        if id is None:
            return _invalid_receipt(tool_call_id, "target_id_required")
        if action == "update" and content is None:
            return _invalid_receipt(tool_call_id, "content_required")
        prior = current_store.get(current_namespace, str(id))
        if prior is None:
            return _receipt(tool_call_id, "not_found", id, ok=False)
        if action == "delete":
            current_store.delete(current_namespace, str(id))
            return _receipt(tool_call_id, "deleted", id, ok=True)
        if prior.value.get("content") == content:
            return _receipt(tool_call_id, "no_change", id, ok=True)
        current_store.put(current_namespace, str(id), {"content": content})
        return _receipt(tool_call_id, "updated", id, ok=True)

    async def amanage_memory(
        content: str | None = None,
        action: Literal["create", "update", "delete"] = "create",
        *,
        id: uuid.UUID | None = None,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        current_store = store if store is not None else get_store()
        current_namespace = namespacer()
        if action == "create":
            if id is not None:
                return _invalid_receipt(tool_call_id, "create_must_omit_id")
            if content is None:
                return _invalid_receipt(tool_call_id, "content_required")
            memory_id = uuid.uuid4()
            await current_store.aput(current_namespace, str(memory_id), {"content": content})
            return _receipt(tool_call_id, "created", memory_id, ok=True)
        if id is None:
            return _invalid_receipt(tool_call_id, "target_id_required")
        if action == "update" and content is None:
            return _invalid_receipt(tool_call_id, "content_required")
        prior = await current_store.aget(current_namespace, str(id))
        if prior is None:
            return _receipt(tool_call_id, "not_found", id, ok=False)
        if action == "delete":
            await current_store.adelete(current_namespace, str(id))
            return _receipt(tool_call_id, "deleted", id, ok=True)
        if prior.value.get("content") == content:
            return _receipt(tool_call_id, "no_change", id, ok=True)
        await current_store.aput(current_namespace, str(id), {"content": content})
        return _receipt(tool_call_id, "updated", id, ok=True)

    # Reuse LangMem's tool subclass so the model-visible required list stays identical.
    return cast(StructuredTool, type(native).from_function(
        manage_memory, coroutine=amanage_memory, name=native.name,
        description=(native.description + "\nCreate and update require non-null content. "
                     "Update and delete require an existing memory in this user's "
                     "namespace; an unchanged update makes no write."),
        args_schema=native.args_schema,
    ))


__all__ = [
    "Annotated",
    "BaseStore",
    "InjectedToolCallId",
    "Literal",
    "NamespaceTemplate",
    "StructuredTool",
    "ToolMessage",
    "cast",
    "create_manage_memory_tool",
    "create_strict_manage_memory_tool",
    "get_store",
    "json",
    "uuid",
]
