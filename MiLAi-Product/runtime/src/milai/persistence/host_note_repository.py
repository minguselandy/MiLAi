"""Scoped Note transactions and direct lexical reads in the existing PG store."""

import hashlib
import json
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from milai.domain.host_note import NoteBinding, NoteBrowse, NoteWrite
from milai.persistence.database import Database, SessionContext


class NoteError(RuntimeError):
    pass


_ELIGIBLE = """NOT h.deleted AND NOT v.deleted AND NOT EXISTS (
  SELECT 1 FROM milai.host_note_evidence_ref r
  LEFT JOIN milai.evidence_record e ON e.tenant_id=r.tenant_id AND e.evidence_id=r.evidence_id
  WHERE r.tenant_id=v.tenant_id AND r.memory_id=v.memory_id AND r.version=v.version
    AND (e.evidence_id IS NULL OR e.revoked_at IS NOT NULL OR e.retention_state<>'READABLE'
      OR e.permission_snapshot->'readable' IS DISTINCT FROM 'true'::jsonb
      OR NOT COALESCE(e.permission_snapshot->'project_ids' ? h.project_id,false))
)
"""
_BINDING = """
h.tenant_id=%s AND h.created_by_actor_id=%s
AND h.principal_binding_digest=%s AND h.project_id=%s
"""
_BODY = """
jsonb_build_object('content',v.content,'content_digest',v.content_digest,'format',v.format,
  'tags',v.tags,'source_refs',v.source_refs,'observed_at',v.observed_at,
  'recorded_at',v.recorded_at)
"""


def _binding(context: SessionContext, request: NoteBinding) -> tuple[object, ...]:
    return (
        context.tenant_id, context.actor_id, request.principal_binding_digest, request.project_id,
    )


class HostNoteRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def write(
        self, context: SessionContext, request: NoteWrite, operation_id: str,
    ) -> dict[str, Any]:
        payload = request.model_dump(mode="json", exclude_unset=True)
        fingerprint = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        try:
            with self.database.connection(context) as connection:
                row = connection.execute(
                    "SELECT milai.write_host_note(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*_binding(context, request), request.operation, operation_id, fingerprint,
                     request.memory_id, request.expected_version, Jsonb(payload)),
                ).fetchone()
        except Error as exc:
            code = exc.diag.message_primary
            if code in {"NOTE_SCOPE_DENIED", "INVALID_NOTE", "OPERATION_CONFLICT",
                        "NOTE_NOT_FOUND", "NOTE_DELETED", "STALE_NOTE", "NOTE_SOURCE_UNAVAILABLE"}:
                raise NoteError(code) from exc
            raise
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Note commit receipt unavailable")
        return dict(row[0])

    def get(
        self, context: SessionContext, binding: NoteBinding, memory_id: UUID,
        version: int | None = None,
    ) -> dict[str, Any]:
        with self.database.connection(context, read_only=True) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(f"""  -- fixed SQL fragments only
                    SELECT h.memory_id,v.version,h.current_version,h.deleted,
                      CASE WHEN {_ELIGIBLE} THEN {_BODY} ELSE NULL END AS body
                    FROM milai.host_note h JOIN milai.host_note_version v
                      ON v.tenant_id=h.tenant_id AND v.memory_id=h.memory_id
                      AND v.version=COALESCE(%s,h.current_version)
                    WHERE {_BINDING} AND h.memory_id=%s
                """, (version, *_binding(context, binding), memory_id))  # noqa: S608
                row = cursor.fetchone()
        if row is None:
            raise NoteError("NOTE_NOT_FOUND")
        return row

    def operation(
        self, context: SessionContext, binding: NoteBinding, operation_id: str,
    ) -> dict[str, Any]:
        with self.database.connection(context, read_only=True) as connection:
            row = connection.execute("""
                SELECT milai.get_host_note_operation(%s,%s,%s,%s,%s)
            """, (context.tenant_id, context.actor_id,
                  binding.principal_binding_digest, binding.project_id, operation_id)).fetchone()
        if row is None or not isinstance(row[0], dict):
            raise NoteError("NOTE_OPERATION_NOT_FOUND")
        return dict(row[0])

    def browse(
        self, context: SessionContext, request: NoteBrowse, *, snapshot: str | None,
        after_time: str | None, after_id: str | None,
    ) -> tuple[list[dict[str, Any]], str]:
        with self.database.connection(context, read_only=True) as connection:
            if snapshot is None:
                now = connection.execute("SELECT clock_timestamp()").fetchone()
                assert now is not None
                snapshot = now[0].isoformat()
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(f"""  -- fixed SQL fragments only
                    SELECT h.memory_id,h.created_at,v.version,{_BODY} AS body
                    FROM milai.host_note h JOIN LATERAL (
                      SELECT * FROM milai.host_note_version n
                      WHERE n.tenant_id=h.tenant_id AND n.memory_id=h.memory_id
                        AND n.recorded_at<=%s::timestamptz
                      ORDER BY n.version DESC LIMIT 1
                    ) v ON true
                    WHERE {_BINDING} AND {_ELIGIBLE}
                      AND (%s::timestamptz IS NULL OR
                           (h.created_at,h.memory_id)>(%s::timestamptz,%s::uuid))
                      AND v.tags @> %s::jsonb
                      AND (%s::text IS NULL OR strpos(lower(v.content),lower(%s))>0)
                    ORDER BY h.created_at,h.memory_id LIMIT %s
                """, (snapshot, *_binding(context, request), after_time, after_time, after_id,  # noqa: S608
                      Jsonb(request.tags), request.query, request.query, request.limit + 1))
                rows = cursor.fetchall()
        return rows, snapshot
