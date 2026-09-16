from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.exc import ProgrammingError

from milai.api import create_app
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.persistence import Database


def _migration_url() -> str:
    value = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    if not value:
        pytest.skip("MILAI_MIGRATION_DATABASE_URL is not configured")
    return value


def _database_url(source: str, database: str) -> str:
    parsed = urlsplit(source)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, ""))


def _required_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _set_context(
    connection: psycopg.Connection[tuple[object, ...]], tenant_id: UUID, actor_id: UUID
) -> None:
    connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(tenant_id),))
    connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(actor_id),))


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _migration_scope() -> dict[str, object]:
    return {
        "scope_kind": "CONTEXTUAL",
        "project_ids": ["milai-migration"],
        "task_domains": ["migration-regression"],
        "interaction_modes": [],
        "exclusions": [],
    }


def _ingest_candidate1_evidence(api_url: str, tenant_id: UUID, actor_id: UUID, label: str) -> UUID:
    key = f"migration-evidence-{label}-{uuid4()}"
    content = label.encode()
    content_hash = hashlib.sha256(content).hexdigest()
    with psycopg.connect(api_url) as connection:
        _set_context(connection, tenant_id, actor_id)
        row = connection.execute(
            """
            SELECT milai.tx01_ingest_evidence(
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                tenant_id,
                actor_id,
                key,
                _fingerprint(key),
                "RUNTIME_OBSERVATION",
                f"migration-test://{key}",
                "milai-migration-regression",
                datetime.now(UTC),
                content_hash,
                f"cas://sha256/{tenant_id}/{content_hash}",
                len(content),
                "text/plain",
                Jsonb({"readable": True}),
                "READABLE",
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]["evidence_id"]))


def _submit_candidate1_proposal(
    api_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    operation: str,
    patch: dict[str, object],
    supporting: list[UUID],
    *,
    target_claim_id: UUID | None = None,
    expected_version_id: UUID | None = None,
    contradicting: list[UUID] | None = None,
    policy_version: str = "candidate1-migration-policy-v1",
) -> dict[str, object]:
    key = f"migration-proposal-{operation.lower()}-{uuid4()}"
    with psycopg.connect(api_url) as connection:
        _set_context(connection, tenant_id, actor_id)
        row = connection.execute(
            """
            SELECT milai.create_operation_proposal(
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                tenant_id,
                actor_id,
                key,
                _fingerprint(key),
                target_claim_id,
                operation,
                expected_version_id,
                Jsonb(patch),
                supporting,
                contradicting or [],
                Jsonb(_migration_scope()),
                "ACTION_SAFE",
                policy_version,
                None,
                "migration-regression-template-v1",
                Jsonb({"fixture": "candidate1-populated-forward"}),
            ),
        ).fetchone()
    assert row is not None
    return row[0]


def _review_candidate1_proposal(
    steward_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    proposal_id: UUID,
    *,
    policy_version: str = "candidate1-migration-policy-v1",
    decision: str = "APPROVE",
) -> dict[str, object]:
    key = f"migration-review-{proposal_id}-{uuid4()}"
    reviewer_actor_id = UUID(int=actor_id.int ^ 1)
    with psycopg.connect(steward_url) as connection:
        _set_context(connection, tenant_id, reviewer_actor_id)
        row = connection.execute(
            """
            SELECT milai.review_operation_proposal(
              %s, %s, %s, %s, 'USER', %s, %s, %s, %s
            )
            """,
            (
                tenant_id,
                reviewer_actor_id,
                proposal_id,
                decision,
                policy_version,
                "MIGRATION_REGRESSION_REVIEW",
                key,
                _fingerprint(key),
            ),
        ).fetchone()
    assert row is not None
    return row[0]


def _candidate1_claim_patch(identity: str, *, normative: bool = False) -> dict[str, object]:
    return {
        "subject_id": identity,
        "predicate": "runtime.python.version",
        "claim_type": "FACT",
        "payload": {"value": "3.11"},
        "authority": "ACTION_SAFE",
        "confidence": 0.95,
        "lifecycle": "ACTIVE",
        "epistemic_status": "VERIFIED" if normative else "SUPPORTED",
        "freshness": "CURRENT",
    }


def _create_candidate1_claim(
    api_url: str, steward_url: str, tenant_id: UUID, actor_id: UUID, identity: str
) -> dict[str, object]:
    evidence_id = _ingest_candidate1_evidence(api_url, tenant_id, actor_id, f"{identity}-support")
    proposal = _submit_candidate1_proposal(
        api_url,
        tenant_id,
        actor_id,
        "CREATE",
        _candidate1_claim_patch(identity),
        [evidence_id],
    )
    result = _review_candidate1_proposal(
        steward_url, tenant_id, actor_id, UUID(str(proposal["proposal_id"]))
    )
    return result | {"supporting_evidence_id": evidence_id}


def _create_candidate1_conflict(
    api_url: str,
    steward_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    identity: str,
) -> dict[str, object]:
    created = _create_candidate1_claim(api_url, steward_url, tenant_id, actor_id, identity)
    claim_id = UUID(str(created["claim_id"]))
    version_id = UUID(str(created["claim_version_id"]))
    contradiction = _ingest_candidate1_evidence(
        api_url, tenant_id, actor_id, f"{identity}-contradiction"
    )
    proposal = _submit_candidate1_proposal(
        api_url,
        tenant_id,
        actor_id,
        "CONTRADICT",
        {},
        [],
        target_claim_id=claim_id,
        expected_version_id=version_id,
        contradicting=[contradiction],
    )
    conflict = _review_candidate1_proposal(
        steward_url, tenant_id, actor_id, UUID(str(proposal["proposal_id"]))
    )
    return created | {
        "open_issue_id": conflict["open_issue_id"],
        "conflict_decision_id": conflict["decision_id"],
        "conflict_proposal_id": proposal["proposal_id"],
        "contradicting_evidence_id": contradiction,
    }


def _submit_resolution(
    api_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    *,
    claim_id: UUID,
    version_id: UUID,
    issue_id: UUID,
    expected_issue_revision: int,
    evidence_id: UUID,
    normative: bool,
) -> dict[str, object]:
    patch = _candidate1_claim_patch(f"resolution-{issue_id}", normative=normative)
    patch.pop("subject_id")
    patch.pop("predicate")
    patch.pop("claim_type")
    patch.update(
        {
            "payload": {"value": "3.12"},
            "resolve_issue_id": str(issue_id),
            "expected_issue_revision": expected_issue_revision,
            "addressed_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
        }
    )
    return _submit_candidate1_proposal(
        api_url,
        tenant_id,
        actor_id,
        "SUPERSEDE",
        patch,
        [evidence_id],
        target_claim_id=claim_id,
        expected_version_id=version_id,
    )


def _create_candidate1_tx05_revoke(
    api_url: str,
    steward_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    label: str,
) -> dict[str, object]:
    state = _create_candidate1_conflict(
        api_url,
        steward_url,
        tenant_id,
        actor_id,
        label,
    )
    resolution_evidence = _ingest_candidate1_evidence(
        api_url, tenant_id, actor_id, f"{label}-approved-resolution"
    )
    resolution = _submit_resolution(
        api_url,
        tenant_id,
        actor_id,
        claim_id=UUID(str(state["claim_id"])),
        version_id=UUID(str(state["claim_version_id"])),
        issue_id=UUID(str(state["open_issue_id"])),
        expected_issue_revision=1,
        evidence_id=resolution_evidence,
        normative=False,
    )
    resolution_review = _review_candidate1_proposal(
        steward_url,
        tenant_id,
        actor_id,
        UUID(str(resolution["proposal_id"])),
    )
    revoke_key = f"candidate1-revoke-{uuid4()}"
    with psycopg.connect(steward_url) as connection:
        _set_context(connection, tenant_id, actor_id)
        row = connection.execute(
            """
            SELECT milai.tx05_revoke_evidence(
              %s, %s, %s, %s, 'REVOKE', %s, %s
            )
            """,
            (
                tenant_id,
                actor_id,
                resolution_evidence,
                "MIGRATION_TX05_REVOKE",
                revoke_key,
                _fingerprint(revoke_key),
            ),
        ).fetchone()
    assert row is not None
    return {
        **state,
        "resolution_evidence_id": resolution_evidence,
        "resolution_proposal_id": UUID(str(resolution["proposal_id"])),
        "resolution_decision_id": UUID(str(resolution_review["decision_id"])),
        "revoke_key": revoke_key,
        "revoke": row[0],
    }


TX05_TIMESTAMP_LEGS = (
    "idempotency_created_at",
    "operational_event_created_at",
    "revoke_outbox_created_at",
    "purge_outbox_created_at",
)


def _shift_candidate1_tx05_timestamp(
    connection: psycopg.Connection[tuple[object, ...]],
    tenant_id: UUID,
    revoke_key: str,
    revoke_seq: int,
    leg: str,
) -> None:
    if leg == "idempotency_created_at":
        cursor = connection.execute(
            """
            UPDATE milai.idempotency_record
            SET created_at = created_at + interval '1 second'
            WHERE tenant_id = %s
              AND operation_family = 'TX-05_EVIDENCE_REVOKE'
              AND idempotency_key = %s
            """,
            (tenant_id, revoke_key),
        )
    elif leg == "operational_event_created_at":
        cursor = connection.execute(
            """
            UPDATE milai.operational_event
            SET created_at = created_at + interval '1 second'
            WHERE tenant_id = %s AND event_type = 'EVIDENCE_REVOKED'
              AND safe_metadata ->> 'canonical_commit_seq' = %s
            """,
            (tenant_id, str(revoke_seq)),
        )
    elif leg == "revoke_outbox_created_at":
        cursor = connection.execute(
            """
            UPDATE milai.outbox_event
            SET created_at = created_at + interval '1 second'
            WHERE tenant_id = %s AND event_type = 'EVIDENCE_REVOKED'
              AND canonical_commit_seq = %s
            """,
            (tenant_id, revoke_seq),
        )
    elif leg == "purge_outbox_created_at":
        cursor = connection.execute(
            """
            UPDATE milai.outbox_event
            SET created_at = created_at + interval '1 second'
            WHERE tenant_id = %s
              AND event_type = 'PURGE_EVIDENCE_DERIVATIVES'
              AND canonical_commit_seq = %s
            """,
            (tenant_id, revoke_seq),
        )
    else:  # pragma: no cover - callers use the closed tuple above.
        raise AssertionError(f"unknown TX-05 timestamp leg: {leg}")
    assert cursor.rowcount == 1


