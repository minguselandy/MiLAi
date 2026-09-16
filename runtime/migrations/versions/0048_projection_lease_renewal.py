"""Add bounded current-owner projection lease renewal.

Revision ID: 0048_projection_lease_renewal
Revises: 0047_formation_hydration

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_projection_lease_renewal"
down_revision: str | None = "0047_formation_hydration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENEW_BATCH_SIGNATURE = "uuid, uuid, text, text, uuid[], integer"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.renew_projection_event_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_worker_id text,
          p_outbox_ids uuid[],
          p_lease_seconds integer
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_requested integer;
          v_renewed integer;
          v_delivered integer;
          v_lost integer;
          v_now timestamptz;
          v_expires_at timestamptz;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('evidence', 'fts', 'vector', 'purge')
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR p_outbox_ids IS NULL
             OR cardinality(p_outbox_ids) < 1 OR cardinality(p_outbox_ids) > 128
             OR array_position(p_outbox_ids, NULL) IS NOT NULL
             OR cardinality(p_outbox_ids) <>
                cardinality(ARRAY(SELECT DISTINCT unnest(p_outbox_ids)))
             OR p_lease_seconds < 1 OR p_lease_seconds > 300 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          v_requested := cardinality(p_outbox_ids);

          -- Serialize renewal with completion, failure, expiry recovery, and re-lease.
          -- Missing rows remain an ownership loss without exposing cross-tenant state.
          PERFORM 1
          FROM milai.projection_delivery delivery
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
          ORDER BY delivery.outbox_id
          FOR UPDATE;

          v_now := clock_timestamp();
          v_expires_at := v_now + make_interval(secs => p_lease_seconds);
          UPDATE milai.projection_delivery delivery
          SET lease_expires_at = v_expires_at
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > v_now;
          GET DIAGNOSTICS v_renewed = ROW_COUNT;

          SELECT count(*) INTO v_delivered
          FROM milai.projection_delivery delivery
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = p_projection_name
            AND delivery.outbox_id = ANY(p_outbox_ids)
            AND delivery.state = 'DELIVERED';
          v_lost := v_requested - v_renewed - v_delivered;

          RETURN jsonb_build_object(
            'disposition', CASE
              WHEN v_lost > 0 THEN 'OWNERSHIP_LOST'
              WHEN v_renewed > 0 THEN 'RENEWED'
              ELSE 'TERMINAL'
            END,
            'requested_count', v_requested,
            'renewed_count', v_renewed,
            'delivered_count', v_delivered,
            'ownership_lost_count', v_lost,
            'lease_expires_at', CASE WHEN v_renewed > 0 THEN v_expires_at ELSE NULL END
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.renew_projection_event_batch("
        f"{RENEW_BATCH_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.renew_projection_event_batch("
        f"{RENEW_BATCH_SIGNATURE}) TO milai_worker"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.renew_projection_event_batch({RENEW_BATCH_SIGNATURE})")
