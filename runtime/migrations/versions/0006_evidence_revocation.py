"""Add fail-closed Evidence revocation and deletion tracking.

Revision ID: 0006_evidence_revocation
Revises: 0005_canonical_procedures

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_evidence_revocation"
down_revision: str | None = "0005_canonical_procedures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TX05_SIGNATURE = "uuid, uuid, uuid, text, text, text, text"


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation
        ON milai.{table}
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )


def upgrade() -> None:
    op.create_table(
        "context_capsule",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capsule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("protected_sections", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "capsule_id", name="pk_context_capsule"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INVALIDATED', 'EXPIRED')",
            name="ck_context_capsule_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(protected_sections) = 'object'",
            name="ck_context_capsule_sections",
        ),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_context_capsule_hash"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND invalidated_at IS NULL AND invalidation_reason IS NULL) OR "
            "(status <> 'ACTIVE' AND invalidated_at IS NOT NULL "
            "AND invalidation_reason IS NOT NULL)",
            name="ck_context_capsule_invalidation",
        ),
        schema="milai",
    )
    op.create_table(
        "context_pointer",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pointer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capsule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pointer_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "pointer_id", name="pk_context_pointer"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "capsule_id"],
            ["milai.context_capsule.tenant_id", "milai.context_capsule.capsule_id"],
            name="fk_context_pointer_capsule",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_context_pointer_evidence",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "capsule_id",
            "evidence_id",
            "pointer_hash",
            name="uq_context_pointer_identity",
        ),
        sa.CheckConstraint("pointer_hash ~ '^[0-9a-f]{64}$'", name="ck_context_pointer_hash"),
        sa.CheckConstraint("state IN ('ACTIVE', 'INVALIDATED')", name="ck_context_pointer_state"),
        sa.CheckConstraint(
            "(state = 'ACTIVE' AND invalidated_at IS NULL AND invalidation_reason IS NULL) OR "
            "(state = 'INVALIDATED' AND invalidated_at IS NOT NULL "
            "AND invalidation_reason IS NOT NULL)",
            name="ck_context_pointer_invalidation",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_context_pointer_evidence",
        "context_pointer",
        ["tenant_id", "evidence_id", "state"],
        schema="milai",
    )

    op.create_table(
        "deletion_request",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deletion_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("requested_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_revocation_status", sa.Text(), nullable=False),
        sa.Column("canonical_block_status", sa.Text(), nullable=False),
        sa.Column("derived_purge_status", sa.Text(), nullable=False),
        sa.Column("primary_bytes_status", sa.Text(), nullable=False),
        sa.Column("backup_expiry_status", sa.Text(), nullable=False),
        sa.Column("retention_status", sa.Text(), nullable=False),
        sa.Column("grounding_blocks_created", sa.Integer(), nullable=False),
        sa.Column("context_pointers_invalidated", sa.Integer(), nullable=False),
        sa.Column("shared_live_reference_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("purge_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_bytes_erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backup_expiry_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "deletion_request_id", name="pk_deletion_request"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_deletion_request_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "blob_id"],
            ["milai.content_blob.tenant_id", "milai.content_blob.blob_id"],
            name="fk_deletion_request_blob",
        ),
        sa.UniqueConstraint("tenant_id", "evidence_id", name="uq_deletion_request_evidence"),
        sa.CheckConstraint(
            "logical_revocation_status = 'APPLIED'",
            name="ck_deletion_logical_revocation",
        ),
        sa.CheckConstraint(
            "canonical_block_status = 'APPLIED'",
            name="ck_deletion_canonical_block",
        ),
        sa.CheckConstraint(
            "derived_purge_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'DEAD_LETTER')",
            name="ck_deletion_derived_purge",
        ),
        sa.CheckConstraint(
            "primary_bytes_status IN ("
            "'PENDING', 'BLOCKED_SHARED_REFERENCE', 'RETENTION_BLOCKED', "
            "'ERASED', 'ERROR')",
            name="ck_deletion_primary_bytes",
        ),
        sa.CheckConstraint(
            "backup_expiry_status IN ('PENDING', 'RETENTION_BLOCKED', 'COMPLETED')",
            name="ck_deletion_backup_expiry",
        ),
        sa.CheckConstraint(
            "retention_status IN ('CLEAR', 'LEGAL_HOLD', 'UNREADABLE')",
            name="ck_deletion_retention",
        ),
        sa.CheckConstraint(
            "grounding_blocks_created >= 0 AND context_pointers_invalidated >= 0 "
            "AND shared_live_reference_count >= 0",
            name="ck_deletion_counts",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_deletion_request_progress",
        "deletion_request",
        ["tenant_id", "derived_purge_status", "primary_bytes_status", "requested_at"],
        schema="milai",
    )

    for table in ("context_capsule", "context_pointer", "deletion_request"):
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.tx05_revoke_evidence(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_evidence_id uuid,
          p_reason_code text,
          p_confirmation text,
          p_idempotency_key text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_evidence milai.evidence_record%ROWTYPE;
          v_existing milai.deletion_request%ROWTYPE;
          v_issue milai.open_issue%ROWTYPE;
          v_deletion_request_id uuid;
          v_revoke_outbox_id uuid;
          v_purge_outbox_id uuid;
          v_commit_seq bigint;
          v_block_count integer;
          v_pointer_count integer;
          v_shared_count integer;
          v_to_status text;
          v_event_type text;
          v_retention_status text;
          v_primary_status text;
          v_backup_status text;
          v_affected_claim_ids jsonb;
          v_affected_issue_ids jsonb;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_confirmation <> 'REVOKE'
             OR length(btrim(p_reason_code)) = 0
             OR length(p_reason_code) > 255 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'REVOCATION_NOT_AUTHORIZED';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'TX-05_EVIDENCE_REVOKE', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'TX-05_EVIDENCE_REVOKE'
            AND idempotency_key = p_idempotency_key
          FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          SELECT * INTO v_evidence
          FROM milai.evidence_record
          WHERE tenant_id = p_tenant_id AND evidence_id = p_evidence_id
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EVIDENCE_NOT_FOUND';
          END IF;
          SELECT * INTO v_existing
          FROM milai.deletion_request
          WHERE tenant_id = p_tenant_id AND evidence_id = p_evidence_id;
          IF FOUND THEN
            v_response := jsonb_build_object(
              'deletion_request_id', v_existing.deletion_request_id,
              'evidence_id', p_evidence_id,
              'logical_revocation_status', v_existing.logical_revocation_status,
              'canonical_block_status', v_existing.canonical_block_status,
              'derived_purge_status', v_existing.derived_purge_status,
              'primary_bytes_status', v_existing.primary_bytes_status,
              'backup_expiry_status', v_existing.backup_expiry_status,
              'retention_status', v_existing.retention_status,
              'replayed', true
            );
            UPDATE milai.idempotency_record SET response_payload = v_response
            WHERE tenant_id = p_tenant_id
              AND operation_family = 'TX-05_EVIDENCE_REVOKE'
              AND idempotency_key = p_idempotency_key;
            RETURN v_response;
          END IF;

          v_commit_seq := nextval('milai.canonical_commit_seq');
          UPDATE milai.evidence_record
          SET revoked_at = CURRENT_TIMESTAMP, revocation_reason = p_reason_code
          WHERE tenant_id = p_tenant_id AND evidence_id = p_evidence_id
            AND revoked_at IS NULL;

          INSERT INTO milai.grounding_block (
            tenant_id, block_id, claim_version_id, caused_by_evidence_id,
            block_type, active, created_by_actor_id
          ) SELECT
            p_tenant_id, gen_random_uuid(), gr.claim_version_id,
            p_evidence_id, 'EVIDENCE_REVOKED', true, p_actor_id
          FROM milai.grounding_relation gr
          WHERE gr.tenant_id = p_tenant_id
            AND gr.evidence_id = p_evidence_id
            AND gr.claim_version_id IS NOT NULL
          ON CONFLICT (
            tenant_id, claim_version_id, caused_by_evidence_id, block_type
          ) WHERE active DO NOTHING;
          GET DIAGNOSTICS v_block_count = ROW_COUNT;

          v_affected_claim_ids := COALESCE((
            SELECT jsonb_agg(DISTINCT cv.claim_id)
            FROM milai.grounding_relation gr
            JOIN milai.claim_version cv
              ON cv.tenant_id = gr.tenant_id
             AND cv.claim_version_id = gr.claim_version_id
            WHERE gr.tenant_id = p_tenant_id
              AND gr.evidence_id = p_evidence_id
          ), '[]'::jsonb);
          v_affected_issue_ids := COALESCE((
            SELECT jsonb_agg(DISTINCT oi.issue_id)
            FROM milai.open_issue oi
            WHERE oi.tenant_id = p_tenant_id
              AND (
                (
                  oi.status NOT IN ('RESOLVED', 'DISMISSED')
                  AND EXISTS (
                    SELECT 1 FROM milai.grounding_relation gr
                    WHERE gr.tenant_id = oi.tenant_id
                      AND gr.open_issue_id = oi.issue_id
                      AND gr.evidence_id = p_evidence_id
                  )
                ) OR (
                  oi.status = 'RESOLVED'
                  AND EXISTS (
                    SELECT 1
                    FROM milai.grounding_relation gr
                    JOIN milai.steward_decision sd
                      ON sd.tenant_id = gr.tenant_id
                     AND sd.decision_id = oi.resolved_by_decision_id
                     AND sd.proposal_id = gr.created_from_proposal_id
                    WHERE gr.tenant_id = oi.tenant_id
                      AND gr.open_issue_id = oi.issue_id
                      AND gr.evidence_id = p_evidence_id
                      AND gr.relation_type = 'RESOLUTION_CANDIDATE'
                  )
                )
              )
          ), '[]'::jsonb);

          FOR v_issue IN
            SELECT oi.*
            FROM milai.open_issue oi
            WHERE oi.tenant_id = p_tenant_id
              AND (
                (
                  oi.status NOT IN ('RESOLVED', 'DISMISSED')
                  AND EXISTS (
                    SELECT 1 FROM milai.grounding_relation gr
                    WHERE gr.tenant_id = oi.tenant_id
                      AND gr.open_issue_id = oi.issue_id
                      AND gr.evidence_id = p_evidence_id
                  )
                ) OR (
                  oi.status = 'RESOLVED'
                  AND EXISTS (
                    SELECT 1
                    FROM milai.grounding_relation gr
                    JOIN milai.steward_decision sd
                      ON sd.tenant_id = gr.tenant_id
                     AND sd.decision_id = oi.resolved_by_decision_id
                     AND sd.proposal_id = gr.created_from_proposal_id
                    WHERE gr.tenant_id = oi.tenant_id
                      AND gr.open_issue_id = oi.issue_id
                      AND gr.evidence_id = p_evidence_id
                      AND gr.relation_type = 'RESOLUTION_CANDIDATE'
                  )
                )
              )
            ORDER BY oi.issue_id
            FOR UPDATE
          LOOP
            IF v_issue.status IN ('RESOLVED', 'READY_FOR_REVIEW') THEN
              v_to_status := 'WAITING_EVIDENCE';
            ELSE
              v_to_status := v_issue.status;
            END IF;
            IF v_issue.status = 'RESOLVED' THEN
              v_event_type := 'RESOLUTION_EVIDENCE_REVOKED';
            ELSE
              v_event_type := 'ISSUE_EVIDENCE_REVOKED';
            END IF;
            UPDATE milai.open_issue
            SET status = v_to_status, revision = revision + 1,
                resolved_by_decision_id = NULL, resolved_at = NULL
            WHERE tenant_id = p_tenant_id AND issue_id = v_issue.issue_id
              AND revision = v_issue.revision;
            INSERT INTO milai.open_issue_transition (
              tenant_id, transition_id, issue_id, from_status, to_status,
              from_revision, to_revision, event_type, proposal_id,
              decision_id, policy_version, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_issue.issue_id,
              v_issue.status, v_to_status, v_issue.revision,
              v_issue.revision + 1, v_event_type, NULL, NULL,
              'tx05-revoke-v1', v_commit_seq, p_actor_id
            );
          END LOOP;

          UPDATE milai.context_pointer
          SET state = 'INVALIDATED', invalidated_at = CURRENT_TIMESTAMP,
              invalidation_reason = 'EVIDENCE_REVOKED'
          WHERE tenant_id = p_tenant_id AND evidence_id = p_evidence_id
            AND state = 'ACTIVE';
          GET DIAGNOSTICS v_pointer_count = ROW_COUNT;
          UPDATE milai.context_capsule capsule
          SET status = 'INVALIDATED', invalidated_at = CURRENT_TIMESTAMP,
              invalidation_reason = 'EVIDENCE_REVOKED'
          WHERE capsule.tenant_id = p_tenant_id AND capsule.status = 'ACTIVE'
            AND EXISTS (
              SELECT 1 FROM milai.context_pointer pointer
              WHERE pointer.tenant_id = capsule.tenant_id
                AND pointer.capsule_id = capsule.capsule_id
                AND pointer.evidence_id = p_evidence_id
                AND pointer.state = 'INVALIDATED'
            );

          SELECT count(*) INTO v_shared_count
          FROM milai.evidence_record e
          WHERE e.tenant_id = p_tenant_id AND e.blob_id = v_evidence.blob_id
            AND e.evidence_id <> p_evidence_id
            AND (
              e.revoked_at IS NULL
              OR e.retention_state IN ('LEGAL_HOLD', 'UNREADABLE')
            );
          v_retention_status := CASE v_evidence.retention_state
            WHEN 'LEGAL_HOLD' THEN 'LEGAL_HOLD'
            WHEN 'UNREADABLE' THEN 'UNREADABLE'
            ELSE 'CLEAR'
          END;
          v_primary_status := CASE
            WHEN v_retention_status <> 'CLEAR' THEN 'RETENTION_BLOCKED'
            WHEN v_shared_count > 0 THEN 'BLOCKED_SHARED_REFERENCE'
            ELSE 'PENDING'
          END;
          v_backup_status := CASE
            WHEN v_retention_status <> 'CLEAR' THEN 'RETENTION_BLOCKED'
            ELSE 'PENDING'
          END;
          IF v_primary_status = 'PENDING' THEN
            UPDATE milai.content_blob SET physical_delete_state = 'PURGE_PENDING'
            WHERE tenant_id = p_tenant_id AND blob_id = v_evidence.blob_id
              AND physical_delete_state IN ('PRESENT', 'ERROR');
          END IF;

          v_deletion_request_id := gen_random_uuid();
          INSERT INTO milai.deletion_request (
            tenant_id, deletion_request_id, evidence_id, blob_id,
            reason_code, requested_by_actor_id, logical_revocation_status,
            canonical_block_status, derived_purge_status,
            primary_bytes_status, backup_expiry_status, retention_status,
            grounding_blocks_created, context_pointers_invalidated,
            shared_live_reference_count, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_deletion_request_id, p_evidence_id,
            v_evidence.blob_id, p_reason_code, p_actor_id, 'APPLIED',
            'APPLIED', 'PENDING', v_primary_status, v_backup_status,
            v_retention_status, v_block_count, v_pointer_count,
            v_shared_count, p_actor_id
          );

          v_revoke_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id,
            event_type, payload, priority, canonical_commit_seq,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, v_revoke_outbox_id, 'EVIDENCE', p_evidence_id,
            'EVIDENCE_REVOKED',
            jsonb_build_object(
              'evidence_id', p_evidence_id,
              'deletion_request_id', v_deletion_request_id,
              'affected_claim_ids', v_affected_claim_ids,
              'affected_issue_ids', v_affected_issue_ids
            ), 0, v_commit_seq, p_actor_id
          );
          v_purge_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id,
            event_type, payload, priority, canonical_commit_seq,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, v_purge_outbox_id, 'DELETION_REQUEST',
            v_deletion_request_id, 'PURGE_EVIDENCE_DERIVATIVES',
            jsonb_build_object(
              'deletion_request_id', v_deletion_request_id,
              'evidence_id', p_evidence_id,
              'blob_id', v_evidence.blob_id,
              'primary_bytes_status', v_primary_status,
              'retention_status', v_retention_status
            ), 1, v_commit_seq, p_actor_id
          );
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'EVIDENCE_REVOKED', p_reason_code,
            jsonb_build_object(
              'evidence_id', p_evidence_id,
              'deletion_request_id', v_deletion_request_id,
              'grounding_blocks_created', v_block_count,
              'context_pointers_invalidated', v_pointer_count,
              'shared_live_reference_count', v_shared_count,
              'canonical_commit_seq', v_commit_seq
            ), p_actor_id
          );

          v_response := jsonb_build_object(
            'deletion_request_id', v_deletion_request_id,
            'evidence_id', p_evidence_id,
            'logical_revocation_status', 'APPLIED',
            'canonical_block_status', 'APPLIED',
            'derived_purge_status', 'PENDING',
            'primary_bytes_status', v_primary_status,
            'backup_expiry_status', v_backup_status,
            'retention_status', v_retention_status,
            'grounding_blocks_created', v_block_count,
            'context_pointers_invalidated', v_pointer_count,
            'shared_live_reference_count', v_shared_count,
            'revoke_outbox_id', v_revoke_outbox_id,
            'purge_outbox_id', v_purge_outbox_id,
            'canonical_commit_seq', v_commit_seq,
            'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'TX-05_EVIDENCE_REVOKE'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
    )

    tables = "milai.context_capsule, milai.context_pointer, milai.deletion_request"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"GRANT SELECT ON TABLE {tables} TO milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(f"REVOKE ALL ON FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE}) TO milai_steward"
    )


def downgrade() -> None:
    bind = op.get_bind()
    request_count = bind.execute(
        sa.text("SELECT count(*) FROM milai.deletion_request")
    ).scalar_one()
    if request_count:
        raise RuntimeError(
            "0006 downgrade is unsafe after revocation: deletion requests must be retained"
        )
    op.execute(f"DROP FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE})")
    op.drop_index("ix_deletion_request_progress", table_name="deletion_request", schema="milai")
    op.drop_table("deletion_request", schema="milai")
    op.drop_index("ix_context_pointer_evidence", table_name="context_pointer", schema="milai")
    op.drop_table("context_pointer", schema="milai")
    op.drop_table("context_capsule", schema="milai")
