"""Add governed exact Evidence hydration for noncanonical sidecars.

Revision ID: 0047_formation_hydration
Revises: 0046_proposal_idempotency

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047_formation_hydration"
down_revision: str | None = "0046_proposal_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HYDRATE_SIGNATURE = "uuid, uuid, uuid[], jsonb, timestamptz, integer, text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.hydrate_evidence_projection_by_id(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_evidence_ids uuid[],
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
          IF cardinality(p_evidence_ids) < 1
             OR cardinality(p_evidence_ids) > 24
             OR p_limit < 1 OR p_limit > 24
             OR p_projection_version <> 'evidence-search-v1'
             OR jsonb_typeof(p_requested_scope) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_ID_HYDRATION_QUERY';
          END IF;

          WITH requested AS MATERIALIZED (
            SELECT value.evidence_id, min(value.input_order) AS input_order
            FROM unnest(p_evidence_ids) WITH ORDINALITY
              AS value(evidence_id, input_order)
            GROUP BY value.evidence_id
          ), live AS MATERIALIZED (
            SELECT document.*, evidence.retention_state AS live_retention_state,
                   requested.input_order
            FROM requested
            JOIN milai.evidence_search_document document
              ON document.tenant_id = p_tenant_id
             AND document.evidence_id = requested.evidence_id
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
            WHERE document.projection_version = p_projection_version
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
                  ) requested_scope(project_id)
                    ON requested_scope.project_id = allowed.project_id
                )
              )
          ), limited AS MATERIALIZED (
            SELECT *
            FROM live
            ORDER BY input_order, source_ref, evidence_id
            LIMIT p_limit
          ), rendered AS (
            SELECT limited.input_order,
                   limited.source_ref,
                   limited.evidence_id,
                   jsonb_build_object(
                     'kind', 'EVIDENCE_OBSERVATION',
                     'evidence_id', limited.evidence_id,
                     'evidence_ids', jsonb_build_array(limited.evidence_id),
                     'source_ref', limited.source_ref,
                     'subject_id', limited.subject_id,
                     'speaker', COALESCE(limited.source_speaker, 'unknown'),
                     'speaker_source', limited.speaker_source,
                     'source_context',
                       CASE WHEN limited.source_context_source = 'UNKNOWN' THEN NULL
                            ELSE jsonb_build_object(
                              'session_id', limited.source_session_id,
                              'turn_id', limited.source_turn_id,
                              'turn_ordinal', limited.source_turn_ordinal,
                              'round_id', limited.source_round_id,
                              'round_ordinal', limited.source_round_ordinal,
                              'previous_turn_id', limited.previous_source_turn_id,
                              'next_turn_id', limited.next_source_turn_id
                            ) END,
                     'source_context_source', limited.source_context_source,
                     'observed_at', limited.observed_at,
                     'captured_at', limited.captured_at,
                     'content', limited.lexical_text,
                     'content_hash', limited.content_hash,
                     'permission_snapshot', limited.permission_snapshot,
                     'retention_state', limited.live_retention_state,
                     'projection_version', limited.projection_version,
                     'source_outbox_sequence', limited.source_outbox_sequence,
                     'relevance_score', 0.0,
                     'candidate_unit', 'TURN',
                     'acquisition_channel', 'FTS_RAW',
                     'sidecar_channel', 'FORMED_SOURCE_HYDRATION',
                     'matched_fields', jsonb_build_array('formation_source_id'),
                     'anchor_match', false,
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item
            FROM limited
          )
          SELECT COALESCE(
                   jsonb_agg(
                     rendered.item
                     ORDER BY rendered.input_order,
                              rendered.source_ref,
                              rendered.evidence_id
                   ),
                   '[]'::jsonb
                 )
          INTO v_result
          FROM rendered;
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.hydrate_evidence_projection_by_id("
        f"{HYDRATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.hydrate_evidence_projection_by_id("
        f"{HYDRATE_SIGNATURE}) TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.hydrate_evidence_projection_by_id({HYDRATE_SIGNATURE})"
    )
