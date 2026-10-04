"""Opt-in tools over MemoryService; user-facing requests need no UUIDs or source refs."""

from __future__ import annotations

import json
from collections.abc import Callable
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
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, WithJsonSchema, create_model

from milai_lab.contracts.public_memory_contracts import CAPTURE_GUIDANCE, parameter_guidance
from milai_lab.contracts.read_protocol import ReadProtocolRejected, reject
from milai_lab.memory.service import MemoryService

SemanticPatch = Annotated[dict[str, Any], WithJsonSchema({
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "scope": {"type": "object", "additionalProperties": True},
        "basis": {"type": "string", "enum": [
            "user_statement", "tool_observation", "plan", "inference",
        ]},
        "kind": {"type": "string", "enum": ["semantic", "episodic"]},
    },
    "additionalProperties": False,
})]

FieldSupport = Annotated[dict[str, Any], WithJsonSchema({
    "type": "object",
    "properties": {field: {"oneOf": [
        {"type": "object", "properties": {"source_refs": {
            "type": "array", "items": {"type": "string"}, "minItems": 1,
        }}, "required": ["source_refs"], "additionalProperties": False},
        {"type": "object", "properties": {"reuse_support_from": {"type": "string"}},
         "required": ["reuse_support_from"], "additionalProperties": False},
    ]} for field in ("content", "scope", "basis", "kind")},
    "required": ["content", "scope", "basis", "kind"], "additionalProperties": False,
})]


