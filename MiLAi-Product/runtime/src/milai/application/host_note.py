"""Thin Note operations: exact content, scoped pagination and explicit receipts."""

import re
from typing import Any
from uuid import UUID

from milai.application.page_cursor import PageCursor
from milai.domain.host_note import NoteBinding, NoteBrowse, NoteGet, NoteOperationGet, NoteWrite
from milai.persistence.database import SessionContext
from milai.persistence.host_note_repository import HostNoteRepository, NoteError


def _snippet(content: str, query: str | None) -> dict[str, Any]:
    # Search eligibility belongs to the repository. Locate a literal match only
    # for presentation, on the original string so Unicode case conversion cannot
    # shift read offsets. A collation mismatch is explicit, not invented evidence.
    match = re.search(re.escape(query), content, re.IGNORECASE) if query else None
    start = max(0, match.start() - 64) if match else 0
    end = min(start + 256, len(content))
    return {
        "snippet": content[start:end], "snippet_only": True,
        "snippet_offset": start, "snippet_end": end,
        "match_in_snippet": match is not None,
        "match_complete": match is not None and match.end() <= end,
    }


def _view(row: dict[str, Any]) -> dict[str, Any]:
    available = row["body"] is not None
    status = "DELETED" if row.get("deleted") else "ACTIVE" if available else "SOURCE_UNAVAILABLE"
    return {
        "schema_version": "host-note-v1", "object_type": "HOST_NOTE",
        "authority": "HOST_WORKING", "memory_id": str(row["memory_id"]),
        "version": row["version"], "status": status,
        "direct_read_available": available, "expires_at": None,
        "read_tool": "milai_note_get",
        "read_arguments": {"memory_id": str(row["memory_id"]), "version": row["version"]},
    }


class HostNoteService:
    def __init__(self, repository: HostNoteRepository, cursor_secret: str) -> None:
        self.repository = repository
        self._cursor = PageCursor(cursor_secret, "host-note-cursor-v1")

    def get(self, context: SessionContext, request: NoteGet) -> dict[str, Any]:
        row = self.repository.get(context, request, request.memory_id, request.version)
        result = _view(row)
        body = row["body"]
        if body is not None:
            content = body["content"]
            end = min(request.offset + request.length, len(content))
            sources = body["source_refs"]
            source_end = min(request.source_offset + request.source_limit, len(sources))
            result.update({
                **body, "content_digest": "sha256:" + body["content_digest"],
                "content": content[request.offset:end], "offset": request.offset,
                "total_characters": len(content),
                "next_offset": end if end < len(content) else None,
                "content_complete": request.offset == 0 and end == len(content),
                "source_relation": "HOST_DECLARED", "origin": "HOST_SUBMISSION",
                "source_refs": sources[request.source_offset:source_end],
                "source_offset": request.source_offset, "total_source_refs": len(sources),
                "next_source_offset": source_end if source_end < len(sources) else None,
                "source_refs_complete": request.source_offset == 0 and source_end == len(sources),
            })
        else:
            result["content"] = None
        if row.get("deleted"):
            result["deletion"] = self.deletion_status()
        return result

    @staticmethod
    def deletion_status() -> dict[str, str | bool]:
        return {
            "logical": "APPLIED", "primary_storage": "NOT_IMPLEMENTED",
            "derived_cleanup": "NOT_APPLICABLE", "backup_expiry": "NOT_SCHEDULED",
            "scope": "SINGLE_NOTE_ALL_VERSIONS", "history_retained": "YES",
            "physical_deletion_supported": False,
        }

    def _receipt(
        self, context: SessionContext, binding: NoteBinding, receipt: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.repository.get(
            context, binding, UUID(receipt["memory_id"]), receipt["version"],
        )
        result = {
            **_view(row), **receipt, "commit_status": "COMMITTED", "durable": True,
            "search_index_status": "DIRECT" if row["body"] is not None else "NOT_VISIBLE",
        }
        if row["body"] is not None:
            result["content_digest"] = "sha256:" + row["body"]["content_digest"]
        if row.get("deleted"):
            result["deletion"] = self.deletion_status()
        return result

    def write(
        self, context: SessionContext, request: NoteWrite, operation_id: str,
    ) -> dict[str, Any]:
        receipt = self.repository.write(context, request, operation_id)
        return self._receipt(context, request, receipt)

    def operation(self, context: SessionContext, request: NoteOperationGet) -> dict[str, Any]:
        return self._receipt(
            context, request, self.repository.operation(context, request, request.operation_id),
        )

    def browse(self, context: SessionContext, request: NoteBrowse) -> dict[str, Any]:
        binding = {
            "tenant": str(context.tenant_id), "actor": str(context.actor_id),
            "principal": request.principal_binding_digest, "project": request.project_id,
            "query": request.query, "tags": sorted(request.tags),
        }
        try:
            cursor = self._cursor.decode(request.cursor, binding)
        except ValueError as exc:
            raise NoteError("INVALID_NOTE_CURSOR") from exc
        rows, snapshot = self.repository.browse(
            context, request, snapshot=cursor.get("snapshot"),
            after_time=cursor.get("after_time"), after_id=cursor.get("after_id"),
        )
        more = len(rows) > request.limit
        rows = rows[:request.limit]
        next_cursor = None
        if more:
            last = rows[-1]
            next_cursor = self._cursor.encode(binding, {
                **cursor, "snapshot": snapshot,
                "after_time": last["created_at"].isoformat(), "after_id": str(last["memory_id"]),
            })
        items = [{
            **_view(row), **_snippet(row["body"]["content"], request.query),
            "recorded_at": row["body"].get("recorded_at"),
            "observed_at": row["body"].get("observed_at"),
            "total_source_refs": len(row["body"]["source_refs"]),
            "source_refs_complete": not row["body"]["source_refs"],
        } for row in rows]
        return {
            "schema_version": "host-note-page-v1", "items": items, "next_cursor": next_cursor,
            "snapshot": snapshot, "search_index_status": "DIRECT", "truncated": more,
            "search_scope": {
                "object_types": ["HOST_NOTE"], "current_eligible_only": True,
                "mode": "LITERAL_SUBSTRING" if request.query is not None else "BROWSE",
                "query": request.query,
            },
            "absence_confirmed": False,
            "unsearched_sources": ["GOVERNED_MEMORY", "WORKING_STATE"],
            "time_semantics": (
                "recorded_at is storage time; observed_at is not necessarily event time"
            ),
        }
