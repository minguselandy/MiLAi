from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import HostCognitiveStateError, IdempotencyConflict
from milai.domain.host_cognitive_state import (
    HostCognitiveBinding,
    HostCognitiveStateGetRequest,
    HostCognitiveStateUpdateRequest,
)
from milai.persistence.database import Database, SessionContext


@dataclass(frozen=True, slots=True)
class HostCognitiveStateRecord:
    state_id: UUID
    state_version_id: UUID
    version: int
    scope_type: str
    lifecycle: str
    payload: dict[str, Any]
    state_digest: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    stale_evidence_refs: tuple[UUID, ...]

    @property
    def expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class HostCognitiveStateWrite:
    request: HostCognitiveStateUpdateRequest
    operation_id: str
    request_fingerprint: str
    state_digest: str
    evidence_refs: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class HostCognitiveStateWriteResult:
    record: HostCognitiveStateRecord
    replayed: bool


class HostCognitiveStateRepository:
    """PostgreSQL boundary for one append-only Host working-state chain."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_current(
        self,
        context: SessionContext,
        binding: HostCognitiveStateGetRequest,
    ) -> HostCognitiveStateRecord | None:
        with self._database.connection(context) as connection:
            row = connection.execute(
                """
                SELECT head.state_id, version.state_version_id, version.version,
                       head.scope_type, head.lifecycle, version.payload_json,
                       version.state_digest, head.created_at, head.updated_at,
                       head.expires_at
                FROM milai.host_cognitive_state head
                JOIN milai.host_cognitive_state_version version
                  ON version.tenant_id = head.tenant_id
                 AND version.state_id = head.state_id
                 AND version.state_version_id = head.current_state_version_id
                WHERE head.tenant_id = %s
                  AND head.created_by_actor_id = %s
                  AND head.principal_binding_digest = %s
                  AND head.project_id = %s
                  AND head.scope_type = %s
                  AND head.scope_ref = %s
                  AND head.lifecycle = 'ACTIVE'
                ORDER BY head.created_at DESC
                LIMIT 1
                """,
                _binding_params(context, binding),
            ).fetchone()
            stale: tuple[UUID, ...] = ()
            if row is not None:
                stale_rows = connection.execute(
                    """
                    SELECT ref.evidence_id
                    FROM milai.host_cognitive_state_evidence_ref ref
                    LEFT JOIN milai.evidence_record evidence
                      ON evidence.tenant_id = ref.tenant_id
                     AND evidence.evidence_id = ref.evidence_id
                    WHERE ref.tenant_id = %s
                      AND ref.state_version_id = %s
                      AND (
                        evidence.evidence_id IS NULL
                        OR evidence.revoked_at IS NOT NULL
                        OR evidence.retention_state <> 'READABLE'
                        OR evidence.permission_snapshot @> '{"readable": true}'::jsonb IS NOT TRUE
                      )
                    ORDER BY ref.evidence_id
                    """,
                    (context.tenant_id, row[1]),
                ).fetchall()
                stale = tuple(UUID(str(item[0])) for item in stale_rows)
            connection.execute(
                """
                INSERT INTO milai.operational_event (
                  tenant_id, event_id, event_type, reason_code, safe_metadata,
                  created_by_actor_id
                ) VALUES (
                  %s, gen_random_uuid(), 'HOST_WORKING_STATE_ACCESSED', NULL,
                  jsonb_build_object(
                    'state_id', %s::text,
                    'scope_type', %s::text,
                    'scope_ref_sha256', encode(sha256(convert_to(%s::text, 'UTF8')), 'hex'),
                    'found', %s::boolean
                  ), %s
                )
                """,
                (
                    context.tenant_id,
                    str(row[0]) if row is not None else None,
                    binding.scope_type,
                    binding.scope_ref,
                    row is not None,
                    context.actor_id,
                ),
            )
        return _record(row, stale) if row is not None else None

    def write(
        self,
        context: SessionContext,
        command: HostCognitiveStateWrite,
    ) -> HostCognitiveStateWriteResult:
        request = command.request
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.update_host_cognitive_state(
                      %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        request.state_id,
                        request.expected_version,
                        request.principal_binding_digest,
                        request.project_id,
                        request.scope_type,
                        request.scope_ref,
                        Jsonb(request.payload),
                        command.state_digest,
                        list(command.evidence_refs),
                        command.operation_id,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            code = exc.diag.message_primary or "HOST_WORKING_STATE_REJECTED"
            if code == "IDEMPOTENCY_CONFLICT":
                raise IdempotencyConflict("operation ID has a different payload") from exc
            if code in {
                "EVIDENCE_REFERENCE_INVALID",
                "HOST_WORKING_STATE_EXPIRED",
                "HOST_WORKING_STATE_NOT_FOUND",
                "HOST_WORKING_STATE_SCOPE_DENIED",
                "INVALID_HOST_WORKING_STATE",
                "STALE_WORKING_STATE",
                "TENANT_MISMATCH",
            }:
                raise HostCognitiveStateError(code) from exc
            raise
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("Host cognitive state procedure returned no result")
        payload: dict[str, Any] = row[0]
        if payload.get("status") == "STALE_WORKING_STATE":
            raise HostCognitiveStateError(
                "STALE_WORKING_STATE",
                current_version=int(payload["current_version"]),
                state_id=str(payload["state_id"]),
            )
        record = self._get_by_version_id(
            context,
            state_id=UUID(str(payload["state_id"])),
            state_version_id=UUID(str(payload["state_version_id"])),
            expires_at=payload["expires_at"],
        )
        if record is None:
            raise RuntimeError("persisted Host cognitive state is not readable")
        return HostCognitiveStateWriteResult(record, bool(payload.get("replayed")))

    def _get_by_version_id(
        self,
        context: SessionContext,
        *,
        state_id: UUID,
        state_version_id: UUID,
        expires_at: object,
    ) -> HostCognitiveStateRecord | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT head.state_id, version.state_version_id, version.version,
                       head.scope_type, 'ACTIVE', version.payload_json,
                       version.state_digest, head.created_at, version.created_at,
                       %s::timestamptz
                FROM milai.host_cognitive_state head
                JOIN milai.host_cognitive_state_version version
                  ON version.tenant_id = head.tenant_id
                 AND version.state_id = head.state_id
                WHERE head.tenant_id = %s
                  AND head.state_id = %s
                  AND version.state_version_id = %s
                """,
                (expires_at, context.tenant_id, state_id, state_version_id),
            ).fetchone()
            if row is None:
                return None
            stale_rows = connection.execute(
                """
                SELECT ref.evidence_id
                FROM milai.host_cognitive_state_evidence_ref ref
                LEFT JOIN milai.evidence_record evidence
                  ON evidence.tenant_id = ref.tenant_id
                 AND evidence.evidence_id = ref.evidence_id
                WHERE ref.tenant_id = %s AND ref.state_version_id = %s
                  AND (
                    evidence.evidence_id IS NULL
                    OR evidence.revoked_at IS NOT NULL
                    OR evidence.retention_state <> 'READABLE'
                    OR evidence.permission_snapshot @> '{"readable": true}'::jsonb IS NOT TRUE
                  )
                ORDER BY ref.evidence_id
                """,
                (context.tenant_id, row[1]),
            ).fetchall()
        return _record(row, tuple(UUID(str(item[0])) for item in stale_rows))


def _binding_params(
    context: SessionContext,
    binding: HostCognitiveBinding,
) -> tuple[object, ...]:
    return (
        context.tenant_id,
        context.actor_id,
        binding.principal_binding_digest,
        binding.project_id,
        binding.scope_type,
        binding.scope_ref,
    )


def _record(
    row: tuple[Any, ...],
    stale: tuple[UUID, ...],
) -> HostCognitiveStateRecord:
    return HostCognitiveStateRecord(
        state_id=UUID(str(row[0])),
        state_version_id=UUID(str(row[1])),
        version=int(row[2]),
        scope_type=str(row[3]),
        lifecycle=str(row[4]),
        payload=dict(row[5]),
        state_digest=str(row[6]),
        created_at=row[7],
        updated_at=row[8],
        expires_at=row[9],
        stale_evidence_refs=stale,
    )
