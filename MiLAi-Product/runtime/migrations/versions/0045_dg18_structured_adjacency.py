"""Add structured source adjacency and governed local hydration for DG-18 R1.

Revision ID: 0045_dg18_adjacency
Revises: 0044_dg17_evidence_dense

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_dg18_adjacency"
down_revision = "0044_dg17_evidence_dense"
branch_labels = None
depends_on = None

INGEST_SIGNATURE = (
    "uuid, uuid, text, text, text, text, text, text, jsonb, timestamptz, "
    "text, text, bigint, text, jsonb, text"
)
SPEAKER_INGEST_SIGNATURE = (
    "uuid, uuid, text, text, text, text, text, text, timestamptz, "
    "text, text, bigint, text, jsonb, text"
)
SEARCH_SIGNATURE = "uuid, uuid, text, jsonb, timestamptz, integer, text"
HYDRATE_SIGNATURE = "uuid, uuid, uuid[], jsonb, timestamptz, integer, text"

_CONTEXT_COLUMNS = (
    ("source_session_id", sa.Text()),
    ("source_turn_id", sa.Text()),
    ("source_turn_ordinal", sa.Integer()),
    ("source_round_id", sa.Text()),
    ("source_round_ordinal", sa.Integer()),
    ("previous_source_turn_id", sa.Text()),
    ("next_source_turn_id", sa.Text()),
)


def upgrade() -> None:
    for table in ("evidence_record", "evidence_search_document"):
        for name, column_type in _CONTEXT_COLUMNS:
            op.add_column(
                table,
                sa.Column(name, column_type, nullable=True),
                schema="milai",
            )
        op.add_column(
            table,
            sa.Column(
                "source_context_source",
                sa.Text(),
                nullable=False,
                server_default="UNKNOWN",
            ),
            schema="milai",
        )
        op.create_check_constraint(
            f"ck_{table}_source_context_lineage",
            table,
            _context_check(),
            schema="milai",
        )

    op.create_index(
        "ix_evidence_search_structured_round",
        "evidence_search_document",
        [
            "tenant_id",
            "source_session_id",
            "source_round_ordinal",
            "source_turn_ordinal",
            "evidence_id",
        ],
        schema="milai",
        postgresql_where=sa.text("source_context_source <> 'UNKNOWN'"),
    )
    _create_ingest_context_boundary()
    _replace_evidence_identity_guard(include_context=True)
    _create_projection_context_boundary()
    op.execute(
        """
        UPDATE milai.evidence_search_document document
        SET source_session_id = evidence.source_session_id,
            source_turn_id = evidence.source_turn_id,
            source_turn_ordinal = evidence.source_turn_ordinal,
            source_round_id = evidence.source_round_id,
            source_round_ordinal = evidence.source_round_ordinal,
            previous_source_turn_id = evidence.previous_source_turn_id,
            next_source_turn_id = evidence.next_source_turn_id,
            source_context_source = evidence.source_context_source
        FROM milai.evidence_record evidence
        WHERE evidence.tenant_id = document.tenant_id
          AND evidence.evidence_id = document.evidence_id
        """
    )
    _replace_search_function(include_context=True)
    _create_hydration_function()


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.hydrate_evidence_adjacency({HYDRATE_SIGNATURE})")
    _replace_search_function(include_context=False)
    op.execute(
        "DROP TRIGGER trg_evidence_projection_structured_context "
        "ON milai.evidence_search_document"
    )
    op.execute("DROP FUNCTION milai.propagate_structured_evidence_context()")
    op.execute(
        "DROP TRIGGER trg_evidence_ingest_structured_context ON milai.evidence_record"
    )
    op.execute("DROP FUNCTION milai.populate_structured_evidence_context()")
    op.execute(
        f"DROP FUNCTION milai.tx01_ingest_evidence_with_context({INGEST_SIGNATURE})"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.tx01_ingest_evidence_with_speaker("
        f"{SPEAKER_INGEST_SIGNATURE}) TO milai_api"
    )
    _replace_evidence_identity_guard(include_context=False)
    op.drop_index(
        "ix_evidence_search_structured_round",
        table_name="evidence_search_document",
        schema="milai",
    )
    for table in ("evidence_search_document", "evidence_record"):
        op.drop_constraint(
            f"ck_{table}_source_context_lineage",
            table,
            schema="milai",
            type_="check",
        )
        op.drop_column(table, "source_context_source", schema="milai")
        for name, _column_type in reversed(_CONTEXT_COLUMNS):
            op.drop_column(table, name, schema="milai")


def _context_check() -> str:
    required = (
        "source_session_id IS NOT NULL AND length(btrim(source_session_id)) > 0 AND "
        "source_turn_id IS NOT NULL AND length(btrim(source_turn_id)) > 0 AND "
        "source_turn_ordinal IS NOT NULL AND source_turn_ordinal >= 0 AND "
        "source_round_id IS NOT NULL AND length(btrim(source_round_id)) > 0 AND "
        "source_round_ordinal IS NOT NULL AND source_round_ordinal >= 0"
    )
    optional = (
        "(previous_source_turn_id IS NULL OR "
        "(length(btrim(previous_source_turn_id)) > 0 AND "
        "previous_source_turn_id <> source_turn_id)) AND "
        "(next_source_turn_id IS NULL OR "
        "(length(btrim(next_source_turn_id)) > 0 AND "
        "next_source_turn_id <> source_turn_id)) AND "
        "(previous_source_turn_id IS NULL OR next_source_turn_id IS NULL OR "
        "previous_source_turn_id <> next_source_turn_id)"
    )
    empty = " AND ".join(f"{name} IS NULL" for name, _ in _CONTEXT_COLUMNS)
    return (
        f"(source_context_source = 'UNKNOWN' AND {empty}) OR "
        "(source_context_source IN "
        "('STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL') AND "
        f"{required} AND {optional})"
    )


def _create_ingest_context_boundary() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.populate_structured_evidence_context()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_raw text;
          v_context jsonb;
        BEGIN
          v_raw := NULLIF(current_setting('milai.tx01_source_context', true), '');
          IF v_raw IS NULL THEN
            NEW.source_context_source := 'UNKNOWN';
            RETURN NEW;
          END IF;
          v_context := v_raw::jsonb;
          IF jsonb_typeof(v_context) <> 'object'
             OR jsonb_typeof(v_context -> 'session_id') <> 'string'
             OR jsonb_typeof(v_context -> 'turn_id') <> 'string'
             OR jsonb_typeof(v_context -> 'turn_ordinal') <> 'number'
             OR jsonb_typeof(v_context -> 'round_id') <> 'string'
             OR jsonb_typeof(v_context -> 'round_ordinal') <> 'number' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_SOURCE_CONTEXT';
          END IF;
          NEW.source_session_id := v_context ->> 'session_id';
          NEW.source_turn_id := v_context ->> 'turn_id';
          NEW.source_turn_ordinal := (v_context ->> 'turn_ordinal')::integer;
          NEW.source_round_id := v_context ->> 'round_id';
          NEW.source_round_ordinal := (v_context ->> 'round_ordinal')::integer;
          NEW.previous_source_turn_id := NULLIF(v_context ->> 'previous_turn_id', '');
          NEW.next_source_turn_id := NULLIF(v_context ->> 'next_turn_id', '');
          NEW.source_context_source := 'STRUCTURED_TURN_METADATA';
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_ingest_structured_context
        BEFORE INSERT ON milai.evidence_record
        FOR EACH ROW EXECUTE FUNCTION milai.populate_structured_evidence_context()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.tx01_ingest_evidence_with_context(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_idempotency_key text,
          p_request_fingerprint text,
          p_source_type text,
          p_source_ref text,
          p_subject_id text,
          p_source_speaker text,
          p_source_context jsonb,
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
          IF p_source_context IS NOT NULL
             AND jsonb_typeof(p_source_context) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_SOURCE_CONTEXT';
          END IF;
          PERFORM set_config(
            'milai.tx01_source_context', COALESCE(p_source_context::text, ''), true
          );
          v_result := milai.tx01_ingest_evidence_with_speaker(
            p_tenant_id, p_actor_id, p_idempotency_key, p_request_fingerprint,
            p_source_type, p_source_ref, p_subject_id, p_source_speaker,
            p_observed_at, p_content_hash, p_storage_uri, p_byte_length,
            p_media_type, p_permission_snapshot, p_retention_state
          );
          PERFORM set_config('milai.tx01_source_context', '', true);
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.tx01_ingest_evidence_with_context("
        f"{INGEST_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.tx01_ingest_evidence_with_context("
        f"{INGEST_SIGNATURE}) TO milai_api"
    )
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION milai.tx01_ingest_evidence_with_speaker("
        f"{SPEAKER_INGEST_SIGNATURE}) FROM milai_api"
    )


def _create_projection_context_boundary() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.propagate_structured_evidence_context()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          SELECT evidence.source_session_id,
                 evidence.source_turn_id,
                 evidence.source_turn_ordinal,
                 evidence.source_round_id,
                 evidence.source_round_ordinal,
                 evidence.previous_source_turn_id,
                 evidence.next_source_turn_id,
                 evidence.source_context_source
          INTO NEW.source_session_id,
               NEW.source_turn_id,
               NEW.source_turn_ordinal,
               NEW.source_round_id,
               NEW.source_round_ordinal,
               NEW.previous_source_turn_id,
               NEW.next_source_turn_id,
               NEW.source_context_source
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
        CREATE TRIGGER trg_evidence_projection_structured_context
        BEFORE INSERT OR UPDATE ON milai.evidence_search_document
        FOR EACH ROW EXECUTE FUNCTION milai.propagate_structured_evidence_context()
        """
    )


