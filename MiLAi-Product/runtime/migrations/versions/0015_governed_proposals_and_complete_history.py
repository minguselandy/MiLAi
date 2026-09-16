"""Make proposal submission non-canonical and complete creation histories.

Revision ID: 0015_governed_history
Revises: 0014_query_plan_outbox_sequence

This migration is intentionally forward-only for canonical data.  It preserves the
candidate.1 procedures under private ``*_legacy`` names, exposes corrected wrappers,
normalises the three orthogonal ClaimVersion state axes, and makes creation events
first-class append-only history records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_governed_history"
down_revision: str | None = "0014_query_plan_outbox_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_SIGNATURE = (
    "uuid, uuid, text, text, uuid, text, uuid, jsonb, uuid[], uuid[], "
    "jsonb, text, text, text, text, jsonb"
)
REVIEW_SIGNATURE = "uuid, uuid, uuid, text, text, text, text, text, text"


def upgrade() -> None:
    # Candidate.1 names did not match the normative, orthogonal state vocabulary.
    # The mapping is explicit and lossless with respect to the old finite domains.
    op.execute("DROP TRIGGER trg_claim_version_append_only ON milai.claim_version")
    op.drop_constraint("ck_claim_version_lifecycle", "claim_version", schema="milai", type_="check")
    op.drop_constraint("ck_claim_version_epistemic", "claim_version", schema="milai", type_="check")
    op.drop_constraint("ck_claim_version_freshness", "claim_version", schema="milai", type_="check")
    op.execute(
        """
        UPDATE milai.claim_version
        SET lifecycle = CASE lifecycle WHEN 'RETIRED' THEN 'ARCHIVED' ELSE lifecycle END,
            epistemic_status = CASE epistemic_status
              WHEN 'SUPPORTED' THEN 'VERIFIED'
              WHEN 'WEAKENED' THEN 'CHALLENGED'
              WHEN 'UNCERTAIN' THEN 'PROVISIONAL'
              ELSE epistemic_status
            END,
            freshness = CASE freshness WHEN 'UNKNOWN' THEN 'STALE' ELSE freshness END
        """
    )
    op.create_check_constraint(
        "ck_claim_version_lifecycle",
        "claim_version",
        "lifecycle IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED', 'DELETED')",
        schema="milai",
    )
    op.create_check_constraint(
        "ck_claim_version_epistemic",
        "claim_version",
        "epistemic_status IN ('PROVISIONAL', 'VERIFIED', 'CHALLENGED', 'UNPROVABLE')",
        schema="milai",
    )
    op.create_check_constraint(
        "ck_claim_version_freshness",
        "claim_version",
        "freshness IN ('CURRENT', 'STALE')",
        schema="milai",
    )
    op.execute(
        """
        CREATE FUNCTION milai.normalize_claim_version_axes()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          NEW.lifecycle := CASE NEW.lifecycle
            WHEN 'RETIRED' THEN 'ARCHIVED' ELSE NEW.lifecycle END;
          NEW.epistemic_status := CASE NEW.epistemic_status
            WHEN 'SUPPORTED' THEN 'VERIFIED'
            WHEN 'WEAKENED' THEN 'CHALLENGED'
            WHEN 'UNCERTAIN' THEN 'PROVISIONAL'
            ELSE NEW.epistemic_status END;
          NEW.freshness := CASE NEW.freshness
            WHEN 'UNKNOWN' THEN 'STALE' ELSE NEW.freshness END;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_version_normalize_axes
        BEFORE INSERT ON milai.claim_version
        FOR EACH ROW EXECUTE FUNCTION milai.normalize_claim_version_axes()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_version_append_only
        BEFORE UPDATE OR DELETE ON milai.claim_version
        FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()
        """
    )

    # A creation transition has no predecessor.  Revision zero / NULL status are
    # explicit sentinels only on ISSUE_CREATED; every later transition remains +1.
    op.alter_column(
        "version_transition",
        "old_claim_version_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="milai",
    )
    op.create_check_constraint(
        "ck_version_transition_creation",
        "version_transition",
        "(transition_type = 'CREATE' AND old_claim_version_id IS NULL) OR "
        "(transition_type <> 'CREATE' AND old_claim_version_id IS NOT NULL)",
        schema="milai",
    )
    op.drop_constraint(
        "ck_issue_transition_revision",
        "open_issue_transition",
        schema="milai",
        type_="check",
    )
    op.alter_column(
        "open_issue_transition",
        "from_status",
        existing_type=sa.Text(),
        nullable=True,
        schema="milai",
    )
    op.create_check_constraint(
        "ck_issue_transition_revision",
        "open_issue_transition",
        "(event_type = 'ISSUE_CREATED' AND from_status IS NULL "
        " AND from_revision = 0 AND to_revision = 1) OR "
        "(event_type <> 'ISSUE_CREATED' AND from_status IS NOT NULL "
        " AND to_revision = from_revision + 1)",
        schema="milai",
    )
    op.create_check_constraint(
        "ck_issue_transition_governed",
        "open_issue_transition",
        "proposal_id IS NOT NULL AND decision_id IS NOT NULL "
        "AND policy_version IS NOT NULL AND canonical_commit_seq IS NOT NULL",
        schema="milai",
        postgresql_not_valid=True,
    )

    op.execute(
        """
        CREATE FUNCTION milai.append_creation_history_from_decision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_version milai.claim_version%ROWTYPE;
          v_issue milai.open_issue%ROWTYPE;
        BEGIN
          IF NEW.decision <> 'APPROVE' THEN
            RETURN NEW;
          END IF;
          IF NEW.resulting_claim_version_id IS NOT NULL THEN
            SELECT * INTO v_version
            FROM milai.claim_version
            WHERE tenant_id = NEW.tenant_id
              AND claim_version_id = NEW.resulting_claim_version_id;
            IF FOUND AND v_version.version_number = 1
               AND NOT EXISTS (
                 SELECT 1 FROM milai.version_transition transition
                 WHERE transition.tenant_id = NEW.tenant_id
                   AND transition.new_claim_version_id = v_version.claim_version_id
               ) THEN
              INSERT INTO milai.version_transition (
                tenant_id, transition_id, claim_id, old_claim_version_id,
                new_claim_version_id, transition_type, proposal_id,
                decision_id, canonical_commit_seq, created_by_actor_id
              ) VALUES (
                NEW.tenant_id, gen_random_uuid(), v_version.claim_id, NULL,
                v_version.claim_version_id, 'CREATE', NEW.proposal_id,
                NEW.decision_id, NEW.canonical_commit_seq, NEW.decision_actor_id
              );
            END IF;
          END IF;
          IF NEW.resulting_open_issue_id IS NOT NULL THEN
            SELECT * INTO v_issue
            FROM milai.open_issue
            WHERE tenant_id = NEW.tenant_id
              AND issue_id = NEW.resulting_open_issue_id;
            IF FOUND AND v_issue.revision = 1
               AND v_issue.created_from_proposal_id = NEW.proposal_id
               AND NOT EXISTS (
                 SELECT 1 FROM milai.open_issue_transition transition
                 WHERE transition.tenant_id = NEW.tenant_id
                   AND transition.issue_id = v_issue.issue_id
               ) THEN
              INSERT INTO milai.open_issue_transition (
                tenant_id, transition_id, issue_id, from_status, to_status,
                from_revision, to_revision, event_type, proposal_id,
                decision_id, policy_version, canonical_commit_seq,
                created_by_actor_id
              ) VALUES (
                NEW.tenant_id, gen_random_uuid(), v_issue.issue_id, NULL,
                v_issue.status, 0, 1, 'ISSUE_CREATED', NEW.proposal_id,
                NEW.decision_id, NEW.policy_version,
                NEW.canonical_commit_seq, NEW.decision_actor_id
              );
            END IF;
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_steward_decision_creation_history
        AFTER INSERT ON milai.steward_decision
        FOR EACH ROW EXECUTE FUNCTION milai.append_creation_history_from_decision()
        """
    )

    # Keep the old implementations private so existing installations can migrate
    # without rewriting migration history.  The public wrappers below own the new
    # transaction contract.
    op.execute(
        f"ALTER FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) "
        "RENAME TO create_operation_proposal_legacy"
    )
    op.execute(
        f"ALTER FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "RENAME TO review_operation_proposal_legacy"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal_legacy({CREATE_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.review_operation_proposal_legacy({REVIEW_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )

    _create_proposal_function()
    _create_review_function()


def _create_proposal_function() -> None:
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
          v_outbox_id uuid;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
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
          IF p_proposed_patch ?| ARRAY[
            'resolve_issue_id', 'expected_issue_revision', 'addressed_branches'
          ] AND (
            p_operation <> 'SUPERSEDE'
            OR NOT (p_proposed_patch ?& ARRAY[
              'resolve_issue_id', 'expected_issue_revision', 'addressed_branches'
            ])
            OR jsonb_typeof(p_proposed_patch -> 'expected_issue_revision') <> 'number'
            OR jsonb_typeof(p_proposed_patch -> 'addressed_branches') <> 'array'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
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
        f"REVOKE ALL ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE}) TO milai_api"
    )


def _create_review_function() -> None:
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
          v_issue_id uuid;
          v_expected_issue_revision integer;
          v_decision_id uuid;
          v_new_version_id uuid;
          v_outbox_id uuid;
          v_commit_seq bigint;
          v_rows integer;
          v_new_payload jsonb;
          v_new_scope jsonb;
          v_new_authority text;
          v_new_confidence numeric;
          v_response jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          SELECT * INTO v_proposal
          FROM milai.operation_proposal
          WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROPOSAL_NOT_FOUND';
          END IF;
          IF NOT (v_proposal.proposed_patch ? 'resolve_issue_id') THEN
            RETURN milai.review_operation_proposal_legacy(
              p_tenant_id, p_actor_id, p_proposal_id, p_decision,
              p_decision_actor_type, p_policy_version, p_reason_code,
              p_idempotency_key, p_request_fingerprint
            );
          END IF;
          IF p_decision NOT IN ('APPROVE', 'REJECT')
             OR p_decision_actor_type NOT IN ('USER', 'STEWARD') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_DECISION';
          END IF;
          BEGIN
            v_issue_id := (v_proposal.proposed_patch ->> 'resolve_issue_id')::uuid;
            v_expected_issue_revision :=
              (v_proposal.proposed_patch ->> 'expected_issue_revision')::integer;
          EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_PROPOSAL';
          END;

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
          IF v_proposal.status <> 'PENDING_REVIEW' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'PROPOSAL_ALREADY_DECIDED';
          END IF;
          SELECT * INTO v_issue
          FROM milai.open_issue
          WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id;
          IF NOT FOUND
             OR v_issue.target_claim_id IS DISTINCT FROM v_proposal.target_claim_id THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
          END IF;

          v_decision_id := gen_random_uuid();
          IF p_decision = 'REJECT' THEN
            INSERT INTO milai.steward_decision (
              tenant_id, decision_id, proposal_id, decision,
              decision_actor_type, decision_actor_id, policy_version,
              reason_code, resulting_open_issue_id, created_by_actor_id
            ) VALUES (
              p_tenant_id, v_decision_id, p_proposal_id, 'REJECT',
              p_decision_actor_type, p_actor_id, p_policy_version,
              p_reason_code, v_issue_id, p_actor_id
            );
            UPDATE milai.operation_proposal SET status = 'REJECTED'
            WHERE tenant_id = p_tenant_id AND proposal_id = p_proposal_id;
            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(), 'CANONICAL_PROPOSAL_REJECTED',
              p_reason_code,
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'open_issue_id', v_issue_id
              ), p_actor_id
            );
            v_outbox_id := gen_random_uuid();
            INSERT INTO milai.outbox_event (
              tenant_id, outbox_id, aggregate_type, aggregate_id,
              event_type, payload, priority, created_by_actor_id
            ) VALUES (
              p_tenant_id, v_outbox_id, 'PROPOSAL', p_proposal_id,
              'PROPOSAL_REJECTED',
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'open_issue_id', v_issue_id
              ), 60, p_actor_id
            );
            v_response := jsonb_build_object(
              'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
              'decision', 'REJECT', 'open_issue_id', v_issue_id,
              'canonical_commit_seq', NULL, 'outbox_id', v_outbox_id,
              'replayed', false
            );
          ELSE
            IF v_proposal.operation <> 'SUPERSEDE'
               OR v_issue.status NOT IN ('OPEN', 'WAITING_EVIDENCE', 'WAITING_USER')
               OR v_issue.revision <> v_expected_issue_revision THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'ISSUE_REVISION_CONFLICT';
            END IF;
            IF NOT milai.evidence_refs_admissible(
                 p_tenant_id, v_proposal.supporting_evidence_refs
               )
               OR NOT milai.authority_satisfies(
                 v_proposal.requested_authority, v_issue.required_authority
               )
               OR NOT v_proposal.scope_predicate @> COALESCE(
                 v_issue.discharge_rule -> 'required_scope', '{}'::jsonb
               )
               OR NOT (v_proposal.proposed_patch -> 'addressed_branches') @>
                 COALESCE(
                   v_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
                 )
               OR EXISTS (
                 SELECT 1
                 FROM jsonb_array_elements_text(COALESCE(
                   v_issue.discharge_rule -> 'must_address_branches', '[]'::jsonb
                 )) required(branch_type)
                 WHERE NOT EXISTS (
                   SELECT 1 FROM milai.grounding_relation relation
                   WHERE relation.tenant_id = p_tenant_id
                     AND relation.open_issue_id = v_issue_id
                     AND relation.relation_type = required.branch_type
                 )
               )
               OR EXISTS (
                 SELECT 1 FROM milai.evidence_record evidence
                 WHERE evidence.tenant_id = p_tenant_id
                   AND evidence.evidence_id = ANY(v_proposal.supporting_evidence_refs)
                   AND NOT (
                     v_issue.discharge_rule -> 'required_evidence_kinds'
                     ? evidence.source_type
                   )
               )
               OR (
                 SELECT count(DISTINCT evidence.source_ref)
                 FROM milai.evidence_record evidence
                 WHERE evidence.tenant_id = p_tenant_id
                   AND evidence.evidence_id = ANY(v_proposal.supporting_evidence_refs)
               ) < COALESCE(
                 (v_issue.discharge_rule ->> 'minimum_independent_sources')::integer, 1
               ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
            END IF;
            SELECT version.* INTO v_current
            FROM milai.claim_head head
            JOIN milai.claim_version version
              ON version.tenant_id = head.tenant_id
             AND version.claim_version_id = head.current_claim_version_id
            WHERE head.tenant_id = p_tenant_id
              AND head.claim_id = v_proposal.target_claim_id
            FOR UPDATE OF head;
            IF NOT FOUND
               OR v_current.claim_version_id <> v_proposal.expected_version_id THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'VERSION_CONFLICT';
            END IF;
            IF EXISTS (
              SELECT 1 FROM milai.grounding_block block
              WHERE block.tenant_id = p_tenant_id
                AND block.claim_version_id = v_current.claim_version_id
                AND block.active
            ) THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'GROUNDING_BLOCKED';
            END IF;

            v_commit_seq := nextval('milai.canonical_commit_seq');
            v_new_version_id := gen_random_uuid();
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
              p_tenant_id, v_new_version_id, v_current.claim_id,
              v_current.version_number + 1, v_new_payload, v_new_scope,
              CASE WHEN v_proposal.proposed_patch ? 'valid_time_from'
                THEN NULLIF(v_proposal.proposed_patch ->> 'valid_time_from', '')::timestamptz
                ELSE v_current.valid_time_from END,
              CASE WHEN v_proposal.proposed_patch ? 'valid_time_to'
                THEN NULLIF(v_proposal.proposed_patch ->> 'valid_time_to', '')::timestamptz
                ELSE v_current.valid_time_to END,
              COALESCE(v_proposal.proposed_patch ->> 'lifecycle', v_current.lifecycle),
              COALESCE(
                v_proposal.proposed_patch ->> 'epistemic_status',
                v_current.epistemic_status
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
            INSERT INTO milai.grounding_relation (
              tenant_id, relation_id, open_issue_id, evidence_id,
              relation_type, created_from_proposal_id, created_by_actor_id
            ) SELECT
              p_tenant_id, gen_random_uuid(), v_issue_id, evidence_id,
              'RESOLUTION_CANDIDATE', p_proposal_id, p_actor_id
            FROM unnest(v_proposal.supporting_evidence_refs) AS evidence_id
            ON CONFLICT DO NOTHING;
            UPDATE milai.claim_head
            SET current_claim_version_id = v_new_version_id,
                updated_at = CURRENT_TIMESTAMP,
                updated_by_actor_id = p_actor_id
            WHERE tenant_id = p_tenant_id
              AND claim_id = v_current.claim_id
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
              p_tenant_id, gen_random_uuid(), v_current.claim_id,
              v_current.claim_version_id, v_new_version_id, 'SUPERSEDE',
              p_proposal_id, v_decision_id, v_commit_seq, p_actor_id
            );
            UPDATE milai.open_issue
            SET status = 'RESOLVED', revision = revision + 1,
                resolved_by_decision_id = v_decision_id,
                resolved_at = CURRENT_TIMESTAMP
            WHERE tenant_id = p_tenant_id AND issue_id = v_issue_id
              AND status = v_issue.status AND revision = v_expected_issue_revision;
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
              p_tenant_id, gen_random_uuid(), v_issue_id, v_issue.status,
              'RESOLVED', v_expected_issue_revision,
              v_expected_issue_revision + 1, 'DISCHARGE_APPROVED',
              p_proposal_id, v_decision_id, p_policy_version,
              v_commit_seq, p_actor_id
            );
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
                'operation', 'SUPERSEDE',
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
              p_tenant_id, v_outbox_id, 'OPEN_ISSUE', v_issue_id,
              'OPEN_ISSUE_CHANGED',
              jsonb_build_object(
                'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
                'operation', 'SUPERSEDE', 'claim_id', v_current.claim_id,
                'claim_version_id', v_new_version_id,
                'open_issue_id', v_issue_id
              ), 50, v_commit_seq, p_actor_id
            );
            v_response := jsonb_build_object(
              'proposal_id', p_proposal_id, 'decision_id', v_decision_id,
              'decision', 'APPROVE', 'claim_id', v_current.claim_id,
              'claim_version_id', v_new_version_id,
              'open_issue_id', v_issue_id, 'outbox_id', v_outbox_id,
              'canonical_commit_seq', v_commit_seq, 'replayed', false
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
        f"REVOKE ALL ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE}) "
        "TO milai_steward"
    )


def downgrade() -> None:
    connection = op.get_bind()
    creation_count = connection.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM milai.version_transition "
            "WHERE transition_type = 'CREATE') + "
            "(SELECT count(*) FROM milai.open_issue_transition "
            "WHERE event_type = 'ISSUE_CREATED')"
        )
    ).scalar_one()
    if creation_count:
        raise RuntimeError(
            "0015 downgrade is unsafe after governed creation history has been recorded"
        )
    op.execute(f"DROP FUNCTION milai.review_operation_proposal({REVIEW_SIGNATURE})")
    op.execute(f"DROP FUNCTION milai.create_operation_proposal({CREATE_SIGNATURE})")
    op.execute(
        f"ALTER FUNCTION milai.review_operation_proposal_legacy({REVIEW_SIGNATURE}) "
        "RENAME TO review_operation_proposal"
    )
    op.execute(
        f"ALTER FUNCTION milai.create_operation_proposal_legacy({CREATE_SIGNATURE}) "
        "RENAME TO create_operation_proposal"
    )
    op.execute("DROP TRIGGER trg_steward_decision_creation_history ON milai.steward_decision")
    op.execute("DROP FUNCTION milai.append_creation_history_from_decision()")
    op.drop_constraint(
        "ck_issue_transition_governed",
        "open_issue_transition",
        schema="milai",
        type_="check",
    )
    op.drop_constraint(
        "ck_issue_transition_revision",
        "open_issue_transition",
        schema="milai",
        type_="check",
    )
    op.alter_column(
        "open_issue_transition",
        "from_status",
        existing_type=sa.Text(),
        nullable=False,
        schema="milai",
    )
    op.create_check_constraint(
        "ck_issue_transition_revision",
        "open_issue_transition",
        "to_revision = from_revision + 1",
        schema="milai",
    )
    op.drop_constraint(
        "ck_version_transition_creation",
        "version_transition",
        schema="milai",
        type_="check",
    )
    op.alter_column(
        "version_transition",
        "old_claim_version_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="milai",
    )
    op.execute("DROP TRIGGER trg_claim_version_normalize_axes ON milai.claim_version")
    op.execute("DROP FUNCTION milai.normalize_claim_version_axes()")
