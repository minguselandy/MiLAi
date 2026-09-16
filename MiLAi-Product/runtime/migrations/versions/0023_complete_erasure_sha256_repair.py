"""Complete compatibility repair for the second erasure SHA-256 call.

Revision ID: 0023_erasure_sha256_repair
Revises: 0022_builtin_erasure_sha256
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_erasure_sha256_repair"
down_revision: str | None = "0022_builtin_erasure_sha256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        DO $migration$
        DECLARE
          v_definition text;
        BEGIN
          v_definition := pg_get_functiondef(
            'milai.complete_blob_erasure(uuid,uuid,uuid,text,text,text,text,text)'
            ::regprocedure
          );
          IF strpos(v_definition, '), ''sha256'')') > 0 THEN
            EXECUTE replace(v_definition, '), ''sha256'')', '))');
          END IF;
        END
        $migration$
        """
    )


def downgrade() -> None:
    raise RuntimeError("0023 downgrade is intentionally unsupported for erasure history")
