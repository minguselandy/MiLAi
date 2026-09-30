"""Opt-in tools over MemoryService; user-facing requests need no UUIDs or source refs."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

import anyio
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import (
    BaseTool,
    InjectedToolCallId,
    StructuredTool,
    create_schema_from_function,
)

from milai_lab.memory.service import MemoryService


def create_service_tools(
    service: MemoryService, *, replay_requested: bool = False
) -> tuple[BaseTool, ...]:
    if type(replay_requested) is not bool:
        raise ValueError("V13_MEMORY_REPLAY_REQUESTED_INVALID")
    def session_for(config: RunnableConfig) -> str:
        cfg = config.get("configurable", {})
        if cfg.get("user_id") != service.owner or not cfg.get("v13_session"):
            raise ValueError("V13_MEMORY_TOOL_SCOPE_MISMATCH")
        return str(cfg["v13_session"])

    def message(name: str, call_id: str, receipt: dict[str, Any]) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(receipt, ensure_ascii=False),
            name=name,
            tool_call_id=call_id,
            status="success" if receipt["ok"] else "error",
        )

    def manage_memory(
        content: str,
        config: RunnableConfig,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
        action: Literal["create", "update"] = "create",
        kind: Literal["semantic", "episodic"] = "semantic",
        scope: dict[str, Any] | None = None,
        basis: Literal[
            "user_statement", "tool_observation", "plan", "inference"
        ] = "user_statement",
        target_query: str | None = None,
        id: str | None = None,
        expected_revision: int | None = None,
        source_ref: str | None = None,
        object_ref: str | None = None,
        fields: dict[str, str] | None = None,
        content_format: str | None = None,
    ) -> ToolMessage:
        """Save a proposed memory or revise a discovered record. Prose is always unchecked.

        Use scope to retain personal/project/one-off and time limits. For updates,
        search/read first or supply target_query; a unique matching record is
        discovered internally. User statements support expressed preferences, not
        confirmed business facts. Tool facts need a captured tool source and its
        issued object_ref; only status and label_status can be receipt matched.
        Source refs are optional: the bound session's latest relevant real event
        is selected. A committed receipt confirms memory storage only.
        """
        session = session_for(config)
        requested = {
            "content": content,
            "action": action,
            "kind": kind,
            "scope": scope,
            "basis": basis,
            "target_query": target_query,
            "id": id,
            "expected_revision": expected_revision,
            "source_ref": source_ref,
            "object_ref": object_ref,
            "fields": fields,
        }
        if service.receipt_contract == "explicit_receipt_v1":
            requested["content_format"] = content_format
        if replay_requested:
            prior_receipt = service.replay_requested(session, tool_call_id, requested)
            if prior_receipt is not None:
                return message("manage_memory", tool_call_id, prior_receipt)
        sources = service.sources(session)
        if source_ref is None:
            relevant = [
                event
                for event in sources
                if event["role"] == ("tool" if basis == "tool_observation" else "user")
            ]
            source_ref = relevant[-1]["event_id"] if relevant else ""
        event = service.source(source_ref)
        if object_ref is None and basis == "tool_observation" and event is not None:
            ref = event.get("object_ref")
            object_ref = ref["id"] if ref else None
        target_resolution_error = False
        if action == "update" and id is None:
            result = service.search(target_query or "", include_raw=False)
            candidates = result["records"]
            if len(candidates) == 1:
                id = candidates[0]["id"]
            else:
                # Preserve the proposal as a rejected attempt; do not pick an
                # arbitrary match or create a replacement memory silently.
                target_resolution_error = True
        if expected_revision is None:
            prior = service.read(id) if id else None
            expected_revision = (prior or {}).get("value", {}).get("revision", 0)
        proposal = {
            "content": content,
            "kind": kind,
            "scope": scope or {},
            "basis": basis,
            "source_ref": source_ref,
            "object_ref": object_ref,
            "fields": fields or {},
            "id": id,
            "expected_revision": expected_revision,
            "action": action,
            "target_query": target_query,
            "requested": requested,
            "target_resolution_error": target_resolution_error,
        }
        if service.receipt_contract == "explicit_receipt_v1":
            proposal["content_format"] = content_format
        receipt = service.commit(session, tool_call_id, proposal)
        return message("manage_memory", tool_call_id, receipt)

    async def amanage_memory(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: manage_memory(config=config, **arguments))

    def search_memory(
        query: str,
        config: RunnableConfig,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
        limit: int = 10,
        dense: bool = False,
    ) -> ToolMessage:
        """Find current memories and original events. Raw capture may still be unformed.

        Retrieval uses explicit raw/keyword fallback when dense search is unavailable.
        No result says nothing about existence in the business application.
        """
        session_for(config)
        return message("search_memory", tool_call_id, service.search(query, limit, dense=dense))

    async def asearch_memory(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: search_memory(config=config, **arguments))

    def read_memory(
        config: RunnableConfig,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
        id: str | None = None,
        query: str | None = None,
        revision: int | None = None,
    ) -> ToolMessage:
        """Read an exact memory, or discover a unique query match; revision reads history.

        Revisions are historical observations. Business mutations need current
        application discovery and authorization; a memory ref grants neither.
        """
        session_for(config)
        if id is None:
            candidates = service.search(query or "", include_raw=False)["records"]
            if len(candidates) != 1:
                return message(
                    "read_memory",
                    tool_call_id,
                    {
                        "ok": False,
                        "status": "target_not_unique",
                        "candidates": [row["id"] for row in candidates],
                    },
                )
            id = candidates[0]["id"]
        return message("read_memory", tool_call_id, service.read(id, revision))

    async def aread_memory(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: read_memory(config=config, **arguments))

    explicit = service.receipt_contract == "explicit_receipt_v1"
    manage_tool = StructuredTool.from_function(
        manage_memory,
        coroutine=amanage_memory,
        name="manage_memory",
        args_schema=(
            None if explicit else create_schema_from_function(
                "manage_memory", manage_memory,
                filter_args=["run_manager", "callbacks", "config", "content_format"],
            )
        ),
    )
    if explicit:
        manage_tool.description += (
            "\n\nExplicit receipt contract: for tool_observation bound to an actual reservation "
            "receipt, propose both status and label_status as strings in fields. Declare "
            "content_format='receipt_json_v1' and provide content as a JSON object with "
            "literal string status and label_status, plus optional notes (string); no other "
            "keys. Missing claims or undeclared/malformed bodies are rejected. Field-grounded "
            "mode compares fields to the original observed receipt and body literals to fields; "
            "Ref-only mode checks refs/schema while claims remain unchecked. Never fill or "
            "repair a rejected proposal silently. Only these two finite claims can be matched; "
            "notes, free prose and quotations are always unchecked. This contract does not "
            "assert current applicability of historical observations. Ordinary user preferences "
            "need no receipt JSON. Source/object refs are discovered internally when omitted."
        )
    return (
        manage_tool,
        *(
            StructuredTool.from_function(function, coroutine=coroutine, name=name)
            for name, function, coroutine in (
                ("search_memory", search_memory, asearch_memory),
                ("read_memory", read_memory, aread_memory),
            )
        ),
    )
