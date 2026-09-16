"""Independent Host notes; immutable versions and scoped operation receipts.

Schema 0.1.x EXPERIMENTAL. NO-GO FOR SCHEMA FREEZE.
"""

from alembic import op

revision = "0056_host_notes"
down_revision = "0055_working_state_ref_capacity"
branch_labels = None
depends_on = None

SIGNATURE = "uuid,uuid,text,text,text,text,text,uuid,integer,jsonb"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE milai.host_note (
          tenant_id uuid NOT NULL,
          memory_id uuid NOT NULL,
          created_by_actor_id uuid NOT NULL,
          principal_binding_digest text NOT NULL CHECK (principal_binding_digest ~ '^[0-9a-f]{64}$'),
          project_id text NOT NULL CHECK (length(project_id) BETWEEN 1 AND 512),
          authority text NOT NULL DEFAULT 'HOST_WORKING' CHECK (authority = 'HOST_WORKING'),
          current_version integer NOT NULL CHECK (current_version >= 1),
          deleted boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          PRIMARY KEY (tenant_id, memory_id)
        );
        CREATE INDEX host_note_private_page ON milai.host_note
          (tenant_id, created_by_actor_id, principal_binding_digest, project_id, created_at, memory_id);
        CREATE TABLE milai.host_note_version (
          tenant_id uuid NOT NULL,
          memory_id uuid NOT NULL,
          version integer NOT NULL CHECK (version >= 1),
          created_by_actor_id uuid NOT NULL,
          content text,
          content_digest text,
          format text NOT NULL CHECK (format IN ('text','markdown')),
          tags jsonb NOT NULL CHECK (jsonb_typeof(tags) = 'array'),
          source_refs jsonb NOT NULL CHECK (jsonb_typeof(source_refs) = 'array'),
          observed_at timestamptz,
          recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          deleted boolean NOT NULL,
          CHECK ((deleted AND content IS NULL AND content_digest IS NULL) OR
            (NOT deleted AND octet_length(content) BETWEEN 1 AND 65536
             AND content_digest ~ '^[0-9a-f]{64}$')),
          PRIMARY KEY (tenant_id, memory_id, version),
          FOREIGN KEY (tenant_id, memory_id) REFERENCES milai.host_note ON DELETE RESTRICT
        );
        ALTER TABLE milai.host_note ADD CONSTRAINT host_note_current_version_fk
          FOREIGN KEY (tenant_id, memory_id, current_version)
          REFERENCES milai.host_note_version (tenant_id, memory_id, version)
          DEFERRABLE INITIALLY DEFERRED;
        CREATE TABLE milai.host_note_evidence_ref (
          tenant_id uuid NOT NULL,
          memory_id uuid NOT NULL,
          version integer NOT NULL,
          evidence_id uuid NOT NULL,
          created_by_actor_id uuid NOT NULL,
          PRIMARY KEY (tenant_id, memory_id, version, evidence_id),
          FOREIGN KEY (tenant_id, memory_id, version) REFERENCES milai.host_note_version
            ON DELETE RESTRICT,
          FOREIGN KEY (tenant_id, evidence_id) REFERENCES milai.evidence_record ON DELETE RESTRICT
        );
    """)
    for table in ("host_note", "host_note_version", "host_note_evidence_ref"):
        op.execute(f"""
            ALTER TABLE milai.{table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE milai.{table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_actor ON milai.{table}
              USING (tenant_id = milai.current_tenant_id()
                     AND created_by_actor_id = milai.current_actor_id())
              WITH CHECK (tenant_id = milai.current_tenant_id()
                          AND created_by_actor_id = milai.current_actor_id());
            REVOKE ALL ON milai.{table} FROM PUBLIC, milai_api, milai_steward,
              milai_worker, milai_audit;
            GRANT SELECT ON milai.{table} TO milai_api;
        """)
    for table in ("host_note_version", "host_note_evidence_ref"):
        op.execute(f"""
            CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON milai.{table}
            FOR EACH ROW EXECUTE FUNCTION milai.reject_host_cognitive_history_mutation();
        """)
    op.execute("""
        CREATE FUNCTION milai.write_host_note(
          p_tenant uuid, p_actor uuid, p_principal text, p_project text,
          p_operation text, p_key text, p_fingerprint text,
          p_id uuid, p_expected integer, p_body jsonb
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, milai AS $$
        DECLARE
          v_head milai.host_note%ROWTYPE;
          v_previous milai.host_note_version%ROWTYPE;
          v_receipt milai.idempotency_record%ROWTYPE;
          v_key text;
          v_id uuid;
          v_version integer;
          v_content text;
          v_format text;
          v_tags jsonb;
          v_sources jsonb;
          v_observed timestamptz;
          v_refs uuid[];
          v_result jsonb;
        BEGIN
          IF p_tenant IS DISTINCT FROM milai.current_tenant_id()
             OR p_actor IS DISTINCT FROM milai.current_actor_id() THEN
            RAISE EXCEPTION 'NOTE_SCOPE_DENIED';
          END IF;
          IF p_principal IS NULL OR p_principal !~ '^[0-9a-f]{64}$'
             OR p_project IS NULL OR length(p_project) NOT BETWEEN 1 AND 512
             OR p_operation IS NULL OR p_operation NOT IN ('ADD','UPDATE','DELETE')
             OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128
             OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$'
             OR p_expected IS NULL OR p_expected < 0
             OR (p_operation = 'ADD' AND (p_id IS NOT NULL OR p_expected <> 0))
             OR (p_operation <> 'ADD' AND (p_id IS NULL OR p_expected < 1)) THEN
            RAISE EXCEPTION 'INVALID_NOTE';
          END IF;
          v_key := encode(sha256(convert_to(jsonb_build_array(
            p_actor, p_principal, p_project, p_key)::text, 'UTF8')), 'hex');
          INSERT INTO milai.idempotency_record
            (tenant_id, operation_family, idempotency_key, request_fingerprint, created_by_actor_id)
            VALUES (p_tenant,'HOST_NOTE',v_key,p_fingerprint,p_actor)
            ON CONFLICT DO NOTHING;
          SELECT * INTO v_receipt FROM milai.idempotency_record
            WHERE tenant_id=p_tenant AND operation_family='HOST_NOTE' AND idempotency_key=v_key
            FOR UPDATE;
          IF v_receipt.request_fingerprint <> p_fingerprint THEN
            RAISE EXCEPTION 'OPERATION_CONFLICT';
          END IF;
          IF v_receipt.response_payload IS NOT NULL THEN
            RETURN v_receipt.response_payload || '{"replayed": true}'::jsonb;
          END IF;
          IF p_operation = 'ADD' THEN
            v_id := gen_random_uuid();
            v_version := 1;
          ELSE
            SELECT * INTO v_head FROM milai.host_note
              WHERE tenant_id=p_tenant AND memory_id=p_id AND created_by_actor_id=p_actor
                AND principal_binding_digest=p_principal AND project_id=p_project FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'NOTE_NOT_FOUND'; END IF;
            IF v_head.deleted THEN RAISE EXCEPTION 'NOTE_DELETED'; END IF;
            IF v_head.current_version <> p_expected THEN RAISE EXCEPTION 'STALE_NOTE'; END IF;
            v_id := p_id;
            v_version := p_expected + 1;
            SELECT * INTO v_previous FROM milai.host_note_version
              WHERE tenant_id=p_tenant AND memory_id=p_id AND version=p_expected;
          END IF;
          v_content := CASE WHEN p_operation='DELETE' THEN NULL ELSE p_body->>'content' END;
          v_format := COALESCE(p_body->>'format',v_previous.format,'text');
          v_tags := COALESCE(NULLIF(p_body->'tags','null'::jsonb),v_previous.tags,'[]'::jsonb);
          v_sources := COALESCE(NULLIF(p_body->'source_refs','null'::jsonb),
                                v_previous.source_refs,'[]'::jsonb);
          v_observed := CASE WHEN p_body ? 'observed_at' THEN (p_body->>'observed_at')::timestamptz
                            ELSE v_previous.observed_at END;
          IF p_operation='DELETE' THEN
            v_tags := '[]'::jsonb;
            v_sources := '[]'::jsonb;
            v_observed := NULL;
          ELSIF v_content IS NULL OR octet_length(v_content) NOT BETWEEN 1 AND 65536 THEN
            RAISE EXCEPTION 'INVALID_NOTE';
          END IF;
          SELECT COALESCE(array_agg(DISTINCT (s->>'evidence_id')::uuid),ARRAY[]::uuid[])
            INTO v_refs FROM jsonb_array_elements(v_sources) s WHERE s->>'kind'='EVIDENCE';
          IF cardinality(v_refs)>1024 OR jsonb_array_length(v_sources)>1024
             OR jsonb_array_length(v_tags)>32 THEN RAISE EXCEPTION 'INVALID_NOTE'; END IF;
          -- Lock declared evidence against revocation until this transaction commits.
          PERFORM 1 FROM milai.evidence_record WHERE tenant_id=p_tenant
            AND evidence_id=ANY(v_refs) ORDER BY evidence_id FOR SHARE;
          IF EXISTS (SELECT 1 FROM unnest(v_refs) r LEFT JOIN milai.evidence_record e
            ON e.tenant_id=p_tenant AND e.evidence_id=r
            WHERE e.evidence_id IS NULL OR e.revoked_at IS NOT NULL
              OR e.retention_state<>'READABLE'
              OR e.permission_snapshot->'readable' IS DISTINCT FROM 'true'::jsonb
              OR NOT COALESCE(e.permission_snapshot->'project_ids' ? p_project,false)) THEN
            RAISE EXCEPTION 'NOTE_SOURCE_UNAVAILABLE';
          END IF;
          IF p_operation='ADD' THEN
            INSERT INTO milai.host_note (tenant_id,memory_id,created_by_actor_id,
              principal_binding_digest,project_id,current_version)
              VALUES (p_tenant,v_id,p_actor,p_principal,p_project,v_version);
          ELSE
            UPDATE milai.host_note SET current_version=v_version,deleted=(p_operation='DELETE')
              WHERE tenant_id=p_tenant AND memory_id=v_id;
          END IF;
          INSERT INTO milai.host_note_version (tenant_id,memory_id,version,created_by_actor_id,
            content,content_digest,format,tags,source_refs,observed_at,deleted)
            VALUES (p_tenant,v_id,v_version,p_actor,v_content,
              CASE WHEN v_content IS NULL THEN NULL
                   ELSE encode(sha256(convert_to(v_content,'UTF8')),'hex') END,
              v_format,v_tags,v_sources,v_observed,p_operation='DELETE');
          INSERT INTO milai.host_note_evidence_ref
            (tenant_id,memory_id,version,evidence_id,created_by_actor_id)
            SELECT p_tenant,v_id,v_version,r,p_actor FROM unnest(v_refs) r;
          v_result := jsonb_build_object('memory_id',v_id,'version',v_version,
            'operation',p_operation,'operation_id',p_key,'replayed',false);
          UPDATE milai.idempotency_record SET response_payload=v_result
            WHERE tenant_id=p_tenant AND operation_family='HOST_NOTE' AND idempotency_key=v_key;
          INSERT INTO milai.operational_event
            (tenant_id,event_id,event_type,reason_code,safe_metadata,created_by_actor_id)
            VALUES (p_tenant,gen_random_uuid(),'HOST_NOTE_COMMITTED',NULL,
                    jsonb_build_object('memory_id',v_id,'version',v_version,
                                       'operation',p_operation),p_actor);
          RETURN v_result;
        END $$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION milai.write_host_note({SIGNATURE}) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION milai.write_host_note({SIGNATURE}) TO milai_api")
    op.execute("""
        CREATE FUNCTION milai.get_host_note_operation(
          p_tenant uuid,p_actor uuid,p_principal text,p_project text,p_key text
        ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, milai AS $$
        DECLARE v_result jsonb;
        BEGIN
          IF p_tenant IS DISTINCT FROM milai.current_tenant_id()
             OR p_actor IS DISTINCT FROM milai.current_actor_id()
          THEN RAISE EXCEPTION 'NOTE_SCOPE_DENIED'; END IF;
          SELECT response_payload INTO v_result FROM milai.idempotency_record
            WHERE tenant_id=p_tenant AND created_by_actor_id=p_actor
              AND operation_family='HOST_NOTE' AND idempotency_key=encode(sha256(convert_to(
                jsonb_build_array(p_actor,p_principal,p_project,p_key)::text,'UTF8')),'hex');
          RETURN v_result;
        END $$;
        REVOKE ALL ON FUNCTION milai.get_host_note_operation(uuid,uuid,text,text,text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION milai.get_host_note_operation(uuid,uuid,text,text,text) TO milai_api;
    """)


def downgrade() -> None:
    # The owner must see all notes for the nonempty check. A rejection rolls
    # this transactional change back; API RLS remains enabled throughout.
    op.execute("ALTER TABLE milai.host_note NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM milai.host_note)
          THEN RAISE EXCEPTION 'HOST_NOTES_DOWNGRADE_REQUIRES_EMPTY_STORAGE'; END IF;
        END $$;
    """)
    op.execute(f"DROP FUNCTION milai.write_host_note({SIGNATURE})")
    op.execute("DROP FUNCTION milai.get_host_note_operation(uuid,uuid,text,text,text)")
    op.execute("ALTER TABLE milai.host_note DROP CONSTRAINT host_note_current_version_fk")
    op.execute("DROP TABLE milai.host_note_evidence_ref, milai.host_note_version, milai.host_note")
