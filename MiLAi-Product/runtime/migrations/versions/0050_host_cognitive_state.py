"""Add append-only, Host-owned cognitive working state.

Revision ID: 0050_host_cognitive_state
Revises: 0049_cleanup_terminal_counts

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from __future__ import annotations

from alembic import op

revision = "0050_host_cognitive_state"
down_revision = "0049_cleanup_terminal_counts"
branch_labels = None
depends_on = None

UPDATE_SIGNATURE = (
    "uuid,uuid,uuid,integer,text,text,text,text,jsonb,text,uuid[],text,text"
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
        CREATE TABLE milai.host_cognitive_state (
          tenant_id uuid NOT NULL,
          state_id uuid NOT NULL,
          root_state_id uuid NOT NULL,
          principal_binding_digest text NOT NULL,
          project_id text NOT NULL,
          scope_type text NOT NULL,
          scope_ref text NOT NULL,
          authority text NOT NULL DEFAULT 'HOST_WORKING',
          schema_name text NOT NULL DEFAULT 'codex-cognitive-state-v1',
          lifecycle text NOT NULL DEFAULT 'ACTIVE',
          current_version integer NOT NULL,
          current_state_version_id uuid NOT NULL,
          expires_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_host_cognitive_state PRIMARY KEY (tenant_id, state_id),
          CONSTRAINT ck_host_cognitive_state_root CHECK (root_state_id = state_id),
          CONSTRAINT ck_host_cognitive_principal_digest CHECK (
            principal_binding_digest ~ '^[0-9a-f]{64}$'
          ),
          CONSTRAINT ck_host_cognitive_project CHECK (length(btrim(project_id)) BETWEEN 1 AND 512),
          CONSTRAINT ck_host_cognitive_scope CHECK (
            scope_type IN ('SESSION', 'TASK', 'PROJECT')
            AND length(btrim(scope_ref)) BETWEEN 1 AND 1024
          ),
          CONSTRAINT ck_host_cognitive_authority CHECK (authority = 'HOST_WORKING'),
          CONSTRAINT ck_host_cognitive_schema CHECK (
            schema_name = 'codex-cognitive-state-v1'
          ),
          CONSTRAINT ck_host_cognitive_lifecycle CHECK (
            lifecycle IN ('ACTIVE', 'ARCHIVED', 'EXPIRED', 'DELETED')
          ),
          CONSTRAINT ck_host_cognitive_version CHECK (current_version >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_host_cognitive_active_binding
        ON milai.host_cognitive_state (
          tenant_id, created_by_actor_id, principal_binding_digest,
          project_id, scope_type, scope_ref
        ) WHERE lifecycle = 'ACTIVE'
        """
    )
    op.execute(
        """
        CREATE TABLE milai.host_cognitive_state_version (
          tenant_id uuid NOT NULL,
          state_version_id uuid NOT NULL,
          state_id uuid NOT NULL,
          version integer NOT NULL,
          predecessor_state_version_id uuid,
          payload_json jsonb NOT NULL,
          state_digest text NOT NULL,
          operation_id text NOT NULL,
          request_fingerprint text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_host_cognitive_state_version PRIMARY KEY (
            tenant_id, state_version_id
          ),
          CONSTRAINT uq_host_cognitive_state_version UNIQUE (
            tenant_id, state_id, version
          ),
          CONSTRAINT uq_host_cognitive_state_version_identity UNIQUE (
            tenant_id, state_id, state_version_id
          ),
          CONSTRAINT fk_host_cognitive_version_state FOREIGN KEY (tenant_id, state_id)
            REFERENCES milai.host_cognitive_state (tenant_id, state_id)
            ON DELETE RESTRICT,
          CONSTRAINT fk_host_cognitive_version_predecessor FOREIGN KEY (
            tenant_id, predecessor_state_version_id
          ) REFERENCES milai.host_cognitive_state_version (
            tenant_id, state_version_id
          ) ON DELETE RESTRICT,
          CONSTRAINT ck_host_cognitive_version_number CHECK (version >= 1),
          CONSTRAINT ck_host_cognitive_version_predecessor CHECK (
            (version = 1 AND predecessor_state_version_id IS NULL)
            OR (version > 1 AND predecessor_state_version_id IS NOT NULL)
          ),
          CONSTRAINT ck_host_cognitive_payload CHECK (jsonb_typeof(payload_json) = 'object'),
          CONSTRAINT ck_host_cognitive_state_digest CHECK (state_digest ~ '^[0-9a-f]{64}$'),
          CONSTRAINT ck_host_cognitive_operation CHECK (length(operation_id) BETWEEN 1 AND 128),
          CONSTRAINT ck_host_cognitive_request_fingerprint CHECK (
            request_fingerprint ~ '^[0-9a-f]{64}$'
          )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE milai.host_cognitive_state
        ADD CONSTRAINT fk_host_cognitive_current_version FOREIGN KEY (
          tenant_id, state_id, current_state_version_id
        ) REFERENCES milai.host_cognitive_state_version (
          tenant_id, state_id, state_version_id
        ) DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        CREATE TABLE milai.host_cognitive_state_evidence_ref (
          tenant_id uuid NOT NULL,
          state_version_id uuid NOT NULL,
          evidence_id uuid NOT NULL,
          basis_relation text NOT NULL DEFAULT 'HOST_ASSERTED',
          validated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by_actor_id uuid NOT NULL,
          CONSTRAINT pk_host_cognitive_evidence_ref PRIMARY KEY (
            tenant_id, state_version_id, evidence_id
          ),
          CONSTRAINT fk_host_cognitive_ref_version FOREIGN KEY (
            tenant_id, state_version_id
          ) REFERENCES milai.host_cognitive_state_version (
            tenant_id, state_version_id
          ) ON DELETE RESTRICT,
          CONSTRAINT fk_host_cognitive_ref_evidence FOREIGN KEY (
            tenant_id, evidence_id
          ) REFERENCES milai.evidence_record (tenant_id, evidence_id)
            ON DELETE RESTRICT,
          CONSTRAINT ck_host_cognitive_basis_relation CHECK (
            basis_relation = 'HOST_ASSERTED'
          )
        )
        """
    )

    for table in (
        "host_cognitive_state",
        "host_cognitive_state_version",
        "host_cognitive_state_evidence_ref",
    ):
        _tenant_actor_policy(table)

    op.execute(
        """
        CREATE FUNCTION milai.reject_host_cognitive_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, milai
        AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IMMUTABLE_HOST_WORKING_HISTORY';
        END
        $$
        """
    )
    for table in (
        "host_cognitive_state_version",
        "host_cognitive_state_evidence_ref",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON milai.{table}
            FOR EACH ROW EXECUTE FUNCTION milai.reject_host_cognitive_history_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION milai.update_host_cognitive_state(
          p_tenant_id uuid,
          p_actor_id uuid,
          p_state_id uuid,
          p_expected_version integer,
          p_principal_binding_digest text,
          p_project_id text,
          p_scope_type text,
          p_scope_ref text,
          p_payload jsonb,
          p_state_digest text,
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
          v_head milai.host_cognitive_state%ROWTYPE;
          v_new_state_id uuid;
          v_new_version_id uuid := gen_random_uuid();
          v_new_version integer;
          v_expires_at timestamptz;
          v_response jsonb;
          v_evidence_id uuid;
        BEGIN
          PERFORM milai.assert_session_context(p_tenant_id, p_actor_id);
          IF p_expected_version < 0
             OR p_principal_binding_digest !~ '^[0-9a-f]{64}$'
             OR length(btrim(p_project_id)) NOT BETWEEN 1 AND 512
             OR p_scope_type NOT IN ('SESSION', 'TASK', 'PROJECT')
             OR length(btrim(p_scope_ref)) NOT BETWEEN 1 AND 1024
             OR jsonb_typeof(p_payload) <> 'object'
             OR octet_length(p_payload::text) > 65536
             OR p_state_digest !~ '^[0-9a-f]{64}$'
             OR length(p_operation_id) NOT BETWEEN 1 AND 128
             OR p_request_fingerprint !~ '^[0-9a-f]{64}$'
             OR COALESCE(cardinality(p_evidence_refs), 0) > 256
             OR (p_state_id IS NULL) <> (p_expected_version = 0) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'INVALID_HOST_WORKING_STATE';
          END IF;

          INSERT INTO milai.idempotency_record (
            tenant_id, operation_family, idempotency_key, request_fingerprint,
            response_payload, created_by_actor_id
          ) VALUES (
            p_tenant_id, 'HOST_COGNITIVE_STATE_UPDATE', p_operation_id,
            p_request_fingerprint, NULL, p_actor_id
          ) ON CONFLICT DO NOTHING;
          SELECT * INTO v_idempotency
          FROM milai.idempotency_record
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'HOST_COGNITIVE_STATE_UPDATE'
            AND idempotency_key = p_operation_id
          FOR UPDATE;
          IF v_idempotency.request_fingerprint <> p_request_fingerprint THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'IDEMPOTENCY_CONFLICT';
          END IF;
          IF v_idempotency.response_payload IS NOT NULL THEN
            RETURN v_idempotency.response_payload || '{"replayed": true}'::jsonb;
          END IF;

          v_expires_at := CURRENT_TIMESTAMP + CASE p_scope_type
            WHEN 'SESSION' THEN interval '24 hours'
            WHEN 'TASK' THEN interval '30 days'
            ELSE interval '365 days'
          END;

          IF p_state_id IS NULL THEN
            UPDATE milai.host_cognitive_state
            SET lifecycle = 'EXPIRED', updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = p_tenant_id
              AND created_by_actor_id = p_actor_id
              AND principal_binding_digest = p_principal_binding_digest
              AND project_id = p_project_id
              AND scope_type = p_scope_type
              AND scope_ref = p_scope_ref
              AND lifecycle = 'ACTIVE'
              AND expires_at <= CURRENT_TIMESTAMP;
            SELECT * INTO v_head
            FROM milai.host_cognitive_state
            WHERE tenant_id = p_tenant_id
              AND created_by_actor_id = p_actor_id
              AND principal_binding_digest = p_principal_binding_digest
              AND project_id = p_project_id
              AND scope_type = p_scope_type
              AND scope_ref = p_scope_ref
              AND lifecycle = 'ACTIVE'
            FOR UPDATE;
            IF FOUND THEN
              v_response := jsonb_build_object(
                'status', 'STALE_WORKING_STATE',
                'state_id', v_head.state_id,
                'current_version', v_head.current_version,
                'replayed', false
              );
              UPDATE milai.idempotency_record SET response_payload = v_response
              WHERE tenant_id = p_tenant_id
                AND operation_family = 'HOST_COGNITIVE_STATE_UPDATE'
                AND idempotency_key = p_operation_id;
              RETURN v_response;
            END IF;
            v_new_state_id := gen_random_uuid();
            v_new_version := 1;
            INSERT INTO milai.host_cognitive_state (
              tenant_id, state_id, root_state_id, principal_binding_digest,
              project_id, scope_type, scope_ref, authority, schema_name,
              lifecycle, current_version, current_state_version_id,
              expires_at, created_by_actor_id
            ) VALUES (
              p_tenant_id, v_new_state_id, v_new_state_id,
              p_principal_binding_digest, p_project_id, p_scope_type,
              p_scope_ref, 'HOST_WORKING', 'codex-cognitive-state-v1',
              'ACTIVE', v_new_version, v_new_version_id,
              v_expires_at, p_actor_id
            );
          ELSE
            SELECT * INTO v_head
            FROM milai.host_cognitive_state
            WHERE tenant_id = p_tenant_id AND state_id = p_state_id
            FOR UPDATE;
            IF NOT FOUND THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'HOST_WORKING_STATE_NOT_FOUND';
            END IF;
            IF v_head.created_by_actor_id <> p_actor_id
               OR v_head.principal_binding_digest <> p_principal_binding_digest
               OR v_head.project_id <> p_project_id
               OR v_head.scope_type <> p_scope_type
               OR v_head.scope_ref <> p_scope_ref THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'HOST_WORKING_STATE_SCOPE_DENIED';
            END IF;
            IF v_head.lifecycle <> 'ACTIVE' OR v_head.expires_at <= CURRENT_TIMESTAMP THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'HOST_WORKING_STATE_EXPIRED';
            END IF;
            IF v_head.current_version <> p_expected_version THEN
              v_response := jsonb_build_object(
                'status', 'STALE_WORKING_STATE',
                'state_id', v_head.state_id,
                'current_version', v_head.current_version,
                'replayed', false
              );
              UPDATE milai.idempotency_record SET response_payload = v_response
              WHERE tenant_id = p_tenant_id
                AND operation_family = 'HOST_COGNITIVE_STATE_UPDATE'
                AND idempotency_key = p_operation_id;
              RETURN v_response;
            END IF;
            v_new_state_id := v_head.state_id;
            v_new_version := v_head.current_version + 1;
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
                AND (
                  p_scope_type <> 'SESSION'
                  OR evidence.source_session_id = p_scope_ref
                )
            )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'EVIDENCE_REFERENCE_INVALID';
          END IF;

          INSERT INTO milai.host_cognitive_state_version (
            tenant_id, state_version_id, state_id, version,
            predecessor_state_version_id, payload_json, state_digest,
            operation_id, request_fingerprint, created_by_actor_id
          ) VALUES (
            p_tenant_id, v_new_version_id, v_new_state_id, v_new_version,
            CASE WHEN v_new_version = 1 THEN NULL ELSE v_head.current_state_version_id END,
            p_payload, p_state_digest, p_operation_id, p_request_fingerprint,
            p_actor_id
          );
          FOREACH v_evidence_id IN ARRAY COALESCE(p_evidence_refs, ARRAY[]::uuid[])
          LOOP
            INSERT INTO milai.host_cognitive_state_evidence_ref (
              tenant_id, state_version_id, evidence_id, basis_relation,
              created_by_actor_id
            ) VALUES (
              p_tenant_id, v_new_version_id, v_evidence_id,
              'HOST_ASSERTED', p_actor_id
            );
          END LOOP;
          IF v_new_version > 1 THEN
            UPDATE milai.host_cognitive_state
            SET current_version = v_new_version,
                current_state_version_id = v_new_version_id,
                expires_at = v_expires_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = p_tenant_id
              AND state_id = v_new_state_id
              AND current_version = p_expected_version;
            IF NOT FOUND THEN
              RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'STALE_WORKING_STATE';
            END IF;
          END IF;

          v_response := jsonb_build_object(
            'status', CASE WHEN v_new_version = 1 THEN 'CREATED' ELSE 'UPDATED' END,
            'state_id', v_new_state_id,
            'state_version_id', v_new_version_id,
            'version', v_new_version,
            'expires_at', v_expires_at,
            'state_digest', p_state_digest,
            'replayed', false
          );
          UPDATE milai.idempotency_record SET response_payload = v_response
          WHERE tenant_id = p_tenant_id
            AND operation_family = 'HOST_COGNITIVE_STATE_UPDATE'
            AND idempotency_key = p_operation_id;
          INSERT INTO milai.operational_event (
            tenant_id, event_id, event_type, reason_code, safe_metadata,
            created_by_actor_id
          ) VALUES (
            p_tenant_id, gen_random_uuid(), 'HOST_WORKING_STATE_VERSION_APPENDED', NULL,
            jsonb_build_object(
              'state_id', v_new_state_id,
              'state_version_id', v_new_version_id,
              'version', v_new_version,
              'scope_type', p_scope_type,
              'scope_ref_sha256', encode(
                sha256(convert_to(p_scope_ref, 'UTF8')), 'hex'
              ),
              'state_digest', p_state_digest,
              'evidence_ref_count', COALESCE(cardinality(p_evidence_refs), 0)
            ), p_actor_id
          );
          RETURN v_response;
        END
        $$
        """
    )

    op.execute(
        "REVOKE ALL ON TABLE milai.host_cognitive_state, "
        "milai.host_cognitive_state_version, "
        "milai.host_cognitive_state_evidence_ref "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.host_cognitive_state, "
        "milai.host_cognitive_state_version, "
        "milai.host_cognitive_state_evidence_ref TO milai_api"
    )
    op.execute(
        "GRANT SELECT (tenant_id, state_id, root_state_id, principal_binding_digest, "
        "project_id, scope_type, scope_ref, authority, schema_name, lifecycle, "
        "current_version, current_state_version_id, expires_at, created_at, updated_at, "
        "created_by_actor_id) ON milai.host_cognitive_state TO milai_audit"
    )
    op.execute(
        "GRANT SELECT (tenant_id, state_version_id, state_id, version, "
        "predecessor_state_version_id, state_digest, operation_id, request_fingerprint, "
        "created_at, created_by_actor_id) ON milai.host_cognitive_state_version TO milai_audit"
    )
    op.execute(
        "GRANT SELECT ON TABLE milai.host_cognitive_state_evidence_ref TO milai_audit"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.update_host_cognitive_state({UPDATE_SIGNATURE}) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION milai.update_host_cognitive_state({UPDATE_SIGNATURE}) "
        "TO milai_api"
    )


def downgrade() -> None:
    # Schema 0.1.x remains experimental. Downgrading is deliberately explicit and
    # destructive for Host working state, while operational audit history is retained.
    op.execute(
        f"REVOKE ALL ON FUNCTION milai.update_host_cognitive_state({UPDATE_SIGNATURE}) "
        "FROM PUBLIC, milai_api, milai_steward, milai_worker, milai_audit"
    )
    op.execute(
        f"DROP FUNCTION milai.update_host_cognitive_state({UPDATE_SIGNATURE})"
    )
    for table in (
        "host_cognitive_state_version",
        "host_cognitive_state_evidence_ref",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON milai.{table}")
    op.execute("DROP FUNCTION milai.reject_host_cognitive_history_mutation()")
    op.execute(
        "ALTER TABLE milai.host_cognitive_state "
        "DROP CONSTRAINT fk_host_cognitive_current_version"
    )
    op.execute("DROP TABLE milai.host_cognitive_state_evidence_ref")
    op.execute("DROP TABLE milai.host_cognitive_state_version")
    op.execute("DROP TABLE milai.host_cognitive_state")
    op.execute(
        "DELETE FROM milai.idempotency_record "
        "WHERE operation_family = 'HOST_COGNITIVE_STATE_UPDATE'"
    )
