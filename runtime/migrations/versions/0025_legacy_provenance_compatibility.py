"""Guard rejected candidate.3 provenance and reconcile its deployed state.

Revision ID: 0025_legacy_provenance_guard
Revises: 0024_legacy_history_reconcile

Candidate.4 corrects the unaccepted 0024 migration so a fresh populated chain
fails inside 0024 and rolls back to 0023.  This additional forward revision is
the compatibility path for development databases that already ran the exact
candidate.3 version of 0024: it re-proves the durable TX-05 DeletionRequest and
moves rejected pre-Decision grounding into the same immutable audit ledger.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_legacy_provenance_guard"
down_revision: str | None = "0024_legacy_history_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_grounding_quarantine_ledger_if_missing()
    _lock_sources()
    _prove_legacy_tx05_source()
    _prove_reconciliation_source()
    _reconcile_rejected_grounding()
    _enforce_postconditions()


def _create_grounding_quarantine_ledger_if_missing() -> None:
    connection = op.get_bind()
    exists = connection.execute(
        sa.text("SELECT to_regclass('milai.legacy_grounding_relation_quarantine')")
    ).scalar_one()
    if exists is not None:
        return

    op.create_table(
        "legacy_grounding_relation_quarantine",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_relation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("open_issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_relation_type", sa.Text(), nullable=False),
        sa.Column("created_from_proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_row_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "quarantined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "migration_revision",
            sa.Text(),
            nullable=False,
            server_default="0025_legacy_provenance_guard",
        ),
        sa.Column(
            "quarantine_reason",
            sa.Text(),
            nullable=False,
            server_default="REJECTED_PREDECISION_RESOLUTION_GROUNDING",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "original_relation_id",
            name="pk_legacy_grounding_relation_quarantine",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "open_issue_id"],
            ["milai.open_issue.tenant_id", "milai.open_issue.issue_id"],
            name="fk_legacy_grounding_quarantine_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_legacy_grounding_quarantine_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_from_proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_legacy_grounding_quarantine_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reconciliation_decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_legacy_grounding_quarantine_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "original_transition_id"],
            [
                "milai.legacy_issue_transition_quarantine.tenant_id",
                "milai.legacy_issue_transition_quarantine.original_transition_id",
            ],
            name="fk_legacy_grounding_quarantine_transition",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "claim_version_id IS NULL AND open_issue_id IS NOT NULL",
            name="ck_legacy_grounding_issue_owner",
        ),
        sa.CheckConstraint(
            "original_relation_type = 'RESOLUTION_CANDIDATE'",
            name="ck_legacy_grounding_relation_type",
        ),
        sa.CheckConstraint(
            "length(original_row_sha256) = 64",
            name="ck_legacy_grounding_sha256",
        ),
        sa.CheckConstraint(
            "migration_revision = '0025_legacy_provenance_guard'",
            name="ck_legacy_grounding_migration",
        ),
        schema="milai",
    )
    op.execute(
        "ALTER TABLE milai.legacy_grounding_relation_quarantine ENABLE ROW LEVEL SECURITY; "
        "ALTER TABLE milai.legacy_grounding_relation_quarantine FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY legacy_grounding_relation_quarantine_tenant_isolation
        ON milai.legacy_grounding_relation_quarantine
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )
    op.execute(
        "CREATE TRIGGER trg_legacy_grounding_relation_quarantine_append_only "
        "BEFORE UPDATE OR DELETE ON milai.legacy_grounding_relation_quarantine "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )
    op.execute(
        "REVOKE ALL ON TABLE milai.legacy_grounding_relation_quarantine "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.legacy_grounding_relation_quarantine "
        "TO milai_steward, milai_audit"
    )
    op.execute(
        "COMMENT ON TABLE milai.legacy_grounding_relation_quarantine IS "
        "'Exact immutable evidence of rejected candidate.1 pre-Decision grounding; not canonical'"
    )


def _lock_sources() -> None:
    op.execute(
        """
        LOCK TABLE
          milai.content_blob,
          milai.evidence_record,
          milai.deletion_request,
          milai.idempotency_record,
          milai.grounding_relation,
          milai.operation_proposal,
          milai.steward_decision,
          milai.open_issue,
          milai.open_issue_transition,
          milai.legacy_issue_transition_quarantine,
          milai.legacy_grounding_relation_quarantine,
          milai.operational_event,
          milai.outbox_event
        IN ACCESS EXCLUSIVE MODE
        """
    )


def _prove_legacy_tx05_source() -> None:
    op.execute(
        """
        DO $tx05_source_proof$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM milai.outbox_event revoke_event
            WHERE revoke_event.event_type = 'EVIDENCE_REVOKED'
              AND NOT (
                revoke_event.payload ? 'proposal_id'
                AND revoke_event.payload ? 'decision_id'
              )
              AND NOT EXISTS (
                SELECT 1
                FROM milai.evidence_record evidence
                JOIN milai.deletion_request deletion
                  ON deletion.tenant_id = evidence.tenant_id
                 AND deletion.evidence_id = evidence.evidence_id
                 AND deletion.blob_id = evidence.blob_id
                 AND deletion.deletion_request_id::text =
                     revoke_event.payload ->> 'deletion_request_id'
                 AND deletion.requested_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND deletion.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND deletion.requested_at = evidence.revoked_at
                 AND deletion.logical_revocation_status = 'APPLIED'
                 AND deletion.canonical_block_status = 'APPLIED'
                 AND deletion.derived_purge_status IN (
                   'PENDING', 'PROCESSING', 'COMPLETED', 'DEAD_LETTER'
                 )
                 AND deletion.primary_bytes_status IN (
                   'PENDING', 'BLOCKED_SHARED_REFERENCE', 'RETENTION_BLOCKED',
                   'ERASED', 'ERROR'
                 )
                 AND deletion.backup_expiry_status IN (
                   'PENDING', 'RETENTION_BLOCKED', 'COMPLETED'
                 )
                 AND deletion.retention_status IN (
                   'CLEAR', 'LEGAL_HOLD', 'UNREADABLE'
                 )
                JOIN milai.idempotency_record idempotency
                  ON idempotency.tenant_id = evidence.tenant_id
                 AND idempotency.operation_family = 'TX-05_EVIDENCE_REVOKE'
                 AND idempotency.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND idempotency.created_at = deletion.requested_at
                 AND idempotency.response_payload ->> 'canonical_commit_seq' =
                     revoke_event.canonical_commit_seq::text
                 AND idempotency.response_payload ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND idempotency.response_payload ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND idempotency.response_payload ->> 'logical_revocation_status' =
                     'APPLIED'
                 AND idempotency.response_payload ->> 'canonical_block_status' =
                     'APPLIED'
                 AND idempotency.response_payload ->> 'derived_purge_status' =
                     'PENDING'
                 AND idempotency.response_payload ->> 'grounding_blocks_created' =
                     deletion.grounding_blocks_created::text
                 AND idempotency.response_payload ->> 'context_pointers_invalidated' =
                     deletion.context_pointers_invalidated::text
                 AND idempotency.response_payload ->> 'shared_live_reference_count' =
                     deletion.shared_live_reference_count::text
                 AND idempotency.response_payload ->> 'revoke_outbox_id' =
                     revoke_event.outbox_id::text
                JOIN milai.operational_event operational
                  ON operational.tenant_id = evidence.tenant_id
                 AND operational.event_type = 'EVIDENCE_REVOKED'
                 AND operational.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND operational.created_at = deletion.requested_at
                 AND operational.reason_code = deletion.reason_code
                 AND operational.safe_metadata ->> 'canonical_commit_seq' =
                     revoke_event.canonical_commit_seq::text
                 AND operational.safe_metadata ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND operational.safe_metadata ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND operational.safe_metadata ->> 'grounding_blocks_created' =
                     deletion.grounding_blocks_created::text
                 AND operational.safe_metadata ->> 'context_pointers_invalidated' =
                     deletion.context_pointers_invalidated::text
                 AND operational.safe_metadata ->> 'shared_live_reference_count' =
                     deletion.shared_live_reference_count::text
                JOIN milai.outbox_event purge_event
                  ON purge_event.tenant_id = evidence.tenant_id
                 AND purge_event.aggregate_type = 'DELETION_REQUEST'
                 AND purge_event.aggregate_id = deletion.deletion_request_id
                 AND purge_event.event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                 AND purge_event.canonical_commit_seq =
                     revoke_event.canonical_commit_seq
                 AND purge_event.created_by_actor_id =
                     revoke_event.created_by_actor_id
                 AND purge_event.created_at = deletion.requested_at
                 AND purge_event.payload ->> 'deletion_request_id' =
                     deletion.deletion_request_id::text
                 AND purge_event.payload ->> 'evidence_id' =
                     evidence.evidence_id::text
                 AND purge_event.payload ->> 'blob_id' = deletion.blob_id::text
                 AND purge_event.payload ->> 'primary_bytes_status' =
                     idempotency.response_payload ->> 'primary_bytes_status'
                 AND purge_event.payload ->> 'retention_status' =
                     idempotency.response_payload ->> 'retention_status'
                 AND idempotency.response_payload ->> 'purge_outbox_id' =
                     purge_event.outbox_id::text
                WHERE evidence.tenant_id = revoke_event.tenant_id
                  AND evidence.evidence_id::text =
                      revoke_event.payload ->> 'evidence_id'
                  AND revoke_event.aggregate_type = 'EVIDENCE'
                  AND revoke_event.aggregate_id = evidence.evidence_id
                  AND revoke_event.created_at = deletion.requested_at
                  AND revoke_event.payload ->> 'deletion_request_id' IS NOT NULL
                  AND evidence.revoked_at IS NOT NULL
                  AND evidence.revocation_reason = deletion.reason_code
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_UNPROVABLE_LEGACY_TX05';
          END IF;
        END
        $tx05_source_proof$
        """
    )


def _prove_reconciliation_source() -> None:
    op.execute(
        """
        DO $grounding_source_proof$
        BEGIN
          -- Every rejected candidate.1 relation must exist exactly once in
          -- either canonical grounding (old candidate.3) or quarantine
          -- (corrected 0024), and must equal an actual Proposal support ref.
          IF EXISTS (
            SELECT 1
            FROM milai.legacy_issue_transition_quarantine quarantine
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = quarantine.tenant_id
             AND proposal.proposal_id = quarantine.proposal_id
            JOIN milai.steward_decision decision
              ON decision.tenant_id = quarantine.tenant_id
             AND decision.decision_id = quarantine.reconciliation_decision_id
            WHERE quarantine.original_event_type =
                  'RESOLUTION_EVIDENCE_PROPOSED'
              AND decision.decision = 'REJECT'
              AND (
                proposal.status <> 'REJECTED'
                OR decision.resulting_open_issue_id IS DISTINCT FROM
                   quarantine.issue_id
                OR EXISTS (
                  SELECT 1
                  FROM unnest(proposal.supporting_evidence_refs) support(evidence_id)
                  WHERE (
                    SELECT count(*)
                    FROM (
                      SELECT relation.evidence_id
                      FROM milai.grounding_relation relation
                      WHERE relation.tenant_id = quarantine.tenant_id
                        AND relation.open_issue_id = quarantine.issue_id
                        AND relation.created_from_proposal_id = proposal.proposal_id
                        AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                        AND relation.evidence_id = support.evidence_id
                      UNION ALL
                      SELECT ledger.evidence_id
                      FROM milai.legacy_grounding_relation_quarantine ledger
                      WHERE ledger.tenant_id = quarantine.tenant_id
                        AND ledger.open_issue_id = quarantine.issue_id
                        AND ledger.created_from_proposal_id = proposal.proposal_id
                        AND ledger.original_transition_id =
                            quarantine.original_transition_id
                        AND ledger.original_relation_type = 'RESOLUTION_CANDIDATE'
                        AND ledger.evidence_id = support.evidence_id
                    ) exact_source
                  ) <> 1
                )
                OR EXISTS (
                  SELECT 1
                  FROM milai.grounding_relation relation
                  WHERE relation.tenant_id = quarantine.tenant_id
                    AND relation.open_issue_id = quarantine.issue_id
                    AND relation.created_from_proposal_id = proposal.proposal_id
                    AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                    AND NOT COALESCE(
                      relation.evidence_id = ANY(proposal.supporting_evidence_refs),
                      false
                    )
                )
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_LEGACY_RESOLUTION_GROUNDING';
          END IF;

          -- An already-approved candidate.1 resolution remains canonical and
          -- must still be justified by that exact Decision and support set.
          IF EXISTS (
            SELECT 1
            FROM milai.legacy_issue_transition_quarantine quarantine
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = quarantine.tenant_id
             AND proposal.proposal_id = quarantine.proposal_id
            JOIN milai.steward_decision decision
              ON decision.tenant_id = quarantine.tenant_id
             AND decision.decision_id = quarantine.reconciliation_decision_id
            WHERE quarantine.original_event_type =
                  'RESOLUTION_EVIDENCE_PROPOSED'
              AND decision.decision = 'APPROVE'
              AND (
                proposal.status <> 'APPLIED'
                OR decision.resulting_open_issue_id IS DISTINCT FROM
                   quarantine.issue_id
                OR EXISTS (
                  SELECT 1
                  FROM unnest(proposal.supporting_evidence_refs) support(evidence_id)
                  WHERE (
                    SELECT count(*)
                    FROM milai.grounding_relation relation
                    WHERE relation.tenant_id = quarantine.tenant_id
                      AND relation.open_issue_id = quarantine.issue_id
                      AND relation.created_from_proposal_id = proposal.proposal_id
                      AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                      AND relation.evidence_id = support.evidence_id
                  ) <> 1
                )
                OR EXISTS (
                  SELECT 1
                  FROM milai.legacy_grounding_relation_quarantine ledger
                  WHERE ledger.tenant_id = quarantine.tenant_id
                    AND ledger.original_transition_id =
                        quarantine.original_transition_id
                )
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_APPROVED_RESOLUTION_GROUNDING';
          END IF;
        END
        $grounding_source_proof$
        """
    )


def _reconcile_rejected_grounding() -> None:
    op.execute("DROP TRIGGER trg_grounding_relation_append_only ON milai.grounding_relation")
    op.execute(
        """
        DO $grounding_reconcile$
        DECLARE
          legacy record;
          v_row_hash text;
          v_rows integer;
        BEGIN
          FOR legacy IN
            SELECT relation.*,
                   quarantine.original_transition_id,
                   decision.decision_id AS reconciliation_decision_id,
                   decision.canonical_commit_seq,
                   decision.decision_actor_id
            FROM milai.grounding_relation relation
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = relation.tenant_id
             AND proposal.proposal_id = relation.created_from_proposal_id
            JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
             AND decision.decision = 'REJECT'
            JOIN milai.legacy_issue_transition_quarantine quarantine
              ON quarantine.tenant_id = relation.tenant_id
             AND quarantine.issue_id = relation.open_issue_id
             AND quarantine.proposal_id = relation.created_from_proposal_id
             AND quarantine.original_event_type =
                 'RESOLUTION_EVIDENCE_PROPOSED'
             AND quarantine.reconciliation_decision_id = decision.decision_id
            WHERE relation.relation_type = 'RESOLUTION_CANDIDATE'
              AND relation.claim_version_id IS NULL
              AND relation.evidence_id = ANY(proposal.supporting_evidence_refs)
            ORDER BY relation.tenant_id, relation.open_issue_id,
                     relation.relation_id
          LOOP
            v_row_hash := encode(sha256(convert_to(jsonb_build_object(
              'tenant_id', legacy.tenant_id,
              'relation_id', legacy.relation_id,
              'claim_version_id', legacy.claim_version_id,
              'open_issue_id', legacy.open_issue_id,
              'evidence_id', legacy.evidence_id,
              'relation_type', legacy.relation_type,
              'created_from_proposal_id', legacy.created_from_proposal_id,
              'created_at', legacy.created_at,
              'created_by_actor_id', legacy.created_by_actor_id
            )::text, 'UTF8')), 'hex');
            INSERT INTO milai.legacy_grounding_relation_quarantine (
              tenant_id, original_relation_id, claim_version_id,
              open_issue_id, evidence_id, original_relation_type,
              created_from_proposal_id, original_created_at,
              original_created_by_actor_id, original_transition_id,
              reconciliation_decision_id, original_row_sha256
            ) VALUES (
              legacy.tenant_id, legacy.relation_id, legacy.claim_version_id,
              legacy.open_issue_id, legacy.evidence_id, legacy.relation_type,
              legacy.created_from_proposal_id, legacy.created_at,
              legacy.created_by_actor_id, legacy.original_transition_id,
              legacy.reconciliation_decision_id, v_row_hash
            );
            DELETE FROM milai.grounding_relation
            WHERE tenant_id = legacy.tenant_id
              AND relation_id = legacy.relation_id;
            GET DIAGNOSTICS v_rows = ROW_COUNT;
            IF v_rows <> 1 THEN
              RAISE EXCEPTION USING
                ERRCODE = 'P0001',
                MESSAGE = 'AF09_GROUNDING_QUARANTINE_MOVE_FAILED';
            END IF;
            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              legacy.tenant_id, gen_random_uuid(),
              'LEGACY_RESOLUTION_GROUNDING_QUARANTINED',
              'REJECTED_PREDECISION_RESOLUTION_GROUNDING',
              jsonb_build_object(
                'issue_id', legacy.open_issue_id,
                'proposal_id', legacy.created_from_proposal_id,
                'decision_id', legacy.reconciliation_decision_id,
                'original_relation_id', legacy.relation_id,
                'original_transition_id', legacy.original_transition_id,
                'original_row_sha256', v_row_hash,
                'canonical_commit_seq', legacy.canonical_commit_seq
              ), legacy.decision_actor_id
            );
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              legacy.tenant_id, gen_random_uuid(), 'OPEN_ISSUE',
              legacy.open_issue_id,
              'OPEN_ISSUE_LEGACY_GROUNDING_QUARANTINED',
              jsonb_build_object(
                'issue_id', legacy.open_issue_id,
                'proposal_id', legacy.created_from_proposal_id,
                'decision_id', legacy.reconciliation_decision_id,
                'original_relation_id', legacy.relation_id,
                'original_transition_id', legacy.original_transition_id,
                'original_row_sha256', v_row_hash
              ), 20, legacy.canonical_commit_seq, legacy.decision_actor_id
            );
          END LOOP;
        END
        $grounding_reconcile$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_grounding_relation_append_only "
        "BEFORE UPDATE OR DELETE ON milai.grounding_relation "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )


def _enforce_postconditions() -> None:
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute(
        """
        DO $postconditions$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            LEFT JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = relation.tenant_id
             AND proposal.proposal_id = relation.created_from_proposal_id
            LEFT JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE relation.relation_type = 'RESOLUTION_CANDIDATE'
              AND (
                relation.claim_version_id IS NOT NULL
                OR relation.open_issue_id IS NULL
                OR proposal.proposal_id IS NULL
                OR proposal.operation <> 'SUPERSEDE'
                OR proposal.status <> 'APPLIED'
                OR proposal.proposed_patch ->> 'resolve_issue_id' IS DISTINCT FROM
                   relation.open_issue_id::text
                OR NOT COALESCE(
                  relation.evidence_id = ANY(proposal.supporting_evidence_refs), false
                )
                OR decision.decision_id IS NULL
                OR decision.decision <> 'APPROVE'
                OR decision.resulting_open_issue_id IS DISTINCT FROM
                   relation.open_issue_id
                OR decision.canonical_commit_seq IS NULL
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNGOVERNED_RESOLUTION_GROUNDING';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM milai.legacy_grounding_relation_quarantine ledger
            JOIN milai.steward_decision decision
              ON decision.tenant_id = ledger.tenant_id
             AND decision.decision_id = ledger.reconciliation_decision_id
            WHERE decision.decision <> 'REJECT'
               OR ledger.original_relation_type <> 'RESOLUTION_CANDIDATE'
               OR ledger.claim_version_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_INVALID_GROUNDING_QUARANTINE';
          END IF;
        END
        $postconditions$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0025 downgrade is intentionally unsupported for reconciled canonical history"
    )
