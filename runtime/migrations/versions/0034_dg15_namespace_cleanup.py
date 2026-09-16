"""Add governed namespace cleanup jobs and staged receipts.

Revision ID: 0034_dg15_namespace_cleanup
Revises: 0033_dg15_projection
"""

from __future__ import annotations

from alembic import op

revision = "0034_dg15_namespace_cleanup"
down_revision = "0033_dg15_projection"
branch_labels = None
depends_on = None

SUBMIT_SIGNATURE = "uuid,uuid,text,text,text,text,text"
STATUS_SIGNATURE = "uuid,uuid,uuid,integer,integer"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE milai.namespace_cleanup_job (
          tenant_id uuid NOT NULL,
          cleanup_job_id uuid NOT NULL,
          project_id text NOT NULL CHECK (length(btrim(project_id)) BETWEEN 1 AND 255),
          reason_code text NOT NULL CHECK (length(btrim(reason_code)) BETWEEN 1 AND 255),
          idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
          request_fingerprint text NOT NULL CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
          submission_status text NOT NULL CHECK (
            submission_status IN ('PROCESSING', 'ACCEPTED', 'PARTIAL_FAILURE')
          ),
          evidence_count integer NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
          accepted_count integer NOT NULL DEFAULT 0 CHECK (accepted_count >= 0),
          failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
          target_purge_outbox_id uuid,
          requested_by_actor_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          submitted_at timestamptz,
          created_by_actor_id uuid NOT NULL,
          PRIMARY KEY (tenant_id, cleanup_job_id),
          UNIQUE (tenant_id, idempotency_key)
        );

        CREATE TABLE milai.namespace_cleanup_item (
          tenant_id uuid NOT NULL,
          cleanup_job_id uuid NOT NULL,
          item_ordinal integer NOT NULL CHECK (item_ordinal >= 0),
          evidence_id uuid NOT NULL,
          deletion_request_id uuid,
          purge_outbox_id uuid,
          outcome text NOT NULL CHECK (
            outcome IN ('TX05_APPLIED', 'ALREADY_REVOKED', 'FAILED')
          ),
          error_code text,
          tx05_receipt jsonb,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          PRIMARY KEY (tenant_id, cleanup_job_id, evidence_id),
          UNIQUE (tenant_id, cleanup_job_id, item_ordinal),
          FOREIGN KEY (tenant_id, cleanup_job_id)
            REFERENCES milai.namespace_cleanup_job(tenant_id, cleanup_job_id)
            ON DELETE RESTRICT,
          FOREIGN KEY (tenant_id, evidence_id)
            REFERENCES milai.evidence_record(tenant_id, evidence_id)
            ON DELETE RESTRICT
        );

        CREATE INDEX namespace_cleanup_item_deletion_idx
          ON milai.namespace_cleanup_item(tenant_id, deletion_request_id)
          WHERE deletion_request_id IS NOT NULL;

        ALTER TABLE milai.namespace_cleanup_job ENABLE ROW LEVEL SECURITY;
        ALTER TABLE milai.namespace_cleanup_job FORCE ROW LEVEL SECURITY;
        ALTER TABLE milai.namespace_cleanup_item ENABLE ROW LEVEL SECURITY;
        ALTER TABLE milai.namespace_cleanup_item FORCE ROW LEVEL SECURITY;

        CREATE POLICY namespace_cleanup_job_tenant_isolation
          ON milai.namespace_cleanup_job
          USING (tenant_id = nullif(current_setting('milai.tenant_id', true), '')::uuid)
          WITH CHECK (
            tenant_id = nullif(current_setting('milai.tenant_id', true), '')::uuid
          );
        CREATE POLICY namespace_cleanup_item_tenant_isolation
          ON milai.namespace_cleanup_item
          USING (tenant_id = nullif(current_setting('milai.tenant_id', true), '')::uuid)
          WITH CHECK (
            tenant_id = nullif(current_setting('milai.tenant_id', true), '')::uuid
          );
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.submit_namespace_cleanup(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_project_id text,
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
          v_job milai.namespace_cleanup_job%ROWTYPE;
          v_evidence record;
          v_result jsonb;
          v_job_id uuid;
          v_item_key text;
          v_item_fingerprint text;
          v_ordinal integer := 0;
          v_accepted integer := 0;
          v_failed integer := 0;
          v_target_outbox_id uuid;
          v_error text;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_confirmation <> 'CLEANUP_NAMESPACE'
             OR length(btrim(p_project_id)) NOT BETWEEN 1 AND 255
             OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 255
             OR length(p_idempotency_key) NOT BETWEEN 1 AND 128
             OR p_request_fingerprint !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'NAMESPACE_CLEANUP_NOT_AUTHORIZED';
          END IF;

          SELECT * INTO v_job
          FROM milai.namespace_cleanup_job
          WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key
          FOR UPDATE;
          IF FOUND THEN
            IF v_job.request_fingerprint <> p_request_fingerprint
               OR v_job.project_id <> p_project_id THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
            END IF;
            RETURN jsonb_build_object(
              'cleanup_job_id', v_job.cleanup_job_id,
              'project_id', v_job.project_id,
              'status', v_job.submission_status,
              'cleanup_accepted', v_job.submission_status IN ('ACCEPTED', 'PARTIAL_FAILURE'),
              'evidence_count', v_job.evidence_count,
              'accepted_count', v_job.accepted_count,
              'failed_count', v_job.failed_count,
              'target_purge_outbox_id', v_job.target_purge_outbox_id,
              'replayed', true
            );
          END IF;

          v_job_id := gen_random_uuid();
          INSERT INTO milai.namespace_cleanup_job (
            tenant_id, cleanup_job_id, project_id, reason_code,
            idempotency_key, request_fingerprint, submission_status,
            requested_by_actor_id, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_job_id, p_project_id, p_reason_code,
            p_idempotency_key, p_request_fingerprint, 'PROCESSING',
            p_actor_id, p_actor_id
          );

          FOR v_evidence IN
            SELECT evidence.evidence_id, evidence.revoked_at,
                   deletion.deletion_request_id,
                   purge.outbox_id AS existing_purge_outbox_id
            FROM milai.evidence_record evidence
            LEFT JOIN milai.deletion_request deletion
              ON deletion.tenant_id = evidence.tenant_id
             AND deletion.evidence_id = evidence.evidence_id
            LEFT JOIN LATERAL (
              SELECT event.outbox_id
              FROM milai.outbox_event event
              WHERE event.tenant_id = evidence.tenant_id
                AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                AND event.payload ->> 'evidence_id' = evidence.evidence_id::text
              ORDER BY event.outbox_sequence DESC LIMIT 1
            ) purge ON true
            WHERE evidence.tenant_id = p_tenant_id
              AND COALESCE(evidence.permission_snapshot -> 'project_ids', '[]'::jsonb)
                    ? p_project_id
            ORDER BY evidence.evidence_id
          LOOP
            IF v_evidence.revoked_at IS NOT NULL THEN
              INSERT INTO milai.namespace_cleanup_item (
                tenant_id, cleanup_job_id, item_ordinal, evidence_id,
                deletion_request_id, purge_outbox_id, outcome,
                tx05_receipt, created_by_actor_id
              ) VALUES (
                p_tenant_id, v_job_id, v_ordinal, v_evidence.evidence_id,
                v_evidence.deletion_request_id,
                v_evidence.existing_purge_outbox_id, 'ALREADY_REVOKED',
                jsonb_build_object(
                  'evidence_id', v_evidence.evidence_id,
                  'deletion_request_id', v_evidence.deletion_request_id,
                  'replayed', true
                ), p_actor_id
              );
              v_accepted := v_accepted + 1;
              v_target_outbox_id := COALESCE(
                v_evidence.existing_purge_outbox_id, v_target_outbox_id
              );
            ELSE
              v_item_key := 'dg15-ns:' || v_job_id::text || ':' || v_evidence.evidence_id::text;
              v_item_fingerprint := encode(sha256(convert_to(concat_ws(
                ':', p_tenant_id::text, v_job_id::text,
                v_evidence.evidence_id::text, p_reason_code
              ), 'UTF8')), 'hex');
              BEGIN
                v_result := milai.tx05_revoke_evidence(
                  p_tenant_id, p_actor_id, v_evidence.evidence_id,
                  p_reason_code, 'REVOKE', v_item_key, v_item_fingerprint
                );
                INSERT INTO milai.namespace_cleanup_item (
                  tenant_id, cleanup_job_id, item_ordinal, evidence_id,
                  deletion_request_id, purge_outbox_id, outcome,
                  tx05_receipt, created_by_actor_id
                ) VALUES (
                  p_tenant_id, v_job_id, v_ordinal, v_evidence.evidence_id,
                  (v_result ->> 'deletion_request_id')::uuid,
                  (v_result ->> 'purge_outbox_id')::uuid,
                  'TX05_APPLIED', v_result, p_actor_id
                );
                v_accepted := v_accepted + 1;
                v_target_outbox_id := (v_result ->> 'purge_outbox_id')::uuid;
              EXCEPTION WHEN raise_exception THEN
                GET STACKED DIAGNOSTICS v_error = MESSAGE_TEXT;
                IF v_error NOT IN (
                  'EVIDENCE_NOT_FOUND', 'IDEMPOTENCY_CONFLICT',
                  'REVOCATION_NOT_AUTHORIZED', 'TENANT_MISMATCH'
                ) THEN
                  RAISE;
                END IF;
                INSERT INTO milai.namespace_cleanup_item (
                  tenant_id, cleanup_job_id, item_ordinal, evidence_id,
                  outcome, error_code, created_by_actor_id
                ) VALUES (
                  p_tenant_id, v_job_id, v_ordinal, v_evidence.evidence_id,
                  'FAILED', v_error, p_actor_id
                );
                v_failed := v_failed + 1;
              END;
            END IF;
            v_ordinal := v_ordinal + 1;
          END LOOP;

          UPDATE milai.namespace_cleanup_job
          SET submission_status = CASE WHEN v_failed = 0 THEN 'ACCEPTED'
                                       ELSE 'PARTIAL_FAILURE' END,
              evidence_count = v_ordinal,
              accepted_count = v_accepted,
              failed_count = v_failed,
              target_purge_outbox_id = v_target_outbox_id,
              submitted_at = CURRENT_TIMESTAMP
          WHERE tenant_id = p_tenant_id AND cleanup_job_id = v_job_id;

          RETURN jsonb_build_object(
            'cleanup_job_id', v_job_id,
            'project_id', p_project_id,
            'status', CASE WHEN v_failed = 0 THEN 'ACCEPTED'
                           ELSE 'PARTIAL_FAILURE' END,
            'cleanup_accepted', true,
            'evidence_count', v_ordinal,
            'accepted_count', v_accepted,
            'failed_count', v_failed,
            'target_purge_outbox_id', v_target_outbox_id,
            'replayed', false
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.namespace_cleanup_status(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_cleanup_job_id uuid,
          p_offset integer,
          p_limit integer
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_job milai.namespace_cleanup_job%ROWTYPE;
          v_items jsonb;
          v_purged integer;
          v_erased integer;
          v_backup_complete integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_offset < 0 OR p_limit < 1 OR p_limit > 200 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CLEANUP_STATUS_REQUEST';
          END IF;
          SELECT * INTO v_job FROM milai.namespace_cleanup_job
          WHERE tenant_id = p_tenant_id AND cleanup_job_id = p_cleanup_job_id;
          IF NOT FOUND THEN
            RETURN NULL;
          END IF;

          SELECT count(*) FILTER (
                   WHERE deletion.derived_purge_status IN ('PURGED', 'COMPLETED')
                 ),
                 count(*) FILTER (WHERE deletion.primary_bytes_status = 'ERASED'),
                 count(*) FILTER (WHERE deletion.backup_expiry_status = 'COMPLETED')
          INTO v_purged, v_erased, v_backup_complete
          FROM milai.namespace_cleanup_item item
          LEFT JOIN milai.deletion_request deletion
            ON deletion.tenant_id = item.tenant_id
           AND deletion.deletion_request_id = item.deletion_request_id
          WHERE item.tenant_id = p_tenant_id
            AND item.cleanup_job_id = p_cleanup_job_id;

          SELECT COALESCE(jsonb_agg(row.item ORDER BY row.item_ordinal), '[]'::jsonb)
          INTO v_items
          FROM (
            SELECT item.item_ordinal, jsonb_build_object(
              'ordinal', item.item_ordinal,
              'evidence_id', item.evidence_id,
              'deletion_request_id', item.deletion_request_id,
              'purge_outbox_id', item.purge_outbox_id,
              'outcome', item.outcome,
              'error_code', item.error_code,
              'logical_revocation_status', deletion.logical_revocation_status,
              'canonical_block_status', deletion.canonical_block_status,
              'derived_purge_status', deletion.derived_purge_status,
              'primary_bytes_status', deletion.primary_bytes_status,
              'backup_expiry_status', deletion.backup_expiry_status,
              'retention_status', deletion.retention_status
            ) AS item
            FROM milai.namespace_cleanup_item item
            LEFT JOIN milai.deletion_request deletion
              ON deletion.tenant_id = item.tenant_id
             AND deletion.deletion_request_id = item.deletion_request_id
            WHERE item.tenant_id = p_tenant_id
              AND item.cleanup_job_id = p_cleanup_job_id
            ORDER BY item.item_ordinal
            OFFSET p_offset LIMIT p_limit
          ) row;

          RETURN jsonb_build_object(
            'cleanup_job_id', v_job.cleanup_job_id,
            'project_id', v_job.project_id,
            'submission_status', v_job.submission_status,
            'cleanup_accepted', v_job.submission_status IN ('ACCEPTED', 'PARTIAL_FAILURE'),
            'evidence_count', v_job.evidence_count,
            'accepted_count', v_job.accepted_count,
            'failed_count', v_job.failed_count,
            'canonical_blocked_count', v_job.accepted_count,
            'projection_purged_count', COALESCE(v_purged, 0),
            'primary_bytes_erased_count', COALESCE(v_erased, 0),
            'backup_expiry_completed_count', COALESCE(v_backup_complete, 0),
            'target_purge_outbox_id', v_job.target_purge_outbox_id,
            'offset', p_offset,
            'limit', p_limit,
            'item_outcomes', v_items
          );
        END
        $$
        """
    )

    tables = "milai.namespace_cleanup_job, milai.namespace_cleanup_item"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(f"GRANT SELECT ON TABLE {tables} TO milai_audit")
    for name, signature in (
        ("submit_namespace_cleanup", SUBMIT_SIGNATURE),
        ("namespace_cleanup_status", STATUS_SIGNATURE),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.submit_namespace_cleanup({SUBMIT_SIGNATURE}) "
        "TO milai_steward"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE})"
    )
    op.execute(
        f"DROP FUNCTION milai.submit_namespace_cleanup({SUBMIT_SIGNATURE})"
    )
    op.execute("DROP TABLE milai.namespace_cleanup_item")
    op.execute("DROP TABLE milai.namespace_cleanup_job")
