"""Make ECS the authoritative, axis-complete Canonical Gate input.

Revision ID: 0017_authoritative_ecs
Revises: 0016_governed_revocation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_authoritative_ecs"
down_revision: str | None = "0016_governed_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_GATE_SIGNATURE = "uuid, uuid, uuid[], text, jsonb, timestamptz"
NEW_GATE_SIGNATURE = (
    "uuid, uuid, uuid[], text, jsonb, timestamptz, text, text[], text, numeric, timestamptz"
)


def upgrade() -> None:
    op.execute("DROP VIEW milai.effective_claim_state")
    _create_effective_claim_state()
    op.execute(
        "GRANT SELECT ON milai.effective_claim_state TO milai_api, milai_steward, milai_audit"
    )
    op.execute(
        f"ALTER FUNCTION milai.evaluate_canonical_candidates({OLD_GATE_SIGNATURE}) "
        "RENAME TO evaluate_canonical_candidates_legacy"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.evaluate_canonical_candidates_legacy({OLD_GATE_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    _create_gate()


def _create_effective_claim_state() -> None:
    op.execute(
        """
        CREATE VIEW milai.effective_claim_state
        WITH (security_invoker = true)
        AS
        SELECT
          claim.tenant_id,
          claim.claim_id,
          claim.subject_id,
          claim.predicate,
          claim.claim_type,
          version.claim_version_id,
          version.version_number,
          version.payload,
          version.scope_predicate,
          version.valid_time_from,
          version.valid_time_to,
          version.system_time,
          version.lifecycle,
          version.epistemic_status,
          version.freshness,
          version.authority,
          version.confidence,
          version.canonical_commit_seq,
          head.current_claim_version_id = version.claim_version_id AS is_current,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
          ) AS has_any_grounding,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = relation.tenant_id
             AND evidence.evidence_id = relation.evidence_id
            JOIN milai.content_blob blob
              ON blob.tenant_id = evidence.tenant_id
             AND blob.blob_id = evidence.blob_id
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
              AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
              AND blob.physical_delete_state = 'PRESENT'
          ) AS has_live_grounding,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = relation.tenant_id
             AND evidence.evidence_id = relation.evidence_id
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND evidence.revoked_at IS NOT NULL
          ) AS has_revoked_grounding,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = relation.tenant_id
             AND evidence.evidence_id = relation.evidence_id
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND evidence.retention_state <> 'READABLE'
          ) AS has_unreadable_retention,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = relation.tenant_id
             AND evidence.evidence_id = relation.evidence_id
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND NOT evidence.permission_snapshot @> '{"readable": true}'::jsonb
          ) AS has_permission_denied,
          EXISTS (
            SELECT 1
            FROM milai.grounding_relation relation
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = relation.tenant_id
             AND evidence.evidence_id = relation.evidence_id
            JOIN milai.content_blob blob
              ON blob.tenant_id = evidence.tenant_id
             AND blob.blob_id = evidence.blob_id
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
              AND blob.physical_delete_state <> 'PRESENT'
          ) AS has_unavailable_blob,
          EXISTS (
            SELECT 1 FROM milai.grounding_block block
            WHERE block.tenant_id = version.tenant_id
              AND block.claim_version_id = version.claim_version_id
              AND block.active
          ) AS has_live_block,
          EXISTS (
            SELECT 1 FROM milai.open_issue issue
            WHERE issue.tenant_id = claim.tenant_id
              AND issue.target_claim_id = claim.claim_id
              AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
          ) AS has_live_open_issue,
          COALESCE((
            SELECT jsonb_agg(DISTINCT relation.evidence_id ORDER BY relation.evidence_id)
            FROM milai.grounding_relation relation
            WHERE relation.tenant_id = version.tenant_id
              AND relation.claim_version_id = version.claim_version_id
              AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
          ), '[]'::jsonb) AS evidence_ids,
          COALESCE((
            SELECT jsonb_agg(issue.issue_id ORDER BY issue.issue_id)
            FROM milai.open_issue issue
            WHERE issue.tenant_id = claim.tenant_id
              AND issue.target_claim_id = claim.claim_id
              AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
          ), '[]'::jsonb) AS open_issue_ids,
          CASE
            WHEN head.current_claim_version_id <> version.claim_version_id
              THEN 'STALE_VERSION'
            WHEN version.lifecycle <> 'ACTIVE' THEN 'LIFECYCLE_BLOCKED'
            WHEN version.epistemic_status IN ('CHALLENGED', 'UNPROVABLE')
              THEN 'EPISTEMIC_BLOCKED'
            WHEN version.freshness <> 'CURRENT' THEN 'STALE'
            WHEN EXISTS (
              SELECT 1 FROM milai.grounding_block block
              WHERE block.tenant_id = version.tenant_id
                AND block.claim_version_id = version.claim_version_id
                AND block.active
            ) THEN 'BLOCKED'
            WHEN NOT EXISTS (
              SELECT 1
              FROM milai.grounding_relation relation
              JOIN milai.evidence_record evidence
                ON evidence.tenant_id = relation.tenant_id
               AND evidence.evidence_id = relation.evidence_id
              JOIN milai.content_blob blob
                ON blob.tenant_id = evidence.tenant_id
               AND blob.blob_id = evidence.blob_id
              WHERE relation.tenant_id = version.tenant_id
                AND relation.claim_version_id = version.claim_version_id
                AND relation.relation_type IN ('SUPPORTS', 'DERIVED_FROM')
                AND evidence.revoked_at IS NULL
                AND evidence.retention_state = 'READABLE'
                AND evidence.permission_snapshot @> '{"readable": true}'::jsonb
                AND blob.physical_delete_state = 'PRESENT'
            ) THEN 'UNGROUNDED'
            WHEN EXISTS (
              SELECT 1 FROM milai.open_issue issue
              WHERE issue.tenant_id = claim.tenant_id
                AND issue.target_claim_id = claim.claim_id
                AND issue.status NOT IN ('RESOLVED', 'DISMISSED')
            ) THEN 'CONFLICTED'
            ELSE 'EFFECTIVE'
          END AS effective_status
        FROM milai.claim claim
        JOIN milai.claim_head head
          ON head.tenant_id = claim.tenant_id AND head.claim_id = claim.claim_id
        JOIN milai.claim_version version
          ON version.tenant_id = claim.tenant_id
         AND version.claim_id = claim.claim_id
        """
    )


def _create_gate() -> None:
    op.execute(
        """
        CREATE FUNCTION milai.evaluate_canonical_candidates(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_claim_version_ids uuid[],
          p_required_authority text,
          p_requested_scope jsonb,
          p_valid_as_of timestamptz,
          p_required_lifecycle text,
          p_accepted_epistemic_statuses text[],
          p_required_freshness text,
          p_minimum_confidence numeric,
          p_system_as_of timestamptz
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_candidate_id uuid;
          v_state milai.effective_claim_state%ROWTYPE;
          v_reason text;
          v_result jsonb := '[]'::jsonb;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_required_authority NOT IN (
               'INFORMATIONAL', 'ACTION_SAFE', 'USER_CONFIRMED'
             )
             OR jsonb_typeof(p_requested_scope) <> 'object'
             OR p_valid_as_of IS NULL OR p_system_as_of IS NULL
             OR p_required_lifecycle NOT IN (
               'ACTIVE', 'SUPERSEDED', 'ARCHIVED', 'DELETED'
             )
             OR COALESCE(cardinality(p_accepted_epistemic_statuses), 0) = 0
             OR EXISTS (
               SELECT 1 FROM unnest(p_accepted_epistemic_statuses) value
               WHERE value NOT IN (
                 'PROVISIONAL', 'VERIFIED', 'CHALLENGED', 'UNPROVABLE'
               )
             )
             OR p_required_freshness NOT IN ('CURRENT', 'STALE')
             OR p_minimum_confidence IS NULL
             OR p_minimum_confidence < 0 OR p_minimum_confidence > 1
             OR COALESCE(cardinality(p_claim_version_ids), 0) > 256 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_GATE_REQUEST';
          END IF;

          FOREACH v_candidate_id IN ARRAY COALESCE(p_claim_version_ids, '{}'::uuid[])
          LOOP
            v_reason := NULL;
            SELECT * INTO v_state
            FROM milai.effective_claim_state state
            WHERE state.tenant_id = p_tenant_id
              AND state.claim_version_id = v_candidate_id;
            IF NOT FOUND THEN
              v_reason := 'UNKNOWN_CANDIDATE';
            ELSIF NOT v_state.is_current THEN
              v_reason := 'STALE_VERSION';
            ELSIF v_state.lifecycle <> p_required_lifecycle THEN
              v_reason := 'LIFECYCLE_MISMATCH';
            ELSIF NOT v_state.epistemic_status = ANY(p_accepted_epistemic_statuses) THEN
              v_reason := 'EPISTEMIC_MISMATCH';
            ELSIF v_state.freshness <> p_required_freshness THEN
              v_reason := 'FRESHNESS_MISMATCH';
            ELSIF NOT v_state.scope_predicate @> p_requested_scope THEN
              v_reason := 'SCOPE_MISMATCH';
            ELSIF (v_state.valid_time_from IS NOT NULL
                   AND v_state.valid_time_from > p_valid_as_of)
               OR (v_state.valid_time_to IS NOT NULL
                   AND v_state.valid_time_to <= p_valid_as_of) THEN
              v_reason := 'OUTSIDE_VALID_TIME';
            ELSIF v_state.system_time > p_system_as_of THEN
              v_reason := 'OUTSIDE_SYSTEM_TIME';
            ELSIF NOT milai.authority_satisfies(
              v_state.authority, p_required_authority
            ) THEN
              v_reason := 'AUTHORITY_INSUFFICIENT';
            ELSIF v_state.confidence < p_minimum_confidence THEN
              v_reason := 'CONFIDENCE_BELOW_MINIMUM';
            ELSIF v_state.has_live_block THEN
              v_reason := 'GROUNDING_BLOCKED';
            ELSIF v_state.has_live_open_issue THEN
              v_reason := 'OPEN_ISSUE';
            ELSIF NOT v_state.has_any_grounding THEN
              v_reason := 'LINEAGE_MISSING';
            ELSIF v_state.has_revoked_grounding THEN
              v_reason := 'EVIDENCE_REVOKED';
            ELSIF v_state.has_unreadable_retention THEN
              v_reason := 'RETENTION_UNREADABLE';
            ELSIF v_state.has_permission_denied THEN
              v_reason := 'PERMISSION_DENIED';
            ELSIF v_state.has_unavailable_blob THEN
              v_reason := 'BLOB_UNAVAILABLE';
            ELSIF NOT v_state.has_live_grounding THEN
              v_reason := 'LINEAGE_NOT_LIVE';
            END IF;

            v_result := v_result || jsonb_build_array(jsonb_build_object(
              'claim_version_id', v_candidate_id,
              'claim_id', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                               THEN NULL ELSE v_state.claim_id END,
              'accepted', v_reason IS NULL,
              'reject_reason', v_reason,
              'lifecycle', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                THEN NULL ELSE v_state.lifecycle END,
              'epistemic_status', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                       THEN NULL ELSE v_state.epistemic_status END,
              'freshness', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                THEN NULL ELSE v_state.freshness END,
              'authority', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                THEN NULL ELSE v_state.authority END,
              'confidence', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                 THEN NULL ELSE v_state.confidence END,
              'system_time', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                  THEN NULL ELSE v_state.system_time END,
              'canonical_commit_seq', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                           THEN NULL
                                           ELSE v_state.canonical_commit_seq END,
              'evidence_ids', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                   THEN '[]'::jsonb ELSE v_state.evidence_ids END,
              'open_issue_ids', CASE WHEN v_reason = 'UNKNOWN_CANDIDATE'
                                     THEN '[]'::jsonb ELSE v_state.open_issue_ids END
            ));
          END LOOP;
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.evaluate_canonical_candidates({NEW_GATE_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.evaluate_canonical_candidates({NEW_GATE_SIGNATURE}) "
        "TO milai_api, milai_steward"
    )


def downgrade() -> None:
    raise RuntimeError("0017 downgrade is intentionally unsupported for canonical state semantics")
