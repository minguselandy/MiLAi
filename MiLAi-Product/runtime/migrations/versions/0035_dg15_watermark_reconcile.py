"""Reconcile ordered watermarks and align cleanup stage status.

Revision ID: 0035_dg15_watermark_reconcile
Revises: 0034_dg15_namespace_cleanup
"""

from __future__ import annotations

from alembic import op

revision = "0035_dg15_watermark_reconcile"
down_revision = "0034_dg15_namespace_cleanup"
branch_labels = None
depends_on = None

RECONCILE_SIGNATURE = "uuid,uuid,text"
STATUS_SIGNATURE = "uuid,uuid,uuid,integer,integer"


def _create_cleanup_status(*, completed_is_purged: bool) -> None:
    purge_predicate = (
        "deletion.derived_purge_status IN ('PURGED', 'COMPLETED')"
        if completed_is_purged
        else "deletion.derived_purge_status = 'PURGED'"
    )
    statement = """
        CREATE OR REPLACE FUNCTION milai.namespace_cleanup_status(
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

          SELECT count(*) FILTER (WHERE __PURGE_PREDICATE__),
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
    op.execute(statement.replace("__PURGE_PREDICATE__", purge_predicate))


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.reconcile_projection_watermark(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_watermark bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('evidence', 'fts', 'vector', 'purge') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROJECTION_NAME';
          END IF;
          SELECT COALESCE(max(delivered.outbox_sequence), 0) INTO v_watermark
          FROM milai.projection_delivery delivered
          WHERE delivered.tenant_id = p_tenant_id
            AND delivered.projection_name = p_projection_name
            AND delivered.state = 'DELIVERED'
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery gap
              WHERE gap.tenant_id = delivered.tenant_id
                AND gap.projection_name = delivered.projection_name
                AND gap.outbox_sequence < delivered.outbox_sequence
                AND gap.state <> 'DELIVERED'
            );
          UPDATE milai.index_watermark
          SET last_contiguous_outbox_sequence = v_watermark,
              updated_at = CURRENT_TIMESTAMP,
              updated_by_actor_id = p_actor_id
          WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name;
          RETURN v_watermark;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.reconcile_projection_watermark("
        f"{RECONCILE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.reconcile_projection_watermark("
        f"{RECONCILE_SIGNATURE}) TO milai_worker"
    )
    _create_cleanup_status(completed_is_purged=True)
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    _create_cleanup_status(completed_is_purged=False)
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "TO milai_api"
    )
    op.execute(
        f"DROP FUNCTION milai.reconcile_projection_watermark({RECONCILE_SIGNATURE})"
    )
