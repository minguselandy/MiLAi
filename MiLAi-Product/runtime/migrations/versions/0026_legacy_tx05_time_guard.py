"""Certify the complete candidate.1 TX-05 transaction timestamp.

Revision ID: 0026_legacy_tx05_time_guard
Revises: 0025_legacy_provenance_guard

Candidate.5 corrects the unaccepted 0024 and 0025 proof predicates so fresh
and candidate.3-compatible databases fail before governance reconstruction.
This proof-only forward revision is the compatibility gate for development
databases that already reached candidate.4 revision 0025.  It certifies that
DeletionRequest, Evidence revocation, idempotency, OperationalEvent, and both
Outbox legs retain the one PostgreSQL transaction timestamp emitted by the
candidate.1 public TX-05 procedure.  It creates no replacement authority.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026_legacy_tx05_time_guard"
down_revision: str | None = "0025_legacy_provenance_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _lock_sources()
    _prove_legacy_tx05_source()


def _lock_sources() -> None:
    # Proof and Alembic head advancement share the migration transaction.  The
    # service is expected to be offline, and the explicit locks prevent an
    # owner/session race from changing any provenance leg after validation.
    op.execute(
        """
        LOCK TABLE
          milai.evidence_record,
          milai.deletion_request,
          milai.idempotency_record,
          milai.operational_event,
          milai.outbox_event
        IN ACCESS EXCLUSIVE MODE
        """
    )


def _prove_legacy_tx05_source() -> None:
    op.execute(
        """
        DO $tx05_time_proof$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM milai.outbox_event revoke_event
            WHERE revoke_event.event_type = 'EVIDENCE_REVOKED'
              AND NOT (
                revoke_event.payload ? 'proposal_id'
                AND revoke_event.payload ? 'decision_id'
              )
              AND NOT EXISTS (
                SELECT 1
                FROM milai.evidence_record evidence
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = evidence.tenant_id
                 AND deletion.evidence_id = evidence.evidence_id
                 AND deletion.blob_id = evidence.blob_id
                 AND deletion.deletion_request_id::text =
                     revoke_event.payload ->> 'deletion_request_id'
                 AND deletion.requested_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND deletion.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND deletion.requested_at = evidence.revoked_at
                 AND deletion.logical_revocation_status = 'APPLIED'
                 AND deletion.canonical_block_status = 'APPLIED'
                 AND deletion.derived_purge_status IN (
                   'PENDING', 'PROCESSING', 'COMPLETED', 'DEAD_LETTER'
                 )
                 AND deletion.primary_bytes_status IN (
                   'PENDING', 'BLOCKED_SHARED_REFERENCE', 'RETENTION_BLOCKED',
                   'ERASED', 'ERROR'
                 )
                 AND deletion.backup_expiry_status IN (
                   'PENDING', 'RETENTION_BLOCKED', 'COMPLETED'
                 )
                 AND deletion.retention_status IN (
                   'CLEAR', 'LEGAL_HOLD', 'UNREADABLE'
                 )
                JOIN milai.idempotency_record idempotency
                  ON idempotency.tenant_id = evidence.tenant_id
                 AND idempotency.operation_family = 'TX-05_EVIDENCE_REVOKE'
                 AND idempotency.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND idempotency.created_at = deletion.requested_at
                 AND idempotency.response_payload ->> 'canonical_commit_seq' =
                     revoke_event.canonical_commit_seq::text
                 AND idempotency.response_payload ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND idempotency.response_payload ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND idempotency.response_payload ->> 'logical_revocation_status' =
                     'APPLIED'
                 AND idempotency.response_payload ->> 'canonical_block_status' =
                     'APPLIED'
                 AND idempotency.response_payload ->> 'derived_purge_status' =
                     'PENDING'
                 AND idempotency.response_payload ->> 'grounding_blocks_created' =
                     deletion.grounding_blocks_created::text
                 AND idempotency.response_payload ->> 'context_pointers_invalidated' =
                     deletion.context_pointers_invalidated::text
                 AND idempotency.response_payload ->> 'shared_live_reference_count' =
                     deletion.shared_live_reference_count::text
                 AND idempotency.response_payload ->> 'revoke_outbox_id' =
                     revoke_event.outbox_id::text
                JOIN milai.operational_event operational
                  ON operational.tenant_id = evidence.tenant_id
                 AND operational.event_type = 'EVIDENCE_REVOKED'
                 AND operational.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND operational.created_at = deletion.requested_at
                 AND operational.reason_code = deletion.reason_code
                 AND operational.safe_metadata ->> 'canonical_commit_seq' =
                     revoke_event.canonical_commit_seq::text
                 AND operational.safe_metadata ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND operational.safe_metadata ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND operational.safe_metadata ->> 'grounding_blocks_created' =
                     deletion.grounding_blocks_created::text
                 AND operational.safe_metadata ->> 'context_pointers_invalidated' =
                     deletion.context_pointers_invalidated::text
                 AND operational.safe_metadata ->> 'shared_live_reference_count' =
                     deletion.shared_live_reference_count::text
                JOIN milai.outbox_event purge_event
                  ON purge_event.tenant_id = evidence.tenant_id
                 AND purge_event.aggregate_type = 'DELETION_REQUEST'
                 AND purge_event.aggregate_id = deletion.deletion_request_id
                 AND purge_event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                 AND purge_event.canonical_commit_seq =
                     revoke_event.canonical_commit_seq
                 AND purge_event.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND purge_event.created_at = deletion.requested_at
                 AND purge_event.payload ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND purge_event.payload ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND purge_event.payload ->> 'blob_id' = deletion.blob_id::text
                 AND purge_event.payload ->> 'primary_bytes_status' =
                     idempotency.response_payload ->> 'primary_bytes_status'
                 AND purge_event.payload ->> 'retention_status' =
                     idempotency.response_payload ->> 'retention_status'
                 AND idempotency.response_payload ->> 'purge_outbox_id' =
                     purge_event.outbox_id::text
                WHERE evidence.tenant_id = revoke_event.tenant_id
                  AND evidence.evidence_id::text =
                      revoke_event.payload ->> 'evidence_id'
                  AND revoke_event.aggregate_type = 'EVIDENCE'
                  AND revoke_event.aggregate_id = evidence.evidence_id
                  AND revoke_event.created_at = deletion.requested_at
                  AND revoke_event.payload ->> 'deletion_request_id' IS NOT NULL
                  AND evidence.revoked_at IS NOT NULL
                  AND evidence.revocation_reason = deletion.reason_code
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_UNPROVABLE_LEGACY_TX05';
          END IF;
        END
        $tx05_time_proof$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0026 downgrade is intentionally unsupported for a certified legacy provenance head"
    )
