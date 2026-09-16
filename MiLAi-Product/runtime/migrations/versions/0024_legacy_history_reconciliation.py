"""Reconcile candidate.1 governance history without inventing prior authority.

Revision ID: 0024_legacy_history_reconcile
Revises: 0023_erasure_sha256_repair

Candidate.1 could create V1/OpenIssue rows without their creation sentinels,
move an Issue to READY_FOR_REVIEW and materialise resolution grounding while
the proposal was still pending, and emit TX-05 history without governance
links.  This forward-only migration proves every durable source object before
it changes anything, backfills the missing sentinels, preserves exact legacy
rows in immutable quarantine ledgers, and writes a continuous governed replay.
Unrecognised or unprovable data aborts the whole migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_legacy_history_reconcile"
down_revision: str | None = "0023_erasure_sha256_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_quarantine_ledger()
    _create_grounding_quarantine_ledger()
    _lock_governance_tables()
    _prove_legacy_tx05_source()
    _prove_source_state()
    _backfill_creation_history()
    _reconcile_legacy_tx05_governance()
    _reconcile_legacy_predecision_transitions()
    _reconcile_legacy_resolution_grounding()
    _enforce_complete_history()


def _create_quarantine_ledger() -> None:
    op.create_table(
        "legacy_issue_transition_quarantine",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("from_revision", sa.Integer(), nullable=False),
        sa.Column("to_revision", sa.Integer(), nullable=False),
        sa.Column("original_event_type", sa.Text(), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_policy_version", sa.Text(), nullable=False),
        sa.Column("original_canonical_commit_seq", sa.BigInteger(), nullable=False),
        sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reconciliation_proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replacement_transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reversal_transition_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            server_default="0024_legacy_history_reconcile",
        ),
        sa.Column(
            "quarantine_reason",
            sa.Text(),
            nullable=False,
            server_default="CANDIDATE1_PREDECISION_CANONICAL_EFFECT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "original_transition_id",
            name="pk_legacy_issue_transition_quarantine",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["milai.open_issue.tenant_id", "milai.open_issue.issue_id"],
            name="fk_legacy_quarantine_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_legacy_quarantine_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reconciliation_decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_legacy_quarantine_reconciliation_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reconciliation_proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_legacy_quarantine_reconciliation_proposal",
        ),
        sa.CheckConstraint("original_decision_id IS NULL", name="ck_legacy_quarantine_predecision"),
        sa.CheckConstraint(
            "original_event_type IN ('RESOLUTION_EVIDENCE_PROPOSED', "
            "'RESOLUTION_EVIDENCE_REVOKED', 'ISSUE_EVIDENCE_REVOKED')",
            name="ck_legacy_quarantine_event",
        ),
        sa.CheckConstraint(
            "to_revision = from_revision + 1",
            name="ck_legacy_quarantine_revision",
        ),
        sa.CheckConstraint(
            "length(original_row_sha256) = 64",
            name="ck_legacy_quarantine_sha256",
        ),
        sa.CheckConstraint(
            "migration_revision = '0024_legacy_history_reconcile'",
            name="ck_legacy_quarantine_migration",
        ),
        schema="milai",
    )
    op.execute(
        "ALTER TABLE milai.legacy_issue_transition_quarantine ENABLE ROW LEVEL SECURITY; "
        "ALTER TABLE milai.legacy_issue_transition_quarantine FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY legacy_issue_transition_quarantine_tenant_isolation
        ON milai.legacy_issue_transition_quarantine
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )
    op.execute(
        "CREATE TRIGGER trg_legacy_issue_transition_quarantine_append_only "
        "BEFORE UPDATE OR DELETE ON milai.legacy_issue_transition_quarantine "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )
    op.execute(
        "REVOKE ALL ON TABLE milai.legacy_issue_transition_quarantine "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.legacy_issue_transition_quarantine "
        "TO milai_steward, milai_audit"
    )
    op.execute(
        "COMMENT ON TABLE milai.legacy_issue_transition_quarantine IS "
        "'Exact immutable evidence of candidate.1 pre-Decision Issue effects; not canonical history'"
    )


def _create_grounding_quarantine_ledger() -> None:
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


def _lock_governance_tables() -> None:
    # The service must be offline for migration, but an explicit lock also closes
    # the race between provenance proof and the subsequent CAS reconciliation.
    op.execute(
        """
        LOCK TABLE
          milai.content_blob,
          milai.evidence_record,
          milai.deletion_request,
          milai.idempotency_record,
          milai.claim_version,
          milai.version_transition,
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
    # The source object is not proven merely because several JSON documents
    # repeat its UUID.  Require the durable DeletionRequest plus the immutable
    # idempotency result, revoke/purge Outbox pair, Evidence, actor, reason,
    # counts, original OperationalEvent, and the exact PostgreSQL transaction
    # timestamp shared by every candidate.1 insert to describe one transaction.
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


