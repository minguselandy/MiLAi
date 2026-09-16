"""Batch explicit not-applicable projection receipts.

Revision ID: 0037_dg15_skip_batch
Revises: 0036_dg15_evidence_session
"""

from __future__ import annotations

from alembic import op

revision = "0037_dg15_skip_batch"
down_revision = "0036_dg15_evidence_session"
branch_labels = None
depends_on = None

SKIP_BATCH_SIGNATURE = "uuid,uuid,text,text,uuid[],text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.complete_projection_skip_batch(
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
          v_applicable integer;
          v_watermark bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('evidence', 'fts', 'vector', 'purge')
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR cardinality(p_outbox_ids) < 1 OR cardinality(p_outbox_ids) > 128
             OR cardinality(p_outbox_ids) <>
                cardinality(ARRAY(SELECT DISTINCT unnest(p_outbox_ids)))
             OR p_routing_version <> 'dg15-routing-v1' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;

          SELECT count(*), count(*) FILTER (WHERE CASE
            WHEN p_projection_name = 'evidence' THEN
              event.event_type IN ('EVIDENCE_INGESTED', 'PURGE_EVIDENCE_DERIVATIVES')
            WHEN p_projection_name IN ('fts', 'vector') THEN
              event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
              OR (
                event.event_type IN ('CLAIM_VERSION_COMMITTED', 'OPEN_ISSUE_CHANGED')
                AND length(COALESCE(event.payload ->> 'claim_version_id', '')) > 0
              )
            ELSE event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
          END)
          INTO v_count, v_applicable
          FROM milai.projection_delivery delivery
          JOIN milai.outbox_event event
            ON event.tenant_id = delivery.tenant_id
           AND event.outbox_id = delivery.outbox_id
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP;
          IF v_count <> cardinality(p_outbox_ids) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF v_applicable > 0 THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'APPLICABLE_EVENT_CANNOT_BE_SKIPPED';
          END IF;

          UPDATE milai.projection_delivery delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = encode(sha256(convert_to(
                concat_ws(':', event.event_type, event.outbox_id::text,
                          p_projection_name, 'EXPLICIT_SKIP'), 'UTF8')), 'hex'),
              routing_version = p_routing_version,
              applicability = 'ACK_NOT_APPLICABLE',
              handler_outcome = 'EXPLICIT_SKIP'
          FROM milai.outbox_event event
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP
            AND event.tenant_id = delivery.tenant_id
            AND event.outbox_id = delivery.outbox_id;

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
            'applicability', 'ACK_NOT_APPLICABLE',
            'handler_outcome', 'EXPLICIT_SKIP',
            'item_count', v_count,
            'watermark', v_watermark
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.complete_projection_skip_batch("
        f"{SKIP_BATCH_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.complete_projection_skip_batch("
        f"{SKIP_BATCH_SIGNATURE}) TO milai_worker"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.complete_projection_skip_batch("
        f"{SKIP_BATCH_SIGNATURE})"
    )
