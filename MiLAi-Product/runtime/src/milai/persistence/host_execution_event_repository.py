from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Error, sql
from psycopg.types.json import Jsonb

from milai.application.errors import HostExecutionEventError, IdempotencyConflict
from milai.domain.host_execution_event import (
    HostExecutionEventAppendRequest,
    HostExecutionEventWindowRequest,
)
from milai.persistence.database import Database, SessionContext


@dataclass(frozen=True, slots=True)
class HostExecutionEventRecord:
    event_id: UUID
    position: int
    event_family: str
    event_type: str
    observed_at: datetime
    bounded_payload: dict[str, Any]
    evidence_refs: tuple[UUID, ...]
    stale_evidence_refs: tuple[UUID, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HostExecutionEventAppend:
    request: HostExecutionEventAppendRequest
    operation_id: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class HostExecutionEventAppendResult:
    record: HostExecutionEventRecord
    replayed: bool


@dataclass(frozen=True, slots=True)
class HostExecutionEventWindow:
    events: tuple[HostExecutionEventRecord, ...]
    after_position: int
    next_position: int
    visible_high_watermark: int
    has_more: bool


class HostExecutionEventRepository:
    """PostgreSQL boundary for sparse, actor-private Host Event windows."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def append(
        self,
        context: SessionContext,
        command: HostExecutionEventAppend,
    ) -> HostExecutionEventAppendResult:
        request = command.request
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.append_host_execution_event(
                      %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        request.principal_binding_digest,
                        request.project_id,
                        request.task_ref,
                        request.event_family,
                        request.event_type,
                        request.observed_at,
                        Jsonb(request.bounded_payload),
                        request.evidence_refs,
                        command.operation_id,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            code = exc.diag.message_primary or "HOST_EXECUTION_EVENT_REJECTED"
            if code == "IDEMPOTENCY_CONFLICT":
                raise IdempotencyConflict("operation ID has a different payload") from exc
            if code in {
                "EVIDENCE_REFERENCE_INVALID",
                "INVALID_HOST_EXECUTION_EVENT",
                "TENANT_MISMATCH",
            }:
                raise HostExecutionEventError(code) from exc
            raise
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Host execution Event procedure returned no result")
        payload: dict[str, Any] = row[0]
        record = self._get_by_id(
            context,
            request,
            event_id=UUID(str(payload["event_id"])),
        )
        if record is None:
            raise RuntimeError("persisted Host execution Event is not readable")
        return HostExecutionEventAppendResult(record, bool(payload.get("replayed")))

    def read_window(
        self,
        context: SessionContext,
        request: HostExecutionEventWindowRequest,
    ) -> HostExecutionEventWindow:
        # A frozen statement pair is required: a concurrent append after the
        # watermark query must not appear in rows beyond that watermark.
        with self._database.connection(
            context,
            isolation_level="REPEATABLE READ",
        ) as connection:
            high_row = connection.execute(
                """
                SELECT COALESCE(max(position), 0)
                FROM milai.host_execution_event
                WHERE tenant_id = %s
                  AND created_by_actor_id = %s
                  AND principal_binding_digest = %s
                  AND project_id = %s
                  AND task_ref = %s
                """,
                _binding_params(context, request),
            ).fetchone()
            rows = connection.execute(
                _WINDOW_SQL,
                (*_binding_params(context, request), request.after_position, request.limit + 1),
            ).fetchall()
            connection.execute(
                """
                INSERT INTO milai.operational_event (
                  tenant_id, event_id, event_type, reason_code, safe_metadata,
                  created_by_actor_id
                ) VALUES (
                  %s, gen_random_uuid(), 'HOST_EXECUTION_EVENT_WINDOW_READ', NULL,
                  jsonb_build_object(
                    'after_position', %s::bigint,
                    'returned_count', %s::integer,
                    'task_ref_sha256', encode(
                      sha256(convert_to(%s::text, 'UTF8')), 'hex'
                    )
                  ), %s
                )
                """,
                (
                    context.tenant_id,
                    request.after_position,
                    min(len(rows), request.limit),
                    request.task_ref,
                    context.actor_id,
                ),
            )
        has_more = len(rows) > request.limit
        visible_rows = rows[: request.limit]
        events = tuple(_record(row) for row in visible_rows)
        next_position = events[-1].position if events else request.after_position
        return HostExecutionEventWindow(
            events=events,
            after_position=request.after_position,
            next_position=next_position,
            visible_high_watermark=int(high_row[0]) if high_row is not None else 0,
            has_more=has_more,
        )

    def _get_by_id(
        self,
        context: SessionContext,
        binding: HostExecutionEventAppendRequest,
        *,
        event_id: UUID,
    ) -> HostExecutionEventRecord | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                _EVENT_BY_ID_SQL,
                (*_binding_params(context, binding), event_id),
            ).fetchone()
        return _record(row) if row is not None else None


_EVENT_COLUMNS = """
event.event_id,
event.position,
event.event_family,
event.event_type,
event.observed_at,
event.bounded_payload,
COALESCE(
  array_agg(ref.evidence_id ORDER BY ref.ordinal)
    FILTER (
      WHERE ref.evidence_id IS NOT NULL
        AND evidence.evidence_id IS NOT NULL
        AND evidence.revoked_at IS NULL
        AND evidence.retention_state = 'READABLE'
        AND evidence.permission_snapshot @> jsonb_build_object(
          'readable', true,
          'project_ids', jsonb_build_array(event.project_id)
        )
    ),
  ARRAY[]::uuid[]
) AS evidence_refs,
COALESCE(
  array_agg(ref.evidence_id ORDER BY ref.ordinal)
    FILTER (
      WHERE ref.evidence_id IS NOT NULL
        AND (
          evidence.evidence_id IS NULL
          OR evidence.revoked_at IS NOT NULL
          OR evidence.retention_state <> 'READABLE'
          OR evidence.permission_snapshot @> jsonb_build_object(
            'readable', true,
            'project_ids', jsonb_build_array(event.project_id)
          ) IS NOT TRUE
        )
    ),
  ARRAY[]::uuid[]
) AS stale_evidence_refs,
event.created_at
"""

_EVENT_GROUP_BY = """
event.event_id,
event.position,
event.event_family,
event.event_type,
event.observed_at,
event.bounded_payload,
event.created_at
"""

_EVENT_BY_ID_SQL = sql.SQL(
    """
SELECT {columns}
FROM milai.host_execution_event event
LEFT JOIN milai.host_execution_event_evidence_ref ref
  ON ref.tenant_id = event.tenant_id
 AND ref.event_id = event.event_id
LEFT JOIN milai.evidence_record evidence
  ON evidence.tenant_id = ref.tenant_id
 AND evidence.evidence_id = ref.evidence_id
WHERE event.tenant_id = %s
  AND event.created_by_actor_id = %s
  AND event.principal_binding_digest = %s
  AND event.project_id = %s
  AND event.task_ref = %s
  AND event.event_id = %s
GROUP BY {group_by}
"""
).format(columns=sql.SQL(_EVENT_COLUMNS), group_by=sql.SQL(_EVENT_GROUP_BY))

_WINDOW_SQL = sql.SQL(
    """
SELECT {columns}
FROM milai.host_execution_event event
LEFT JOIN milai.host_execution_event_evidence_ref ref
  ON ref.tenant_id = event.tenant_id
 AND ref.event_id = event.event_id
LEFT JOIN milai.evidence_record evidence
  ON evidence.tenant_id = ref.tenant_id
 AND evidence.evidence_id = ref.evidence_id
WHERE event.tenant_id = %s
  AND event.created_by_actor_id = %s
  AND event.principal_binding_digest = %s
  AND event.project_id = %s
  AND event.task_ref = %s
  AND event.position > %s
GROUP BY {group_by}
ORDER BY event.position
LIMIT %s
"""
).format(columns=sql.SQL(_EVENT_COLUMNS), group_by=sql.SQL(_EVENT_GROUP_BY))


def _binding_params(
    context: SessionContext,
    binding: HostExecutionEventAppendRequest | HostExecutionEventWindowRequest,
) -> tuple[object, ...]:
    return (
        context.tenant_id,
        context.actor_id,
        binding.principal_binding_digest,
        binding.project_id,
        binding.task_ref,
    )


def _record(row: tuple[Any, ...]) -> HostExecutionEventRecord:
    return HostExecutionEventRecord(
        event_id=UUID(str(row[0])),
        position=int(row[1]),
        event_family=str(row[2]),
        event_type=str(row[3]),
        observed_at=row[4],
        bounded_payload=dict(row[5]),
        evidence_refs=tuple(UUID(str(item)) for item in row[6]),
        stale_evidence_refs=tuple(UUID(str(item)) for item in row[7]),
        created_at=row[8],
    )
