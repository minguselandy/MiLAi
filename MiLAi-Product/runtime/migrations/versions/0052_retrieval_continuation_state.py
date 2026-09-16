"""Add immutable, non-canonical retrieval continuation state.

Revision ID: 0052_retrieval_continuation
Revises: 0051_host_execution_event

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

from alembic import op

revision = "0052_retrieval_continuation"
down_revision = "0051_host_execution_event"
branch_labels = None
depends_on = None

ROOT_SIGNATURE = "uuid,uuid,jsonb"
SUCCESSOR_SIGNATURE = "uuid,uuid,jsonb"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE milai.retrieval_continuation_state (
          tenant_id uuid NOT NULL,
          state_id uuid NOT NULL,
          root_state_id uuid NOT NULL,
          predecessor_state_id uuid,
          generation integer NOT NULL,
          payload_semantics_version text NOT NULL
            DEFAULT 'retrieval-continuation-v0.1',
          query_digest text NOT NULL,
          request_digest text NOT NULL,
          snapshot_as_of timestamptz NOT NULL,
          canonical_position bigint,
          selected_evidence_ids jsonb NOT NULL,
          seen_evidence_ids jsonb NOT NULL,
          frontier_evidence_ids jsonb NOT NULL,
          operation_fingerprint text,
          state_digest text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          expires_at timestamptz NOT NULL,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_retrieval_continuation_state PRIMARY KEY (
            tenant_id, state_id
          ),
          CONSTRAINT uq_retrieval_continuation_identity UNIQUE (
            tenant_id, state_id, root_state_id
          ),
          CONSTRAINT fk_retrieval_continuation_root FOREIGN KEY (
            tenant_id, root_state_id
          ) REFERENCES milai.retrieval_continuation_state (tenant_id, state_id)
            DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_retrieval_continuation_predecessor FOREIGN KEY (
            tenant_id, predecessor_state_id
          ) REFERENCES milai.retrieval_continuation_state (tenant_id, state_id)
            ON DELETE RESTRICT,
          CONSTRAINT ck_retrieval_continuation_generation CHECK (
            generation BETWEEN 0 AND 4
          ),
          CONSTRAINT ck_retrieval_continuation_lineage CHECK (
            (generation = 0 AND predecessor_state_id IS NULL AND root_state_id = state_id)
            OR
            (generation > 0 AND predecessor_state_id IS NOT NULL)
          ),
          CONSTRAINT ck_retrieval_continuation_semantics CHECK (
            payload_semantics_version = 'retrieval-continuation-v0.1'
          ),
          CONSTRAINT ck_retrieval_continuation_digests CHECK (
            query_digest ~ '^[0-9a-f]{64}$'
            AND request_digest ~ '^[0-9a-f]{64}$'
            AND state_digest ~ '^[0-9a-f]{64}$'
            AND (
              operation_fingerprint IS NULL
              OR operation_fingerprint ~ '^[0-9a-f]{64}$'
            )
          ),
          CONSTRAINT ck_retrieval_continuation_arrays CHECK (
            jsonb_typeof(selected_evidence_ids) = 'array'
            AND jsonb_typeof(seen_evidence_ids) = 'array'
            AND jsonb_typeof(frontier_evidence_ids) = 'array'
            AND jsonb_array_length(selected_evidence_ids) <= 120
            AND jsonb_array_length(seen_evidence_ids) <= 120
            AND jsonb_array_length(frontier_evidence_ids) <= 120
          ),
          CONSTRAINT ck_retrieval_continuation_expiry CHECK (
            expires_at > created_at
            AND expires_at <= created_at + interval '1 day 5 minutes'
          )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_retrieval_continuation_operation
        ON milai.retrieval_continuation_state (
          tenant_id, created_by_actor_id, operation_fingerprint
        ) WHERE operation_fingerprint IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_retrieval_continuation_root
        ON milai.retrieval_continuation_state (
          tenant_id, created_by_actor_id, root_state_id, generation
        )
        """
    )
    op.execute("ALTER TABLE milai.retrieval_continuation_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE milai.retrieval_continuation_state FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY retrieval_continuation_state_tenant_actor_isolation
        ON milai.retrieval_continuation_state
        USING (
          tenant_id = milai.current_tenant_id()
          AND created_by_actor_id = milai.current_actor_id()
        )
        WITH CHECK (
          tenant_id = milai.current_tenant_id()
          AND created_by_actor_id = milai.current_actor_id()
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.reject_retrieval_continuation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'IMMUTABLE_RETRIEVAL_CONTINUATION';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_retrieval_continuation_immutable
        BEFORE UPDATE OR DELETE ON milai.retrieval_continuation_state
        FOR EACH ROW EXECUTE FUNCTION milai.reject_retrieval_continuation_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION milai.create_retrieval_continuation_root(
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
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          BEGIN
            v_state_id := (p_payload ->> 'state_id')::uuid;
          EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END;
          IF jsonb_typeof(p_payload) <> 'object'
             OR p_payload ->> 'query_digest' !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'request_digest' !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'state_digest' !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_payload -> 'selected_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'seen_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'frontier_evidence_ids') <> 'array'
             OR jsonb_array_length(p_payload -> 'selected_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'seen_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'frontier_evidence_ids') > 120
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'selected_evidence_ids'
               ) value WHERE NOT (p_payload -> 'seen_evidence_ids') ? value
             )
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'frontier_evidence_ids'
               ) value WHERE (p_payload -> 'seen_evidence_ids') ? value
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END IF;

          INSERT INTO milai.retrieval_continuation_state (
            tenant_id, state_id, root_state_id, predecessor_state_id,
            generation, query_digest, request_digest, snapshot_as_of,
            canonical_position, selected_evidence_ids, seen_evidence_ids,
            frontier_evidence_ids, operation_fingerprint, state_digest,
            expires_at, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_state_id, v_state_id, NULL, 0,
            p_payload ->> 'query_digest', p_payload ->> 'request_digest',
            (p_payload ->> 'snapshot_as_of')::timestamptz,
            (p_payload ->> 'canonical_position')::bigint,
            p_payload -> 'selected_evidence_ids',
            p_payload -> 'seen_evidence_ids',
            p_payload -> 'frontier_evidence_ids', NULL,
            p_payload ->> 'state_digest',
            (p_payload ->> 'expires_at')::timestamptz, p_actor_id
          ) ON CONFLICT (tenant_id, state_id) DO NOTHING;
          GET DIAGNOSTICS v_inserted = ROW_COUNT;

          SELECT * INTO v_existing
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND state_id = v_state_id;
          IF NOT FOUND OR v_existing.state_digest <> p_payload ->> 'state_digest' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
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
                )
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
        CREATE FUNCTION milai.create_retrieval_continuation_successor(
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
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          BEGIN
            v_state_id := (p_payload ->> 'state_id')::uuid;
            v_predecessor_id := (p_payload ->> 'predecessor_state_id')::uuid;
          EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END;
          v_operation := p_payload ->> 'operation_fingerprint';
          IF jsonb_typeof(p_payload) <> 'object'
             OR v_operation !~ '^[0-9a-f]{64}$'
             OR p_payload ->> 'state_digest' !~ '^[0-9a-f]{64}$'
             OR jsonb_typeof(p_payload -> 'selected_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'seen_evidence_ids') <> 'array'
             OR jsonb_typeof(p_payload -> 'frontier_evidence_ids') <> 'array'
             OR jsonb_array_length(p_payload -> 'selected_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'seen_evidence_ids') > 120
             OR jsonb_array_length(p_payload -> 'frontier_evidence_ids') > 120
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'selected_evidence_ids'
               ) value WHERE NOT (p_payload -> 'seen_evidence_ids') ? value
             )
             OR EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(
                 p_payload -> 'frontier_evidence_ids'
               ) value WHERE (p_payload -> 'seen_evidence_ids') ? value
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
          FOR SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'RETRIEVAL_CONTINUATION_NOT_FOUND';
          END IF;
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
          IF EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
              p_payload -> 'frontier_evidence_ids'
            ) value WHERE NOT v_predecessor.frontier_evidence_ids ? value
          ) OR EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
              v_predecessor.seen_evidence_ids
            ) value WHERE NOT (p_payload -> 'seen_evidence_ids') ? value
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001',
              MESSAGE = 'INVALID_RETRIEVAL_CONTINUATION';
          END IF;

          INSERT INTO milai.retrieval_continuation_state (
            tenant_id, state_id, root_state_id, predecessor_state_id,
            generation, query_digest, request_digest, snapshot_as_of,
            canonical_position, selected_evidence_ids, seen_evidence_ids,
            frontier_evidence_ids, operation_fingerprint, state_digest,
            expires_at, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_state_id, v_predecessor.root_state_id,
            v_predecessor.state_id, v_predecessor.generation + 1,
            v_predecessor.query_digest, v_predecessor.request_digest,
            v_predecessor.snapshot_as_of, v_predecessor.canonical_position,
            p_payload -> 'selected_evidence_ids',
            p_payload -> 'seen_evidence_ids',
            p_payload -> 'frontier_evidence_ids', v_operation,
            p_payload ->> 'state_digest', v_predecessor.expires_at, p_actor_id
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
              )
            ), p_actor_id
          );
          RETURN jsonb_build_object('state_id', v_state_id, 'replayed', false);
        EXCEPTION WHEN unique_violation THEN
          SELECT * INTO v_existing
          FROM milai.retrieval_continuation_state
          WHERE tenant_id = p_tenant_id
            AND created_by_actor_id = p_actor_id
            AND operation_fingerprint = v_operation;
          IF FOUND THEN
            RETURN jsonb_build_object(
              'state_id', v_existing.state_id,
              'replayed', true
            );
          END IF;
          RAISE;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON TABLE milai.retrieval_continuation_state "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.retrieval_continuation_state TO milai_api"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.retrieval_continuation_state TO milai_audit"
    )
    for name, signature in (
        ("create_retrieval_continuation_root", ROOT_SIGNATURE),
        ("create_retrieval_continuation_successor", SUCCESSOR_SIGNATURE),
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION milai.{name}({signature}) FROM PUBLIC"
        )
        op.execute(
            f"GRANT EXECUTE ON FUNCTION milai.{name}({signature}) TO milai_api"
        )


def downgrade() -> None:
    for name, signature in (
        ("create_retrieval_continuation_successor", SUCCESSOR_SIGNATURE),
        ("create_retrieval_continuation_root", ROOT_SIGNATURE),
    ):
        op.execute(
            f"REVOKE ALL ON FUNCTION milai.{name}({signature}) "
            "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
        )
        op.execute(f"DROP FUNCTION milai.{name}({signature})")
    op.execute(
        "DROP TRIGGER trg_retrieval_continuation_immutable "
        "ON milai.retrieval_continuation_state"
    )
    op.execute("DROP FUNCTION milai.reject_retrieval_continuation_mutation()")
    op.execute("DROP TABLE milai.retrieval_continuation_state")
