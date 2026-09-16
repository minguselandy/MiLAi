"""Batch governed purge work without weakening per-item erasure checks.

Revision ID: 0038_dg15_purge_batch
Revises: 0037_dg15_skip_batch
"""

from __future__ import annotations

from alembic import op

revision = "0038_dg15_purge_batch"
down_revision = "0037_dg15_skip_batch"
branch_labels = None
depends_on = None

APPLY_PURGE_BATCH_SIGNATURE = "uuid,uuid,text,uuid[]"
ERASURE_BATCH_SIGNATURE = "uuid,uuid,text,jsonb"
COMPLETE_APPLY_BATCH_SIGNATURE = "uuid,uuid,text,text,jsonb,text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.apply_purge_projection_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_worker_id text,
          p_outbox_ids uuid[]
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count integer;
          v_event record;
          v_result jsonb;
          v_outcomes jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR cardinality(p_outbox_ids) < 1 OR cardinality(p_outbox_ids) > 128
             OR cardinality(p_outbox_ids) <>
                cardinality(ARRAY(SELECT DISTINCT unnest(p_outbox_ids))) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;

          SELECT count(*) INTO v_count
          FROM milai.projection_delivery delivery
          JOIN milai.outbox_event event
            ON event.tenant_id = delivery.tenant_id
           AND event.outbox_id = delivery.outbox_id
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = 'purge'
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP
            AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES';
          IF v_count <> cardinality(p_outbox_ids) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;

          FOR v_event IN
            SELECT event.outbox_id
            FROM milai.outbox_event event
            WHERE event.tenant_id = p_tenant_id
              AND event.outbox_id = ANY(p_outbox_ids)
            ORDER BY event.outbox_sequence
          LOOP
            v_result := milai.apply_purge_projection(
              p_tenant_id, p_actor_id, v_event.outbox_id, p_worker_id
            );
            v_outcomes := v_outcomes || jsonb_build_array(
              v_result || jsonb_build_object('outbox_id', v_event.outbox_id)
            );
          END LOOP;
          RETURN jsonb_build_object(
            'projection', 'purge',
            'item_count', v_count,
            'outcomes', v_outcomes
          );
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.complete_blob_erasure_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_worker_id text,
          p_proofs jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count integer;
          v_distinct integer;
          v_proof record;
          v_result jsonb;
          v_outcomes jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR jsonb_typeof(p_proofs) <> 'array'
             OR jsonb_array_length(p_proofs) < 1
             OR jsonb_array_length(p_proofs) > 128 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          SELECT count(*), count(DISTINCT proof.blob_id)
          INTO v_count, v_distinct
          FROM jsonb_to_recordset(p_proofs) AS proof(
            blob_id uuid,
            disposition text,
            proof_hash text,
            storage_uri text,
            content_hash text
          );
          IF v_count <> v_distinct THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'DUPLICATE_BATCH_ITEM';
          END IF;

          FOR v_proof IN
            SELECT *
            FROM jsonb_to_recordset(p_proofs) AS proof(
              blob_id uuid,
              disposition text,
              proof_hash text,
              storage_uri text,
              content_hash text
            )
            ORDER BY proof.blob_id
          LOOP
            v_result := milai.complete_blob_erasure(
              p_tenant_id,
              p_actor_id,
              v_proof.blob_id,
              p_worker_id,
              v_proof.disposition,
              v_proof.proof_hash,
              v_proof.storage_uri,
              v_proof.content_hash
            );
            v_outcomes := v_outcomes || jsonb_build_array(v_result);
          END LOOP;
          RETURN jsonb_build_object(
            'item_count', v_count,
            'outcomes', v_outcomes
          );
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.complete_projection_apply_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_worker_id text,
          p_items jsonb,
          p_routing_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count integer;
          v_distinct integer;
          v_applicable integer;
          v_watermark bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name <> 'purge'
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR jsonb_typeof(p_items) <> 'array'
             OR jsonb_array_length(p_items) < 1
             OR jsonb_array_length(p_items) > 128
             OR p_routing_version <> 'dg15-routing-v1' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          SELECT count(*), count(DISTINCT item.outbox_id)
          INTO v_count, v_distinct
          FROM jsonb_to_recordset(p_items) AS item(
            outbox_id uuid, result_hash text, handler_outcome text
          );
          IF v_count <> v_distinct OR EXISTS (
            SELECT 1
            FROM jsonb_to_recordset(p_items) AS item(
              outbox_id uuid, result_hash text, handler_outcome text
            )
            WHERE item.result_hash !~ '^[0-9a-f]{64}$'
               OR length(btrim(item.handler_outcome)) = 0
               OR length(item.handler_outcome) > 128
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_BATCH_ITEM';
          END IF;

          SELECT count(*), count(*) FILTER (
            WHERE event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
          ) INTO v_distinct, v_applicable
          FROM jsonb_to_recordset(p_items) AS item(
            outbox_id uuid, result_hash text, handler_outcome text
          )
          JOIN milai.projection_delivery delivery
            ON delivery.tenant_id = p_tenant_id
           AND delivery.projection_name = p_projection_name
           AND delivery.outbox_id = item.outbox_id
           AND delivery.state = 'PROCESSING'
           AND delivery.lease_owner = p_worker_id
           AND delivery.lease_expires_at > CURRENT_TIMESTAMP
          JOIN milai.outbox_event event
            ON event.tenant_id = delivery.tenant_id
           AND event.outbox_id = delivery.outbox_id;
          IF v_distinct <> v_count THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF v_applicable <> v_count THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'INAPPLICABLE_EVENT_CANNOT_BE_APPLIED';
          END IF;

          UPDATE milai.projection_delivery delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = item.result_hash,
              routing_version = p_routing_version,
              applicability = 'APPLY',
              handler_outcome = item.handler_outcome
          FROM jsonb_to_recordset(p_items) AS item(
            outbox_id uuid, result_hash text, handler_outcome text
          )
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = item.outbox_id
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP;

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
            'item_count', v_count,
            'watermark', v_watermark
          );
        END
        $$
        """
    )

    for name, signature in (
        ("apply_purge_projection_batch", APPLY_PURGE_BATCH_SIGNATURE),
        ("complete_blob_erasure_batch", ERASURE_BATCH_SIGNATURE),
        ("complete_projection_apply_batch", COMPLETE_APPLY_BATCH_SIGNATURE),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_worker")


def downgrade() -> None:
    for name, signature in reversed(
        (
            ("apply_purge_projection_batch", APPLY_PURGE_BATCH_SIGNATURE),
            ("complete_blob_erasure_batch", ERASURE_BATCH_SIGNATURE),
            ("complete_projection_apply_batch", COMPLETE_APPLY_BATCH_SIGNATURE),
        )
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