def _replace_evidence_identity_guard(*, include_context: bool) -> None:
    context_fields = ""
    old_context_fields = ""
    if include_context:
        context_fields = """
            NEW.source_session_id, NEW.source_turn_id, NEW.source_turn_ordinal,
            NEW.source_round_id, NEW.source_round_ordinal,
            NEW.previous_source_turn_id, NEW.next_source_turn_id,
            NEW.source_context_source,
        """
        old_context_fields = """
            OLD.source_session_id, OLD.source_turn_id, OLD.source_turn_ordinal,
            OLD.source_round_id, OLD.source_round_ordinal,
            OLD.previous_source_turn_id, OLD.next_source_turn_id,
            OLD.source_context_source,
        """
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
            NEW.subject_id, NEW.source_speaker, NEW.speaker_source,
            {context_fields}
            NEW.observed_at, NEW.captured_at, NEW.blob_id,
            NEW.content_hash, NEW.permission_snapshot,
            NEW.ingest_idempotency_key, NEW.request_fingerprint,
            NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.evidence_id, OLD.source_type, OLD.source_ref,
            OLD.subject_id, OLD.source_speaker, OLD.speaker_source,
            {old_context_fields}
            OLD.observed_at, OLD.captured_at, OLD.blob_id,
            OLD.content_hash, OLD.permission_snapshot,
            OLD.ingest_idempotency_key, OLD.request_fingerprint,
            OLD.created_at, OLD.created_by_actor_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'IMMUTABLE_EVIDENCE_IDENTITY';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )


