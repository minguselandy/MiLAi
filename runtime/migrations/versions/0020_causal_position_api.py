"""Expose narrow, tenant-scoped causal position summaries to the API role.

Revision ID: 0020_causal_position_api
Revises: 0019_erasure_proof
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_causal_position_api"
down_revision: str | None = "0019_erasure_proof"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.resolve_outbox_position(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_outbox_ids uuid[]
        ) RETURNS bigint
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count bigint;
          v_maximum bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF COALESCE(cardinality(p_outbox_ids), 0) NOT BETWEEN 1 AND 16
             OR cardinality(p_outbox_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(p_outbox_ids) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CAUSAL_REQUEST';
          END IF;
          SELECT count(*), max(event.outbox_sequence)
          INTO v_count, v_maximum
          FROM milai.outbox_event event
          WHERE event.tenant_id = p_tenant_id
            AND event.outbox_id = ANY(p_outbox_ids);
          IF v_count <> cardinality(p_outbox_ids) THEN
            RETURN NULL;
          END IF;
          RETURN v_maximum;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.causal_projection_status(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_minimum_outbox_sequence bigint
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_state jsonb;
          v_exists boolean;
          v_dead_letter boolean;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_minimum_outbox_sequence IS NULL OR p_minimum_outbox_sequence < 1 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CAUSAL_REQUEST';
          END IF;
          SELECT EXISTS (
            SELECT 1 FROM milai.outbox_event event
            WHERE event.tenant_id = p_tenant_id
              AND event.outbox_sequence = p_minimum_outbox_sequence
          ) INTO v_exists;
          v_state := milai.retrieval_projection_state(p_tenant_id, p_actor_id);
          SELECT EXISTS (
            SELECT 1 FROM milai.projection_delivery delivery
            WHERE delivery.tenant_id = p_tenant_id
              AND delivery.projection_name IN ('fts', 'vector')
              AND delivery.state = 'DEAD_LETTER'
              AND delivery.outbox_sequence <= p_minimum_outbox_sequence
          ) INTO v_dead_letter;
          RETURN v_state || jsonb_build_object(
            'position_exists', v_exists,
            'blocking_dead_letter', v_dead_letter
          );
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION milai.resolve_outbox_position(uuid, uuid, uuid[]) FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION milai.causal_projection_status(uuid, uuid, bigint) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION milai.resolve_outbox_position(uuid, uuid, uuid[]) TO milai_api"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION milai.causal_projection_status(uuid, uuid, bigint) TO milai_api"
    )


def downgrade() -> None:
    raise RuntimeError("0020 downgrade is intentionally unsupported for causal API history")
