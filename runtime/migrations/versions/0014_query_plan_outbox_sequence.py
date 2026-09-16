"""Name QueryPlan read-your-writes ordering after the outbox sequence.

Revision ID: 0014_query_plan_outbox_sequence
Revises: 0013_live_confirmation_gate

Schema 0.1.x EXPERIMENTAL.
Implementation CANDIDATE.
NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_query_plan_outbox_sequence"
down_revision: str | None = "0013_live_confirmation_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _query_plan_constraint(field: str, rejected_field: str) -> str:
    return f"""
      jsonb_typeof(query_plan) = 'object'
      AND query_plan ? 'planner_version'
      AND query_plan ? 'routes'
      AND query_plan ? '{field}'
      AND NOT query_plan ? '{rejected_field}'
      AND CASE jsonb_typeof(query_plan -> '{field}')
            WHEN 'null' THEN true
            WHEN 'number' THEN (query_plan ->> '{field}')::numeric >= 0
            ELSE false
          END
    """


def _replace_sequence_field(old_field: str, new_field: str) -> None:
    op.execute("DROP TRIGGER trg_retrieval_trace_append_only ON milai.retrieval_trace")
    op.drop_constraint(
        "ck_retrieval_trace_query_plan",
        "retrieval_trace",
        schema="milai",
        type_="check",
    )
    op.get_bind().execute(
        sa.text(
            """
        UPDATE milai.retrieval_trace
        SET query_plan = jsonb_set(
          query_plan - CAST(:old_field AS text),
          ARRAY[CAST(:new_field AS text)],
          COALESCE(query_plan -> CAST(:old_field AS text), 'null'::jsonb),
          true
        )
        """
        ),
        {"old_field": old_field, "new_field": new_field},
    )
    op.create_check_constraint(
        "ck_retrieval_trace_query_plan",
        "retrieval_trace",
        _query_plan_constraint(new_field, old_field),
        schema="milai",
    )
    op.execute(
        """
        CREATE TRIGGER trg_retrieval_trace_append_only
        BEFORE UPDATE OR DELETE ON milai.retrieval_trace
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )


def upgrade() -> None:
    # canonical_commit_seq orders governed Claim/OpenIssue changes. Projection
    # visibility is ordered by the independent, gap-checked outbox_sequence.
    _replace_sequence_field("minimum_commit_seq", "minimum_outbox_sequence")


def downgrade() -> None:
    _replace_sequence_field("minimum_outbox_sequence", "minimum_commit_seq")
