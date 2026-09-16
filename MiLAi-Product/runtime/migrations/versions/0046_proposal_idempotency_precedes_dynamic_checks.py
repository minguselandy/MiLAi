"""Replay completed proposal submissions before dynamic head checks.

Revision ID: 0046_proposal_idempotency
Revises: 0045_dg18_adjacency

An exact idempotent replay is a lookup of an already accepted request.  The
previous procedure checked the mutable Claim head and Evidence state first,
which could turn a successful request into VERSION_CONFLICT after its review
advanced the head.  A narrow wrapper now returns completed matching records
before delegating new requests to the unchanged validation/CAS procedure.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_proposal_idempotency"
down_revision: str | None = "0045_dg18_adjacency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_SIGNATURE = (
    "uuid, uuid, text, text, uuid, text, uuid, jsonb, uuid[], uuid[], "
    "jsonb, text, text, text, text, jsonb"
)


def upgrade() -> None:
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "FROM milai_api"
    )
    op.execute(
        f"ALTER FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "RENAME TO create_operation_proposal_after_idempotency"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.create_operation_proposal_after_idempotency({CREATE_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        """
        CREATE FUNCTION milai.create_operation_proposal(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_idempotency_key text,
          p_request_fingerprint text,
          p_target_claim_id uuid,
          p_operation text,
          p_expected_version_id uuid,
          p_proposed_patch jsonb,
          p_supporting_evidence_refs uuid[],
          p_contradicting_evidence_refs uuid[],
          p_scope_predicate jsonb,
          p_requested_authority text,
          p_derivation_policy_id text,
          p_model_id text,
          p_template_id text,
          p_derivation_snapshot jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_idempotency milai.idempotency_record%ROWTYPE;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'CREATE_PROPOSAL'
            AND idempotency_key = p_idempotency_key
          FOR UPDATE;
          IF FOUND THEN
            IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
            END IF;
            IF v_idempotency.response_payload IS NOT NULL THEN
              RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
            END IF;
          END IF;
          RETURN milai.create_operation_proposal_after_idempotency(
            p_tenant_id, p_actor_id, p_idempotency_key, p_request_fingerprint,
            p_target_claim_id, p_operation, p_expected_version_id,
            p_proposed_patch, p_supporting_evidence_refs,
            p_contradicting_evidence_refs, p_scope_predicate,
            p_requested_authority, p_derivation_policy_id, p_model_id,
            p_template_id, p_derivation_snapshot
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    op.execute(
        f"DROP FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE})"
    )
    op.execute(
        f"ALTER FUNCTION "
        f"milai.create_operation_proposal_after_idempotency({CREATE_SIGNATURE}) "
        "RENAME TO create_operation_proposal"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "TO milai_api"
    )
