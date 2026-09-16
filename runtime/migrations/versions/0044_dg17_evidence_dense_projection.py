"""Add an optional, rebuildable 128d Raw Evidence dense projection.

Revision ID: 0044_dg17_evidence_dense
Revises: 0043_dg17_speaker
"""

from __future__ import annotations

from alembic import op

revision = "0044_dg17_evidence_dense"
down_revision = "0043_dg17_speaker"
branch_labels = None
depends_on = None

UPSERT_SIGNATURE = "uuid, uuid, jsonb, text, text"
SEARCH_SIGNATURE = (
    "uuid, uuid, double precision[], jsonb, timestamptz, timestamptz, "
    "timestamptz, integer, text, text"
)
BACKFILL_SIGNATURE = "uuid, uuid, uuid, integer, text, text"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE milai.evidence_dense_embedding_128 (
          tenant_id uuid NOT NULL,
          evidence_id uuid NOT NULL,
          model_id text NOT NULL,
          projection_version text NOT NULL,
          embedding vector(128) NOT NULL,
          source_outbox_sequence bigint NOT NULL,
          projected_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_evidence_dense_embedding_128 PRIMARY KEY (
            tenant_id, evidence_id, model_id, projection_version
          ),
          CONSTRAINT fk_evidence_dense_document FOREIGN KEY (tenant_id, evidence_id)
            REFERENCES milai.evidence_search_document (tenant_id, evidence_id)
            ON DELETE CASCADE,
          CONSTRAINT ck_evidence_dense_model CHECK (length(btrim(model_id)) > 0),
          CONSTRAINT ck_evidence_dense_version CHECK (
            length(btrim(projection_version)) > 0
          ),
          CONSTRAINT ck_evidence_dense_sequence CHECK (source_outbox_sequence > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_evidence_dense_embedding_128_hnsw
        ON milai.evidence_dense_embedding_128
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_evidence_dense_embedding_128_identity
        ON milai.evidence_dense_embedding_128 (
          tenant_id, model_id, projection_version, evidence_id
        )
        """
    )
    op.execute("ALTER TABLE milai.evidence_dense_embedding_128 ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.evidence_dense_embedding_128 FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY evidence_dense_tenant_isolation
        ON milai.evidence_dense_embedding_128
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )
    op.execute("REVOKE ALL ON TABLE milai.evidence_dense_embedding_128 FROM PUBLIC")

    op.execute(
        """
        CREATE FUNCTION milai.upsert_evidence_dense_128(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_items jsonb,
          p_model_id text,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai, public
        AS $$
        DECLARE
          v_requested integer;
          v_projected integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF jsonb_typeof(p_items) <> 'array'
             OR jsonb_array_length(p_items) < 1
             OR jsonb_array_length(p_items) > 128
             OR length(btrim(p_model_id)) = 0
             OR length(p_model_id) > 255
             OR length(btrim(p_projection_version)) = 0
             OR length(p_projection_version) > 512 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_DENSE_BATCH';
          END IF;

          WITH items AS (
            SELECT item.evidence_id, item.embedding
            FROM jsonb_to_recordset(p_items)
              AS item(evidence_id uuid, embedding jsonb)
          )
          SELECT count(*), count(DISTINCT evidence_id)
          INTO v_requested, v_projected
          FROM items;
          IF v_requested <> v_projected OR EXISTS (
            SELECT 1
            FROM jsonb_to_recordset(p_items)
              AS item(evidence_id uuid, embedding jsonb)
            WHERE item.evidence_id IS NULL
               OR jsonb_typeof(item.embedding) <> 'array'
               OR jsonb_array_length(item.embedding) <> 128
               OR EXISTS (
                 SELECT 1 FROM jsonb_array_elements(item.embedding) element(value)
                 WHERE jsonb_typeof(element.value) <> 'number'
               )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_DENSE_ITEM';
          END IF;

          INSERT INTO milai.evidence_dense_embedding_128 (
            tenant_id, evidence_id, model_id, projection_version,
            embedding, source_outbox_sequence, created_by_actor_id
          )
          SELECT p_tenant_id, item.evidence_id, p_model_id, p_projection_version,
                 (
                   SELECT array_agg((element.value #>> '{}')::double precision
                                    ORDER BY element.ordinality)::vector(128)
                   FROM jsonb_array_elements(item.embedding)
                     WITH ORDINALITY AS element(value, ordinality)
                 ),
                 document.source_outbox_sequence, p_actor_id
          FROM jsonb_to_recordset(p_items)
            AS item(evidence_id uuid, embedding jsonb)
          JOIN milai.evidence_search_document document
            ON document.tenant_id = p_tenant_id
           AND document.evidence_id = item.evidence_id
          ON CONFLICT (tenant_id, evidence_id, model_id, projection_version)
          DO UPDATE SET
            embedding = EXCLUDED.embedding,
            source_outbox_sequence = EXCLUDED.source_outbox_sequence,
            projected_at = CURRENT_TIMESTAMP,
            created_by_actor_id = EXCLUDED.created_by_actor_id;
          GET DIAGNOSTICS v_projected = ROW_COUNT;
          IF v_projected <> v_requested THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'EVIDENCE_DENSE_SOURCE_GAP';
          END IF;
          RETURN jsonb_build_object(
            'status', 'COMPLETE',
            'projected_count', v_projected,
            'model_id', p_model_id,
            'projection_version', p_projection_version
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.search_evidence_dense_128(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_embedding double precision[],
          p_requested_scope jsonb,
          p_as_of timestamptz,
          p_source_start timestamptz,
          p_source_end timestamptz,
          p_limit integer,
          p_model_id text,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai, public
        AS $$
        DECLARE
          v_source_count integer;
          v_projected_count integer;
          v_items jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF cardinality(p_embedding) <> 128
             OR jsonb_typeof(p_requested_scope) <> 'object'
             OR p_as_of IS NULL
             OR (p_source_start IS NULL) <> (p_source_end IS NULL)
             OR (p_source_start IS NOT NULL AND p_source_start >= p_source_end)
             OR p_limit < 1 OR p_limit > 30
             OR length(btrim(p_model_id)) = 0
             OR length(btrim(p_projection_version)) = 0 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_DENSE_QUERY';
          END IF;

          WITH eligible AS MATERIALIZED (
            SELECT document.*
            FROM milai.evidence_search_document document
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
            WHERE document.tenant_id = p_tenant_id
              AND document.observed_at <= p_as_of
              AND (p_source_start IS NULL OR (
                document.observed_at >= p_source_start
                AND document.observed_at < p_source_end
              ))
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
            SELECT eligible.*, dense.embedding
            FROM eligible
            JOIN milai.evidence_dense_embedding_128 dense
              ON dense.tenant_id = eligible.tenant_id
             AND dense.evidence_id = eligible.evidence_id
             AND dense.model_id = p_model_id
             AND dense.projection_version = p_projection_version
             AND dense.source_outbox_sequence = eligible.source_outbox_sequence
          ), selected AS (
            SELECT projected.*,
                   1 - (projected.embedding <=> p_embedding::vector(128)) AS score,
                   projected.embedding <=> p_embedding::vector(128) AS distance
            FROM projected
            ORDER BY distance, projected.observed_at DESC,
                     projected.source_ref, projected.evidence_id
            LIMIT p_limit
          )
          SELECT (SELECT count(*) FROM eligible),
                 (SELECT count(*) FROM projected),
                 COALESCE(jsonb_agg(
                   jsonb_build_object(
                     'kind', 'EVIDENCE_OBSERVATION',
                     'evidence_id', selected.evidence_id,
                     'evidence_ids', jsonb_build_array(selected.evidence_id),
                     'source_ref', selected.source_ref,
                     'subject_id', selected.subject_id,
                     'speaker', selected.source_speaker,
                     'speaker_source', selected.speaker_source,
                     'observed_at', selected.observed_at,
                     'captured_at', selected.captured_at,
                     'content', selected.lexical_text,
                     'content_hash', selected.content_hash,
                     'permission_snapshot', selected.permission_snapshot,
                     'retention_state', selected.retention_state,
                     'projection_version', selected.projection_version,
                     'dense_projection_version', p_projection_version,
                     'source_outbox_sequence', selected.source_outbox_sequence,
                     'relevance_score', selected.score,
                     'acquisition_channel', 'EVIDENCE_DENSE',
                     'matched_fields', jsonb_build_array('evidence_dense_embedding'),
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) ORDER BY selected.distance, selected.observed_at DESC,
                              selected.source_ref, selected.evidence_id
                 ), '[]'::jsonb)
          INTO v_source_count, v_projected_count, v_items
          FROM selected;

          RETURN jsonb_build_object(
            'status', CASE WHEN v_projected_count = v_source_count
                           THEN 'COMPLETE' ELSE 'PARTIAL' END,
            'items', v_items,
            'source_count', v_source_count,
            'projected_count', v_projected_count,
            'projection_ready', v_projected_count = v_source_count,
            'source_partition_closed', true,
            'scan_axis', 'SOURCE_OBSERVED_TIME',
            'model_id', p_model_id,
            'projection_version', p_projection_version
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.read_evidence_dense_backfill_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_after_evidence_id uuid,
          p_limit integer,
          p_model_id text,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_items jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_limit < 1 OR p_limit > 128
             OR length(btrim(p_model_id)) = 0
             OR length(btrim(p_projection_version)) = 0 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_DENSE_BACKFILL';
          END IF;
          SELECT COALESCE(jsonb_agg(
                   jsonb_build_object(
                     'evidence_id', candidate.evidence_id,
                     'content', candidate.lexical_text
                   ) ORDER BY candidate.evidence_id
                 ), '[]'::jsonb)
          INTO v_items
          FROM (
            SELECT document.evidence_id, document.lexical_text
            FROM milai.evidence_search_document document
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
            LEFT JOIN milai.evidence_dense_embedding_128 dense
              ON dense.tenant_id = document.tenant_id
             AND dense.evidence_id = document.evidence_id
             AND dense.model_id = p_model_id
             AND dense.projection_version = p_projection_version
             AND dense.source_outbox_sequence = document.source_outbox_sequence
            WHERE document.tenant_id = p_tenant_id
              AND (p_after_evidence_id IS NULL
                   OR document.evidence_id > p_after_evidence_id)
              AND evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
              AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND dense.evidence_id IS NULL
            ORDER BY document.evidence_id
            LIMIT p_limit
          ) candidate;
          RETURN jsonb_build_object('status', 'COMPLETE', 'items', v_items);
        END
        $$
        """
    )

    for signature, name, role in (
        (UPSERT_SIGNATURE, "upsert_evidence_dense_128", "milai_worker"),
        (SEARCH_SIGNATURE, "search_evidence_dense_128", "milai_api"),
        (BACKFILL_SIGNATURE, "read_evidence_dense_backfill_batch", "milai_worker"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO {role}")


def downgrade() -> None:
    for signature, name in (
        (BACKFILL_SIGNATURE, "read_evidence_dense_backfill_batch"),
        (SEARCH_SIGNATURE, "search_evidence_dense_128"),
        (UPSERT_SIGNATURE, "upsert_evidence_dense_128"),
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.execute("DROP TABLE milai.evidence_dense_embedding_128")
