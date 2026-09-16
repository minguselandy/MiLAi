"""Add one bitemporal mode to the authoritative Canonical Gate.

Revision ID: 0030_memory_state_view_gate
Revises: 0029_dg13_access_trace

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
MemoryStateView remains a dynamic read model; this migration creates no table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_memory_state_view_gate"
down_revision: str | None = "0029_dg13_access_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_GATE_SIGNATURE = (
    "uuid, uuid, uuid[], text, jsonb, timestamptz, text, text[], text, numeric, timestamptz"
)
BITEMPORAL_GATE_SIGNATURE = CURRENT_GATE_SIGNATURE + ", boolean"


def upgrade() -> None:
    _create_bitemporal_gate()
    _replace_current_wrapper()


def _create_bitemporal_gate() -> None:
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
          p_system_as_of timestamptz,
          p_allow_historical boolean
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_candidate_id uuid;
          v_state milai.effective_claim_state%ROWTYPE;
          v_state_found boolean;
          v_reason text;
          v_historical_open_issue_ids jsonb;
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
             OR p_allow_historical IS NULL
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
            v_state_found := FOUND;
            IF v_state_found AND p_allow_historical THEN
              SELECT COALESCE(
                jsonb_agg(issue.issue_id ORDER BY issue.issue_id),
                '[]'::jsonb
              ) INTO v_historical_open_issue_ids
              FROM milai.open_issue issue
              WHERE issue.tenant_id = p_tenant_id
                AND issue.target_claim_id = v_state.claim_id
                AND issue.created_at <= p_system_as_of
                AND issue.scope_predicate @> p_requested_scope
                AND COALESCE((
                  SELECT transition.to_status
                  FROM milai.open_issue_transition transition
                  WHERE transition.tenant_id = issue.tenant_id
                    AND transition.issue_id = issue.issue_id
                    AND transition.created_at <= p_system_as_of
                  ORDER BY transition.canonical_commit_seq DESC NULLS LAST,
                           transition.created_at DESC,
                           transition.transition_id DESC
                  LIMIT 1
                ), CASE
                     WHEN issue.resolved_at IS NULL
                       OR issue.resolved_at > p_system_as_of THEN 'OPEN'
                     ELSE 'RESOLVED'
                   END) NOT IN ('RESOLVED', 'DISMISSED');
            ELSE
              v_historical_open_issue_ids := '[]'::jsonb;
            END IF;
            IF NOT v_state_found THEN
              v_reason := 'UNKNOWN_CANDIDATE';
            ELSIF NOT p_allow_historical AND NOT v_state.is_current THEN
              v_reason := 'STALE_VERSION';
            ELSIF NOT p_allow_historical
                  AND v_state.lifecycle <> p_required_lifecycle THEN
              v_reason := 'LIFECYCLE_MISMATCH';
            ELSIF NOT v_state.epistemic_status = ANY(p_accepted_epistemic_statuses) THEN
              v_reason := 'EPISTEMIC_MISMATCH';
            ELSIF NOT p_allow_historical
                  AND v_state.freshness <> p_required_freshness THEN
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
            ELSIF (
              p_allow_historical
              AND jsonb_array_length(v_historical_open_issue_ids) > 0
            ) OR (NOT p_allow_historical AND v_state.has_live_open_issue) THEN
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
              'historical_resolution', p_allow_historical,
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
              'open_issue_ids', CASE
                WHEN v_reason = 'UNKNOWN_CANDIDATE' THEN '[]'::jsonb
                WHEN p_allow_historical THEN v_historical_open_issue_ids
                ELSE v_state.open_issue_ids
              END
            ));
          END LOOP;
          RETURN v_result;
        END
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.evaluate_canonical_candidates({BITEMPORAL_GATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"milai.evaluate_canonical_candidates({BITEMPORAL_GATE_SIGNATURE}) "
        "TO milai_api, milai_steward"
    )


def _replace_current_wrapper() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION milai.evaluate_canonical_candidates(
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
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
          SELECT milai.evaluate_canonical_candidates(
            p_tenant_id, p_actor_id, p_claim_version_ids,
            p_required_authority, p_requested_scope, p_valid_as_of,
            p_required_lifecycle, p_accepted_epistemic_statuses,
            p_required_freshness, p_minimum_confidence, p_system_as_of,
            false
          )
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"milai.evaluate_canonical_candidates({CURRENT_GATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"milai.evaluate_canonical_candidates({CURRENT_GATE_SIGNATURE}) "
        "TO milai_api, milai_steward"
    )


def downgrade() -> None:
    raise RuntimeError(
        "0030 downgrade is intentionally unsupported: bitemporal gate traces may already exist; "
        "restore a verified pre-0030 backup"
    )
