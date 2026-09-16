"""Persist DG-13 retrieval execution facts for the read-only AccessTrace view.

Revision ID: 0029_dg13_access_trace
Revises: 0028_dg11_window_projection

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
AccessTrace is deliberately not a table: it is derived from the append-only
RetrievalTrace plus request-local MCP/Host spans.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_dg13_access_trace"
down_revision: str | None = "0028_dg11_window_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TRACE_SIGNATURE = (
    "uuid, uuid, text, text, text, text, jsonb, jsonb, timestamptz, text, bigint, "
    "bigint, bigint, jsonb, jsonb, boolean, text, boolean, text, integer, bigint, "
    "text, integer"
)
NEW_TRACE_SIGNATURE = OLD_TRACE_SIGNATURE + ", jsonb, jsonb"


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_retrieval_trace_append_only ON milai.retrieval_trace")
    op.add_column(
        "retrieval_trace",
        sa.Column("execution_trace", postgresql.JSONB(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "retrieval_trace",
        sa.Column("stage_metrics", postgresql.JSONB(), nullable=True),
        schema="milai",
    )
    op.execute(
        """
        UPDATE milai.retrieval_trace
        SET execution_trace = jsonb_build_object(
              'schema_version', 'retrieval-execution-v1',
              'requested_intent', NULL,
              'planned_stage', CASE WHEN route = 'L0' THEN 'EXACT' ELSE 'SEARCH' END,
              'attempted_stages', jsonb_build_array(
                CASE WHEN route = 'L0' THEN 'EXACT' ELSE 'SEARCH' END,
                'CANONICAL_GATE'
              ),
              'terminal_stage', CASE
                WHEN abstained THEN 'CANONICAL_GATE'
                WHEN route = 'L0' THEN 'EXACT'
                ELSE 'SEARCH'
              END,
              'stop_reason', COALESCE(abstention_reason, 'LEGACY_TRACE_BACKFILL'),
              'fallback_reason', fallback_reason,
              'result_count', jsonb_array_length(accepted_candidates),
              'route_trace_complete', false,
              'trace_gap_reason', 'LEGACY_STAGE_DETAIL_UNAVAILABLE'
            ),
            stage_metrics = jsonb_build_object(
              'durations_ms', jsonb_build_object('query_total_ms', duration_ms),
              'counts', jsonb_build_object('query_total_ms', 1)
            )
        """
    )
    op.alter_column("retrieval_trace", "execution_trace", nullable=False, schema="milai")
    op.alter_column("retrieval_trace", "stage_metrics", nullable=False, schema="milai")
    op.create_check_constraint(
        "ck_retrieval_trace_execution_trace",
        "retrieval_trace",
        """
        jsonb_typeof(execution_trace) = 'object'
        AND execution_trace ->> 'schema_version' = 'retrieval-execution-v1'
        AND execution_trace ->> 'planned_stage' IN ('EXACT', 'SEARCH')
        AND jsonb_typeof(execution_trace -> 'attempted_stages') = 'array'
        AND execution_trace ->> 'terminal_stage' IS NOT NULL
        AND execution_trace ->> 'stop_reason' IS NOT NULL
        AND jsonb_typeof(execution_trace -> 'result_count') = 'number'
        AND (execution_trace ->> 'result_count')::integer >= 0
        AND jsonb_typeof(execution_trace -> 'route_trace_complete') = 'boolean'
        """,
        schema="milai",
    )
    op.create_check_constraint(
        "ck_retrieval_trace_stage_metrics",
        "retrieval_trace",
        """
        jsonb_typeof(stage_metrics) = 'object'
        AND jsonb_typeof(stage_metrics -> 'durations_ms') = 'object'
        AND jsonb_typeof(stage_metrics -> 'counts') = 'object'
        AND jsonb_typeof(stage_metrics -> 'durations_ms' -> 'query_total_ms') = 'number'
        AND jsonb_typeof(stage_metrics -> 'counts' -> 'query_total_ms') = 'number'
        AND (stage_metrics -> 'durations_ms' ->> 'query_total_ms')::numeric >= 0
        AND (stage_metrics -> 'counts' ->> 'query_total_ms')::integer = 1
        """,
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
        "RENAME TO record_retrieval_trace_pre_access_trace"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.record_retrieval_trace_pre_access_trace({OLD_TRACE_SIGNATURE}) "
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
          p_causal_waited_ms integer,
          p_execution_trace jsonb,
          p_stage_metrics jsonb
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
             )
             OR jsonb_typeof(p_execution_trace) <> 'object'
             OR p_execution_trace ->> 'schema_version' <> 'retrieval-execution-v1'
             OR p_execution_trace ->> 'planned_stage'
                IS DISTINCT FROM (
                  CASE WHEN p_route = 'L0' THEN 'EXACT' ELSE 'SEARCH' END
                )
             OR jsonb_typeof(p_execution_trace -> 'attempted_stages') <> 'array'
             OR p_execution_trace ->> 'terminal_stage' IS NULL
             OR p_execution_trace ->> 'stop_reason' IS NULL
             OR jsonb_typeof(p_execution_trace -> 'result_count') <> 'number'
             OR (p_execution_trace ->> 'result_count')::integer
                <> jsonb_array_length(p_accepted)
             OR p_execution_trace -> 'fallback_reason'
                IS DISTINCT FROM COALESCE(to_jsonb(p_fallback_reason), 'null'::jsonb)
             OR p_execution_trace ->> 'route_trace_complete' <> 'true'
             OR p_execution_trace -> 'trace_gap_reason' <> 'null'::jsonb
             OR jsonb_typeof(p_stage_metrics) <> 'object'
             OR jsonb_typeof(p_stage_metrics -> 'durations_ms') <> 'object'
             OR jsonb_typeof(p_stage_metrics -> 'counts') <> 'object'
             OR (p_stage_metrics -> 'durations_ms' ->> 'query_total_ms')::numeric < 0
             OR (p_stage_metrics -> 'counts' ->> 'query_total_ms')::integer <> 1
             THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TRACE';
          END IF;
          INSERT INTO milai.retrieval_trace (
            tenant_id, trace_id, request_id, route, consistency,
            query_fingerprint, query_plan, requested_scope, as_of,
            required_authority, canonical_snapshot_outbox_sequence,
            fts_watermark, vector_watermark, accepted_candidates,
            rejected_candidates, fallback_used, fallback_reason, abstained,
            abstention_reason, duration_ms, minimum_outbox_sequence,
            causal_wait_outcome, causal_waited_ms, execution_trace,
            stage_metrics, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_trace_id, p_request_id, p_route, p_consistency,
            p_query_fingerprint, p_query_plan, p_requested_scope, p_as_of,
            p_required_authority, p_canonical_snapshot, p_fts_watermark,
            p_vector_watermark, p_accepted, p_rejected, p_fallback_used,
            p_fallback_reason, p_abstained, p_abstention_reason,
            p_duration_ms, p_minimum_outbox_sequence, p_causal_wait_outcome,
            p_causal_waited_ms, p_execution_trace, p_stage_metrics, p_actor_id
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
    raise RuntimeError(
        "0029 downgrade is intentionally unsupported: dropping append-only AccessTrace facts "
        "would make post-0029 retrieval history unverifiable; restore a verified pre-0029 backup"
    )
