"""Persist the deterministic QueryPlan with every RetrievalTrace.

Revision ID: 0012_query_plan_trace
Revises: 0011_episode_settlement

Schema 0.1.x EXPERIMENTAL.
Implementation CANDIDATE.
NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_query_plan_trace"
down_revision: str | None = "0011_episode_settlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TRACE_SIGNATURE = (
    "uuid, uuid, text, text, text, text, jsonb, timestamptz, text, bigint, "
    "bigint, bigint, jsonb, jsonb, boolean, text, boolean, text, integer"
)
NEW_TRACE_SIGNATURE = (
    "uuid, uuid, text, text, text, text, jsonb, jsonb, timestamptz, text, bigint, "
    "bigint, bigint, jsonb, jsonb, boolean, text, boolean, text, integer"
)


def _create_new_trace_function() -> None:
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
          p_duration_ms integer
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
             OR p_duration_ms < 0
             OR (p_fallback_used <> (p_fallback_reason IS NOT NULL))
             OR (p_abstained <> (p_abstention_reason IS NOT NULL)) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TRACE';
          END IF;
          INSERT INTO milai.retrieval_trace (
            tenant_id, trace_id, request_id, route, consistency,
            query_fingerprint, query_plan, requested_scope, as_of,
            required_authority, canonical_snapshot_outbox_sequence,
            fts_watermark, vector_watermark, accepted_candidates,
            rejected_candidates, fallback_used, fallback_reason, abstained,
            abstention_reason, duration_ms, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_trace_id, p_request_id, p_route, p_consistency,
            p_query_fingerprint, p_query_plan, p_requested_scope, p_as_of,
            p_required_authority, p_canonical_snapshot, p_fts_watermark,
            p_vector_watermark, p_accepted, p_rejected, p_fallback_used,
            p_fallback_reason, p_abstained, p_abstention_reason,
            p_duration_ms, p_actor_id
          );
          RETURN v_trace_id;
        END
        $$
        """
    )


def _create_old_trace_function() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.record_retrieval_trace(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_request_id text,
          p_route text,
          p_consistency text,
          p_query_fingerprint text,
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
          p_duration_ms integer
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
             OR jsonb_typeof(p_requested_scope) <> 'object'
             OR jsonb_typeof(p_accepted) <> 'array'
             OR jsonb_typeof(p_rejected) <> 'array'
             OR p_duration_ms < 0
             OR (p_fallback_used <> (p_fallback_reason IS NOT NULL))
             OR (p_abstained <> (p_abstention_reason IS NOT NULL)) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TRACE';
          END IF;
          INSERT INTO milai.retrieval_trace (
            tenant_id, trace_id, request_id, route, consistency,
            query_fingerprint, requested_scope, as_of, required_authority,
            canonical_snapshot_outbox_sequence, fts_watermark,
            vector_watermark, accepted_candidates, rejected_candidates,
            fallback_used, fallback_reason, abstained, abstention_reason,
            duration_ms, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_trace_id, p_request_id, p_route, p_consistency,
            p_query_fingerprint, p_requested_scope, p_as_of,
            p_required_authority, p_canonical_snapshot, p_fts_watermark,
            p_vector_watermark, p_accepted, p_rejected, p_fallback_used,
            p_fallback_reason, p_abstained, p_abstention_reason,
            p_duration_ms, p_actor_id
          );
          RETURN v_trace_id;
        END
        $$
        """
    )


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_retrieval_trace_append_only ON milai.retrieval_trace")
    op.add_column(
        "retrieval_trace",
        sa.Column(
            "query_plan",
            postgresql.JSONB(),
            nullable=True,
        ),
        schema="milai",
    )
    op.execute(
        """
        UPDATE milai.retrieval_trace
        SET query_plan = jsonb_build_object(
          'planner_version', 'legacy-pre-0012',
          'intent', 'UNKNOWN',
          'entities', jsonb_build_array(),
          'time_constraint', jsonb_build_object('as_of', as_of),
          'scope_predicate', requested_scope,
          'required_authority', required_authority,
          'require_user_confirmation', false,
          'complexity', route,
          'consistency_mode', consistency,
          'minimum_commit_seq', NULL,
          'context_budget', 8000,
          'routes', jsonb_build_array(route)
        )
        """
    )
    op.alter_column("retrieval_trace", "query_plan", schema="milai", nullable=False)
    op.execute(
        """
        CREATE TRIGGER trg_retrieval_trace_append_only
        BEFORE UPDATE OR DELETE ON milai.retrieval_trace
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )
    op.create_check_constraint(
        "ck_retrieval_trace_query_plan",
        "retrieval_trace",
        "jsonb_typeof(query_plan) = 'object' "
        "AND query_plan ? 'planner_version' AND query_plan ? 'routes'",
        schema="milai",
    )
    op.execute(f"DROP FUNCTION milai.record_retrieval_trace({OLD_TRACE_SIGNATURE})")
    _create_new_trace_function()
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_retrieval_trace({NEW_TRACE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_retrieval_trace({NEW_TRACE_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.record_retrieval_trace({NEW_TRACE_SIGNATURE})")
    op.drop_constraint(
        "ck_retrieval_trace_query_plan",
        "retrieval_trace",
        schema="milai",
        type_="check",
    )
    op.drop_column("retrieval_trace", "query_plan", schema="milai")
    _create_old_trace_function()
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_retrieval_trace({OLD_TRACE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_retrieval_trace({OLD_TRACE_SIGNATURE}) "
        "TO milai_api"
    )
