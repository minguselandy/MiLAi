"""Persist authenticated read-your-writes wait outcomes.

Revision ID: 0018_causal_trace
Revises: 0017_authoritative_ecs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_causal_trace"
down_revision: str | None = "0017_authoritative_ecs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TRACE_SIGNATURE = (
    "uuid, uuid, text, text, text, text, jsonb, jsonb, timestamptz, text, bigint, "
    "bigint, bigint, jsonb, jsonb, boolean, text, boolean, text, integer"
)
NEW_TRACE_SIGNATURE = OLD_TRACE_SIGNATURE + ", bigint, text, integer"


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_retrieval_trace_append_only ON milai.retrieval_trace")
    op.add_column(
        "retrieval_trace",
        sa.Column("minimum_outbox_sequence", sa.BigInteger(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "retrieval_trace",
        sa.Column("causal_wait_outcome", sa.Text(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "retrieval_trace",
        sa.Column("causal_waited_ms", sa.Integer(), nullable=False, server_default="0"),
        schema="milai",
    )
    op.execute(
        """
        UPDATE milai.retrieval_trace
        SET causal_wait_outcome = 'LEGACY_UNTOKENED'
        WHERE consistency = 'READ_YOUR_WRITES'
        """
    )
    op.create_check_constraint(
        "ck_retrieval_trace_causal_wait",
        "retrieval_trace",
        "causal_waited_ms >= 0 AND ("
        "(consistency = 'READ_YOUR_WRITES' AND ("
        "  (minimum_outbox_sequence >= 1 AND causal_wait_outcome IN ("
        "    'REACHED', 'TIMEOUT', 'DEAD_LETTER', 'CANONICAL_L0'"
        "  )) OR (minimum_outbox_sequence IS NULL "
        "         AND causal_wait_outcome = 'LEGACY_UNTOKENED')"
        ")) OR (consistency <> 'READ_YOUR_WRITES' "
        "       AND minimum_outbox_sequence IS NULL "
        "       AND causal_wait_outcome IS NULL AND causal_waited_ms = 0)"
        ")",
        schema="milai",
    )
    op.execute(
        """
        CREATE TRIGGER trg_retrieval_trace_append_only
        BEFORE UPDATE OR DELETE ON milai.retrieval_trace
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )
    op.execute(
        f"ALTER FUNCTION milai.record_retrieval_trace({OLD_TRACE_SIGNATURE}) "
        "RENAME TO record_retrieval_trace_legacy"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_retrieval_trace_legacy({OLD_TRACE_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    _create_trace_function()


def _create_trace_function() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.record_retrieval_trace(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_request_id text,
          p_route text,
          p_consistency text,
          p_query_fingerprint text,
          p_query_plan jsonb,
          p_requested_scope jsonb,
          p_as_of timestamptz,
          p_required_authority text,
          p_canonical_snapshot bigint,
          p_fts_watermark bigint,
          p_vector_watermark bigint,
          p_accepted jsonb,
          p_rejected jsonb,
          p_fallback_used boolean,
          p_fallback_reason text,
          p_abstained boolean,
          p_abstention_reason text,
          p_duration_ms integer,
          p_minimum_outbox_sequence bigint,
          p_causal_wait_outcome text,
          p_causal_waited_ms integer
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_trace_id uuid := gen_random_uuid();
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_route NOT IN ('L0', 'L1')
             OR p_consistency NOT IN (
               'EVENTUAL', 'READ_YOUR_WRITES', 'CANONICAL_REQUIRED'
             )
             OR p_query_fingerprint !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_query_plan) <> 'object'
             OR jsonb_typeof(p_query_plan -> 'routes') <> 'array'
             OR p_query_plan ->> 'planner_version' IS NULL
             OR p_query_plan ->> 'complexity' IS DISTINCT FROM p_route
             OR p_query_plan ->> 'consistency_mode' IS DISTINCT FROM p_consistency
             OR p_query_plan ->> 'required_authority'
                IS DISTINCT FROM p_required_authority
             OR jsonb_typeof(p_requested_scope) <> 'object'
             OR p_query_plan -> 'scope_predicate' IS DISTINCT FROM p_requested_scope
             OR jsonb_typeof(p_accepted) <> 'array'
             OR jsonb_typeof(p_rejected) <> 'array'
             OR p_duration_ms < 0 OR p_causal_waited_ms < 0
             OR (p_fallback_used <> (p_fallback_reason IS NOT NULL))
             OR (p_abstained <> (p_abstention_reason IS NOT NULL))
             OR (
               p_consistency = 'READ_YOUR_WRITES' AND (
                 p_minimum_outbox_sequence IS NULL
                 OR p_minimum_outbox_sequence < 1
                 OR p_causal_wait_outcome NOT IN (
                   'REACHED', 'TIMEOUT', 'DEAD_LETTER', 'CANONICAL_L0'
                 )
                 OR NULLIF(
                   p_query_plan ->> 'minimum_outbox_sequence', ''
                 )::bigint IS DISTINCT FROM p_minimum_outbox_sequence
               )
             )
             OR (
               p_consistency <> 'READ_YOUR_WRITES' AND (
                 p_minimum_outbox_sequence IS NOT NULL
                 OR p_causal_wait_outcome IS NOT NULL
                 OR p_causal_waited_ms <> 0
               )
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TRACE';
          END IF;
          INSERT INTO milai.retrieval_trace (
            tenant_id, trace_id, request_id, route, consistency,
            query_fingerprint, query_plan, requested_scope, as_of,
            required_authority, canonical_snapshot_outbox_sequence,
            fts_watermark, vector_watermark, accepted_candidates,
            rejected_candidates, fallback_used, fallback_reason, abstained,
            abstention_reason, duration_ms, minimum_outbox_sequence,
            causal_wait_outcome, causal_waited_ms, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_trace_id, p_request_id, p_route, p_consistency,
            p_query_fingerprint, p_query_plan, p_requested_scope, p_as_of,
            p_required_authority, p_canonical_snapshot, p_fts_watermark,
            p_vector_watermark, p_accepted, p_rejected, p_fallback_used,
            p_fallback_reason, p_abstained, p_abstention_reason,
            p_duration_ms, p_minimum_outbox_sequence, p_causal_wait_outcome,
            p_causal_waited_ms, p_actor_id
          );
          RETURN v_trace_id;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_retrieval_trace({NEW_TRACE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_retrieval_trace({NEW_TRACE_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    raise RuntimeError("0018 downgrade is intentionally unsupported for causal audit history")
