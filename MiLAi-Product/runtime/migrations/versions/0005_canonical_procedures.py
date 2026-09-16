"""Create controlled proposal and canonical TX-02/03/04/06 procedures.

Revision ID: 0005_canonical_procedures
Revises: 0004_canonical_state_schema

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_canonical_procedures"
down_revision: str | None = "0004_canonical_state_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_PROPOSAL_SIGNATURE = (
    "uuid, uuid, text, text, uuid, text, uuid, jsonb, uuid[], uuid[], "
    "jsonb, text, text, text, text, jsonb"
)
REVIEW_PROPOSAL_SIGNATURE = "uuid, uuid, uuid, text, text, text, text, text, text"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.assert_session_context(p_tenant_id uuid, p_actor_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF NULLIF(current_setting('milai.tenant_id', true), '')::uuid
               IS DISTINCT FROM p_tenant_id
             OR NULLIF(current_setting('milai.actor_id', true), '')::uuid
               IS DISTINCT FROM p_actor_id THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'TENANT_MISMATCH';
          END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.authority_satisfies(p_actual text, p_required text)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
          SELECT CASE p_required
            WHEN 'INFORMATIONAL' THEN p_actual IN (
              'INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED'
            )
            WHEN 'ACTION_SAFE' THEN p_actual = 'ACTION_SAFE'
            WHEN 'USER_CONFIRMED' THEN p_actual = 'USER_CONFIRMED'
            ELSE false
          END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.evidence_refs_admissible(p_tenant_id uuid, p_refs uuid[])
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
          SELECT COALESCE(cardinality(p_refs), 0) > 0
             AND (
               SELECT count(*) = cardinality(p_refs)
                  AND count(DISTINCT e.evidence_id) = cardinality(p_refs)
               FROM milai.evidence_record e
               WHERE e.tenant_id = p_tenant_id
                 AND e.evidence_id = ANY(p_refs)
                 AND e.revoked_at IS NULL
                 AND e.retention_state = 'READABLE'
                 AND e.permission_snapshot @> '{"readable": true}'::jsonb
             )
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION milai.protect_proposal_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF ROW(
            NEW.tenant_id, NEW.proposal_id, NEW.target_claim_id, NEW.operation,
            NEW.expected_version_id, NEW.proposed_patch,
            NEW.supporting_evidence_refs, NEW.contradicting_evidence_refs,
            NEW.scope_predicate, NEW.requested_authority,
            NEW.derivation_policy_id, NEW.model_id, NEW.template_id,
            NEW.derivation_snapshot, NEW.proposer_actor_id,
            NEW.canonical_commit_authorized, NEW.idempotency_key,
            NEW.request_fingerprint, NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.proposal_id, OLD.target_claim_id, OLD.operation,
            OLD.expected_version_id, OLD.proposed_patch,
            OLD.supporting_evidence_refs, OLD.contradicting_evidence_refs,
            OLD.scope_predicate, OLD.requested_authority,
            OLD.derivation_policy_id, OLD.model_id, OLD.template_id,
            OLD.derivation_snapshot, OLD.proposer_actor_id,
            OLD.canonical_commit_authorized, OLD.idempotency_key,
            OLD.request_fingerprint, OLD.created_at, OLD.created_by_actor_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_PROPOSAL_IDENTITY';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_operation_proposal_identity
        BEFORE UPDATE ON milai.operation_proposal
        FOR EACH ROW EXECUTE FUNCTION milai.protect_proposal_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.protect_open_issue_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          IF ROW(
            NEW.tenant_id, NEW.issue_id, NEW.target_claim_id, NEW.issue_type,
            NEW.scope_predicate, NEW.discharge_rule, NEW.required_authority,
            NEW.created_from_proposal_id, NEW.created_at, NEW.created_by_actor_id
          ) IS DISTINCT FROM ROW(
            OLD.tenant_id, OLD.issue_id, OLD.target_claim_id, OLD.issue_type,
            OLD.scope_predicate, OLD.discharge_rule, OLD.required_authority,
            OLD.created_from_proposal_id, OLD.created_at, OLD.created_by_actor_id
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_OPEN_ISSUE_IDENTITY';
          END IF;
          IF NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_open_issue_identity_and_revision
        BEFORE UPDATE ON milai.open_issue
        FOR EACH ROW EXECUTE FUNCTION milai.protect_open_issue_identity()
        """
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
          v_proposal_id uuid;
          v_current_version_id uuid;
          v_resolution_issue milai.open_issue%ROWTYPE;
          v_resolution_issue_id uuid;
          v_expected_issue_revision integer;
          v_issue_commit_seq bigint;
          v_rows integer;
          v_outbox_id uuid;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_operation = 'SPLIT' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'OPERATION_NOT_ENABLED';
          END IF;
          IF p_operation = 'UPDATE' OR p_operation NOT IN (
            'CREATE', 'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND',
            'SUPERSEDE', 'CONTEXTUALIZE', 'CONTRADICT', 'NO_CHANGE'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'OPERATION_NOT_ENABLED';
          END IF;
          IF jsonb_typeof(p_proposed_patch) <> 'object'
             OR jsonb_typeof(p_scope_predicate) <> 'object'
             OR jsonb_typeof(p_derivation_snapshot) <> 'object' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
          END IF;
          IF p_requested_authority NOT IN (
            'INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'AUTHORITY_INSUFFICIENT';
          END IF;

          IF p_operation = 'CREATE' THEN
            IF p_target_claim_id IS NOT NULL OR p_expected_version_id IS NOT NULL
               OR NOT (p_proposed_patch ?& ARRAY[
                 'subject_id', 'predicate', 'claim_type', 'payload', 'authority', 'confidence'
               ]) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
            END IF;
          ELSE
            IF p_target_claim_id IS NULL OR p_expected_version_id IS NULL THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
            END IF;
            SELECT current_claim_version_id INTO v_current_version_id
            FROM milai.claim_head
            WHERE tenant_id = p_tenant_id AND claim_id = p_target_claim_id;
            IF v_current_version_id IS NULL
               OR v_current_version_id <> p_expected_version_id THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
            END IF;
          END IF;

          IF p_operation IN (
            'CREATE', 'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND',
            'SUPERSEDE', 'CONTEXTUALIZE'
          ) AND NOT milai.evidence_refs_admissible(
            p_tenant_id, p_supporting_evidence_refs
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
          END IF;
          IF COALESCE(cardinality(p_contradicting_evidence_refs), 0) > 0
             AND NOT milai.evidence_refs_admissible(
               p_tenant_id, p_contradicting_evidence_refs
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
          END IF;
          IF p_operation = 'CONTRADICT'
             AND COALESCE(cardinality(p_contradicting_evidence_refs), 0) = 0 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
          END IF;
          IF p_proposed_patch ? 'authority'
             AND p_proposed_patch ->> 'authority' <> p_requested_authority THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'AUTHORITY_INSUFFICIENT';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'CREATE_PROPOSAL', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'CREATE_PROPOSAL'
            AND idempotency_key = p_idempotency_key
          FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          v_proposal_id := gen_random_uuid();
          INSERT INTO milai.operation_proposal (
            tenant_id, proposal_id, target_claim_id, operation,
            expected_version_id, proposed_patch, supporting_evidence_refs,
            contradicting_evidence_refs, scope_predicate, requested_authority,
            derivation_policy_id, model_id, template_id, derivation_snapshot,
            proposer_actor_id, canonical_commit_authorized, status,
            idempotency_key, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_proposal_id, p_target_claim_id, p_operation,
            p_expected_version_id, p_proposed_patch,
            COALESCE(p_supporting_evidence_refs, '{}'::uuid[]),
            COALESCE(p_contradicting_evidence_refs, '{}'::uuid[]),
            p_scope_predicate, p_requested_authority,
            p_derivation_policy_id, p_model_id, p_template_id,
            p_derivation_snapshot, p_actor_id, false, 'PENDING_REVIEW',
            p_idempotency_key, p_request_fingerprint, p_actor_id
          );

          IF p_proposed_patch ?| ARRAY[
            'resolve_issue_id', 'expected_issue_revision', 'addressed_branches'
          ] THEN
            IF p_operation <> 'SUPERSEDE'
               OR NOT (p_proposed_patch ?& ARRAY[
                 'resolve_issue_id', 'expected_issue_revision', 'addressed_branches'
               ])
               OR jsonb_typeof(p_proposed_patch -> 'expected_issue_revision') <> 'number'
               OR jsonb_typeof(p_proposed_patch -> 'addressed_branches') <> 'array' THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
            END IF;
            BEGIN
              v_resolution_issue_id := (p_proposed_patch ->> 'resolve_issue_id')::uuid;
              v_expected_issue_revision :=
                (p_proposed_patch ->> 'expected_issue_revision')::integer;
            EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
            END;
            SELECT * INTO v_resolution_issue
            FROM milai.open_issue
            WHERE tenant_id = p_tenant_id AND issue_id = v_resolution_issue_id
            FOR UPDATE;
            IF NOT FOUND
               OR v_resolution_issue.target_claim_id IS DISTINCT FROM p_target_claim_id
               OR v_resolution_issue.status NOT IN (
                 'OPEN', 'WAITING_EVIDENCE', 'WAITING_USER'
               )
               OR v_resolution_issue.revision <> v_expected_issue_revision THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
            END IF;
            IF NOT milai.authority_satisfies(
                 p_requested_authority, v_resolution_issue.required_authority
               )
               OR NOT p_scope_predicate @> COALESCE(
                 v_resolution_issue.discharge_rule -> 'required_scope', '{}'::jsonb
               )
               OR NOT (p_proposed_patch -> 'addressed_branches') @> COALESCE(
                 v_resolution_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
               )
               OR EXISTS (
                 SELECT 1
                 FROM jsonb_array_elements_text(COALESCE(
                   v_resolution_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
                 )) required(branch_type)
                 WHERE NOT EXISTS (
                   SELECT 1 FROM milai.grounding_relation gr
                   WHERE gr.tenant_id = p_tenant_id
                     AND gr.open_issue_id = v_resolution_issue_id
                     AND gr.relation_type = required.branch_type
                 )
               )
               OR EXISTS (
                 SELECT 1 FROM milai.evidence_record e
                 WHERE e.tenant_id = p_tenant_id
                   AND e.evidence_id = ANY(p_supporting_evidence_refs)
                   AND NOT (
                     v_resolution_issue.discharge_rule -> 'required_evidence_kinds'
                     ? e.source_type
                   )
               )
               OR (
                 SELECT count(DISTINCT e.source_ref)
                 FROM milai.evidence_record e
                 WHERE e.tenant_id = p_tenant_id
                   AND e.evidence_id = ANY(p_supporting_evidence_refs)
               ) < COALESCE(
                 (v_resolution_issue.discharge_rule ->>
                   'minimum_independent_sources')::integer, 1
               ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
            END IF;

            INSERT INTO milai.grounding_relation (
              tenant_id, relation_id, open_issue_id, evidence_id,
              relation_type, created_from_proposal_id, created_by_actor_id
            ) SELECT
              p_tenant_id, gen_random_uuid(), v_resolution_issue_id, evidence_id,
              'RESOLUTION_CANDIDATE', v_proposal_id, p_actor_id
            FROM unnest(p_supporting_evidence_refs) AS evidence_id
            ON CONFLICT DO NOTHING;
            UPDATE milai.open_issue
            SET status = 'READY_FOR_REVIEW', revision = revision + 1
            WHERE tenant_id = p_tenant_id AND issue_id = v_resolution_issue_id
              AND revision = v_expected_issue_revision
              AND status IN ('OPEN', 'WAITING_EVIDENCE', 'WAITING_USER');
            GET DIAGNOSTICS v_rows = ROW_COUNT;
            IF v_rows <> 1 THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
            END IF;
            v_issue_commit_seq := nextval('milai.canonical_commit_seq');
            INSERT INTO milai.open_issue_transition (
              tenant_id, transition_id, issue_id, from_status, to_status,
              from_revision, to_revision, event_type, proposal_id,
              decision_id, policy_version, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), v_resolution_issue_id,
              v_resolution_issue.status, 'READY_FOR_REVIEW',
              v_expected_issue_revision, v_expected_issue_revision + 1,
              'RESOLUTION_EVIDENCE_PROPOSED', v_proposal_id,
              NULL, p_derivation_policy_id, v_issue_commit_seq, p_actor_id
            );
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), 'OPEN_ISSUE', v_resolution_issue_id,
              'OPEN_ISSUE_READY_FOR_REVIEW',
              jsonb_build_object(
                'issue_id', v_resolution_issue_id,
                'proposal_id', v_proposal_id,
                'revision', v_expected_issue_revision + 1
              ), 40, v_issue_commit_seq, p_actor_id
            );
          END IF;
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'PROPOSAL_CREATED', NULL,
            jsonb_build_object('proposal_id', v_proposal_id, 'operation', p_operation),
            p_actor_id
          );
          v_outbox_id := gen_random_uuid();
          INSERT INTO milai.outbox_event (
            tenant_id, outbox_id, aggregate_type, aggregate_id,
            event_type, payload, priority, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_outbox_id, 'PROPOSAL', v_proposal_id,
            'PROPOSAL_CREATED',
            jsonb_build_object('proposal_id', v_proposal_id, 'operation', p_operation),
            80, p_actor_id
          );
          v_response := jsonb_build_object(
            'proposal_id', v_proposal_id, 'outbox_id', v_outbox_id,
            'status', 'PENDING_REVIEW', 'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'CREATE_PROPOSAL'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
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
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_proposal milai.operation_proposal%ROWTYPE;
          v_current milai.claim_version%ROWTYPE;
          v_issue milai.open_issue%ROWTYPE;
          v_claim_id uuid;
          v_new_version_id uuid;
          v_decision_id uuid;
          v_issue_id uuid;
          v_outbox_id uuid;
          v_commit_seq bigint;
          v_next_version integer;
          v_expected_issue_revision integer;
          v_rows integer;
          v_new_payload jsonb;
          v_new_scope jsonb;
          v_new_authority text;
          v_new_confidence numeric;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_decision NOT IN ('APPROVE', 'REJECT')
             OR p_decision_actor_type NOT IN ('POLICY', 'USER', 'STEWARD') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_DECISION';
          END IF;
          IF p_decision = 'APPROVE' AND p_decision_actor_type = 'POLICY' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'AUTHORITY_INSUFFICIENT';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'REVIEW_PROPOSAL', p_idempotency_key,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'REVIEW_PROPOSAL'
            AND idempotency_key = p_idempotency_key
          FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          SELECT * INTO v_proposal
          FROM milai.operation_proposal
          WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROPOSAL_NOT_FOUND';
          END IF;
          IF v_proposal.status <> 'PENDING_REVIEW' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROPOSAL_ALREADY_DECIDED';
          END IF;

          v_decision_id := gen_random_uuid();
          IF p_decision = 'REJECT' THEN
            IF v_proposal.proposed_patch ? 'resolve_issue_id' THEN
              BEGIN
                v_issue_id := (v_proposal.proposed_patch ->> 'resolve_issue_id')::uuid;
                v_expected_issue_revision :=
                  (v_proposal.proposed_patch ->> 'expected_issue_revision')::integer;
              EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
              END;
              SELECT * INTO v_issue
              FROM milai.open_issue
              WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
              FOR UPDATE;
              IF NOT FOUND
                 OR v_issue.target_claim_id IS DISTINCT FROM v_proposal.target_claim_id
                 OR v_issue.status <> 'READY_FOR_REVIEW'
                 OR v_issue.revision <> v_expected_issue_revision + 1 THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
              END IF;
              v_commit_seq := nextval('milai.canonical_commit_seq');
            END IF;
            INSERT INTO milai.steward_decision (
              tenant_id, decision_id, proposal_id, decision,
              decision_actor_type, decision_actor_id, policy_version,
              reason_code, resulting_open_issue_id, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, v_decision_id, p_proposal_id, 'REJECT',
              p_decision_actor_type, p_actor_id, p_policy_version,
              p_reason_code, v_issue_id, v_commit_seq, p_actor_id
            );
            IF v_issue_id IS NOT NULL THEN
              UPDATE milai.open_issue
              SET status = 'OPEN', revision = revision + 1
              WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
                AND status = 'READY_FOR_REVIEW'
                AND revision = v_issue.revision;
              GET DIAGNOSTICS v_rows = ROW_COUNT;
              IF v_rows <> 1 THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
              END IF;
              INSERT INTO milai.open_issue_transition (
                tenant_id, transition_id, issue_id, from_status, to_status,
                from_revision, to_revision, event_type, proposal_id,
                decision_id, policy_version, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                p_tenant_id, gen_random_uuid(), v_issue_id,
                'READY_FOR_REVIEW', 'OPEN', v_issue.revision,
                v_issue.revision + 1, 'RESOLUTION_REJECTED', p_proposal_id,
                v_decision_id, p_policy_version, v_commit_seq, p_actor_id
              );
            END IF;
            UPDATE milai.operation_proposal SET status = 'REJECTED'
            WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id;
            v_outbox_id := gen_random_uuid();
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, v_outbox_id,
              CASE WHEN v_issue_id IS NULL THEN 'PROPOSAL' ELSE 'OPEN_ISSUE' END,
              COALESCE(v_issue_id, p_proposal_id),
              CASE WHEN v_issue_id IS NULL THEN 'PROPOSAL_REJECTED'
                   ELSE 'OPEN_ISSUE_RESOLUTION_REJECTED' END,
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'open_issue_id', v_issue_id
              ), 60, v_commit_seq, p_actor_id
            );
            v_response := jsonb_build_object(
              'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
              'decision', 'REJECT', 'open_issue_id', v_issue_id,
              'canonical_commit_seq', v_commit_seq, 'replayed', false
            );
          ELSE
            IF v_proposal.operation IN (
              'CREATE', 'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND',
              'SUPERSEDE', 'CONTEXTUALIZE'
            ) AND NOT milai.evidence_refs_admissible(
              p_tenant_id, v_proposal.supporting_evidence_refs
            ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
            END IF;
            IF COALESCE(cardinality(v_proposal.contradicting_evidence_refs), 0) > 0
               AND NOT milai.evidence_refs_admissible(
                 p_tenant_id, v_proposal.contradicting_evidence_refs
               ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
            END IF;

            v_commit_seq := nextval('milai.canonical_commit_seq');
            IF v_proposal.operation = 'CREATE' THEN
              v_claim_id := gen_random_uuid();
              v_new_version_id := gen_random_uuid();
              v_new_payload := v_proposal.proposed_patch -> 'payload';
              v_new_scope := v_proposal.scope_predicate;
              v_new_authority := v_proposal.proposed_patch ->> 'authority';
              v_new_confidence := (v_proposal.proposed_patch ->> 'confidence')::numeric;
              IF jsonb_typeof(v_new_payload) <> 'object'
                 OR v_new_authority <> v_proposal.requested_authority THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
              END IF;
              BEGIN
                INSERT INTO milai.claim (
                  tenant_id, claim_id, subject_id, predicate, claim_type,
                  created_by_actor_id
                ) VALUES (
                  p_tenant_id, v_claim_id,
                  v_proposal.proposed_patch ->> 'subject_id',
                  v_proposal.proposed_patch ->> 'predicate',
                  v_proposal.proposed_patch ->> 'claim_type', p_actor_id
                );
              EXCEPTION WHEN unique_violation THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
              END;
              INSERT INTO milai.claim_version (
                tenant_id, claim_version_id, claim_id, version_number,
                payload, scope_predicate, valid_time_from, valid_time_to,
                lifecycle, epistemic_status, freshness, authority, confidence,
                derivation_policy_id, model_id, template_id,
                steward_decision_id, canonical_commit_seq, created_by_actor_id
              ) VALUES (
                p_tenant_id, v_new_version_id, v_claim_id, 1,
                v_new_payload, v_new_scope,
                NULLIF(v_proposal.proposed_patch ->> 'valid_time_from', '')::timestamptz,
                NULLIF(v_proposal.proposed_patch ->> 'valid_time_to', '')::timestamptz,
                COALESCE(v_proposal.proposed_patch ->> 'lifecycle', 'ACTIVE'),
                COALESCE(v_proposal.proposed_patch ->> 'epistemic_status', 'SUPPORTED'),
                COALESCE(v_proposal.proposed_patch ->> 'freshness', 'CURRENT'),
                v_new_authority, v_new_confidence,
                v_proposal.derivation_policy_id, v_proposal.model_id,
                v_proposal.template_id, v_decision_id, v_commit_seq, p_actor_id
              );
              INSERT INTO milai.claim_head (
                tenant_id, claim_id, current_claim_version_id,
                created_by_actor_id, updated_at, updated_by_actor_id
              ) VALUES (
                p_tenant_id, v_claim_id, v_new_version_id,
                p_actor_id, CURRENT_TIMESTAMP, p_actor_id
              );
              INSERT INTO milai.grounding_relation (
                tenant_id, relation_id, claim_version_id, evidence_id,
                relation_type, created_from_proposal_id, created_by_actor_id
              ) SELECT
                p_tenant_id, gen_random_uuid(), v_new_version_id, evidence_id,
                'SUPPORTS', p_proposal_id, p_actor_id
              FROM unnest(v_proposal.supporting_evidence_refs) AS evidence_id;

            ELSIF v_proposal.operation IN (
              'SUPPORT', 'WEAKEN', 'REVALIDATE', 'REGROUND',
              'SUPERSEDE', 'CONTEXTUALIZE'
            ) THEN
              SELECT cv.* INTO v_current
              FROM milai.claim_head ch
              JOIN milai.claim_version cv
                ON cv.tenant_id = ch.tenant_id
               AND cv.claim_version_id = ch.current_claim_version_id
              WHERE ch.tenant_id = p_tenant_id
                AND ch.claim_id = v_proposal.target_claim_id
              FOR UPDATE OF ch;
              IF NOT FOUND OR v_current.claim_version_id <> v_proposal.expected_version_id THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
              END IF;
              IF v_proposal.operation <> 'REGROUND' AND EXISTS (
                SELECT 1 FROM milai.grounding_block gb
                WHERE gb.tenant_id = p_tenant_id
                  AND gb.claim_version_id = v_current.claim_version_id
                  AND gb.active
              ) THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
              END IF;
              IF v_proposal.operation = 'REGROUND' AND NOT EXISTS (
                SELECT 1 FROM milai.grounding_block gb
                WHERE gb.tenant_id = p_tenant_id
                  AND gb.claim_version_id = v_current.claim_version_id
                  AND gb.active
              ) THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
              END IF;

              IF v_proposal.proposed_patch ? 'resolve_issue_id' THEN
                BEGIN
                  v_issue_id := (v_proposal.proposed_patch ->> 'resolve_issue_id')::uuid;
                  v_expected_issue_revision :=
                    (v_proposal.proposed_patch ->> 'expected_issue_revision')::integer;
                EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
                END;
                SELECT * INTO v_issue
                FROM milai.open_issue
                WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
                FOR UPDATE;
                IF NOT FOUND
                   OR v_proposal.operation <> 'SUPERSEDE'
                   OR v_issue.target_claim_id IS DISTINCT FROM v_proposal.target_claim_id
                   OR v_issue.status <> 'READY_FOR_REVIEW'
                   OR v_issue.revision <> v_expected_issue_revision + 1 THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
                END IF;
                IF NOT milai.authority_satisfies(
                     v_proposal.requested_authority, v_issue.required_authority
                   )
                   OR NOT v_proposal.scope_predicate @> COALESCE(
                     v_issue.discharge_rule -> 'required_scope', '{}'::jsonb
                   )
                   OR NOT (v_proposal.proposed_patch -> 'addressed_branches') @> COALESCE(
                     v_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
                   )
                   OR EXISTS (
                     SELECT 1
                     FROM jsonb_array_elements_text(COALESCE(
                       v_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
                     )) required(branch_type)
                     WHERE NOT EXISTS (
                       SELECT 1 FROM milai.grounding_relation gr
                       WHERE gr.tenant_id = p_tenant_id
                         AND gr.open_issue_id = v_issue_id
                         AND gr.relation_type = required.branch_type
                     )
                   )
                   OR (
                     SELECT count(DISTINCT gr.evidence_id)
                     FROM milai.grounding_relation gr
                     JOIN milai.evidence_record e
                       ON e.tenant_id = gr.tenant_id AND e.evidence_id = gr.evidence_id
                     WHERE gr.tenant_id = p_tenant_id
                       AND gr.open_issue_id = v_issue_id
                       AND gr.created_from_proposal_id = p_proposal_id
                       AND gr.relation_type = 'RESOLUTION_CANDIDATE'
                       AND e.revoked_at IS NULL
                       AND e.retention_state = 'READABLE'
                       AND e.permission_snapshot @> '{"readable": true}'::jsonb
                   ) <> cardinality(v_proposal.supporting_evidence_refs)
                   OR (
                     SELECT count(DISTINCT e.source_ref)
                     FROM milai.grounding_relation gr
                     JOIN milai.evidence_record e
                       ON e.tenant_id = gr.tenant_id AND e.evidence_id = gr.evidence_id
                     WHERE gr.tenant_id = p_tenant_id
                       AND gr.open_issue_id = v_issue_id
                       AND gr.created_from_proposal_id = p_proposal_id
                       AND gr.relation_type = 'RESOLUTION_CANDIDATE'
                   ) < COALESCE(
                     (v_issue.discharge_rule ->>
                       'minimum_independent_sources')::integer, 1
                   ) THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
                END IF;
              END IF;

              v_claim_id := v_current.claim_id;
              v_new_version_id := gen_random_uuid();
              v_next_version := v_current.version_number + 1;
              v_new_payload := CASE WHEN v_proposal.proposed_patch ? 'payload'
                THEN v_proposal.proposed_patch -> 'payload' ELSE v_current.payload END;
              v_new_scope := CASE WHEN v_proposal.proposed_patch ? 'scope_predicate'
                THEN v_proposal.proposed_patch -> 'scope_predicate'
                ELSE v_proposal.scope_predicate END;
              v_new_authority := COALESCE(
                v_proposal.proposed_patch ->> 'authority', v_current.authority
              );
              v_new_confidence := COALESCE(
                NULLIF(v_proposal.proposed_patch ->> 'confidence', '')::numeric,
                v_current.confidence
              );
              IF jsonb_typeof(v_new_payload) <> 'object'
                 OR jsonb_typeof(v_new_scope) <> 'object'
                 OR v_new_authority <> v_proposal.requested_authority THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
              END IF;
              INSERT INTO milai.claim_version (
                tenant_id, claim_version_id, claim_id, version_number,
                payload, scope_predicate, valid_time_from, valid_time_to,
                lifecycle, epistemic_status, freshness, authority, confidence,
                derivation_policy_id, model_id, template_id,
                steward_decision_id, canonical_commit_seq, created_by_actor_id
              ) VALUES (
                p_tenant_id, v_new_version_id, v_claim_id, v_next_version,
                v_new_payload, v_new_scope,
                CASE WHEN v_proposal.proposed_patch ? 'valid_time_from'
                  THEN NULLIF(v_proposal.proposed_patch ->> 'valid_time_from', '')::timestamptz
                  ELSE v_current.valid_time_from END,
                CASE WHEN v_proposal.proposed_patch ? 'valid_time_to'
                  THEN NULLIF(v_proposal.proposed_patch ->> 'valid_time_to', '')::timestamptz
                  ELSE v_current.valid_time_to END,
                COALESCE(v_proposal.proposed_patch ->> 'lifecycle', v_current.lifecycle),
                COALESCE(
                  v_proposal.proposed_patch ->> 'epistemic_status',
                  CASE WHEN v_proposal.operation = 'WEAKEN' THEN 'WEAKENED'
                       ELSE v_current.epistemic_status END
                ),
                COALESCE(v_proposal.proposed_patch ->> 'freshness', v_current.freshness),
                v_new_authority, v_new_confidence,
                v_proposal.derivation_policy_id, v_proposal.model_id,
                v_proposal.template_id, v_decision_id, v_commit_seq, p_actor_id
              );
              INSERT INTO milai.grounding_relation (
                tenant_id, relation_id, claim_version_id, evidence_id,
                relation_type, created_from_proposal_id, created_by_actor_id
              ) SELECT
                p_tenant_id, gen_random_uuid(), v_new_version_id, evidence_id,
                'SUPPORTS', p_proposal_id, p_actor_id
              FROM unnest(v_proposal.supporting_evidence_refs) AS evidence_id;
              UPDATE milai.claim_head
              SET current_claim_version_id = v_new_version_id,
                  updated_at = CURRENT_TIMESTAMP,
                  updated_by_actor_id = p_actor_id
              WHERE tenant_id = p_tenant_id AND claim_id = v_claim_id
                AND current_claim_version_id = v_proposal.expected_version_id;
              GET DIAGNOSTICS v_rows = ROW_COUNT;
              IF v_rows <> 1 THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
              END IF;
              INSERT INTO milai.version_transition (
                tenant_id, transition_id, claim_id, old_claim_version_id,
                new_claim_version_id, transition_type, proposal_id,
                decision_id, canonical_commit_seq, created_by_actor_id
              ) VALUES (
                p_tenant_id, gen_random_uuid(), v_claim_id,
                v_current.claim_version_id, v_new_version_id,
                v_proposal.operation, p_proposal_id, v_decision_id,
                v_commit_seq, p_actor_id
              );
              IF v_proposal.operation = 'REGROUND' THEN
                UPDATE milai.grounding_block
                SET active = false, released_at = CURRENT_TIMESTAMP,
                    restored_by_claim_version_id = v_new_version_id,
                    restored_by_decision_id = v_decision_id
                WHERE tenant_id = p_tenant_id
                  AND claim_version_id = v_current.claim_version_id AND active;
              END IF;
              IF v_issue_id IS NOT NULL THEN
                UPDATE milai.open_issue
                SET status = 'RESOLVED', revision = revision + 1,
                    resolved_by_decision_id = v_decision_id,
                    resolved_at = CURRENT_TIMESTAMP
                WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
                  AND status = 'READY_FOR_REVIEW'
                  AND revision = v_issue.revision;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                IF v_rows <> 1 THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
                END IF;
                INSERT INTO milai.open_issue_transition (
                  tenant_id, transition_id, issue_id, from_status, to_status,
                  from_revision, to_revision, event_type, proposal_id,
                  decision_id, policy_version, canonical_commit_seq,
                  created_by_actor_id
                ) VALUES (
                  p_tenant_id, gen_random_uuid(), v_issue_id,
                  'READY_FOR_REVIEW', 'RESOLVED', v_issue.revision,
                  v_issue.revision + 1, 'DISCHARGE_APPROVED', p_proposal_id,
                  v_decision_id, p_policy_version, v_commit_seq, p_actor_id
                );
              END IF;

            ELSIF v_proposal.operation = 'CONTRADICT' THEN
              SELECT cv.* INTO v_current
              FROM milai.claim_head ch
              JOIN milai.claim_version cv
                ON cv.tenant_id = ch.tenant_id
               AND cv.claim_version_id = ch.current_claim_version_id
              WHERE ch.tenant_id = p_tenant_id
                AND ch.claim_id = v_proposal.target_claim_id
              FOR UPDATE OF ch;
              IF NOT FOUND OR v_current.claim_version_id <> v_proposal.expected_version_id THEN
                RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
              END IF;
              SELECT * INTO v_issue FROM milai.open_issue
              WHERE tenant_id = p_tenant_id
                AND target_claim_id = v_proposal.target_claim_id
                AND issue_type = 'CONFLICT'
                AND status NOT IN ('RESOLVED', 'DISMISSED')
              FOR UPDATE;
              IF NOT FOUND THEN
                v_issue_id := gen_random_uuid();
                INSERT INTO milai.open_issue (
                  tenant_id, issue_id, target_claim_id, issue_type, status,
                  revision, scope_predicate, discharge_rule, required_authority,
                  created_from_proposal_id, created_by_actor_id
                ) VALUES (
                  p_tenant_id, v_issue_id, v_proposal.target_claim_id,
                  'CONFLICT', 'OPEN', 1, v_proposal.scope_predicate,
                  jsonb_build_object(
                    'rule_version', '1',
                    'required_evidence_kinds', jsonb_build_array('RUNTIME_OBSERVATION'),
                    'required_scope', v_proposal.scope_predicate,
                    'required_authority', v_proposal.requested_authority,
                    'minimum_independent_sources', 1,
                    'must_address_branches',
                      jsonb_build_array('SUPPORT_BRANCH', 'CONTRADICT_BRANCH'),
                    'review_required', true
                  ),
                  v_proposal.requested_authority, p_proposal_id, p_actor_id
                );
              ELSE
                v_issue_id := v_issue.issue_id;
                UPDATE milai.open_issue SET revision = revision + 1
                WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
                  AND revision = v_issue.revision;
                GET DIAGNOSTICS v_rows = ROW_COUNT;
                IF v_rows <> 1 THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
                END IF;
                INSERT INTO milai.open_issue_transition (
                  tenant_id, transition_id, issue_id, from_status, to_status,
                  from_revision, to_revision, event_type, proposal_id,
                  decision_id, policy_version, canonical_commit_seq,
                  created_by_actor_id
                ) VALUES (
                  p_tenant_id, gen_random_uuid(), v_issue_id,
                  v_issue.status, v_issue.status, v_issue.revision,
                  v_issue.revision + 1, 'CONFLICT_EVIDENCE_ADDED',
                  p_proposal_id, v_decision_id, p_policy_version,
                  v_commit_seq, p_actor_id
                );
              END IF;
              INSERT INTO milai.grounding_relation (
                tenant_id, relation_id, open_issue_id, evidence_id,
                relation_type, created_from_proposal_id, created_by_actor_id
              ) SELECT
                p_tenant_id, gen_random_uuid(), v_issue_id, evidence_id,
                'SUPPORT_BRANCH', p_proposal_id, p_actor_id
              FROM (
                SELECT unnest(v_proposal.supporting_evidence_refs) AS evidence_id
                UNION
                SELECT gr.evidence_id FROM milai.grounding_relation gr
                WHERE gr.tenant_id = p_tenant_id
                  AND gr.claim_version_id = v_current.claim_version_id
                  AND gr.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              ) support
              ON CONFLICT DO NOTHING;
              INSERT INTO milai.grounding_relation (
                tenant_id, relation_id, open_issue_id, evidence_id,
                relation_type, created_from_proposal_id, created_by_actor_id
              ) SELECT
                p_tenant_id, gen_random_uuid(), v_issue_id, evidence_id,
                'CONTRADICT_BRANCH', p_proposal_id, p_actor_id
              FROM unnest(v_proposal.contradicting_evidence_refs) AS evidence_id
              ON CONFLICT DO NOTHING;

            ELSIF v_proposal.operation = 'NO_CHANGE' THEN
              IF v_proposal.target_claim_id IS NOT NULL THEN
                PERFORM 1 FROM milai.claim_head
                WHERE tenant_id = p_tenant_id
                  AND claim_id = v_proposal.target_claim_id
                  AND current_claim_version_id = v_proposal.expected_version_id
                FOR UPDATE;
                IF NOT FOUND THEN
                  RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
                END IF;
              END IF;
            ELSE
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'OPERATION_NOT_ENABLED';
            END IF;

            INSERT INTO milai.steward_decision (
              tenant_id, decision_id, proposal_id, decision,
              decision_actor_type, decision_actor_id, policy_version,
              reason_code, resulting_claim_version_id,
              resulting_open_issue_id, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, v_decision_id, p_proposal_id, 'APPROVE',
              p_decision_actor_type, p_actor_id, p_policy_version,
              p_reason_code, v_new_version_id, v_issue_id,
              v_commit_seq, p_actor_id
            );
            UPDATE milai.operation_proposal SET status = 'APPLIED'
            WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id;
            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), 'CANONICAL_PROPOSAL_APPLIED',
              p_reason_code,
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'operation', v_proposal.operation,
                'claim_version_id', v_new_version_id,
                'open_issue_id', v_issue_id,
                'canonical_commit_seq', v_commit_seq
              ), p_actor_id
            );
            v_outbox_id := gen_random_uuid();
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, canonical_commit_seq,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, v_outbox_id,
              CASE WHEN v_issue_id IS NOT NULL THEN 'OPEN_ISSUE' ELSE 'CLAIM' END,
              COALESCE(v_issue_id, v_claim_id, v_proposal.target_claim_id, p_proposal_id),
              CASE WHEN v_issue_id IS NOT NULL THEN 'OPEN_ISSUE_CHANGED'
                   WHEN v_new_version_id IS NOT NULL THEN 'CLAIM_VERSION_COMMITTED'
                   ELSE 'NO_CHANGE_RECORDED' END,
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'operation', v_proposal.operation,
                'claim_id', COALESCE(v_claim_id, v_proposal.target_claim_id),
                'claim_version_id', v_new_version_id,
                'open_issue_id', v_issue_id
              ), 50, v_commit_seq, p_actor_id
            );
            v_response := jsonb_build_object(
              'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
              'decision', 'APPROVE',
              'claim_id', COALESCE(v_claim_id, v_proposal.target_claim_id),
              'claim_version_id', v_new_version_id,
              'open_issue_id', v_issue_id,
              'outbox_id', v_outbox_id,
              'canonical_commit_seq', v_commit_seq,
              'replayed', false
            );
          END IF;

          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'REVIEW_PROPOSAL'
            AND idempotency_key = p_idempotency_key;
          RETURN v_response;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON FUNCTION milai.assert_session_context(uuid, uuid), "
        "milai.authority_satisfies(text, text), "
        "milai.evidence_refs_admissible(uuid, uuid[]) FROM PUBLIC"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal({CREATE_PROPOSAL_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.review_operation_proposal({REVIEW_PROPOSAL_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.create_operation_proposal({CREATE_PROPOSAL_SIGNATURE}) "
        "TO milai_api"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.review_operation_proposal({REVIEW_PROPOSAL_SIGNATURE}) "
        "TO milai_steward"
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION milai.review_operation_proposal({REVIEW_PROPOSAL_SIGNATURE})")
    op.execute(f"DROP FUNCTION milai.create_operation_proposal({CREATE_PROPOSAL_SIGNATURE})")
    op.execute("DROP FUNCTION milai.protect_open_issue_identity() CASCADE")
    op.execute("DROP FUNCTION milai.protect_proposal_identity() CASCADE")
    op.execute("DROP FUNCTION milai.evidence_refs_admissible(uuid, uuid[])")
    op.execute("DROP FUNCTION milai.authority_satisfies(text, text)")
    op.execute("DROP FUNCTION milai.assert_session_context(uuid, uuid)")
