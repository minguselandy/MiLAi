"""Add the sparse, append-only Host execution Event journal.

Revision ID: 0051_host_execution_event
Revises: 0050_host_cognitive_state

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

from alembic import op

revision = "0051_host_execution_event"
down_revision = "0050_host_cognitive_state"
branch_labels = None
depends_on = None

APPEND_SIGNATURE = (
    "uuid,uuid,text,text,text,text,text,timestamp with time zone,jsonb,uuid[],text,text"
)


def _tenant_actor_policy(table: str) -> None:
    op.execute(f"ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_actor_isolation
        ON milai.{table}
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


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE milai.host_execution_event (
          tenant_id uuid NOT NULL,
          event_id uuid NOT NULL,
          position bigint GENERATED ALWAYS AS IDENTITY,
          principal_binding_digest text NOT NULL,
          project_id text NOT NULL,
          task_ref text NOT NULL,
          event_family text NOT NULL,
          event_type text NOT NULL,
          observed_at timestamptz NOT NULL,
          bounded_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          operation_id text NOT NULL,
          request_fingerprint text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_host_execution_event PRIMARY KEY (tenant_id, event_id),
          CONSTRAINT uq_host_execution_event_position UNIQUE (position),
          CONSTRAINT ck_host_execution_event_principal CHECK (
            principal_binding_digest ~ '^[0-9a-f]{64}$'
          ),
          CONSTRAINT ck_host_execution_event_project CHECK (
            length(btrim(project_id)) BETWEEN 1 AND 512
          ),
          CONSTRAINT ck_host_execution_event_task CHECK (
            length(btrim(task_ref)) BETWEEN 1 AND 1024
          ),
          CONSTRAINT ck_host_execution_event_family CHECK (
            event_family ~ '^[A-Z][A-Z0-9_.-]{0,63}$'
          ),
          CONSTRAINT ck_host_execution_event_type CHECK (
            event_type ~ '^[A-Z][A-Z0-9_.-]{0,95}$'
          ),
          CONSTRAINT ck_host_execution_event_payload CHECK (
            jsonb_typeof(bounded_payload) = 'object'
            AND octet_length(bounded_payload::text) <= 16384
          ),
          CONSTRAINT ck_host_execution_event_operation CHECK (
            length(operation_id) BETWEEN 1 AND 128
          ),
          CONSTRAINT ck_host_execution_event_fingerprint CHECK (
            request_fingerprint ~ '^[0-9a-f]{64}$'
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_host_execution_event_binding_position
        ON milai.host_execution_event (
          tenant_id, created_by_actor_id, principal_binding_digest,
          project_id, task_ref, position
        )
        """
    )
    op.execute(
        """
        CREATE TABLE milai.host_execution_event_evidence_ref (
          tenant_id uuid NOT NULL,
          event_id uuid NOT NULL,
          evidence_id uuid NOT NULL,
          ordinal integer NOT NULL,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_host_execution_event_evidence_ref PRIMARY KEY (
            tenant_id, event_id, evidence_id
          ),
          CONSTRAINT uq_host_execution_event_evidence_ordinal UNIQUE (
            tenant_id, event_id, ordinal
          ),
          CONSTRAINT fk_host_execution_event_ref_event FOREIGN KEY (
            tenant_id, event_id
          ) REFERENCES milai.host_execution_event (tenant_id, event_id)
            ON DELETE RESTRICT,
          CONSTRAINT fk_host_execution_event_ref_evidence FOREIGN KEY (
            tenant_id, evidence_id
          ) REFERENCES milai.evidence_record (tenant_id, evidence_id)
            ON DELETE RESTRICT,
          CONSTRAINT ck_host_execution_event_ref_ordinal CHECK (ordinal >= 0)
        )
        """
    )

    for table in (
        "host_execution_event",
        "host_execution_event_evidence_ref",
    ):
        _tenant_actor_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.reject_host_execution_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_HOST_EXECUTION_EVENT';
        END
        $$
        """
    )
    for table in (
        "host_execution_event",
        "host_execution_event_evidence_ref",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON milai.{table}
            FOR EACH ROW EXECUTE FUNCTION milai.reject_host_execution_event_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION milai.append_host_execution_event(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_principal_binding_digest text,
          p_project_id text,
          p_task_ref text,
          p_event_family text,
          p_event_type text,
          p_observed_at timestamptz,
          p_bounded_payload jsonb,
          p_evidence_refs uuid[],
          p_operation_id text,
          p_request_fingerprint text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, milai
        AS $$
        DECLARE
          v_idempotency milai.idempotency_record%ROWTYPE;
          v_event_id uuid := gen_random_uuid();
          v_position bigint;
          v_response jsonb;
          v_evidence_id uuid;
          v_ordinal integer := 0;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_principal_binding_digest !~ '^[0-9a-f]{64}$'
             OR length(btrim(p_project_id)) NOT BETWEEN 1 AND 512
             OR length(btrim(p_task_ref)) NOT BETWEEN 1 AND 1024
             OR p_event_family !~ '^[A-Z][A-Z0-9_.-]{0,63}$'
             OR p_event_type !~ '^[A-Z][A-Z0-9_.-]{0,95}$'
             OR p_observed_at IS NULL
             OR jsonb_typeof(p_bounded_payload) <> 'object'
             OR octet_length(p_bounded_payload::text) > 16384
             OR COALESCE(cardinality(p_evidence_refs), 0) > 64
             OR COALESCE(cardinality(p_evidence_refs), 0) <>
                COALESCE((SELECT count(DISTINCT item) FROM unnest(p_evidence_refs) item), 0)
             OR length(p_operation_id) NOT BETWEEN 1 AND 128
             OR p_request_fingerprint !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_HOST_EXECUTION_EVENT';
          END IF;
          IF p_event_family = 'DIALOGUE' AND p_event_type = 'MESSAGE'
             AND (
               COALESCE(cardinality(p_evidence_refs), 0) = 0
               OR p_bounded_payload - 'role' <> '{}'::jsonb
               OR COALESCE(p_bounded_payload ->> 'role', '') NOT IN ('USER', 'ASSISTANT')
             ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_HOST_EXECUTION_EVENT';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'HOST_EXECUTION_EVENT_APPEND', p_operation_id,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'HOST_EXECUTION_EVENT_APPEND'
            AND idempotency_key = p_operation_id
          FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          IF EXISTS (
            SELECT 1
            FROM unnest(COALESCE(p_evidence_refs, ARRAY[]::uuid[])) ref(evidence_id)
            WHERE NOT EXISTS (
              SELECT 1
              FROM milai.evidence_record evidence
              WHERE evidence.tenant_id = p_tenant_id
                AND evidence.evidence_id = ref.evidence_id
                AND evidence.revoked_at IS NULL
                AND evidence.retention_state = 'READABLE'
                AND evidence.permission_snapshot @> jsonb_build_object(
                  'readable', true,
                  'project_ids', jsonb_build_array(p_project_id)
                )
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EVIDENCE_REFERENCE_INVALID';
          END IF;

          INSERT INTO milai.host_execution_event (
            tenant_id, event_id, principal_binding_digest, project_id, task_ref,
            event_family, event_type, observed_at, bounded_payload,
            operation_id, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_event_id, p_principal_binding_digest, p_project_id,
            p_task_ref, p_event_family, p_event_type, p_observed_at,
            p_bounded_payload, p_operation_id, p_request_fingerprint, p_actor_id
          ) RETURNING position INTO v_position;

          FOREACH v_evidence_id IN ARRAY COALESCE(p_evidence_refs, ARRAY[]::uuid[])
          LOOP
            INSERT INTO milai.host_execution_event_evidence_ref (
              tenant_id, event_id, evidence_id, ordinal, created_by_actor_id
            ) VALUES (
              p_tenant_id, v_event_id, v_evidence_id, v_ordinal, p_actor_id
            );
            v_ordinal := v_ordinal + 1;
          END LOOP;

          v_response := jsonb_build_object(
            'status', 'APPENDED',
            'event_id', v_event_id,
            'position', v_position,
            'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'HOST_EXECUTION_EVENT_APPEND'
            AND idempotency_key = p_operation_id;
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'HOST_EXECUTION_EVENT_APPENDED', NULL,
            jsonb_build_object(
              'host_event_id', v_event_id,
              'position', v_position,
              'event_family', p_event_family,
              'event_type', p_event_type,
              'task_ref_sha256', encode(
                sha256(convert_to(p_task_ref, 'UTF8')), 'hex'
              ),
              'evidence_ref_count', COALESCE(cardinality(p_evidence_refs), 0)
            ), p_actor_id
          );
          RETURN v_response;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON TABLE milai.host_execution_event, "
        "milai.host_execution_event_evidence_ref "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.host_execution_event, "
        "milai.host_execution_event_evidence_ref TO milai_api"
    )
    op.execute(
        "GRANT SELECT (tenant_id, event_id, position, principal_binding_digest, "
        "project_id, task_ref, event_family, event_type, observed_at, operation_id, "
        "request_fingerprint, created_at, created_by_actor_id) "
        "ON milai.host_execution_event TO milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.host_execution_event_evidence_ref TO milai_audit"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.append_host_execution_event({APPEND_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.append_host_execution_event({APPEND_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    # This removes only the experimental C1 Event journal. Canonical, Evidence,
    # Retrieval, and Host Cognitive State remain untouched.
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.append_host_execution_event({APPEND_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"DROP FUNCTION milai.append_host_execution_event({APPEND_SIGNATURE})"
    )
    for table in (
        "host_execution_event_evidence_ref",
        "host_execution_event",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON milai.{table}")
    op.execute("DROP FUNCTION milai.reject_host_execution_event_mutation()")
    op.execute("DROP TABLE milai.host_execution_event_evidence_ref")
    op.execute("DROP TABLE milai.host_execution_event")
    op.execute(
        "DELETE FROM milai.idempotency_record "
        "WHERE operation_family = 'HOST_EXECUTION_EVENT_APPEND'"
    )
