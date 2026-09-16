"""Add bounded lexical Evidence search within acquired source/session pairs.

Revision ID: 0054_intra_source_shadow
Revises: 0053_continuation_hardening

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

from alembic import op

revision = "0054_intra_source_shadow"
down_revision = "0053_continuation_hardening"
branch_labels = None
depends_on = None

SIGNATURE = "uuid,uuid,text,uuid[],jsonb,timestamptz,integer,integer,text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.search_evidence_projection_within_sources(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_tsquery text,
          p_coarse_evidence_ids uuid[],
          p_requested_scope jsonb,
          p_as_of timestamptz,
          p_hits_per_session integer,
          p_max_items integer,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_result jsonb;
          v_source_count integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_tsquery IS NULL OR length(btrim(p_tsquery)) = 0
             OR p_coarse_evidence_ids IS NULL
             OR cardinality(p_coarse_evidence_ids) < 1
             OR cardinality(p_coarse_evidence_ids) > 120
             OR p_requested_scope IS NULL
             OR p_as_of IS NULL
             OR p_hits_per_session IS NULL
             OR p_hits_per_session < 1 OR p_hits_per_session > 8
             OR p_max_items IS NULL
             OR p_max_items < 1 OR p_max_items > 120
             OR p_projection_version IS NULL
             OR p_projection_version <> 'evidence-search-v1'
             OR jsonb_typeof(p_requested_scope) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_INTRA_SOURCE_EVIDENCE_QUERY';
          END IF;

          WITH requested AS MATERIALIZED (
            SELECT requested.evidence_id, requested.source_pool_order
            FROM unnest(p_coarse_evidence_ids) WITH ORDINALITY
              AS requested(evidence_id, source_pool_order)
          ), allowed_sources AS MATERIALIZED (
            SELECT anchor_evidence.source_type,
                   anchor_document.source_session_id,
                   min(requested.source_pool_order) AS source_pool_order
            FROM requested
            JOIN milai.evidence_search_document anchor_document
              ON anchor_document.tenant_id = p_tenant_id
             AND anchor_document.evidence_id = requested.evidence_id
            JOIN milai.evidence_record anchor_evidence
              ON anchor_evidence.tenant_id = anchor_document.tenant_id
             AND anchor_evidence.evidence_id = anchor_document.evidence_id
             AND anchor_evidence.content_hash = anchor_document.content_hash
            WHERE anchor_document.projection_version = p_projection_version
              AND anchor_document.observed_at <= p_as_of
              AND anchor_document.source_context_source IN (
                'STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'
              )
              AND anchor_evidence.revoked_at IS NULL
              AND anchor_evidence.retention_state = 'READABLE'
              AND anchor_evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND (
                NOT (p_requested_scope ? 'project_ids')
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                    COALESCE(
                      anchor_evidence.permission_snapshot -> 'project_ids', '[]'::jsonb
                    )
                  ) allowed(project_id)
                  JOIN jsonb_array_elements_text(
                    p_requested_scope -> 'project_ids'
                  ) requested_project(project_id)
                    ON requested_project.project_id = allowed.project_id
                )
              )
            GROUP BY anchor_evidence.source_type, anchor_document.source_session_id
          )
          SELECT count(*) INTO v_source_count FROM allowed_sources;

          IF v_source_count > 50 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INTRA_SOURCE_POOL_LIMIT_EXCEEDED';
          END IF;

          WITH requested AS MATERIALIZED (
            SELECT requested.evidence_id, requested.source_pool_order
            FROM unnest(p_coarse_evidence_ids) WITH ORDINALITY
              AS requested(evidence_id, source_pool_order)
          ), allowed_sources AS MATERIALIZED (
            SELECT anchor_evidence.source_type,
                   anchor_document.source_session_id,
                   min(requested.source_pool_order) AS source_pool_order
            FROM requested
            JOIN milai.evidence_search_document anchor_document
              ON anchor_document.tenant_id = p_tenant_id
             AND anchor_document.evidence_id = requested.evidence_id
            JOIN milai.evidence_record anchor_evidence
              ON anchor_evidence.tenant_id = anchor_document.tenant_id
             AND anchor_evidence.evidence_id = anchor_document.evidence_id
             AND anchor_evidence.content_hash = anchor_document.content_hash
            WHERE anchor_document.projection_version = p_projection_version
              AND anchor_document.observed_at <= p_as_of
              AND anchor_document.source_context_source IN (
                'STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'
              )
              AND anchor_evidence.revoked_at IS NULL
              AND anchor_evidence.retention_state = 'READABLE'
              AND anchor_evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND (
                NOT (p_requested_scope ? 'project_ids')
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                    COALESCE(
                      anchor_evidence.permission_snapshot -> 'project_ids', '[]'::jsonb
                    )
                  ) allowed(project_id)
                  JOIN jsonb_array_elements_text(
                    p_requested_scope -> 'project_ids'
                  ) requested_project(project_id)
                    ON requested_project.project_id = allowed.project_id
                )
              )
            GROUP BY anchor_evidence.source_type, anchor_document.source_session_id
          ), live AS MATERIALIZED (
            SELECT document.*,
                   evidence.source_type,
                   evidence.retention_state AS live_retention_state,
                   allowed_sources.source_pool_order
            FROM milai.evidence_search_document document
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
             AND evidence.content_hash = document.content_hash
            JOIN allowed_sources
              ON allowed_sources.source_type = evidence.source_type
             AND allowed_sources.source_session_id = document.source_session_id
            WHERE document.tenant_id = p_tenant_id
              AND document.projection_version = p_projection_version
              AND document.observed_at <= p_as_of
              AND document.source_context_source IN (
                'STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'
              )
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
          ), ranked AS MATERIALIZED (
            SELECT live.*,
                   ts_rank_cd(
                     live.search_vector, to_tsquery('simple', p_tsquery)
                   ) AS lexical_score,
                   row_number() OVER (
                     PARTITION BY live.source_type, live.source_session_id
                     ORDER BY ts_rank_cd(
                                live.search_vector, to_tsquery('simple', p_tsquery)
                              ) DESC,
                              live.observed_at DESC,
                              live.source_turn_ordinal,
                              live.source_ref,
                              live.evidence_id
                   ) AS fine_source_rank
            FROM live
            WHERE live.search_vector @@ to_tsquery('simple', p_tsquery)
          ), bounded AS MATERIALIZED (
            SELECT ranked.*,
                   row_number() OVER (
                     ORDER BY ranked.source_pool_order,
                              ranked.lexical_score DESC,
                              ranked.fine_source_rank,
                              ranked.source_ref,
                              ranked.evidence_id
                   ) AS fine_global_rank
            FROM ranked
            WHERE ranked.fine_source_rank <= p_hits_per_session
          ), limited AS MATERIALIZED (
            SELECT * FROM bounded
            ORDER BY fine_global_rank
            LIMIT p_max_items
          ), rendered AS (
            SELECT limited.fine_global_rank,
                   jsonb_build_object(
                     'kind', 'EVIDENCE_OBSERVATION',
                     'evidence_id', limited.evidence_id,
                     'evidence_ids', jsonb_build_array(limited.evidence_id),
                     'source_type', limited.source_type,
                     'source_ref', limited.source_ref,
                     'subject_id', limited.subject_id,
                     'speaker', COALESCE(limited.source_speaker, 'unknown'),
                     'speaker_source', limited.speaker_source,
                     'source_context', jsonb_build_object(
                       'session_id', limited.source_session_id,
                       'turn_id', limited.source_turn_id,
                       'turn_ordinal', limited.source_turn_ordinal,
                       'round_id', limited.source_round_id,
                       'round_ordinal', limited.source_round_ordinal,
                       'previous_turn_id', limited.previous_source_turn_id,
                       'next_turn_id', limited.next_source_turn_id
                     ),
                     'source_context_source', limited.source_context_source,
                     'observed_at', limited.observed_at,
                     'captured_at', limited.captured_at,
                     'content', limited.lexical_text,
                     'content_hash', limited.content_hash,
                     'permission_snapshot', limited.permission_snapshot,
                     'retention_state', limited.live_retention_state,
                     'projection_version', limited.projection_version,
                     'source_outbox_sequence', limited.source_outbox_sequence,
                     'relevance_score', limited.lexical_score,
                     'fine_source_rank', limited.fine_source_rank,
                     'fine_global_rank', limited.fine_global_rank,
                     'candidate_unit', 'TURN',
                     'acquisition_channel', 'FTS_INTRA_SOURCE',
                     'sidecar_channel', 'EXPLICIT_INTRA_SOURCE_ACQUISITION',
                     'matched_fields', jsonb_build_array('lexical_text'),
                     'anchor_match', true,
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item
            FROM limited
          )
          SELECT COALESCE(
            jsonb_agg(rendered.item ORDER BY rendered.fine_global_rank),
            '[]'::jsonb
          ) INTO v_result
          FROM rendered;
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        f"milai.search_evidence_projection_within_sources({SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        f"milai.search_evidence_projection_within_sources({SIGNATURE}) TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE ALL ON FUNCTION "
        f"milai.search_evidence_projection_within_sources({SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "DROP FUNCTION "
        f"milai.search_evidence_projection_within_sources({SIGNATURE})"
    )
