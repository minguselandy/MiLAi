from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

from milai.adapters import DeterministicHashEmbedding, LocalContentAddressedBlobStore
from milai.config import RuntimeSettings, SettingsError, load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations.migrations import alembic_config
from milai.persistence import Database
from milai.persistence.projection_repository import ProjectionRepository
from milai.workers.main import FoundationWorker

_RUNTIME_ROOT = Path(__file__).resolve().parents[3]
_DATABASE_PREFIX = "milai_smoke_"
_MIGRATION_ENV_LOCK = threading.RLock()


class SmokeFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _HttpResponse:
    status_code: int
    payload: object

    def get_json(self, *, silent: bool = False) -> object:
        del silent
        return self.payload


class _HttpClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> _HttpResponse:
        return self._request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> _HttpResponse:
        return self._request("POST", path, headers=headers, payload=json)

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        payload: dict[str, object] | None = None,
    ) -> _HttpResponse:
        body = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(  # noqa: S310 -- base URL is constructed from loopback settings
            f"{self._base_url}{path}", data=body, headers=request_headers, method=method
        )
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 -- loopback URL only
                raw = response.read()
                status = response.status
        except HTTPError as error:
            raw = error.read()
            status = error.code
        try:
            value: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = None
        return _HttpResponse(status, value)


def _database_url(source: str, database: str) -> str:
    parsed = urlsplit(source)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.username is None:
        raise SmokeFailure("UNSAFE_DATABASE_URL")
    return urlunsplit(parsed._replace(path=f"/{database}"))


def _headers(token: str, operation_id: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}"}
    if operation_id is not None:
        result["Idempotency-Key"] = operation_id
    return result


def _body(response: Any, expected: int | tuple[int, ...], step: str) -> dict[str, Any]:
    statuses = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise SmokeFailure(f"{step.upper()}_HTTP_{response.status_code}")
    value = response.get_json(silent=True)
    if not isinstance(value, dict):
        raise SmokeFailure(f"{step.upper()}_INVALID_JSON")
    return value


def _alembic_config() -> Config:
    return alembic_config()


@contextmanager
def _migration_url(value: str) -> Iterator[None]:
    # Alembic obtains its target from a process-global environment variable.
    # Keep only that short migration phase serialized; the expensive ingest,
    # projection, and retrieval phases may safely run against isolated DBs in
    # parallel.
    with _MIGRATION_ENV_LOCK:
        previous = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
        os.environ["MILAI_MIGRATION_DATABASE_URL"] = value
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("MILAI_MIGRATION_DATABASE_URL", None)
            else:
                os.environ["MILAI_MIGRATION_DATABASE_URL"] = previous


def _create_database(owner_url: str, database: str) -> None:
    if not database.startswith(_DATABASE_PREFIX):
        raise SmokeFailure("UNSAFE_SMOKE_DATABASE_NAME")
    with psycopg.connect(owner_url, autocommit=True, connect_timeout=5) as owner:
        role = owner.execute("SELECT current_user").fetchone()
        if role is None or role[0] != "milai_owner":
            raise SmokeFailure("SMOKE_OWNER_ROLE_MISMATCH")
        existing = owner.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if existing is not None:
            raise SmokeFailure("SMOKE_DATABASE_ALREADY_EXISTS")
        owner.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier("milai_owner")
            )
        )
    smoke_owner_url = _database_url(owner_url, database)
    with psycopg.connect(smoke_owner_url, autocommit=True, connect_timeout=5) as smoke_owner:
        smoke_owner.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        smoke_owner.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}, {}, {}").format(
                sql.Identifier(database),
                sql.Identifier("milai_api"),
                sql.Identifier("milai_steward"),
                sql.Identifier("milai_worker"),
                sql.Identifier("milai_audit"),
            )
        )