@pytest.mark.integration
def test_migrations_reach_foundation_head() -> None:
    url = _migration_url()
    command.upgrade(Config("alembic.ini"), "head")
    with psycopg.connect(url) as connection:
        rows = dict(connection.execute("SELECT key, value FROM milai.runtime_metadata").fetchall())
    assert rows == {
        "implementation_status": "CANDIDATE",
        "schema_freeze": "NO-GO FOR SCHEMA FREEZE",
        "schema_status": "0.1.x EXPERIMENTAL",
    }


@pytest.mark.integration
def test_full_forward_migration_chain_on_empty_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_migration_roundtrip_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert revision == ("0056_host_notes",)
        with pytest.raises(
            RuntimeError, match=r"intentionally (unsupported|irreversible)"
        ):
            command.downgrade(config, "0014_query_plan_outbox_sequence")
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_formation_hydration_migration_is_reversible_and_least_privilege(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_formation_hydration_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    signature = (
        "milai.hydrate_evidence_projection_by_id("
        "uuid,uuid,uuid[],jsonb,timestamp with time zone,integer,text)"
    )
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0046_proposal_idempotency")
        with psycopg.connect(target_url) as owner:
            assert owner.execute(
                "SELECT to_regprocedure(%s)", (signature,)
            ).fetchone() == (None,)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            upgraded = owner.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regprocedure(%s) IS NOT NULL,
                       has_function_privilege('milai_api', %s, 'EXECUTE'),
                       has_function_privilege('milai_steward', %s, 'EXECUTE'),
                       NOT EXISTS (
                         SELECT 1
                         FROM pg_proc function
                         CROSS JOIN LATERAL aclexplode(
                           COALESCE(
                             function.proacl,
                             acldefault('f', function.proowner)
                           )
                         ) privilege
                         WHERE function.oid = to_regprocedure(%s)
                           AND privilege.grantee = 0
                           AND privilege.privilege_type = 'EXECUTE'
                       )
                """,
                (signature, signature, signature, signature),
            ).fetchone()
        assert upgraded == (
            "0056_host_notes",
            True,
            True,
            False,
            True,
        )

        command.downgrade(config, "0046_proposal_idempotency")
        with psycopg.connect(target_url) as owner:
            downgraded = owner.execute(
                "SELECT (SELECT version_num FROM alembic_version), "
                "to_regprocedure(%s)",
                (signature,),
            ).fetchone()
        assert downgraded == ("0046_proposal_idempotency", None)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            reupgraded = owner.execute(
                "SELECT (SELECT version_num FROM alembic_version), "
                "to_regprocedure(%s) IS NOT NULL",
                (signature,),
            ).fetchone()
        assert reupgraded == ("0056_host_notes", True)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_dg17_a6_evidence_dense_migration_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_dg17_a6_roundtrip_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            upgraded = owner.execute(
                "SELECT version_num, to_regclass('milai.evidence_dense_embedding_128') "
                "FROM alembic_version"
            ).fetchone()
        assert upgraded == (
            "0056_host_notes",
            "milai.evidence_dense_embedding_128",
        )

        command.downgrade(config, "0043_dg17_speaker")
        with psycopg.connect(target_url) as owner:
            downgraded = owner.execute(
                "SELECT version_num, to_regclass('milai.evidence_dense_embedding_128') "
                "FROM alembic_version"
            ).fetchone()
        assert downgraded == ("0043_dg17_speaker", None)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            reupgraded = owner.execute(
                "SELECT version_num, to_regclass('milai.evidence_dense_embedding_128') "
                "FROM alembic_version"
            ).fetchone()
        assert reupgraded == (
            "0056_host_notes",
            "milai.evidence_dense_embedding_128",
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_dg17_structured_speaker_migration_round_trip_preserves_unknown_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_dg17_speaker_roundtrip_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    token = f"legacytoken{uuid4().hex}"
    key = f"dg17-speaker-legacy-{uuid4()}"
    content_hash = hashlib.sha256(token.encode()).hexdigest()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0042_dg17_turn_first")
        with psycopg.connect(api_url) as api:
            _set_context(api, tenant_id, actor_id)
            receipt = api.execute(
                """
                SELECT milai.tx01_ingest_evidence(
                  %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    tenant_id,
                    actor_id,
                    key,
                    _fingerprint(key),
                    "RUNTIME_OBSERVATION",
                    f"migration-test://{key}",
                    "dg17-legacy-speaker",
                    datetime.now(UTC),
                    content_hash,
                    f"cas://sha256/{tenant_id}/{content_hash}",
                    len(token),
                    "text/plain",
                    Jsonb({"readable": True}),
                    "READABLE",
                ),
            ).fetchone()[0]
        evidence_id = UUID(str(receipt["evidence_id"]))
        outbox_id = UUID(str(receipt["outbox_id"]))
        with psycopg.connect(target_url) as owner:
            owner.execute(
                """
                INSERT INTO milai.evidence_search_document (
                  tenant_id, evidence_id, source_ref, subject_id,
                  observed_at, captured_at, lexical_text, semantic_text,
                  content_hash, permission_snapshot, retention_state,
                  projection_version, source_outbox_sequence, created_by_actor_id
                )
                SELECT evidence.tenant_id, evidence.evidence_id, evidence.source_ref,
                       evidence.subject_id, evidence.observed_at, evidence.captured_at,
                       %s, %s, evidence.content_hash, evidence.permission_snapshot,
                       evidence.retention_state, 'evidence-search-v1',
                       event.outbox_sequence, %s
                FROM milai.evidence_record evidence
                JOIN milai.outbox_event event
                  ON event.tenant_id = evidence.tenant_id AND event.outbox_id = %s
                WHERE evidence.tenant_id = %s AND evidence.evidence_id = %s
                """,
                (token, token, actor_id, outbox_id, tenant_id, evidence_id),
            )

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            upgraded = owner.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       evidence.source_speaker, evidence.speaker_source,
                       document.source_speaker, document.speaker_source
                FROM milai.evidence_record evidence
                JOIN milai.evidence_search_document document
                  ON document.tenant_id = evidence.tenant_id
                 AND document.evidence_id = evidence.evidence_id
                WHERE evidence.tenant_id = %s AND evidence.evidence_id = %s
                """,
                (tenant_id, evidence_id),
            ).fetchone()
        assert upgraded == (
            "0056_host_notes",
            None,
            "UNKNOWN",
            None,
            "UNKNOWN",
        )
        with psycopg.connect(api_url) as api:
            _set_context(api, tenant_id, actor_id)
            items = api.execute(
                """
                SELECT milai.search_evidence_projection(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    tenant_id,
                    actor_id,
                    token,
                    Jsonb({}),
                    datetime.now(UTC),
                    5,
                    "evidence-search-v1",
                ),
            ).fetchone()[0]
        assert items[0]["speaker"] == "unknown"
        assert items[0]["speaker_source"] == "UNKNOWN"

        with psycopg.connect(target_url, autocommit=True) as owner:
            with pytest.raises(psycopg.Error, match="IMMUTABLE_EVIDENCE_IDENTITY"):
                owner.execute(
                    """
                    UPDATE milai.evidence_record
                    SET source_speaker = 'assistant',
                        speaker_source = 'AUTHORITATIVE_BACKFILL'
                    WHERE tenant_id = %s AND evidence_id = %s
                    """,
                    (tenant_id, evidence_id),
                )

        command.downgrade(config, "0042_dg17_turn_first")
        with psycopg.connect(target_url) as owner:
            downgraded = owner.execute(
                """
                SELECT (SELECT version_num FROM alembic_version), count(*)
                FROM information_schema.columns
                WHERE table_schema = 'milai'
                  AND table_name IN ('evidence_record', 'evidence_search_document')
                  AND column_name IN ('source_speaker', 'speaker_source')
                """
            ).fetchone()
        assert downgraded == ("0042_dg17_turn_first", 0)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner:
            reupgraded = owner.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       source_speaker, speaker_source
                FROM milai.evidence_record
                WHERE tenant_id = %s AND evidence_id = %s
                """,
                (tenant_id, evidence_id),
            ).fetchone()
        assert reupgraded == ("0056_host_notes", None, "UNKNOWN")
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_dg13_access_trace_backfill_marks_legacy_stage_detail_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_dg13_trace_backfill_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    scope = {"project_ids": ["milai"]}
    plan = {
        "planner_version": "legacy-backfill-test-v1",
        "intent": "SEARCH",
        "entities": [],
        "time_constraint": {"as_of": "2026-08-26T00:00:00Z"},
        "scope_predicate": scope,
        "required_authority": "INFORMATIONAL",
        "require_user_confirmation": False,
        "complexity": "L1",
        "consistency_mode": "EVENTUAL",
        "minimum_outbox_sequence": None,
        "context_budget": 8000,
        "routes": ["L1"],
    }
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0028_dg11_window_projection")
        with psycopg.connect(api_url) as connection:
            _set_context(connection, tenant_id, actor_id)
            trace_id = connection.execute(
                """
                SELECT milai.record_retrieval_trace(
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s
                )
                """,
                (
                    tenant_id,
                    actor_id,
                    "dg13-legacy-trace",
                    "L1",
                    "EVENTUAL",
                    _fingerprint("dg13-legacy-trace"),
                    Jsonb(plan),
                    Jsonb(scope),
                    datetime(2026, 8, 26, tzinfo=UTC),
                    "INFORMATIONAL",
                    0,
                    0,
                    0,
                    Jsonb([]),
                    Jsonb([]),
                    False,
                    None,
                    True,
                    "NO_ACCEPTED_CANDIDATES",
                    17,
                    None,
                    None,
                    0,
                ),
            ).fetchone()[0]

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as owner_connection:
            revision = owner_connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
        with psycopg.connect(api_url) as connection:
            _set_context(connection, tenant_id, actor_id)
            row = connection.execute(
                """
                SELECT execution_trace, stage_metrics
                FROM milai.retrieval_trace
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (tenant_id, trace_id),
            ).fetchone()
            assert row is not None
            execution_trace, stage_metrics = row
            privileges = connection.execute(
                """
                SELECT
                  has_function_privilege(
                    'milai_api',
                    'milai.record_retrieval_trace_pre_access_trace('
                    'uuid,uuid,text,text,text,text,jsonb,jsonb,timestamptz,text,'
                    'bigint,bigint,bigint,jsonb,jsonb,boolean,text,boolean,text,'
                    'integer,bigint,text,integer)',
                    'EXECUTE'
                  ),
                  has_function_privilege(
                    'milai_api',
                    'milai.record_retrieval_trace('
                    'uuid,uuid,text,text,text,text,jsonb,jsonb,timestamptz,text,'
                    'bigint,bigint,bigint,jsonb,jsonb,boolean,text,boolean,text,'
                    'integer,bigint,text,integer,jsonb,jsonb)',
                    'EXECUTE'
                  )
                """
            ).fetchone()

        assert revision == ("0056_host_notes",)
        assert execution_trace == {
            "schema_version": "retrieval-execution-v1",
            "requested_intent": None,
            "planned_stage": "SEARCH",
            "attempted_stages": ["SEARCH", "CANONICAL_GATE"],
            "terminal_stage": "CANONICAL_GATE",
            "stop_reason": "NO_ACCEPTED_CANDIDATES",
            "fallback_reason": None,
            "result_count": 0,
            "route_trace_complete": False,
            "trace_gap_reason": "LEGACY_STAGE_DETAIL_UNAVAILABLE",
        }
        assert stage_metrics == {
            "durations_ms": {"query_total_ms": 17},
            "counts": {"query_total_ms": 1},
        }
        assert privileges == (False, True)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate1_populated_governance_state_is_reconciled_forward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_reconcile_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_conflict(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate1-populated-{uuid4()}",
        )
        claim_id = UUID(str(state["claim_id"]))
        version_id = UUID(str(state["claim_version_id"]))
        issue_id = UUID(str(state["open_issue_id"]))
        resolution_evidence = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-legacy-resolution"
        )
        legacy_proposal = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=claim_id,
            version_id=version_id,
            issue_id=issue_id,
            expected_issue_revision=1,
            evidence_id=resolution_evidence,
            normative=False,
        )
        legacy_proposal_id = UUID(str(legacy_proposal["proposal_id"]))
        with psycopg.connect(target_url) as connection:
            before = connection.execute(
                """
                SELECT issue.status, issue.revision,
                       (SELECT count(*) FROM milai.version_transition transition
                        WHERE transition.new_claim_version_id = %s),
                       (SELECT count(*) FROM milai.open_issue_transition transition
                        WHERE transition.issue_id = issue.issue_id
                          AND transition.event_type = 'ISSUE_CREATED'),
                       (SELECT count(*) FROM milai.open_issue_transition transition
                        WHERE transition.issue_id = issue.issue_id
                          AND transition.decision_id IS NULL),
                       proposal.status
                FROM milai.open_issue issue
                JOIN milai.operation_proposal proposal
                  ON proposal.tenant_id = issue.tenant_id
                 AND proposal.proposal_id = %s
                WHERE issue.tenant_id = %s AND issue.issue_id = %s
                """,
                (version_id, legacy_proposal_id, tenant_id, issue_id),
            ).fetchone()
            original_transition_id = connection.execute(
                """
                SELECT transition_id
                FROM milai.open_issue_transition
                WHERE tenant_id = %s AND issue_id = %s
                  AND event_type = 'RESOLUTION_EVIDENCE_PROPOSED'
                  AND decision_id IS NULL
                """,
                (tenant_id, issue_id),
            ).fetchone()[0]
            original_grounding = connection.execute(
                """
                SELECT relation_id, claim_version_id, open_issue_id,
                       evidence_id, relation_type, created_from_proposal_id,
                       created_at, created_by_actor_id
                FROM milai.grounding_relation
                WHERE tenant_id = %s AND open_issue_id = %s
                  AND created_from_proposal_id = %s
                  AND relation_type = 'RESOLUTION_CANDIDATE'
                """,
                (tenant_id, issue_id, legacy_proposal_id),
            ).fetchone()
        assert before == ("READY_FOR_REVIEW", 2, 0, 0, 1, "PENDING_REVIEW")
        assert original_grounding is not None
        assert original_grounding[1:6] == (
            None,
            issue_id,
            resolution_evidence,
            "RESOLUTION_CANDIDATE",
            legacy_proposal_id,
        )

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            create_history = connection.execute(
                """
                SELECT transition.transition_type,
                       transition.old_claim_version_id,
                       transition.proposal_id,
                       transition.decision_id,
                       transition.canonical_commit_seq = decision.canonical_commit_seq
                FROM milai.version_transition transition
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = transition.tenant_id
                 AND decision.decision_id = transition.decision_id
                WHERE transition.tenant_id = %s
                  AND transition.new_claim_version_id = %s
                """,
                (tenant_id, version_id),
            ).fetchone()
            issue_creation = connection.execute(
                """
                SELECT transition.from_status, transition.to_status,
                       transition.from_revision, transition.to_revision,
                       transition.proposal_id, transition.decision_id,
                       transition.canonical_commit_seq = decision.canonical_commit_seq
                FROM milai.open_issue_transition transition
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = transition.tenant_id
                 AND decision.decision_id = transition.decision_id
                WHERE transition.tenant_id = %s AND transition.issue_id = %s
                  AND transition.event_type = 'ISSUE_CREATED'
                """,
                (tenant_id, issue_id),
            ).fetchone()
            reconciliation = connection.execute(
                """
                SELECT quarantine.original_transition_id,
                       quarantine.original_decision_id,
                       quarantine.proposal_id,
                       quarantine.reconciliation_proposal_id,
                       quarantine.original_row_sha256 = encode(sha256(convert_to(
                         jsonb_build_object(
                           'tenant_id', quarantine.tenant_id,
                           'transition_id', quarantine.original_transition_id,
                           'issue_id', quarantine.issue_id,
                           'from_status', quarantine.from_status,
                           'to_status', quarantine.to_status,
                           'from_revision', quarantine.from_revision,
                           'to_revision', quarantine.to_revision,
                           'event_type', quarantine.original_event_type,
                           'proposal_id', quarantine.proposal_id,
                           'decision_id', quarantine.original_decision_id,
                           'policy_version', quarantine.original_policy_version,
                           'canonical_commit_seq',
                             quarantine.original_canonical_commit_seq,
                           'created_at', quarantine.original_created_at,
                           'created_by_actor_id',
                             quarantine.original_created_by_actor_id
                         )::text, 'UTF8')), 'hex'),
                       proposal.status, decision.decision,
                       decision.decision_actor_type, decision.policy_version,
                       decision.reason_code, issue.status, issue.revision,
                       (SELECT array_agg(transition.event_type
                                         ORDER BY transition.to_revision)
                        FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.issue_id = issue.issue_id),
                       (SELECT count(*)
                        FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.issue_id = issue.issue_id
                          AND (transition.proposal_id IS NULL
                               OR transition.decision_id IS NULL
                               OR transition.policy_version IS NULL
                               OR transition.canonical_commit_seq IS NULL)),
                       (SELECT count(*)
                        FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.transition_id =
                              quarantine.original_transition_id),
                       (SELECT count(*)
                        FROM milai.outbox_event event
                        WHERE event.tenant_id = issue.tenant_id
                          AND event.event_type =
                              'OPEN_ISSUE_LEGACY_HISTORY_RECONCILED'
                          AND event.payload ->> 'decision_id' =
                              decision.decision_id::text)
                FROM milai.legacy_issue_transition_quarantine quarantine
                JOIN milai.operation_proposal proposal
                  ON proposal.tenant_id = quarantine.tenant_id
                 AND proposal.proposal_id =
                     quarantine.reconciliation_proposal_id
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = quarantine.tenant_id
                 AND decision.decision_id =
                     quarantine.reconciliation_decision_id
                JOIN milai.open_issue issue
                  ON issue.tenant_id = quarantine.tenant_id
                 AND issue.issue_id = quarantine.issue_id
                WHERE quarantine.tenant_id = %s
                  AND quarantine.original_transition_id = %s
                """,
                (tenant_id, original_transition_id),
            ).fetchone()
            constraint_valid = connection.execute(
                """
                SELECT convalidated
                FROM pg_constraint
                WHERE conrelid = 'milai.open_issue_transition'::regclass
                  AND conname = 'ck_issue_transition_governed'
                """
            ).fetchone()
            grounding_reconciliation = connection.execute(
                """
                SELECT ledger.original_relation_id,
                       ledger.claim_version_id,
                       ledger.open_issue_id,
                       ledger.evidence_id,
                       ledger.original_relation_type,
                       ledger.created_from_proposal_id,
                       ledger.original_created_at,
                       ledger.original_created_by_actor_id,
                       ledger.original_transition_id,
                       ledger.reconciliation_decision_id,
                       ledger.original_row_sha256 = encode(sha256(convert_to(
                         jsonb_build_object(
                           'tenant_id', ledger.tenant_id,
                           'relation_id', ledger.original_relation_id,
                           'claim_version_id', ledger.claim_version_id,
                           'open_issue_id', ledger.open_issue_id,
                           'evidence_id', ledger.evidence_id,
                           'relation_type', ledger.original_relation_type,
                           'created_from_proposal_id',
                             ledger.created_from_proposal_id,
                           'created_at', ledger.original_created_at,
                           'created_by_actor_id',
                             ledger.original_created_by_actor_id
                         )::text, 'UTF8')), 'hex'),
                       ledger.migration_revision,
                       ledger.quarantine_reason,
                       (SELECT count(*)
                        FROM milai.grounding_relation relation
                        WHERE relation.tenant_id = ledger.tenant_id
                          AND relation.relation_id = ledger.original_relation_id),
                       (SELECT count(*)
                        FROM milai.grounding_relation relation
                        WHERE relation.tenant_id = ledger.tenant_id
                          AND relation.open_issue_id = ledger.open_issue_id
                          AND relation.created_from_proposal_id =
                              ledger.created_from_proposal_id
                          AND relation.relation_type = 'RESOLUTION_CANDIDATE')
                FROM milai.legacy_grounding_relation_quarantine ledger
                WHERE ledger.tenant_id = %s
                  AND ledger.original_relation_id = %s
                """,
                (tenant_id, original_grounding[0]),
            ).fetchone()
            grounding_quarantine_security = connection.execute(
                """
                SELECT class.relrowsecurity, class.relforcerowsecurity,
                       has_table_privilege(
                         'milai_api',
                         'milai.legacy_grounding_relation_quarantine',
                         'SELECT'
                       ),
                       has_table_privilege(
                         'milai_worker',
                         'milai.legacy_grounding_relation_quarantine',
                         'SELECT'
                       ),
                       has_table_privilege(
                         'milai_steward',
                         'milai.legacy_grounding_relation_quarantine',
                         'SELECT'
                       ),
                       has_table_privilege(
                         'milai_audit',
                         'milai.legacy_grounding_relation_quarantine',
                         'SELECT'
                       ),
                       EXISTS (
                         SELECT 1 FROM pg_trigger trigger
                         WHERE trigger.tgrelid = class.oid
                           AND trigger.tgname =
                               'trg_legacy_grounding_relation_quarantine_append_only'
                           AND trigger.tgenabled = 'O'
                       )
                FROM pg_class class
                WHERE class.oid =
                  'milai.legacy_grounding_relation_quarantine'::regclass
                """
            ).fetchone()
        assert revision == ("0056_host_notes",)
        assert create_history == (
            "CREATE",
            None,
            UUID(str(state["proposal_id"])),
            UUID(str(state["decision_id"])),
            True,
        )
        assert issue_creation == (
            None,
            "OPEN",
            0,
            1,
            UUID(str(state["conflict_proposal_id"])),
            UUID(str(state["conflict_decision_id"])),
            True,
        )
        assert reconciliation == (
            original_transition_id,
            None,
            legacy_proposal_id,
            legacy_proposal_id,
            True,
            "REJECTED",
            "REJECT",
            "POLICY",
            "af09-candidate1-reconciliation-v1",
            "LEGACY_PREDECISION_EFFECT_REJECTED",
            "OPEN",
            3,
            [
                "ISSUE_CREATED",
                "LEGACY_PREDECISION_EFFECT_QUARANTINED",
                "LEGACY_RESOLUTION_REJECTED",
            ],
            0,
            0,
            1,
        )
        assert constraint_valid == (True,)
        assert grounding_reconciliation is not None
        assert grounding_reconciliation[:8] == original_grounding
        assert grounding_reconciliation[8] == original_transition_id
        assert isinstance(grounding_reconciliation[9], UUID)
        assert grounding_reconciliation[10:] == (
            True,
            "0025_legacy_provenance_guard",
            "REJECTED_PREDECISION_RESOLUTION_GROUNDING",
            0,
            0,
        )
        assert grounding_quarantine_security == (
            True,
            True,
            False,
            False,
            True,
            True,
            True,
        )

        # The migration owner needs read access for audit and backup, but must
        # not be able to rewrite the exact candidate.1 bytes after quarantine.
        with psycopg.connect(target_url) as connection:
            _set_context(connection, tenant_id, actor_id)
            with pytest.raises(psycopg.errors.RaiseException, match="APPEND_ONLY_VIOLATION"):
                connection.execute(
                    """
                    UPDATE milai.legacy_issue_transition_quarantine
                    SET quarantine_reason = quarantine_reason
                    WHERE tenant_id = %s AND original_transition_id = %s
                    """,
                    (tenant_id, original_transition_id),
                )
            connection.rollback()
            _set_context(connection, tenant_id, actor_id)
            with pytest.raises(psycopg.errors.RaiseException, match="APPEND_ONLY_VIOLATION"):
                connection.execute(
                    """
                    UPDATE milai.legacy_grounding_relation_quarantine
                    SET quarantine_reason = quarantine_reason
                    WHERE tenant_id = %s AND original_relation_id = %s
                    """,
                    (tenant_id, original_grounding[0]),
                )

        # Exercise the real Issue and Context consumers, not only the storage
        # row: neither may expose the rejected proposal's quarantined branch.
        api_token = "migration-test-token-with-at-least-32-characters"
        settings = RuntimeSettings(
            database_url=api_url,
            steward_database_url=steward_url,
            blob_root=tmp_path / "candidate1-populated-blobs",
            tenant_id=tenant_id,
            local_actor_id=actor_id,
            api_token=api_token,
            causal_token_secret="migration-causal-secret-with-at-least-32-characters",
        )
        prepare_runtime_directories(settings)
        api_database = Database(settings)
        steward_database = Database(settings, dsn=settings.steward_database_dsn)
        try:
            app = create_app(
                settings,
                database=api_database,
                steward_database=steward_database,
            )
            app.config["TESTING"] = True
            client = app.test_client()
            headers = {"Authorization": f"Bearer {api_token}"}
            issue_response = client.get(f"/v1/open-issues/{issue_id}", headers=headers)
            assert issue_response.status_code == 200
            assert resolution_evidence not in {
                UUID(branch["evidence_id"]) for branch in issue_response.json["branches"]
            }
            assert {branch["relation_type"] for branch in issue_response.json["branches"]} == {
                "SUPPORT_BRANCH",
                "CONTRADICT_BRANCH",
            }

            query_response = client.post(
                "/v1/memory/query",
                headers=headers,
                json={
                    "route": "L0",
                    "claim_id": str(claim_id),
                    "consistency": "CANONICAL_REQUIRED",
                    "requested_scope": _migration_scope(),
                    "required_authority": "ACTION_SAFE",
                },
            )
            assert query_response.status_code == 200
            capsule_response = client.post(
                "/v1/context-capsules",
                headers=headers,
                json={
                    "retrieval_trace_id": query_response.json["retrieval_trace_id"],
                    "active_goal": "verify populated migration context",
                    "constraints": ["rejected proposal grounding must remain absent"],
                    "byte_budget": 100_000,
                },
            )
            assert capsule_response.status_code == 201
            context_issue = next(
                item
                for item in capsule_response.json["protected_sections"]["OPEN ISSUES"]
                if item["issue_id"] == str(issue_id)
            )
            assert resolution_evidence not in {
                UUID(branch["evidence_id"]) for branch in context_issue["branches"]
            }
            assert {branch["relation_type"] for branch in context_issue["branches"]} == {
                "SUPPORT_BRANCH",
                "CONTRADICT_BRANCH",
            }
        finally:
            api_database.close()
            steward_database.close()

        fresh_evidence = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-post-migration-resolution"
        )
        fresh_proposal = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=claim_id,
            version_id=version_id,
            issue_id=issue_id,
            expected_issue_revision=3,
            evidence_id=fresh_evidence,
            normative=True,
        )
        with psycopg.connect(target_url) as connection:
            noncanonical_submission = connection.execute(
                """
                SELECT status, revision,
                       (SELECT count(*) FROM milai.open_issue_transition
                        WHERE tenant_id = %s AND issue_id = %s)
                FROM milai.open_issue
                WHERE tenant_id = %s AND issue_id = %s
                """,
                (tenant_id, issue_id, tenant_id, issue_id),
            ).fetchone()
        assert noncanonical_submission == ("OPEN", 3, 3)
        approved = _review_candidate1_proposal(
            steward_url,
            tenant_id,
            actor_id,
            UUID(str(fresh_proposal["proposal_id"])),
        )
        with psycopg.connect(target_url) as connection:
            continued = connection.execute(
                """
                SELECT issue.status, issue.revision, transition.event_type,
                       transition.decision_id, decision.resulting_open_issue_id,
                       (SELECT count(*) FROM milai.outbox_event event
                        WHERE event.tenant_id = issue.tenant_id
                          AND event.payload ->> 'decision_id' =
                              decision.decision_id::text)
                FROM milai.open_issue issue
                JOIN milai.open_issue_transition transition
                  ON transition.tenant_id = issue.tenant_id
                 AND transition.issue_id = issue.issue_id
                 AND transition.to_revision = issue.revision
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = transition.tenant_id
                 AND decision.decision_id = transition.decision_id
                WHERE issue.tenant_id = %s AND issue.issue_id = %s
                """,
                (tenant_id, issue_id),
            ).fetchone()
        assert continued == (
            "RESOLVED",
            4,
            "DISCHARGE_APPROVED",
            UUID(str(approved["decision_id"])),
            issue_id,
            1,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate1_unprovable_resolution_grounding_rolls_back_whole_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_grounding_fail_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_conflict(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"ground-fail-{uuid4().hex[:8]}",
        )
        issue_id = UUID(str(state["open_issue_id"]))
        resolution_evidence = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-unprovable-grounding"
        )
        resolution = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=UUID(str(state["claim_id"])),
            version_id=UUID(str(state["claim_version_id"])),
            issue_id=issue_id,
            expected_issue_revision=1,
            evidence_id=resolution_evidence,
            normative=False,
        )
        proposal_id = UUID(str(resolution["proposal_id"]))
        with psycopg.connect(target_url) as connection:
            connection.execute(
                "DROP TRIGGER trg_grounding_relation_append_only ON milai.grounding_relation"
            )
            connection.execute(
                """
                DELETE FROM milai.grounding_relation
                WHERE tenant_id = %s AND open_issue_id = %s
                  AND created_from_proposal_id = %s
                  AND relation_type = 'RESOLUTION_CANDIDATE'
                """,
                (tenant_id, issue_id, proposal_id),
            )

        with pytest.raises(
            ProgrammingError,
            match="AF09_UNPROVABLE_LEGACY_RESOLUTION_GROUNDING",
        ):
            command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            failed_closed = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_issue_transition_quarantine'),
                       to_regclass('milai.legacy_grounding_relation_quarantine'),
                       proposal.status,
                       (SELECT count(*) FROM milai.steward_decision decision
                        WHERE decision.tenant_id = proposal.tenant_id
                          AND decision.proposal_id = proposal.proposal_id),
                       issue.status, issue.revision,
                       (SELECT count(*) FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.issue_id = issue.issue_id
                          AND transition.proposal_id = proposal.proposal_id
                          AND transition.decision_id IS NULL)
                FROM milai.operation_proposal proposal
                JOIN milai.open_issue issue
                  ON issue.tenant_id = proposal.tenant_id
                 AND issue.issue_id = %s
                WHERE proposal.tenant_id = %s AND proposal.proposal_id = %s
                """,
                (issue_id, tenant_id, proposal_id),
            ).fetchone()
        assert failed_closed == (
            "0023_erasure_sha256_repair",
            None,
            None,
            "PENDING_REVIEW",
            0,
            "READY_FOR_REVIEW",
            2,
            1,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate1_decided_reject_quarantines_only_unauthorized_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_decided_reject_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_conflict(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"decided-reject-{uuid4().hex[:8]}",
        )
        issue_id = UUID(str(state["open_issue_id"]))
        evidence_id = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-rejected-resolution"
        )
        resolution = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=UUID(str(state["claim_id"])),
            version_id=UUID(str(state["claim_version_id"])),
            issue_id=issue_id,
            expected_issue_revision=1,
            evidence_id=evidence_id,
            normative=False,
        )
        proposal_id = UUID(str(resolution["proposal_id"]))
        rejected = _review_candidate1_proposal(
            steward_url,
            tenant_id,
            actor_id,
            proposal_id,
            decision="REJECT",
        )
        decision_id = UUID(str(rejected["decision_id"]))
        with psycopg.connect(target_url) as connection:
            before = connection.execute(
                """
                SELECT issue.status, issue.revision, proposal.status,
                       decision.decision,
                       (SELECT count(*) FROM milai.grounding_relation relation
                        WHERE relation.tenant_id = issue.tenant_id
                          AND relation.open_issue_id = issue.issue_id
                          AND relation.created_from_proposal_id = proposal.proposal_id
                          AND relation.relation_type = 'RESOLUTION_CANDIDATE')
                FROM milai.open_issue issue
                JOIN milai.operation_proposal proposal
                  ON proposal.tenant_id = issue.tenant_id
                 AND proposal.proposal_id = %s
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = proposal.tenant_id
                 AND decision.proposal_id = proposal.proposal_id
                WHERE issue.tenant_id = %s AND issue.issue_id = %s
                """,
                (proposal_id, tenant_id, issue_id),
            ).fetchone()
        assert before == ("OPEN", 3, "REJECTED", "REJECT", 1)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            reconciled = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       issue.status, issue.revision,
                       (SELECT count(*) FROM milai.grounding_relation relation
                        WHERE relation.tenant_id = issue.tenant_id
                          AND relation.open_issue_id = issue.issue_id
                          AND relation.created_from_proposal_id = %s
                          AND relation.relation_type = 'RESOLUTION_CANDIDATE'),
                       (SELECT count(*)
                        FROM milai.legacy_grounding_relation_quarantine ledger
                        WHERE ledger.tenant_id = issue.tenant_id
                          AND ledger.open_issue_id = issue.issue_id
                          AND ledger.created_from_proposal_id = %s
                          AND ledger.reconciliation_decision_id = %s),
                       (SELECT count(*) FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.issue_id = issue.issue_id),
                       (SELECT count(DISTINCT transition.to_revision)
                        FROM milai.open_issue_transition transition
                        WHERE transition.tenant_id = issue.tenant_id
                          AND transition.issue_id = issue.issue_id)
                FROM milai.open_issue issue
                WHERE issue.tenant_id = %s AND issue.issue_id = %s
                """,
                (
                    proposal_id,
                    proposal_id,
                    decision_id,
                    tenant_id,
                    issue_id,
                ),
            ).fetchone()
        assert reconciled == (
            "0056_host_notes",
            "OPEN",
            3,
            0,
            1,
            3,
            3,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate3_applied_0024_grounding_is_forward_repaired_by_0025(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate3_0024_compat_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_conflict(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate3-compat-{uuid4().hex[:8]}",
        )
        issue_id = UUID(str(state["open_issue_id"]))
        evidence_id = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-candidate3-compat"
        )
        resolution = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=UUID(str(state["claim_id"])),
            version_id=UUID(str(state["claim_version_id"])),
            issue_id=issue_id,
            expected_issue_revision=1,
            evidence_id=evidence_id,
            normative=False,
        )
        proposal_id = UUID(str(resolution["proposal_id"]))
        command.upgrade(config, "0024_legacy_history_reconcile")

        # Recreate the exact structural delta of the rejected candidate.3
        # migration: its Issue quarantine exists, but its grounding ledger did
        # not, and the rejected relation remained canonical.
        with psycopg.connect(target_url) as connection:
            relation_id = connection.execute(
                """
                SELECT original_relation_id
                FROM milai.legacy_grounding_relation_quarantine
                WHERE tenant_id = %s AND open_issue_id = %s
                  AND created_from_proposal_id = %s
                """,
                (tenant_id, issue_id, proposal_id),
            ).fetchone()[0]
            connection.execute(
                "DROP TRIGGER trg_grounding_relation_append_only ON milai.grounding_relation"
            )
            connection.execute(
                """
                INSERT INTO milai.grounding_relation (
                  tenant_id, relation_id, claim_version_id, open_issue_id,
                  evidence_id, relation_type, created_from_proposal_id,
                  created_at, created_by_actor_id
                )
                SELECT tenant_id, original_relation_id, claim_version_id,
                       open_issue_id, evidence_id, original_relation_type,
                       created_from_proposal_id, original_created_at,
                       original_created_by_actor_id
                FROM milai.legacy_grounding_relation_quarantine
                WHERE tenant_id = %s AND original_relation_id = %s
                """,
                (tenant_id, relation_id),
            )
            connection.execute(
                "CREATE TRIGGER trg_grounding_relation_append_only "
                "BEFORE UPDATE OR DELETE ON milai.grounding_relation "
                "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
            )
            connection.execute("DROP TABLE milai.legacy_grounding_relation_quarantine")
            connection.execute(
                """
                DELETE FROM milai.operational_event
                WHERE tenant_id = %s
                  AND event_type = 'LEGACY_RESOLUTION_GROUNDING_QUARANTINED'
                """,
                (tenant_id,),
            )
            connection.execute(
                """
                DELETE FROM milai.outbox_event
                WHERE tenant_id = %s
                  AND event_type = 'OPEN_ISSUE_LEGACY_GROUNDING_QUARANTINED'
                """,
                (tenant_id,),
            )

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            repaired = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       (SELECT count(*) FROM milai.grounding_relation
                        WHERE tenant_id = %s AND relation_id = %s),
                       ledger.original_relation_id,
                       ledger.evidence_id,
                       ledger.created_from_proposal_id,
                       ledger.migration_revision,
                       ledger.original_row_sha256 = encode(sha256(convert_to(
                         jsonb_build_object(
                           'tenant_id', ledger.tenant_id,
                           'relation_id', ledger.original_relation_id,
                           'claim_version_id', ledger.claim_version_id,
                           'open_issue_id', ledger.open_issue_id,
                           'evidence_id', ledger.evidence_id,
                           'relation_type', ledger.original_relation_type,
                           'created_from_proposal_id',
                             ledger.created_from_proposal_id,
                           'created_at', ledger.original_created_at,
                           'created_by_actor_id',
                             ledger.original_created_by_actor_id
                         )::text, 'UTF8')), 'hex')
                FROM milai.legacy_grounding_relation_quarantine ledger
                WHERE ledger.tenant_id = %s
                  AND ledger.original_relation_id = %s
                """,
                (tenant_id, relation_id, tenant_id, relation_id),
            ).fetchone()
        assert repaired == (
            "0056_host_notes",
            0,
            relation_id,
            evidence_id,
            proposal_id,
            "0025_legacy_provenance_guard",
            True,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate3_applied_0024_missing_deletion_request_is_blocked_by_0025(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate3_0024_tx05_fail_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate3-tx05-compat-{uuid4().hex[:8]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        deletion_request_id = UUID(str(revoke["deletion_request_id"]))

        command.upgrade(config, "0024_legacy_history_reconcile")
        with psycopg.connect(target_url) as connection:
            # Candidate.3 did not contain the grounding quarantine table.  Its
            # exact 0024 bytes are preserved in the immutable submission; this
            # removes only the candidate.4 schema delta from this temporary
            # compatibility fixture.
            connection.execute("DROP TABLE milai.legacy_grounding_relation_quarantine")
            connection.execute(
                """
                DELETE FROM milai.deletion_request
                WHERE tenant_id = %s AND deletion_request_id = %s
                """,
                (tenant_id, deletion_request_id),
            )

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_LEGACY_TX05"):
            command.upgrade(config, "head")

        with psycopg.connect(target_url) as connection:
            blocked = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_grounding_relation_quarantine'),
                       (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'LEGACY_RESOLUTION_GROUNDING_QUARANTINED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'OPEN_ISSUE_LEGACY_GROUNDING_QUARANTINED')
                """,
                (tenant_id, tenant_id, tenant_id, tenant_id),
            ).fetchone()
        # Candidate.3's already-committed governance remains forensic input at
        # 0024, but 0025 cannot certify or extend it and leaves no new residue.
        assert blocked == (
            "0024_legacy_history_reconcile",
            None,
            1,
            1,
            0,
            0,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
@pytest.mark.parametrize("timestamp_leg", TX05_TIMESTAMP_LEGS)
def test_candidate3_applied_0024_timestamp_conflict_is_blocked_by_0025(
    monkeypatch: pytest.MonkeyPatch,
    timestamp_leg: str,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate3_tx05_time_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"c3t{TX05_TIMESTAMP_LEGS.index(timestamp_leg)}-{uuid4().hex[:6]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        revoke_seq = int(revoke["canonical_commit_seq"])
        revoke_key = str(state["revoke_key"])

        command.upgrade(config, "0024_legacy_history_reconcile")
        with psycopg.connect(target_url) as connection:
            # Candidate.3 did not yet contain the grounding quarantine schema.
            connection.execute("DROP TABLE milai.legacy_grounding_relation_quarantine")
            _shift_candidate1_tx05_timestamp(
                connection,
                tenant_id,
                revoke_key,
                revoke_seq,
                timestamp_leg,
            )

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_LEGACY_TX05"):
            command.upgrade(config, "0025_legacy_provenance_guard")

        with psycopg.connect(target_url) as connection:
            blocked = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_grounding_relation_quarantine'),
                       (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'
                          AND idempotency_key = %s),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'LEGACY_RESOLUTION_GROUNDING_QUARANTINED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'OPEN_ISSUE_LEGACY_GROUNDING_QUARANTINED')
                """,
                (
                    tenant_id,
                    f"tx05:{revoke_key}",
                    tenant_id,
                    tenant_id,
                    tenant_id,
                ),
            ).fetchone()
        assert blocked == (
            "0024_legacy_history_reconcile",
            None,
            1,
            1,
            0,
            0,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate4_applied_0025_valid_tx05_time_proof_advances_to_0026(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate4_tx05_time_ok_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate4-time-ok-{uuid4().hex[:8]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        revoke_seq = int(revoke["canonical_commit_seq"])
        command.upgrade(config, "0025_legacy_provenance_guard")
        with psycopg.connect(target_url) as connection:
            before = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       count(*), count(DISTINCT source_time)
                FROM (
                  SELECT deletion.requested_at AS source_time
                  FROM milai.deletion_request deletion
                  WHERE deletion.tenant_id = %s
                    AND deletion.deletion_request_id = %s
                  UNION ALL
                  SELECT evidence.revoked_at
                  FROM milai.evidence_record evidence
                  WHERE evidence.tenant_id = %s AND evidence.evidence_id = %s
                  UNION ALL
                  SELECT idempotency.created_at
                  FROM milai.idempotency_record idempotency
                  WHERE idempotency.tenant_id = %s
                    AND idempotency.operation_family = 'TX-05_EVIDENCE_REVOKE'
                    AND idempotency.idempotency_key = %s
                  UNION ALL
                  SELECT operational.created_at
                  FROM milai.operational_event operational
                  WHERE operational.tenant_id = %s
                    AND operational.event_type = 'EVIDENCE_REVOKED'
                    AND operational.safe_metadata ->> 'canonical_commit_seq' = %s
                  UNION ALL
                  SELECT event.created_at
                  FROM milai.outbox_event event
                  WHERE event.tenant_id = %s
                    AND event.event_type IN (
                      'EVIDENCE_REVOKED', 'PURGE_EVIDENCE_DERIVATIVES'
                    )
                    AND event.canonical_commit_seq = %s
                ) timestamps
                """,
                (
                    tenant_id,
                    UUID(str(revoke["deletion_request_id"])),
                    tenant_id,
                    UUID(str(state["resolution_evidence_id"])),
                    tenant_id,
                    str(state["revoke_key"]),
                    tenant_id,
                    str(revoke_seq),
                    tenant_id,
                    revoke_seq,
                ),
            ).fetchone()
        assert before == ("0025_legacy_provenance_guard", 6, 1)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            after = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert after == ("0056_host_notes",)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
@pytest.mark.parametrize("timestamp_leg", TX05_TIMESTAMP_LEGS)
def test_candidate4_applied_0025_timestamp_conflict_is_blocked_by_0026(
    monkeypatch: pytest.MonkeyPatch,
    timestamp_leg: str,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate4_tx05_time_fail_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"c4t{TX05_TIMESTAMP_LEGS.index(timestamp_leg)}-{uuid4().hex[:6]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        revoke_seq = int(revoke["canonical_commit_seq"])
        revoke_key = str(state["revoke_key"])
        command.upgrade(config, "0025_legacy_provenance_guard")
        with psycopg.connect(target_url) as connection:
            _shift_candidate1_tx05_timestamp(
                connection,
                tenant_id,
                revoke_key,
                revoke_seq,
                timestamp_leg,
            )
            before = connection.execute(
                """
                SELECT (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'
                          AND idempotency_key = %s),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type = 'LEGACY_TX05_GOVERNANCE_RECONCILED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED')
                """,
                (
                    tenant_id,
                    f"tx05:{revoke_key}",
                    tenant_id,
                    tenant_id,
                    tenant_id,
                ),
            ).fetchone()
        assert before == (1, 1, 1, 1)

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_LEGACY_TX05"):
            command.upgrade(config, "head")

        with psycopg.connect(target_url) as connection:
            blocked = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'
                          AND idempotency_key = %s),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type = 'LEGACY_TX05_GOVERNANCE_RECONCILED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED')
                """,
                (
                    tenant_id,
                    f"tx05:{revoke_key}",
                    tenant_id,
                    tenant_id,
                    tenant_id,
                ),
            ).fetchone()
        assert blocked == ("0025_legacy_provenance_guard", 1, 1, 1, 1)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_tx05_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_conflict(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate1-tx05-{uuid4()}",
        )
        claim_id = UUID(str(state["claim_id"]))
        version_id = UUID(str(state["claim_version_id"]))
        issue_id = UUID(str(state["open_issue_id"]))
        resolution_evidence = _ingest_candidate1_evidence(
            api_url, tenant_id, actor_id, f"{issue_id}-approved-resolution"
        )
        resolution = _submit_resolution(
            api_url,
            tenant_id,
            actor_id,
            claim_id=claim_id,
            version_id=version_id,
            issue_id=issue_id,
            expected_issue_revision=1,
            evidence_id=resolution_evidence,
            normative=False,
        )
        resolution_review = _review_candidate1_proposal(
            steward_url,
            tenant_id,
            actor_id,
            UUID(str(resolution["proposal_id"])),
        )
        revoke_key = f"candidate1-revoke-{uuid4()}"
        with psycopg.connect(steward_url) as connection:
            _set_context(connection, tenant_id, actor_id)
            revoke_result = connection.execute(
                """
                SELECT milai.tx05_revoke_evidence(
                  %s, %s, %s, %s, 'REVOKE', %s, %s
                )
                """,
                (
                    tenant_id,
                    actor_id,
                    resolution_evidence,
                    "MIGRATION_TX05_REVOKE",
                    revoke_key,
                    _fingerprint(revoke_key),
                ),
            ).fetchone()[0]
        revoke_seq = int(revoke_result["canonical_commit_seq"])
        with psycopg.connect(target_url) as connection:
            original_transition_id = connection.execute(
                """
                SELECT transition_id
                FROM milai.open_issue_transition
                WHERE tenant_id = %s AND issue_id = %s
                  AND event_type = 'RESOLUTION_EVIDENCE_REVOKED'
                  AND proposal_id IS NULL AND decision_id IS NULL
                """,
                (tenant_id, issue_id),
            ).fetchone()[0]
            before = connection.execute(
                """
                SELECT status, revision FROM milai.open_issue
                WHERE tenant_id = %s AND issue_id = %s
                """,
                (tenant_id, issue_id),
            ).fetchone()
        assert before == ("WAITING_EVIDENCE", 4)

        command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            repaired = connection.execute(
                """
                SELECT quarantine.original_transition_id,
                       quarantine.proposal_id,
                       proposal.operation, proposal.status,
                       proposal.idempotency_key,
                       decision.decision, decision.decision_actor_type,
                       decision.resulting_evidence_id,
                       decision.canonical_commit_seq,
                       transition.event_type, transition.from_revision,
                       transition.to_revision, transition.proposal_id,
                       transition.decision_id,
                       (SELECT count(*) FROM milai.open_issue_transition item
                        WHERE item.tenant_id = transition.tenant_id
                          AND (item.proposal_id IS NULL OR item.decision_id IS NULL
                               OR item.policy_version IS NULL
                               OR item.canonical_commit_seq IS NULL)),
                       (SELECT count(*) FROM milai.outbox_event event
                        WHERE event.tenant_id = transition.tenant_id
                          AND event.event_type =
                              'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED'
                          AND event.payload ->> 'decision_id' =
                              decision.decision_id::text)
                FROM milai.legacy_issue_transition_quarantine quarantine
                JOIN milai.operation_proposal proposal
                  ON proposal.tenant_id = quarantine.tenant_id
                 AND proposal.proposal_id =
                     quarantine.reconciliation_proposal_id
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = quarantine.tenant_id
                 AND decision.decision_id =
                     quarantine.reconciliation_decision_id
                JOIN milai.open_issue_transition transition
                  ON transition.tenant_id = quarantine.tenant_id
                 AND transition.transition_id =
                     quarantine.replacement_transition_id
                WHERE quarantine.tenant_id = %s
                  AND quarantine.original_transition_id = %s
                """,
                (tenant_id, original_transition_id),
            ).fetchone()
            issue_replay = connection.execute(
                """
                SELECT issue.status, issue.revision,
                       count(transition.transition_id),
                       count(DISTINCT transition.to_revision),
                       min(transition.from_revision), max(transition.to_revision)
                FROM milai.open_issue issue
                JOIN milai.open_issue_transition transition
                  ON transition.tenant_id = issue.tenant_id
                 AND transition.issue_id = issue.issue_id
                WHERE issue.tenant_id = %s AND issue.issue_id = %s
                GROUP BY issue.status, issue.revision
                """,
                (tenant_id, issue_id),
            ).fetchone()
            decided_resolution_reconciliation = connection.execute(
                """
                SELECT quarantine.original_decision_id,
                       quarantine.reconciliation_decision_id,
                       replacement.event_type, replacement.decision_id
                FROM milai.legacy_issue_transition_quarantine quarantine
                JOIN milai.open_issue_transition replacement
                  ON replacement.tenant_id = quarantine.tenant_id
                 AND replacement.transition_id =
                     quarantine.replacement_transition_id
                WHERE quarantine.tenant_id = %s
                  AND quarantine.issue_id = %s
                  AND quarantine.original_event_type =
                      'RESOLUTION_EVIDENCE_PROPOSED'
                """,
                (tenant_id, issue_id),
            ).fetchone()
            approved_grounding = connection.execute(
                """
                SELECT count(*),
                       bool_and(relation.evidence_id = %s),
                       bool_and(relation.created_from_proposal_id = %s),
                       bool_and(decision.decision = 'APPROVE'),
                       bool_and(decision.decision_id = %s),
                       (SELECT count(*)
                        FROM milai.legacy_grounding_relation_quarantine ledger
                        WHERE ledger.tenant_id = %s
                          AND ledger.open_issue_id = %s
                          AND ledger.created_from_proposal_id = %s)
                FROM milai.grounding_relation relation
                JOIN milai.steward_decision decision
                  ON decision.tenant_id = relation.tenant_id
                 AND decision.proposal_id = relation.created_from_proposal_id
                WHERE relation.tenant_id = %s
                  AND relation.open_issue_id = %s
                  AND relation.relation_type = 'RESOLUTION_CANDIDATE'
                  AND relation.created_from_proposal_id = %s
                """,
                (
                    resolution_evidence,
                    UUID(str(resolution["proposal_id"])),
                    UUID(str(resolution_review["decision_id"])),
                    tenant_id,
                    issue_id,
                    UUID(str(resolution["proposal_id"])),
                    tenant_id,
                    issue_id,
                    UUID(str(resolution["proposal_id"])),
                ),
            ).fetchone()
        assert repaired is not None
        assert repaired[:12] == (
            original_transition_id,
            None,
            "REVOKE_EVIDENCE",
            "APPLIED",
            f"tx05:{revoke_key}",
            "APPROVE",
            "STEWARD",
            resolution_evidence,
            revoke_seq,
            "RESOLUTION_EVIDENCE_REVOKED",
            3,
            4,
        )
        assert repaired[12] is not None
        assert repaired[13] is not None
        assert repaired[14:] == (0, 1)
        assert issue_replay == ("WAITING_EVIDENCE", 4, 4, 4, 0, 4)
        assert decided_resolution_reconciliation == (
            None,
            UUID(str(resolution_review["decision_id"])),
            "LEGACY_PREDECISION_EFFECT_QUARANTINED",
            UUID(str(resolution_review["decision_id"])),
        )
        assert approved_grounding == (1, True, True, True, True, 0)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
@pytest.mark.parametrize(
    "corruption",
    (
        "deletion_request_missing",
        "deletion_request_actor",
        "deletion_request_reason",
        "deletion_request_status",
        "idempotency_result",
        "evidence_revocation",
        "operational_event",
        "revoke_outbox",
        "purge_outbox",
    ),
)
def test_candidate1_legacy_tx05_corrupt_proof_leg_rolls_back_whole_migration(
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_tx05_fail_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"tx05-corrupt-{uuid4().hex[:8]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        deletion_request_id = UUID(str(revoke["deletion_request_id"]))
        evidence_id = UUID(str(state["resolution_evidence_id"]))
        revoke_seq = int(revoke["canonical_commit_seq"])
        corrupt_uuid = uuid4()

        with psycopg.connect(target_url) as connection:
            if corruption == "deletion_request_missing":
                connection.execute(
                    """
                    DELETE FROM milai.deletion_request
                    WHERE tenant_id = %s AND deletion_request_id = %s
                    """,
                    (tenant_id, deletion_request_id),
                )
            elif corruption == "deletion_request_actor":
                connection.execute(
                    """
                    UPDATE milai.deletion_request
                    SET requested_by_actor_id = %s
                    WHERE tenant_id = %s AND deletion_request_id = %s
                    """,
                    (corrupt_uuid, tenant_id, deletion_request_id),
                )
            elif corruption == "deletion_request_reason":
                connection.execute(
                    """
                    UPDATE milai.deletion_request
                    SET reason_code = 'CORRUPTED_REASON'
                    WHERE tenant_id = %s AND deletion_request_id = %s
                    """,
                    (tenant_id, deletion_request_id),
                )
            elif corruption == "deletion_request_status":
                connection.execute(
                    """
                    ALTER TABLE milai.deletion_request
                    DROP CONSTRAINT ck_deletion_canonical_block
                    """
                )
                connection.execute(
                    """
                    UPDATE milai.deletion_request
                    SET canonical_block_status = 'CORRUPTED'
                    WHERE tenant_id = %s AND deletion_request_id = %s
                    """,
                    (tenant_id, deletion_request_id),
                )
            elif corruption == "idempotency_result":
                connection.execute(
                    """
                    UPDATE milai.idempotency_record
                    SET response_payload = jsonb_set(
                      response_payload, '{deletion_request_id}', to_jsonb(%s::text)
                    )
                    WHERE tenant_id = %s
                      AND operation_family = 'TX-05_EVIDENCE_REVOKE'
                      AND idempotency_key = %s
                    """,
                    (str(corrupt_uuid), tenant_id, state["revoke_key"]),
                )
            elif corruption == "evidence_revocation":
                connection.execute(
                    """
                    UPDATE milai.evidence_record
                    SET revocation_reason = 'CORRUPTED_REASON'
                    WHERE tenant_id = %s AND evidence_id = %s
                    """,
                    (tenant_id, evidence_id),
                )
            elif corruption == "operational_event":
                connection.execute(
                    """
                    UPDATE milai.operational_event
                    SET safe_metadata = jsonb_set(
                      safe_metadata, '{deletion_request_id}', to_jsonb(%s::text)
                    )
                    WHERE tenant_id = %s AND event_type = 'EVIDENCE_REVOKED'
                      AND safe_metadata ->> 'canonical_commit_seq' = %s
                    """,
                    (str(corrupt_uuid), tenant_id, str(revoke_seq)),
                )
            elif corruption == "revoke_outbox":
                connection.execute(
                    """
                    UPDATE milai.outbox_event
                    SET payload = jsonb_set(
                      payload, '{deletion_request_id}', to_jsonb(%s::text)
                    )
                    WHERE tenant_id = %s AND event_type = 'EVIDENCE_REVOKED'
                      AND canonical_commit_seq = %s
                    """,
                    (str(corrupt_uuid), tenant_id, revoke_seq),
                )
            elif corruption == "purge_outbox":
                connection.execute(
                    """
                    UPDATE milai.outbox_event
                    SET payload = jsonb_set(payload, '{blob_id}', to_jsonb(%s::text))
                    WHERE tenant_id = %s
                      AND event_type = 'PURGE_EVIDENCE_DERIVATIVES'
                      AND canonical_commit_seq = %s
                    """,
                    (str(corrupt_uuid), tenant_id, revoke_seq),
                )
            else:  # pragma: no cover - parametrization is closed above.
                raise AssertionError(f"unknown corruption leg: {corruption}")

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_LEGACY_TX05"):
            command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            failed_closed = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_issue_transition_quarantine'),
                       to_regclass('milai.legacy_grounding_relation_quarantine'),
                       (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'
                          AND idempotency_key = %s),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.open_issue_transition
                        WHERE tenant_id = %s AND canonical_commit_seq = %s
                          AND proposal_id IS NOT NULL),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type = 'LEGACY_TX05_GOVERNANCE_RECONCILED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED'),
                       (SELECT count(*) FROM milai.open_issue_transition
                        WHERE tenant_id = %s AND canonical_commit_seq = %s
                          AND proposal_id IS NULL AND decision_id IS NULL)
                """,
                (
                    tenant_id,
                    f"tx05:{state['revoke_key']}",
                    tenant_id,
                    tenant_id,
                    revoke_seq,
                    tenant_id,
                    tenant_id,
                    tenant_id,
                    revoke_seq,
                ),
            ).fetchone()
        assert failed_closed == (
            "0023_erasure_sha256_repair",
            None,
            None,
            0,
            0,
            0,
            0,
            0,
            1,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


def _assert_candidate1_tx05_timestamp_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    timestamp_leg: str,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_tx05_time_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        state = _create_candidate1_tx05_revoke(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"tx05-time-{timestamp_leg}-{uuid4().hex[:8]}",
        )
        revoke = state["revoke"]
        assert isinstance(revoke, dict)
        revoke_seq = int(revoke["canonical_commit_seq"])
        revoke_key = str(state["revoke_key"])
        with psycopg.connect(target_url) as connection:
            _shift_candidate1_tx05_timestamp(
                connection,
                tenant_id,
                revoke_key,
                revoke_seq,
                timestamp_leg,
            )

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_LEGACY_TX05"):
            command.upgrade(config, "head")

        with psycopg.connect(target_url) as connection:
            failed_closed = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_issue_transition_quarantine'),
                       to_regclass('milai.legacy_grounding_relation_quarantine'),
                       (SELECT count(*) FROM milai.operation_proposal
                        WHERE tenant_id = %s AND operation = 'REVOKE_EVIDENCE'
                          AND idempotency_key = %s),
                       (SELECT count(*)
                        FROM milai.steward_decision decision
                        JOIN milai.operation_proposal proposal
                          ON proposal.tenant_id = decision.tenant_id
                         AND proposal.proposal_id = decision.proposal_id
                        WHERE proposal.tenant_id = %s
                          AND proposal.operation = 'REVOKE_EVIDENCE'),
                       (SELECT count(*) FROM milai.operational_event
                        WHERE tenant_id = %s
                          AND event_type = 'LEGACY_TX05_GOVERNANCE_RECONCILED'),
                       (SELECT count(*) FROM milai.outbox_event
                        WHERE tenant_id = %s
                          AND event_type =
                              'EVIDENCE_REVOCATION_GOVERNANCE_RECONCILED')
                """,
                (
                    tenant_id,
                    f"tx05:{revoke_key}",
                    tenant_id,
                    tenant_id,
                    tenant_id,
                ),
            ).fetchone()
        assert failed_closed == (
            "0023_erasure_sha256_repair",
            None,
            None,
            0,
            0,
            0,
            0,
        )
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_candidate1_tx05_idempotency_timestamp_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_candidate1_tx05_timestamp_conflict_rolls_back(monkeypatch, "idempotency_created_at")


@pytest.mark.integration
def test_candidate1_tx05_operational_event_timestamp_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_candidate1_tx05_timestamp_conflict_rolls_back(
        monkeypatch, "operational_event_created_at"
    )


@pytest.mark.integration
def test_candidate1_tx05_revoke_outbox_timestamp_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_candidate1_tx05_timestamp_conflict_rolls_back(monkeypatch, "revoke_outbox_created_at")


@pytest.mark.integration
def test_candidate1_tx05_purge_outbox_timestamp_conflict_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_candidate1_tx05_timestamp_conflict_rolls_back(monkeypatch, "purge_outbox_created_at")


@pytest.mark.integration
def test_candidate1_unprovable_creation_history_fails_upgrade_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    api_source = _required_url("MILAI_TEST_API_DATABASE_URL")
    steward_source = _required_url("MILAI_TEST_STEWARD_DATABASE_URL")
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_candidate1_fail_closed_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    api_url = _database_url(api_source, database_name)
    steward_url = _database_url(steward_source, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0014_query_plan_outbox_sequence")
        created = _create_candidate1_claim(
            api_url,
            steward_url,
            tenant_id,
            actor_id,
            f"candidate1-unprovable-{uuid4()}",
        )
        with psycopg.connect(target_url) as connection:
            connection.execute(
                "DROP TRIGGER trg_steward_decision_append_only ON milai.steward_decision"
            )
            connection.execute(
                """
                UPDATE milai.steward_decision
                SET resulting_claim_version_id = NULL
                WHERE tenant_id = %s AND decision_id = %s
                """,
                (tenant_id, UUID(str(created["decision_id"]))),
            )
            connection.execute(
                "CREATE TRIGGER trg_steward_decision_append_only "
                "BEFORE UPDATE OR DELETE ON milai.steward_decision "
                "FOR EACH ROW EXECUTE FUNCTION milai.reject_append_only_mutation()"
            )

        with pytest.raises(ProgrammingError, match="AF09_UNPROVABLE_V1_CREATION_HISTORY"):
            command.upgrade(config, "head")
        with psycopg.connect(target_url) as connection:
            failed_closed = connection.execute(
                """
                SELECT (SELECT version_num FROM alembic_version),
                       to_regclass('milai.legacy_issue_transition_quarantine'),
                       (SELECT count(*) FROM milai.version_transition
                        WHERE new_claim_version_id = %s)
                """,
                (UUID(str(created["claim_version_id"])),),
            ).fetchone()
        assert failed_closed == ("0023_erasure_sha256_repair", None, 0)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_query_plan_sequence_key_migrates_without_losing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_url = _migration_url()
    admin_url = _database_url(owner_url, "postgres")
    database_name = f"milai_query_plan_migration_{uuid4().hex[:12]}"
    target_url = _database_url(owner_url, database_name)
    tenant_id = uuid4()
    actor_id = uuid4()
    trace_id = uuid4()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", target_url)
        config = Config("alembic.ini")
        command.upgrade(config, "0013_live_confirmation_gate")
        old_plan = {
            "planner_version": "lean-query-plan-v1",
            "intent": "EXACT_CURRENT",
            "entities": [],
            "time_constraint": {},
            "scope_predicate": {},
            "required_authority": "INFORMATIONAL",
            "require_user_confirmation": False,
            "complexity": "L0",
            "consistency_mode": "READ_YOUR_WRITES",
            "minimum_commit_seq": 17,
            "context_budget": 8000,
            "routes": ["L0"],
        }
        with psycopg.connect(target_url) as connection:
            connection.execute(
                """
                INSERT INTO milai.retrieval_trace (
                  tenant_id, trace_id, request_id, route, consistency,
                  query_fingerprint, query_plan, requested_scope, as_of,
                  required_authority, canonical_snapshot_outbox_sequence,
                  fts_watermark, vector_watermark, accepted_candidates,
                  rejected_candidates, fallback_used, fallback_reason,
                  abstained, abstention_reason, duration_ms, created_by_actor_id
                ) VALUES (
                  %s, %s, 'migration-test', 'L0', 'READ_YOUR_WRITES',
                  %s, %s, %s, CURRENT_TIMESTAMP, 'INFORMATIONAL',
                  17, 17, 17, %s, %s, false, NULL, true, 'NO_CANDIDATE', 0, %s
                )
                """,
                (
                    tenant_id,
                    trace_id,
                    "0" * 64,
                    Jsonb(old_plan),
                    Jsonb({}),
                    Jsonb([]),
                    Jsonb([]),
                    actor_id,
                ),
            )

        command.upgrade(config, "0014_query_plan_outbox_sequence")
        with psycopg.connect(target_url) as connection:
            upgraded = connection.execute(
                """
                SELECT query_plan FROM milai.retrieval_trace
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (tenant_id, trace_id),
            ).fetchone()[0]
        assert upgraded["minimum_outbox_sequence"] == 17
        assert "minimum_commit_seq" not in upgraded
        assert upgraded["planner_version"] == "lean-query-plan-v1"

        command.downgrade(config, "0013_live_confirmation_gate")
        with psycopg.connect(target_url) as connection:
            downgraded = connection.execute(
                """
                SELECT query_plan FROM milai.retrieval_trace
                WHERE tenant_id = %s AND trace_id = %s
                """,
                (tenant_id, trace_id),
            ).fetchone()[0]
        assert downgraded["minimum_commit_seq"] == 17
        assert "minimum_outbox_sequence" not in downgraded
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.mark.integration
def test_runtime_role_can_ping_real_postgresql(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = os.environ.get("MILAI_TEST_API_DATABASE_URL")
    if not url:
        pytest.skip("MILAI_TEST_API_DATABASE_URL is not configured")
    settings = RuntimeSettings(
        database_url=url,
        steward_database_url=os.environ.get(
            "MILAI_TEST_STEWARD_DATABASE_URL",
            "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
        ),
        blob_root=tmp_path / "blobs",
        tenant_id="11111111-1111-4111-8111-111111111111",
        local_actor_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        api_token="test-token-with-at-least-32-characters",
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
    )
    database = Database(settings)
    try:
        database.ping()
    finally:
        database.close()
