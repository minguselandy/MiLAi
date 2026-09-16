"""Add governed minimal context capsules and traceable chat turns.

Revision ID: 0009_context_chat
Revises: 0008_retrieval_gate

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_context_chat"
down_revision: str | None = "0008_retrieval_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_CAPSULE_SIGNATURE = "uuid, uuid, uuid, jsonb, integer, timestamptz"
RECOVER_POINTER_SIGNATURE = "uuid, uuid, uuid"
RECORD_CHAT_SIGNATURE = (
    "uuid, uuid, text, text, uuid, uuid, text, jsonb, jsonb, jsonb, boolean, boolean, text, integer"
)


def upgrade() -> None:
    op.add_column(
        "context_capsule",
        sa.Column("retrieval_trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="milai",
    )
    op.add_column(
        "context_capsule",
        sa.Column("byte_budget", sa.Integer(), nullable=False, server_default="65536"),
        schema="milai",
    )
    op.add_column(
        "context_capsule",
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="2"),
        schema="milai",
    )
    op.create_foreign_key(
        "fk_context_capsule_retrieval_trace",
        "context_capsule",
        "retrieval_trace",
        ["tenant_id", "retrieval_trace_id"],
        ["tenant_id", "trace_id"],
        source_schema="milai",
        referent_schema="milai",
    )
    op.create_check_constraint(
        "ck_context_capsule_budget",
        "context_capsule",
        "byte_budget >= 64 AND byte_budget <= 1000000 "
        "AND byte_size >= 2 AND byte_size <= byte_budget",
        schema="milai",
    )

    op.add_column(
        "context_pointer",
        sa.Column("content_hash_snapshot", sa.String(length=64), nullable=True),
        schema="milai",
    )
    op.add_column(
        "context_pointer",
        sa.Column("permission_snapshot", postgresql.JSONB(), nullable=True),
        schema="milai",
    )
    op.add_column(
        "context_pointer",
        sa.Column("retention_state_snapshot", sa.Text(), nullable=True),
        schema="milai",
    )
    op.execute(
        """
        UPDATE milai.context_pointer pointer
        SET content_hash_snapshot = blob.content_hash,
            permission_snapshot = evidence.permission_snapshot,
            retention_state_snapshot = evidence.retention_state
        FROM milai.evidence_record evidence
        JOIN milai.content_blob blob
          ON blob.tenant_id = evidence.tenant_id
         AND blob.blob_id = evidence.blob_id
        WHERE evidence.tenant_id = pointer.tenant_id
          AND evidence.evidence_id = pointer.evidence_id
        """
    )
    op.alter_column("context_pointer", "content_hash_snapshot", nullable=False, schema="milai")
    op.alter_column("context_pointer", "permission_snapshot", nullable=False, schema="milai")
    op.alter_column("context_pointer", "retention_state_snapshot", nullable=False, schema="milai")
    op.create_check_constraint(
        "ck_context_pointer_content_hash",
        "context_pointer",
        "content_hash_snapshot ~ '^[0-9a-f]{64}$'",
        schema="milai",
    )
    op.create_check_constraint(
        "ck_context_pointer_permission",
        "context_pointer",
        "jsonb_typeof(permission_snapshot) = 'object'",
        schema="milai",
    )

    op.create_table(
        "chat_turn",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chat_turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("query_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("capsule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retrieval_trace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("used_claim_version_ids", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("open_issue_refs", postgresql.JSONB(), nullable=False),
        sa.Column("action_sensitive", sa.Boolean(), nullable=False),
        sa.Column("live_confirmation", sa.Boolean(), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("abstention_reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "chat_turn_id", name="pk_chat_turn"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "capsule_id"],
            ["milai.context_capsule.tenant_id", "milai.context_capsule.capsule_id"],
            name="fk_chat_turn_capsule",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "retrieval_trace_id"],
            ["milai.retrieval_trace.tenant_id", "milai.retrieval_trace.trace_id"],
            name="fk_chat_turn_retrieval_trace",
        ),
        sa.CheckConstraint("query_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_chat_turn_fingerprint"),
        sa.CheckConstraint(
            "jsonb_typeof(used_claim_version_ids) = 'array' "
            "AND jsonb_typeof(evidence_refs) = 'array' "
            "AND jsonb_typeof(open_issue_refs) = 'array'",
            name="ck_chat_turn_refs",
        ),
        sa.CheckConstraint(
            "(abstained AND abstention_reason IS NOT NULL) "
            "OR (NOT abstained AND abstention_reason IS NULL)",
            name="ck_chat_turn_abstention",
        ),
        sa.CheckConstraint(
            "NOT action_sensitive OR live_confirmation OR abstained",
            name="ck_chat_turn_confirmation",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_chat_turn_duration"),
        schema="milai",
    )
    op.create_index(
        "ix_chat_turn_created",
        "chat_turn",
        ["tenant_id", sa.text("created_at DESC")],
        schema="milai",
    )
    op.execute("ALTER TABLE milai.chat_turn ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.chat_turn FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY chat_turn_tenant_isolation
        ON milai.chat_turn
        USING (tenant_id = milai.current_tenant_id())
        WITH CHECK (tenant_id = milai.current_tenant_id())
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_chat_turn_append_only
        BEFORE UPDATE OR DELETE ON milai.chat_turn
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.create_context_capsule(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_retrieval_trace_id uuid,
          p_sections jsonb,
          p_byte_budget integer,
          p_expires_at timestamptz
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_trace milai.retrieval_trace%ROWTYPE;
          v_capsule_id uuid := gen_random_uuid();
          v_byte_size integer;
          v_content_hash text;
          v_claim_version_ids uuid[];
          v_gate jsonb;
          v_evidence jsonb;
          v_pointer_id uuid;
          v_evidence_id uuid;
          v_pointer_hash text;
          v_pointer_ids jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_trace FROM milai.retrieval_trace
          WHERE tenant_id = p_tenant_id AND trace_id = p_retrieval_trace_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'RETRIEVAL_TRACE_NOT_FOUND';
          END IF;
          IF jsonb_typeof(p_sections) <> 'object'
             OR NOT p_sections ?& ARRAY[
               'ACTIVE GOAL', 'ACTIVE STATE', 'OPEN ISSUES', 'CONSTRAINTS',
               'RETRIEVED EVIDENCE', 'TRACE POINTERS'
             ]
             OR (SELECT count(*) FROM jsonb_object_keys(p_sections)) <> 6
             OR jsonb_typeof(p_sections -> 'ACTIVE GOAL') <> 'object'
             OR length(btrim(p_sections -> 'ACTIVE GOAL' ->> 'text')) = 0
             OR jsonb_typeof(p_sections -> 'ACTIVE STATE') <> 'array'
             OR jsonb_typeof(p_sections -> 'OPEN ISSUES') <> 'array'
             OR jsonb_typeof(p_sections -> 'CONSTRAINTS') <> 'array'
             OR jsonb_typeof(p_sections -> 'RETRIEVED EVIDENCE') <> 'array'
             OR p_sections -> 'TRACE POINTERS' ->> 'retrieval_trace_id'
                IS DISTINCT FROM p_retrieval_trace_id::text
             OR p_byte_budget < 64 OR p_byte_budget > 1000000
             OR p_expires_at <= CURRENT_TIMESTAMP
             OR p_expires_at > CURRENT_TIMESTAMP + interval '7 days' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CONTEXT_CAPSULE';
          END IF;
          v_byte_size := octet_length(p_sections::text);
          IF v_byte_size > p_byte_budget THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'CONTEXT_BUDGET_INFEASIBLE';
          END IF;

          SELECT COALESCE(array_agg((state ->> 'claim_version_id')::uuid), '{}'::uuid[])
          INTO v_claim_version_ids
          FROM jsonb_array_elements(p_sections -> 'ACTIVE STATE') state;
          IF EXISTS (
            SELECT 1 FROM unnest(v_claim_version_ids) version_id
            WHERE NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_trace.accepted_candidates) accepted
              WHERE accepted ->> 'claim_version_id' = version_id::text
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;
          v_gate := milai.evaluate_canonical_candidates(
            p_tenant_id, p_actor_id, v_claim_version_ids,
            v_trace.required_authority, v_trace.requested_scope, v_trace.as_of
          );
          IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_gate) outcome
            WHERE NOT (outcome ->> 'accepted')::boolean
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;

          IF EXISTS (
            SELECT 1 FROM milai.open_issue issue
            WHERE issue.tenant_id = p_tenant_id
              AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
              AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(p_sections -> 'OPEN ISSUES') item
                WHERE item ->> 'issue_id' = issue.issue_id::text
                  AND item ->> 'target_claim_id' = issue.target_claim_id::text
                  AND item ->> 'status' = issue.status
                  AND item -> 'discharge_rule' = issue.discharge_rule
              )
          ) OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_sections -> 'OPEN ISSUES') item
            WHERE NOT EXISTS (
              SELECT 1 FROM milai.open_issue issue
              WHERE issue.tenant_id = p_tenant_id
                AND issue.issue_id = (item ->> 'issue_id')::uuid
                AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_ISSUE_OMITTED';
          END IF;

          FOR v_evidence IN
            SELECT value FROM jsonb_array_elements(p_sections -> 'RETRIEVED EVIDENCE')
          LOOP
            v_pointer_id := (v_evidence ->> 'pointer_id')::uuid;
            v_evidence_id := (v_evidence ->> 'evidence_id')::uuid;
            IF NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_trace.accepted_candidates) accepted,
                            jsonb_array_elements_text(accepted -> 'evidence_ids') evidence_id
              WHERE evidence_id = v_evidence_id::text
            ) OR NOT EXISTS (
              SELECT 1 FROM milai.evidence_record evidence
              WHERE evidence.tenant_id = p_tenant_id
                AND evidence.evidence_id = v_evidence_id
                AND evidence.revoked_at IS NULL
                AND evidence.retention_state = 'READABLE'
                AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
            ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
            END IF;
          END LOOP;

          v_content_hash := encode(sha256(convert_to(p_sections::text, 'UTF8')), 'hex');
          INSERT INTO milai.context_capsule (
            tenant_id, capsule_id, status, protected_sections, content_hash,
            retrieval_trace_id, byte_budget, byte_size, expires_at,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, v_capsule_id, 'ACTIVE', p_sections, v_content_hash,
            p_retrieval_trace_id, p_byte_budget, v_byte_size, p_expires_at,
            p_actor_id
          );

          FOR v_evidence IN
            SELECT value FROM jsonb_array_elements(p_sections -> 'RETRIEVED EVIDENCE')
          LOOP
            v_pointer_id := (v_evidence ->> 'pointer_id')::uuid;
            v_evidence_id := (v_evidence ->> 'evidence_id')::uuid;
            INSERT INTO milai.context_pointer (
              tenant_id, pointer_id, capsule_id, evidence_id, pointer_hash,
              content_hash_snapshot, permission_snapshot,
              retention_state_snapshot, state, created_by_actor_id
            ) SELECT
              p_tenant_id, v_pointer_id, v_capsule_id, evidence.evidence_id,
              encode(sha256(convert_to(
                evidence.evidence_id::text || ':' || blob.content_hash || ':' ||
                evidence.permission_snapshot::text || ':' || evidence.retention_state,
                'UTF8'
              )), 'hex'),
              blob.content_hash, evidence.permission_snapshot,
              evidence.retention_state, 'ACTIVE', p_actor_id
            FROM milai.evidence_record evidence
            JOIN milai.content_blob blob
              ON blob.tenant_id = evidence.tenant_id
             AND blob.blob_id = evidence.blob_id
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.evidence_id = v_evidence_id;
            v_pointer_ids := v_pointer_ids || jsonb_build_array(v_pointer_id);
          END LOOP;
          RETURN jsonb_build_object(
            'capsule_id', v_capsule_id,
            'content_hash', v_content_hash,
            'byte_budget', p_byte_budget,
            'byte_size', v_byte_size,
            'expires_at', p_expires_at,
            'pointer_ids', v_pointer_ids
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.recover_context_pointer(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_pointer_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_pointer milai.context_pointer%ROWTYPE;
          v_capsule milai.context_capsule%ROWTYPE;
          v_evidence milai.evidence_record%ROWTYPE;
          v_blob milai.content_blob%ROWTYPE;
          v_hash text;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_pointer FROM milai.context_pointer
          WHERE tenant_id = p_tenant_id AND pointer_id = p_pointer_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_NOT_FOUND';
          END IF;
          SELECT * INTO STRICT v_capsule FROM milai.context_capsule
          WHERE tenant_id = p_tenant_id AND capsule_id = v_pointer.capsule_id;
          IF v_capsule.status <> 'ACTIVE' OR v_capsule.expires_at <= CURRENT_TIMESTAMP
             OR v_pointer.state <> 'ACTIVE' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;
          SELECT * INTO STRICT v_evidence FROM milai.evidence_record
          WHERE tenant_id = p_tenant_id AND evidence_id = v_pointer.evidence_id;
          SELECT * INTO STRICT v_blob FROM milai.content_blob
          WHERE tenant_id = p_tenant_id AND blob_id = v_evidence.blob_id;
          v_hash := encode(sha256(convert_to(
            v_evidence.evidence_id::text || ':' || v_blob.content_hash || ':' ||
            v_evidence.permission_snapshot::text || ':' || v_evidence.retention_state,
            'UTF8'
          )), 'hex');
          IF v_evidence.revoked_at IS NOT NULL
             OR v_evidence.retention_state <> 'READABLE'
             OR NOT v_evidence.permission_snapshot @> '{"readable": true}'::jsonb
             OR v_blob.physical_delete_state <> 'PRESENT'
             OR v_blob.content_hash <> v_pointer.content_hash_snapshot
             OR v_evidence.permission_snapshot <> v_pointer.permission_snapshot
             OR v_evidence.retention_state <> v_pointer.retention_state_snapshot
             OR v_hash <> v_pointer.pointer_hash THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;
          RETURN jsonb_build_object(
            'pointer_id', v_pointer.pointer_id,
            'capsule_id', v_pointer.capsule_id,
            'evidence_id', v_evidence.evidence_id,
            'content_hash', v_blob.content_hash,
            'storage_uri', v_blob.storage_uri,
            'byte_length', v_blob.byte_length,
            'media_type', v_blob.media_type,
            'permission_snapshot', v_evidence.permission_snapshot,
            'retention_state', v_evidence.retention_state
          );
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.record_chat_turn(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_request_id text,
          p_query_fingerprint text,
          p_capsule_id uuid,
          p_retrieval_trace_id uuid,
          p_answer_text text,
          p_claim_ids jsonb,
          p_evidence_refs jsonb,
          p_issue_refs jsonb,
          p_action_sensitive boolean,
          p_live_confirmation boolean,
          p_abstention_reason text,
          p_duration_ms integer
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_chat_turn_id uuid := gen_random_uuid();
          v_abstained boolean := p_abstention_reason IS NOT NULL;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_query_fingerprint !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_claim_ids) <> 'array'
             OR jsonb_typeof(p_evidence_refs) <> 'array'
             OR jsonb_typeof(p_issue_refs) <> 'array'
             OR p_duration_ms < 0
             OR (p_action_sensitive AND NOT p_live_confirmation AND NOT v_abstained)
             OR (NOT v_abstained AND (p_capsule_id IS NULL OR p_retrieval_trace_id IS NULL)) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CHAT_TURN';
          END IF;
          INSERT INTO milai.chat_turn (
            tenant_id, chat_turn_id, request_id, query_fingerprint,
            capsule_id, retrieval_trace_id, answer_text,
            used_claim_version_ids, evidence_refs, open_issue_refs,
            action_sensitive, live_confirmation, abstained,
            abstention_reason, duration_ms, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_chat_turn_id, p_request_id, p_query_fingerprint,
            p_capsule_id, p_retrieval_trace_id, p_answer_text,
            p_claim_ids, p_evidence_refs, p_issue_refs,
            p_action_sensitive, p_live_confirmation, v_abstained,
            p_abstention_reason, p_duration_ms, p_actor_id
          );
          RETURN v_chat_turn_id;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON TABLE milai.chat_turn "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute("GRANT SELECT ON TABLE milai.chat_turn TO milai_api, milai_steward, milai_audit")
    for signature, name in (
        (CREATE_CAPSULE_SIGNATURE, "create_context_capsule"),
        (RECOVER_POINTER_SIGNATURE, "recover_context_pointer"),
        (RECORD_CHAT_SIGNATURE, "record_chat_turn"),
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_api")


def downgrade() -> None:
    for signature, name in (
        (RECORD_CHAT_SIGNATURE, "record_chat_turn"),
        (RECOVER_POINTER_SIGNATURE, "recover_context_pointer"),
        (CREATE_CAPSULE_SIGNATURE, "create_context_capsule"),
    ):
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.drop_index("ix_chat_turn_created", table_name="chat_turn", schema="milai")
    op.drop_table("chat_turn", schema="milai")
    op.drop_constraint(
        "ck_context_pointer_permission", "context_pointer", schema="milai", type_="check"
    )
    op.drop_constraint(
        "ck_context_pointer_content_hash", "context_pointer", schema="milai", type_="check"
    )
    op.drop_column("context_pointer", "retention_state_snapshot", schema="milai")
    op.drop_column("context_pointer", "permission_snapshot", schema="milai")
    op.drop_column("context_pointer", "content_hash_snapshot", schema="milai")
    op.drop_constraint(
        "ck_context_capsule_budget", "context_capsule", schema="milai", type_="check"
    )
    op.drop_constraint(
        "fk_context_capsule_retrieval_trace",
        "context_capsule",
        schema="milai",
        type_="foreignkey",
    )
    op.drop_column("context_capsule", "byte_size", schema="milai")
    op.drop_column("context_capsule", "byte_budget", schema="milai")
    op.drop_column("context_capsule", "retrieval_trace_id", schema="milai")