def _drop_database(owner_url: str, database: str) -> dict[str, object]:
    if not database.startswith(_DATABASE_PREFIX) or len(database) > 63:
        return {"status": "BLOCKED", "reason": "UNSAFE_SMOKE_DATABASE_NAME"}
    try:
        with psycopg.connect(owner_url, autocommit=True, connect_timeout=5) as owner:
            # psycopg_pool closes its maintenance workers asynchronously.  We never
            # terminate those sessions; cleanup waits for natural zero connections.
            deadline = time.monotonic() + 20
            row = None
            while time.monotonic() < deadline:
                row = owner.execute(
                    """
                    SELECT pg_get_userbyid(datdba),
                           (SELECT count(*) FROM pg_stat_activity
                            WHERE datname = database.datname)
                    FROM pg_database database WHERE datname = %s
                    """,
                    (database,),
                ).fetchone()
                if row is None or int(row[1]) == 0:
                    break
                time.sleep(0.1)
            if row is None:
                return {"status": "BLOCKED", "reason": "SMOKE_DATABASE_MISSING"}
            database_owner, connections = str(row[0]), int(row[1])
            if database_owner != "milai_owner":
                return {"status": "BLOCKED", "reason": "SMOKE_DATABASE_OWNER_MISMATCH"}
            if connections != 0:
                return {
                    "status": "BLOCKED",
                    "reason": "SMOKE_DATABASE_HAS_CONNECTIONS",
                    "connections": connections,
                }
            owner.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
        return {
            "status": "PASS",
            "owner": "milai_owner",
            "connections_before_drop": 0,
        }
    except (psycopg.Error, OSError):
        return {"status": "BLOCKED", "reason": "SMOKE_DATABASE_DROP_FAILED"}


