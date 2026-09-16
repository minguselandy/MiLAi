"""Add the canonical retrieval gate and append-only retrieval trace.

Revision ID: 0008_retrieval_gate
Revises: 0007_projection_outbox

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_retrieval_gate"
down_revision: str | None = "0007_projection_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GATE_SIGNATURE = "uuid, uuid, uuid[], text, jsonb, timestamptz"
STATE_SIGNATURE = "uuid, uuid"
TRACE_SIGNATURE = (
    "uuid, uuid, text, text, text, text, jsonb, timestamptz, text, bigint, "
    "bigint, bigint, jsonb, jsonb, boolean, text, boolean, text, integer"
)


def upgrade() -> None:
    op.create_table(
        "retrieval_trace",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("consistency", sa.Text(), nullable=False),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("requested_scope", postgresql.JSONB(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("required_authority", sa.Text(), nullable=False),
        sa.Column("canonical_snapshot_outbox_sequence", sa.BigInteger(), nullable=False),
        sa.Column("fts_watermark", sa.BigInteger(), nullable=True),
        sa.Column("vector_watermark", sa.BigInteger(), nullable=True),
        sa.Column("accepted_candidates", postgresql.JSONB(), nullable=False),
        sa.Column("rejected_candidates", postgresql.JSONB(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("abstention_reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "trace_id", name="pk_retrieval_trace"),
        sa.CheckConstraint("route IN ('L0', 'L1')", name="ck_retrieval_trace_route"),
        sa.CheckConstraint(
            "consistency IN ('EVENTUAL', 'READ_YOUR_WRITES', 'CANONICAL_REQUIRED')",
            name="ck_retrieval_trace_consistency",
        ),
        sa.CheckConstraint(
            "query_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_retrieval_trace_fingerprint"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requested_scope) = 'object'",
            name="ck_retrieval_trace_scope",
        ),
        sa.CheckConstraint(
            "required_authority IN ('INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED')",
            name="ck_retrieval_trace_authority",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(accepted_candidates) = 'array' "
            "AND jsonb_typeof(rejected_candidates) = 'array'",
            name="ck_retrieval_trace_candidates",
        ),
        sa.CheckConstraint(
            "(fallback_used AND fallback_reason IS NOT NULL) "
            "OR (NOT fallback_used AND fallback_reason IS NULL)",
            name="ck_retrieval_trace_fallback",
        ),
        sa.CheckConstraint(
            "(abstained AND abstention_reason IS NOT NULL) "
            "OR (NOT abstained AND abstention_reason IS NULL)",
            name="ck_retrieval_trace_abstention",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_retrieval_trace_duration"),
        schema="milai",
    )
    op.create_index(
        "ix_retrieval_trace_created",
        "retrieval_trace",
        ["tenant_id", sa.text("created_at DESC")],
        schema="milai",
    )
    op.execute("ALTER TABLE milai.retrieval_trace ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.retrieval_trace FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY retrieval_trace_tenant_isolation
        ON milai.retrieval_trace
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_retrieval_trace_append_only
        BEFORE UPDATE OR DELETE ON milai.retrieval_trace
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.retrieval_projection_state(
          p_tenant_id uuid,
          p_actor_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          RETURN jsonb_build_object(
            'canonical_snapshot_outbox_sequence', COALESCE((
              SELECT max(event.outbox_sequence)
              FROM milai.outbox_event event
              WHERE event.tenant_id = p_tenant_id
            ), 0),
            'fts_watermark', COALESCE((
              SELECT watermark.last_contiguous_outbox_sequence
              FROM milai.index_watermark watermark
              WHERE watermark.tenant_id = p_tenant_id
                AND watermark.projection_name = 'fts'
            ), 0),
            'vector_watermark', COALESCE((
              SELECT watermark.last_contiguous_outbox_sequence
              FROM milai.index_watermark watermark
              WHERE watermark.tenant_id = p_tenant_id
                AND watermark.projection_name = 'vector'
            ), 0),
            'fts_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery delivery
              WHERE delivery.tenant_id = p_tenant_id
                AND delivery.projection_name = 'fts'
                AND delivery.state = 'DEAD_LETTER'
            ),
            'vector_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery delivery
              WHERE delivery.tenant_id = p_tenant_id
                AND delivery.projection_name = 'vector'
                AND delivery.state = 'DEAD_LETTER'
            )
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.evaluate_canonical_candidates(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_claim_version_ids uuid[],
          p_required_authority text,
          p_requested_scope jsonb,
          p_as_of timestamptz
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_candidate_id uuid;
          v_version milai.claim_version%ROWTYPE;
          v_claim milai.claim%ROWTYPE;
          v_head_id uuid;
          v_reason text;
          v_evidence_ids jsonb;
          v_issue_ids jsonb;
          v_result jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_required_authority NOT IN (
            'INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED'
          ) OR jsonb_typeof(p_requested_scope) <> 'object'
             OR p_as_of IS NULL
             OR COALESCE(cardinality(p_claim_version_ids), 0) > 256 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_GATE_REQUEST';
          END IF;

          FOREACH v_candidate_id IN ARRAY COALESCE(p_claim_version_ids, '{}'::uuid[])
          LOOP
            v_reason := NULL;
            v_evidence_ids := '[]'::jsonb;
            v_issue_ids := '[]'::jsonb;
            SELECT * INTO v_version
            FROM milai.claim_version
            WHERE tenant_id = p_tenant_id AND claim_version_id = v_candidate_id;
            IF NOT FOUND THEN
              v_reason := 'UNKNOWN_CANDIDATE';
            ELSE
              SELECT * INTO STRICT v_claim FROM milai.claim
              WHERE tenant_id = p_tenant_id AND claim_id = v_version.claim_id;
              SELECT current_claim_version_id INTO v_head_id
              FROM milai.claim_head
              WHERE tenant_id = p_tenant_id AND claim_id = v_version.claim_id;
              v_evidence_ids := COALESCE((
                SELECT jsonb_agg(DISTINCT gr.evidence_id ORDER BY gr.evidence_id)
                FROM milai.grounding_relation gr
                WHERE gr.tenant_id = p_tenant_id
                  AND gr.claim_version_id = v_candidate_id
                  AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              ), '[]'::jsonb);
              v_issue_ids := COALESCE((
                SELECT jsonb_agg(oi.issue_id ORDER BY oi.issue_id)
                FROM milai.open_issue oi
                WHERE oi.tenant_id = p_tenant_id
                  AND oi.target_claim_id = v_version.claim_id
                  AND oi.status NOT IN ('RESOLVED', 'DISMISSED')
              ), '[]'::jsonb);

              IF v_head_id IS DISTINCT FROM v_candidate_id THEN
                v_reason := 'STALE_VERSION';
              ELSIF v_version.lifecycle <> 'ACTIVE' THEN
                v_reason := 'RETIRED';
              ELSIF NOT v_version.scope_predicate @> p_requested_scope THEN
                v_reason := 'SCOPE_MISMATCH';
              ELSIF (v_version.valid_time_from IS NOT NULL
                     AND v_version.valid_time_from > p_as_of)
                 OR (v_version.valid_time_to IS NOT NULL
                     AND v_version.valid_time_to <= p_as_of) THEN
                v_reason := 'OUTSIDE_VALID_TIME';
              ELSIF NOT milai.authority_satisfies(
                v_version.authority, p_required_authority
              ) THEN
                v_reason := 'AUTHORITY_INSUFFICIENT';
              ELSIF EXISTS (
                SELECT 1 FROM milai.grounding_block block
                WHERE block.tenant_id = p_tenant_id
                  AND block.claim_version_id = v_candidate_id AND block.active
              ) THEN
                v_reason := 'GROUNDING_BLOCKED';
              ELSIF jsonb_array_length(v_issue_ids) > 0 THEN
                v_reason := 'OPEN_ISSUE';
              ELSIF jsonb_array_length(v_evidence_ids) = 0 THEN
                v_reason := 'LINEAGE_MISSING';
              ELSIF EXISTS (
                SELECT 1
                FROM milai.grounding_relation gr
                JOIN milai.evidence_record evidence
                  ON evidence.tenant_id = gr.tenant_id
                 AND evidence.evidence_id = gr.evidence_id
                WHERE gr.tenant_id = p_tenant_id
                  AND gr.claim_version_id = v_candidate_id
                  AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                  AND evidence.revoked_at IS NOT NULL
              ) THEN
                v_reason := 'EVIDENCE_REVOKED';
              ELSIF EXISTS (
                SELECT 1
                FROM milai.grounding_relation gr
                JOIN milai.evidence_record evidence
                  ON evidence.tenant_id = gr.tenant_id
                 AND evidence.evidence_id = gr.evidence_id
                WHERE gr.tenant_id = p_tenant_id
                  AND gr.claim_version_id = v_candidate_id
                  AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                  AND evidence.retention_state <> 'READABLE'
              ) THEN
                v_reason := 'RETENTION_UNREADABLE';
              ELSIF EXISTS (
                SELECT 1
                FROM milai.grounding_relation gr
                JOIN milai.evidence_record evidence
                  ON evidence.tenant_id = gr.tenant_id
                 AND evidence.evidence_id = gr.evidence_id
                WHERE gr.tenant_id = p_tenant_id
                  AND gr.claim_version_id = v_candidate_id
                  AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                  AND NOT evidence.permission_snapshot @> '{"readable": true}'::jsonb
              ) THEN
                v_reason := 'PERMISSION_DENIED';
              END IF;
            END IF;

            v_result := v_result || jsonb_build_array(jsonb_build_object(
              'claim_version_id', v_candidate_id,
              'claim_id', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                               THEN NULL ELSE v_version.claim_id END,
              'accepted', v_reason IS NULL,
              'reject_reason', v_reason,
              'authority', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                THEN NULL ELSE v_version.authority END,
              'canonical_commit_seq', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                           THEN NULL
                                           ELSE v_version.canonical_commit_seq END,
              'evidence_ids', v_evidence_ids,
              'open_issue_ids', v_issue_ids
            ));
          END LOOP;
          RETURN v_result;
        END
        $$
        """
    )

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

    op.execute(
        "REVOKE ALL ON TABLE milai.retrieval_trace "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.retrieval_trace TO milai_api, milai_steward, milai_audit"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.retrieval_projection_state({STATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.retrieval_projection_state({STATE_SIGNATURE}) "
        "TO milai_api, milai_steward"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.evaluate_canonical_candidates({GATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.evaluate_canonical_candidates({GATE_SIGNATURE}) "
        "TO milai_api, milai_steward"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_retrieval_trace({TRACE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_retrieval_trace({TRACE_SIGNATURE}) TO milai_api"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.record_retrieval_trace({TRACE_SIGNATURE})")
    op.execute(f"DROP FUNCTION milai.evaluate_canonical_candidates({GATE_SIGNATURE})")
    op.execute(f"DROP FUNCTION IF EXISTS milai.retrieval_projection_state({STATE_SIGNATURE})")
    op.drop_index("ix_retrieval_trace_created", table_name="retrieval_trace", schema="milai")
    op.drop_table("retrieval_trace", schema="milai")
