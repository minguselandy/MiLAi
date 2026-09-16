"""Add routed Evidence projection, micro-batches, and exact readiness status.

Revision ID: 0033_dg15_projection
Revises: 0032_reviewer_actor_separation

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
Raw Evidence remains non-canonical. The new table is a revocable, permission-
gated search projection and cannot move ClaimHead or create ClaimVersion rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_dg15_projection"
down_revision: str | None = "0032_reviewer_actor_separation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEASE_BATCH_SIGNATURE = "uuid, uuid, text, text, integer, integer, integer"
COMPLETE_ROUTED_SIGNATURE = "uuid, uuid, text, uuid, text, text, text, text, text"
APPLY_EVIDENCE_BATCH_SIGNATURE = "uuid, uuid, text, jsonb, text, text"
SEARCH_EVIDENCE_SIGNATURE = "uuid, uuid, text, jsonb, timestamptz, integer, text"
READINESS_SIGNATURE = "uuid, uuid, uuid, text[], jsonb"


def upgrade() -> None:
    op.drop_constraint(
        "ck_projection_delivery_name", "projection_delivery", schema="milai", type_="check"
    )
    op.create_check_constraint(
        "ck_projection_delivery_name",
        "projection_delivery",
        "projection_name IN ('evidence', 'fts', 'vector', 'purge')",
        schema="milai",
    )
    op.drop_constraint(
        "ck_index_watermark_name", "index_watermark", schema="milai", type_="check"
    )
    op.create_check_constraint(
        "ck_index_watermark_name",
        "index_watermark",
        "projection_name IN ('evidence', 'fts', 'vector', 'purge')",
        schema="milai",
    )
    op.add_column(
        "projection_delivery",
        sa.Column("routing_version", sa.Text(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "projection_delivery",
        sa.Column("applicability", sa.Text(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "projection_delivery",
        sa.Column("handler_outcome", sa.Text(), nullable=True),
        schema="milai",
    )
    op.create_check_constraint(
        "ck_projection_delivery_applicability",
        "projection_delivery",
        "applicability IS NULL OR applicability IN ('APPLY', 'ACK_NOT_APPLICABLE')",
        schema="milai",
    )

    op.create_table(
        "evidence_search_document",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lexical_text", sa.Text(), nullable=False),
        sa.Column("semantic_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("permission_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retention_state", sa.Text(), nullable=False),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("source_outbox_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "evidence_id", name="pk_evidence_search_document"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_evidence_search_evidence",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(lexical_text) > 0", name="ck_evidence_search_text"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_evidence_search_content_hash"
        ),
        sa.CheckConstraint(
            "source_outbox_sequence > 0", name="ck_evidence_search_outbox_sequence"
        ),
        schema="milai",
    )
    op.execute(
        "ALTER TABLE milai.evidence_search_document "
        "ADD COLUMN search_vector tsvector GENERATED ALWAYS AS "
        "(to_tsvector('simple', lexical_text)) STORED"
    )
    op.create_index(
        "ix_evidence_search_vector",
        "evidence_search_document",
        ["search_vector"],
        unique=False,
        schema="milai",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_evidence_search_temporal",
        "evidence_search_document",
        ["tenant_id", sa.text("observed_at DESC"), "evidence_id"],
        schema="milai",
    )
    op.execute("ALTER TABLE milai.evidence_search_document ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.evidence_search_document FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY evidence_search_tenant_isolation
        ON milai.evidence_search_document
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.lease_projection_event_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_worker_id text,
          p_lease_seconds integer,
          p_max_attempts integer,
          p_batch_size integer
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_first_sequence bigint;
          v_ids uuid[];
          v_result jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('evidence', 'fts', 'vector', 'purge')
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR p_lease_seconds < 1 OR p_lease_seconds > 300
             OR p_max_attempts < 1 OR p_max_attempts > 100
             OR p_batch_size < 1 OR p_batch_size > 128 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;

          INSERT INTO milai.index_watermark (
            tenant_id, projection_name, last_contiguous_outbox_sequence,
            updated_by_actor_id
          ) VALUES (p_tenant_id, p_projection_name, 0, p_actor_id)
          ON CONFLICT DO NOTHING;

          UPDATE milai.projection_delivery
          SET state = CASE WHEN attempt_count >= p_max_attempts
                           THEN 'DEAD_LETTER' ELSE 'PENDING' END,
              lease_owner = NULL, lease_expires_at = NULL,
              last_error_code = COALESCE(last_error_code, 'LEASE_EXPIRED')
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND state = 'PROCESSING' AND lease_expires_at <= CURRENT_TIMESTAMP;

          INSERT INTO milai.projection_delivery (
            tenant_id, projection_name, outbox_id, outbox_sequence,
            state, attempt_count, available_at, created_by_actor_id
          ) SELECT
            event.tenant_id, p_projection_name, event.outbox_id,
            event.outbox_sequence, 'PENDING', 0, CURRENT_TIMESTAMP, p_actor_id
          FROM milai.outbox_event event
          WHERE event.tenant_id = p_tenant_id
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery delivery
              WHERE delivery.tenant_id = event.tenant_id
                AND delivery.projection_name = p_projection_name
                AND delivery.outbox_id = event.outbox_id
            )
          ORDER BY event.outbox_sequence
          ON CONFLICT DO NOTHING;

          SELECT min(outbox_sequence) INTO v_first_sequence
          FROM milai.projection_delivery
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND state <> 'DELIVERED';
          IF v_first_sequence IS NULL THEN
            RETURN '[]'::jsonb;
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM milai.projection_delivery
            WHERE tenant_id = p_tenant_id
              AND projection_name = p_projection_name
              AND outbox_sequence = v_first_sequence
              AND state = 'PENDING' AND available_at <= CURRENT_TIMESTAMP
          ) THEN
            RETURN '[]'::jsonb;
          END IF;

          SELECT array_agg(candidate.outbox_id ORDER BY candidate.outbox_sequence)
          INTO v_ids
          FROM (
            SELECT delivery.outbox_id, delivery.outbox_sequence
            FROM milai.projection_delivery delivery
            WHERE delivery.tenant_id = p_tenant_id
              AND delivery.projection_name = p_projection_name
              AND delivery.outbox_sequence >= v_first_sequence
              AND delivery.state = 'PENDING'
              AND delivery.available_at <= CURRENT_TIMESTAMP
              AND NOT EXISTS (
                SELECT 1 FROM milai.projection_delivery blocker
                WHERE blocker.tenant_id = delivery.tenant_id
                  AND blocker.projection_name = delivery.projection_name
                  AND blocker.outbox_sequence >= v_first_sequence
                  AND blocker.outbox_sequence < delivery.outbox_sequence
                  AND blocker.state <> 'PENDING'
              )
            ORDER BY delivery.outbox_sequence
            LIMIT p_batch_size
            FOR UPDATE SKIP LOCKED
          ) candidate;
          IF v_ids IS NULL OR cardinality(v_ids) = 0 THEN
            RETURN '[]'::jsonb;
          END IF;

          UPDATE milai.projection_delivery
          SET state = 'PROCESSING', attempt_count = attempt_count + 1,
              lease_owner = p_worker_id,
              lease_expires_at = CURRENT_TIMESTAMP + make_interval(secs => p_lease_seconds),
              last_error_code = NULL
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = ANY(v_ids);

          SELECT jsonb_agg(
            jsonb_build_object(
              'outbox_id', event.outbox_id,
              'outbox_sequence', event.outbox_sequence,
              'event_type', event.event_type,
              'aggregate_type', event.aggregate_type,
              'aggregate_id', event.aggregate_id,
              'payload', event.payload,
              'canonical_commit_seq', event.canonical_commit_seq,
              'attempt_count', delivery.attempt_count,
              'lease_expires_at', delivery.lease_expires_at,
              'created_at', event.created_at
            ) ORDER BY event.outbox_sequence
          ) INTO v_result
          FROM milai.outbox_event event
          JOIN milai.projection_delivery delivery
            ON delivery.tenant_id = event.tenant_id
           AND delivery.outbox_id = event.outbox_id
           AND delivery.projection_name = p_projection_name
          WHERE event.tenant_id = p_tenant_id AND event.outbox_id = ANY(v_ids);
          RETURN COALESCE(v_result, '[]'::jsonb);
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.complete_projection_event_routed(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid,
          p_worker_id text,
          p_handler_result_hash text,
          p_routing_version text,
          p_applicability text,
          p_handler_outcome text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_sequence bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('evidence', 'fts', 'vector', 'purge')
             OR p_handler_result_hash !~ '^[0-9a-f]{64}$'
             OR p_routing_version <> 'dg15-routing-v1'
             OR p_applicability NOT IN ('APPLY', 'ACK_NOT_APPLICABLE')
             OR length(btrim(p_handler_outcome)) = 0
             OR length(p_handler_outcome) > 128 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          UPDATE milai.projection_delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = p_handler_result_hash,
              routing_version = p_routing_version,
              applicability = p_applicability,
              handler_outcome = p_handler_outcome
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = p_outbox_id
            AND state = 'PROCESSING' AND lease_owner = p_worker_id
            AND lease_expires_at > CURRENT_TIMESTAMP
          RETURNING outbox_sequence INTO v_sequence;
          IF v_sequence IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          SELECT COALESCE(max(delivered.outbox_sequence), 0) INTO v_sequence
          FROM milai.projection_delivery delivered
          WHERE delivered.tenant_id = p_tenant_id
            AND delivered.projection_name = p_projection_name
            AND delivered.state = 'DELIVERED'
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery gap
              WHERE gap.tenant_id = delivered.tenant_id
                AND gap.projection_name = delivered.projection_name
                AND gap.outbox_sequence < delivered.outbox_sequence
                AND gap.state <> 'DELIVERED'
            );
          UPDATE milai.index_watermark
          SET last_contiguous_outbox_sequence = v_sequence,
              updated_at = CURRENT_TIMESTAMP, updated_by_actor_id = p_actor_id
          WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name;
          RETURN (
            SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
            WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.apply_evidence_projection_batch(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_worker_id text,
          p_items jsonb,
          p_routing_version text,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_count integer;
          v_leased integer;
          v_maximum bigint;
          v_outcomes jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF jsonb_typeof(p_items) <> 'array'
             OR jsonb_array_length(p_items) < 1
             OR jsonb_array_length(p_items) > 128
             OR p_routing_version <> 'dg15-routing-v1'
             OR p_projection_version <> 'evidence-search-v1' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          SELECT count(*), count(DISTINCT item.outbox_id)
          INTO v_count, v_leased
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text);
          IF v_count <> v_leased THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'DUPLICATE_BATCH_ITEM';
          END IF;
          SELECT count(*) INTO v_leased
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
          JOIN milai.projection_delivery delivery
            ON delivery.tenant_id = p_tenant_id
           AND delivery.projection_name = 'evidence'
           AND delivery.outbox_id = item.outbox_id
           AND delivery.state = 'PROCESSING'
           AND delivery.lease_owner = p_worker_id
           AND delivery.lease_expires_at > CURRENT_TIMESTAMP;
          IF v_count <> v_leased THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
            JOIN milai.outbox_event event
              ON event.tenant_id = p_tenant_id AND event.outbox_id = item.outbox_id
            WHERE event.event_type = 'EVIDENCE_INGESTED'
              AND (item.content IS NULL OR length(item.content) = 0)
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EVIDENCE_CONTENT_UNAVAILABLE';
          END IF;

          INSERT INTO milai.evidence_search_document (
            tenant_id, evidence_id, source_ref, subject_id,
            observed_at, captured_at, lexical_text, semantic_text,
            content_hash, permission_snapshot, retention_state,
            projection_version, source_outbox_sequence, created_by_actor_id
          )
          SELECT
            evidence.tenant_id, evidence.evidence_id, evidence.source_ref,
            evidence.subject_id, evidence.observed_at, evidence.captured_at,
            item.content, item.content, evidence.content_hash,
            evidence.permission_snapshot, evidence.retention_state,
            p_projection_version, event.outbox_sequence, p_actor_id
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
          JOIN milai.outbox_event event
            ON event.tenant_id = p_tenant_id AND event.outbox_id = item.outbox_id
          JOIN milai.evidence_record evidence
            ON evidence.tenant_id = event.tenant_id
           AND evidence.evidence_id = event.aggregate_id
          WHERE event.event_type = 'EVIDENCE_INGESTED'
          ON CONFLICT (tenant_id, evidence_id) DO UPDATE
          SET source_ref = EXCLUDED.source_ref,
              subject_id = EXCLUDED.subject_id,
              observed_at = EXCLUDED.observed_at,
              captured_at = EXCLUDED.captured_at,
              lexical_text = EXCLUDED.lexical_text,
              semantic_text = EXCLUDED.semantic_text,
              content_hash = EXCLUDED.content_hash,
              permission_snapshot = EXCLUDED.permission_snapshot,
              retention_state = EXCLUDED.retention_state,
              projection_version = EXCLUDED.projection_version,
              source_outbox_sequence = EXCLUDED.source_outbox_sequence,
              projected_at = CURRENT_TIMESTAMP,
              created_by_actor_id = EXCLUDED.created_by_actor_id;

          DELETE FROM milai.evidence_search_document document
          USING jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text),
                milai.outbox_event event
          WHERE event.tenant_id = p_tenant_id
            AND event.outbox_id = item.outbox_id
            AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
            AND document.tenant_id = event.tenant_id
            AND document.evidence_id = (event.payload ->> 'evidence_id')::uuid;

          UPDATE milai.projection_delivery delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = encode(sha256(convert_to(
                concat_ws(':', event.event_type, event.outbox_id::text,
                          p_projection_version), 'UTF8')), 'hex'),
              routing_version = p_routing_version,
              applicability = CASE
                WHEN event.event_type IN (
                  'EVIDENCE_INGESTED', 'PURGE_EVIDENCE_DERIVATIVES'
                ) THEN 'APPLY' ELSE 'ACK_NOT_APPLICABLE' END,
              handler_outcome = CASE
                WHEN event.event_type = 'EVIDENCE_INGESTED' THEN 'PROJECTED'
                WHEN event.event_type = 'PURGE_EVIDENCE_DERIVATIVES' THEN 'PURGED'
                ELSE 'EXPLICIT_SKIP' END
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
          JOIN milai.outbox_event event
            ON event.tenant_id = p_tenant_id AND event.outbox_id = item.outbox_id
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = 'evidence'
            AND delivery.outbox_id = item.outbox_id
            AND delivery.state = 'PROCESSING'
            AND delivery.lease_owner = p_worker_id
            AND delivery.lease_expires_at > CURRENT_TIMESTAMP;

          SELECT max(event.outbox_sequence) INTO v_maximum
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
          JOIN milai.outbox_event event
            ON event.tenant_id = p_tenant_id AND event.outbox_id = item.outbox_id;
          SELECT COALESCE(max(delivered.outbox_sequence), 0) INTO v_maximum
          FROM milai.projection_delivery delivered
          WHERE delivered.tenant_id = p_tenant_id
            AND delivered.projection_name = 'evidence'
            AND delivered.state = 'DELIVERED'
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery gap
              WHERE gap.tenant_id = delivered.tenant_id
                AND gap.projection_name = delivered.projection_name
                AND gap.outbox_sequence < delivered.outbox_sequence
                AND gap.state <> 'DELIVERED'
            );
          UPDATE milai.index_watermark
          SET last_contiguous_outbox_sequence = v_maximum,
              updated_at = CURRENT_TIMESTAMP, updated_by_actor_id = p_actor_id
          WHERE tenant_id = p_tenant_id AND projection_name = 'evidence';

          SELECT jsonb_agg(jsonb_build_object(
            'outbox_id', event.outbox_id,
            'outbox_sequence', event.outbox_sequence,
            'event_type', event.event_type,
            'applicability', delivery.applicability,
            'outcome', delivery.handler_outcome
          ) ORDER BY event.outbox_sequence) INTO v_outcomes
          FROM jsonb_to_recordset(p_items) AS item(outbox_id uuid, content text)
          JOIN milai.outbox_event event
            ON event.tenant_id = p_tenant_id AND event.outbox_id = item.outbox_id
          JOIN milai.projection_delivery delivery
            ON delivery.tenant_id = event.tenant_id
           AND delivery.projection_name = 'evidence'
           AND delivery.outbox_id = event.outbox_id;
          RETURN jsonb_build_object(
            'projection', 'evidence',
            'projection_version', p_projection_version,
            'routing_version', p_routing_version,
            'watermark', (
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'evidence'
            ),
            'outcomes', COALESCE(v_outcomes, '[]'::jsonb)
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.search_evidence_projection(
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
                                                        candidate.observed_at DESC,
                                                        candidate.evidence_id), '[]'::jsonb)
          INTO v_result
          FROM (
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
          ) candidate;
          RETURN v_result;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.projection_readiness_status(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_target_outbox_id uuid,
          p_required_projections text[],
          p_expected_versions jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_target bigint;
          v_details jsonb;
          v_ready boolean;
          v_versions_match boolean;
          v_gap bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF cardinality(p_required_projections) < 1
             OR cardinality(p_required_projections) > 4
             OR EXISTS (
               SELECT 1 FROM unnest(p_required_projections) projection
               WHERE projection NOT IN ('evidence', 'fts', 'vector', 'purge')
             )
             OR jsonb_typeof(p_expected_versions) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_READINESS_REQUEST';
          END IF;
          SELECT outbox_sequence INTO v_target
          FROM milai.outbox_event
          WHERE tenant_id = p_tenant_id AND outbox_id = p_target_outbox_id;
          IF v_target IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'OUTBOX_POSITION_NOT_FOUND';
          END IF;
          SELECT min(delivery.outbox_sequence) INTO v_gap
          FROM milai.projection_delivery delivery
          WHERE delivery.tenant_id = p_tenant_id
            AND delivery.projection_name = ANY(p_required_projections)
            AND delivery.outbox_sequence <= v_target
            AND delivery.state = 'DEAD_LETTER';
          SELECT jsonb_agg(jsonb_build_object(
            'projection', projection.name,
            'current_watermark', COALESCE(watermark.last_contiguous_outbox_sequence, 0),
            'target_watermark', v_target,
            'projection_version', CASE projection.name
              WHEN 'evidence' THEN 'evidence-search-v1'
              WHEN 'fts' THEN 'canonical-fts-v1'
              WHEN 'vector' THEN 'canonical-vector-v1'
              ELSE 'purge-v1' END,
            'version_match', p_expected_versions ->> projection.name = CASE projection.name
              WHEN 'evidence' THEN 'evidence-search-v1'
              WHEN 'fts' THEN 'canonical-fts-v1'
              WHEN 'vector' THEN 'canonical-vector-v1'
              ELSE 'purge-v1' END,
            'ready', COALESCE(watermark.last_contiguous_outbox_sequence, 0) >= v_target
          ) ORDER BY projection.name) INTO v_details
          FROM unnest(p_required_projections) projection(name)
          LEFT JOIN milai.index_watermark watermark
            ON watermark.tenant_id = p_tenant_id
           AND watermark.projection_name = projection.name;
          SELECT bool_and(
            COALESCE(watermark.last_contiguous_outbox_sequence, 0) >= v_target
            AND p_expected_versions ->> projection.name = CASE projection.name
              WHEN 'evidence' THEN 'evidence-search-v1'
              WHEN 'fts' THEN 'canonical-fts-v1'
              WHEN 'vector' THEN 'canonical-vector-v1'
              ELSE 'purge-v1' END
          ) INTO v_ready
          FROM unnest(p_required_projections) projection(name)
          LEFT JOIN milai.index_watermark watermark
            ON watermark.tenant_id = p_tenant_id
           AND watermark.projection_name = projection.name;
          SELECT bool_and(
            p_expected_versions ->> projection.name = CASE projection.name
              WHEN 'evidence' THEN 'evidence-search-v1'
              WHEN 'fts' THEN 'canonical-fts-v1'
              WHEN 'vector' THEN 'canonical-vector-v1'
              ELSE 'purge-v1' END
          ) INTO v_versions_match
          FROM unnest(p_required_projections) projection(name);
          RETURN jsonb_build_object(
            'status', CASE
              WHEN v_gap IS NOT NULL THEN 'DEAD_LETTER_GAP'
              WHEN NOT v_versions_match THEN 'VERSION_MISMATCH'
              WHEN v_ready THEN 'READY'
              ELSE 'WAITING' END,
            'target_outbox_id', p_target_outbox_id,
            'target_watermark', v_target,
            'routing_version', 'dg15-routing-v1',
            'earliest_dead_letter_gap', v_gap,
            'projections', COALESCE(v_details, '[]'::jsonb)
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION milai.retrieval_projection_state(
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
              SELECT max(event.outbox_sequence) FROM milai.outbox_event event
              WHERE event.tenant_id = p_tenant_id
            ), 0),
            'evidence_watermark', COALESCE((
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'evidence'
            ), 0),
            'fts_watermark', COALESCE((
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'fts'
            ), 0),
            'vector_watermark', COALESCE((
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'vector'
            ), 0),
            'evidence_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery
              WHERE tenant_id = p_tenant_id AND projection_name = 'evidence'
                AND state = 'DEAD_LETTER'
            ),
            'fts_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery
              WHERE tenant_id = p_tenant_id AND projection_name = 'fts'
                AND state = 'DEAD_LETTER'
            ),
            'vector_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery
              WHERE tenant_id = p_tenant_id AND projection_name = 'vector'
                AND state = 'DEAD_LETTER'
            )
          );
        END
        $$
        """
    )

    tables = "milai.evidence_search_document"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(f"GRANT SELECT ON TABLE {tables} TO milai_audit")
    for signature, name in (
        (LEASE_BATCH_SIGNATURE, "lease_projection_event_batch"),
        (COMPLETE_ROUTED_SIGNATURE, "complete_projection_event_routed"),
        (APPLY_EVIDENCE_BATCH_SIGNATURE, "apply_evidence_projection_batch"),
        (SEARCH_EVIDENCE_SIGNATURE, "search_evidence_projection"),
        (READINESS_SIGNATURE, "projection_readiness_status"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
    for name, signature in (
        ("lease_projection_event_batch", LEASE_BATCH_SIGNATURE),
        ("complete_projection_event_routed", COMPLETE_ROUTED_SIGNATURE),
        ("apply_evidence_projection_batch", APPLY_EVIDENCE_BATCH_SIGNATURE),
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_worker")
    for name, signature in (
        ("search_evidence_projection", SEARCH_EVIDENCE_SIGNATURE),
        ("projection_readiness_status", READINESS_SIGNATURE),
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_api")


def downgrade() -> None:
    for signature, name in (
        (READINESS_SIGNATURE, "projection_readiness_status"),
        (SEARCH_EVIDENCE_SIGNATURE, "search_evidence_projection"),
        (APPLY_EVIDENCE_BATCH_SIGNATURE, "apply_evidence_projection_batch"),
        (COMPLETE_ROUTED_SIGNATURE, "complete_projection_event_routed"),
        (LEASE_BATCH_SIGNATURE, "lease_projection_event_batch"),
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION milai.retrieval_projection_state(
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
              SELECT max(event.outbox_sequence) FROM milai.outbox_event event
              WHERE event.tenant_id = p_tenant_id
            ), 0),
            'fts_watermark', COALESCE((
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'fts'
            ), 0),
            'vector_watermark', COALESCE((
              SELECT last_contiguous_outbox_sequence FROM milai.index_watermark
              WHERE tenant_id = p_tenant_id AND projection_name = 'vector'
            ), 0),
            'fts_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery
              WHERE tenant_id = p_tenant_id AND projection_name = 'fts'
                AND state = 'DEAD_LETTER'
            ),
            'vector_dead_letter', EXISTS (
              SELECT 1 FROM milai.projection_delivery
              WHERE tenant_id = p_tenant_id AND projection_name = 'vector'
                AND state = 'DEAD_LETTER'
            )
          );
        END
        $$
        """
    )
    op.drop_index("ix_evidence_search_temporal", table_name="evidence_search_document", schema="milai")
    op.drop_index("ix_evidence_search_vector", table_name="evidence_search_document", schema="milai")
    op.drop_table("evidence_search_document", schema="milai")
    op.drop_constraint(
        "ck_projection_delivery_applicability",
        "projection_delivery",
        schema="milai",
        type_="check",
    )
    op.drop_column("projection_delivery", "handler_outcome", schema="milai")
    op.drop_column("projection_delivery", "applicability", schema="milai")
    op.drop_column("projection_delivery", "routing_version", schema="milai")
    op.drop_constraint(
        "ck_projection_delivery_name", "projection_delivery", schema="milai", type_="check"
    )
    op.create_check_constraint(
        "ck_projection_delivery_name",
        "projection_delivery",
        "projection_name IN ('fts', 'vector', 'purge')",
        schema="milai",
    )
    op.drop_constraint(
        "ck_index_watermark_name", "index_watermark", schema="milai", type_="check"
    )
    op.create_check_constraint(
        "ck_index_watermark_name",
        "index_watermark",
        "projection_name IN ('fts', 'vector', 'purge')",
        schema="milai",
    )