def _write_report(report: dict[str, object]) -> Path:
    report_root = _RUNTIME_ROOT / "var" / "reports"
    report_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    report_root.chmod(0o700)
    run_id = str(report["run_id"])
    target = report_root / f"smoke-{run_id}.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def _smoke_settings(
    source: RuntimeSettings,
    database_urls: dict[str, str],
    blob_root: Path,
    tenant_id: UUID,
    actor_id: UUID,
    tokens: dict[str, str],
    bind_port: int,
) -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        {
            "environment": "test",
            "database_url": database_urls["api"],
            "steward_database_url": database_urls["steward"],
            "blob_root": blob_root,
            "tenant_id": tenant_id,
            "local_actor_id": actor_id,
            "api_token": tokens["legacy"],
            "causal_token_secret": tokens["causal"],
            "agent_reader_token": tokens["reader"],
            "agent_submitter_token": tokens["submitter"],
            "agent_operator_token": tokens["operator"],
            "agent_reviewer_token": tokens["reviewer"],
            "data_mode": "SYNTHETIC_ONLY",
            "blob_encryption": "AES_256_GCM",
            "blob_kek_b64": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
            "blob_key_reference": "smoke-ephemeral-kek-v1",
            "backup_key_recovery_confirmed": False,
            "embedding_provider": "deterministic_hash",
            "embedding_model_id": "deterministic-hash-v1",
            "embedding_source_dimensions": 16,
            "database_pool_min_size": 1,
            "database_pool_max_size": 2,
            "worker_event_limit": 10_000,
            "worker_retry_delay_seconds": 0,
            "max_evidence_bytes": min(source.max_evidence_bytes, 1_048_576),
            "bind_host": "127.0.0.1",
            "bind_port": bind_port,
        }
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _api_environment(
    settings: RuntimeSettings, database_urls: dict[str, str], tokens: dict[str, str]
) -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("MILAI_")
    }
    assert settings.blob_kek is not None
    environment.update(
        {
            "MILAI_ENVIRONMENT": "test",
            "MILAI_DATABASE_URL": database_urls["api"],
            "MILAI_STEWARD_DATABASE_URL": database_urls["steward"],
            "MILAI_BLOB_ROOT": str(settings.blob_root),
            "MILAI_TENANT_ID": str(settings.tenant_id),
            "MILAI_LOCAL_ACTOR_ID": str(settings.local_actor_id),
            "MILAI_API_TOKEN": tokens["legacy"],
            "MILAI_CAUSAL_TOKEN_SECRET": tokens["causal"],
            "MILAI_AGENT_READER_TOKEN": tokens["reader"],
            "MILAI_AGENT_SUBMITTER_TOKEN": tokens["submitter"],
            "MILAI_AGENT_OPERATOR_TOKEN": tokens["operator"],
            "MILAI_AGENT_REVIEWER_TOKEN": tokens["reviewer"],
            "MILAI_DATA_MODE": "SYNTHETIC_ONLY",
            "MILAI_FEATURE_PROFILE": settings.feature_profile,
            "MILAI_BUDGET_INVARIANT_CONTEXT_V0_1": str(
                settings.budget_invariant_context_v0_1
            ).lower(),
            "MILAI_PROGRESSIVE_CONTEXT_EVIDENCE_V0_1": str(
                settings.progressive_context_evidence_v0_1
            ).lower(),
            "MILAI_BLOB_ENCRYPTION": "AES_256_GCM",
            "MILAI_BLOB_KEK_B64": base64.b64encode(settings.blob_kek).decode("ascii"),
            "MILAI_BLOB_KEY_REFERENCE": settings.blob_key_reference,
            "MILAI_BACKUP_KEY_RECOVERY_CONFIRMED": "false",
            "MILAI_EMBEDDING_PROVIDER": settings.embedding_provider,
            "MILAI_EMBEDDING_MODEL_ID": settings.embedding_model_id,
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS": str(settings.embedding_source_dimensions),
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": str(settings.embedding_projection_dimensions),
            "MILAI_EMBEDDING_PREWARM": "true" if settings.embedding_prewarm else "false",
            "MILAI_EMBEDDING_MAX_CONCURRENCY": str(settings.embedding_max_concurrency),
            "MILAI_RETRIEVAL_RERANKER_PROVIDER": settings.retrieval_reranker_provider,
            "MILAI_RETRIEVAL_RERANKER_MODEL_ID": settings.retrieval_reranker_model_id,
            "MILAI_RETRIEVAL_RERANKER_REVISION": settings.retrieval_reranker_revision,
            "MILAI_RETRIEVAL_RERANKER_POOL_SIZE": str(settings.retrieval_reranker_pool_size),
            "MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED": str(
                settings.retrieval_evidence_dense_enabled
            ).lower(),
            "MILAI_RETRIEVAL_TEMPORAL_RERANKER_POOL_SIZE": str(
                settings.retrieval_temporal_reranker_pool_size
            ),
            "MILAI_DATABASE_POOL_MIN_SIZE": "1",
            "MILAI_DATABASE_POOL_MAX_SIZE": "2",
            "MILAI_BIND_HOST": settings.bind_host,
            "MILAI_BIND_PORT": str(settings.bind_port),
            "MILAI_LOG_LEVEL": "ERROR",
            "MILAI_LOG_FORMAT": "json",
        }
    )
    if settings.embedding_model_path is not None:
        environment["MILAI_EMBEDDING_MODEL_PATH"] = str(settings.embedding_model_path)
    if settings.retrieval_reranker_model_path is not None:
        assert settings.retrieval_reranker_model_sha256 is not None
        environment.update(
            {
                "MILAI_RETRIEVAL_RERANKER_MODEL_PATH": str(settings.retrieval_reranker_model_path),
                "MILAI_RETRIEVAL_RERANKER_MODEL_SHA256": (settings.retrieval_reranker_model_sha256),
            }
        )
    return environment


