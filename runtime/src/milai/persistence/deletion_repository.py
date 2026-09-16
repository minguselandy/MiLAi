from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Error

from milai.application.errors import CanonicalOperationError
from milai.persistence import Database, SessionContext

_SAFE_DATABASE_CODES = {
    "EVIDENCE_NOT_FOUND",
    "IDEMPOTENCY_CONFLICT",
    "REVOCATION_NOT_AUTHORIZED",
    "TENANT_MISMATCH",
}


@dataclass(frozen=True, slots=True)
class RevokeEvidenceCommand:
    evidence_id: UUID
    reason_code: str
    confirmation: str
    idempotency_key: str
    request_fingerprint: str


class DeletionRepository:
    def __init__(self, database: Database, steward_database: Database) -> None:
        self._database = database
        self._steward_database = steward_database

    def revoke(self, context: SessionContext, command: RevokeEvidenceCommand) -> dict[str, Any]:
        try:
            with self._steward_database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.tx05_revoke_evidence(
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.evidence_id,
                        command.reason_code,
                        command.confirmation,
                        command.idempotency_key,
                        command.request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            code = exc.diag.message_primary
            if code not in _SAFE_DATABASE_CODES:
                raise
            raise CanonicalOperationError(code) from exc
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("TX-05 returned a non-object result")
        return row[0]

    def submit_namespace_cleanup(
        self,
        context: SessionContext,
        *,
        project_id: str,
        reason_code: str,
        confirmation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        try:
            with self._steward_database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.submit_namespace_cleanup(
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        project_id,
                        reason_code,
                        confirmation,
                        idempotency_key,
                        request_fingerprint,
                    ),
                ).fetchone()
        except Error as exc:
            code = exc.diag.message_primary
            if code not in {
                "IDEMPOTENCY_CONFLICT",
                "NAMESPACE_CLEANUP_NOT_AUTHORIZED",
            }:
                raise
            raise CanonicalOperationError(code) from exc
        if row is None or not isinstance(row[0], dict):
            raise RuntimeError("namespace cleanup returned a non-object result")
        return row[0]

    def namespace_cleanup_status(
        self,
        context: SessionContext,
        cleanup_job_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any] | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                "SELECT milai.namespace_cleanup_status(%s, %s, %s, %s, %s)",
                (
                    context.tenant_id,
                    context.actor_id,
                    cleanup_job_id,
                    offset,
                    limit,
                ),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        if not isinstance(row[0], dict):
            raise RuntimeError("namespace cleanup status returned a non-object result")
        return row[0]

    def get(self, context: SessionContext, deletion_request_id: UUID) -> dict[str, Any] | None:
        return self._get(context, "deletion_request_id", deletion_request_id)

    def get_for_evidence(self, context: SessionContext, evidence_id: UUID) -> dict[str, Any] | None:
        return self._get(context, "evidence_id", evidence_id)

    def _get(self, context: SessionContext, key: str, identifier: UUID) -> dict[str, Any] | None:
        columns = """
            SELECT deletion_request_id, evidence_id, blob_id, reason_code,
                   requested_by_actor_id, logical_revocation_status,
                   canonical_block_status, derived_purge_status,
                   primary_bytes_status, backup_expiry_status,
                   retention_status, grounding_blocks_created,
                   context_pointers_invalidated, shared_live_reference_count,
                   last_error_code, purge_completed_at,
                   primary_bytes_erased_at, backup_expiry_completed_at,
                   primary_erasure_disposition, primary_erasure_proof_hash,
                   primary_erasure_verified_at,
                   requested_at
            FROM milai.deletion_request
        """
        if key == "deletion_request_id":
            query = columns + " WHERE tenant_id = %s AND deletion_request_id = %s"
        elif key == "evidence_id":
            query = columns + " WHERE tenant_id = %s AND evidence_id = %s"
        else:
            raise ValueError("unsupported deletion request lookup")
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                query,
                (context.tenant_id, identifier),
            ).fetchone()
        if row is None:
            return None
        keys = (
            "deletion_request_id",
            "evidence_id",
            "blob_id",
            "reason_code",
            "requested_by_actor_id",
            "logical_revocation_status",
            "canonical_block_status",
            "derived_purge_status",
            "primary_bytes_status",
            "backup_expiry_status",
            "retention_status",
            "grounding_blocks_created",
            "context_pointers_invalidated",
            "shared_live_reference_count",
            "last_error_code",
            "purge_completed_at",
            "primary_bytes_erased_at",
            "backup_expiry_completed_at",
            "primary_erasure_disposition",
            "primary_erasure_proof_hash",
            "primary_erasure_verified_at",
            "requested_at",
        )
        return _json_safe(dict(zip(keys, row, strict=True)))


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if isinstance(value, UUID):
            values[key] = str(value)
        elif isinstance(value, datetime):
            values[key] = value.isoformat()
    return values
