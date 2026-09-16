"""Enforce proposal reviewer actor separation at the canonical boundary.

Revision ID: 0032_reviewer_actor_separation
Revises: 0031_task_free_receipt

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
This migration adds no table. It wraps the canonical review procedure so every
caller, including privileged local compatibility credentials, is unable to
decide a proposal created by the same actor.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_reviewer_actor_separation"
down_revision: str | None = "0031_task_free_receipt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_SIGNATURE = "uuid, uuid, uuid, text, text, text, text, text, text"
PRE_SEPARATION_NAME = "review_operation_proposal_without_actor_separation"


def upgrade() -> None:
    op.execute(
        f"ALTER FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        f"RENAME TO {PRE_SEPARATION_NAME}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.{PRE_SEPARATION_NAME}({REVIEW_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        """
        CREATE FUNCTION milai.review_operation_proposal(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_proposal_id uuid,
          p_decision text,
          p_decision_actor_type text,
          p_policy_version text,
          p_reason_code text,
          p_idempotency_key text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_proposer_actor_id uuid;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT proposer_actor_id INTO v_proposer_actor_id
          FROM milai.operation_proposal
          WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROPOSAL_NOT_FOUND';
          END IF;
          IF v_proposer_actor_id = p_actor_id THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'SELF_REVIEW_FORBIDDEN';
          END IF;
          RETURN milai.review_operation_proposal_without_actor_separation(
            p_tenant_id, p_actor_id, p_proposal_id, p_decision,
            p_decision_actor_type, p_policy_version, p_reason_code,
            p_idempotency_key, p_request_fingerprint
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "TO milai_steward"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE})")
    op.execute(
        f"ALTER FUNCTION milai.{PRE_SEPARATION_NAME}({REVIEW_SIGNATURE}) "
        "RENAME TO review_operation_proposal"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "TO milai_steward"
    )