def _prove_source_state() -> None:
    op.execute(
        """
        DO $proof$
        BEGIN
          -- A V1 sentinel may only be derived from the exact APPROVE decision
          -- already carried by that immutable ClaimVersion.
          IF EXISTS (
            SELECT 1
            FROM milai.claim_version version
            LEFT JOIN milai.steward_decision decision
              ON decision.tenant_id = version.tenant_id
             AND decision.decision_id = version.steward_decision_id
            LEFT JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = decision.tenant_id
             AND proposal.proposal_id = decision.proposal_id
            WHERE version.version_number = 1
              AND (
                decision.decision_id IS NULL
                OR decision.decision <> 'APPROVE'
                OR decision.resulting_claim_version_id IS DISTINCT FROM
                   version.claim_version_id
                OR decision.canonical_commit_seq IS NULL
                OR decision.canonical_commit_seq IS DISTINCT FROM
                   version.canonical_commit_seq
                OR decision.decision_actor_id IS DISTINCT FROM
                   version.created_by_actor_id
                OR proposal.proposal_id IS NULL
                OR proposal.operation <> 'CREATE'
                OR proposal.status <> 'APPLIED'
                OR proposal.target_claim_id IS NOT NULL
                OR proposal.expected_version_id IS NOT NULL
                OR NOT EXISTS (
                  SELECT 1
                  FROM milai.outbox_event event
                  WHERE event.tenant_id = decision.tenant_id
                    AND event.canonical_commit_seq = decision.canonical_commit_seq
                    AND event.payload ->> 'proposal_id' = decision.proposal_id::text
                    AND event.payload ->> 'decision_id' = decision.decision_id::text
                    AND event.payload ->> 'claim_version_id' =
                        version.claim_version_id::text
                )
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_V1_CREATION_HISTORY';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM milai.claim_version version
            JOIN milai.version_transition transition
              ON transition.tenant_id = version.tenant_id
             AND transition.new_claim_version_id = version.claim_version_id
            JOIN milai.steward_decision decision
              ON decision.tenant_id = version.tenant_id
             AND decision.decision_id = version.steward_decision_id
            WHERE version.version_number = 1
              AND (
                transition.transition_type <> 'CREATE'
                OR transition.claim_id IS DISTINCT FROM version.claim_id
                OR transition.old_claim_version_id IS NOT NULL
                OR transition.proposal_id IS DISTINCT FROM decision.proposal_id
                OR transition.decision_id IS DISTINCT FROM decision.decision_id
                OR transition.canonical_commit_seq IS DISTINCT FROM
                   decision.canonical_commit_seq
              )
          ) OR EXISTS (
            SELECT 1
            FROM milai.version_transition transition
            WHERE transition.transition_type = 'CREATE'
            GROUP BY transition.tenant_id, transition.new_claim_version_id
            HAVING count(*) <> 1
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_CONFLICTING_V1_CREATION_HISTORY';
          END IF;

          -- Candidate.1 creates an Issue only in an approved CONTRADICT
          -- transaction.  The Proposal, Decision, Issue identity, actor, sequence,
          -- and original Outbox must all agree before a sentinel can be backfilled.
          IF EXISTS (
            SELECT 1
            FROM milai.open_issue issue
            LEFT JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = issue.tenant_id
             AND proposal.proposal_id = issue.created_from_proposal_id
            LEFT JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE proposal.proposal_id IS NULL
               OR proposal.operation <> 'CONTRADICT'
               OR proposal.status <> 'APPLIED'
               OR proposal.target_claim_id IS DISTINCT FROM issue.target_claim_id
               OR decision.decision_id IS NULL
               OR decision.decision <> 'APPROVE'
               OR decision.resulting_open_issue_id IS DISTINCT FROM issue.issue_id
               OR decision.canonical_commit_seq IS NULL
               OR decision.decision_actor_id IS DISTINCT FROM issue.created_by_actor_id
               OR NOT EXISTS (
                 SELECT 1
                 FROM milai.outbox_event event
                 WHERE event.tenant_id = decision.tenant_id
                   AND event.canonical_commit_seq = decision.canonical_commit_seq
                   AND event.payload ->> 'proposal_id' = decision.proposal_id::text
                   AND event.payload ->> 'decision_id' = decision.decision_id::text
                   AND event.payload ->> 'open_issue_id' = issue.issue_id::text
               )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_ISSUE_CREATION_HISTORY';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM milai.open_issue issue
            JOIN milai.open_issue_transition transition
              ON transition.tenant_id = issue.tenant_id
             AND transition.issue_id = issue.issue_id
             AND transition.event_type = 'ISSUE_CREATED'
            JOIN milai.steward_decision decision
              ON decision.tenant_id = issue.tenant_id
             AND decision.proposal_id = issue.created_from_proposal_id
            WHERE transition.from_status IS NOT NULL
               OR transition.to_status <> 'OPEN'
               OR transition.from_revision <> 0
               OR transition.to_revision <> 1
               OR transition.proposal_id IS DISTINCT FROM decision.proposal_id
               OR transition.decision_id IS DISTINCT FROM decision.decision_id
               OR transition.policy_version IS DISTINCT FROM decision.policy_version
               OR transition.canonical_commit_seq IS DISTINCT FROM
                  decision.canonical_commit_seq
          ) OR EXISTS (
            SELECT 1
            FROM milai.open_issue_transition transition
            WHERE transition.event_type = 'ISSUE_CREATED'
            GROUP BY transition.tenant_id, transition.issue_id
            HAVING count(*) <> 1
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_CONFLICTING_ISSUE_CREATION_HISTORY';
          END IF;

          -- Every incomplete governance tuple must be the exact shape emitted by
          -- candidate.1 proposal submission, with matching proposal and Outbox.
          IF EXISTS (
            SELECT 1
            FROM milai.open_issue_transition transition
            LEFT JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = transition.tenant_id
             AND proposal.proposal_id = transition.proposal_id
            LEFT JOIN milai.open_issue issue
              ON issue.tenant_id = transition.tenant_id
             AND issue.issue_id = transition.issue_id
            WHERE (
              transition.proposal_id IS NULL
              OR transition.decision_id IS NULL
              OR transition.policy_version IS NULL
              OR transition.canonical_commit_seq IS NULL
            ) AND NOT (
              (
              transition.decision_id IS NULL
              AND transition.proposal_id IS NOT NULL
              AND transition.policy_version IS NOT NULL
              AND transition.canonical_commit_seq IS NOT NULL
              AND transition.event_type = 'RESOLUTION_EVIDENCE_PROPOSED'
              AND transition.from_status IN ('OPEN', 'WAITING_EVIDENCE', 'WAITING_USER')
              AND transition.to_status = 'READY_FOR_REVIEW'
              AND transition.to_revision = transition.from_revision + 1
              AND proposal.proposal_id IS NOT NULL
              AND proposal.operation = 'SUPERSEDE'
              AND proposal.target_claim_id IS NOT DISTINCT FROM issue.target_claim_id
              AND proposal.proposed_patch ->> 'resolve_issue_id' =
                  transition.issue_id::text
              AND proposal.proposed_patch ->> 'expected_issue_revision' =
                  transition.from_revision::text
              AND jsonb_typeof(proposal.proposed_patch -> 'addressed_branches') = 'array'
              AND proposal.derivation_policy_id = transition.policy_version
              AND proposal.proposer_actor_id = transition.created_by_actor_id
              AND EXISTS (
                SELECT 1
                FROM milai.outbox_event event
                WHERE event.tenant_id = transition.tenant_id
                  AND event.aggregate_type = 'OPEN_ISSUE'
                  AND event.aggregate_id = transition.issue_id
                  AND event.event_type = 'OPEN_ISSUE_READY_FOR_REVIEW'
                  AND event.canonical_commit_seq = transition.canonical_commit_seq
                  AND event.payload ->> 'proposal_id' = transition.proposal_id::text
                  AND event.payload ->> 'revision' = transition.to_revision::text
              )
              ) OR (
                transition.proposal_id IS NULL
                AND transition.decision_id IS NULL
                AND transition.policy_version = 'tx05-revoke-v1'
                AND transition.canonical_commit_seq IS NOT NULL
                AND transition.to_revision = transition.from_revision + 1
                AND (
                  (
                    transition.event_type = 'RESOLUTION_EVIDENCE_REVOKED'
                    AND transition.from_status = 'RESOLVED'
                    AND transition.to_status = 'WAITING_EVIDENCE'
                  ) OR (
                    transition.event_type = 'ISSUE_EVIDENCE_REVOKED'
                    AND (
                      (transition.from_status = 'READY_FOR_REVIEW'
                       AND transition.to_status = 'WAITING_EVIDENCE')
                      OR
                      (transition.from_status NOT IN ('RESOLVED', 'READY_FOR_REVIEW')
                       AND transition.to_status = transition.from_status)
                    )
                  )
                )
                AND EXISTS (
                  SELECT 1
                  FROM milai.outbox_event revoke_event
                  JOIN milai.evidence_record evidence
                    ON evidence.tenant_id = revoke_event.tenant_id
                   AND evidence.evidence_id::text =
                       revoke_event.payload ->> 'evidence_id'
                  WHERE revoke_event.tenant_id = transition.tenant_id
                    AND revoke_event.event_type = 'EVIDENCE_REVOKED'
                    AND revoke_event.canonical_commit_seq =
                        transition.canonical_commit_seq
                    AND revoke_event.created_by_actor_id =
                        transition.created_by_actor_id
                    AND revoke_event.payload ->> 'deletion_request_id' IS NOT NULL
                    AND revoke_event.payload -> 'affected_issue_ids' @>
                        jsonb_build_array(transition.issue_id)
                    AND evidence.revoked_at IS NOT NULL
                    AND EXISTS (
                      SELECT 1
                      FROM milai.idempotency_record idempotency
                      WHERE idempotency.tenant_id = transition.tenant_id
                        AND idempotency.operation_family = 'TX-05_EVIDENCE_REVOKE'
                        AND idempotency.created_by_actor_id =
                            transition.created_by_actor_id
                        AND idempotency.response_payload ->> 'canonical_commit_seq' =
                            transition.canonical_commit_seq::text
                        AND idempotency.response_payload ->> 'evidence_id' =
                            evidence.evidence_id::text
                        AND idempotency.response_payload ->> 'deletion_request_id' =
                            revoke_event.payload ->> 'deletion_request_id'
                    )
                    AND EXISTS (
                      SELECT 1
                      FROM milai.operational_event operational
                      WHERE operational.tenant_id = transition.tenant_id
                        AND operational.event_type = 'EVIDENCE_REVOKED'
                        AND operational.created_by_actor_id =
                            transition.created_by_actor_id
                        AND operational.reason_code IS NOT NULL
                        AND operational.safe_metadata ->> 'canonical_commit_seq' =
                            transition.canonical_commit_seq::text
                        AND operational.safe_metadata ->> 'evidence_id' =
                            evidence.evidence_id::text
                        AND operational.safe_metadata ->> 'deletion_request_id' =
                            revoke_event.payload ->> 'deletion_request_id'
                    )
                )
              )
            )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNRECOGNISED_UNGOVERNED_ISSUE_TRANSITION';
          END IF;

          -- A recognised legacy transition is either already followed by the
          -- real review Decision/outcome, or is the one current pending effect
          -- that this migration may safely reject and reverse.
          IF EXISTS (
            SELECT 1
            FROM milai.open_issue_transition transition
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = transition.tenant_id
             AND proposal.proposal_id = transition.proposal_id
            JOIN milai.open_issue issue
              ON issue.tenant_id = transition.tenant_id
             AND issue.issue_id = transition.issue_id
            LEFT JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE transition.decision_id IS NULL
              AND transition.event_type = 'RESOLUTION_EVIDENCE_PROPOSED'
              AND NOT (
                (
                  decision.decision_id IS NULL
                  AND proposal.status = 'PENDING_REVIEW'
                  AND issue.status = 'READY_FOR_REVIEW'
                  AND issue.revision = transition.to_revision
                  AND NOT EXISTS (
                    SELECT 1
                    FROM milai.open_issue_transition later
                    WHERE later.tenant_id = transition.tenant_id
                      AND later.issue_id = transition.issue_id
                      AND later.from_revision >= transition.to_revision
                  )
                ) OR (
                  decision.decision_id IS NOT NULL
                  AND decision.canonical_commit_seq IS NOT NULL
                  AND decision.resulting_open_issue_id = transition.issue_id
                  AND proposal.status = CASE decision.decision
                    WHEN 'APPROVE' THEN 'APPLIED' ELSE 'REJECTED' END
                  AND EXISTS (
                    SELECT 1
                    FROM milai.open_issue_transition outcome
                    WHERE outcome.tenant_id = transition.tenant_id
                      AND outcome.issue_id = transition.issue_id
                      AND outcome.from_revision = transition.to_revision
                      AND outcome.to_revision = transition.to_revision + 1
                      AND outcome.proposal_id = transition.proposal_id
                      AND outcome.decision_id = decision.decision_id
                      AND outcome.policy_version = decision.policy_version
                      AND outcome.canonical_commit_seq = decision.canonical_commit_seq
                      AND (
                        (decision.decision = 'APPROVE'
                         AND outcome.event_type = 'DISCHARGE_APPROVED'
                         AND outcome.to_status = 'RESOLVED')
                        OR
                        (decision.decision = 'REJECT'
                         AND outcome.event_type = 'RESOLUTION_REJECTED'
                         AND outcome.to_status = 'OPEN')
                      )
                  )
                )
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNSAFE_LEGACY_RESOLUTION_STATE';
          END IF;

          -- Candidate.1 submission wrote one Issue-owned resolution relation
          -- for each distinct support reference.  Refuse to guess when that
          -- exact set cannot be attributed to the same proposal/Issue.
          IF EXISTS (
            SELECT 1
            FROM milai.open_issue_transition transition
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = transition.tenant_id
             AND proposal.proposal_id = transition.proposal_id
            WHERE transition.decision_id IS NULL
              AND transition.event_type = 'RESOLUTION_EVIDENCE_PROPOSED'
              AND (
                EXISTS (
                  SELECT 1
                  FROM milai.grounding_relation relation
                  WHERE relation.tenant_id = transition.tenant_id
                    AND relation.created_from_proposal_id = transition.proposal_id
                    AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                    AND (
                      relation.claim_version_id IS NOT NULL
                      OR relation.open_issue_id IS DISTINCT FROM transition.issue_id
                      OR NOT (
                        relation.evidence_id = ANY(proposal.supporting_evidence_refs)
                      )
                    )
                )
                OR (
                  SELECT count(*)
                  FROM milai.grounding_relation relation
                  WHERE relation.tenant_id = transition.tenant_id
                    AND relation.created_from_proposal_id = transition.proposal_id
                    AND relation.open_issue_id = transition.issue_id
                    AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                ) <> (
                  SELECT count(DISTINCT support.evidence_id)
                  FROM unnest(proposal.supporting_evidence_refs) support(evidence_id)
                )
                OR EXISTS (
                  SELECT 1
                  FROM unnest(proposal.supporting_evidence_refs) support(evidence_id)
                  WHERE NOT EXISTS (
                    SELECT 1
                    FROM milai.grounding_relation relation
                    WHERE relation.tenant_id = transition.tenant_id
                      AND relation.created_from_proposal_id = transition.proposal_id
                      AND relation.open_issue_id = transition.issue_id
                      AND relation.evidence_id = support.evidence_id
                      AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                  )
                )
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_LEGACY_RESOLUTION_GROUNDING';
          END IF;
        END
        $proof$
        """
    )


