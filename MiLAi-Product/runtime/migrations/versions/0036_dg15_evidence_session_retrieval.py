"""Add multi-write readiness targets and session-aware Evidence retrieval.

Revision ID: 0036_dg15_evidence_session
Revises: 0035_dg15_watermark_reconcile
"""

from __future__ import annotations

from alembic import op

revision = "0036_dg15_evidence_session"
down_revision = "0035_dg15_watermark_reconcile"
branch_labels = None
depends_on = None

READINESS_MANY_SIGNATURE = "uuid,uuid,uuid[],text[],jsonb"
SEARCH_SIGNATURE = "uuid,uuid,text,jsonb,timestamptz,integer,text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.projection_readiness_status_many(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_target_outbox_ids uuid[],
          p_required_projections text[],
          p_expected_versions jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_target_id uuid;
          v_count integer;
          v_result jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF cardinality(p_target_outbox_ids) < 1
             OR cardinality(p_target_outbox_ids) > 512
             OR cardinality(p_target_outbox_ids) <>
                cardinality(ARRAY(SELECT DISTINCT unnest(p_target_outbox_ids))) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_READINESS_TARGETS';
          END IF;
          SELECT count(*), (
            array_agg(event.outbox_id ORDER BY event.outbox_sequence DESC)
          )[1]
          INTO v_count, v_target_id
          FROM milai.outbox_event event
          WHERE event.tenant_id = p_tenant_id
            AND event.outbox_id = ANY(p_target_outbox_ids);
          IF v_count <> cardinality(p_target_outbox_ids) OR v_target_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'OUTBOX_POSITION_NOT_FOUND';
          END IF;
          v_result := milai.projection_readiness_status(
            p_tenant_id, p_actor_id, v_target_id,
            p_required_projections, p_expected_versions
          );
          RETURN v_result || jsonb_build_object(
            'target_outbox_ids', to_jsonb(p_target_outbox_ids),
            'target_count', cardinality(p_target_outbox_ids)
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.projection_readiness_status_many("
        f"{READINESS_MANY_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.projection_readiness_status_many("
        f"{READINESS_MANY_SIGNATURE}) TO milai_api"
    )
    _create_search_function(session_aware=True)


def _create_search_function(*, session_aware: bool) -> None:
    if session_aware:
        candidates = """
          WITH live AS (
            SELECT document.*, evidence.revoked_at,
                   evidence.retention_state AS live_retention_state
            FROM milai.evidence_search_document document
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
            WHERE document.tenant_id = p_tenant_id
              AND document.projection_version = p_projection_version
              AND document.observed_at <= p_as_of
              AND evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
              AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND (
                NOT (p_requested_scope ? 'project_ids')
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                    COALESCE(evidence.permission_snapshot -> 'project_ids', '[]'::jsonb)
                  ) allowed(project_id)
                  JOIN jsonb_array_elements_text(
                    p_requested_scope -> 'project_ids'
                  ) requested(project_id)
                    ON requested.project_id = allowed.project_id
                )
              )
          ), session_scores AS (
            SELECT subject_id,
                   max(ts_rank_cd(search_vector, to_tsquery('simple', p_tsquery)))
                     AS session_rank
            FROM live
            WHERE search_vector @@ to_tsquery('simple', p_tsquery)
            GROUP BY subject_id
            ORDER BY session_rank DESC, subject_id
            LIMIT LEAST(p_limit, 12)
          )
          SELECT live.evidence_id, live.observed_at, score.session_rank AS rank,
                 jsonb_build_object(
                   'kind', 'EVIDENCE_OBSERVATION',
                   'evidence_id', live.evidence_id,
                   'evidence_ids', jsonb_build_array(live.evidence_id),
                   'source_ref', live.source_ref,
                   'subject_id', live.subject_id,
                   'observed_at', live.observed_at,
                   'captured_at', live.captured_at,
                   'content', live.lexical_text,
                   'content_hash', live.content_hash,
                   'permission_snapshot', live.permission_snapshot,
                   'retention_state', live.live_retention_state,
                   'projection_version', live.projection_version,
                   'source_outbox_sequence', live.source_outbox_sequence,
                   'relevance_score', score.session_rank,
                   'anchor_match', live.search_vector @@ to_tsquery('simple', p_tsquery),
                   'authority', 'EVIDENCE_ONLY',
                   'canonical', false
                 ) AS item
          FROM live
          JOIN session_scores score ON score.subject_id = live.subject_id
          ORDER BY score.session_rank DESC, live.subject_id,
                   live.observed_at, live.evidence_id
          LIMIT p_limit
        """
    else:
        candidates = """
          SELECT document.evidence_id, document.observed_at,
                 ts_rank_cd(document.search_vector, to_tsquery('simple', p_tsquery)) AS rank,
                 jsonb_build_object(
                   'kind', 'EVIDENCE_OBSERVATION',
                   'evidence_id', document.evidence_id,
                   'evidence_ids', jsonb_build_array(document.evidence_id),
                   'source_ref', document.source_ref,
                   'subject_id', document.subject_id,
                   'observed_at', document.observed_at,
                   'captured_at', document.captured_at,
                   'content', document.lexical_text,
                   'content_hash', document.content_hash,
                   'permission_snapshot', document.permission_snapshot,
                   'retention_state', evidence.retention_state,
                   'projection_version', document.projection_version,
                   'source_outbox_sequence', document.source_outbox_sequence,
                   'relevance_score', ts_rank_cd(
                     document.search_vector, to_tsquery('simple', p_tsquery)
                   ),
                   'authority', 'EVIDENCE_ONLY',
                   'canonical', false
                 ) AS item
          FROM milai.evidence_search_document document
          JOIN milai.evidence_record evidence
            ON evidence.tenant_id = document.tenant_id
           AND evidence.evidence_id = document.evidence_id
          WHERE document.tenant_id = p_tenant_id
            AND document.projection_version = p_projection_version
            AND document.search_vector @@ to_tsquery('simple', p_tsquery)
            AND document.observed_at <= p_as_of
            AND evidence.revoked_at IS NULL
            AND evidence.retention_state = 'READABLE'
            AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
            AND (
              NOT (p_requested_scope ? 'project_ids')
              OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(
                  COALESCE(evidence.permission_snapshot -> 'project_ids', '[]'::jsonb)
                ) allowed(project_id)
                JOIN jsonb_array_elements_text(
                  p_requested_scope -> 'project_ids'
                ) requested(project_id)
                  ON requested.project_id = allowed.project_id
              )
            )
          ORDER BY rank DESC, document.observed_at DESC, document.evidence_id
          LIMIT p_limit
        """
    statement = """
        CREATE OR REPLACE FUNCTION milai.search_evidence_projection(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_tsquery text,
          p_requested_scope jsonb,
          p_as_of timestamptz,
          p_limit integer,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_result jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF length(btrim(p_tsquery)) = 0 OR p_limit < 1 OR p_limit > 120
             OR p_projection_version <> 'evidence-search-v1'
             OR jsonb_typeof(p_requested_scope) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EVIDENCE_QUERY';
          END IF;
          SELECT COALESCE(jsonb_agg(candidate.item ORDER BY candidate.rank DESC,
                                                        candidate.observed_at,
                                                        candidate.evidence_id), '[]'::jsonb)
          INTO v_result
          FROM (
            __CANDIDATES__
          ) candidate;
          RETURN v_result;
        END
        $$
        """
    op.execute(statement.replace("__CANDIDATES__", candidates))
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    _create_search_function(session_aware=False)
    op.execute(
        f"DROP FUNCTION milai.projection_readiness_status_many("
        f"{READINESS_MANY_SIGNATURE})"
    )