def _wait_api(client: _HttpClient, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure("SMOKE_API_EXITED")
        try:
            response = client.get("/health/ready")
            if response.status_code == 200:
                body = response.get_json()
                if isinstance(body, dict) and body.get("status") == "ready":
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise SmokeFailure("SMOKE_API_NOT_READY")


def _stop_api(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_chain(
    settings: RuntimeSettings,
    database_urls: dict[str, str],
    tokens: dict[str, str],
    steps: list[dict[str, object]],
) -> dict[str, object]:
    worker_database = Database(settings, dsn=database_urls["worker"], expected_role="milai_worker")
    executable = Path(sys.executable).with_name("milai-api")
    if not executable.is_file():
        raise SmokeFailure("SMOKE_API_ENTRYPOINT_MISSING")
    api_process = subprocess.Popen(  # noqa: S603 -- exact installed local entrypoint
        [str(executable)],
        cwd=_RUNTIME_ROOT,
        env=_api_environment(settings, database_urls, tokens),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = _HttpClient(f"http://{settings.bind_host}:{settings.bind_port}")
    try:
        _wait_api(client, api_process)

        live = _body(client.get("/health/live"), 200, "health_live")
        ready = _body(client.get("/health/ready"), 200, "health_ready")
        if live.get("status") != "ok" or ready.get("status") != "ready":
            raise SmokeFailure("HEALTH_NOT_READY")
        steps.append({"step": "health", "status": "PASS"})

        unique = uuid4().hex
        evidence = _body(
            client.post(
                "/v1/evidence",
                headers=_headers(tokens["submitter"], f"smoke-evidence-{unique}"),
                json={
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": f"smoke://{unique}",
                    "subject_id": f"smoke-runtime-{unique}",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "content": f"synthetic smoke runtime marker {unique} uses Python 3.12",
                    "media_type": "text/plain",
                    "permission_snapshot": {"readable": True, "scope": "synthetic-smoke"},
                    "retention_state": "READABLE",
                },
            ),
            201,
            "ingest",
        )
        evidence_id = str(evidence["evidence_id"])
        steps.append({"step": "ingest_synthetic_evidence", "status": "PASS"})

        proposal = _body(
            client.post(
                "/v1/proposals",
                headers=_headers(tokens["submitter"], f"smoke-proposal-{unique}"),
                json={
                    "operation": "CREATE",
                    "proposed_patch": {
                        "subject_id": f"smoke-runtime-{unique}",
                        "predicate": "runtime.python.version",
                        "claim_type": "RUNTIME_VERSION",
                        "payload": {"python": "3.12", "marker": unique},
                        "authority": "ACTION_SAFE",
                        "confidence": 0.99,
                    },
                    "supporting_evidence_refs": [evidence_id],
                    "scope_predicate": {"project_ids": ["milai-smoke"]},
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "isolated-smoke-v1",
                    "derivation_snapshot": {"fixture": "isolated-synthetic-smoke"},
                },
            ),
            201,
            "proposal",
        )
        proposal_id = str(proposal["proposal_id"])
        if proposal.get("commit_policy_decision") != "USER_REVIEW":
            raise SmokeFailure("PROPOSAL_NOT_PENDING_REVIEW")
        stored = _body(
            client.get(
                f"/v1/proposals/{proposal_id}",
                headers=_headers(tokens["reviewer"]),
            ),
            200,
            "proposal_get",
        )
        if stored.get("status") not in {"PENDING", "PENDING_REVIEW"}:
            raise SmokeFailure("PROPOSAL_STATUS_NOT_PENDING")
        with psycopg.connect(database_urls["owner"], connect_timeout=5) as owner:
            before_review = owner.execute(
                "SELECT count(*) FROM milai.claim WHERE tenant_id = %s",
                (settings.tenant_id,),
            ).fetchone()
        if before_review is None or int(before_review[0]) != 0:
            raise SmokeFailure("CLAIM_EXISTED_BEFORE_REVIEW")
        steps.append({"step": "pending_proposal_without_claim", "status": "PASS"})

        reviewed = _body(
            client.post(
                f"/v1/proposals/{proposal_id}/review",
                headers=_headers(tokens["reviewer"], f"smoke-review-{unique}"),
                json={
                    "decision": "APPROVE",
                    "policy_version": "isolated-test-steward-v1",
                    "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
                },
            ),
            200,
            "review",
        )
        claim_id = str(reviewed["claim_id"])
        claim_version_id = str(reviewed["claim_version_id"])
        steps.append({"step": "explicit_test_steward_review", "status": "PASS"})

        worker = FoundationWorker(
            settings,
            worker_database,
            repository=ProjectionRepository(worker_database),
            blob_store=LocalContentAddressedBlobStore(
                settings.blob_root,
                kek=settings.blob_kek,
                key_reference=settings.blob_key_reference,
                allow_plaintext_read=True,
            ),
            embedding=DeterministicHashEmbedding(),
            worker_id=f"isolated-smoke-{unique}",
        )
        if worker.run_once() <= 0:
            raise SmokeFailure("WORKER_DID_NOT_PROCESS_CREATE")
        steps.append({"step": "worker_projection", "status": "PASS"})

        recall_payload = {
            "requested_scope": {"project_ids": ["milai-smoke"]},
            "required_authority": "ACTION_SAFE",
            "consistency": "CANONICAL_REQUIRED",
        }
        l0 = _body(
            client.post(
                "/v1/memory/query",
                headers=_headers(tokens["reader"]),
                json={"route": "L0", "claim_id": claim_id, **recall_payload},
            ),
            200,
            "l0_recall",
        )
        if l0.get("abstained") is not False or not l0.get("results"):
            raise SmokeFailure("L0_RECALL_FAILED")
        l1 = _body(
            client.post(
                "/v1/memory/query",
                headers=_headers(tokens["reader"]),
                json={
                    "route": "L1",
                    "query": unique,
                    "consistency": "EVENTUAL",
                    "requested_scope": {"project_ids": ["milai-smoke"]},
                    "required_authority": "ACTION_SAFE",
                },
            ),
            200,
            "l1_recall",
        )
        if l1.get("abstained") is not False or not l1.get("results"):
            raise SmokeFailure("L1_RECALL_FAILED")
        trace_id = str(l1["retrieval_trace_id"])
        steps.append({"step": "l0_l1_recall", "status": "PASS"})

        capsule = _body(
            client.post(
                "/v1/context-capsules",
                headers=_headers(tokens["reader"]),
                json={
                    "retrieval_trace_id": trace_id,
                    "active_goal": "verify isolated synthetic smoke memory",
                    "constraints": ["canonical gate required", "synthetic data only"],
                    "byte_budget": 16_384,
                },
            ),
            201,
            "context_capsule",
        )
        if not capsule.get("capsule_id") or not capsule.get("protected_sections"):
            raise SmokeFailure("CONTEXT_CAPSULE_INCOMPLETE")
        trace = _body(
            client.get(f"/v1/retrieval-traces/{trace_id}", headers=_headers(tokens["reader"])),
            200,
            "retrieval_trace",
        )
        if not trace.get("accepted_candidates"):
            raise SmokeFailure("TRACE_MISSING_ACCEPTED_CANDIDATE")
        steps.append({"step": "context_and_trace", "status": "PASS"})

        revoke = _body(
            client.post(
                f"/v1/evidence/{evidence_id}/revoke",
                headers=_headers(tokens["operator"], f"smoke-revoke-{unique}"),
                json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
            ),
            202,
            "revoke",
        )
        if (
            revoke.get("logical_revocation_status") != "APPLIED"
            or revoke.get("canonical_block_status") != "APPLIED"
        ):
            raise SmokeFailure("REVOKE_NOT_FAIL_CLOSED")
        deletion_request_id = str(revoke["deletion_request_id"])

        stale = _body(
            client.post(
                "/v1/memory/query",
                headers=_headers(tokens["reader"]),
                json={
                    "route": "L1",
                    "query": unique,
                    "consistency": "EVENTUAL",
                    "requested_scope": {"project_ids": ["milai-smoke"]},
                    "required_authority": "ACTION_SAFE",
                },
            ),
            200,
            "stale_recall",
        )
        if stale.get("abstained") is not True or stale.get("results") != []:
            raise SmokeFailure("STALE_PROJECTION_NOT_REJECTED")
        stale_trace_id = str(stale["retrieval_trace_id"])
        stale_trace = _body(
            client.get(
                f"/v1/retrieval-traces/{stale_trace_id}",
                headers=_headers(tokens["reader"]),
            ),
            200,
            "stale_trace",
        )
        reject_reasons = {
            str(item.get("reject_reason"))
            for item in stale_trace.get("rejected_candidates", [])
            if isinstance(item, dict)
        }
        if "GROUNDING_BLOCKED" not in reject_reasons:
            raise SmokeFailure("STALE_TRACE_MISSING_GROUNDING_BLOCK")
        steps.append({"step": "revoke_and_stale_abstention", "status": "PASS"})

        if worker.run_once() <= 0:
            raise SmokeFailure("WORKER_DID_NOT_PROCESS_PURGE")
        deletion = _body(
            client.get(
                f"/v1/deletion-requests/{deletion_request_id}",
                headers=_headers(tokens["reader"]),
            ),
            200,
            "deletion_status",
        )
        if (
            deletion.get("derived_purge_status") != "COMPLETED"
            or deletion.get("primary_bytes_status") != "ERASED"
        ):
            raise SmokeFailure("DELETION_NOT_COMPLETED")
        steps.append({"step": "deletion_status", "status": "PASS"})
        return {
            "evidence_id": evidence_id,
            "proposal_id": proposal_id,
            "claim_id": claim_id,
            "claim_version_id": claim_version_id,
            "context_capsule_id": str(capsule["capsule_id"]),
            "retrieval_trace_id": trace_id,
            "stale_retrieval_trace_id": stale_trace_id,
            "deletion_request_id": deletion_request_id,
        }
    finally:
        _stop_api(api_process)
        worker_database.close()


def run_isolated_smoke() -> dict[str, object]:
    source = load_settings()
    owner_url = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_url = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_url = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_url or not worker_url or not audit_url:
        raise SettingsError("smoke-test requires owner, worker, and audit database URLs")

    run_id = uuid4().hex
    database = f"{_DATABASE_PREFIX}{run_id[:20]}"
    tenant_id = uuid4()
    actor_id = uuid4()
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    database_urls = {
        "owner": _database_url(owner_url, database),
        "api": _database_url(source.database_dsn, database),
        "steward": _database_url(source.steward_database_dsn, database),
        "worker": _database_url(worker_url, database),
        "audit": _database_url(audit_url, database),
    }
    report: dict[str, object] = {
        "schema": "milai.isolated-smoke.v1",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "BLOCKED",
        "mode": "ISOLATED_SYNTHETIC_FULL_CHAIN",
        "database": database,
        "tenant_id": str(tenant_id),
        "steps": [],
    }
    created = False
    cleanup: dict[str, object] = {"status": "NOT_STARTED"}
    temporary_path: str | None = None
    try:
        _create_database(owner_url, database)
        created = True
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        with psycopg.connect(database_urls["owner"], connect_timeout=5) as smoke_owner:
            revision = smoke_owner.execute("SELECT version_num FROM alembic_version").fetchone()
        if revision is None:
            raise SmokeFailure("SMOKE_MIGRATION_HEAD_MISSING")
        report["migration_head"] = str(revision[0])
        with tempfile.TemporaryDirectory(prefix="milai-smoke-blobs-") as blob_directory:
            temporary_path = str(Path(blob_directory).resolve())
            settings = _smoke_settings(
                source,
                database_urls,
                Path(blob_directory),
                tenant_id,
                actor_id,
                tokens,
                _free_loopback_port(),
            )
            prepare_runtime_directories(settings)
            artifacts = _run_chain(
                settings,
                database_urls,
                tokens,
                report["steps"],  # type: ignore[arg-type]
            )
            report["artifacts"] = artifacts
        report["blob_cleanup"] = {
            "status": "PASS" if temporary_path and not Path(temporary_path).exists() else "BLOCKED",
            "exact_temporary_root_removed": bool(
                temporary_path and not Path(temporary_path).exists()
            ),
        }
        report["status"] = "PASS"
    except Exception as exc:
        report["failure_code"] = (
            exc.code if isinstance(exc, SmokeFailure) else type(exc).__name__.upper()
        )
    finally:
        if created:
            cleanup = _drop_database(owner_url, database)
        report["database_cleanup"] = cleanup
        if cleanup.get("status") != "PASS":
            report["status"] = "BLOCKED"
        report["finished_at"] = datetime.now(UTC).isoformat()
        report_path = _write_report(report)

    return {
        "status": report["status"],
        "mode": report["mode"],
        "run_id": run_id,
        "steps": report["steps"],
        "database_cleanup": report["database_cleanup"],
        "blob_cleanup": report.get("blob_cleanup", {"status": "NOT_STARTED"}),
        "report": str(report_path),
        **({"failure_code": report["failure_code"]} if "failure_code" in report else {}),
    }
