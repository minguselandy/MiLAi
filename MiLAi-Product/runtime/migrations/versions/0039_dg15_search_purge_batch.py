"""Batch contiguous FTS/vector purge events and their routed receipts.

Revision ID: 0039_dg15_search_purge_batch
Revises: 0038_dg15_purge_batch
"""

from __future__ import annotations

from alembic import op

revision = "0039_dg15_search_purge_batch"
down_revision = "0038_dg15_purge_batch"
branch_labels = None
depends_on = None

SEARCH_PURGE_BATCH_SIGNATURE = "uuid,uuid,text,text,uuid[],text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.apply_search_purge_projection_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_worker_id text,
          p_outbox_ids uuid[],
          p_routing_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count integer;
          v_primary_deleted integer := 0;
          v_window_deleted integer := 0;
          v_watermark bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('fts', 'vector')
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR cardinality(p_outbox_ids) < 1 OR cardinality(p_outbox_ids) > 128
             OR cardinality(p_outbox_ids) <>
                cardinality(ARRAY(SELECT DISTINCT unnest(p_outbox_ids)))
             OR p_routing_version <> 'dg15-routing-v1' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;

          SELECT count(*) INTO v_count
          FROM milai.projection_delivery delivery
          JOIN milai.outbox_event event
            ON event.tenant_id = delivery.tenant_id
           AND event.outbox_id = delivery.outbox_id
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP
            AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES';
          IF v_count <> cardinality(p_outbox_ids) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;

          IF p_projection_name = 'fts' THEN
            DELETE FROM milai.search_document document
            WHERE document.tenant_id = p_tenant_id
              AND EXISTS (
                SELECT 1
                FROM milai.grounding_relation grounding
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = grounding.tenant_id
                 AND deletion.evidence_id = grounding.evidence_id
                JOIN milai.outbox_event event
                  ON event.tenant_id = deletion.tenant_id
                 AND event.aggregate_id = deletion.deletion_request_id
                 AND event.outbox_id = ANY(p_outbox_ids)
                 AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                WHERE grounding.tenant_id = document.tenant_id
                  AND grounding.claim_version_id = document.claim_version_id
              );
            GET DIAGNOSTICS v_primary_deleted = ROW_COUNT;

            DELETE FROM milai.search_document_fragment fragment
            WHERE fragment.tenant_id = p_tenant_id
              AND EXISTS (
                SELECT 1
                FROM milai.grounding_relation grounding
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = grounding.tenant_id
                 AND deletion.evidence_id = grounding.evidence_id
                JOIN milai.outbox_event event
                  ON event.tenant_id = deletion.tenant_id
                 AND event.aggregate_id = deletion.deletion_request_id
                 AND event.outbox_id = ANY(p_outbox_ids)
                 AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                WHERE grounding.tenant_id = fragment.tenant_id
                  AND grounding.claim_version_id = fragment.claim_version_id
              );
            GET DIAGNOSTICS v_window_deleted = ROW_COUNT;
          ELSE
            DELETE FROM milai.search_embedding embedding
            WHERE embedding.tenant_id = p_tenant_id
              AND EXISTS (
                SELECT 1
                FROM milai.grounding_relation grounding
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = grounding.tenant_id
                 AND deletion.evidence_id = grounding.evidence_id
                JOIN milai.outbox_event event
                  ON event.tenant_id = deletion.tenant_id
                 AND event.aggregate_id = deletion.deletion_request_id
                 AND event.outbox_id = ANY(p_outbox_ids)
                 AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                WHERE grounding.tenant_id = embedding.tenant_id
                  AND grounding.claim_version_id = embedding.claim_version_id
              );
            GET DIAGNOSTICS v_primary_deleted = ROW_COUNT;

            DELETE FROM milai.search_embedding_window_128 embedding
            WHERE embedding.tenant_id = p_tenant_id
              AND EXISTS (
                SELECT 1
                FROM milai.grounding_relation grounding
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = grounding.tenant_id
                 AND deletion.evidence_id = grounding.evidence_id
                JOIN milai.outbox_event event
                  ON event.tenant_id = deletion.tenant_id
                 AND event.aggregate_id = deletion.deletion_request_id
                 AND event.outbox_id = ANY(p_outbox_ids)
                 AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                WHERE grounding.tenant_id = embedding.tenant_id
                  AND grounding.claim_version_id = embedding.claim_version_id
              );
            GET DIAGNOSTICS v_window_deleted = ROW_COUNT;
          END IF;

          UPDATE milai.projection_delivery delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = encode(sha256(convert_to(
                concat_ws(':', event.event_type, event.outbox_id::text,
                          p_projection_name, 'PURGED'), 'UTF8')), 'hex'),
              routing_version = p_routing_version,
              applicability = 'APPLY',
              handler_outcome = 'PURGED'
          FROM milai.outbox_event event
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP
            AND event.tenant_id = delivery.tenant_id
            AND event.outbox_id = delivery.outbox_id
            AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES';

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
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name;
          RETURN jsonb_build_object(
            'projection', p_projection_name,
            'routing_version', p_routing_version,
            'applicability', 'APPLY',
            'handler_outcome', 'PURGED',
            'item_count', v_count,
            'primary_rows_deleted', v_primary_deleted,
            'window_rows_deleted', v_window_deleted,
            'watermark', v_watermark
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.apply_search_purge_projection_batch("
        f"{SEARCH_PURGE_BATCH_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.apply_search_purge_projection_batch("
        f"{SEARCH_PURGE_BATCH_SIGNATURE}) TO milai_worker"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.apply_search_purge_projection_batch("
        f"{SEARCH_PURGE_BATCH_SIGNATURE})"
    )
