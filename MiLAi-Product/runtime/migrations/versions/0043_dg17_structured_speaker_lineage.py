"""Add immutable structured Evidence speaker lineage for DG-17 A3.

Revision ID: 0043_dg17_speaker
Revises: 0042_dg17_turn_first

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_dg17_speaker"
down_revision = "0042_dg17_turn_first"
branch_labels = None
depends_on = None

INGEST_WITH_SPEAKER_SIGNATURE = (
    "uuid, uuid, text, text, text, text, text, text, timestamptz, "
    "text, text, bigint, text, jsonb, text"
)
SEARCH_SIGNATURE = "uuid, uuid, text, jsonb, timestamptz, integer, text"


def upgrade() -> None:
    op.add_column(
        "evidence_record",
        sa.Column("source_speaker", sa.Text(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "evidence_record",
        sa.Column(
            "speaker_source",
            sa.Text(),
            nullable=False,
            server_default="UNKNOWN",
        ),
        schema="milai",
    )
    op.create_check_constraint(
        "ck_evidence_speaker_lineage",
        "evidence_record",
        "(source_speaker IS NULL AND speaker_source = 'UNKNOWN') OR "
        "(source_speaker IN ('user', 'assistant', 'system', 'tool') AND "
        "speaker_source IN ('STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'))",
        schema="milai",
    )
    op.add_column(
        "evidence_search_document",
        sa.Column("source_speaker", sa.Text(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "evidence_search_document",
        sa.Column(
            "speaker_source",
            sa.Text(),
            nullable=False,
            server_default="UNKNOWN",
        ),
        schema="milai",
    )
    op.create_check_constraint(
        "ck_evidence_search_speaker_lineage",
        "evidence_search_document",
        "(source_speaker IS NULL AND speaker_source = 'UNKNOWN') OR "
        "(source_speaker IN ('user', 'assistant', 'system', 'tool') AND "
        "speaker_source IN ('STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'))",
        schema="milai",
    )
    _create_ingest_speaker_boundary()
    _replace_evidence_identity_guard(include_speaker=True)
    _create_projection_speaker_boundary()
    op.execute(
        """
        UPDATE milai.evidence_search_document document
        SET source_speaker = evidence.source_speaker,
            speaker_source = evidence.speaker_source
        FROM milai.evidence_record evidence
        WHERE evidence.tenant_id = document.tenant_id
          AND evidence.evidence_id = document.evidence_id
        """
    )
    _replace_search_function(include_speaker=True)


def downgrade() -> None:
    _replace_search_function(include_speaker=False)
    op.execute(
        f"DROP FUNCTION milai.tx01_ingest_evidence_with_speaker("
        f"{INGEST_WITH_SPEAKER_SIGNATURE})"
    )
    op.execute(
        "DROP TRIGGER trg_evidence_projection_structured_speaker "
        "ON milai.evidence_search_document"
    )
    op.execute("DROP FUNCTION milai.propagate_structured_evidence_speaker()")
    op.execute("DROP TRIGGER trg_evidence_ingest_structured_speaker ON milai.evidence_record")
    op.execute("DROP FUNCTION milai.populate_structured_evidence_speaker()")
    _replace_evidence_identity_guard(include_speaker=False)
    op.drop_constraint(
        "ck_evidence_search_speaker_lineage",
        "evidence_search_document",
        schema="milai",
        type_="check",
    )
    op.drop_column("evidence_search_document", "speaker_source", schema="milai")
    op.drop_column("evidence_search_document", "source_speaker", schema="milai")
    op.drop_constraint(
        "ck_evidence_speaker_lineage",
        "evidence_record",
        schema="milai",
        type_="check",
    )
    op.drop_column("evidence_record", "speaker_source", schema="milai")
    op.drop_column("evidence_record", "source_speaker", schema="milai")


def _create_ingest_speaker_boundary() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.populate_structured_evidence_speaker()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_speaker text;
        BEGIN
          v_speaker := NULLIF(
            current_setting('milai.tx01_source_speaker', true), ''
          );
          IF v_speaker IS NOT NULL
             AND v_speaker NOT IN ('user', 'assistant', 'system', 'tool') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EVIDENCE_SPEAKER';
          END IF;
          NEW.source_speaker := v_speaker;
          NEW.speaker_source := CASE
            WHEN v_speaker IS NULL THEN 'UNKNOWN'
            ELSE 'STRUCTURED_TURN_METADATA'
          END;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_ingest_structured_speaker
        BEFORE INSERT ON milai.evidence_record
        FOR EACH ROW EXECUTE FUNCTION milai.populate_structured_evidence_speaker()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.tx01_ingest_evidence_with_speaker(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_idempotency_key text,
          p_request_fingerprint text,
          p_source_type text,
          p_source_ref text,
          p_subject_id text,
          p_source_speaker text,
          p_observed_at timestamptz,
          p_content_hash text,
          p_storage_uri text,
          p_byte_length bigint,
          p_media_type text,
          p_permission_snapshot jsonb,
          p_retention_state text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_result jsonb;
        BEGIN
          IF p_source_speaker IS NOT NULL
             AND p_source_speaker NOT IN ('user', 'assistant', 'system', 'tool') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EVIDENCE_SPEAKER';
          END IF;
          PERFORM set_config(
            'milai.tx01_source_speaker', COALESCE(p_source_speaker, ''), true
          );
          v_result := milai.tx01_ingest_evidence(
            p_tenant_id, p_actor_id, p_idempotency_key, p_request_fingerprint,
            p_source_type, p_source_ref, p_subject_id, p_observed_at,
            p_content_hash, p_storage_uri, p_byte_length, p_media_type,
            p_permission_snapshot, p_retention_state
          );
          PERFORM set_config('milai.tx01_source_speaker', '', true);
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.tx01_ingest_evidence_with_speaker("
        f"{INGEST_WITH_SPEAKER_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.tx01_ingest_evidence_with_speaker("
        f"{INGEST_WITH_SPEAKER_SIGNATURE}) TO milai_api"
    )


def _create_projection_speaker_boundary() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.propagate_structured_evidence_speaker()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          SELECT evidence.source_speaker, evidence.speaker_source
          INTO NEW.source_speaker, NEW.speaker_source
          FROM milai.evidence_record evidence
          WHERE evidence.tenant_id = NEW.tenant_id
            AND evidence.evidence_id = NEW.evidence_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EVIDENCE_NOT_FOUND';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_projection_structured_speaker
        BEFORE INSERT OR UPDATE ON milai.evidence_search_document
        FOR EACH ROW EXECUTE FUNCTION milai.propagate_structured_evidence_speaker()
        """
    )


