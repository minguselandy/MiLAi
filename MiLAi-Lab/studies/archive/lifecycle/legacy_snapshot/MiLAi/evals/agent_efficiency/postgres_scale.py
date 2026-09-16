from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import statistics
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import psycopg
from alembic import command
from alembic.config import Config
from milai.adapters import DeterministicHashEmbedding
from milai.application import RetrievalService
from milai.config import load_settings
from milai.domain import RetrievalRequest
from milai.operations import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).resolve().with_name("fixtures.json")


def _alembic_config() -> Config:
    config = Config(str(ROOT / "runtime" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "runtime" / "migrations"))
    config.set_main_option("prepend_sys_path", str(ROOT / "runtime"))
    return config


def _percentile(values: Sequence[float], ratio: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def _seed_batch(
    owner_url: str,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    evidence_id: UUID,
    start: int,
    end: int,
) -> float:
    started = perf_counter()
    with psycopg.connect(owner_url) as connection, connection.transaction():
        # Isolated benchmark bulk load only. All rows below are created as one complete
        # graph, then queried through the exact API role and live Canonical Gate.
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute("SET CONSTRAINTS ALL DEFERRED")
        connection.execute(
            """
            CREATE TEMP TABLE scale_seed ON COMMIT DROP AS
            SELECT value AS ordinal,
                   gen_random_uuid() AS proposal_id,
                   gen_random_uuid() AS decision_id,
                   gen_random_uuid() AS claim_id,
                   gen_random_uuid() AS version_id,
                   gen_random_uuid() AS transition_id,
                   gen_random_uuid() AS relation_id,
                   gen_random_uuid() AS document_id
            FROM generate_series(%s::bigint, %s::bigint) AS value
            """,
            (start, end),
        )
        common = (tenant_id, actor_id)
        connection.execute(
            """
            INSERT INTO milai.operation_proposal (
              tenant_id, proposal_id, target_claim_id, operation, expected_version_id,
              proposed_patch, supporting_evidence_refs, contradicting_evidence_refs,
              scope_predicate, requested_authority, derivation_policy_id, model_id,
              template_id, derivation_snapshot, proposer_actor_id,
              canonical_commit_authorized, status, idempotency_key, request_fingerprint,
              created_by_actor_id
            )
            SELECT %s, proposal_id, NULL, 'CREATE', NULL,
                   jsonb_build_object('synthetic_scale_ordinal', ordinal), ARRAY[%s]::uuid[],
                   '{}'::uuid[], '{"project_ids":["scale"]}'::jsonb, 'INFORMATIONAL',
                   'scale-benchmark-v1', 'offline-synthetic', 'v1',
                   '{"input_snapshot_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'::jsonb,
                   %s, false, 'APPLIED', 'scale-' || ordinal,
                   repeat('a', 64), %s
            FROM scale_seed
            """,
            (tenant_id, evidence_id, actor_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO milai.claim (
              tenant_id, claim_id, subject_id, predicate, claim_type, created_by_actor_id
            )
            SELECT %s, claim_id, 'scale-subject-' || lpad(ordinal::text, 6, '0'),
                   'scale.fact', 'FACT', %s
            FROM scale_seed
            """,
            common,
        )
        connection.execute(
            """
            INSERT INTO milai.claim_version (
              tenant_id, claim_version_id, claim_id, version_number, payload,
              scope_predicate, lifecycle, epistemic_status, freshness, authority,
              confidence, derivation_policy_id, model_id, template_id,
              steward_decision_id, canonical_commit_seq, created_by_actor_id
            )
            SELECT %s, version_id, claim_id, 1,
                   jsonb_build_object(
                     'token', 'scale-token-' || lpad(ordinal::text, 6, '0'),
                     'value', 'synthetic'
                   ),
                   '{"project_ids":["scale"]}'::jsonb, 'ACTIVE', 'VERIFIED',
                   'CURRENT', 'INFORMATIONAL', 0.99, 'scale-benchmark-v1',
                   'offline-synthetic', 'v1', decision_id, ordinal, %s
            FROM scale_seed
            """,
            common,
        )
        connection.execute(
            """
            INSERT INTO milai.claim_head (
              tenant_id, claim_id, current_claim_version_id, created_by_actor_id,
              updated_at, updated_by_actor_id
            )
            SELECT %s, claim_id, version_id, %s, CURRENT_TIMESTAMP, %s
            FROM scale_seed
            """,
            (tenant_id, actor_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO milai.steward_decision (
              tenant_id, decision_id, proposal_id, decision, decision_actor_type,
              decision_actor_id, policy_version, reason_code, resulting_claim_version_id,
              canonical_commit_seq, created_by_actor_id
            )
            SELECT %s, decision_id, proposal_id, 'APPROVE', 'STEWARD', %s,
                   'scale-benchmark-v1', 'SYNTHETIC_SCALE_FIXTURE', version_id,
                   ordinal, %s
            FROM scale_seed
            """,
            (tenant_id, actor_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO milai.version_transition (
              tenant_id, transition_id, claim_id, old_claim_version_id,
              new_claim_version_id, transition_type, proposal_id, decision_id,
              canonical_commit_seq, created_by_actor_id
            )
            SELECT %s, transition_id, claim_id, NULL, version_id, 'CREATE', proposal_id,
                   decision_id, ordinal, %s
            FROM scale_seed
            """,
            common,
        )
        connection.execute(
            """
            INSERT INTO milai.grounding_relation (
              tenant_id, relation_id, claim_version_id, open_issue_id, evidence_id,
              relation_type, created_from_proposal_id, created_by_actor_id
            )
            SELECT %s, relation_id, version_id, NULL, %s, 'SUPPORTS', proposal_id, %s
            FROM scale_seed
            """,
            (tenant_id, evidence_id, actor_id),
        )
        connection.execute(
            """
            INSERT INTO milai.search_document (
              tenant_id, document_id, claim_id, claim_version_id, content_text,
              search_vector, scope_predicate, authority, canonical_commit_seq,
              source_outbox_sequence, created_by_actor_id
            )
            SELECT %s, document_id, claim_id, version_id,
                   'milai scale token ' || lpad(ordinal::text, 6, '0'),
                   to_tsvector('simple', 'milai scale token ' || lpad(ordinal::text, 6, '0')),
                   '{"project_ids":["scale"]}'::jsonb, 'INFORMATIONAL', ordinal,
                   ordinal, %s
            FROM scale_seed
            """,
            common,
        )
    with psycopg.connect(owner_url, autocommit=True) as connection:
        connection.execute("ANALYZE milai.claim")
        connection.execute("ANALYZE milai.claim_head")
        connection.execute("ANALYZE milai.claim_version")
        connection.execute("ANALYZE milai.search_document")
    return perf_counter() - started


def _run_route(
    service: RetrievalService,
    context: SessionContext,
    *,
    route: str,
    ordinal: int,
    claim_id: UUID,
) -> float:
    if route == "L0":
        request = RetrievalRequest(
            route="L0",
            claim_id=claim_id,
            requested_scope={"project_ids": ["scale"]},
            required_authority="INFORMATIONAL",
            consistency="CANONICAL_REQUIRED",
            limit=1,
        )
    else:
        request = RetrievalRequest(
            route="L1",
            query=f"token {ordinal:06d}",
            requested_scope={"project_ids": ["scale"]},
            required_authority="INFORMATIONAL",
            consistency="EVENTUAL",
            limit=3,
        )
    started = perf_counter()
    result = service.retrieve(context, request, f"scale-{route}-{uuid4()}")
    elapsed = (perf_counter() - started) * 1_000
    if result.status_code != 200 or result.body["abstained"]:
        raise RuntimeError(
            f"{route} scale query did not return a canonical-gated result"
        )
    return elapsed


def _targets(
    owner_url: str, tenant_id: UUID, size: int, samples: int
) -> list[tuple[int, UUID]]:
    ordinals = [1 + (index * 7919) % size for index in range(samples)]
    subjects = [f"scale-subject-{ordinal:06d}" for ordinal in ordinals]
    with psycopg.connect(owner_url) as connection:
        rows = connection.execute(
            """
            SELECT subject_id, claim_id FROM milai.claim
            WHERE tenant_id = %s AND subject_id = ANY(%s)
            """,
            (tenant_id, subjects),
        ).fetchall()
    by_subject = {str(row[0]): UUID(str(row[1])) for row in rows}
    return [
        (ordinal, by_subject[f"scale-subject-{ordinal:06d}"]) for ordinal in ordinals
    ]


def _measure_size(
    service: RetrievalService,
    context: SessionContext,
    owner_url: str,
    size: int,
) -> dict[str, object]:
    targets = _targets(owner_url, context.tenant_id, size, 64)
    result: dict[str, object] = {"claims": size, "routes": {}}
    for route in ("L0", "L1"):
        cold = _run_route(
            service,
            context,
            route=route,
            ordinal=targets[0][0],
            claim_id=targets[0][1],
        )
        route_result: dict[str, object] = {"cold_ms": round(cold, 3), "warm": {}}
        for workers in (1, 4, 16):
            started = perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as executor:
                values = list(
                    executor.map(
                        lambda target, _route=route: _run_route(
                            service,
                            context,
                            route=_route,
                            ordinal=target[0],
                            claim_id=target[1],
                        ),
                        targets,
                    )
                )
            wall = perf_counter() - started
            route_result["warm"][str(workers)] = {
                "samples": len(values),
                "p50_ms": round(statistics.median(values), 3),
                "p95_ms": round(_percentile(values, 0.95), 3),
                "p99_ms": round(_percentile(values, 0.99), 3),
                "throughput_qps": round(len(values) / wall, 2),
            }
        result["routes"][route] = route_result
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run isolated MiLAi PostgreSQL scale benchmark"
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime" / ".env")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    load_runtime_environment(args.env_file)
    settings = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    if owner_source is None:
        raise SystemExit("MILAI_MIGRATION_DATABASE_URL is required")
    run_id = secrets.token_hex(10)
    database_name = f"milai_smoke_scale_{run_id}"
    owner_url = _database_url(owner_source, database_name)
    api_url = _database_url(settings.database_dsn, database_name)
    steward_url = _database_url(settings.steward_database_dsn, database_name)
    report: dict[str, object] = {
        "format": "milai-postgresql-scale-benchmark-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "database": database_name,
        "schema_status": "0.1.x EXPERIMENTAL",
        "implementation_status": "CANDIDATE",
        "status": "BLOCKED",
        "machine": {
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "sizes": [],
    }
    created = False
    runtime_database: Database | None = None
    steward_database: Database | None = None
    blob_directory = tempfile.TemporaryDirectory(prefix="milai-scale-blobs-")
    try:
        _create_database(owner_source, database_name)
        created = True
        previous_migration_url = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
        os.environ["MILAI_MIGRATION_DATABASE_URL"] = owner_url
        try:
            command.upgrade(_alembic_config(), "head")
        finally:
            if previous_migration_url is None:
                os.environ.pop("MILAI_MIGRATION_DATABASE_URL", None)
            else:
                os.environ["MILAI_MIGRATION_DATABASE_URL"] = previous_migration_url
        benchmark_settings = settings.model_copy(
            update={
                "database_url": SecretStr(api_url),
                "steward_database_url": SecretStr(steward_url),
                "blob_root": Path(blob_directory.name),
                "embedding_provider": "deterministic_hash",
                "embedding_model_path": None,
                "embedding_model_id": "deterministic-hash-v1",
                "embedding_source_dimensions": 16,
                "database_pool_min_size": 1,
                "database_pool_max_size": 16,
            }
        )
        runtime_database = Database(benchmark_settings, expected_role="milai_api")
        steward_database = Database(
            benchmark_settings,
            dsn=benchmark_settings.steward_database_dsn,
            expected_role="milai_steward",
        )
        from milai.api import create_app

        app = create_app(
            benchmark_settings,
            database=runtime_database,
            steward_database=steward_database,
        )
        response = app.test_client().post(
            "/v1/evidence",
            headers={
                "Authorization": f"Bearer {settings.api_token.get_secret_value()}",
                "Idempotency-Key": "scale-shared-grounding-v1",
            },
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": "scale-benchmark://shared-grounding",
                "subject_id": "scale-benchmark",
                "observed_at": "2026-08-18T00:00:00Z",
                "content": "synthetic shared scale benchmark grounding",
                "data_classification": "SYNTHETIC",
                "permission_snapshot": {"readable": True, "scope": "local"},
                "retention_state": "READABLE",
            },
        )
        if response.status_code != 201:
            raise RuntimeError("failed to create isolated benchmark grounding Evidence")
        evidence_id = UUID(str(response.json["evidence_id"]))
        service = RetrievalService(
            RetrievalRepository(runtime_database),
            embedding=DeterministicHashEmbedding(),
        )
        context = SessionContext(settings.tenant_id, settings.local_actor_id)
        previous = 0
        for size in (1, 1_000, 10_000, 100_000):
            seed_seconds = _seed_batch(
                owner_url,
                tenant_id=settings.tenant_id,
                actor_id=settings.local_actor_id,
                evidence_id=evidence_id,
                start=previous + 1,
                end=size,
            )
            measurement = _measure_size(service, context, owner_url, size)
            measurement["seed_seconds"] = round(seed_seconds, 3)
            report["sizes"].append(measurement)
            previous = size
        ten_thousand = next(
            item for item in report["sizes"] if item["claims"] == 10_000
        )
        gates = {
            "10k_l0_p95_under_30ms": (
                ten_thousand["routes"]["L0"]["warm"]["1"]["p95_ms"] < 30
            ),
            "10k_l1_p95_under_100ms": (
                ten_thousand["routes"]["L1"]["warm"]["1"]["p95_ms"] < 100
            ),
            "100k_measured": any(item["claims"] == 100_000 for item in report["sizes"]),
        }
        report["gates"] = gates
        report["status"] = "PASS" if all(gates.values()) else "FAIL"
    except Exception as exc:
        report["failure_code"] = type(exc).__name__
        raise
    finally:
        if runtime_database is not None:
            runtime_database.close()
        if steward_database is not None:
            steward_database.close()
        blob_directory.cleanup()
        cleanup = (
            _drop_database(owner_source, database_name)
            if created
            else {"status": "NOT_CREATED"}
        )
        report["cleanup"] = cleanup
        report["finished_at"] = datetime.now(UTC).isoformat()
        if cleanup.get("status") != "PASS":
            report["status"] = "BLOCKED"
        encoded = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if args.output is not None:
            output = args.output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
        sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
