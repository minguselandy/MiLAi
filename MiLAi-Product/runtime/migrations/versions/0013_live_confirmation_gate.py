"""Validate Chat lineage and live USER_CONFIRMATION Evidence in the DB boundary.

Revision ID: 0013_live_confirmation_gate
Revises: 0012_query_plan_trace

Schema 0.1.x EXPERIMENTAL.
Implementation CANDIDATE.
NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_live_confirmation_gate"
down_revision: str | None = "0012_query_plan_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECORD_CHAT_SIGNATURE = (
    "uuid, uuid, text, text, uuid, uuid, text, jsonb, jsonb, jsonb, boolean, boolean, text, integer"
)


def _create_guarded_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION milai.record_chat_turn(
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
          v_claim_ids uuid[];
          v_evidence_ids uuid[];
          v_issue_ids uuid[];
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF length(p_request_id) NOT BETWEEN 1 AND 128
             OR length(p_answer_text) = 0
             OR p_query_fingerprint !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_claim_ids) <> 'array'
             OR jsonb_typeof(p_evidence_refs) <> 'array'
             OR jsonb_typeof(p_issue_refs) <> 'array'
             OR p_duration_ms < 0
             OR (p_action_sensitive AND NOT p_live_confirmation AND NOT v_abstained)
             OR (NOT v_abstained AND (p_capsule_id IS NULL OR p_retrieval_trace_id IS NULL)) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CHAT_TURN';
          END IF;
          BEGIN
            SELECT COALESCE(array_agg(value::uuid), '{}'::uuid[])
            INTO v_claim_ids FROM jsonb_array_elements_text(p_claim_ids) value;
            SELECT COALESCE(array_agg(value::uuid), '{}'::uuid[])
            INTO v_evidence_ids FROM jsonb_array_elements_text(p_evidence_refs) value;
            SELECT COALESCE(array_agg(value::uuid), '{}'::uuid[])
            INTO v_issue_ids FROM jsonb_array_elements_text(p_issue_refs) value;
          EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CHAT_TURN';
          END;
          IF cardinality(v_claim_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(v_claim_ids) value
             ) OR cardinality(v_evidence_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(v_evidence_ids) value
             ) OR cardinality(v_issue_ids) <> (
               SELECT count(DISTINCT value) FROM unnest(v_issue_ids) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_CHAT_TURN';
          END IF;
          IF (SELECT count(*) FROM milai.claim_version version
              WHERE version.tenant_id = p_tenant_id
                AND version.claim_version_id = ANY(v_claim_ids))
               <> cardinality(v_claim_ids)
             OR (SELECT count(*) FROM milai.evidence_record evidence
                 JOIN milai.content_blob blob
                   ON blob.tenant_id = evidence.tenant_id
                  AND blob.blob_id = evidence.blob_id
                 WHERE evidence.tenant_id = p_tenant_id
                   AND evidence.evidence_id = ANY(v_evidence_ids)
                   AND evidence.revoked_at IS NULL
                   AND evidence.retention_state = 'READABLE'
                   AND evidence.permission_snapshot ->> 'readable' = 'true'
                   AND blob.physical_delete_state = 'PRESENT')
                  <> cardinality(v_evidence_ids)
             OR (SELECT count(*) FROM milai.open_issue issue
                 WHERE issue.tenant_id = p_tenant_id
                   AND issue.issue_id = ANY(v_issue_ids)
                   AND issue.status NOT IN ('RESOLVED', 'DISMISSED'))
                  <> cardinality(v_issue_ids) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CHAT_LINEAGE_INVALID';
          END IF;
          IF p_action_sensitive AND p_live_confirmation AND NOT EXISTS (
            SELECT 1 FROM milai.evidence_record evidence
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.evidence_id = ANY(v_evidence_ids)
              AND evidence.source_type = 'USER_CONFIRMATION'
              AND evidence.source_ref LIKE 'chat-confirmation:%'
              AND evidence.subject_id = 'action-sensitive-chat'
              AND evidence.observed_at BETWEEN CURRENT_TIMESTAMP - interval '5 minutes'
                                           AND CURRENT_TIMESTAMP + interval '5 minutes'
              AND evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
              AND evidence.permission_snapshot ->> 'readable' = 'true'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LIVE_CONFIRMATION_REQUIRED';
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


def _create_legacy_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION milai.record_chat_turn(
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


def upgrade() -> None:
    _create_guarded_function()
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_chat_turn({RECORD_CHAT_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_chat_turn({RECORD_CHAT_SIGNATURE}) TO milai_api"
    )


def downgrade() -> None:
    _create_legacy_function()
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.record_chat_turn({RECORD_CHAT_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.record_chat_turn({RECORD_CHAT_SIGNATURE}) TO milai_api"
    )
