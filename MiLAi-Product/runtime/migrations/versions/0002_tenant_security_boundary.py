"""Create the tenant context and first RLS-protected runtime table.

Revision ID: 0002_tenant_security_boundary
Revises: 0001_runtime_foundation

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_tenant_security_boundary"
down_revision: str | None = "0001_runtime_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.current_tenant_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
          SELECT NULLIF(current_setting('milai.tenant_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.current_actor_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
          SELECT NULLIF(current_setting('milai.actor_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION milai.current_tenant_id() FROM PUBLIC; "
        "REVOKE ALL ON FUNCTION milai.current_actor_id() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION milai.current_tenant_id(), milai.current_actor_id() "
        "TO milai_api, milai_steward, milai_worker, milai_audit"
    )

    op.create_table(
        "operational_event",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name="pk_operational_event"),
        sa.CheckConstraint(
            "jsonb_typeof(safe_metadata) = 'object'",
            name="ck_operational_event_safe_metadata_object",
        ),
        schema="milai",
    )
    op.execute("ALTER TABLE milai.operational_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.operational_event FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY operational_event_tenant_isolation
        ON milai.operational_event
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (
          tenant_id = milai.current_tenant_id()
          AND created_by_actor_id = milai.current_actor_id()
        )
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE milai.operational_event "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT, INSERT ON TABLE milai.operational_event "
        "TO milai_api, milai_steward, milai_worker"
    )
    op.execute("GRANT SELECT ON TABLE milai.operational_event TO milai_audit")


def downgrade() -> None:
    op.drop_table("operational_event", schema="milai")
    op.execute("DROP FUNCTION milai.current_actor_id()")
    op.execute("DROP FUNCTION milai.current_tenant_id()")
