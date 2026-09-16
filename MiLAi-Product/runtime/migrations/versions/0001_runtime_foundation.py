"""Create the experimental runtime foundation.

Revision ID: 0001_runtime_foundation
Revises: None

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_runtime_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS milai AUTHORIZATION CURRENT_USER")
    op.create_table(
        "runtime_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="milai",
    )
    op.execute(
        """
        INSERT INTO milai.runtime_metadata (key, value)
        VALUES
          ('schema_status', '0.1.x EXPERIMENTAL'),
          ('implementation_status', 'CANDIDATE'),
          ('schema_freeze', 'NO-GO FOR SCHEMA FREEZE')
        """
    )
    op.execute("GRANT USAGE ON SCHEMA milai TO milai_api, milai_steward, milai_worker, milai_audit")
    op.execute(
        "GRANT SELECT ON TABLE milai.runtime_metadata "
        "TO milai_api, milai_steward, milai_worker, milai_audit"
    )


def downgrade() -> None:
    op.drop_table("runtime_metadata", schema="milai")
    op.execute("DROP SCHEMA IF EXISTS milai")
    # The vector extension may be shared by other schemas and is intentionally retained.
