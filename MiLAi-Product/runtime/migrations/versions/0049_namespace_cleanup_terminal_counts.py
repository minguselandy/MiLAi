"""Treat legal shared/retention Blob dispositions as cleanup terminal states.

Revision ID: 0049_cleanup_terminal_counts
Revises: 0048_projection_lease_renewal
"""

from __future__ import annotations

from alembic import op

revision = "0049_cleanup_terminal_counts"
down_revision = "0048_projection_lease_renewal"
branch_labels = None
depends_on = None

STATUS_SIGNATURE = "uuid,uuid,uuid,integer,integer"


def _create_cleanup_status(*, terminal_counts: bool) -> None:
    declarations = """
          v_terminal integer;
          v_retained_shared integer;
          v_retention_blocked integer;
    """ if terminal_counts else ""
    select_columns = """
                 , count(*) FILTER (
                   WHERE deletion.primary_bytes_status IN (
                     'ERASED', 'BLOCKED_SHARED_REFERENCE', 'RETENTION_BLOCKED'
                   )
                 ),
                 count(*) FILTER (
                   WHERE deletion.primary_bytes_status = 'BLOCKED_SHARED_REFERENCE'
                 ),
                 count(*) FILTER (
                   WHERE deletion.primary_bytes_status = 'RETENTION_BLOCKED'
                 )
    """ if terminal_counts else ""
    select_targets = (
        "v_purged, v_erased, v_backup_complete, v_terminal, "
        "v_retained_shared, v_retention_blocked"
        if terminal_counts
        else "v_purged, v_erased, v_backup_complete"
    )
    json_counts = """
            'primary_bytes_terminal_count', COALESCE(v_terminal, 0),
            'primary_bytes_retained_shared_count', COALESCE(v_retained_shared, 0),
            'primary_bytes_retention_blocked_count', COALESCE(v_retention_blocked, 0),
    """ if terminal_counts else ""
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
          __DECLARATIONS__
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
                 __SELECT_COLUMNS__
          INTO __SELECT_TARGETS__
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
            __JSON_COUNTS__
            'backup_expiry_completed_count', COALESCE(v_backup_complete, 0),
            'target_purge_outbox_id', v_job.target_purge_outbox_id,
            'offset', p_offset,
            'limit', p_limit,
            'item_outcomes', v_items
          );
        END
        $$
        """
    op.execute(
        statement.replace("__DECLARATIONS__", declarations)
        .replace("__SELECT_COLUMNS__", select_columns)
        .replace("__SELECT_TARGETS__", select_targets)
        .replace("__JSON_COUNTS__", json_counts)
    )


def _permissions() -> None:
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.namespace_cleanup_status({STATUS_SIGNATURE}) "
        "TO milai_api"
    )


def upgrade() -> None:
    _create_cleanup_status(terminal_counts=True)
    _permissions()


def downgrade() -> None:
    _create_cleanup_status(terminal_counts=False)
    _permissions()
