"""Rank Raw Evidence turns before any session expansion.

Revision ID: 0042_dg17_turn_first
Revises: 0041_dg16_evidence_order
"""

from __future__ import annotations

from alembic import op

revision = "0042_dg17_turn_first"
down_revision = "0041_dg16_evidence_order"
branch_labels = None
depends_on = None

SIGNATURE = "uuid, uuid, text, jsonb, timestamptz, integer, text"


def upgrade() -> None:
    _replace_search_function(turn_first=True)


def downgrade() -> None:
    _replace_search_function(turn_first=False)


def _replace_search_function(*, turn_first: bool) -> None:
    candidates = _turn_first_candidates() if turn_first else _session_first_candidates()
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
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_QUERY';
          END IF;

          __CANDIDATES__
          RETURN v_result;
        END
        $$
        """
    op.execute(statement.replace("__CANDIDATES__", candidates))
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.search_evidence_projection({SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.search_evidence_projection({SIGNATURE}) "
        "TO milai_api"
    )


def _turn_first_candidates() -> str:
    return """
          WITH live AS MATERIALIZED (
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
          ), ranked_turns AS MATERIALIZED (
            SELECT live.*,
                   ts_rank_cd(
                     live.search_vector, to_tsquery('simple', p_tsquery)
                   ) AS turn_score,
                   row_number() OVER (
                     ORDER BY ts_rank_cd(
                                live.search_vector,
                                to_tsquery('simple', p_tsquery)
                              ) DESC,
                              live.observed_at DESC,
                              live.source_ref,
                              live.evidence_id
                   ) AS turn_rank
            FROM live
            WHERE live.search_vector @@ to_tsquery('simple', p_tsquery)
          ), candidates AS (
            SELECT ranked_turns.turn_rank,
                   jsonb_build_object(
                     'kind', 'EVIDENCE_OBSERVATION',
                     'evidence_id', ranked_turns.evidence_id,
                     'evidence_ids', jsonb_build_array(ranked_turns.evidence_id),
                     'source_ref', ranked_turns.source_ref,
                     'subject_id', ranked_turns.subject_id,
                     'observed_at', ranked_turns.observed_at,
                     'captured_at', ranked_turns.captured_at,
                     'content', ranked_turns.lexical_text,
                     'content_hash', ranked_turns.content_hash,
                     'permission_snapshot', ranked_turns.permission_snapshot,
                     'retention_state', ranked_turns.live_retention_state,
                     'projection_version', ranked_turns.projection_version,
                     'source_outbox_sequence', ranked_turns.source_outbox_sequence,
                     'relevance_score', ranked_turns.turn_score,
                     'turn_rank', ranked_turns.turn_rank,
                     'candidate_unit', 'TURN',
                     'acquisition_channel', 'FTS_RAW',
                     'matched_fields', jsonb_build_array('lexical_text'),
                     'anchor_match', true,
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item
            FROM ranked_turns
            WHERE ranked_turns.turn_rank <= p_limit
          )
          SELECT COALESCE(
                   jsonb_agg(candidates.item ORDER BY candidates.turn_rank),
                   '[]'::jsonb
                 )
          INTO v_result
          FROM candidates;
    """


def _session_first_candidates() -> str:
    """Restore the deterministic 0041 behavior for an operational rollback."""

    return """
          WITH live AS MATERIALIZED (
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
          ), session_scores AS MATERIALIZED (
            SELECT subject_id,
                   max(ts_rank_cd(search_vector, to_tsquery('simple', p_tsquery)))
                     AS session_rank
            FROM live
            WHERE search_vector @@ to_tsquery('simple', p_tsquery)
            GROUP BY subject_id
            ORDER BY session_rank DESC, subject_id
            LIMIT LEAST(p_limit, 12)
          ), candidates AS (
            SELECT live.source_ref, live.subject_id, live.observed_at,
                   score.session_rank AS rank,
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
                     'anchor_match',
                       live.search_vector @@ to_tsquery('simple', p_tsquery),
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item
            FROM live
            JOIN session_scores score ON score.subject_id = live.subject_id
            ORDER BY score.session_rank DESC, live.subject_id,
                     live.observed_at, live.source_ref
            LIMIT p_limit
          )
          SELECT COALESCE(
                   jsonb_agg(candidates.item ORDER BY candidates.rank DESC,
                                                    candidates.subject_id,
                                                    candidates.observed_at,
                                                    candidates.source_ref),
                   '[]'::jsonb
                 )
          INTO v_result
          FROM candidates;
    """