def _backfill_creation_history() -> None:
    op.execute(
        """
        INSERT INTO milai.version_transition (
          tenant_id, transition_id, claim_id, old_claim_version_id,
          new_claim_version_id, transition_type, proposal_id, decision_id,
          canonical_commit_seq, created_at, created_by_actor_id
        )
        SELECT
          version.tenant_id, gen_random_uuid(), version.claim_id, NULL,
          version.claim_version_id, 'CREATE', decision.proposal_id,
          decision.decision_id, decision.canonical_commit_seq,
          decision.decided_at, decision.decision_actor_id
        FROM milai.claim_version version
        JOIN milai.steward_decision decision
          ON decision.tenant_id = version.tenant_id
         AND decision.decision_id = version.steward_decision_id
        WHERE version.version_number = 1
          AND NOT EXISTS (
            SELECT 1
            FROM milai.version_transition transition
            WHERE transition.tenant_id = version.tenant_id
              AND transition.new_claim_version_id = version.claim_version_id
          )
        """
    )
    op.execute(
        """
        INSERT INTO milai.open_issue_transition (
          tenant_id, transition_id, issue_id, from_status, to_status,
          from_revision, to_revision, event_type, proposal_id, decision_id,
          policy_version, canonical_commit_seq, created_at, created_by_actor_id
        )
        SELECT
          issue.tenant_id, gen_random_uuid(), issue.issue_id, NULL, 'OPEN',
          0, 1, 'ISSUE_CREATED', decision.proposal_id, decision.decision_id,
          decision.policy_version, decision.canonical_commit_seq,
          decision.decided_at, decision.decision_actor_id
        FROM milai.open_issue issue
        JOIN milai.steward_decision decision
          ON decision.tenant_id = issue.tenant_id
         AND decision.proposal_id = issue.created_from_proposal_id
        WHERE NOT EXISTS (
          SELECT 1
          FROM milai.open_issue_transition transition
          WHERE transition.tenant_id = issue.tenant_id
            AND transition.issue_id = issue.issue_id
            AND transition.event_type = 'ISSUE_CREATED'
        )
        """
    )


