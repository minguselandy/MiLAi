"""Route every context consumer through the axis-complete Gate and repair digest lookup.

Revision ID: 0021_gate_consumers
Revises: 0020_causal_position_api
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_gate_consumers"
down_revision: str | None = "0020_causal_position_api"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_trace_gate()
    _repair_context_capsule_gate_call()
    _qualify_erasure_digest()


def _create_trace_gate() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.evaluate_retrieval_trace_candidates(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_claim_version_ids uuid[],
          p_retrieval_trace_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_trace milai.retrieval_trace%ROWTYPE;
          v_lifecycle text;
          v_epistemic text[];
          v_freshness text;
          v_minimum_confidence numeric;
          v_system_as_of timestamptz;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_trace
          FROM milai.retrieval_trace trace
          WHERE trace.tenant_id = p_tenant_id
            AND trace.trace_id = p_retrieval_trace_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'RETRIEVAL_TRACE_NOT_FOUND';
          END IF;
          v_lifecycle := COALESCE(
            v_trace.query_plan ->> 'required_lifecycle', 'ACTIVE'
          );
          IF jsonb_typeof(
               v_trace.query_plan -> 'accepted_epistemic_statuses'
             ) = 'array' THEN
            SELECT array_agg(value ORDER BY ordinal)
            INTO v_epistemic
            FROM jsonb_array_elements_text(
              v_trace.query_plan -> 'accepted_epistemic_statuses'
            ) WITH ORDINALITY item(value, ordinal);
          ELSE
            v_epistemic := ARRAY['VERIFIED', 'PROVISIONAL']::text[];
          END IF;
          v_freshness := COALESCE(
            v_trace.query_plan ->> 'required_freshness', 'CURRENT'
          );
          v_minimum_confidence := COALESCE(
            NULLIF(v_trace.query_plan ->> 'minimum_confidence', '')::numeric,
            0
          );
          v_system_as_of := COALESCE(
            NULLIF(
              v_trace.query_plan #>> '{time_constraint,system_as_of}', ''
            )::timestamptz,
            v_trace.created_at
          );
          RETURN milai.evaluate_canonical_candidates(
            p_tenant_id,
            p_actor_id,
            p_claim_version_ids,
            v_trace.required_authority,
            v_trace.requested_scope,
            v_trace.as_of,
            v_lifecycle,
            v_epistemic,
            v_freshness,
            v_minimum_confidence,
            v_system_as_of
          );
        END
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "milai.evaluate_retrieval_trace_candidates(uuid, uuid, uuid[], uuid) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "milai.evaluate_retrieval_trace_candidates(uuid, uuid, uuid[], uuid) "
        "TO milai_api"
    )


def _repair_context_capsule_gate_call() -> None:
    op.execute(
        r"""
        DO $migration$
        DECLARE
          v_definition text;
          v_old text := $old$milai.evaluate_canonical_candidates(
            p_tenant_id, p_actor_id, v_claim_version_ids,
            v_trace.required_authority, v_trace.requested_scope, v_trace.as_of
          )$old$;
          v_new text := $new$milai.evaluate_retrieval_trace_candidates(
            p_tenant_id, p_actor_id, v_claim_version_ids,
            p_retrieval_trace_id
          )$new$;
        BEGIN
          v_definition := pg_get_functiondef(
            'milai.create_context_capsule(uuid,uuid,uuid,jsonb,integer,timestamptz)'
            ::regprocedure
          );
          IF strpos(v_definition, v_new) = 0 THEN
            IF strpos(v_definition, v_old) = 0 THEN
              RAISE EXCEPTION 'CREATE_CONTEXT_GATE_CALL_NOT_FOUND';
            END IF;
            EXECUTE replace(v_definition, v_old, v_new);
          END IF;
        END
        $migration$
        """
    )


def _qualify_erasure_digest() -> None:
    # An already-upgraded candidate.1 database may contain a pgcrypto-style
    # digest call. Fresh databases receive PostgreSQL 16's built-in sha256 form
    # directly from 0019.
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
    raise RuntimeError("0021 downgrade is intentionally unsupported for canonical history")
