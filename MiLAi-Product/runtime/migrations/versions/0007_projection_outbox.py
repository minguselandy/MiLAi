"""Add durable per-projection outbox delivery and derived stores.

Revision ID: 0007_projection_outbox
Revises: 0006_evidence_revocation

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_projection_outbox"
down_revision: str | None = "0006_evidence_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEASE_SIGNATURE = "uuid, uuid, text, text, integer, integer"
COMPLETE_SIGNATURE = "uuid, uuid, text, uuid, text, text"
FAIL_SIGNATURE = "uuid, uuid, text, uuid, text, text, integer, integer"
RETRY_SIGNATURE = "uuid, uuid, text, uuid"
SEARCH_SIGNATURE = "uuid, uuid, text, uuid, text, double precision[]"
PURGE_SIGNATURE = "uuid, uuid, uuid, text"
ERASE_SIGNATURE = "uuid, uuid, uuid, text"
PURGE_ERROR_SIGNATURE = "uuid, uuid, uuid, text"


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation
        ON milai.{table}
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )


def upgrade() -> None:
    op.execute("CREATE SEQUENCE milai.outbox_sequence AS bigint START WITH 1")
    op.add_column(
        "outbox_event",
        sa.Column(
            "outbox_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("nextval('milai.outbox_sequence')"),
        ),
        schema="milai",
    )
    op.create_unique_constraint(
        "uq_outbox_sequence", "outbox_event", ["outbox_sequence"], schema="milai"
    )

    op.create_table(
        "projection_delivery",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("projection_name", sa.Text(), nullable=False),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbox_sequence", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("handler_result_hash", sa.String(length=64), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "projection_name", "outbox_id", name="pk_projection_delivery"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "outbox_id"],
            ["milai.outbox_event.tenant_id", "milai.outbox_event.outbox_id"],
            name="fk_projection_delivery_outbox",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "projection_name",
            "outbox_sequence",
            name="uq_projection_delivery_sequence",
        ),
        sa.CheckConstraint(
            "projection_name IN ('fts', 'vector', 'purge')",
            name="ck_projection_delivery_name",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'DELIVERED', 'DEAD_LETTER')",
            name="ck_projection_delivery_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_projection_delivery_attempts"),
        sa.CheckConstraint(
            "handler_result_hash IS NULL OR handler_result_hash ~ '^[0-9a-f]{64}$'",
            name="ck_projection_delivery_result_hash",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_projection_delivery_dispatch",
        "projection_delivery",
        ["tenant_id", "projection_name", "state", "outbox_sequence"],
        schema="milai",
    )

    op.create_table(
        "index_watermark",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("projection_name", sa.Text(), nullable=False),
        sa.Column(
            "last_contiguous_outbox_sequence", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "projection_name", name="pk_index_watermark"),
        sa.CheckConstraint(
            "projection_name IN ('fts', 'vector', 'purge')",
            name="ck_index_watermark_name",
        ),
        sa.CheckConstraint("last_contiguous_outbox_sequence >= 0", name="ck_index_watermark_value"),
        schema="milai",
    )

    op.create_table(
        "search_document",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column("scope_predicate", postgresql.JSONB(), nullable=False),
        sa.Column("valid_time_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_time_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=False),
        sa.Column("source_outbox_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "document_id", name="pk_search_document"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id", "claim_version_id"],
            [
                "milai.claim_version.tenant_id",
                "milai.claim_version.claim_id",
                "milai.claim_version.claim_version_id",
            ],
            name="fk_search_document_claim_version",
        ),
        sa.UniqueConstraint(
            "tenant_id", "claim_version_id", name="uq_search_document_claim_version"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_predicate) = 'object'", name="ck_search_document_scope"
        ),
        schema="milai",
    )
    op.create_index(
        "ix_search_document_fts",
        "search_document",
        ["search_vector"],
        schema="milai",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_search_document_claim",
        "search_document",
        ["tenant_id", "claim_id", "canonical_commit_seq"],
        schema="milai",
    )

    op.execute(
        """
        CREATE TABLE milai.search_embedding (
          tenant_id uuid NOT NULL,
          embedding_id uuid NOT NULL,
          claim_id uuid NOT NULL,
          claim_version_id uuid NOT NULL,
          embedding vector(16) NOT NULL,
          model_id text NOT NULL,
          projection_version text NOT NULL,
          canonical_commit_seq bigint NOT NULL,
          source_outbox_sequence bigint NOT NULL,
          projected_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_search_embedding PRIMARY KEY (tenant_id, embedding_id),
          CONSTRAINT uq_search_embedding_version_model UNIQUE (
            tenant_id, claim_version_id, model_id, projection_version
          ),
          CONSTRAINT fk_search_embedding_claim_version FOREIGN KEY (
            tenant_id, claim_id, claim_version_id
          ) REFERENCES milai.claim_version (
            tenant_id, claim_id, claim_version_id
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_embedding_hnsw
        ON milai.search_embedding USING hnsw (embedding vector_cosine_ops)
        """
    )

    for table in (
        "projection_delivery",
        "index_watermark",
        "search_document",
        "search_embedding",
    ):
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.protect_evidence_blob_state()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_state text;
        BEGIN
          SELECT physical_delete_state INTO v_state
          FROM milai.content_blob
          WHERE tenant_id = NEW.tenant_id AND blob_id = NEW.blob_id
          FOR UPDATE;
          IF v_state = 'ERASED' THEN
            UPDATE milai.content_blob SET physical_delete_state = 'PRESENT'
            WHERE tenant_id = NEW.tenant_id AND blob_id = NEW.blob_id
              AND physical_delete_state = 'ERASED';
          ELSIF v_state <> 'PRESENT' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BLOB_PURGE_RACE';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_evidence_blob_state
        BEFORE INSERT ON milai.evidence_record
        FOR EACH ROW EXECUTE FUNCTION milai.protect_evidence_blob_state()
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.lease_projection_event(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_worker_id text,
          p_lease_seconds integer,
          p_max_attempts integer
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_delivery milai.projection_delivery%ROWTYPE;
          v_event milai.outbox_event%ROWTYPE;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('fts', 'vector', 'purge')
             OR length(btrim(p_worker_id)) = 0 OR length(p_worker_id) > 128
             OR p_lease_seconds < 1 OR p_lease_seconds > 300
             OR p_max_attempts < 1 OR p_max_attempts > 100 THEN
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
            e.tenant_id, p_projection_name, e.outbox_id, e.outbox_sequence,
            'PENDING', 0, CURRENT_TIMESTAMP, p_actor_id
          FROM milai.outbox_event e
          WHERE e.tenant_id = p_tenant_id
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery d
              WHERE d.tenant_id = e.tenant_id
                AND d.projection_name = p_projection_name
                AND d.outbox_id = e.outbox_id
            )
          ORDER BY e.outbox_sequence
          LIMIT 128
          ON CONFLICT DO NOTHING;

          SELECT d.* INTO v_delivery
          FROM milai.projection_delivery d
          WHERE d.tenant_id = p_tenant_id
            AND d.projection_name = p_projection_name
            AND d.state = 'PENDING'
            AND d.available_at <= CURRENT_TIMESTAMP
            AND d.outbox_sequence = (
              SELECT min(first_pending.outbox_sequence)
              FROM milai.projection_delivery first_pending
              WHERE first_pending.tenant_id = p_tenant_id
                AND first_pending.projection_name = p_projection_name
                AND first_pending.state <> 'DELIVERED'
            )
          FOR UPDATE SKIP LOCKED;
          IF NOT FOUND THEN
            RETURN NULL;
          END IF;
          UPDATE milai.projection_delivery
          SET state = 'PROCESSING', attempt_count = attempt_count + 1,
              lease_owner = p_worker_id,
              lease_expires_at = CURRENT_TIMESTAMP
                + make_interval(secs => p_lease_seconds),
              last_error_code = NULL
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = v_delivery.outbox_id
          RETURNING * INTO v_delivery;
          SELECT * INTO STRICT v_event FROM milai.outbox_event
          WHERE tenant_id = p_tenant_id AND outbox_id = v_delivery.outbox_id;
          RETURN jsonb_build_object(
            'outbox_id', v_event.outbox_id,
            'outbox_sequence', v_event.outbox_sequence,
            'event_type', v_event.event_type,
            'aggregate_type', v_event.aggregate_type,
            'aggregate_id', v_event.aggregate_id,
            'payload', v_event.payload,
            'canonical_commit_seq', v_event.canonical_commit_seq,
            'attempt_count', v_delivery.attempt_count,
            'lease_expires_at', v_delivery.lease_expires_at
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.complete_projection_event(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid,
          p_worker_id text,
          p_handler_result_hash text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_sequence bigint;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_handler_result_hash !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          UPDATE milai.projection_delivery
          SET state = 'DELIVERED', delivered_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              handler_result_hash = p_handler_result_hash
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = p_outbox_id
            AND state = 'PROCESSING' AND lease_owner = p_worker_id
            AND lease_expires_at > CURRENT_TIMESTAMP
          RETURNING outbox_sequence INTO v_sequence;
          IF v_sequence IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          UPDATE milai.index_watermark
          SET last_contiguous_outbox_sequence = v_sequence,
              updated_at = CURRENT_TIMESTAMP, updated_by_actor_id = p_actor_id
          WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name
            AND NOT EXISTS (
              SELECT 1 FROM milai.projection_delivery gap
              WHERE gap.tenant_id = p_tenant_id
                AND gap.projection_name = p_projection_name
                AND gap.outbox_sequence < v_sequence
                AND gap.state <> 'DELIVERED'
            );
          RETURN (
            SELECT last_contiguous_outbox_sequence
            FROM milai.index_watermark
            WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.fail_projection_event(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid,
          p_worker_id text,
          p_error_code text,
          p_max_attempts integer,
          p_retry_delay_seconds integer
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_state text;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_error_code !~ '^[A-Z0-9_:-]{1,128}$'
             OR p_max_attempts < 1 OR p_max_attempts > 100
             OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          UPDATE milai.projection_delivery
          SET state = CASE WHEN attempt_count >= p_max_attempts
                           THEN 'DEAD_LETTER' ELSE 'PENDING' END,
              available_at = CURRENT_TIMESTAMP
                + make_interval(secs => p_retry_delay_seconds),
              lease_owner = NULL, lease_expires_at = NULL,
              last_error_code = p_error_code
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = p_outbox_id
            AND state = 'PROCESSING' AND lease_owner = p_worker_id
          RETURNING state INTO v_state;
          IF v_state IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF p_projection_name = 'purge' AND v_state = 'DEAD_LETTER' THEN
            UPDATE milai.deletion_request deletion
            SET derived_purge_status = 'DEAD_LETTER',
                last_error_code = p_error_code
            FROM milai.outbox_event event
            WHERE event.tenant_id = p_tenant_id
              AND event.outbox_id = p_outbox_id
              AND event.aggregate_type = 'DELETION_REQUEST'
              AND deletion.tenant_id = event.tenant_id
              AND deletion.deletion_request_id = event.aggregate_id;
          END IF;
          RETURN v_state;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.retry_dead_letter(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          UPDATE milai.projection_delivery
          SET state = 'PENDING', available_at = CURRENT_TIMESTAMP,
              lease_owner = NULL, lease_expires_at = NULL,
              last_error_code = NULL
          WHERE tenant_id = p_tenant_id
            AND projection_name = p_projection_name
            AND outbox_id = p_outbox_id AND state = 'DEAD_LETTER';
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'DEAD_LETTER_NOT_FOUND';
          END IF;
          IF p_projection_name = 'purge' THEN
            UPDATE milai.deletion_request deletion
            SET derived_purge_status = 'PENDING', last_error_code = NULL
            FROM milai.outbox_event event
            WHERE event.tenant_id = p_tenant_id
              AND event.outbox_id = p_outbox_id
              AND event.aggregate_type = 'DELETION_REQUEST'
              AND deletion.tenant_id = event.tenant_id
              AND deletion.deletion_request_id = event.aggregate_id;
          END IF;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.apply_search_projection(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid,
          p_worker_id text,
          p_embedding double precision[]
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_event milai.outbox_event%ROWTYPE;
          v_version milai.claim_version%ROWTYPE;
          v_claim milai.claim%ROWTYPE;
          v_version_id uuid;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('fts', 'vector')
             OR NOT EXISTS (
               SELECT 1 FROM milai.projection_delivery d
               WHERE d.tenant_id = p_tenant_id
                 AND d.projection_name = p_projection_name
                 AND d.outbox_id = p_outbox_id
                 AND d.state = 'PROCESSING' AND d.lease_owner = p_worker_id
                 AND d.lease_expires_at > CURRENT_TIMESTAMP
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          SELECT * INTO STRICT v_event FROM milai.outbox_event
          WHERE tenant_id = p_tenant_id AND outbox_id = p_outbox_id;
          IF v_event.event_type = 'PURGE_EVIDENCE_DERIVATIVES' THEN
            IF p_projection_name = 'fts' THEN
              DELETE FROM milai.search_document document
              USING milai.deletion_request deletion
              WHERE deletion.tenant_id = p_tenant_id
                AND deletion.deletion_request_id = v_event.aggregate_id
                AND document.tenant_id = deletion.tenant_id
                AND EXISTS (
                  SELECT 1 FROM milai.grounding_relation gr
                  WHERE gr.tenant_id = document.tenant_id
                    AND gr.claim_version_id = document.claim_version_id
                    AND gr.evidence_id = deletion.evidence_id
                );
            ELSE
              DELETE FROM milai.search_embedding embedding
              USING milai.deletion_request deletion
              WHERE deletion.tenant_id = p_tenant_id
                AND deletion.deletion_request_id = v_event.aggregate_id
                AND embedding.tenant_id = deletion.tenant_id
                AND EXISTS (
                  SELECT 1 FROM milai.grounding_relation gr
                  WHERE gr.tenant_id = embedding.tenant_id
                    AND gr.claim_version_id = embedding.claim_version_id
                    AND gr.evidence_id = deletion.evidence_id
                );
            END IF;
            RETURN jsonb_build_object(
              'action', 'PURGED', 'projection', p_projection_name,
              'deletion_request_id', v_event.aggregate_id
            );
          END IF;
          BEGIN
            v_version_id := NULLIF(v_event.payload ->> 'claim_version_id', '')::uuid;
          EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_OUTBOX_EVENT';
          END;
          IF v_version_id IS NULL THEN
            RETURN jsonb_build_object('action', 'NO_OP', 'reason', 'NO_CLAIM_VERSION');
          END IF;
          SELECT * INTO v_version FROM milai.claim_version
          WHERE tenant_id = p_tenant_id AND claim_version_id = v_version_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CANONICAL_VERSION_NOT_FOUND';
          END IF;
          SELECT * INTO STRICT v_claim FROM milai.claim
          WHERE tenant_id = p_tenant_id AND claim_id = v_version.claim_id;

          IF p_projection_name = 'fts' THEN
            INSERT INTO milai.search_document (
              tenant_id, document_id, claim_id, claim_version_id,
              content_text, search_vector, scope_predicate,
              valid_time_from, valid_time_to, authority,
              canonical_commit_seq, source_outbox_sequence,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_claim.claim_id,
              v_version.claim_version_id,
              concat_ws(
                ' ', v_claim.subject_id, v_claim.predicate,
                v_claim.claim_type, v_version.payload::text
              ),
              to_tsvector('simple', concat_ws(
                ' ', v_claim.subject_id, v_claim.predicate,
                v_claim.claim_type, v_version.payload::text
              )),
              v_version.scope_predicate, v_version.valid_time_from,
              v_version.valid_time_to, v_version.authority,
              v_version.canonical_commit_seq, v_event.outbox_sequence,
              p_actor_id
            ) ON CONFLICT (tenant_id, claim_version_id) DO UPDATE
            SET content_text = EXCLUDED.content_text,
                search_vector = EXCLUDED.search_vector,
                scope_predicate = EXCLUDED.scope_predicate,
                valid_time_from = EXCLUDED.valid_time_from,
                valid_time_to = EXCLUDED.valid_time_to,
                authority = EXCLUDED.authority,
                canonical_commit_seq = EXCLUDED.canonical_commit_seq,
                source_outbox_sequence = EXCLUDED.source_outbox_sequence,
                projected_at = CURRENT_TIMESTAMP,
                created_by_actor_id = EXCLUDED.created_by_actor_id;
          ELSE
            IF cardinality(p_embedding) <> 16 THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EMBEDDING';
            END IF;
            INSERT INTO milai.search_embedding (
              tenant_id, embedding_id, claim_id, claim_version_id,
              embedding, model_id, projection_version,
              canonical_commit_seq, source_outbox_sequence,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_claim.claim_id,
              v_version.claim_version_id, p_embedding::public.vector,
              'deterministic-hash-v1', '1',
              v_version.canonical_commit_seq, v_event.outbox_sequence,
              p_actor_id
            ) ON CONFLICT (
              tenant_id, claim_version_id, model_id, projection_version
            ) DO UPDATE
            SET embedding = EXCLUDED.embedding,
                canonical_commit_seq = EXCLUDED.canonical_commit_seq,
                source_outbox_sequence = EXCLUDED.source_outbox_sequence,
                projected_at = CURRENT_TIMESTAMP,
                created_by_actor_id = EXCLUDED.created_by_actor_id;
          END IF;
          RETURN jsonb_build_object(
            'action', 'PROJECTED', 'projection', p_projection_name,
            'claim_id', v_claim.claim_id,
            'claim_version_id', v_version.claim_version_id
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.apply_purge_projection(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_outbox_id uuid,
          p_worker_id text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_event milai.outbox_event%ROWTYPE;
          v_request milai.deletion_request%ROWTYPE;
          v_blob milai.content_blob%ROWTYPE;
          v_blocking_refs integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF NOT EXISTS (
            SELECT 1 FROM milai.projection_delivery d
            WHERE d.tenant_id = p_tenant_id AND d.projection_name = 'purge'
              AND d.outbox_id = p_outbox_id AND d.state = 'PROCESSING'
              AND d.lease_owner = p_worker_id
              AND d.lease_expires_at > CURRENT_TIMESTAMP
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          SELECT * INTO STRICT v_event FROM milai.outbox_event
          WHERE tenant_id = p_tenant_id AND outbox_id = p_outbox_id;
          IF v_event.event_type <> 'PURGE_EVIDENCE_DERIVATIVES' THEN
            RETURN jsonb_build_object('action', 'NO_OP', 'reason', 'NOT_PURGE_EVENT');
          END IF;
          SELECT * INTO STRICT v_request FROM milai.deletion_request
          WHERE tenant_id = p_tenant_id
            AND deletion_request_id = v_event.aggregate_id
          FOR UPDATE;

          DELETE FROM milai.search_embedding embedding
          WHERE embedding.tenant_id = p_tenant_id
            AND EXISTS (
              SELECT 1 FROM milai.grounding_relation gr
              WHERE gr.tenant_id = embedding.tenant_id
                AND gr.claim_version_id = embedding.claim_version_id
                AND gr.evidence_id = v_request.evidence_id
            );
          DELETE FROM milai.search_document document
          WHERE document.tenant_id = p_tenant_id
            AND EXISTS (
              SELECT 1 FROM milai.grounding_relation gr
              WHERE gr.tenant_id = document.tenant_id
                AND gr.claim_version_id = document.claim_version_id
                AND gr.evidence_id = v_request.evidence_id
            );
          UPDATE milai.context_capsule capsule
          SET protected_sections = '{}'::jsonb,
              content_hash =
                '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'
          WHERE capsule.tenant_id = p_tenant_id
            AND capsule.status = 'INVALIDATED'
            AND EXISTS (
              SELECT 1 FROM milai.context_pointer pointer
              WHERE pointer.tenant_id = capsule.tenant_id
                AND pointer.capsule_id = capsule.capsule_id
                AND pointer.evidence_id = v_request.evidence_id
            );
          UPDATE milai.deletion_request
          SET derived_purge_status = 'COMPLETED',
              purge_completed_at = COALESCE(purge_completed_at, CURRENT_TIMESTAMP),
              last_error_code = NULL
          WHERE tenant_id = p_tenant_id
            AND deletion_request_id = v_request.deletion_request_id;

          SELECT count(*) INTO v_blocking_refs
          FROM milai.evidence_record evidence
          WHERE evidence.tenant_id = p_tenant_id
            AND evidence.blob_id = v_request.blob_id
            AND (
              evidence.revoked_at IS NULL
              OR evidence.retention_state IN ('LEGAL_HOLD', 'UNREADABLE')
            );
          IF v_blocking_refs = 0 THEN
            UPDATE milai.content_blob
            SET physical_delete_state = 'PURGE_PENDING'
            WHERE tenant_id = p_tenant_id AND blob_id = v_request.blob_id
              AND physical_delete_state IN ('PRESENT', 'ERROR');
            UPDATE milai.deletion_request
            SET primary_bytes_status = 'PENDING',
                shared_live_reference_count = 0
            WHERE tenant_id = p_tenant_id AND blob_id = v_request.blob_id
              AND retention_status = 'CLEAR'
              AND primary_bytes_status IN (
                'BLOCKED_SHARED_REFERENCE', 'ERROR', 'PENDING'
              );
          END IF;
          SELECT * INTO STRICT v_blob FROM milai.content_blob
          WHERE tenant_id = p_tenant_id AND blob_id = v_request.blob_id;
          SELECT * INTO STRICT v_request FROM milai.deletion_request
          WHERE tenant_id = p_tenant_id
            AND deletion_request_id = v_request.deletion_request_id;
          RETURN jsonb_build_object(
            'action', 'PURGED_DERIVATIVES',
            'deletion_request_id', v_request.deletion_request_id,
            'evidence_id', v_request.evidence_id,
            'blob_id', v_blob.blob_id,
            'storage_uri', v_blob.storage_uri,
            'content_hash', v_blob.content_hash,
            'byte_length', v_blob.byte_length,
            'primary_bytes_status', v_request.primary_bytes_status,
            'physical_delete_state', v_blob.physical_delete_state
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.complete_blob_erasure(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_blob_id uuid,
          p_worker_id text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF NOT EXISTS (
            SELECT 1
            FROM milai.projection_delivery delivery
            JOIN milai.outbox_event event
              ON event.tenant_id = delivery.tenant_id
             AND event.outbox_id = delivery.outbox_id
            JOIN milai.deletion_request deletion
              ON deletion.tenant_id = event.tenant_id
             AND deletion.deletion_request_id = event.aggregate_id
            WHERE delivery.tenant_id = p_tenant_id
              AND delivery.projection_name = 'purge'
              AND delivery.state = 'PROCESSING'
              AND delivery.lease_owner = p_worker_id
              AND delivery.lease_expires_at > CURRENT_TIMESTAMP
              AND event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
              AND deletion.blob_id = p_blob_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          IF EXISTS (
            SELECT 1 FROM milai.evidence_record evidence
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.blob_id = p_blob_id
              AND (
                evidence.revoked_at IS NULL
                OR evidence.retention_state IN ('LEGAL_HOLD', 'UNREADABLE')
              )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BLOB_STILL_REFERENCED';
          END IF;
          UPDATE milai.content_blob SET physical_delete_state = 'ERASED'
          WHERE tenant_id = p_tenant_id AND blob_id = p_blob_id
            AND physical_delete_state IN ('PURGE_PENDING', 'ERASED');
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BLOB_NOT_PURGEABLE';
          END IF;
          UPDATE milai.deletion_request
          SET primary_bytes_status = 'ERASED',
              primary_bytes_erased_at = COALESCE(
                primary_bytes_erased_at, CURRENT_TIMESTAMP
              ), last_error_code = NULL
          WHERE tenant_id = p_tenant_id AND blob_id = p_blob_id
            AND retention_status = 'CLEAR';
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.record_purge_error(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_deletion_request_id uuid,
          p_error_code text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_error_code !~ '^[A-Z0-9_:-]{1,128}$' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_WORKER_REQUEST';
          END IF;
          UPDATE milai.deletion_request
          SET last_error_code = p_error_code,
              primary_bytes_status = CASE
                WHEN primary_bytes_status = 'PENDING' THEN 'ERROR'
                ELSE primary_bytes_status END
          WHERE tenant_id = p_tenant_id
            AND deletion_request_id = p_deletion_request_id;
        END
        $$
        """
    )

    tables = (
        "milai.projection_delivery, milai.index_watermark, "
        "milai.search_document, milai.search_embedding"
    )
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"GRANT SELECT ON TABLE {tables} TO milai_api, milai_steward, milai_worker, milai_audit"
    )
    for signature, name in (
        (LEASE_SIGNATURE, "lease_projection_event"),
        (COMPLETE_SIGNATURE, "complete_projection_event"),
        (FAIL_SIGNATURE, "fail_projection_event"),
        (SEARCH_SIGNATURE, "apply_search_projection"),
        (PURGE_SIGNATURE, "apply_purge_projection"),
        (ERASE_SIGNATURE, "complete_blob_erasure"),
        (PURGE_ERROR_SIGNATURE, "record_purge_error"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_worker")
    op.execute(f"REVOKE ALL ON FUNCTION milai.retry_dead_letter({RETRY_SIGNATURE}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.retry_dead_letter({RETRY_SIGNATURE}) TO milai_steward"
    )
    op.execute("REVOKE ALL ON FUNCTION milai.protect_evidence_blob_state() FROM PUBLIC")


def downgrade() -> None:
    for signature, name in (
        (PURGE_ERROR_SIGNATURE, "record_purge_error"),
        (ERASE_SIGNATURE, "complete_blob_erasure"),
        (PURGE_SIGNATURE, "apply_purge_projection"),
        (SEARCH_SIGNATURE, "apply_search_projection"),
        (RETRY_SIGNATURE, "retry_dead_letter"),
        (FAIL_SIGNATURE, "fail_projection_event"),
        (COMPLETE_SIGNATURE, "complete_projection_event"),
        (LEASE_SIGNATURE, "lease_projection_event"),
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.execute("DROP FUNCTION milai.protect_evidence_blob_state() CASCADE")
    op.execute("DROP TABLE milai.search_embedding")
    op.drop_index("ix_search_document_claim", table_name="search_document", schema="milai")
    op.drop_index("ix_search_document_fts", table_name="search_document", schema="milai")
    op.drop_table("search_document", schema="milai")
    op.drop_table("index_watermark", schema="milai")
    op.drop_index(
        "ix_projection_delivery_dispatch",
        table_name="projection_delivery",
        schema="milai",
    )
    op.drop_table("projection_delivery", schema="milai")
    op.drop_constraint("uq_outbox_sequence", "outbox_event", schema="milai", type_="unique")
    op.drop_column("outbox_event", "outbox_sequence", schema="milai")
    op.execute("DROP SEQUENCE milai.outbox_sequence")
