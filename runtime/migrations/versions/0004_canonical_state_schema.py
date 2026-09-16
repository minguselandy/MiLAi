"""Create experimental canonical state and governance schema.

Revision ID: 0004_canonical_state_schema
Revises: 0003_evidence_plane

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_canonical_state_schema"
down_revision: str | None = "0003_evidence_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation
        ON milai.{table}
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )


def _common_columns() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE SEQUENCE milai.canonical_commit_seq AS bigint START WITH 1")

    op.create_table(
        "claim",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "claim_id", name="pk_claim"),
        sa.UniqueConstraint(
            "tenant_id",
            "subject_id",
            "predicate",
            "claim_type",
            name="uq_claim_identity",
        ),
        sa.CheckConstraint("length(btrim(subject_id)) > 0", name="ck_claim_subject"),
        sa.CheckConstraint("length(btrim(predicate)) > 0", name="ck_claim_predicate"),
        sa.CheckConstraint("length(btrim(claim_type)) > 0", name="ck_claim_type"),
        schema="milai",
    )

    op.create_table(
        "operation_proposal",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("expected_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposed_patch", postgresql.JSONB(), nullable=False),
        sa.Column(
            "supporting_evidence_refs",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "contradicting_evidence_refs",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("scope_predicate", postgresql.JSONB(), nullable=False),
        sa.Column("requested_authority", sa.Text(), nullable=False),
        sa.Column("derivation_policy_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("derivation_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("proposer_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "canonical_commit_authorized", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "proposal_id", name="pk_operation_proposal"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_claim_id"],
            ["milai.claim.tenant_id", "milai.claim.claim_id"],
            name="fk_proposal_target_claim",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_operation_proposal_idempotency"
        ),
        sa.CheckConstraint(
            "operation IN ('CREATE', 'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND', "
            "'SUPERSEDE', 'CONTEXTUALIZE', 'CONTRADICT', 'NO_CHANGE', 'SPLIT')",
            name="ck_operation_proposal_operation",
        ),
        sa.CheckConstraint(
            "requested_authority IN ('INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED')",
            name="ck_operation_proposal_authority",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_REVIEW', 'DEFERRED', 'APPLIED', 'REJECTED')",
            name="ck_operation_proposal_status",
        ),
        sa.CheckConstraint(
            "canonical_commit_authorized = false", name="ck_proposal_never_authorized"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposed_patch) = 'object'", name="ck_proposal_patch_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_predicate) = 'object'", name="ck_proposal_scope_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(derivation_snapshot) = 'object'",
            name="ck_proposal_derivation_snapshot_object",
        ),
        schema="milai",
    )

    op.create_table(
        "steward_decision",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("decision_actor_type", sa.Text(), nullable=False),
        sa.Column("decision_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resulting_claim_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resulting_open_issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "decision_id", name="pk_steward_decision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_decision_proposal",
        ),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_decision_proposal"),
        sa.CheckConstraint("decision IN ('APPROVE', 'REJECT')", name="ck_decision_value"),
        sa.CheckConstraint(
            "decision_actor_type IN ('POLICY', 'USER', 'STEWARD')",
            name="ck_decision_actor_type",
        ),
        schema="milai",
    )

    op.create_table(
        "open_issue",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("scope_predicate", postgresql.JSONB(), nullable=False),
        sa.Column("discharge_rule", postgresql.JSONB(), nullable=False),
        sa.Column("required_authority", sa.Text(), nullable=False),
        sa.Column("created_from_proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_by_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "issue_id", name="pk_open_issue"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_claim_id"],
            ["milai.claim.tenant_id", "milai.claim.claim_id"],
            name="fk_open_issue_claim",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_from_proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_open_issue_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resolved_by_decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_open_issue_resolution_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "issue_type IN ('CONFLICT', 'MISSING_EVIDENCE', 'SCOPE_UNCERTAIN', "
            "'AUTHORITY_UNCERTAIN', 'DEPENDENCY_INVALIDATED')",
            name="ck_open_issue_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'WAITING_EVIDENCE', 'WAITING_USER', "
            "'READY_FOR_REVIEW', 'RESOLVED', 'DISMISSED')",
            name="ck_open_issue_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_open_issue_revision"),
        sa.CheckConstraint(
            "required_authority IN ('INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED')",
            name="ck_open_issue_authority",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope_predicate) = 'object'", name="ck_open_issue_scope_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(discharge_rule) = 'object'", name="ck_open_issue_discharge_object"
        ),
        sa.CheckConstraint(
            "(status = 'RESOLVED' AND resolved_by_decision_id IS NOT NULL "
            "AND resolved_at IS NOT NULL) OR "
            "(status <> 'RESOLVED' AND resolved_by_decision_id IS NULL "
            "AND resolved_at IS NULL)",
            name="ck_open_issue_resolution_fields",
        ),
        schema="milai",
    )
    op.create_index(
        "uq_open_issue_live_type",
        "open_issue",
        ["tenant_id", "target_claim_id", "issue_type"],
        unique=True,
        schema="milai",
        postgresql_where=sa.text("status NOT IN ('RESOLVED', 'DISMISSED')"),
    )

    op.create_table(
        "claim_version",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("scope_predicate", postgresql.JSONB(), nullable=False),
        sa.Column("valid_time_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_time_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "system_time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lifecycle", sa.Text(), nullable=False),
        sa.Column("epistemic_status", sa.Text(), nullable=False),
        sa.Column("freshness", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("derivation_policy_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("steward_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "claim_version_id", name="pk_claim_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["milai.claim.tenant_id", "milai.claim.claim_id"],
            name="fk_claim_version_claim",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "steward_decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_claim_version_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "tenant_id", "claim_id", "version_number", name="uq_claim_version_number"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "claim_id",
            "claim_version_id",
            name="uq_claim_version_claim_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id", "canonical_commit_seq", name="uq_claim_version_commit_seq"
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_claim_version_number"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_claim_payload_object"),
        sa.CheckConstraint(
            "jsonb_typeof(scope_predicate) = 'object'", name="ck_claim_scope_object"
        ),
        sa.CheckConstraint(
            "valid_time_to IS NULL OR valid_time_from IS NULL OR valid_time_to > valid_time_from",
            name="ck_claim_valid_time",
        ),
        sa.CheckConstraint("lifecycle IN ('ACTIVE', 'RETIRED')", name="ck_claim_version_lifecycle"),
        sa.CheckConstraint(
            "epistemic_status IN ('SUPPORTED', 'WEAKENED', 'UNCERTAIN')",
            name="ck_claim_version_epistemic",
        ),
        sa.CheckConstraint(
            "freshness IN ('CURRENT', 'STALE', 'UNKNOWN')", name="ck_claim_version_freshness"
        ),
        sa.CheckConstraint(
            "authority IN ('INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED')",
            name="ck_claim_version_authority",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_claim_confidence"),
        schema="milai",
    )

    op.create_table(
        "claim_head",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "claim_id", name="pk_claim_head"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["milai.claim.tenant_id", "milai.claim.claim_id"],
            name="fk_claim_head_claim",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id", "current_claim_version_id"],
            [
                "milai.claim_version.tenant_id",
                "milai.claim_version.claim_id",
                "milai.claim_version.claim_version_id",
            ],
            name="fk_claim_head_version",
        ),
        schema="milai",
    )

    op.create_table(
        "version_transition",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("new_claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transition_type", sa.Text(), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "transition_id", name="pk_version_transition"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id"],
            ["milai.claim.tenant_id", "milai.claim.claim_id"],
            name="fk_transition_claim",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id", "old_claim_version_id"],
            [
                "milai.claim_version.tenant_id",
                "milai.claim_version.claim_id",
                "milai.claim_version.claim_version_id",
            ],
            name="fk_transition_old_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_id", "new_claim_version_id"],
            [
                "milai.claim_version.tenant_id",
                "milai.claim_version.claim_id",
                "milai.claim_version.claim_version_id",
            ],
            name="fk_transition_new_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_transition_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_transition_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        schema="milai",
    )

    op.create_table(
        "grounding_relation",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("open_issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("created_from_proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "relation_id", name="pk_grounding_relation"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_version_id"],
            ["milai.claim_version.tenant_id", "milai.claim_version.claim_version_id"],
            name="fk_grounding_claim_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "open_issue_id"],
            ["milai.open_issue.tenant_id", "milai.open_issue.issue_id"],
            name="fk_grounding_open_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_grounding_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_from_proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_grounding_proposal",
        ),
        sa.CheckConstraint(
            "(claim_version_id IS NOT NULL)::integer + (open_issue_id IS NOT NULL)::integer = 1",
            name="ck_grounding_exactly_one_owner",
        ),
        sa.CheckConstraint(
            "(claim_version_id IS NOT NULL AND relation_type IN "
            "('SUPPORTS', 'CONTRADICTS', 'DERIVED_FROM')) OR "
            "(open_issue_id IS NOT NULL AND relation_type IN "
            "('SUPPORT_BRANCH', 'CONTRADICT_BRANCH', 'RESOLUTION_CANDIDATE'))",
            name="ck_grounding_owner_relation_type",
        ),
        schema="milai",
    )
    op.create_index(
        "uq_grounding_claim_evidence_type",
        "grounding_relation",
        ["tenant_id", "claim_version_id", "evidence_id", "relation_type"],
        unique=True,
        schema="milai",
        postgresql_where=sa.text("claim_version_id IS NOT NULL"),
    )
    op.create_index(
        "uq_grounding_issue_evidence_type",
        "grounding_relation",
        ["tenant_id", "open_issue_id", "evidence_id", "relation_type"],
        unique=True,
        schema="milai",
        postgresql_where=sa.text("open_issue_id IS NOT NULL"),
    )

    op.create_table(
        "grounding_block",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("caused_by_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by_claim_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("restored_by_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "block_id", name="pk_grounding_block"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "claim_version_id"],
            ["milai.claim_version.tenant_id", "milai.claim_version.claim_version_id"],
            name="fk_grounding_block_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "caused_by_evidence_id"],
            ["milai.evidence_record.tenant_id", "milai.evidence_record.evidence_id"],
            name="fk_grounding_block_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "restored_by_claim_version_id"],
            ["milai.claim_version.tenant_id", "milai.claim_version.claim_version_id"],
            name="fk_grounding_block_restore_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "restored_by_decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_grounding_block_restore_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "block_type IN ('EVIDENCE_REVOKED', 'PERMISSION_UNREADABLE', "
            "'RETENTION_UNREADABLE', 'DEPENDENCY_INVALIDATED')",
            name="ck_grounding_block_type",
        ),
        sa.CheckConstraint(
            "(active AND released_at IS NULL AND restored_by_claim_version_id IS NULL "
            "AND restored_by_decision_id IS NULL) OR "
            "(NOT active AND released_at IS NOT NULL AND restored_by_claim_version_id IS NOT NULL "
            "AND restored_by_decision_id IS NOT NULL)",
            name="ck_grounding_block_release",
        ),
        schema="milai",
    )
    op.create_index(
        "uq_grounding_block_active_cause",
        "grounding_block",
        ["tenant_id", "claim_version_id", "caused_by_evidence_id", "block_type"],
        unique=True,
        schema="milai",
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "open_issue_transition",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("from_revision", sa.Integer(), nullable=False),
        sa.Column("to_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_version", sa.Text(), nullable=True),
        sa.Column("canonical_commit_seq", sa.BigInteger(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "transition_id", name="pk_open_issue_transition"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"],
            ["milai.open_issue.tenant_id", "milai.open_issue.issue_id"],
            name="fk_issue_transition_issue",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["milai.operation_proposal.tenant_id", "milai.operation_proposal.proposal_id"],
            name="fk_issue_transition_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["milai.steward_decision.tenant_id", "milai.steward_decision.decision_id"],
            name="fk_issue_transition_decision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("to_revision = from_revision + 1", name="ck_issue_transition_revision"),
        schema="milai",
    )

    op.create_foreign_key(
        "fk_decision_result_version",
        "steward_decision",
        "claim_version",
        ["tenant_id", "resulting_claim_version_id"],
        ["tenant_id", "claim_version_id"],
        source_schema="milai",
        referent_schema="milai",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_decision_result_issue",
        "steward_decision",
        "open_issue",
        ["tenant_id", "resulting_open_issue_id"],
        ["tenant_id", "issue_id"],
        source_schema="milai",
        referent_schema="milai",
        deferrable=True,
        initially="DEFERRED",
    )

    tenant_tables = (
        "claim",
        "operation_proposal",
        "steward_decision",
        "open_issue",
        "claim_version",
        "claim_head",
        "version_transition",
        "grounding_relation",
        "grounding_block",
        "open_issue_transition",
    )
    for table in tenant_tables:
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.reject_append_only_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'APPEND_ONLY_VIOLATION';
        END
        $$
        """
    )
    for table in (
        "claim",
        "claim_version",
        "version_transition",
        "grounding_relation",
        "steward_decision",
        "open_issue_transition",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON milai.{table}
            FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
            """
        )

    op.execute(
        """
        CREATE VIEW milai.effective_claim_state
        WITH (security_invoker = true)
        AS
        SELECT
          c.tenant_id,
          c.claim_id,
          c.subject_id,
          c.predicate,
          c.claim_type,
          cv.claim_version_id,
          cv.version_number,
          cv.payload,
          cv.scope_predicate,
          cv.valid_time_from,
          cv.valid_time_to,
          cv.system_time,
          cv.lifecycle,
          cv.epistemic_status,
          cv.freshness,
          cv.authority,
          cv.confidence,
          cv.canonical_commit_seq,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation gr
            JOIN milai.evidence_record e
              ON e.tenant_id = gr.tenant_id AND e.evidence_id = gr.evidence_id
            WHERE gr.tenant_id = cv.tenant_id
              AND gr.claim_version_id = cv.claim_version_id
              AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND e.revoked_at IS NULL
              AND e.retention_state = 'READABLE'
              AND e.permission_snapshot @> '{"readable": true}'::jsonb
          ) AS has_live_grounding,
          EXISTS (
            SELECT 1 FROM milai.grounding_block gb
            WHERE gb.tenant_id = cv.tenant_id
              AND gb.claim_version_id = cv.claim_version_id
              AND gb.active
          ) AS has_live_block,
          EXISTS (
            SELECT 1 FROM milai.open_issue oi
            WHERE oi.tenant_id = c.tenant_id
              AND oi.target_claim_id = c.claim_id
              AND oi.status NOT IN ('RESOLVED', 'DISMISSED')
          ) AS has_live_open_issue,
          CASE
            WHEN EXISTS (
              SELECT 1 FROM milai.grounding_block gb
              WHERE gb.tenant_id = cv.tenant_id
                AND gb.claim_version_id = cv.claim_version_id AND gb.active
            ) THEN 'BLOCKED'
            WHEN NOT EXISTS (
              SELECT 1
              FROM milai.grounding_relation gr
              JOIN milai.evidence_record e
                ON e.tenant_id = gr.tenant_id AND e.evidence_id = gr.evidence_id
              WHERE gr.tenant_id = cv.tenant_id
                AND gr.claim_version_id = cv.claim_version_id
                AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                AND e.revoked_at IS NULL
                AND e.retention_state = 'READABLE'
                AND e.permission_snapshot @> '{"readable": true}'::jsonb
            ) THEN 'UNGROUNDED'
            WHEN EXISTS (
              SELECT 1 FROM milai.open_issue oi
              WHERE oi.tenant_id = c.tenant_id AND oi.target_claim_id = c.claim_id
                AND oi.status NOT IN ('RESOLVED', 'DISMISSED')
            ) THEN 'CONFLICTED'
            ELSE 'EFFECTIVE'
          END AS effective_status
        FROM milai.claim c
        JOIN milai.claim_head ch
          ON ch.tenant_id = c.tenant_id AND ch.claim_id = c.claim_id
        JOIN milai.claim_version cv
          ON cv.tenant_id = ch.tenant_id
         AND cv.claim_version_id = ch.current_claim_version_id
        """
    )

    canonical_tables = ", ".join(f"milai.{table}" for table in tenant_tables)
    op.execute(
        f"REVOKE ALL ON TABLE {canonical_tables} "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"GRANT SELECT ON TABLE {canonical_tables} "
        "TO milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON milai.effective_claim_state TO milai_api, milai_steward, milai_audit"
    )
    op.execute("REVOKE ALL ON SEQUENCE milai.canonical_commit_seq FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP VIEW milai.effective_claim_state")
    op.execute("DROP FUNCTION milai.reject_append_only_mutation() CASCADE")
    op.drop_table("open_issue_transition", schema="milai")
    op.drop_table("grounding_block", schema="milai")
    op.drop_table("grounding_relation", schema="milai")
    op.drop_table("version_transition", schema="milai")
    op.drop_table("claim_head", schema="milai")
    op.drop_constraint(
        "fk_decision_result_version", "steward_decision", schema="milai", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_decision_result_issue", "steward_decision", schema="milai", type_="foreignkey"
    )
    op.drop_table("claim_version", schema="milai")
    op.drop_index("uq_open_issue_live_type", table_name="open_issue", schema="milai")
    op.drop_table("open_issue", schema="milai")
    op.drop_table("steward_decision", schema="milai")
    op.drop_table("operation_proposal", schema="milai")
    op.drop_table("claim", schema="milai")
    op.execute("DROP SEQUENCE milai.canonical_commit_seq")