def _source_context_json(alias: str) -> str:
    return f"""
      CASE WHEN {alias}.source_context_source = 'UNKNOWN' THEN NULL
           ELSE jsonb_build_object(
             'session_id', {alias}.source_session_id,
             'turn_id', {alias}.source_turn_id,
             'turn_ordinal', {alias}.source_turn_ordinal,
             'round_id', {alias}.source_round_id,
             'round_ordinal', {alias}.source_round_ordinal,
             'previous_turn_id', {alias}.previous_source_turn_id,
             'next_turn_id', {alias}.next_source_turn_id
           ) END
    """


def _replace_search_function(*, include_context: bool) -> None:
    context_fields = ""
    if include_context:
        context_fields = f"""
                     'source_context', {_source_context_json('ranked_turns')},
                     'source_context_source', ranked_turns.source_context_source,
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
                                live.search_vector, to_tsquery('simple', p_tsquery)
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
                     'speaker', COALESCE(ranked_turns.source_speaker, 'unknown'),
                     'speaker_source', ranked_turns.speaker_source,
                     __CONTEXT_FIELDS__
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
        """.replace("__CONTEXT_FIELDS__", context_fields)
    op.execute(statement)
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.search_evidence_projection({SEARCH_SIGNATURE}) "
        "TO milai_api"
    )


