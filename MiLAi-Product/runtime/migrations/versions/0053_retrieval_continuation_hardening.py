"""Harden retrieval continuation identity, replay, and live eligibility.

Revision ID: 0053_continuation_hardening
Revises: 0052_retrieval_continuation

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

from alembic import op

revision = "0053_continuation_hardening"
down_revision = "0052_retrieval_continuation"
branch_labels = None
depends_on = None

SIGNATURE = "uuid,uuid,jsonb"
HYDRATE_SIGNATURE = "uuid,uuid,uuid[],jsonb,timestamptz,integer,text"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE milai.retrieval_continuation_state
        ADD COLUMN online_ineligible_count integer NOT NULL DEFAULT 0,
        DROP CONSTRAINT ck_retrieval_continuation_semantics,
        ADD CONSTRAINT ck_retrieval_continuation_semantics CHECK (
          payload_semantics_version IN (
            'retrieval-continuation-v0.1',
            'retrieval-continuation-v0.2'
          )
        ),
        ADD CONSTRAINT ck_retrieval_continuation_ineligible_count CHECK (
          online_ineligible_count BETWEEN 0 AND 120
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.hydrate_evidence_projection_by_id_v2(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_evidence_ids uuid[],
          p_requested_scope jsonb,
          p_as_of timestamptz,
          p_limit integer,
          p_projection_version text
        ) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
          WITH hydrated AS MATERIALIZED (
            SELECT value.item, value.ordinality
            FROM jsonb_array_elements(
              milai.hydrate_evidence_projection_by_id(
                p_tenant_id, p_actor_id, p_evidence_ids,
                p_requested_scope, p_as_of, p_limit, p_projection_version
              )
            ) WITH ORDINALITY AS value(item, ordinality)
          ), live_identity AS MATERIALIZED (
            SELECT hydrated.item, hydrated.ordinality
            FROM hydrated
            JOIN milai.evidence_search_document document
              ON document.tenant_id = p_tenant_id
             AND document.evidence_id = (hydrated.item ->> 'evidence_id')::uuid
             AND document.projection_version = p_projection_version
            JOIN milai.evidence_record evidence
              ON evidence.tenant_id = document.tenant_id
             AND evidence.evidence_id = document.evidence_id
             AND evidence.content_hash = document.content_hash
            WHERE evidence.revoked_at IS NULL
              AND evidence.retention_state = 'READABLE'
          )
          SELECT COALESCE(
            jsonb_agg(live_identity.item ORDER BY live_identity.ordinality),
            '[]'::jsonb
          )
          FROM live_identity
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.hydrate_evidence_projection_by_id_v2("
        f"{HYDRATE_SIGNATURE}) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.hydrate_evidence_projection_by_id_v2("
        f"{HYDRATE_SIGNATURE}) TO milai_api"
    )
    op.execute(
        """
        CREATE FUNCTION milai.create_retrieval_continuation_root_v2(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_payload jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_state_id uuid;
          v_existing milai.retrieval_continuation_state%ROWTYPE;
          v_inserted integer := 0;
          v_online_ineligible_count integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF octet_length(convert_to(p_payload::text, 'UTF8')) > 262144 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'STATE_SIZE_LIMIT_REACHED';
          END IF;
          BEGIN
            v_state_id := (p_payload ->> 'state_id')::uuid;
            v_online_ineligible_count :=
              (p_payload ->> 'online_ineligible_count')::integer;
          EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END;
          IF jsonb_typeof(p_payload) <> 'object'
             OR p_payload ->> 'query_digest' !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'request_digest' !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'state_digest' !~ '^[0-9a-f]{64}$'
             OR v_online_ineligible_count NOT BETWEEN 0 AND 120
             OR jsonb_typeof(p_payload -> 'selected_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'seen_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'frontier_evidence_ids') <> 'array'
             OR jsonb_array_length(p_payload -> 'selected_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'seen_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'frontier_evidence_ids') > 120
             OR p_payload -> 'selected_evidence_ids'
                <> p_payload -> 'seen_evidence_ids'
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 (p_payload -> 'selected_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
               ) value WHERE value !~
                 '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
             )
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'frontier_evidence_ids'
               ) value WHERE (p_payload -> 'seen_evidence_ids') ? value
             )
             OR (
               SELECT count(*) FROM jsonb_array_elements_text(
                 (p_payload -> 'seen_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
               )
             ) <> (
               SELECT count(DISTINCT value) FROM jsonb_array_elements_text(
                 (p_payload -> 'seen_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
               ) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END IF;

          INSERT INTO milai.retrieval_continuation_state (
            tenant_id, state_id, root_state_id, predecessor_state_id,
            generation, payload_semantics_version, query_digest,
            request_digest, snapshot_as_of, canonical_position,
            selected_evidence_ids, seen_evidence_ids, frontier_evidence_ids,
            online_ineligible_count, operation_fingerprint, state_digest,
            expires_at, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_state_id, v_state_id, NULL, 0,
            'retrieval-continuation-v0.2', p_payload ->> 'query_digest',
            p_payload ->> 'request_digest',
            (p_payload ->> 'snapshot_as_of')::timestamptz,
            (p_payload ->> 'canonical_position')::bigint,
            p_payload -> 'selected_evidence_ids',
            p_payload -> 'seen_evidence_ids',
            p_payload -> 'frontier_evidence_ids', v_online_ineligible_count,
            NULL, p_payload ->> 'state_digest',
            (p_payload ->> 'expires_at')::timestamptz, p_actor_id
          ) ON CONFLICT (tenant_id, state_id) DO NOTHING;
          GET DIAGNOSTICS v_inserted = ROW_COUNT;

          SELECT * INTO v_existing
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND state_id = v_state_id;
          IF NOT FOUND
             OR v_existing.state_digest <> p_payload ->> 'state_digest'
             OR v_existing.online_ineligible_count <> v_online_ineligible_count THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'OPERATION_CONFLICT';
          END IF;
          IF v_inserted = 1 THEN
            INSERT INTO milai.operational_event (
              tenant_id, event_id, event_type, reason_code, safe_metadata,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, gen_random_uuid(),
              'RETRIEVAL_CONTINUATION_ROOT_CREATED', NULL,
              jsonb_build_object(
                'state_id', v_state_id,
                'frontier_count', jsonb_array_length(
                  p_payload -> 'frontier_evidence_ids'
                ),
                'online_ineligible_count', v_online_ineligible_count
              ), p_actor_id
            );
          END IF;
          RETURN jsonb_build_object(
            'state_id', v_state_id,
            'replayed', v_inserted = 0
          );
        EXCEPTION WHEN invalid_text_representation OR datetime_field_overflow THEN
          RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.create_retrieval_continuation_successor_v2(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_payload jsonb
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_state_id uuid;
          v_predecessor_id uuid;
          v_predecessor milai.retrieval_continuation_state%ROWTYPE;
          v_existing milai.retrieval_continuation_state%ROWTYPE;
          v_operation text;
          v_expected_frontier jsonb;
          v_online_ineligible_count integer;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF octet_length(convert_to(p_payload::text, 'UTF8')) > 262144 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'STATE_SIZE_LIMIT_REACHED';
          END IF;
          BEGIN
            v_state_id := (p_payload ->> 'state_id')::uuid;
            v_predecessor_id := (p_payload ->> 'predecessor_state_id')::uuid;
            v_online_ineligible_count :=
              (p_payload ->> 'online_ineligible_count')::integer;
          EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END;
          v_operation := p_payload ->> 'operation_fingerprint';
          IF jsonb_typeof(p_payload) <> 'object'
             OR v_operation !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'state_digest' !~ '^[0-9a-f]{64}$'
             OR v_online_ineligible_count NOT BETWEEN 0 AND 120
             OR jsonb_typeof(p_payload -> 'selected_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'seen_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'frontier_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'discarded_evidence_ids') <> 'array'
             OR jsonb_array_length(p_payload -> 'selected_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'seen_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'frontier_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'discarded_evidence_ids') > 120
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 (p_payload -> 'selected_evidence_ids')
                 || (p_payload -> 'seen_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
                 || (p_payload -> 'discarded_evidence_ids')
               ) value WHERE value !~
                 '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
             )
             OR (
               SELECT count(*) FROM jsonb_array_elements_text(
                 (p_payload -> 'selected_evidence_ids')
                 || (p_payload -> 'discarded_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
               )
             ) <> (
               SELECT count(DISTINCT value) FROM jsonb_array_elements_text(
                 (p_payload -> 'selected_evidence_ids')
                 || (p_payload -> 'discarded_evidence_ids')
                 || (p_payload -> 'frontier_evidence_ids')
               ) value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END IF;

          SELECT * INTO v_existing
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND operation_fingerprint = v_operation;
          IF FOUND THEN
            IF v_existing.state_id <> v_state_id
               OR v_existing.predecessor_state_id <> v_predecessor_id
               OR v_existing.state_digest <> p_payload ->> 'state_digest'
               OR v_existing.online_ineligible_count
                  <> v_online_ineligible_count THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001',
                MESSAGE = 'OPERATION_CONFLICT';
            END IF;
            RETURN jsonb_build_object(
              'state_id', v_existing.state_id,
              'replayed', true
            );
          END IF;

          SELECT * INTO v_predecessor
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND state_id = v_predecessor_id
          FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'RETRIEVAL_CONTINUATION_NOT_FOUND';
          END IF;
          PERFORM 1 FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND state_id = v_predecessor.root_state_id
          FOR UPDATE;
          IF v_predecessor.expires_at <= CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'RETRIEVAL_CONTINUATION_EXPIRED';
          END IF;
          IF v_predecessor.generation >= 4 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'GENERATION_LIMIT_REACHED';
          END IF;
          IF (
            SELECT count(*) FROM milai.retrieval_continuation_state
            WHERE tenant_id = p_tenant_id
              AND created_by_actor_id = p_actor_id
              AND predecessor_state_id = v_predecessor_id
          ) >= 8 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'SUCCESSOR_LIMIT_REACHED';
          END IF;
          IF (
            SELECT count(*) FROM milai.retrieval_continuation_state
            WHERE tenant_id = p_tenant_id
              AND created_by_actor_id = p_actor_id
              AND root_state_id = v_predecessor.root_state_id
          ) >= 16 THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'ROOT_STATE_LIMIT_REACHED';
          END IF;

          SELECT COALESCE(jsonb_agg(value ORDER BY ordinality), '[]'::jsonb)
          INTO v_expected_frontier
          FROM jsonb_array_elements_text(
            v_predecessor.frontier_evidence_ids
          ) WITH ORDINALITY frontier(value, ordinality)
          WHERE NOT (p_payload -> 'selected_evidence_ids') ? value
            AND NOT (p_payload -> 'discarded_evidence_ids') ? value;

          IF EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'selected_evidence_ids'
               ) value WHERE NOT v_predecessor.frontier_evidence_ids ? value
             )
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'discarded_evidence_ids'
               ) value WHERE NOT v_predecessor.frontier_evidence_ids ? value
             )
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'discarded_evidence_ids'
               ) value WHERE (p_payload -> 'selected_evidence_ids') ? value
             )
             OR p_payload -> 'frontier_evidence_ids' <> v_expected_frontier
             OR p_payload -> 'seen_evidence_ids'
                <> v_predecessor.seen_evidence_ids
                   || (p_payload -> 'selected_evidence_ids')
             OR v_online_ineligible_count
                <> v_predecessor.online_ineligible_count
                   + jsonb_array_length(p_payload -> 'discarded_evidence_ids') THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END IF;

          INSERT INTO milai.retrieval_continuation_state (
            tenant_id, state_id, root_state_id, predecessor_state_id,
            generation, payload_semantics_version, query_digest,
            request_digest, snapshot_as_of, canonical_position,
            selected_evidence_ids, seen_evidence_ids, frontier_evidence_ids,
            online_ineligible_count, operation_fingerprint, state_digest,
            expires_at, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_state_id, v_predecessor.root_state_id,
            v_predecessor.state_id, v_predecessor.generation + 1,
            'retrieval-continuation-v0.2', v_predecessor.query_digest,
            v_predecessor.request_digest, v_predecessor.snapshot_as_of,
            v_predecessor.canonical_position,
            p_payload -> 'selected_evidence_ids',
            p_payload -> 'seen_evidence_ids',
            p_payload -> 'frontier_evidence_ids', v_online_ineligible_count,
            v_operation, p_payload ->> 'state_digest',
            v_predecessor.expires_at, p_actor_id
          );
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(),
            'RETRIEVAL_CONTINUATION_ADVANCED', NULL,
            jsonb_build_object(
              'state_id', v_state_id,
              'root_state_id', v_predecessor.root_state_id,
              'predecessor_state_id', v_predecessor.state_id,
              'generation', v_predecessor.generation + 1,
              'frontier_count', jsonb_array_length(
                p_payload -> 'frontier_evidence_ids'
              ),
              'online_ineligible_count', v_online_ineligible_count
            ), p_actor_id
          );
          RETURN jsonb_build_object('state_id', v_state_id, 'replayed', false);
        EXCEPTION WHEN unique_violation THEN
          SELECT * INTO v_existing
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND operation_fingerprint = v_operation;
          IF FOUND
             AND v_existing.state_id = v_state_id
             AND v_existing.predecessor_state_id = v_predecessor_id
             AND v_existing.state_digest = p_payload ->> 'state_digest'
             AND v_existing.online_ineligible_count = v_online_ineligible_count THEN
            RETURN jsonb_build_object(
              'state_id', v_existing.state_id,
              'replayed', true
            );
          END IF;
          RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'OPERATION_CONFLICT';
        END
        $$
        """
    )
    for name in (
        "create_retrieval_continuation_root_v2",
        "create_retrieval_continuation_successor_v2",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION milai.{name}({SIGNATURE}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION milai.{name}({SIGNATURE}) TO milai_api")


def downgrade() -> None:
    for name in (
        "create_retrieval_continuation_successor_v2",
        "create_retrieval_continuation_root_v2",
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION milai.{name}({SIGNATURE}) "
            "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
        )
        op.execute(f"DROP FUNCTION milai.{name}({SIGNATURE})")
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.hydrate_evidence_projection_by_id_v2("
        f"{HYDRATE_SIGNATURE}) FROM PUBLIC, milai_api, milai_steward, "
        "milai_worker, milai_audit"
    )
    op.execute(
        f"DROP FUNCTION milai.hydrate_evidence_projection_by_id_v2("
        f"{HYDRATE_SIGNATURE})"
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM milai.retrieval_continuation_state
            WHERE payload_semantics_version = 'retrieval-continuation-v0.2'
          ) THEN
            RAISE EXCEPTION 'RETRIEVAL_CONTINUATION_V2_STATE_EXISTS';
          END IF;
        END
        $$;
        ALTER TABLE milai.retrieval_continuation_state
        DROP CONSTRAINT ck_retrieval_continuation_ineligible_count,
        DROP CONSTRAINT ck_retrieval_continuation_semantics,
        DROP COLUMN online_ineligible_count,
        ADD CONSTRAINT ck_retrieval_continuation_semantics CHECK (
          payload_semantics_version = 'retrieval-continuation-v0.1'
        )
        """
    )
