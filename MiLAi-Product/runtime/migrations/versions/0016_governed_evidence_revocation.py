"""Put TX-05 evidence revocation behind an auditable Steward decision.

Revision ID: 0016_governed_revocation
Revises: 0015_governed_history
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_governed_revocation"
down_revision: str | None = "0015_governed_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TX05_SIGNATURE = "uuid, uuid, uuid, text, text, text, text"


def upgrade() -> None:
    op.drop_constraint(
        "ck_operation_proposal_operation",
        "operation_proposal",
        schema="milai",
        type_="check",
    )
    op.create_check_constraint(
        "ck_operation_proposal_operation",
        "operation_proposal",
        "operation IN ('CREATE', 'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND', "
        "'SUPERSEDE', 'CONTEXTUALIZE', 'CONTRADICT', 'NO_CHANGE', 'SPLIT', "
        "'REVOKE_EVIDENCE')",
        schema="milai",
    )
    op.add_column(
        "steward_decision",
        sa.Column("resulting_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="milai",
    )
    op.create_foreign_key(
        "fk_decision_result_evidence",
        "steward_decision",
        "evidence_record",
        ["tenant_id", "resulting_evidence_id"],
        ["tenant_id", "evidence_id"],
        source_schema="milai",
        referent_schema="milai",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        """
        CREATE FUNCTION milai.link_tx05_governance()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_proposal_id uuid;
          v_decision_id uuid;
        BEGIN
          BEGIN
            v_proposal_id := NULLIF(
              current_setting('milai.tx05_proposal_id', true), ''
            )::uuid;
            v_decision_id := NULLIF(
              current_setting('milai.tx05_decision_id', true), ''
            )::uuid;
          EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TX05_CONTEXT';
          END;
          IF v_proposal_id IS NULL OR v_decision_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'UNGOVERNED_TX05_MUTATION';
          END IF;
          NEW.proposal_id := v_proposal_id;
          NEW.decision_id := v_decision_id;
          NEW.policy_version := 'tx05-revocation-policy-v2';
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tx05_issue_transition_governance
        BEFORE INSERT ON milai.open_issue_transition
        FOR EACH ROW
        WHEN (NEW.event_type IN (
          'RESOLUTION_EVIDENCE_REVOKED', 'ISSUE_EVIDENCE_REVOKED'
        ))
        EXECUTE FUNCTION milai.link_tx05_governance()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.annotate_tx05_event()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_proposal_id uuid;
          v_decision_id uuid;
        BEGIN
          BEGIN
            v_proposal_id := NULLIF(
              current_setting('milai.tx05_proposal_id', true), ''
            )::uuid;
            v_decision_id := NULLIF(
              current_setting('milai.tx05_decision_id', true), ''
            )::uuid;
          EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TX05_CONTEXT';
          END;
          IF v_proposal_id IS NULL OR v_decision_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'UNGOVERNED_TX05_MUTATION';
          END IF;
          IF TG_TABLE_NAME = 'outbox_event' THEN
            NEW.payload := NEW.payload || jsonb_build_object(
              'proposal_id', v_proposal_id, 'decision_id', v_decision_id
            );
          ELSE
            NEW.safe_metadata := COALESCE(NEW.safe_metadata, '{}'::jsonb)
              || jsonb_build_object(
                'proposal_id', v_proposal_id, 'decision_id', v_decision_id
              );
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tx05_outbox_governance
        BEFORE INSERT ON milai.outbox_event
        FOR EACH ROW
        WHEN (NEW.event_type IN ('EVIDENCE_REVOKED', 'PURGE_EVIDENCE_DERIVATIVES'))
        EXECUTE FUNCTION milai.annotate_tx05_event()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tx05_operational_governance
        BEFORE INSERT ON milai.operational_event
        FOR EACH ROW
        WHEN (NEW.event_type = 'EVIDENCE_REVOKED')
        EXECUTE FUNCTION milai.annotate_tx05_event()
        """
    )

    op.execute(
        f"ALTER FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE}) "
        "RENAME TO tx05_revoke_evidence_legacy"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.tx05_revoke_evidence_legacy({TX05_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    _create_tx05_function()


def _create_tx05_function() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.tx05_revoke_evidence(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_evidence_id uuid,
          p_reason_code text,
          p_confirmation text,
          p_idempotency_key text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_proposal milai.operation_proposal%ROWTYPE;
          v_proposal_id uuid;
          v_decision_id uuid;
          v_result jsonb;
          v_commit_seq bigint;
          v_governance_key text;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_confirmation <> 'REVOKE'
             OR length(btrim(p_reason_code)) = 0
             OR length(p_reason_code) > 255 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'REVOCATION_NOT_AUTHORIZED';
          END IF;
          v_governance_key := 'tx05:' || p_idempotency_key;
          SELECT * INTO v_proposal
          FROM milai.operation_proposal
          WHERE tenant_id = p_tenant_id AND idempotency_key = v_governance_key
          FOR UPDATE;
          IF FOUND THEN
            IF v_proposal.request_fingerprint <> p_request_fingerprint
               OR v_proposal.operation <> 'REVOKE_EVIDENCE'
               OR (v_proposal.proposed_patch ->> 'evidence_id')::uuid
                  IS DISTINCT FROM p_evidence_id THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
            END IF;
            SELECT decision_id INTO STRICT v_decision_id
            FROM milai.steward_decision
            WHERE tenant_id = p_tenant_id AND proposal_id = v_proposal.proposal_id;
            PERFORM set_config(
              'milai.tx05_proposal_id', v_proposal.proposal_id::text, true
            );
            PERFORM set_config('milai.tx05_decision_id', v_decision_id::text, true);
            v_result := milai.tx05_revoke_evidence_legacy(
              p_tenant_id, p_actor_id, p_evidence_id, p_reason_code,
              p_confirmation, p_idempotency_key, p_request_fingerprint
            );
            RETURN v_result || jsonb_build_object(
              'proposal_id', v_proposal.proposal_id,
              'decision_id', v_decision_id,
              'replayed', true
            );
          END IF;

          v_proposal_id := gen_random_uuid();
          v_decision_id := gen_random_uuid();
          INSERT INTO milai.operation_proposal (
            tenant_id, proposal_id, target_claim_id, operation,
            expected_version_id, proposed_patch, supporting_evidence_refs,
            contradicting_evidence_refs, scope_predicate, requested_authority,
            derivation_policy_id, model_id, template_id, derivation_snapshot,
            proposer_actor_id, canonical_commit_authorized, status,
            idempotency_key, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_proposal_id, NULL, 'REVOKE_EVIDENCE', NULL,
            jsonb_build_object(
              'evidence_id', p_evidence_id,
              'reason_code', p_reason_code,
              'confirmation', 'REVOKE'
            ), '{}'::uuid[], '{}'::uuid[], '{}'::jsonb, 'USER_CONFIRMED',
            'tx05-revocation-policy-v2', NULL, NULL,
            jsonb_build_object('governance_path', 'TX-05'),
            p_actor_id, false, 'APPLIED', v_governance_key,
            p_request_fingerprint, p_actor_id
          );
          PERFORM set_config('milai.tx05_proposal_id', v_proposal_id::text, true);
          PERFORM set_config('milai.tx05_decision_id', v_decision_id::text, true);
          v_result := milai.tx05_revoke_evidence_legacy(
            p_tenant_id, p_actor_id, p_evidence_id, p_reason_code,
            p_confirmation, p_idempotency_key, p_request_fingerprint
          );
          BEGIN
            v_commit_seq := (v_result ->> 'canonical_commit_seq')::bigint;
          EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TX05_RESULT';
          END;
          IF v_commit_seq IS NULL THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_TX05_RESULT';
          END IF;
          INSERT INTO milai.steward_decision (
            tenant_id, decision_id, proposal_id, decision,
            decision_actor_type, decision_actor_id, policy_version,
            reason_code, resulting_evidence_id, canonical_commit_seq,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, v_decision_id, v_proposal_id, 'APPROVE',
            'STEWARD', p_actor_id, 'tx05-revocation-policy-v2',
            p_reason_code, p_evidence_id, v_commit_seq, p_actor_id
          );
          RETURN v_result || jsonb_build_object(
            'proposal_id', v_proposal_id,
            'decision_id', v_decision_id,
            'replayed', false
          );
        END
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE}) TO milai_steward"
    )


def downgrade() -> None:
    governed_count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM milai.operation_proposal WHERE operation = 'REVOKE_EVIDENCE'"
            )
        )
        .scalar_one()
    )
    if governed_count:
        raise RuntimeError("0016 downgrade is unsafe after governed revocation")
    op.execute(f"DROP FUNCTION milai.tx05_revoke_evidence({TX05_SIGNATURE})")
    op.execute(
        f"ALTER FUNCTION milai.tx05_revoke_evidence_legacy({TX05_SIGNATURE}) "
        "RENAME TO tx05_revoke_evidence"
    )
    op.execute("DROP TRIGGER trg_tx05_operational_governance ON milai.operational_event")
    op.execute("DROP TRIGGER trg_tx05_outbox_governance ON milai.outbox_event")
    op.execute("DROP FUNCTION milai.annotate_tx05_event()")
    op.execute("DROP TRIGGER trg_tx05_issue_transition_governance ON milai.open_issue_transition")
    op.execute("DROP FUNCTION milai.link_tx05_governance()")
    op.drop_constraint(
        "fk_decision_result_evidence",
        "steward_decision",
        schema="milai",
        type_="foreignkey",
    )
    op.drop_column("steward_decision", "resulting_evidence_id", schema="milai")
