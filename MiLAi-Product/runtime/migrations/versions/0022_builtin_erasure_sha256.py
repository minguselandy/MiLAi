"""Repair applied erasure functions to use PostgreSQL's built-in SHA-256.

Revision ID: 0022_builtin_erasure_sha256
Revises: 0021_gate_consumers
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_builtin_erasure_sha256"
down_revision: str | None = "0021_gate_consumers"
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
          IF strpos(v_definition, 'sha256(convert_to') = 0 THEN
            IF strpos(v_definition, 'public.digest(convert_to') > 0 THEN
              v_definition := replace(
                v_definition,
                'public.digest(convert_to',
                'sha256(convert_to'
              );
            ELSIF strpos(v_definition, 'digest(convert_to') > 0 THEN
              v_definition := replace(
                v_definition,
                'digest(convert_to',
                'sha256(convert_to'
              );
            ELSE
              RAISE EXCEPTION 'ERASURE_DIGEST_CALL_NOT_FOUND';
            END IF;
            v_definition := replace(
              v_definition,
              '), ''sha256'')',
              '))'
            );
            EXECUTE v_definition;
          END IF;
        END
        $migration$
        """
    )


def downgrade() -> None:
    raise RuntimeError("0022 downgrade is intentionally unsupported for erasure history")
