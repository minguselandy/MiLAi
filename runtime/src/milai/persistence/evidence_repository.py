from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Error
from psycopg.types.json import Jsonb

from milai.application.errors import BlobPurgeRace, IdempotencyConflict, TenantMismatch
from milai.persistence.database import Database, SessionContext


@dataclass(frozen=True, slots=True)
class IngestEvidenceCommand:
    idempotency_key: str
    request_fingerprint: str
    source_type: str
    source_ref: str
    subject_id: str
    source_speaker: str | None
    source_context: dict[str, object] | None
    observed_at: datetime
    content_hash: str
    storage_uri: str
    byte_length: int
    media_type: str
    permission_snapshot: dict[str, object]
    retention_state: str


@dataclass(frozen=True, slots=True)
class IngestEvidenceResult:
    evidence_id: UUID
    blob_id: UUID
    outbox_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    tenant_id: UUID
    evidence_id: UUID
    source_type: str
    source_ref: str
    subject_id: str
    source_speaker: str | None
    speaker_source: str
    source_session_id: str | None
    source_turn_id: str | None
    source_turn_ordinal: int | None
    source_round_id: str | None
    source_round_ordinal: int | None
    previous_source_turn_id: str | None
    next_source_turn_id: str | None
    source_context_source: str
    observed_at: datetime
    captured_at: datetime
    blob_id: UUID
    content_hash: str
    storage_uri: str
    byte_length: int
    media_type: str
    permission_snapshot: dict[str, object]
    retention_state: str
    revoked_at: datetime | None
    revocation_reason: str | None


class EvidenceRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def ingest(
        self, context: SessionContext, command: IngestEvidenceCommand
    ) -> IngestEvidenceResult:
        try:
            with self._database.connection(context) as connection:
                row = connection.execute(
                    """
                    SELECT milai.tx01_ingest_evidence_with_context(
                      %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        context.tenant_id,
                        context.actor_id,
                        command.idempotency_key,
                        command.request_fingerprint,
                        command.source_type,
                        command.source_ref,
                        command.subject_id,
                        command.source_speaker,
                        (
                            Jsonb(command.source_context)
                            if command.source_context is not None
                            else None
                        ),
                        command.observed_at,
                        command.content_hash,
                        command.storage_uri,
                        command.byte_length,
                        command.media_type,
                        Jsonb(command.permission_snapshot),
                        command.retention_state,
                    ),
                ).fetchone()
        except Error as exc:
            message = exc.diag.message_primary
            if message == "IDEMPOTENCY_CONFLICT":
                raise IdempotencyConflict("idempotency key has a different fingerprint") from exc
            if message == "TENANT_MISMATCH":
                raise TenantMismatch("database tenant context does not match request") from exc
            if message == "BLOB_PURGE_RACE":
                raise BlobPurgeRace("blob is concurrently being purged") from exc
            raise
        if row is None:
            raise RuntimeError("TX-01 returned no result")
        payload: dict[str, Any] = row[0]
        return IngestEvidenceResult(
            evidence_id=UUID(payload["evidence_id"]),
            blob_id=UUID(payload["blob_id"]),
            outbox_id=UUID(payload["outbox_id"]),
            replayed=bool(payload["replayed"]),
        )

    def get(self, context: SessionContext, evidence_id: UUID) -> EvidenceRecord | None:
        with self._database.connection(context, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT
                  e.tenant_id, e.evidence_id, e.source_type, e.source_ref,
                  e.subject_id, e.source_speaker, e.speaker_source,
                  e.source_session_id, e.source_turn_id, e.source_turn_ordinal,
                  e.source_round_id, e.source_round_ordinal,
                  e.previous_source_turn_id, e.next_source_turn_id,
                  e.source_context_source,
                  e.observed_at, e.captured_at, e.blob_id,
                  e.content_hash, b.storage_uri, b.byte_length, b.media_type,
                  e.permission_snapshot, e.retention_state,
                  e.revoked_at, e.revocation_reason
                FROM milai.evidence_record AS e
                JOIN milai.content_blob AS b
                  ON b.tenant_id = e.tenant_id AND b.blob_id = e.blob_id
                WHERE e.tenant_id = %s AND e.evidence_id = %s
                """,
                (context.tenant_id, evidence_id),
            ).fetchone()
        if row is None:
            return None
        return EvidenceRecord(*row)

    def lineage(
        self, context: SessionContext, evidence_id: UUID
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        with self._database.connection(context, read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT claim_version_id, open_issue_id, relation_type
                FROM milai.grounding_relation
                WHERE tenant_id = %s AND evidence_id = %s
                ORDER BY relation_type, relation_id
                """,
                (context.tenant_id, evidence_id),
            ).fetchall()
        claim_versions = [
            {
                "claim_version_id": str(claim_version_id),
                "relation_type": relation_type,
            }
            for claim_version_id, open_issue_id, relation_type in rows
            if claim_version_id is not None
        ]
        open_issues = [
            {"open_issue_id": str(open_issue_id), "relation_type": relation_type}
            for claim_version_id, open_issue_id, relation_type in rows
            if open_issue_id is not None
        ]
        return claim_versions, open_issues