def _reconcile_legacy_tx05_governance() -> None:
    # Candidate.1 TX-05 had a strong Steward/confirmation/idempotency boundary,
    # but did not materialise Proposal/Decision links.  Reconstruct governance
    # only when the immutable idempotency result, deletion request, operational
    # event and original Outbox all prove the same actor/evidence/sequence.
    op.execute("DROP TRIGGER trg_open_issue_transition_append_only ON milai.open_issue_transition")
    op.execute(
        """
        DO $tx05_reconcile$
        DECLARE
          revoke record;
          legacy record;
          existing_proposal milai.operation_proposal%ROWTYPE;
          existing_decision milai.steward_decision%ROWTYPE;
          v_proposal_id uuid;
          v_decision_id uuid;
          v_replacement_id uuid;
          v_row_hash text;
          v_rows integer;
        BEGIN
          FOR revoke IN
            SELECT DISTINCT
              revoke_event.tenant_id,
              revoke_event.canonical_commit_seq,
              revoke_event.created_by_actor_id,
              evidence.evidence_id,
              deletion.deletion_request_id::text AS deletion_request_id,
              operational.reason_code,
              idempotency.idempotency_key,
              idempotency.request_fingerprint
            FROM milai.outbox_event revoke_event
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = revoke_event.tenant_id
             AND evidence.evidence_id::text =
                 revoke_event.payload ->> 'evidence_id'
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
            JOIN milai.operational_event operational
              ON operational.tenant_id = evidence.tenant_id
             AND operational.event_type = 'EVIDENCE_REVOKED'
             AND operational.created_by_actor_id =
                 revoke_event.created_by_actor_id
             AND operational.created_at = deletion.requested_at
             AND operational.safe_metadata ->> 'canonical_commit_seq' =
                 revoke_event.canonical_commit_seq::text
             AND operational.safe_metadata ->> 'evidence_id' =
                 evidence.evidence_id::text
             AND operational.safe_metadata ->> 'deletion_request_id' =
                 deletion.deletion_request_id::text
             AND operational.reason_code = deletion.reason_code
            WHERE revoke_event.event_type = 'EVIDENCE_REVOKED'
              AND revoke_event.created_at = deletion.requested_at
              AND NOT (
                revoke_event.payload ? 'proposal_id'
                AND revoke_event.payload ? 'decision_id'
              )
              AND evidence.revocation_reason = deletion.reason_code
            ORDER BY revoke_event.tenant_id, revoke_event.canonical_commit_seq
          LOOP
            SELECT proposal.* INTO existing_proposal
            FROM milai.operation_proposal proposal
            WHERE proposal.tenant_id = revoke.tenant_id
              AND proposal.idempotency_key =
                  'tx05:' || revoke.idempotency_key;

            IF FOUND THEN
              IF existing_proposal.operation <> 'REVOKE_EVIDENCE'
                 OR existing_proposal.status <> 'APPLIED'
                 OR existing_proposal.request_fingerprint <>
                    revoke.request_fingerprint
                 OR existing_proposal.proposer_actor_id <>
                    revoke.created_by_actor_id
                 OR existing_proposal.proposed_patch ->> 'evidence_id' <>
                    revoke.evidence_id::text THEN
                RAISE EXCEPTION USING
                  ERRCODE = 'P0001', MESSAGE = 'AF09_TX05_GOVERNANCE_COLLISION';
              END IF;
              SELECT decision.* INTO existing_decision
              FROM milai.steward_decision decision
              WHERE decision.tenant_id = revoke.tenant_id
                AND decision.proposal_id = existing_proposal.proposal_id;
              IF NOT FOUND
                 OR existing_decision.decision <> 'APPROVE'
                 OR existing_decision.decision_actor_type <> 'STEWARD'
                 OR existing_decision.decision_actor_id <>
                    revoke.created_by_actor_id
                 OR existing_decision.resulting_evidence_id IS DISTINCT FROM
                    revoke.evidence_id
                 OR existing_decision.canonical_commit_seq IS DISTINCT FROM
                    revoke.canonical_commit_seq THEN
                RAISE EXCEPTION USING
                  ERRCODE = 'P0001', MESSAGE = 'AF09_TX05_GOVERNANCE_COLLISION';
              END IF;
              v_proposal_id := existing_proposal.proposal_id;
              v_decision_id := existing_decision.decision_id;
            ELSE
              v_proposal_id := gen_random_uuid();
              v_decision_id := gen_random_uuid();
              INSERT INTO milai.operation_proposal (
                tenant_id, proposal_id, target_claim_id, operation,
                expected_version_id, proposed_patch, supporting_evidence_refs,
                contradicting_evidence_refs, scope_predicate,
                requested_authority, derivation_policy_id, model_id,
                template_id, derivation_snapshot, proposer_actor_id,
                canonical_commit_authorized, status, idempotency_key,
                request_fingerprint, created_by_actor_id
              ) VALUES (
                revoke.tenant_id, v_proposal_id, NULL, 'REVOKE_EVIDENCE',
                NULL, jsonb_build_object(
                  'evidence_id', revoke.evidence_id,
                  'reason_code', revoke.reason_code,
                  'confirmation', 'REVOKE'
                ), '{}'::uuid[], '{}'::uuid[], '{}'::jsonb,
                'USER_CONFIRMED', 'tx05-revocation-policy-v2', NULL, NULL,
                jsonb_build_object(
                  'governance_path', 'TX-05-LEGACY-RECONCILIATION',
                  'original_canonical_commit_seq', revoke.canonical_commit_seq,
                  'deletion_request_id', revoke.deletion_request_id
                ), revoke.created_by_actor_id, false, 'APPLIED',
                'tx05:' || revoke.idempotency_key,
                revoke.request_fingerprint, revoke.created_by_actor_id
              );
              INSERT INTO milai.steward_decision (
                tenant_id, decision_id, proposal_id, decision,
                decision_actor_type, decision_actor_id, policy_version,
                reason_code, resulting_evidence_id, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                revoke.tenant_id, v_decision_id, v_proposal_id, 'APPROVE',
                'STEWARD', revoke.created_by_actor_id,
                'tx05-revocation-policy-v2', revoke.reason_code,
                revoke.evidence_id, revoke.canonical_commit_seq,
                revoke.created_by_actor_id
              );
            END IF;

            PERFORM set_config(
              'milai.tx05_proposal_id', v_proposal_id::text, true
            );
            PERFORM set_config(
              'milai.tx05_decision_id', v_decision_id::text, true
            );
            FOR legacy IN
              SELECT transition.*
              FROM milai.open_issue_transition transition
              WHERE transition.tenant_id = revoke.tenant_id
                AND transition.canonical_commit_seq =
                    revoke.canonical_commit_seq
                AND transition.proposal_id IS NULL
                AND transition.decision_id IS NULL
                AND transition.event_type IN (
                  'RESOLUTION_EVIDENCE_REVOKED', 'ISSUE_EVIDENCE_REVOKED'
                )
              ORDER BY transition.issue_id, transition.from_revision
            LOOP
              v_replacement_id := gen_random_uuid();
              v_row_hash := encode(sha256(convert_to(jsonb_build_object(
                'tenant_id', legacy.tenant_id,
                'transition_id', legacy.transition_id,
                'issue_id', legacy.issue_id,
                'from_status', legacy.from_status,
                'to_status', legacy.to_status,
                'from_revision', legacy.from_revision,
                'to_revision', legacy.to_revision,
                'event_type', legacy.event_type,
                'proposal_id', legacy.proposal_id,
                'decision_id', legacy.decision_id,
                'policy_version', legacy.policy_version,
                'canonical_commit_seq', legacy.canonical_commit_seq,
                'created_at', legacy.created_at,
                'created_by_actor_id', legacy.created_by_actor_id
              )::text, 'UTF8')), 'hex');
              INSERT INTO milai.legacy_issue_transition_quarantine (
                tenant_id, original_transition_id, issue_id, from_status,
                to_status, from_revision, to_revision, original_event_type,
                proposal_id, original_decision_id, original_policy_version,
                original_canonical_commit_seq, original_created_at,
                original_created_by_actor_id, reconciliation_decision_id,
                reconciliation_proposal_id, replacement_transition_id,
                reversal_transition_id, original_row_sha256
              ) VALUES (
                legacy.tenant_id, legacy.transition_id, legacy.issue_id,
                legacy.from_status, legacy.to_status, legacy.from_revision,
                legacy.to_revision, legacy.event_type, legacy.proposal_id,
                legacy.decision_id, legacy.policy_version,
                legacy.canonical_commit_seq, legacy.created_at,
                legacy.created_by_actor_id, v_decision_id, v_proposal_id,
                v_replacement_id, NULL, v_row_hash
              );
              DELETE FROM milai.open_issue_transition
              WHERE tenant_id = legacy.tenant_id
                AND transition_id = legacy.transition_id;
              GET DIAGNOSTICS v_rows = ROW_COUNT;
              IF v_rows <> 1 THEN
                RAISE EXCEPTION USING
                  ERRCODE = 'P0001', MESSAGE = 'AF09_TX05_QUARANTINE_MOVE_FAILED';
              END IF;
              INSERT INTO milai.open_issue_transition (
                tenant_id, transition_id, issue_id, from_status, to_status,
                from_revision, to_revision, event_type, proposal_id,
                decision_id, policy_version, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                legacy.tenant_id, v_replacement_id, legacy.issue_id,
                legacy.from_status, legacy.to_status, legacy.from_revision,
                legacy.to_revision, legacy.event_type, v_proposal_id,
                v_decision_id, 'tx05-revocation-policy-v2',
                revoke.canonical_commit_seq, revoke.created_by_actor_id
              );
            END LOOP;

            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              revoke.tenant_id, gen_random_uuid(),
              'LEGACY_TX05_GOVERNANCE_RECONCILED', revoke.reason_code,
              jsonb_build_object(
                'proposal_id', v_proposal_id,
                'decision_id', v_decision_id,
                'evidence_id', revoke.evidence_id,
                'deletion_request_id', revoke.deletion_request_id,
                'canonical_commit_seq', revoke.canonical_commit_seq
              ), revoke.created_by_actor_id
            );
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              revoke.tenant_id, gen_random_uuid(), 'EVIDENCE',
              revoke.evidence_id, 'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED',
              jsonb_build_object(
                'proposal_id', v_proposal_id,
                'decision_id', v_decision_id,
                'evidence_id', revoke.evidence_id,
                'deletion_request_id', revoke.deletion_request_id
              ), 0, revoke.canonical_commit_seq, revoke.created_by_actor_id
            );
          END LOOP;
        END
        $tx05_reconcile$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_open_issue_transition_append_only "
        "BEFORE UPDATE OR DELETE ON milai.open_issue_transition "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )


def _reconcile_legacy_predecision_transitions() -> None:
    # The invalid row is never rewritten in place.  Its exact values and hash are
    # inserted into the immutable quarantine ledger before the canonical copy is
    # removed.  Both actions are one PostgreSQL transaction.
    op.execute("DROP TRIGGER trg_open_issue_transition_append_only ON milai.open_issue_transition")
    op.execute(
        """
        DO $reconcile$
        DECLARE
          legacy record;
          existing_decision milai.steward_decision%ROWTYPE;
          v_decision_id uuid;
          v_replacement_id uuid;
          v_reversal_id uuid;
          v_commit_seq bigint;
          v_policy_version text;
          v_decision_actor_id uuid;
          v_pending boolean;
          v_rows integer;
          v_row_hash text;
        BEGIN
          FOR legacy IN
            SELECT transition.*
            FROM milai.open_issue_transition transition
            WHERE transition.decision_id IS NULL
              AND transition.event_type = 'RESOLUTION_EVIDENCE_PROPOSED'
            ORDER BY transition.tenant_id, transition.issue_id,
                     transition.from_revision, transition.transition_id
          LOOP
            SELECT decision.* INTO existing_decision
            FROM milai.steward_decision decision
            WHERE decision.tenant_id = legacy.tenant_id
              AND decision.proposal_id = legacy.proposal_id;
            v_pending := NOT FOUND;
            v_replacement_id := gen_random_uuid();
            v_reversal_id := NULL;

            IF v_pending THEN
              v_decision_id := gen_random_uuid();
              v_reversal_id := gen_random_uuid();
              v_commit_seq := nextval('milai.canonical_commit_seq');
              v_policy_version := 'af09-candidate1-reconciliation-v1';
              v_decision_actor_id :=
                '00000000-0000-4024-8024-000000000024'::uuid;
              INSERT INTO milai.steward_decision (
                tenant_id, decision_id, proposal_id, decision,
                decision_actor_type, decision_actor_id, policy_version,
                reason_code, resulting_open_issue_id, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                legacy.tenant_id, v_decision_id, legacy.proposal_id, 'REJECT',
                'POLICY', v_decision_actor_id, v_policy_version,
                'LEGACY_PREDECISION_EFFECT_REJECTED', legacy.issue_id, v_commit_seq,
                v_decision_actor_id
              );
              UPDATE milai.operation_proposal
              SET status = 'REJECTED'
              WHERE tenant_id = legacy.tenant_id
                AND proposal_id = legacy.proposal_id
                AND status = 'PENDING_REVIEW';
              GET DIAGNOSTICS v_rows = ROW_COUNT;
              IF v_rows <> 1 THEN
                RAISE EXCEPTION USING
                  ERRCODE = 'P0001', MESSAGE = 'AF09_PROPOSAL_REPAIR_CAS_FAILED';
              END IF;
            ELSE
              v_decision_id := existing_decision.decision_id;
              v_commit_seq := existing_decision.canonical_commit_seq;
              v_policy_version := existing_decision.policy_version;
              v_decision_actor_id := existing_decision.decision_actor_id;
            END IF;

            v_row_hash := encode(sha256(convert_to(jsonb_build_object(
              'tenant_id', legacy.tenant_id,
              'transition_id', legacy.transition_id,
              'issue_id', legacy.issue_id,
              'from_status', legacy.from_status,
              'to_status', legacy.to_status,
              'from_revision', legacy.from_revision,
              'to_revision', legacy.to_revision,
              'event_type', legacy.event_type,
              'proposal_id', legacy.proposal_id,
              'decision_id', legacy.decision_id,
              'policy_version', legacy.policy_version,
              'canonical_commit_seq', legacy.canonical_commit_seq,
              'created_at', legacy.created_at,
              'created_by_actor_id', legacy.created_by_actor_id
            )::text, 'UTF8')), 'hex');

            INSERT INTO milai.legacy_issue_transition_quarantine (
              tenant_id, original_transition_id, issue_id, from_status,
              to_status, from_revision, to_revision, original_event_type,
              proposal_id, original_decision_id, original_policy_version,
              original_canonical_commit_seq, original_created_at,
              original_created_by_actor_id, reconciliation_decision_id,
              reconciliation_proposal_id, replacement_transition_id,
              reversal_transition_id,
              original_row_sha256
            ) VALUES (
              legacy.tenant_id, legacy.transition_id, legacy.issue_id,
              legacy.from_status, legacy.to_status, legacy.from_revision,
              legacy.to_revision, legacy.event_type, legacy.proposal_id,
              legacy.decision_id, legacy.policy_version,
              legacy.canonical_commit_seq, legacy.created_at,
              legacy.created_by_actor_id, v_decision_id,
              legacy.proposal_id, v_replacement_id, v_reversal_id, v_row_hash
            );

            DELETE FROM milai.open_issue_transition
            WHERE tenant_id = legacy.tenant_id
              AND transition_id = legacy.transition_id;
            GET DIAGNOSTICS v_rows = ROW_COUNT;
            IF v_rows <> 1 THEN
              RAISE EXCEPTION USING
                ERRCODE = 'P0001', MESSAGE = 'AF09_QUARANTINE_MOVE_FAILED';
            END IF;

            -- This is an observed-effect reconciliation record, not a claim that
            -- the original submission had prior authority.  The paired Decision
            -- governs its classification and (when pending) immediate reversal.
            INSERT INTO milai.open_issue_transition (
              tenant_id, transition_id, issue_id, from_status, to_status,
              from_revision, to_revision, event_type, proposal_id, decision_id,
              policy_version, canonical_commit_seq, created_at,
              created_by_actor_id
            ) VALUES (
              legacy.tenant_id, v_replacement_id, legacy.issue_id,
              legacy.from_status, legacy.to_status, legacy.from_revision,
              legacy.to_revision, 'LEGACY_PREDECISION_EFFECT_QUARANTINED',
              legacy.proposal_id, v_decision_id, v_policy_version,
              v_commit_seq, CURRENT_TIMESTAMP, v_decision_actor_id
            );

            IF v_pending THEN
              UPDATE milai.open_issue
              SET status = legacy.from_status,
                  revision = revision + 1
              WHERE tenant_id = legacy.tenant_id
                AND issue_id = legacy.issue_id
                AND status = legacy.to_status
                AND revision = legacy.to_revision;
              GET DIAGNOSTICS v_rows = ROW_COUNT;
              IF v_rows <> 1 THEN
                RAISE EXCEPTION USING
                  ERRCODE = 'P0001', MESSAGE = 'AF09_ISSUE_REPAIR_CAS_FAILED';
              END IF;
              INSERT INTO milai.open_issue_transition (
                tenant_id, transition_id, issue_id, from_status, to_status,
                from_revision, to_revision, event_type, proposal_id,
                decision_id, policy_version, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                legacy.tenant_id, v_reversal_id, legacy.issue_id,
                legacy.to_status, legacy.from_status, legacy.to_revision,
                legacy.to_revision + 1, 'LEGACY_RESOLUTION_REJECTED',
                legacy.proposal_id, v_decision_id, v_policy_version,
                v_commit_seq, v_decision_actor_id
              );
            END IF;

            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              legacy.tenant_id, gen_random_uuid(),
              'LEGACY_ISSUE_HISTORY_RECONCILED',
              CASE WHEN v_pending THEN 'LEGACY_PREDECISION_EFFECT_REJECTED'
                   ELSE 'LEGACY_PREDECISION_HISTORY_CLASSIFIED' END,
              jsonb_build_object(
                'issue_id', legacy.issue_id,
                'proposal_id', legacy.proposal_id,
                'decision_id', v_decision_id,
                'original_transition_id', legacy.transition_id,
                'replacement_transition_id', v_replacement_id,
                'reversal_transition_id', v_reversal_id,
                'original_row_sha256', v_row_hash,
                'canonical_commit_seq', v_commit_seq,
                'pending_proposal_rejected', v_pending
              ), v_decision_actor_id
            );
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              legacy.tenant_id, gen_random_uuid(), 'OPEN_ISSUE', legacy.issue_id,
              'OPEN_ISSUE_LEGACY_HISTORY_RECONCILED',
              jsonb_build_object(
                'issue_id', legacy.issue_id,
                'proposal_id', legacy.proposal_id,
                'decision_id', v_decision_id,
                'original_transition_id', legacy.transition_id,
                'replacement_transition_id', v_replacement_id,
                'reversal_transition_id', v_reversal_id,
                'original_row_sha256', v_row_hash,
                'pending_proposal_rejected', v_pending
              ), 20, v_commit_seq, v_decision_actor_id
            );
          END LOOP;
        END
        $reconcile$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_open_issue_transition_append_only "
        "BEFORE UPDATE OR DELETE ON milai.open_issue_transition "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )


def _reconcile_legacy_resolution_grounding() -> None:
    # Only a real APPROVE may retain a canonical RESOLUTION_CANDIDATE relation.
    # Exact rejected rows are hashed and moved to a non-authoritative ledger;
    # they are never rewritten in place or silently discarded.
    op.execute("DROP TRIGGER trg_grounding_relation_append_only ON milai.grounding_relation")
    op.execute(
        """
        DO $grounding_reconcile$
        DECLARE
          legacy record;
          v_row_hash text;
          v_rows integer;
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.operation_proposal proposal
              ON proposal.tenant_id = relation.tenant_id
             AND proposal.proposal_id = relation.created_from_proposal_id
            JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE relation.relation_type = 'RESOLUTION_CANDIDATE'
              AND decision.decision = 'REJECT'
              AND NOT EXISTS (
                SELECT 1
                FROM milai.legacy_issue_transition_quarantine quarantine
                WHERE quarantine.tenant_id = relation.tenant_id
                  AND quarantine.issue_id = relation.open_issue_id
                  AND quarantine.proposal_id = relation.created_from_proposal_id
                  AND quarantine.original_event_type =
                      'RESOLUTION_EVIDENCE_PROPOSED'
                  AND quarantine.reconciliation_decision_id = decision.decision_id
                  AND relation.claim_version_id IS NULL
                  AND relation.evidence_id = ANY(proposal.supporting_evidence_refs)
              )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001',
              MESSAGE = 'AF09_UNPROVABLE_LEGACY_RESOLUTION_GROUNDING';
          END IF;

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
        END
        $grounding_reconcile$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_grounding_relation_append_only "
        "BEFORE UPDATE OR DELETE ON milai.grounding_relation "
        "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
    )


def _enforce_complete_history() -> None:
    # Flush deferred FK trigger events before PostgreSQL takes the validation
    # lock; otherwise ALTER TABLE correctly refuses to run in this transaction.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute(
        "ALTER TABLE milai.open_issue_transition VALIDATE CONSTRAINT ck_issue_transition_governed"
    )
    op.execute(
        "ALTER TABLE milai.open_issue_transition VALIDATE CONSTRAINT ck_issue_transition_revision"
    )
    op.execute(
        "ALTER TABLE milai.version_transition VALIDATE CONSTRAINT ck_version_transition_creation"
    )
    op.create_index(
        "uq_version_transition_new_version",
        "version_transition",
        ["tenant_id", "new_claim_version_id"],
        unique=True,
        schema="milai",
    )
    op.create_index(
        "uq_open_issue_transition_revision",
        "open_issue_transition",
        ["tenant_id", "issue_id", "to_revision"],
        unique=True,
        schema="milai",
    )
    op.execute(
        """
        DO $complete$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM milai.claim_version version
            LEFT JOIN milai.version_transition transition
              ON transition.tenant_id = version.tenant_id
             AND transition.new_claim_version_id = version.claim_version_id
            GROUP BY version.tenant_id, version.claim_version_id,
                     version.version_number
            HAVING count(transition.transition_id) <> 1
               OR bool_or(
                    version.version_number = 1
                    AND (
                      transition.transition_type <> 'CREATE'
                      OR transition.old_claim_version_id IS NOT NULL
                    )
                  )
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_INCOMPLETE_VERSION_REPLAY';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM milai.open_issue issue
            LEFT JOIN milai.open_issue_transition transition
              ON transition.tenant_id = issue.tenant_id
             AND transition.issue_id = issue.issue_id
            GROUP BY issue.tenant_id, issue.issue_id, issue.revision
            HAVING count(transition.transition_id) <> issue.revision
               OR min(transition.from_revision) <> 0
               OR max(transition.to_revision) <> issue.revision
               OR count(DISTINCT transition.to_revision) <> issue.revision
               OR count(*) FILTER (
                    WHERE transition.event_type = 'ISSUE_CREATED'
                      AND transition.from_status IS NULL
                      AND transition.from_revision = 0
                      AND transition.to_revision = 1
                  ) <> 1
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_INCOMPLETE_ISSUE_REPLAY';
          END IF;

          IF EXISTS (
            SELECT 1
            FROM milai.open_issue_transition transition
            WHERE transition.proposal_id IS NULL
               OR transition.decision_id IS NULL
               OR transition.policy_version IS NULL
               OR transition.canonical_commit_seq IS NULL
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'AF09_UNGOVERNED_CANONICAL_HISTORY';
          END IF;
        END
        $complete$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0024 downgrade is intentionally unsupported for reconciled canonical history"
    )
