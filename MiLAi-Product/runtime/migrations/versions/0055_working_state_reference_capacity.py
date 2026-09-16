"""Increase bounded working-state provenance capacity without dropping references.

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from alembic import op

revision = "0055_working_state_ref_capacity"
down_revision = "0054_intra_source_shadow"
branch_labels = None
depends_on = None


def _capacity(previous: int, following: int) -> None:
    # Replace only this resource guard; retain the installed function's security,
    # per-reference checks, transaction behavior, owner and existing grants.
    op.execute(f"""
        DO $migration$
        DECLARE
          definition text;
          old_guard text := 'COALESCE(cardinality(p_evidence_refs), 0) > {previous}';
          new_guard text := 'COALESCE(cardinality(p_evidence_refs), 0) > {following}';
        BEGIN
          SELECT pg_get_functiondef(
            'milai.update_host_cognitive_state(uuid,uuid,uuid,integer,text,text,text,text,jsonb,text,uuid[],text,text)'::regprocedure
          ) INTO definition;
          IF (length(definition) - length(replace(definition, old_guard, '')))
              / length(old_guard) <> 1 THEN
            RAISE EXCEPTION 'Unexpected working-state reference capacity guard';
          END IF;
          EXECUTE replace(definition, old_guard, new_guard);
        END $migration$;
    """)


def upgrade() -> None:
    _capacity(256, 1024)


def downgrade() -> None:
    # Existing versions and reads survive. New writes above 256 are rejected.
    _capacity(1024, 256)
