"""Add a governed, bounded Raw Evidence time-range scan for DG-16 Q2.

Revision ID: 0040_dg16_bounded_scan
Revises: 0039_dg15_search_purge_batch
"""

from __future__ import annotations

from alembic import op

revision = "0040_dg16_bounded_scan"
down_revision = "0039_dg15_search_purge_batch"
branch_labels = None
depends_on = None

SIGNATURE = "uuid, uuid, jsonb, timestamptz, timestamptz, integer, text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.scan_evidence_projection_range(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_requested_scope jsonb,
          p_range_start timestamptz,
          p_range_end timestamptz,
          p_max_items integer,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_source_count integer;
          v_projected_count integer;
          v_target_watermark bigint;
          v_current_watermark bigint;
          v_dead_letter boolean;
          v_items jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF jsonb_typeof(p_requested_scope) <> 'object'
             OR p_range_start >= p_range_end
             OR p_max_items < 1 OR p_max_items > 2000
             OR p_projection_version <> 'evidence-search-v1' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_RANGE_SCAN';
          END IF;

          WITH eligible AS MATERIALIZED (
            SELECT evidence.evidence_id, evidence.source_ref,
                   evidence.subject_id, evidence.observed_at,
                   evidence.captured_at, evidence.content_hash,
                   evidence.permission_snapshot, evidence.retention_state,
                   outbox.outbox_sequence
            FROM milai.evidence_record evidence
            JOIN milai.outbox_event outbox
              ON outbox.tenant_id = evidence.tenant_id
             AND outbox.aggregate_id = evidence.evidence_id
             AND outbox.event_type = 'EVIDENCE_INGESTED'
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.observed_at >= p_range_start
              AND evidence.observed_at < p_range_end
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
          )
          SELECT count(*), COALESCE(max(outbox_sequence), 0)
          INTO v_source_count, v_target_watermark
          FROM eligible;

          SELECT COALESCE(watermark.last_contiguous_outbox_sequence, 0)
          INTO v_current_watermark
          FROM (SELECT 1) singleton
          LEFT JOIN milai.index_watermark watermark
            ON watermark.tenant_id = p_tenant_id
           AND watermark.projection_name = 'evidence';

          SELECT EXISTS (
            SELECT 1
            FROM milai.projection_delivery delivery
            WHERE delivery.tenant_id = p_tenant_id
              AND delivery.projection_name = 'evidence'
              AND delivery.state = 'DEAD_LETTER'
              AND delivery.outbox_sequence <= v_target_watermark
          ) INTO v_dead_letter;

          WITH eligible AS MATERIALIZED (
            SELECT evidence.evidence_id, evidence.source_ref,
                   evidence.subject_id, evidence.observed_at,
                   evidence.captured_at, evidence.content_hash,
                   evidence.permission_snapshot, evidence.retention_state
            FROM milai.evidence_record evidence
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.observed_at >= p_range_start
              AND evidence.observed_at < p_range_end
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
          ), projected AS MATERIALIZED (
            SELECT document.*, eligible.retention_state AS live_retention_state
            FROM eligible
            JOIN milai.evidence_search_document document
              ON document.tenant_id = p_tenant_id
             AND document.evidence_id = eligible.evidence_id
             AND document.projection_version = p_projection_version
          ), selected AS (
            SELECT jsonb_build_object(
                     'kind', 'EVIDENCE_OBSERVATION',
                     'evidence_id', projected.evidence_id,
                     'evidence_ids', jsonb_build_array(projected.evidence_id),
                     'source_ref', projected.source_ref,
                     'subject_id', projected.subject_id,
                     'observed_at', projected.observed_at,
                     'captured_at', projected.captured_at,
                     'content', projected.lexical_text,
                     'content_hash', projected.content_hash,
                     'permission_snapshot', projected.permission_snapshot,
                     'retention_state', projected.live_retention_state,
                     'projection_version', projected.projection_version,
                     'source_outbox_sequence', projected.source_outbox_sequence,
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item,
                   projected.observed_at, projected.source_ref,
                   projected.evidence_id
            FROM projected
            ORDER BY projected.observed_at, projected.source_ref,
                     projected.evidence_id
            LIMIT p_max_items
          )
          SELECT (SELECT count(*) FROM projected),
                 COALESCE(
                   jsonb_agg(selected.item ORDER BY selected.observed_at,
                                                      selected.source_ref,
                                                      selected.evidence_id),
                   '[]'::jsonb
                 )
          INTO v_projected_count, v_items
          FROM selected;

          RETURN jsonb_build_object(
            'status', CASE
              WHEN v_dead_letter THEN 'UNAVAILABLE'
              WHEN v_current_watermark < v_target_watermark THEN 'PARTIAL'
              WHEN v_projected_count <> v_source_count THEN 'PARTIAL'
              WHEN v_source_count > p_max_items THEN 'PARTIAL'
              ELSE 'COMPLETE'
            END,
            'items', v_items,
            'range_start', p_range_start,
            'range_end', p_range_end,
            'boundary', 'CLOSED_OPEN',
            'source_count', v_source_count,
            'projected_count', v_projected_count,
            'returned_count', jsonb_array_length(v_items),
            'max_items', p_max_items,
            'source_partition_closed', true,
            'projection_watermark', v_current_watermark,
            'target_watermark', v_target_watermark,
            'projection_watermark_covered',
              v_current_watermark >= v_target_watermark,
            'dead_letter_gap', v_dead_letter,
            'unreadable_evidence_count', 0,
            'projection_version', p_projection_version
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.scan_evidence_projection_range({SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.scan_evidence_projection_range({SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.scan_evidence_projection_range({SIGNATURE})"
    )