def create_service_tools(
    service: MemoryService, *, replay_requested: bool = False,
    context_provider: Callable[[str, RunnableConfig], dict[str, Any]] | None = None,
    recall_provider: Callable[[RunnableConfig], dict[str, Any]] | None = None,
    source_index_provider: Callable[[str | None, RunnableConfig], dict[str, Any]] | None = None,
    selected_page_provider: Callable[[str, RunnableConfig], dict[str, Any]] | None = None,
) -> tuple[BaseTool, ...]:
    if type(replay_requested) is not bool:
        raise ValueError("V13_MEMORY_REPLAY_REQUESTED_INVALID")

    def session_for(config: RunnableConfig) -> str:
        cfg = config.get("configurable", {})
        if cfg.get("user_id") != service.owner or not cfg.get("v13_session"):
            raise ValueError("V13_MEMORY_TOOL_SCOPE_MISMATCH")
        return str(cfg["v13_session"])

    def trigger_for(config: RunnableConfig) -> dict[str, Any] | None:
        cfg = config.get("configurable", {})
        if not cfg.get("v13_turn_id") or not cfg.get("v13_support_config_sha256"):
            return None
        try:
            return service.public_turn(session_for(config), message_id=str(cfg["v13_turn_id"]),
                                       config_sha256=str(cfg["v13_support_config_sha256"]))
        except ValueError:
            return None

    def message(name: str, call_id: str, receipt: dict[str, Any]) -> ToolMessage:
        if (service.mutation_contract == "event_bound_v1"
                and service.candidate_contract != "read_handle_v1"):
            def without_handles(value: Any) -> Any:
                if isinstance(value, dict):
                    return {key: without_handles(child) for key, child in value.items()
                            if key != "candidate_handle"}
                if isinstance(value, list):
                    return [without_handles(child) for child in value]
                return value
            receipt = without_handles(receipt)
        return ToolMessage(
            content=json.dumps(receipt, ensure_ascii=False,
                               separators=(",", ":")
                               if ((name == "search_memory" and context_provider)
                                   or (name == "recall_context" and recall_provider)
                                   or (name == "read_current_sources" and source_index_provider))
                               else None),
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
        source_refs: list[str] | None = None,
        candidate_handle: str | None = None,
        field_support: FieldSupport | None = None,
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
        requested: dict[str, Any] = {
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
        exact = service.mutation_contract == "event_bound_v1"
        if exact:
            requested.update(source_refs=source_refs, candidate_handle=candidate_handle)
        direct = service.support_contract == "direct_support_v1"
        if direct:
            requested.update(field_support=field_support, trigger_binding=trigger_for(config))
        if replay_requested:
            prior_receipt = service.replay_requested(session, tool_call_id, requested)
            if prior_receipt is not None:
                return message("manage_memory", tool_call_id, prior_receipt)
        binding_error = None
        if exact:
            if source_refs is None:
                if direct:
                    source_refs = []
                    binding_error = "source_selection_required"
                else:
                    source_refs = (
                        [source_ref] if source_ref is not None
                        else service.boundary_sources(session)
                    )
                    if len(source_refs) != 1:
                        binding_error = "source_selection_required"
            if source_ref is None:
                source_ref = source_refs[0] if source_refs else ""
            if action == "update":
                if service.candidate_contract != "legacy_query_v1":
                    if (service.candidate_contract == "id_revision_v1" and candidate_handle is None
                            and id is not None and expected_revision is not None):
                        candidate_handle = service.candidate_for_version(id, expected_revision)
                    try:
                        bound = service.candidate(candidate_handle)
                    except ValueError:
                        if not direct:
                            raise
                        bound = None
                    if bound is None:
                        binding_error = "candidate_handle_required_or_invalid"
                    elif (
                        (id is not None and id != bound["record_id"])
                        or (expected_revision is not None
                            and expected_revision != bound["revision"])
                    ):
                        binding_error = "candidate_binding_mismatch"
                    else:
                        id, expected_revision = bound["record_id"], bound["revision"]
            elif expected_revision is None:
                expected_revision = 0
        else:
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
        legacy_target = not exact or service.candidate_contract == "legacy_query_v1"
        if legacy_target and action == "update" and id is None:
            result = service.search(target_query or "", include_raw=False)
            candidates = result["records"]
            if len(candidates) == 1:
                id = candidates[0]["id"]
            else:
                # Preserve the proposal as a rejected attempt; do not pick an
                # arbitrary match or create a replacement memory silently.
                target_resolution_error = True
        if legacy_target and expected_revision is None:
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
        if exact:
            proposal.update(source_refs=source_refs, candidate_handle=candidate_handle,
                            binding_error=binding_error)
        if direct:
            proposal.update(field_support=field_support,
                            trigger_binding=requested["trigger_binding"])
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
        if context_provider is not None:
            return message("search_memory", tool_call_id, context_provider(query, config))
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

    def read_memory_history(
        config: RunnableConfig, *, tool_call_id: Annotated[str, InjectedToolCallId],
        id: str | None = None, query: str | None = None, revision: int | None = None,
        view: Literal["version", "history"] = "version", cursor: str | None = None,
        max_revisions: Annotated[int, Field(ge=1, le=6)] = 6,
        source_ref: str | None = None,
    ) -> ToolMessage:
        """Read an exact revision or enumerate stored history for a known record ID.

        view=history requires an explicit ID; it returns at most six actual revision
        numbers and an opaque next-page cursor. Changed histories invalidate cursors.
        Optional source_ref enumerates only revisions that actually cite that owned source.
        view=version preserves exact id/revision reads and optional unique-query discovery.
        Old citations do not support a current version unless it actually cites them.
        Historical handles remain stale for new writes; no latest revision is filled in.
        Semantic text remains unchecked and no business authority is granted.
        """
        session_for(config)
        try:
            if view == "history":
                if id is None or query is not None or revision is not None:
                    reject(
                        "V13_HISTORY_READ_REQUIRES_EXACT_ID",
                        "memory_tools",
                        service.tool_read_feedback,
                    )
                receipt = service.history_index(id, cursor=cursor, limit=max_revisions,
                                                source_ref=source_ref)
                return message("read_memory", tool_call_id, receipt)
            if cursor is not None or max_revisions != 6 or source_ref is not None:
                reject(
                    "V13_HISTORY_ARGUMENTS_REQUIRE_HISTORY_VIEW",
                    "memory_tools",
                    service.tool_read_feedback,
                )
            result = read_memory(config, tool_call_id=tool_call_id,
                                 id=id, query=query, revision=revision)
            receipt = json.loads(str(result.content))
            if receipt["ok"]:
                receipt["history_index"] = service.history_index(receipt["id"])
                receipt["read_view"] = "current_at_read" if revision is None else "exact_revision"
            return message("read_memory", tool_call_id, receipt)

        except ReadProtocolRejected as error:
            if service.tool_read_feedback == "legacy":
                raise
            return message("read_memory", tool_call_id, error.receipt())

    async def aread_memory_history(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(
            lambda: read_memory_history(config=config, **arguments))

    def revise_memory(
        candidate_handle: str,
        semantic_patch: SemanticPatch,
        config: RunnableConfig,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
        source_refs: list[str] | None = None,
        operation: Literal["revise", "supersede", "no_change"] = "revise",
        field_support: FieldSupport | None = None,
    ) -> ToolMessage:
        """Patch an explicitly selected read-time candidate; preserve other semantic metadata.

        semantic_patch may contain only content, scope, basis and kind; put source_refs
        beside semantic_patch, never inside it. Scope merges named keys. New revisions
        need at least one actual source in the trusted current boundary; historical
        refs can provide additional support. Actual source_refs retain roles; omitted
        refs bind only a trusted current singleton event, while multiple events require
        explicit selection. no_change creates no revision and needs no new source.
        All prose remains unchecked.
        Observation fields cannot be patched. Supersede preserves earlier revisions;
        no_change writes no new revision. Conflicts do not create replacement cards.
        """
        session = session_for(config)
        requested = {"candidate_handle": candidate_handle, "semantic_patch": semantic_patch,
                     "source_refs": source_refs, "operation": operation}
        direct = service.support_contract == "direct_support_v1"
        if direct:
            requested.update(field_support=field_support, trigger_binding=trigger_for(config))
        if replay_requested:
            prior = service.replay_requested(session, tool_call_id, requested)
            if prior is not None:
                return message("revise_memory", tool_call_id, prior)
        support_args: dict[str, Any] = (
            {"field_support": field_support, "trigger_binding": requested["trigger_binding"]}
            if direct else {})
        return message("revise_memory", tool_call_id, service.revise(
            session, tool_call_id, candidate_handle, semantic_patch, source_refs,
            operation=operation,
            **support_args,
        ))

    async def arevise_memory(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: revise_memory(config=config, **arguments))

    def recall_context(config: RunnableConfig, *,
                       tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
        """Recall bounded historical evidence using the actual current public user request.

        This ordinary no-query read shares a fixed packet with prefetch and dirty refresh.
        For an explicit additional query use search_memory(query); that retrieval is charged.
        Observations remain historical and prose is unchecked.
        """
        session_for(config)
        if recall_provider is None:
            raise ValueError("V13_RECALL_PROVIDER_REQUIRED")
        return message("recall_context", tool_call_id, recall_provider(config))

    async def arecall_context(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: recall_context(config=config, **arguments))

    def recall_selected_context(
        config: RunnableConfig, *, tool_call_id: Annotated[str, InjectedToolCallId],
        cursor: str | None = None,
    ) -> ToolMessage:
        """Recall the fixed ordinary public-query packet, or read its omitted-item menu.

        With no cursor this is the single ordinary read, shared with prefetch/dirty refresh.
        With an actual coverage cursor this is an explicit additional page of read pointers
        over the cached selection, with no new retrieval. Its complete tool body is delivered
        and charged separately; it is not an ordinary packet reference. Empty search does
        not prove the archive is empty. Additional queries use search_memory(query).
        """
        if cursor is None:
            return recall_context(config, tool_call_id=tool_call_id)
        session_for(config)
        try:
            if selected_page_provider is None:
                raise ValueError("V13_SELECTED_PAGE_PROVIDER_REQUIRED")
            return message("recall_context", tool_call_id, selected_page_provider(cursor, config))

        except ReadProtocolRejected as error:
            if service.tool_read_feedback == "legacy":
                raise
            return message("recall_context", tool_call_id, error.receipt())

    async def arecall_selected_context(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(
            lambda: recall_selected_context(config=config, **arguments))

    def read_current_sources(
        config: RunnableConfig, *, tool_call_id: Annotated[str, InjectedToolCallId],
        cursor: str | None = None,
    ) -> ToolMessage:
        """List actual trusted current boundary source refs, roles and original hashes.

        No query or guessed source ID is needed. An opaque cursor reads the next page
        of the same boundary; changed boundaries invalidate cursors. Missing bindings
        return an empty index. Boundary membership does not verify semantic claims or
        business state and grants no business write permission.
        """
        session = session_for(config)
        try:
            if source_index_provider is not None:
                receipt = source_index_provider(cursor, config)
            else:
                receipt = {"ok": True,
                           "source_index": service.source_boundary(session, cursor=cursor),
                           "historical_empty": True, "items": []}
            return message("read_current_sources", tool_call_id, receipt)

        except ReadProtocolRejected as error:
            if service.tool_read_feedback == "legacy":
                raise
            return message("read_current_sources", tool_call_id, error.receipt())

    async def aread_current_sources(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(
            lambda: read_current_sources(config=config, **arguments))

    def read_source(
        source_ref: str, config: RunnableConfig, *,
        tool_call_id: Annotated[str, InjectedToolCallId], start: int = 0, max_chars: int = 4096,
    ) -> ToolMessage:
        """Read an original owner-bound source leaf; ranges refer to its original content text.

        This explicit escape preserves role/hash and does not assert semantic or current truth.
        """
        session_for(config)
        if (type(start) is not int or start < 0 or type(max_chars) is not int
                or not 1 <= max_chars <= 16000):
            raise ValueError("V13_SOURCE_READ_RANGE_INVALID")
        source = service.source(source_ref)
        if source is None:
            return message("read_source", tool_call_id, {"ok": False, "status": "not_found"})
        body = source["content"] if isinstance(source["content"], str) else json.dumps(
            source["content"], ensure_ascii=False, sort_keys=True)
        end = min(len(body), start + max_chars)
        return message("read_source", tool_call_id, {"ok": True, "source_ref": source_ref,
            "role": source["role"], "source_hash": source["content_sha256"],
            "observed_at": source["observed_at"], "content": body[start:end],
            "range": [start, end], "range_basis": "original_content_text",
            "next_start": end if end < len(body) else None, "content_verification": "unchecked"})

    def read_observations(
        object_id: str, config: RunnableConfig, *,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        """Read all historical field candidates for an observed object, retaining conflicts.

        object_id is an exact observation id or actual public external object id.
        Observation identity confers no business write permission or current verification.
        """
        session_for(config)
        objects = [row for row in service.observations()["objects"]
                   if object_id in {row["object_ref"]["id"], row["object_ref"]["external_id"]}]
        return message("read_observations", tool_call_id,
                       {"ok": bool(objects), "objects": objects, "current_verified": False})

    async def aread_source(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: read_source(config=config, **arguments))

    async def aread_observations(config: RunnableConfig, **arguments: Any) -> ToolMessage:
        return await anyio.to_thread.run_sync(lambda: read_observations(config=config, **arguments))

    explicit = service.receipt_contract == "explicit_receipt_v1"
    hidden = ["run_manager", "callbacks", "config"]
    if service.support_contract == "legacy":
        hidden.append("field_support")
    if not explicit:
        hidden.append("content_format")
    if service.mutation_contract == "legacy":
        hidden.extend(["source_refs", "candidate_handle"])
    elif service.candidate_contract != "read_handle_v1":
        hidden.append("candidate_handle")
    manage_tool = StructuredTool.from_function(
        manage_memory,
        coroutine=amanage_memory,
        name="manage_memory",
        args_schema=create_schema_from_function(
            "manage_memory", manage_memory, filter_args=hidden,
        ),
    )
    if service.mutation_contract == "event_bound_v1":
        manage_tool.description = (
            "Save an unchecked semantic proposal, or update a candidate you actually read. "
            "For update, supply candidate_handle from search/read; similarity and a single match "
            "never select a target. Its read-time revision must still be current, otherwise the "
            "proposal is rejected as a conflict. Omitted source refs bind only a singleton actual "
            "event in the current boundary. For multiple events select source_refs explicitly; "
            "roles and original hashes are retained. user_statement requires user sources, "
            "tool_observation requires tool sources, and mixed sources need plan/inference. "
            "Creates and updates need at least one actual current boundary source; "
            "historical sources "
            "may provide additional support. "
            "The current source index or read_current_sources reveals those actual refs. "
            "Quotations or references do not verify semantic meaning. Use scope to retain "
            "personal/project/time limits. Tool fields need a captured source and issued "
            "object_ref; "
            "only status and label_status can be receipt matched. A committed receipt confirms "
            "memory storage only. Rejection preserves raw input pending and does not create a "
            "replacement card."
        )
        if service.candidate_contract == "id_revision_v1":
            manage_tool.description = manage_tool.description.replace(
                "supply candidate_handle from search/read",
                "supply id and expected_revision from search/read",
            )
        elif service.candidate_contract == "legacy_query_v1":
            manage_tool.description = (
                "Frozen legacy target-query control: updates may discover a unique target_query; "
                "the original query interface binds its revision internally. Source refs still "
                "bind actual current events; multiple sources require explicit source_refs. "
                "Prose is unchecked; actual tool facts require captured object refs and fields."
            )
    if service.receipt_profile == "document_publication_v1":
        base_schema = manage_tool.args_schema
        assert isinstance(base_schema, type) and issubclass(base_schema, BaseModel)
        manage_tool.args_schema = create_model(
            "manage_memory", __base__=base_schema, fields=(dict[str, Any] | None, None)
        )
        manage_tool.description = manage_tool.description.replace(
            "only status and label_status can be receipt matched.",
            "only the declared finite document receipt fields can be matched; "
            "document_version is an integer.",
        )
    if explicit:
        if service.receipt_profile == "document_publication_v1":
            manage_tool.description += (
                "\n\nExplicit document receipt contract: tool_observation bound to a real document "
                "receipt requires exactly these fields: "
                + ", ".join(service.receipt_fields)
                + ". document_version is an integer; other fields are literal strings. Declare "
                "content_format='receipt_json_v1' with the same eight literal JSON fields and "
                "optional notes:string only. Field-grounded mode compares the original observed "
                "receipt and body literals; Ref-only claims remain unchecked. Never repair a "
                "rejected proposal. Notes/prose/quotations stay unchecked; no live applicability "
                "claim. Refs are discovered internally. Ordinary preferences need no receipt JSON."
            )
        else:
            manage_tool.description += (
                "\n\nExplicit receipt contract: for tool_observation bound to an actual "
                "reservation "
                "receipt, propose both status and label_status as strings in fields. Declare "
                "content_format='receipt_json_v1' and provide content as a JSON object with "
                "literal string status and label_status, plus optional notes (string); no other "
                "keys. Missing claims or undeclared/malformed bodies are rejected. Field-grounded "
                "mode compares fields to the original observed receipt and body literals "
                "to fields; "
                "Ref-only mode checks refs/schema while claims remain unchecked. Never fill or "
                "repair a rejected proposal silently. Only these two finite claims can be matched; "
                "notes, free prose and quotations are always unchecked. This contract does not "
                "assert current applicability of historical observations. Ordinary user "
                "preferences "
                "need no receipt JSON. Source/object refs are discovered internally when omitted."
            )
    if service.mutation_contract == "event_bound_v1":
        base_schema = manage_tool.args_schema
        assert isinstance(base_schema, type) and issubclass(base_schema, BaseModel)
        # Annotation metadata survives LangChain's public tool_call_schema subset.
        # Preserve dictionary DTOs and the existing runtime receipt checks.
        field_type = (dict[str, Any] if service.receipt_profile == "document_publication_v1"
                      else dict[str, str])
        manage_tool.args_schema = create_model(
            "manage_memory", __base__=base_schema,
            fields=(Annotated[field_type, WithJsonSchema({
                "type": "object",
                "properties": {key: {"type": dtype}
                               for key, dtype in service.receipt_fields.items()},
                "additionalProperties": False,
            })] | None, None),
        )
        manage_tool.description += (
            "\n\nfields contains only literal business receipt claims for this profile: "
            + ", ".join(service.receipt_fields)
            + ". Put semantic preferences and their qualifiers in content/scope instead. "
            "Unknown fields are invalid; do not move rejected values or guess object_ref."
        )
        manage_tool.description = manage_tool.description.replace(
            "Source/object refs are discovered internally when omitted.",
            "An object ref may be taken from the exactly selected actual source.",
        ).replace("Refs are discovered internally.",
                  "An object ref may be taken from the exactly selected actual source.")
    revise_tool = None
    if (service.mutation_contract == "event_bound_v1"
            and service.candidate_contract == "read_handle_v1"):
        revise_tool = StructuredTool.from_function(
            revise_memory, coroutine=arevise_memory, name="revise_memory",
            args_schema=create_schema_from_function("revise_memory", revise_memory,
                filter_args=["run_manager", "callbacks", "config"]
                + (["field_support"] if service.support_contract == "legacy" else [])),
        )
    if service.support_contract == "direct_support_v1":
        support_description = (
            "Direct support contract: the actual public turn is a trusted trigger, not evidence. "
            "Explicitly select nonempty source_refs of real supporting leaves "
            "(current or historical); "
            "omission never chooses a current/latest source. field_support must contain content, "
            "scope, basis and kind: each value is exactly {'source_refs':[actual leaf IDs]} or "
            "{'reuse_support_from':candidate_handle}. Reuse requires that same actually read "
            "candidate and an exactly equal whole field; include all its original field leaf IDs "
            "in outer source_refs. Legacy versions lacking field maps can reuse only their entire "
            "legacy_whole_version_set. Changed fields require explicitly selected real leaves. "
            "Current CAS and source owner/role/hash must still match. Metadata/prefix delivery "
            "does "
            "not establish full-body reading or entailment; use the existing explicit read tools "
            "when needed. All prose is unchecked. scope retains original applicability limits; "
            "user_statement uses user leaves, tool_observation uses tool leaves, mixed roles need "
            "plan/inference. Tool object_ref is the STRING id from the exactly selected Source's "
            "tool_argument_ids companion, never its object_ref DTO. Literal receipt constraints "
            "and consumption dedup remain; a memory commit grants no business action authority. "
            "Rejected raw actions remain pending; never silently repair them."
        )
        manage_tool.description = support_description + (
            "\n" + manage_tool.description[manage_tool.description.index("Explicit"):]
            if explicit and "Explicit" in manage_tool.description else "")
        if revise_tool is not None:
            revise_tool.description = support_description + (
                " semantic_patch changes only content/scope/basis/kind; scope merges named keys. "
                "no_change creates no revision. Observation fields are immutable."
            )
    if service.tool_parameter_contract != "legacy":
        for mutation_tool in [manage_tool, *([revise_tool] if revise_tool is not None else [])]:
            properties = convert_to_openai_tool(mutation_tool)["function"]["parameters"].get(
                "properties", {}
            )
            mutation_tool.description += "\n" + parameter_guidance(
                properties, receipt_fields=service.receipt_fields,
                receipt_contract=service.receipt_contract,
                support_contract=service.support_contract,
                grounding_mode=service.mode,
            )
    if service.observation_capture_feedback != "legacy":
        manage_tool.description += "\n" + CAPTURE_GUIDANCE
        if revise_tool is not None:
            revise_tool.description += "\n" + CAPTURE_GUIDANCE
    tools = (
        manage_tool,
        *([StructuredTool.from_function(
            recall_selected_context if service.mutation_contract == "event_bound_v1"
            else recall_context,
            coroutine=arecall_selected_context if service.mutation_contract == "event_bound_v1"
            else arecall_context,
                                        name="recall_context")]
          if recall_provider is not None else []),
        *(
            [StructuredTool.from_function(read_current_sources, coroutine=aread_current_sources,
                                          name="read_current_sources"),
             StructuredTool.from_function(read_source, coroutine=aread_source, name="read_source"),
             StructuredTool.from_function(read_observations, coroutine=aread_observations,
                                          name="read_observations")]
            if service.mutation_contract == "event_bound_v1" else []
        ),
        *(
            [revise_tool] if revise_tool is not None else []
        ),
        *(
            StructuredTool.from_function(function, coroutine=coroutine, name=name,
                args_schema=create_schema_from_function(name, function,
                    filter_args=["run_manager", "callbacks", "config", "limit", "dense"])
                if name == "search_memory" and context_provider else None)
            for name, function, coroutine in (
                ("search_memory", search_memory, asearch_memory),
                ("read_memory", read_memory_history, aread_memory_history)
                if service.mutation_contract == "event_bound_v1"
                else ("read_memory", read_memory, aread_memory),
            )
        ),
    )
    if service.memory_read_protocol != "legacy":
        recall_tool = next((tool for tool in tools if tool.name == "recall_context"), None)
        if recall_tool is not None:
            recall_tool.description += (
                " An actual coverage cursor binds the immutable selected menu of its issuing "
                "ordinary OR explicit-query packet, including owner/public turn/config and "
                "delivered shape. Continuation returns paid version-bound pointers, not full "
                "bodies or a fresh query; metadata/prefixes do not establish full reading. "
                "Unavailable selected members stay visibly unavailable; never repair a cursor."
            )
    if any(value != "legacy" for value in (service.memory_read_protocol,
                                           service.tool_read_feedback,
                                           service.tool_save_communication)):
        for tool in tools:
            tool.metadata = {**(tool.metadata or {}), "read_protocol_profiles": {
                "memory_read_protocol": service.memory_read_protocol,
                "tool_read_feedback": service.tool_read_feedback,
                "tool_save_communication": service.tool_save_communication,
            }}
    return tools
