"""Add replayable Episode capture and governed minimal Settlement.

Revision ID: 0011_episode_settlement
Revises: 0010_backup_operations

Schema 0.1.x EXPERIMENTAL.
Implementation CANDIDATE.
NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_episode_settlement"
down_revision: str | None = "0010_backup_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_SIGNATURE = "uuid, uuid, text, uuid[], uuid[], uuid[], text, text"
SETTLE_SIGNATURE = "uuid, uuid, uuid, integer, uuid[], uuid[], text, text, text"


def _tenant_policy(table: str) -> None:
    op.execute(f"ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON milai.{table}
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
    op.create_table(
        "episode",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "evidence_refs",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "chat_turn_refs",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "context_capsule_refs",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("capture_idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "episode_id", name="pk_episode"),
        sa.UniqueConstraint(
            "tenant_id", "capture_idempotency_key", name="uq_episode_capture_idempotency"
        ),
        sa.CheckConstraint("length(btrim(subject_id)) > 0", name="ck_episode_subject"),
        sa.CheckConstraint("status IN ('OPEN', 'SETTLED')", name="ck_episode_status"),
        sa.CheckConstraint("revision >= 1", name="ck_episode_revision"),
        sa.CheckConstraint(
            "cardinality(evidence_refs) + cardinality(chat_turn_refs) + "
            "cardinality(context_capsule_refs) > 0",
            name="ck_episode_has_replayable_item",
        ),
        sa.CheckConstraint(
            "cardinality(evidence_refs) <= 256 AND cardinality(chat_turn_refs) <= 256 "
            "AND cardinality(context_capsule_refs) <= 256",
            name="ck_episode_ref_limits",
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND settled_at IS NULL) OR "
            "(status = 'SETTLED' AND settled_at IS NOT NULL)",
            name="ck_episode_settled_state",
        ),
        sa.CheckConstraint("request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_episode_fingerprint"),
        schema="milai",
    )
    op.create_table(
        "episode_settlement",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("settlement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_revision", sa.Integer(), nullable=False),
        sa.Column("to_revision", sa.Integer(), nullable=False),
        sa.Column(
            "residual_proposal_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "open_issue_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "expired_context_capsule_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "settlement_id", name="pk_episode_settlement"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "episode_id"],
            ["milai.episode.tenant_id", "milai.episode.episode_id"],
            name="fk_episode_settlement_episode",
        ),
        sa.UniqueConstraint("tenant_id", "episode_id", name="uq_episode_single_settlement"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_episode_settlement_idempotency"
        ),
        sa.CheckConstraint(
            "to_revision = from_revision + 1", name="ck_episode_settlement_revision"
        ),
        sa.CheckConstraint(
            "cardinality(residual_proposal_ids) <= 3", name="ck_episode_residual_limit"
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_episode_settlement_fingerprint",
        ),
        schema="milai",
    )
    op.create_table(
        "episode_transition",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("from_revision", sa.Integer(), nullable=True),
        sa.Column("to_revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("settlement_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("tenant_id", "transition_id", name="pk_episode_transition"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "episode_id"],
            ["milai.episode.tenant_id", "milai.episode.episode_id"],
            name="fk_episode_transition_episode",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "settlement_id"],
            ["milai.episode_settlement.tenant_id", "milai.episode_settlement.settlement_id"],
            name="fk_episode_transition_settlement",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("to_status IN ('OPEN', 'SETTLED')", name="ck_episode_transition_status"),
        sa.CheckConstraint(
            "to_revision >= 1 AND (from_revision IS NULL OR to_revision = from_revision + 1)",
            name="ck_episode_transition_revision",
        ),
        schema="milai",
    )

    for table in ("episode", "episode_settlement", "episode_transition"):
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.protect_episode_capture()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.episode_id IS DISTINCT FROM OLD.episode_id
             OR NEW.subject_id IS DISTINCT FROM OLD.subject_id
             OR NEW.evidence_refs IS DISTINCT FROM OLD.evidence_refs
             OR NEW.chat_turn_refs IS DISTINCT FROM OLD.chat_turn_refs
             OR NEW.context_capsule_refs IS DISTINCT FROM OLD.context_capsule_refs
             OR NEW.capture_idempotency_key IS DISTINCT FROM OLD.capture_idempotency_key
             OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR NEW.created_by_actor_id IS DISTINCT FROM OLD.created_by_actor_id THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_EPISODE_CAPTURE';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER episode_capture_identity_immutable
        BEFORE UPDATE ON milai.episode
        FOR EACH ROW EXECUTE FUNCTION milai.protect_episode_capture()
        """
    )
    for table in ("episode_settlement", "episode_transition"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON milai.{table}
            FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION milai.create_episode(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_subject_id text,
          p_evidence_refs uuid[],
          p_chat_turn_refs uuid[],
          p_context_capsule_refs uuid[],
          p_idempotency_key text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_episode_id uuid;
          v_outbox_id uuid;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          p_evidence_refs := COALESCE(p_evidence_refs, '{}'::uuid[]);
          p_chat_turn_refs := COALESCE(p_chat_turn_refs, '{}'::uuid[]);
          p_context_capsule_refs := COALESCE(p_context_capsule_refs, '{}'::uuid[]);
          IF length(btrim(p_subject_id)) = 0
             OR cardinality(p_evidence_refs) + cardinality(p_chat_turn_refs)
                + cardinality(p_context_capsule_refs) = 0
             OR cardinality(p_evidence_refs) > 256
             OR cardinality(p_chat_turn_refs) > 256
             OR cardinality(p_context_capsule_refs) > 256 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EPISODE';
          END IF;
          IF cardinality(p_evidence_refs) <> (
               SELECT count(DISTINCT value) FROM unnest(p_evidence_refs) value
             ) OR cardinality(p_chat_turn_refs) <> (
               SELECT count(DISTINCT value) FROM unnest(p_chat_turn_refs) value
             ) OR cardinality(p_context_capsule_refs) <> (
               SELECT count(DISTINCT value) FROM unnest(p_context_capsule_refs) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_EPISODE';
          END IF;
          IF (SELECT count(*) FROM milai.evidence_record e
              WHERE e.tenant_id = p_tenant_id AND e.evidence_id = ANY(p_evidence_refs))
               <> cardinality(p_evidence_refs)
             OR (SELECT count(*) FROM milai.chat_turn c
                 WHERE c.tenant_id = p_tenant_id AND c.chat_turn_id = ANY(p_chat_turn_refs))
               <> cardinality(p_chat_turn_refs)
             OR (SELECT count(*) FROM milai.context_capsule c
                 WHERE c.tenant_id = p_tenant_id
                   AND c.capsule_id = ANY(p_context_capsule_refs))
               <> cardinality(p_context_capsule_refs) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EPISODE_REFERENCE_INVALID';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'EPISODE_CAPTURE', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id AND operation_family = 'EPISODE_CAPTURE'
            AND idempotency_key = p_idempotency_key FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          v_episode_id := gen_random_uuid();
          INSERT INTO milai.episode (
            tenant_id, episode_id, subject_id, status, revision,
            evidence_refs, chat_turn_refs, context_capsule_refs,
            capture_idempotency_key, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_episode_id, p_subject_id, 'OPEN', 1,
            p_evidence_refs, p_chat_turn_refs, p_context_capsule_refs,
            p_idempotency_key, p_request_fingerprint, p_actor_id
          );
          INSERT INTO milai.episode_transition (
            tenant_id, transition_id, episode_id, from_status, to_status,
            from_revision, to_revision, event_type, created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), v_episode_id, NULL, 'OPEN',
            NULL, 1, 'EPISODE_CAPTURED', p_actor_id
          );
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'EPISODE_CAPTURED', NULL,
            jsonb_build_object('episode_id', v_episode_id), p_actor_id
          );
          v_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id, event_type,
            payload, priority, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_outbox_id, 'EPISODE', v_episode_id, 'EPISODE_CAPTURED',
            jsonb_build_object('episode_id', v_episode_id), 90, p_actor_id
          );
          v_response := jsonb_build_object(
            'episode_id', v_episode_id, 'status', 'OPEN', 'revision', 1,
            'outbox_id', v_outbox_id, 'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id AND operation_family = 'EPISODE_CAPTURE'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.settle_episode(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_episode_id uuid,
          p_expected_revision integer,
          p_residual_proposal_ids uuid[],
          p_open_issue_ids uuid[],
          p_confirmation text,
          p_idempotency_key text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_episode milai.episode%ROWTYPE;
          v_settlement_id uuid;
          v_outbox_id uuid;
          v_expired_contexts uuid[];
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          p_residual_proposal_ids := COALESCE(p_residual_proposal_ids, '{}'::uuid[]);
          p_open_issue_ids := COALESCE(p_open_issue_ids, '{}'::uuid[]);
          IF p_confirmation <> 'SETTLE' OR cardinality(p_residual_proposal_ids) > 3 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'SETTLEMENT_NOT_AUTHORIZED';
          END IF;
          IF cardinality(p_residual_proposal_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(p_residual_proposal_ids) value
             ) OR cardinality(p_open_issue_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(p_open_issue_ids) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_SETTLEMENT';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'EPISODE_SETTLEMENT', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id AND operation_family = 'EPISODE_SETTLEMENT'
            AND idempotency_key = p_idempotency_key FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          SELECT * INTO v_episode FROM milai.episode
          WHERE tenant_id = p_tenant_id AND episode_id = p_episode_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EPISODE_NOT_FOUND';
          END IF;
          IF v_episode.status <> 'OPEN' OR v_episode.revision <> p_expected_revision THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EPISODE_REVISION_CONFLICT';
          END IF;
          IF (SELECT count(*) FROM milai.operation_proposal p
              WHERE p.tenant_id = p_tenant_id
                AND p.proposal_id = ANY(p_residual_proposal_ids)
                AND p.status = 'PENDING_REVIEW') <> cardinality(p_residual_proposal_ids)
             OR (SELECT count(*) FROM milai.open_issue i
                 WHERE i.tenant_id = p_tenant_id AND i.issue_id = ANY(p_open_issue_ids)
                   AND i.status NOT IN ('RESOLVED', 'DISMISSED'))
                <> cardinality(p_open_issue_ids) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'SETTLEMENT_REFERENCE_INVALID';
          END IF;

          SELECT COALESCE(array_agg(capsule_id ORDER BY capsule_id), '{}'::uuid[])
          INTO v_expired_contexts
          FROM milai.context_capsule
          WHERE tenant_id = p_tenant_id
            AND capsule_id = ANY(v_episode.context_capsule_refs)
            AND status = 'ACTIVE';
          UPDATE milai.context_capsule
          SET status = 'EXPIRED', invalidated_at = CURRENT_TIMESTAMP,
              invalidation_reason = 'EPISODE_SETTLED'
          WHERE tenant_id = p_tenant_id AND capsule_id = ANY(v_expired_contexts);
          UPDATE milai.context_pointer
          SET state = 'INVALIDATED', invalidated_at = CURRENT_TIMESTAMP,
              invalidation_reason = 'EPISODE_SETTLED'
          WHERE tenant_id = p_tenant_id AND capsule_id = ANY(v_expired_contexts)
            AND state = 'ACTIVE';

          v_settlement_id := gen_random_uuid();
          UPDATE milai.episode SET status = 'SETTLED', revision = revision + 1,
            settled_at = CURRENT_TIMESTAMP
          WHERE tenant_id = p_tenant_id AND episode_id = p_episode_id
            AND status = 'OPEN' AND revision = p_expected_revision;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EPISODE_REVISION_CONFLICT';
          END IF;
          INSERT INTO milai.episode_settlement (
            tenant_id, settlement_id, episode_id, from_revision, to_revision,
            residual_proposal_ids, open_issue_ids, expired_context_capsule_ids,
            idempotency_key, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_settlement_id, p_episode_id,
            p_expected_revision, p_expected_revision + 1,
            p_residual_proposal_ids, p_open_issue_ids, v_expired_contexts,
            p_idempotency_key, p_request_fingerprint, p_actor_id
          );
          INSERT INTO milai.episode_transition (
            tenant_id, transition_id, episode_id, from_status, to_status,
            from_revision, to_revision, event_type, settlement_id, created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), p_episode_id, 'OPEN', 'SETTLED',
            p_expected_revision, p_expected_revision + 1,
            'EPISODE_SETTLED', v_settlement_id, p_actor_id
          );
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'EPISODE_SETTLED', NULL,
            jsonb_build_object('episode_id', p_episode_id,
              'settlement_id', v_settlement_id), p_actor_id
          );
          v_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id, event_type,
            payload, priority, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_outbox_id, 'EPISODE', p_episode_id, 'EPISODE_SETTLED',
            jsonb_build_object('episode_id', p_episode_id,
              'settlement_id', v_settlement_id), 70, p_actor_id
          );
          v_response := jsonb_build_object(
            'episode_id', p_episode_id, 'settlement_id', v_settlement_id,
            'status', 'SETTLED', 'revision', p_expected_revision + 1,
            'residual_proposal_ids', p_residual_proposal_ids,
            'open_issue_ids', p_open_issue_ids,
            'expired_context_capsule_ids', v_expired_contexts,
            'outbox_id', v_outbox_id, 'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id AND operation_family = 'EPISODE_SETTLEMENT'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
    )

    tables = "milai.episode, milai.episode_settlement, milai.episode_transition"
    op.execute(
        f"REVOKE ALL ON TABLE {tables} FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(f"GRANT SELECT ON TABLE {tables} TO milai_api, milai_steward, milai_audit")
    op.execute(f"REVOKE ALL ON FUNCTION milai.create_episode({CREATE_SIGNATURE}) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION milai.create_episode({CREATE_SIGNATURE}) TO milai_api")
    op.execute(f"REVOKE ALL ON FUNCTION milai.settle_episode({SETTLE_SIGNATURE}) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.settle_episode({SETTLE_SIGNATURE}) TO milai_steward"
    )
    op.execute("REVOKE ALL ON FUNCTION milai.protect_episode_capture() FROM PUBLIC")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS milai.settle_episode({SETTLE_SIGNATURE})")
    op.execute(f"DROP FUNCTION IF EXISTS milai.create_episode({CREATE_SIGNATURE})")
    op.execute("DROP TRIGGER IF EXISTS episode_capture_identity_immutable ON milai.episode")
    op.execute("DROP FUNCTION IF EXISTS milai.protect_episode_capture()")
    for table in ("episode_transition", "episode_settlement"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON milai.{table}")
    op.drop_table("episode_transition", schema="milai")
    op.drop_table("episode_settlement", schema="milai")
    op.drop_table("episode", schema="milai")
