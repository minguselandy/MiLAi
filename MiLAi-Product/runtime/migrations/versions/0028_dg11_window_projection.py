"""Add reversible DG-11 turn/window FTS and 128d vector projections.

Revision ID: 0028_dg11_window_projection
Revises: 0027_embedding_identity

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
The existing session/vector(16) projections remain intact for rollback.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_dg11_window_projection"
down_revision: str | None = "0027_embedding_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION_SIGNATURE = (
    "uuid, uuid, text, uuid, text, integer, text, integer, integer, "
    "text, text[], double precision[], text, text"
)


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
    op.create_table(
        "search_document_fragment",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fragment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fragment_ordinal", sa.Integer(), nullable=False),
        sa.Column("fragment_kind", sa.Text(), nullable=False),
        sa.Column("turn_start", sa.Integer(), nullable=False),
        sa.Column("turn_end", sa.Integer(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("tenant_id", "fragment_id", name="pk_search_document_fragment"),
        sa.UniqueConstraint(
            "tenant_id",
            "claim_version_id",
            "fragment_ordinal",
            name="uq_search_document_fragment_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id", "claim_version_id"],
            [
                "milai.claim_version.tenant_id",
                "milai.claim_version.claim_id",
                "milai.claim_version.claim_version_id",
            ],
            name="fk_search_document_fragment_claim_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "fragment_ordinal >= 0 AND turn_start >= 0 AND turn_end >= turn_start",
            name="ck_search_document_fragment_position",
        ),
        sa.CheckConstraint(
            "fragment_kind IN ('turn', 'window')",
            name="ck_search_document_fragment_kind",
        ),
        sa.CheckConstraint(
            "cardinality(roles) BETWEEN 1 AND 2",
            name="ck_search_document_fragment_roles",
        ),
        sa.CheckConstraint(
            "length(btrim(content_text)) BETWEEN 1 AND 32768",
            name="ck_search_document_fragment_content",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_predicate) = 'object'",
            name="ck_search_document_fragment_scope",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_search_document_fragment_fts",
        "search_document_fragment",
        ["search_vector"],
        schema="milai",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_search_document_fragment_parent",
        "search_document_fragment",
        ["tenant_id", "claim_version_id", "canonical_commit_seq"],
        schema="milai",
    )
    op.execute(
        """
        CREATE TABLE milai.search_embedding_window_128 (
          tenant_id uuid NOT NULL,
          embedding_id uuid NOT NULL,
          fragment_id uuid NOT NULL,
          claim_id uuid NOT NULL,
          claim_version_id uuid NOT NULL,
          embedding vector(128) NOT NULL,
          model_id text NOT NULL,
          projection_version text NOT NULL,
          canonical_commit_seq bigint NOT NULL,
          source_outbox_sequence bigint NOT NULL,
          projected_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_search_embedding_window_128
            PRIMARY KEY (tenant_id, embedding_id),
          CONSTRAINT uq_search_embedding_window_128_fragment UNIQUE (
            tenant_id, fragment_id, model_id, projection_version
          ),
          CONSTRAINT fk_search_embedding_window_128_fragment FOREIGN KEY (
            tenant_id, fragment_id
          ) REFERENCES milai.search_document_fragment (tenant_id, fragment_id)
            ON DELETE CASCADE,
          CONSTRAINT fk_search_embedding_window_128_claim_version FOREIGN KEY (
            tenant_id, claim_id, claim_version_id
          ) REFERENCES milai.claim_version (
            tenant_id, claim_id, claim_version_id
          ) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_embedding_window_128_hnsw
        ON milai.search_embedding_window_128
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    _tenant_policy("search_document_fragment")
    _tenant_policy("search_embedding_window_128")
    _create_projection_function()
    tables = "milai.search_document_fragment, milai.search_embedding_window_128"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"GRANT SELECT ON TABLE {tables} TO milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.apply_window_search_projection("
        f"{FUNCTION_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.apply_window_search_projection("
        f"{FUNCTION_SIGNATURE}) TO milai_worker"
    )


