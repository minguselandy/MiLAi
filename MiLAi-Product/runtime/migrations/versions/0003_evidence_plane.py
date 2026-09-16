"""Create Evidence Plane, idempotency, and transactional outbox.

Revision ID: 0003_evidence_plane
Revises: 0002_tenant_security_boundary

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_evidence_plane"
down_revision: str | None = "0002_tenant_security_boundary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "content_blob",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("key_reference", sa.Text(), nullable=True),
        sa.Column("physical_delete_state", sa.Text(), nullable=False, server_default="PRESENT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "blob_id", name="pk_content_blob"),
        sa.UniqueConstraint("tenant_id", "content_hash", name="uq_content_blob_tenant_hash"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_content_blob_hash"),
        sa.CheckConstraint("byte_length >= 0", name="ck_content_blob_byte_length"),
        sa.CheckConstraint(
            "physical_delete_state IN ('PRESENT', 'PURGE_PENDING', 'ERASED', 'ERROR')",
            name="ck_content_blob_delete_state",
        ),
        schema="milai",
    )
    op.create_table(
        "evidence_record",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("permission_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("retention_state", sa.Text(), nullable=False, server_default="READABLE"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("ingest_idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "evidence_id", name="pk_evidence_record"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "blob_id"],
            ["milai.content_blob.tenant_id", "milai.content_blob.blob_id"],
            name="fk_evidence_record_blob",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "ingest_idempotency_key", name="uq_evidence_ingest_idempotency"
        ),
        sa.CheckConstraint("length(btrim(source_type)) > 0", name="ck_evidence_source_type"),
        sa.CheckConstraint("length(btrim(source_ref)) > 0", name="ck_evidence_source_ref"),
        sa.CheckConstraint("length(btrim(subject_id)) > 0", name="ck_evidence_subject"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_evidence_hash"),
        sa.CheckConstraint(
            "jsonb_typeof(permission_snapshot) = 'object'",
            name="ck_evidence_permission_snapshot",
        ),
        sa.CheckConstraint(
            "retention_state IN ('READABLE', 'UNREADABLE', 'EXPIRED', 'LEGAL_HOLD')",
            name="ck_evidence_retention_state",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) "
            "OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="ck_evidence_revocation_pair",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_evidence_subject_observed",
        "evidence_record",
        ["tenant_id", "subject_id", sa.text("observed_at DESC")],
        schema="milai",
    )

    op.create_table(
        "idempotency_record",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_family", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "operation_family",
            "idempotency_key",
            name="pk_idempotency_record",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128", name="ck_idempotency_key_length"
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_idempotency_fingerprint"
        ),
        schema="milai",
    )

    op.create_table(
        "outbox_event",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outbox_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="100"),
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
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "outbox_id", name="pk_outbox_event"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_outbox_payload_object"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        sa.CheckConstraint(
            "state IN ('PENDING', 'PROCESSING', 'DELIVERED', 'DEAD_LETTER')",
            name="ck_outbox_state",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_outbox_dispatch",
        "outbox_event",
        ["state", "priority", "available_at", "created_at"],
        schema="milai",
    )

    for table in ("content_blob", "evidence_record", "idempotency_record", "outbox_event"):
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.protect_content_blob_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF ROW(
            NEW.tenant_id, NEW.blob_id, NEW.content_hash, NEW.storage_uri,
            NEW.byte_length, NEW.media_type, NEW.key_reference,
            NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.blob_id, OLD.content_hash, OLD.storage_uri,
            OLD.byte_length, OLD.media_type, OLD.key_reference,
            OLD.created_at, OLD.created_by_actor_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_CONTENT_BLOB';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_content_blob_identity_immutable
        BEFORE UPDATE ON milai.content_blob
        FOR EACH ROW EXECUTE FUNCTION milai.protect_content_blob_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.protect_evidence_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF ROW(
            NEW.tenant_id, NEW.evidence_id, NEW.source_type, NEW.source_ref,
            NEW.subject_id, NEW.observed_at, NEW.captured_at, NEW.blob_id,
            NEW.content_hash, NEW.permission_snapshot,
            NEW.ingest_idempotency_key, NEW.request_fingerprint,
            NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.evidence_id, OLD.source_type, OLD.source_ref,
            OLD.subject_id, OLD.observed_at, OLD.captured_at, OLD.blob_id,
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
    op.execute(
        """
        CREATE TRIGGER trg_evidence_identity_immutable
        BEFORE UPDATE ON milai.evidence_record
        FOR EACH ROW EXECUTE FUNCTION milai.protect_evidence_identity()
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.tx01_ingest_evidence(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_idempotency_key text,
          p_request_fingerprint text,
          p_source_type text,
          p_source_ref text,
          p_subject_id text,
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
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_blob_id uuid;
          v_evidence_id uuid;
          v_outbox_id uuid;
          v_response jsonb;
        BEGIN
          IF NULLIF(current_setting('milai.tenant_id', true), '')::uuid IS DISTINCT FROM p_tenant_id
             OR NULLIF(current_setting('milai.actor_id', true), '')::uuid IS DISTINCT FROM p_actor_id THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'TENANT_MISMATCH';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'TX-01_EVIDENCE_INGEST', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;

          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'TX-01_EVIDENCE_INGEST'
            AND idempotency_key = p_idempotency_key
          FOR UPDATE;

          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          INSERT INTO milai.content_blob (
            tenant_id, blob_id, content_hash, storage_uri, byte_length,
            media_type, physical_delete_state, created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), p_content_hash, p_storage_uri,
            p_byte_length, p_media_type, 'PRESENT', p_actor_id
          ) ON CONFLICT (tenant_id, content_hash) DO NOTHING;

          SELECT blob_id INTO STRICT v_blob_id
          FROM milai.content_blob
          WHERE tenant_id = p_tenant_id AND content_hash = p_content_hash;

          v_evidence_id := gen_random_uuid();
          INSERT INTO milai.evidence_record (
            tenant_id, evidence_id, source_type, source_ref, subject_id,
            observed_at, blob_id, content_hash, permission_snapshot,
            retention_state, ingest_idempotency_key, request_fingerprint,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, v_evidence_id, p_source_type, p_source_ref, p_subject_id,
            p_observed_at, v_blob_id, p_content_hash, p_permission_snapshot,
            p_retention_state, p_idempotency_key, p_request_fingerprint,
            p_actor_id
          );

          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'EVIDENCE_INGESTED', NULL,
            jsonb_build_object('evidence_id', v_evidence_id, 'content_hash', p_content_hash),
            p_actor_id
          );

          v_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id,
            event_type, payload, priority, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_outbox_id, 'EVIDENCE', v_evidence_id,
            'EVIDENCE_INGESTED',
            jsonb_build_object(
              'evidence_id', v_evidence_id,
              'blob_id', v_blob_id,
              'content_hash', p_content_hash
            ),
            100, p_actor_id
          );

          v_response := jsonb_build_object(
            'evidence_id', v_evidence_id,
            'blob_id', v_blob_id,
            'outbox_id', v_outbox_id,
            'replayed', false
          );
          UPDATE milai.idempotency_record
          SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'TX-01_EVIDENCE_INGEST'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON TABLE milai.content_blob, milai.evidence_record, "
        "milai.idempotency_record, milai.outbox_event "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.content_blob, milai.evidence_record "
        "TO milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute("GRANT SELECT ON TABLE milai.outbox_event TO milai_worker, milai_audit")
    op.execute(
        "REVOKE ALL ON FUNCTION milai.tx01_ingest_evidence(uuid, uuid, text, text, text, text, text, timestamptz, text, text, bigint, text, jsonb, text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION milai.tx01_ingest_evidence(uuid, uuid, text, text, text, text, text, timestamptz, text, text, bigint, text, jsonb, text) TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION milai.tx01_ingest_evidence(uuid, uuid, text, text, text, text, text, timestamptz, text, text, bigint, text, jsonb, text)"
    )
    op.execute("DROP FUNCTION milai.protect_evidence_identity() CASCADE")
    op.execute("DROP FUNCTION milai.protect_content_blob_identity() CASCADE")
    op.drop_table("outbox_event", schema="milai")
    op.drop_table("idempotency_record", schema="milai")
    op.drop_index("ix_evidence_subject_observed", table_name="evidence_record", schema="milai")
    op.drop_table("evidence_record", schema="milai")
    op.drop_table("content_blob", schema="milai")
