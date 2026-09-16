"""Bind search projections to an explicit embedding-space identity.

Revision ID: 0027_embedding_identity
Revises: 0026_legacy_tx05_time_guard
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0027_embedding_identity"
down_revision = "0026_legacy_tx05_time_guard"
branch_labels = None
depends_on = None

_SIGNATURE = "milai.apply_search_projection(uuid,uuid,text,uuid,text,double precision[])"
_OLD = "'deterministic-hash-v1', '1',"
_NEW = """COALESCE(NULLIF(current_setting('milai.embedding_model_id', true), ''),
              'deterministic-hash-v1'),
              COALESCE(NULLIF(current_setting('milai.embedding_projection_version', true), ''),
              '1'),"""
_DETERMINISTIC_IDENTITY = "5b479a7b70c0aefb5fcdf20b256621ff8c663626f30b586c25b25f7bccce1598"


def upgrade() -> None:
    connection = op.get_bind()
    definition = connection.execute(
        text("SELECT pg_get_functiondef(CAST(:signature AS regprocedure))"),
        {"signature": _SIGNATURE},
    ).scalar_one()
    if not isinstance(definition, str) or definition.count(_OLD) != 1:
        raise RuntimeError("0027 cannot certify the search projection function definition")
    connection.execute(text(definition.replace(_OLD, _NEW)))
    connection.execute(
        text(
            "UPDATE milai.search_embedding SET projection_version = :identity "
            "WHERE model_id = 'deterministic-hash-v1' AND projection_version = '1'"
        ),
        {"identity": _DETERMINISTIC_IDENTITY},
    )


def downgrade() -> None:
    raise RuntimeError(
        "0027 downgrade is intentionally unsupported; restore a verified pre-0027 backup"
    )