def _create_projection_function() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.apply_window_search_projection(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_outbox_id uuid,
          p_worker_id text,
          p_fragment_ordinal integer,
          p_fragment_kind text,
          p_turn_start integer,
          p_turn_end integer,
          p_content_text text,
          p_roles text[],
          p_embedding double precision[],
          p_model_id text,
          p_projection_version text
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
          v_fragment_id uuid;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('fts', 'vector')
             OR NOT EXISTS (
               SELECT 1 FROM milai.projection_delivery delivery
               WHERE delivery.tenant_id = p_tenant_id
                 AND delivery.projection_name = p_projection_name
                 AND delivery.outbox_id = p_outbox_id
                 AND delivery.state = 'PROCESSING'
                 AND delivery.lease_owner = p_worker_id
                 AND delivery.lease_expires_at > CURRENT_TIMESTAMP
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LEASE_LOST';
          END IF;
          SELECT * INTO STRICT v_event FROM milai.outbox_event
          WHERE tenant_id = p_tenant_id AND outbox_id = p_outbox_id;
          IF v_event.event_type = 'PURGE_EVIDENCE_DERIVATIVES' THEN
            IF p_projection_name = 'fts' THEN
              DELETE FROM milai.search_document_fragment document
              USING milai.deletion_request deletion
              WHERE deletion.tenant_id = p_tenant_id
                AND deletion.deletion_request_id = v_event.aggregate_id
                AND document.tenant_id = deletion.tenant_id
                AND EXISTS (
                  SELECT 1 FROM milai.grounding_relation relation
                  WHERE relation.tenant_id = document.tenant_id
                    AND relation.claim_version_id = document.claim_version_id
                    AND relation.evidence_id = deletion.evidence_id
                );
            ELSE
              DELETE FROM milai.search_embedding_window_128 embedding
              USING milai.deletion_request deletion
              WHERE deletion.tenant_id = p_tenant_id
                AND deletion.deletion_request_id = v_event.aggregate_id
                AND embedding.tenant_id = deletion.tenant_id
                AND EXISTS (
                  SELECT 1 FROM milai.grounding_relation relation
                  WHERE relation.tenant_id = embedding.tenant_id
                    AND relation.claim_version_id = embedding.claim_version_id
                    AND relation.evidence_id = deletion.evidence_id
                );
            END IF;
            RETURN jsonb_build_object(
              'action', 'PURGED', 'projection', p_projection_name,
              'window_projection', 'DG11_A2_128D'
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
          SELECT * INTO STRICT v_version FROM milai.claim_version
          WHERE tenant_id = p_tenant_id AND claim_version_id = v_version_id;
          SELECT * INTO STRICT v_claim FROM milai.claim
          WHERE tenant_id = p_tenant_id AND claim_id = v_version.claim_id;
          IF p_fragment_ordinal < 0
             OR p_fragment_kind NOT IN ('turn', 'window')
             OR p_turn_start < 0 OR p_turn_end < p_turn_start
             OR cardinality(p_roles) NOT BETWEEN 1 AND 2
             OR length(btrim(p_content_text)) NOT BETWEEN 1 AND 32768 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_FRAGMENT';
          END IF;
          IF p_projection_name = 'fts' THEN
            IF p_fragment_ordinal = 0 THEN
              DELETE FROM milai.search_document_fragment
              WHERE tenant_id = p_tenant_id
                AND claim_version_id = v_version.claim_version_id;
            END IF;
            INSERT INTO milai.search_document_fragment (
              tenant_id, fragment_id, claim_id, claim_version_id,
              fragment_ordinal, fragment_kind, turn_start, turn_end,
              roles, content_text, search_vector, scope_predicate,
              valid_time_from, valid_time_to, authority,
              canonical_commit_seq, source_outbox_sequence, created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_claim.claim_id,
              v_version.claim_version_id, p_fragment_ordinal, p_fragment_kind,
              p_turn_start, p_turn_end, p_roles, p_content_text,
              to_tsvector('simple', p_content_text), v_version.scope_predicate,
              v_version.valid_time_from, v_version.valid_time_to,
              v_version.authority, v_version.canonical_commit_seq,
              v_event.outbox_sequence, p_actor_id
            ) ON CONFLICT (
              tenant_id, claim_version_id, fragment_ordinal
            ) DO UPDATE SET
              fragment_kind = EXCLUDED.fragment_kind,
              turn_start = EXCLUDED.turn_start,
              turn_end = EXCLUDED.turn_end,
              roles = EXCLUDED.roles,
              content_text = EXCLUDED.content_text,
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
            IF cardinality(p_embedding) <> 128
               OR length(btrim(p_model_id)) NOT BETWEEN 1 AND 255
               OR p_projection_version !~ '^[0-9a-f]{64}$' THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EMBEDDING';
            END IF;
            IF p_fragment_ordinal = 0 THEN
              DELETE FROM milai.search_embedding_window_128
              WHERE tenant_id = p_tenant_id
                AND claim_version_id = v_version.claim_version_id
                AND model_id = p_model_id
                AND projection_version = p_projection_version;
            END IF;
            SELECT fragment_id INTO STRICT v_fragment_id
            FROM milai.search_document_fragment
            WHERE tenant_id = p_tenant_id
              AND claim_version_id = v_version.claim_version_id
              AND fragment_ordinal = p_fragment_ordinal;
            INSERT INTO milai.search_embedding_window_128 (
              tenant_id, embedding_id, fragment_id, claim_id,
              claim_version_id, embedding, model_id, projection_version,
              canonical_commit_seq, source_outbox_sequence, created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_fragment_id, v_claim.claim_id,
              v_version.claim_version_id, p_embedding::public.vector,
              p_model_id, p_projection_version, v_version.canonical_commit_seq,
              v_event.outbox_sequence, p_actor_id
            ) ON CONFLICT (
              tenant_id, fragment_id, model_id, projection_version
            ) DO UPDATE SET
              embedding = EXCLUDED.embedding,
              canonical_commit_seq = EXCLUDED.canonical_commit_seq,
              source_outbox_sequence = EXCLUDED.source_outbox_sequence,
              projected_at = CURRENT_TIMESTAMP,
              created_by_actor_id = EXCLUDED.created_by_actor_id;
          END IF;
          RETURN jsonb_build_object(
            'action', 'PROJECTED', 'projection', p_projection_name,
            'window_projection', 'DG11_A2_128D',
            'claim_version_id', v_version.claim_version_id,
            'fragment_ordinal', p_fragment_ordinal
          );
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.apply_window_search_projection({FUNCTION_SIGNATURE})")
    op.execute("DROP TABLE milai.search_embedding_window_128")
    op.drop_index(
        "ix_search_document_fragment_parent",
        table_name="search_document_fragment",
        schema="milai",
    )
    op.drop_index(
        "ix_search_document_fragment_fts",
        table_name="search_document_fragment",
        schema="milai",
    )
    op.drop_table("search_document_fragment", schema="milai")
