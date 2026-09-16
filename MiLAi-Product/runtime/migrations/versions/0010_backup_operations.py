"""Add backup/deletion reconciliation and projection rebuild controls.

Revision ID: 0010_backup_operations
Revises: 0009_context_chat

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_backup_operations"
down_revision: str | None = "0009_context_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD_SIGNATURE = "uuid, uuid, uuid, timestamptz, text, text, text, text, jsonb, jsonb"
EXPIRE_SIGNATURE = "uuid, uuid, uuid, text"
REBUILD_SIGNATURE = "uuid, uuid, text, text"


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
        "backup_manifest",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("backup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archive_name", sa.Text(), nullable=False),
        sa.Column("database_dump_hash", sa.String(length=64), nullable=False),
        sa.Column("blob_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("inventory_hash", sa.String(length=64), nullable=False),
        sa.Column("blob_content_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("inventory", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "backup_id", name="pk_backup_manifest"),
        sa.UniqueConstraint("tenant_id", "archive_name", name="uq_backup_archive_name"),
        sa.CheckConstraint(
            "database_dump_hash ~ '^[0-9a-f]{64}$' "
            "AND blob_manifest_hash ~ '^[0-9a-f]{64}$' "
            "AND inventory_hash ~ '^[0-9a-f]{64}$'",
            name="ck_backup_manifest_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(blob_content_hashes) = 'array' AND jsonb_typeof(inventory) = 'object'",
            name="ck_backup_manifest_json",
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'EXPIRED')", name="ck_backup_manifest_status"),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND expired_at IS NULL) "
            "OR (status = 'EXPIRED' AND expired_at IS NOT NULL)",
            name="ck_backup_manifest_expiry",
        ),
        schema="milai",
    )
    op.create_table(
        "backup_deletion_obligation",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("backup_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deletion_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "backup_id",
            "deletion_request_id",
            name="pk_backup_deletion_obligation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "backup_id"],
            ["milai.backup_manifest.tenant_id", "milai.backup_manifest.backup_id"],
            name="fk_backup_obligation_manifest",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "deletion_request_id"],
            ["milai.deletion_request.tenant_id", "milai.deletion_request.deletion_request_id"],
            name="fk_backup_obligation_deletion",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COMPLETED')", name="ck_backup_obligation_status"
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND fulfilled_at IS NULL) "
            "OR (status = 'COMPLETED' AND fulfilled_at IS NOT NULL)",
            name="ck_backup_obligation_completion",
        ),
        schema="milai",
    )
    op.create_index(
        "ix_backup_obligation_pending",
        "backup_deletion_obligation",
        ["tenant_id", "deletion_request_id", "status"],
        schema="milai",
    )
    for table in ("backup_manifest", "backup_deletion_obligation"):
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.attach_backup_deletion_obligations()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          INSERT INTO milai.backup_deletion_obligation (
            tenant_id, backup_id, deletion_request_id,
            status, created_by_actor_id
          )
          SELECT NEW.tenant_id, backup.backup_id,
                 NEW.deletion_request_id, 'PENDING', NEW.created_by_actor_id
          FROM milai.backup_manifest backup
          JOIN milai.content_blob blob
            ON blob.tenant_id = NEW.tenant_id AND blob.blob_id = NEW.blob_id
          WHERE backup.tenant_id = NEW.tenant_id
            AND backup.status = 'ACTIVE'
            AND backup.blob_content_hashes ? blob.content_hash
          ON CONFLICT DO NOTHING;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_deletion_backup_obligation
        AFTER INSERT ON milai.deletion_request
        FOR EACH ROW EXECUTE FUNCTION milai.attach_backup_deletion_obligations()
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.record_backup_manifest(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_backup_id uuid,
          p_snapshot_at timestamptz,
          p_archive_name text,
          p_database_dump_hash text,
          p_blob_manifest_hash text,
          p_inventory_hash text,
          p_blob_content_hashes jsonb,
          p_inventory jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_obligations integer;
          v_completed integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_snapshot_at IS NULL
             OR p_snapshot_at > CURRENT_TIMESTAMP + interval '5 minutes'
             OR length(btrim(p_archive_name)) = 0 OR length(p_archive_name) > 255
             OR position('/' in p_archive_name) > 0
             OR position(chr(92) in p_archive_name) > 0
             OR p_database_dump_hash !~ '^[0-9a-f]{64}$'
             OR p_blob_manifest_hash !~ '^[0-9a-f]{64}$'
             OR p_inventory_hash !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_blob_content_hashes) <> 'array'
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(p_blob_content_hashes) hash
               WHERE hash !~ '^[0-9a-f]{64}$'
             )
             OR jsonb_typeof(p_inventory) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_BACKUP_MANIFEST';
          END IF;
          INSERT INTO milai.backup_manifest (
            tenant_id, backup_id, snapshot_at, archive_name,
            database_dump_hash, blob_manifest_hash, inventory_hash,
            blob_content_hashes, inventory, status, created_by_actor_id
          ) VALUES (
            p_tenant_id, p_backup_id, p_snapshot_at, p_archive_name,
            p_database_dump_hash, p_blob_manifest_hash, p_inventory_hash,
            p_blob_content_hashes, p_inventory, 'ACTIVE', p_actor_id
          );

          INSERT INTO milai.backup_deletion_obligation (
            tenant_id, backup_id, deletion_request_id,
            status, created_by_actor_id
          )
          SELECT p_tenant_id, p_backup_id, deletion.deletion_request_id,
                 'PENDING', p_actor_id
          FROM milai.deletion_request deletion
          JOIN milai.content_blob blob
            ON blob.tenant_id = deletion.tenant_id
           AND blob.blob_id = deletion.blob_id
          WHERE deletion.tenant_id = p_tenant_id
            AND p_blob_content_hashes ? blob.content_hash
          ON CONFLICT DO NOTHING;
          GET DIAGNOSTICS v_obligations = ROW_COUNT;

          UPDATE milai.deletion_request deletion
          SET backup_expiry_status = 'COMPLETED',
              backup_expiry_completed_at = COALESCE(
                backup_expiry_completed_at, CURRENT_TIMESTAMP
              )
          WHERE deletion.tenant_id = p_tenant_id
            AND deletion.retention_status = 'CLEAR'
            AND deletion.primary_bytes_status = 'ERASED'
            AND deletion.backup_expiry_status = 'PENDING'
            AND NOT EXISTS (
              SELECT 1 FROM milai.backup_deletion_obligation obligation
              JOIN milai.backup_manifest backup
                ON backup.tenant_id = obligation.tenant_id
               AND backup.backup_id = obligation.backup_id
              WHERE obligation.tenant_id = deletion.tenant_id
                AND obligation.deletion_request_id = deletion.deletion_request_id
                AND obligation.status = 'PENDING'
                AND backup.status = 'ACTIVE'
            );
          GET DIAGNOSTICS v_completed = ROW_COUNT;
          RETURN jsonb_build_object(
            'backup_id', p_backup_id,
            'status', 'ACTIVE',
            'deletion_obligations', v_obligations,
            'deletion_requests_completed', v_completed
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.expire_backup_manifest(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_backup_id uuid,
          p_confirmation text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_obligations integer;
          v_completed integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_confirmation <> 'ARCHIVE_ERASED' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BACKUP_EXPIRY_NOT_CONFIRMED';
          END IF;
          UPDATE milai.backup_manifest
          SET status = 'EXPIRED', expired_at = CURRENT_TIMESTAMP
          WHERE tenant_id = p_tenant_id AND backup_id = p_backup_id
            AND status = 'ACTIVE';
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'BACKUP_MANIFEST_NOT_ACTIVE';
          END IF;
          UPDATE milai.backup_deletion_obligation
          SET status = 'COMPLETED', fulfilled_at = CURRENT_TIMESTAMP
          WHERE tenant_id = p_tenant_id AND backup_id = p_backup_id
            AND status = 'PENDING';
          GET DIAGNOSTICS v_obligations = ROW_COUNT;
          UPDATE milai.deletion_request deletion
          SET backup_expiry_status = 'COMPLETED',
              backup_expiry_completed_at = COALESCE(
                backup_expiry_completed_at, CURRENT_TIMESTAMP
              )
          WHERE deletion.tenant_id = p_tenant_id
            AND deletion.retention_status = 'CLEAR'
            AND deletion.primary_bytes_status = 'ERASED'
            AND deletion.backup_expiry_status = 'PENDING'
            AND NOT EXISTS (
              SELECT 1 FROM milai.backup_deletion_obligation obligation
              JOIN milai.backup_manifest backup
                ON backup.tenant_id = obligation.tenant_id
               AND backup.backup_id = obligation.backup_id
              WHERE obligation.tenant_id = deletion.tenant_id
                AND obligation.deletion_request_id = deletion.deletion_request_id
                AND obligation.status = 'PENDING'
                AND backup.status = 'ACTIVE'
            );
          GET DIAGNOSTICS v_completed = ROW_COUNT;
          RETURN jsonb_build_object(
            'backup_id', p_backup_id,
            'status', 'EXPIRED',
            'obligations_completed', v_obligations,
            'deletion_requests_completed', v_completed
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.rebuild_search_projection(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_projection_name text,
          p_confirmation text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_documents integer := 0;
          v_deliveries integer := 0;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_projection_name NOT IN ('fts', 'vector')
             OR p_confirmation <> 'REBUILD_DERIVED_PROJECTION' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROJECTION_REBUILD_NOT_AUTHORIZED';
          END IF;
          IF p_projection_name = 'fts' THEN
            DELETE FROM milai.search_document WHERE tenant_id = p_tenant_id;
          ELSE
            DELETE FROM milai.search_embedding WHERE tenant_id = p_tenant_id;
          END IF;
          GET DIAGNOSTICS v_documents = ROW_COUNT;
          DELETE FROM milai.projection_delivery
          WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name;
          GET DIAGNOSTICS v_deliveries = ROW_COUNT;
          DELETE FROM milai.index_watermark
          WHERE tenant_id = p_tenant_id AND projection_name = p_projection_name;
          RETURN jsonb_build_object(
            'projection_name', p_projection_name,
            'derived_rows_removed', v_documents,
            'delivery_rows_removed', v_deliveries,
            'watermark', 0
          );
        END
        $$
        """
    )

    tables = "milai.backup_manifest, milai.backup_deletion_obligation"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(f"GRANT SELECT ON TABLE {tables} TO milai_steward, milai_audit")
    for signature, name, roles in (
        (RECORD_SIGNATURE, "record_backup_manifest", "milai_audit"),
        (EXPIRE_SIGNATURE, "expire_backup_manifest", "milai_audit"),
        (REBUILD_SIGNATURE, "rebuild_search_projection", "milai_steward"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO {roles}")
    op.execute("REVOKE ALL ON FUNCTION milai.attach_backup_deletion_obligations() FROM PUBLIC")


def downgrade() -> None:
    for signature, name in (
        (REBUILD_SIGNATURE, "rebuild_search_projection"),
        (EXPIRE_SIGNATURE, "expire_backup_manifest"),
        (RECORD_SIGNATURE, "record_backup_manifest"),
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.execute("DROP FUNCTION milai.attach_backup_deletion_obligations() CASCADE")
    op.drop_index(
        "ix_backup_obligation_pending",
        table_name="backup_deletion_obligation",
        schema="milai",
    )
    op.drop_table("backup_deletion_obligation", schema="milai")
    op.drop_table("backup_manifest", schema="milai")