def _replace_evidence_identity_guard(*, include_speaker: bool) -> None:
    fields = (
        "NEW.subject_id, NEW.source_speaker, NEW.speaker_source, NEW.observed_at"
        if include_speaker
        else "NEW.subject_id, NEW.observed_at"
    )
    old_fields = (
        "OLD.subject_id, OLD.source_speaker, OLD.speaker_source, OLD.observed_at"
        if include_speaker
        else "OLD.subject_id, OLD.observed_at"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION milai.protect_evidence_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF ROW(
            NEW.tenant_id, NEW.evidence_id, NEW.source_type, NEW.source_ref,
            {fields}, NEW.captured_at, NEW.blob_id,
            NEW.content_hash, NEW.permission_snapshot,
            NEW.ingest_idempotency_key, NEW.request_fingerprint,
            NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.evidence_id, OLD.source_type, OLD.source_ref,
            {old_fields}, OLD.captured_at, OLD.blob_id,
            OLD.content_hash, OLD.permission_snapshot,
            OLD.ingest_idempotency_key, OLD.request_fingerprint,
            OLD.created_at, OLD.created_by_actor_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_EVIDENCE_IDENTITY';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )


def _replace_search_function(*, include_speaker: bool) -> None:
    speaker_fields = ""
    if include_speaker:
        speaker_fields = """
                     'speaker', COALESCE(ranked_turns.source_speaker, 'unknown'),
                     'speaker_source', ranked_turns.speaker_source,
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
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_QUERY';
          END IF;

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
                     __SPEAKER_FIELDS__
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
          RETURN v_result;
        END
        $$
    """
    op.execute(statement.replace("__SPEAKER_FIELDS__", speaker_fields))
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "TO milai_api"
    )
