"""Require a durable absence proof before recording Blob erasure.

Revision ID: 0019_erasure_proof
Revises: 0018_causal_trace
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_erasure_proof"
down_revision: str | None = "0018_causal_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SIGNATURE = "uuid, uuid, uuid, text"
NEW_SIGNATURE = "uuid, uuid, uuid, text, text, text, text, text"


def upgrade() -> None:
    for table, prefix in (
        ("content_blob", "erasure"),
        ("deletion_request", "primary_erasure"),
    ):
        op.add_column(
            table,
            sa.Column(f"{prefix}_disposition", sa.Text(), nullable=True),
            schema="milai",
        )
        op.add_column(
            table,
            sa.Column(f"{prefix}_proof_hash", sa.String(length=64), nullable=True),
            schema="milai",
        )
        op.add_column(
            table,
            sa.Column(
                f"{prefix}_verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            schema="milai",
        )
        op.create_check_constraint(
            f"ck_{table}_{prefix}_proof",
            table,
            f"({prefix}_disposition IS NULL AND {prefix}_proof_hash IS NULL "
            f"AND {prefix}_verified_at IS NULL) OR ("
            f"{prefix}_disposition IN ("
            "'ERASED_AND_VERIFIED_ABSENT', 'VERIFIED_ALREADY_ABSENT') "
            f"AND {prefix}_proof_hash ~ '^[0-9a-f]{{64}}$' "
            f"AND {prefix}_verified_at IS NOT NULL)",
            schema="milai",
        )

    op.execute(
        f"ALTER FUNCTION milai.complete_blob_erasure({OLD_SIGNATURE}) "
        "RENAME TO complete_blob_erasure_legacy"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.complete_blob_erasure_legacy({OLD_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    _create_completion_function()


def _create_completion_function() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.complete_blob_erasure(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_blob_id uuid,
          p_worker_id text,
          p_disposition text,
          p_proof_hash text,
          p_storage_uri text,
          p_content_hash text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_blob milai.content_blob%ROWTYPE;
          v_expected_proof text;
          v_first_verification boolean;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_disposition NOT IN (
               'ERASED_AND_VERIFIED_ABSENT', 'VERIFIED_ALREADY_ABSENT'
             )
             OR p_proof_hash !~ '^[0-9a-f]{64}$'
             OR length(p_worker_id) NOT BETWEEN 1 AND 255 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_ERASURE_PROOF';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM milai.projection_delivery delivery
            JOIN milai.outbox_event event
              ON event.tenant_id = delivery.tenant_id
             AND event.outbox_id = delivery.outbox_id
            JOIN milai.deletion_request deletion
              ON deletion.tenant_id = event.tenant_id
             AND deletion.deletion_request_id = event.aggregate_id
            WHERE delivery.tenant_id = p_tenant_id
              AND delivery.projection_name = 'purge'
              AND delivery.state = 'PROCESSING'
              AND delivery.lease_owner = p_worker_id
              AND delivery.lease_expires_at > CURRENT_TIMESTAMP
              AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
              AND deletion.blob_id = p_blob_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF EXISTS (
            SELECT 1 FROM milai.evidence_record evidence
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.blob_id = p_blob_id
              AND (
                evidence.revoked_at IS NULL
                OR evidence.retention_state IN ('LEGAL_HOLD', 'UNREADABLE')
              )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BLOB_STILL_REFERENCED';
          END IF;
          SELECT * INTO v_blob
          FROM milai.content_blob
          WHERE tenant_id = p_tenant_id AND blob_id = p_blob_id
          FOR UPDATE;
          IF NOT FOUND
             OR v_blob.physical_delete_state NOT IN ('PURGE_PENDING', 'ERASED') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BLOB_NOT_PURGEABLE';
          END IF;
          IF v_blob.storage_uri IS DISTINCT FROM p_storage_uri
             OR v_blob.content_hash IS DISTINCT FROM p_content_hash THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ERASURE_IDENTITY_MISMATCH';
          END IF;
          v_expected_proof := encode(sha256(convert_to(
            'milai-erasure-proof-v1' || chr(10)
            || p_tenant_id::text || chr(10)
            || p_storage_uri || chr(10)
            || p_content_hash || chr(10)
            || p_disposition,
            'UTF8'
          )), 'hex');
          IF v_expected_proof <> p_proof_hash THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_ERASURE_PROOF';
          END IF;

          v_first_verification := v_blob.erasure_verified_at IS NULL;
          UPDATE milai.content_blob
          SET physical_delete_state = 'ERASED',
              erasure_disposition = COALESCE(erasure_disposition, p_disposition),
              erasure_proof_hash = COALESCE(erasure_proof_hash, p_proof_hash),
              erasure_verified_at = COALESCE(erasure_verified_at, CURRENT_TIMESTAMP)
          WHERE tenant_id = p_tenant_id AND blob_id = p_blob_id;
          UPDATE milai.deletion_request
          SET primary_bytes_status = 'ERASED',
              primary_bytes_erased_at = COALESCE(
                primary_bytes_erased_at, CURRENT_TIMESTAMP
              ),
              primary_erasure_disposition = COALESCE(
                primary_erasure_disposition, p_disposition
              ),
              primary_erasure_proof_hash = COALESCE(
                primary_erasure_proof_hash, p_proof_hash
              ),
              primary_erasure_verified_at = COALESCE(
                primary_erasure_verified_at, CURRENT_TIMESTAMP
              ),
              last_error_code = NULL
          WHERE tenant_id = p_tenant_id AND blob_id = p_blob_id
            AND retention_status = 'CLEAR';
          IF v_first_verification THEN
            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), 'BLOB_ERASURE_VERIFIED',
              p_disposition,
              jsonb_build_object(
                'blob_id', p_blob_id,
                'content_hash', p_content_hash,
                'storage_uri', p_storage_uri,
                'proof_hash', p_proof_hash,
                'worker_id_sha256', encode(
                  sha256(convert_to(p_worker_id, 'UTF8')), 'hex'
                )
              ), p_actor_id
            );
          END IF;
          RETURN jsonb_build_object(
            'blob_id', p_blob_id,
            'physical_delete_state', 'ERASED',
            'erasure_disposition', COALESCE(
              v_blob.erasure_disposition, p_disposition
            ),
            'erasure_proof_hash', COALESCE(
              v_blob.erasure_proof_hash, p_proof_hash
            )
          );
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION milai.complete_blob_erasure({NEW_SIGNATURE}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.complete_blob_erasure({NEW_SIGNATURE}) TO milai_worker"
    )


def downgrade() -> None:
    proof_count = (
        op.get_bind()
        .execute(
            sa.text("SELECT count(*) FROM milai.content_blob WHERE erasure_verified_at IS NOT NULL")
        )
        .scalar_one()
    )
    if proof_count:
        raise RuntimeError("0019 downgrade is unsafe after an erasure proof was recorded")
    raise RuntimeError("0019 downgrade requires an explicit compatibility migration")
