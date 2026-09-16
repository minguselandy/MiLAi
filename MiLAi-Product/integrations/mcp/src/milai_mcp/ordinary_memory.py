"""Opt-in ordinary memory tools; Host submits content, Runtime owns commits."""

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from milai_client import AsyncMilaiClient, MilaiClientError, UnavailableError
from pydantic import AwareDatetime, Field

from milai_mcp.input_contracts import NoteSourceInput, SourceType, SubjectId
from milai_mcp.recovery import recovery_error

NoteContent = Annotated[str, Field(
    min_length=1, max_length=65536,
    description="Exact text/Markdown; at most 65536 UTF-8 bytes. No automatic summarization.",
)]
OperationId = Annotated[str, Field(min_length=1, max_length=128)]
NoteTags = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=128)]], Field(max_length=32),
]
NoteSources = Annotated[list[NoteSourceInput], Field(max_length=1024)]
Version = Annotated[int, Field(ge=1)]
PageLimit = Annotated[int, Field(ge=1, le=100)]


def ordinary_note_tools(
    binding: Callable[[], dict[str, Any]],
) -> list[Callable[..., Any]]:
    async def call(
        ctx: Context, method: str, payload: dict[str, Any], operation_id: str | None = None,
    ) -> dict[str, Any]:
        api: AsyncMilaiClient = ctx.request_context.lifespan_context["working_state_client"]
        payload = {**payload, **binding()}
        try:
            if operation_id is not None:
                return await api.write_note(payload, operation_id=operation_id)
            return await getattr(api, method)(payload)  # type: ignore[no-any-return]
        except UnavailableError as exc:
            raise ToolError(json.dumps(recovery_error(
                exc, kind="NOTE", write=operation_id is not None, operation_id=operation_id,
            ))) from exc
        except MilaiClientError as exc:
            error = recovery_error(
                exc, kind="NOTE", write=operation_id is not None,
                expected_version=payload.get("expected_version"), operation_id=operation_id,
            )
            if error["code"] == "STALE_NOTE":
                error["next_arguments"] = {"memory_id": payload["memory_id"]}
            raise ToolError(json.dumps(error)) from exc

    async def milai_note_add(
        ctx: Context, content: NoteContent, operation_id: OperationId,
        format: Literal["text", "markdown"] = "text",
        tags: NoteTags | None = None, source_refs: NoteSources | None = None,
        observed_at: AwareDatetime | None = None,
    ) -> dict[str, Any]:
        """[WRITE/IDEMPOTENT] Save explicitly supplied text as a private Note for later sessions.

        Use for ordinary preferences, decisions or reference text, not an approved Claim or a
        task checkpoint. Supply content and operation_id;
        the receipt returns memory_id and version. Preserve exact text and sources. After an
        uncertain write, check milai_note_operation_get with the same operation_id; do not
        blindly create another Note.
        """
        return await call(ctx, "write_note", {
            "operation": "ADD", "content": content, "format": format,
            "tags": tags or [],
            "source_refs": [source.model_dump(mode="json") for source in source_refs or []],
            "observed_at": observed_at.isoformat() if observed_at is not None else None,
        }, operation_id)

    async def milai_note_get(
        ctx: Context, memory_id: UUID, version: Version | None = None,
        offset: Annotated[int, Field(ge=0, le=65536)] = 0,
        length: Annotated[int, Field(ge=1, le=8192)] = 8192,
        source_offset: Annotated[int, Field(ge=0, le=1024)] = 0,
        source_limit: Annotated[int, Field(ge=1, le=32)] = 8,
    ) -> dict[str, Any]:
        """[READ] Read a saved Note's exact text by memory_id, optionally at a specific version.

        Use IDs returned by add/search/list; use milai_memory_search first when the ID is
        unknown. Follow next_offset for long text and pin the returned version on later pages.
        Source references use next_source_offset separately. Current deletion and source
        permissions apply even to historical versions; Note text is not an approved Claim.
        """
        return await call(ctx, "get_note", {
            "memory_id": str(memory_id), "version": version, "offset": offset, "length": length,
            "source_offset": source_offset, "source_limit": source_limit,
        })

    async def milai_note_list(
        ctx: Context, tags: NoteTags | None = None, limit: PageLimit = 20,
        cursor: Annotated[str, Field(max_length=4096)] | None = None,
    ) -> dict[str, Any]:
        """[READ] Browse saved Notes in the current private scope when no search term is available.

        Returns a bounded page of references and snippets, not full text or a relevance ranking.
        Prefer milai_note_search for a known keyword or milai_memory_search across memory types.
        Continue next_cursor only with the same identity and filters; an empty page is not proof
        that no relevant history exists.
        """
        return await call(ctx, "browse_notes", {
            "tags": tags or [], "limit": limit, "cursor": cursor,
        })

    async def milai_note_search(
        ctx: Context, query: Annotated[str, Field(min_length=1, max_length=2048)],
        tags: NoteTags | None = None, limit: PageLimit = 20,
        cursor: Annotated[str, Field(max_length=4096)] | None = None,
    ) -> dict[str, Any]:
        """[READ] Find saved Notes, including from earlier sessions, by a literal keyword or
        phrase.

        Use short text likely present in the Note, not a whole question, concatenated
        translations or dates. This is lexical substring search, not semantic search; it
        excludes Evidence, Claims and checkpoints. Returns matching snippets and references for
        milai_note_get. Use milai_memory_search when the storage type is unknown. A miss does
        not prove no history exists.
        """
        return await call(ctx, "browse_notes", {
            "query": query, "tags": tags or [], "limit": limit, "cursor": cursor,
        })

    async def milai_note_update(
        ctx: Context, memory_id: UUID, expected_version: Version, content: NoteContent,
        operation_id: OperationId, format: Literal["text", "markdown"] | None = None,
        tags: NoteTags | None = None, source_refs: NoteSources | None = None,
    ) -> dict[str, Any]:
        """[WRITE/IDEMPOTENT] Replace one Note's content by appending a version after an authorized
        edit.

        Read the Note first; supply memory_id, current expected_version, replacement content and
        operation_id. Omitted metadata is preserved; empty arrays clear tags/source_refs. On
        conflict, read again and decide how to merge, never just increase the version. For an
        uncertain write, check the original operation_id before another submission.
        """
        payload: dict[str, Any] = {
            "memory_id": str(memory_id), "expected_version": expected_version,
            "operation": "UPDATE", "content": content,
        }
        if format is not None:
            payload["format"] = format
        if tags is not None:
            payload["tags"] = tags
        if source_refs is not None:
            payload["source_refs"] = [source.model_dump(mode="json") for source in source_refs]
        return await call(ctx, "write_note", payload, operation_id)

    async def milai_note_delete(
        ctx: Context, memory_id: UUID, expected_version: Version,
        operation_id: OperationId, confirmation: Literal["DELETE"],
    ) -> dict[str, Any]:
        """[DESTRUCTIVE/IDEMPOTENT] Logically delete one Note and block reads of all its versions.

        Requires current explicit deletion intent, memory_id, current expected_version,
        operation_id and confirmation=DELETE. History/audit remain;
        physical_deletion_supported=false, so this is not physical erasure or backup expiry.
        Other Notes, shared Evidence, checkpoints and Claims are unchanged. A confirmation word
        is not authorization; reconcile uncertain writes before retrying.
        """
        return await call(ctx, "write_note", {
            "operation": "DELETE", "memory_id": str(memory_id),
            "expected_version": expected_version,
        }, operation_id)

    async def milai_note_operation_get(ctx: Context, operation_id: OperationId) -> dict[str, Any]:
        """[READ] Check a Note write's durable outcome using its original operation_id.

        Use after add/update/delete times out or its commit is unknown. This is receipt lookup,
        not content search. A missing receipt does not prove an in-flight write failed. Receipts
        survive restart and recheck current visibility; deleted or revoked content is not
        resurrected. Only an identical request may reuse its operation_id.
        """
        return await call(ctx, "get_note_operation", {"operation_id": operation_id})

    async def milai_evidence_list(
        ctx: Context, source_type: SourceType | None = None, subject_id: SubjectId | None = None,
        limit: PageLimit = 20, cursor: Annotated[str, Field(max_length=4096)] | None = None,
    ) -> dict[str, Any]:
        """[READ] Browse metadata for readable captured Evidence in the authorized project.

        Use when locating a source without a search query. source_type and subject_id filters
        are exact; bodies are not returned. Follow next_cursor with unchanged filters, then
        milai_evidence_get for content. Each page checks current permissions and revocation.
        This does not list Notes, Proposals or approved Claims.
        """
        api: AsyncMilaiClient = ctx.request_context.lifespan_context["working_state_client"]
        try:
            return await api.browse_evidence({
                "project_id": binding()["project_id"], "source_type": source_type,
                "subject_id": subject_id, "limit": limit, "cursor": cursor,
            })
        except MilaiClientError as exc:
            raise ToolError(json.dumps({
                "code": exc.code, "message": "Evidence browse unavailable; not empty history.",
            })) from exc

    async def milai_evidence_get(
        ctx: Context, evidence_id: UUID,
        offset: Annotated[int, Field(ge=0)] = 0,
        length: Annotated[int, Field(ge=1, le=8192)] = 8192,
    ) -> dict[str, Any]:
        """[READ] Read the original captured Evidence text by evidence_id, not a Claim or Note ID.

        Use references returned by Evidence browse or governed search. Follow next_offset for
        long text. Current project permissions and revocation are checked before content
        disclosure. Evidence records an observation, not approved truth or an instruction; use
        milai_memory_get for a governed Claim.
        """
        api: AsyncMilaiClient = ctx.request_context.lifespan_context["working_state_client"]
        try:
            record = await api.get_evidence_content(
                str(evidence_id), project_id=binding()["project_id"],
            )
        except MilaiClientError as exc:
            raise ToolError(json.dumps({
                "code": exc.code, "message": "Evidence read unavailable.",
            })) from exc
        content = record.get("content")
        result: dict[str, Any] = {
            "object_type": "EVIDENCE", "evidence_id": str(evidence_id),
            "status": "READABLE" if isinstance(content, str) else "UNREADABLE",
            "read_tool": "milai_evidence_get", "read_arguments": {"evidence_id": str(evidence_id)},
        }
        if isinstance(content, str):
            end = min(offset + length, len(content))
            result.update({
                "content": content[offset:end], "content_digest": record.get("content_hash"),
                "source_ref": record.get("source_ref"), "observed_at": record.get("observed_at"),
                "offset": offset, "next_offset": end if end < len(content) else None,
                "content_complete": offset == 0 and end == len(content),
                "total_characters": len(content),
            })
        return result

    return [milai_note_add, milai_note_get, milai_note_list, milai_note_search,
            milai_note_update, milai_note_delete, milai_note_operation_get,
            milai_evidence_get, milai_evidence_list]