def _create_hydration_function() -> None:
    statement = """
        CREATE FUNCTION milai.hydrate_evidence_adjacency(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_anchor_evidence_ids uuid[],
          p_requested_scope jsonb,
          p_as_of timestamptz,
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
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF cardinality(p_anchor_evidence_ids) < 1
             OR cardinality(p_anchor_evidence_ids) > 24
             OR p_max_items < 1 OR p_max_items > 120
             OR p_projection_version <> 'evidence-search-v1'
             OR jsonb_typeof(p_requested_scope) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_EVIDENCE_ADJACENCY_QUERY';
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
          ), anchors AS MATERIALIZED (
            SELECT live.*,
                   array_position(p_anchor_evidence_ids, live.evidence_id) AS anchor_order
            FROM live
            WHERE live.evidence_id = ANY(p_anchor_evidence_ids)
              AND live.source_context_source IN (
                'STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'
              )
          ), expanded AS MATERIALIZED (
            SELECT anchor.evidence_id AS anchor_evidence_id,
                   anchor.anchor_order,
                   candidate.*,
                   CASE
                     WHEN candidate.source_round_id = anchor.source_round_id
                      AND candidate.source_round_ordinal = anchor.source_round_ordinal
                     THEN 'SAME_ROUND'
                     ELSE 'ADJACENT_ROUND'
                   END AS expansion_trigger,
                   abs(candidate.source_round_ordinal - anchor.source_round_ordinal)
                     AS round_distance
            FROM anchors anchor
            JOIN live candidate
              ON candidate.source_session_id = anchor.source_session_id
             AND candidate.evidence_id <> anchor.evidence_id
             AND candidate.source_context_source IN (
               'STRUCTURED_TURN_METADATA', 'AUTHORITATIVE_BACKFILL'
             )
             AND (
               (
                 candidate.source_round_id = anchor.source_round_id
                 AND candidate.source_round_ordinal = anchor.source_round_ordinal
               )
               OR abs(candidate.source_round_ordinal - anchor.source_round_ordinal) = 1
             )
          ), deduplicated AS (
            SELECT expanded.*,
                   row_number() OVER (
                     PARTITION BY expanded.evidence_id
                     ORDER BY expanded.round_distance,
                              expanded.anchor_order,
                              expanded.source_turn_ordinal,
                              expanded.source_ref,
                              expanded.anchor_evidence_id
                   ) AS dedup_rank
            FROM expanded
          ), limited AS (
            SELECT *
            FROM deduplicated
            WHERE dedup_rank = 1
            ORDER BY round_distance,
                     anchor_order,
                     source_round_ordinal,
                     source_turn_ordinal,
                     source_ref,
                     evidence_id
            LIMIT p_max_items
          ), rendered AS (
            SELECT limited.round_distance,
                   limited.anchor_order,
                   limited.source_round_ordinal,
                   limited.source_turn_ordinal,
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
                     'source_context', __SOURCE_CONTEXT_JSON__,
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
                     'acquisition_channel', 'STRUCTURED_ADJACENCY',
                     'matched_fields', jsonb_build_array('source_context'),
                     'anchor_match', false,
                     'context_expansion', jsonb_build_object(
                       'trigger', limited.expansion_trigger,
                       'source_evidence_id', limited.anchor_evidence_id,
                       'round_distance', limited.round_distance
                     ),
                     'authority', 'EVIDENCE_ONLY',
                     'canonical', false
                   ) AS item
            FROM limited
          )
          SELECT COALESCE(
                   jsonb_agg(
                     rendered.item
                     ORDER BY rendered.round_distance,
                              rendered.anchor_order,
                              rendered.source_round_ordinal,
                              rendered.source_turn_ordinal,
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
        """.replace("__SOURCE_CONTEXT_JSON__", _source_context_json("limited"))
    op.execute(statement)
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.hydrate_evidence_adjacency("
        f"{HYDRATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.hydrate_evidence_adjacency("
        f"{HYDRATE_SIGNATURE}) TO milai_api"
    )
