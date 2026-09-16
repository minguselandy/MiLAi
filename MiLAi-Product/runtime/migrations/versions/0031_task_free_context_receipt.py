"""Add task-free ContextReceipt issuance on the existing ContextCapsule store.

Revision ID: 0031_task_free_receipt
Revises: 0030_memory_state_view_gate

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
ContextReceipt remains a wire view: this migration creates no table and stores
no second canonical state.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_task_free_receipt"
down_revision: str | None = "0030_memory_state_view_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_RECEIPT_SIGNATURE = "uuid, uuid, uuid, jsonb, integer, timestamptz"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.create_task_free_context_capsule(
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
          v_metadata jsonb;
          v_coverage jsonb;
          v_claim_version_ids uuid[];
          v_gate jsonb;
          v_projection jsonb;
          v_epistemic text[];
          v_valid_at timestamptz;
          v_known_at timestamptz;
          v_historical boolean;
          v_evidence jsonb;
          v_pointer_id uuid;
          v_evidence_id uuid;
          v_pointer_ids jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_trace
          FROM milai.retrieval_trace trace
          WHERE trace.tenant_id = p_tenant_id
            AND trace.trace_id = p_retrieval_trace_id
            AND trace.created_by_actor_id = p_actor_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'RETRIEVAL_TRACE_NOT_FOUND';
          END IF;

          IF jsonb_typeof(p_sections) <> 'object'
             OR NOT p_sections ?& ARRAY[
               'MEMORY STATE VIEW', 'OPEN ISSUE IDS', 'RETRIEVED EVIDENCE',
               'TRACE POINTERS', 'RECEIPT METADATA'
             ]
             OR (SELECT count(*) FROM jsonb_object_keys(p_sections)) <> 5
             OR p_sections ? 'ACTIVE GOAL'
             OR p_sections ? 'CONSTRAINTS'
             OR jsonb_typeof(p_sections -> 'MEMORY STATE VIEW') <> 'object'
             OR p_sections #>> '{MEMORY STATE VIEW,schema_version}'
                IS DISTINCT FROM 'access-outcome-v0.1'
             OR p_sections #>> '{MEMORY STATE VIEW,status}'
                NOT IN ('HIT', 'PARTIAL')
             OR jsonb_typeof(p_sections #> '{MEMORY STATE VIEW,items}') <> 'array'
             OR jsonb_array_length(p_sections #> '{MEMORY STATE VIEW,items}') = 0
             OR jsonb_typeof(p_sections -> 'OPEN ISSUE IDS') <> 'array'
             OR jsonb_typeof(p_sections -> 'RETRIEVED EVIDENCE') <> 'array'
             OR jsonb_typeof(p_sections -> 'TRACE POINTERS') <> 'object'
             OR p_sections #>> '{TRACE POINTERS,retrieval_trace_id}'
                IS DISTINCT FROM p_retrieval_trace_id::text
             OR jsonb_typeof(p_sections -> 'RECEIPT METADATA') <> 'object'
             OR p_byte_budget < 64 OR p_byte_budget > 1000000
             OR p_expires_at <= CURRENT_TIMESTAMP
             OR p_expires_at > CURRENT_TIMESTAMP + interval '1 day' THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'INVALID_TASK_FREE_CONTEXT_CAPSULE';
          END IF;

          v_metadata := p_sections -> 'RECEIPT METADATA';
          v_coverage := v_metadata -> 'requirement_coverage';
          IF v_metadata ->> 'schema_version' <> 'context-receipt-v0.1'
             OR jsonb_typeof(v_coverage) <> 'object'
             OR v_metadata ->> 'dependency_digest' !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(v_metadata -> 'canonical_position') <> 'number'
             OR (v_metadata ->> 'canonical_position')::bigint < 0
             OR jsonb_typeof(v_metadata -> 'invalidation_sequence') <> 'number'
             OR (v_metadata ->> 'invalidation_sequence')::bigint < 0
             OR v_metadata ->> 'freshness_at_issue' NOT IN ('CURRENT', 'STALE')
             OR v_metadata ->> 'consistency_mode_at_issue' NOT IN (
               'EVENTUAL', 'READ_YOUR_WRITES', 'CANONICAL_REQUIRED'
             )
             OR jsonb_typeof(v_metadata -> 'historical') <> 'boolean'
             OR jsonb_typeof(v_coverage -> 'requested_scope') <> 'object'
             OR v_coverage ->> 'required_authority' NOT IN (
               'INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED'
             ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'INVALID_TASK_FREE_CONTEXT_CAPSULE';
          END IF;
          v_historical := (v_metadata ->> 'historical')::boolean;
          v_valid_at := COALESCE(
            NULLIF(v_coverage ->> 'valid_at', '')::timestamptz,
            CURRENT_TIMESTAMP
          );
          v_known_at := COALESCE(
            NULLIF(v_coverage ->> 'known_at', '')::timestamptz,
            CURRENT_TIMESTAMP
          );

          IF EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_sections #> '{MEMORY STATE VIEW,items}') item
            WHERE item ->> 'claim_version_id'
                    !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               OR item ->> 'claim_id'
                    !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
          ) THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'INVALID_TASK_FREE_CONTEXT_CAPSULE';
          END IF;
          SELECT array_agg(DISTINCT (item ->> 'claim_version_id')::uuid ORDER BY
                           (item ->> 'claim_version_id')::uuid)
          INTO v_claim_version_ids
          FROM jsonb_array_elements(p_sections #> '{MEMORY STATE VIEW,items}') item;
          IF COALESCE(cardinality(v_claim_version_ids), 0) = 0
             OR EXISTS (
               SELECT 1 FROM unnest(v_claim_version_ids) version_id
               WHERE NOT EXISTS (
                 SELECT 1 FROM jsonb_array_elements(v_trace.accepted_candidates) accepted
                 WHERE accepted ->> 'claim_version_id' = version_id::text
               )
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;

          IF jsonb_typeof(v_trace.query_plan -> 'accepted_epistemic_statuses') = 'array' THEN
            SELECT array_agg(value ORDER BY ordinal)
            INTO v_epistemic
            FROM jsonb_array_elements_text(
              v_trace.query_plan -> 'accepted_epistemic_statuses'
            ) WITH ORDINALITY item(value, ordinal);
          ELSE
            v_epistemic := ARRAY['VERIFIED', 'PROVISIONAL']::text[];
          END IF;
          v_gate := milai.evaluate_canonical_candidates(
            p_tenant_id,
            p_actor_id,
            v_claim_version_ids,
            v_coverage ->> 'required_authority',
            v_coverage -> 'requested_scope',
            v_valid_at,
            COALESCE(v_trace.query_plan ->> 'required_lifecycle', 'ACTIVE'),
            v_epistemic,
            v_metadata ->> 'freshness_at_issue',
            COALESCE(NULLIF(v_trace.query_plan ->> 'minimum_confidence', '')::numeric, 0),
            v_known_at,
            v_historical
          );
          IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_gate) outcome
            WHERE outcome ->> 'accepted' <> 'true'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;

          IF EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(p_sections -> 'OPEN ISSUE IDS') issue_id
            WHERE NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_gate) outcome,
                            jsonb_array_elements_text(outcome -> 'open_issue_ids') gated_issue
              WHERE gated_issue = issue_id
            )
          ) OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_gate) outcome,
                          jsonb_array_elements_text(outcome -> 'open_issue_ids') gated_issue
            WHERE NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements_text(
                p_sections -> 'OPEN ISSUE IDS'
              ) stored_issue
              WHERE stored_issue = gated_issue
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;

          IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_sections -> 'RETRIEVED EVIDENCE') item
            WHERE item ->> 'pointer_id'
                    !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               OR item ->> 'evidence_id'
                    !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
          ) OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_sections -> 'RETRIEVED EVIDENCE') item
            WHERE NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_gate) outcome,
                            jsonb_array_elements_text(outcome -> 'evidence_ids') gated_evidence
              WHERE gated_evidence = item ->> 'evidence_id'
            )
          ) OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_gate) outcome,
                          jsonb_array_elements_text(outcome -> 'evidence_ids') gated_evidence
            WHERE NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(
                p_sections -> 'RETRIEVED EVIDENCE'
              ) stored_evidence
              WHERE stored_evidence ->> 'evidence_id' = gated_evidence
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
          END IF;

          v_projection := milai.retrieval_projection_state(p_tenant_id, p_actor_id);
          IF (v_projection ->> 'canonical_snapshot_outbox_sequence')::bigint
               IS DISTINCT FROM (v_metadata ->> 'canonical_position')::bigint
             OR (v_metadata ->> 'invalidation_sequence')::bigint
               IS DISTINCT FROM (v_metadata ->> 'canonical_position')::bigint THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'CONTEXT_DEPENDENCY_ADVANCED';
          END IF;

          v_byte_size := octet_length(p_sections::text);
          IF v_byte_size > p_byte_budget THEN
            RAISE EXCEPTION USING
              ERRCODE = 'P0001', MESSAGE = 'CONTEXT_BUDGET_INFEASIBLE';
          END IF;
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
              AND evidence.evidence_id = v_evidence_id
              AND evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
              AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND blob.physical_delete_state = 'PRESENT'
              AND blob.content_hash = v_evidence ->> 'content_hash';
            IF NOT FOUND THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'CONTEXT_POINTER_INVALID';
            END IF;
            v_pointer_ids := v_pointer_ids || jsonb_build_array(v_pointer_id);
          END LOOP;
          RETURN jsonb_build_object(
            'capsule_id', v_capsule_id,
            'content_hash', v_content_hash,
            'byte_budget', p_byte_budget,
            'byte_size', v_byte_size,
            'issued_at', CURRENT_TIMESTAMP,
            'expires_at', p_expires_at,
            'pointer_ids', v_pointer_ids
          );
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.create_task_free_context_capsule({CREATE_RECEIPT_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"milai.create_task_free_context_capsule({CREATE_RECEIPT_SIGNATURE}) TO milai_api"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0031 downgrade is intentionally unsupported: task-free ContextCapsules may already "
        "exist; restore a verified pre-0031 backup"
    )
