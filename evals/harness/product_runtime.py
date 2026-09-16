from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from evals.harness.contracts import HistoryItem, WorkloadHistory
from evals.harness.infrastructure import TemporaryResourceSpec
from evals.harness.lease import BuildReceipt, EvaluationRuntimeLease


class ProductRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProductRuntimeConfig:
    python_executable: Path
    source_env_file: Path
    product_manifest_sha256: str
    startup_timeout_seconds: float = 120.0
    projection_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.python_executable.is_absolute() or not self.python_executable.is_file():
            raise ValueError("product Python executable must be an absolute file")
        if not self.source_env_file.is_absolute() or not self.source_env_file.is_file():
            raise ValueError("source environment must be an absolute file")
        if len(self.product_manifest_sha256) != 64:
            raise ValueError("product manifest identity must be SHA-256")
        if self.startup_timeout_seconds <= 0 or self.projection_timeout_seconds <= 0:
            raise ValueError("product runtime timeouts must be positive")

    def entrypoint(self, name: str) -> Path:
        path = self.python_executable.with_name(name)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ProductRuntimeError(f"installed product entrypoint is unavailable: {name}")
        return path


def read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.startswith("MILAI_"):
            values[name] = value
    return values


def rewrite_database_url(value: str, database_name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.netloc:
        raise ProductRuntimeError("source database URL is invalid")
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))


def render_evaluation_environment(
    source: Mapping[str, str],
    spec: TemporaryResourceSpec,
    *,
    bind_port: int,
    tenant_id: str,
    actor_id: str,
) -> dict[str, str]:
    values = dict(source)
    database_keys = (
        "MILAI_DATABASE_URL",
        "MILAI_STEWARD_DATABASE_URL",
        "MILAI_WORKER_DATABASE_URL",
        "MILAI_MIGRATION_DATABASE_URL",
        "MILAI_AUDIT_DATABASE_URL",
    )
    missing = [name for name in database_keys if name not in values]
    if missing:
        raise ProductRuntimeError("source environment omits required role database URLs")
    for name in database_keys:
        values[name] = rewrite_database_url(values[name], spec.database_name)
    values.update(
        {
            "MILAI_POSTGRES_DB": spec.database_name,
            "MILAI_BLOB_ROOT": str(spec.blob_root.resolve()),
            "MILAI_TENANT_ID": tenant_id,
            "MILAI_LOCAL_ACTOR_ID": actor_id,
            "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
            "MILAI_BIND_HOST": "127.0.0.1",
            "MILAI_BIND_PORT": str(bind_port),
            "MILAI_BASE_URL": f"http://127.0.0.1:{bind_port}",
        }
    )
    return values


def grouped_history(history: WorkloadHistory) -> tuple[tuple[str, str, str], ...]:
    sessions: dict[str, list[HistoryItem]] = defaultdict(list)
    for item in history.items:
        sessions[item.session_id].append(item)
    result: list[tuple[str, str, str]] = []
    for session_id, items in sessions.items():
        observed_at = next(
            (item.occurred_at for item in items if item.occurred_at is not None),
            "2000-01-01T00:00:00+00:00",
        )
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        observed_at = parsed.astimezone(timezone.utc).isoformat()
        content = "\n".join(f"{item.role}: {item.content}" for item in items)
        result.append((session_id, observed_at, content))
    return tuple(result)


def claim_projection(
    history: WorkloadHistory, *, fingerprint: str, index: int
) -> tuple[str, str, str]:
    metadata = history.metadata
    explicit = metadata.get("claim_projections")
    if isinstance(explicit, list):
        if not 0 <= index < len(explicit) or not isinstance(explicit[index], Mapping):
            raise ProductRuntimeError("explicit claim projection does not match history sessions")
        projection = explicit[index]
        fields = tuple(projection.get(name) for name in ("subject_id", "predicate", "claim_type"))
        if not all(isinstance(value, str) and value.strip() for value in fields):
            raise ProductRuntimeError("explicit claim projection requires typed non-empty fields")
        return str(fields[0]), str(fields[1]), str(fields[2])
    namespace = str(metadata.get("claim_subject_namespace", history.workload_id))
    if len(namespace) > 480:
        namespace = fingerprint[:24]
    width = int(metadata.get("claim_subject_index_width", 5))
    predicate = str(metadata.get("claim_predicate", "memory.session"))
    claim_type = str(metadata.get("claim_type", "SESSION_MEMORY"))
    return f"{namespace}-{index:0{width}d}", predicate, claim_type


def broker_policy(
    *,
    profile: str,
    socket_path: Path,
    mcp_executable: Path,
    base_url: str,
    scope: Mapping[str, Any],
    required_authority: str = "ACTION_SAFE",
) -> dict[str, Any]:
    if required_authority not in {"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"}:
        raise ValueError("unknown evaluation broker authority")
    digest = hashlib.sha256(mcp_executable.read_bytes()).hexdigest()
    return {
        "allowed_peer_uids": [os.geteuid()],
        "base_url": base_url,
        "child_shutdown_seconds": 5,
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_connections": 2,
        "max_limit": 3,
        "mcp_executable": str(mcp_executable),
        "mcp_executable_sha256": digest,
        "profile": profile,
        "required_authority": required_authority,
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "scope": dict(scope),
        "socket_mode": "0600",
        "socket_path": str(socket_path),
    }


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _safe_subprocess_environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.startswith("MILAI_")}


class ProductEvaluationRuntime:
    """Persistent installed-product deployment for immutable evaluation workloads."""

    def __init__(self, config: ProductRuntimeConfig) -> None:
        self.config = config
        self.spec: TemporaryResourceSpec | None = None
        self.environment: dict[str, str] = {}
        self.env_file: Path | None = None
        self._brokers: list[subprocess.Popen[bytes]] = []
        self._broker_logs: list[Any] = []
        self._active_fingerprint: str | None = None
        self._receipts: dict[str, BuildReceipt] = {}
        self._runtime_started = False
        self._database_created = False
        self._api_process: subprocess.Popen[bytes] | None = None
        self._api_log: Any | None = None
        self._managed_operation = False

    @property
    def reader_socket(self) -> Path:
        if self.spec is None:
            raise ProductRuntimeError("product runtime is not provisioned")
        return self.spec.temporary_root.resolve() / "reader-lite" / "reader-lite.sock"

    @property
    def informational_reader_socket(self) -> Path:
        if self.spec is None:
            raise ProductRuntimeError("product runtime is not provisioned")
        return self.spec.temporary_root.resolve() / "ri" / "reader-lite.sock"

    def _database_admin_url(self) -> str:
        source = read_environment(self.config.source_env_file)
        try:
            return rewrite_database_url(source["MILAI_MIGRATION_DATABASE_URL"], "postgres")
        except KeyError as exc:
            raise ProductRuntimeError("source environment has no migration database URL") from exc

    def _create_database(self, name: str) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(self._database_admin_url(), autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER milai_owner").format(sql.Identifier(name))
            )
        self._database_created = True

    def _drop_database(self, name: str) -> None:
        import psycopg
        from psycopg import sql

        with psycopg.connect(self._database_admin_url(), autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        self._database_created = False

    def _run_operation(self, command: str) -> dict[str, Any]:
        if self.env_file is None:
            raise ProductRuntimeError("product runtime environment is unavailable")
        arguments = [
            str(self.config.entrypoint("milai-ops")),
            command,
            "--env-file",
            str(self.env_file),
        ]
        if command == "start":
            arguments.append("--background")
        completed = subprocess.run(
            arguments,
            env=_safe_subprocess_environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=self.config.startup_timeout_seconds,
        )
        if completed.returncode != 0:
            raise ProductRuntimeError(f"installed product {command} operation failed")
        try:
            return dict(json.loads(completed.stdout))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProductRuntimeError("installed product operation returned invalid JSON") from exc

    def create(self, spec: TemporaryResourceSpec) -> EvaluationRuntimeLease:
        if self.spec is not None:
            raise ProductRuntimeError("product runtime already has a resource")
        root = spec.temporary_root.resolve()
        root.mkdir(mode=0o700, parents=True)
        spec.blob_root.resolve().mkdir(mode=0o700, parents=True)
        self.spec = spec
        source = read_environment(self.config.source_env_file)
        self.environment = render_evaluation_environment(
            source,
            spec,
            bind_port=_free_loopback_port(),
            tenant_id=str(uuid4()),
            actor_id=str(uuid4()),
        )
        self.env_file = root / "runtime.env"
        _write_private(
            self.env_file,
            "\n".join(f"{name}={value}" for name, value in sorted(self.environment.items()))
            + "\n",
        )
        try:
            self._create_database(spec.database_name)
            self._run_operation("start")
            self._runtime_started = True
            self._managed_operation = True
        except Exception:
            self.destroy()
            raise
        return EvaluationRuntimeLease(
            lease_id=spec.lease_id,
            reader_socket=self.reader_socket,
            product_manifest_sha256=self.config.product_manifest_sha256,
            history_loader=self.load_history,
            close_callback=self.close,
        )

    def create_governance_only(self, spec: TemporaryResourceSpec) -> dict[str, float]:
        """Start the installed API without a projection worker for timed evaluation."""

        if self.spec is not None:
            raise ProductRuntimeError("product runtime already has a resource")
        root = spec.temporary_root.resolve()
        root.mkdir(mode=0o700, parents=True)
        spec.blob_root.resolve().mkdir(mode=0o700, parents=True)
        self.spec = spec
        source = read_environment(self.config.source_env_file)
        self.environment = render_evaluation_environment(
            source,
            spec,
            bind_port=_free_loopback_port(),
            tenant_id=str(uuid4()),
            actor_id=str(uuid4()),
        )
        self.environment["MILAI_WORKER_EVENT_LIMIT"] = "10000"
        self.env_file = root / "runtime.env"
        _write_private(
            self.env_file,
            "\n".join(f"{name}={value}" for name, value in sorted(self.environment.items()))
            + "\n",
        )
        created_started = time.perf_counter()
        try:
            self._create_database(spec.database_name)
            database_ms = (time.perf_counter() - created_started) * 1_000
            migration_started = time.perf_counter()
            self._run_migrations()
            migration_ms = (time.perf_counter() - migration_started) * 1_000
            api_started = time.perf_counter()
            self._start_api_only()
            api_start_ms = (time.perf_counter() - api_started) * 1_000
            self._runtime_started = True
        except Exception:
            self.destroy()
            raise
        return {
            "db_create_or_clone_ms": round(database_ms, 3),
            "migration_ms": round(migration_ms, 3),
            "api_start_ms": round(api_start_ms, 3),
        }

    def start_existing_database(
        self,
        spec: TemporaryResourceSpec,
        environment: Mapping[str, str],
    ) -> float:
        """Attach the installed API to an exact pre-provisioned evaluation database."""

        if self.spec is not None:
            raise ProductRuntimeError("product runtime already has a resource")
        database_keys = (
            "MILAI_DATABASE_URL",
            "MILAI_STEWARD_DATABASE_URL",
            "MILAI_WORKER_DATABASE_URL",
            "MILAI_MIGRATION_DATABASE_URL",
            "MILAI_AUDIT_DATABASE_URL",
        )
        if any(
            urlsplit(str(environment.get(name, ""))).path != f"/{spec.database_name}"
            for name in database_keys
        ):
            raise ProductRuntimeError("existing evaluation environment database drifted")
        root = spec.temporary_root.resolve()
        root.mkdir(mode=0o700, parents=True)
        spec.blob_root.resolve().mkdir(mode=0o700, parents=True)
        self.spec = spec
        self.environment = dict(environment)
        self.environment["MILAI_BLOB_ROOT"] = str(spec.blob_root.resolve())
        self.environment["MILAI_BIND_PORT"] = str(_free_loopback_port())
        self.environment["MILAI_BASE_URL"] = (
            f"http://127.0.0.1:{self.environment['MILAI_BIND_PORT']}"
        )
        self.env_file = root / "runtime.env"
        _write_private(
            self.env_file,
            "\n".join(f"{name}={value}" for name, value in sorted(self.environment.items()))
            + "\n",
        )
        started = time.perf_counter()
        try:
            self._start_api_only()
            self._runtime_started = True
        except Exception:
            self.destroy()
            raise
        return round((time.perf_counter() - started) * 1_000, 3)

    def bind_scope(self, scope: Mapping[str, Any]) -> None:
        """Bind installed MCP brokers to one explicit evaluation scope."""

        if not self._runtime_started:
            raise ProductRuntimeError("product runtime is not ready")
        self._start_brokers(scope)

    def _component_environment(self, *, worker: bool) -> dict[str, str]:
        result = {**_safe_subprocess_environment(), **self.environment}
        forbidden = {
            "MILAI_MIGRATION_DATABASE_URL",
            "MILAI_AUDIT_DATABASE_URL",
            "MILAI_RESTORE_DATABASE_URL",
            "MILAI_OWNER_DB_PASSWORD",
            "MILAI_AUDIT_DB_PASSWORD",
        }
        if not worker:
            forbidden.update({"MILAI_WORKER_DATABASE_URL", "MILAI_WORKER_DB_PASSWORD"})
        for name in forbidden:
            result.pop(name, None)
        return result

    def _run_migrations(self) -> None:
        completed = subprocess.run(
            [
                str(self.config.python_executable),
                "-c",
                (
                    "from alembic import command; "
                    "from milai.operations.migrations import alembic_config; "
                    "command.upgrade(alembic_config(), 'head')"
                ),
            ],
            env={**_safe_subprocess_environment(), **self.environment},
            check=False,
            capture_output=True,
            timeout=self.config.startup_timeout_seconds,
        )
        if completed.returncode != 0:
            raise ProductRuntimeError("installed product migration failed")

    def _start_api_only(self) -> None:
        if self.spec is None:
            raise ProductRuntimeError("product runtime is not provisioned")
        log_path = self.spec.temporary_root.resolve() / "api.log"
        self._api_log = log_path.open("ab")
        self._api_process = subprocess.Popen(
            [str(self.config.entrypoint("milai-api"))],
            env=self._component_environment(worker=False),
            stdin=subprocess.DEVNULL,
            stdout=self._api_log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        ready_url = self.environment["MILAI_BASE_URL"] + "/health/ready"
        while time.monotonic() < deadline:
            if self._api_process.poll() is not None:
                raise ProductRuntimeError("installed API exited before readiness")
            try:
                with urlopen(ready_url, timeout=1) as response:
                    payload = json.loads(response.read())
                if payload.get("status") == "ready":
                    return
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.05)
        raise ProductRuntimeError("installed API did not become ready")

    def _stop_brokers(self) -> None:
        for process in self._brokers:
            if process.poll() is None:
                process.terminate()
        for process in self._brokers:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in self._broker_logs:
            handle.close()
        self._brokers.clear()
        self._broker_logs.clear()

    def _start_brokers(self, scope: Mapping[str, Any]) -> None:
        if self.spec is None:
            raise ProductRuntimeError("product runtime is not provisioned")
        self._stop_brokers()
        root = self.spec.temporary_root.resolve()
        broker_executable = self.config.entrypoint("milai-mcp-broker")
        mcp_executable = self.config.entrypoint("milai-mcp")
        base_url = self.environment["MILAI_BASE_URL"]
        capabilities = (
            (
                "reader-lite",
                "reader-lite",
                self.environment["MILAI_AGENT_READER_TOKEN"],
                "ACTION_SAFE",
            ),
            (
                "ri",
                "reader-lite",
                self.environment["MILAI_AGENT_READER_TOKEN"],
                "INFORMATIONAL",
            ),
            (
                "submitter",
                "submitter",
                self.environment["MILAI_AGENT_SUBMITTER_TOKEN"],
                "ACTION_SAFE",
            ),
        )
        for capability, profile, token, required_authority in capabilities:
            directory = root / capability
            directory.mkdir(mode=0o700, exist_ok=True)
            socket_path = directory / f"{profile}.sock"
            policy_path = root / f"{capability}.policy.json"
            token_path = root / f"{capability}.token"
            policy_path.unlink(missing_ok=True)
            token_path.unlink(missing_ok=True)
            _write_private(
                policy_path,
                json.dumps(
                    broker_policy(
                        profile=profile,
                        socket_path=socket_path,
                        mcp_executable=mcp_executable,
                        base_url=base_url,
                        scope=scope,
                        required_authority=required_authority,
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            _write_private(token_path, token + "\n")
            log = (root / f"{capability}.broker.log").open("ab")
            process = subprocess.Popen(
                [
                    str(broker_executable),
                    "--policy",
                    str(policy_path),
                    "--token-file",
                    str(token_path),
                ],
                env=_safe_subprocess_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
            self._brokers.append(process)
            self._broker_logs.append(log)
        deadline = time.monotonic() + 10
        sockets = [
            root / "reader-lite" / "reader-lite.sock",
            root / "ri" / "reader-lite.sock",
            root / "submitter" / "submitter.sock",
        ]
        while time.monotonic() < deadline:
            if all(path.exists() for path in sockets) and all(
                process.poll() is None for process in self._brokers
            ):
                return
            time.sleep(0.05)
        self._stop_brokers()
        raise ProductRuntimeError("installed MCP broker did not become ready")

    def _http_json(
        self,
        method: str,
        path: str,
        *,
        token: str,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            data = json.dumps(dict(body), separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(
            self.environment["MILAI_BASE_URL"] + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=15) as response:
                return dict(json.loads(response.read()))
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            raise ProductRuntimeError("installed product HTTP operation failed") from exc

    def _wait_for_projections(self) -> int:
        deadline = time.monotonic() + self.config.projection_timeout_seconds
        last_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status = self._http_json(
                "GET",
                "/v1/system/watermarks",
                token=self.environment["MILAI_AGENT_READER_TOKEN"],
            )
            last_status = status
            snapshot = int(status["canonical_snapshot"])
            watermarks = status.get("watermarks", [])
            if watermarks and all(int(item["watermark"]) >= snapshot for item in watermarks):
                return snapshot
            time.sleep(0.1)
        summary = {
            "canonical_snapshot": last_status.get("canonical_snapshot"),
            "watermarks": last_status.get("watermarks"),
        }
        raise ProductRuntimeError(
            "installed product projections did not catch up: "
            + json.dumps(summary, sort_keys=True, separators=(",", ":"))
        )

    def load_history(self, history: WorkloadHistory) -> BuildReceipt:
        return self._load_history(history, wait_for_projections=True)

    def load_governed_history(self, history: WorkloadHistory) -> BuildReceipt:
        """Create canonical state while deliberately leaving projections pending."""

        return self._load_history(history, wait_for_projections=False)

    def _load_history(
        self, history: WorkloadHistory, *, wait_for_projections: bool
    ) -> BuildReceipt:
        if not self._runtime_started or self.spec is None:
            raise ProductRuntimeError("product runtime is not ready")
        fingerprint = history.fingerprint
        project_ids = history.metadata.get(
            "scope_project_ids", [f"eval-{fingerprint[:24]}"]
        )
        scope = {"project_ids": list(project_ids)}
        if self._active_fingerprint != fingerprint:
            self._start_brokers(scope)
            self._active_fingerprint = fingerprint
        existing = self._receipts.get(fingerprint)
        if existing is not None:
            return BuildReceipt(
                workload_fingerprint=fingerprint,
                status="UNCHANGED",
                canonical_position=existing.canonical_position,
                product_usage={
                    **existing.product_usage,
                    "build_calls": 0,
                    "immutable_workload_reused": True,
                },
            )

        from milai_openworker_mcp import McpUnixClient

        started = time.perf_counter()
        sessions = grouped_history(history)
        submitter_socket = self.spec.temporary_root.resolve() / "submitter" / "submitter.sock"
        client = McpUnixClient(
            submitter_socket,
            request_timeout_seconds=30,
            max_frame_bytes=2 * 1024 * 1024,
        )
        claim_receipts: list[dict[str, Any]] = []
        stage_ms = {"evidence_ms": 0.0, "proposal_ms": 0.0, "review_ms": 0.0}

        def measured(stage: str, function: Any, *args: Any, **kwargs: Any) -> Any:
            stage_started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                stage_ms[stage] += (time.perf_counter() - stage_started) * 1_000

        try:
            for index, (session_id, observed_at, content) in enumerate(sessions):
                operation = f"eval-{fingerprint[:16]}-{index:05d}"
                subject_id, predicate, claim_type = claim_projection(
                    history, fingerprint=fingerprint, index=index
                )
                evidence = measured(
                    "evidence_ms",
                    client.capture_evidence,
                    {
                        "operation_id": operation + "-e",
                        "source_type": "EVALUATION_HISTORY",
                        "source_ref": f"evaluation://{fingerprint}/{index:05d}",
                        "subject_id": subject_id,
                        "observed_at": observed_at,
                        "content": content,
                        "permission_snapshot": {"readable": True, **scope},
                        "confirmation": "CAPTURE",
                        "retention_state": "READABLE",
                        "data_classification": "DEIDENTIFIED",
                    },
                )
                evidence_id = str(evidence["evidence_id"])
                explicit_payloads = history.metadata.get("claim_payloads")
                claim_payload = (
                    explicit_payloads[index]
                    if isinstance(explicit_payloads, list)
                    and index < len(explicit_payloads)
                    and isinstance(explicit_payloads[index], Mapping)
                    else {
                        "session_id": session_id,
                        "memory_text": content,
                    }
                )
                proposal = measured(
                    "proposal_ms",
                    client.create_proposal,
                    {
                        "operation_id": operation + "-p",
                        "proposal": {
                            "operation": "CREATE",
                            "supporting_evidence_refs": [evidence_id],
                            "requested_authority": "ACTION_SAFE",
                            "scope_predicate": scope,
                            "model_id": "deterministic-evaluation-loader",
                            "template_version": "session-memory/v1",
                            "input_snapshot_hash": hashlib.sha256(content.encode()).hexdigest(),
                            "proposed_patch": {
                                "subject_id": subject_id,
                                "predicate": predicate,
                                "claim_type": claim_type,
                                "payload": dict(claim_payload),
                                "valid_time_from": observed_at,
                                "authority": "ACTION_SAFE",
                                "confidence": 1.0,
                            },
                            "derivation_policy_id": "session-memory/v1",
                        },
                        "confirmation": "SUBMIT",
                    },
                )
                reviewed = measured(
                    "review_ms",
                    self._http_json,
                    "POST",
                    f"/v1/proposals/{proposal['proposal_id']}/review",
                    token=self.environment["MILAI_AGENT_REVIEWER_TOKEN"],
                    idempotency_key=operation + "-r",
                    body={
                        "decision": "APPROVE",
                        "policy_version": "evaluation-steward/v1",
                        "reason_code": "DEIDENTIFIED_EVALUATION_HISTORY",
                    },
                )
                claim_receipts.append(
                    {
                        "index": index,
                        "subject_id": subject_id,
                        "predicate": predicate,
                        "claim_type": claim_type,
                        "claim_id": str(reviewed["claim_id"]),
                        "claim_version_id": str(reviewed["claim_version_id"]),
                        "evidence_id": evidence_id,
                    }
                )
        finally:
            client.close()
        governance_total_ms = (time.perf_counter() - started) * 1_000
        projection_wait_started = time.perf_counter()
        if wait_for_projections:
            canonical_position = self._wait_for_projections()
            status = "READY"
        else:
            snapshot = self._http_json(
                "GET",
                "/v1/system/watermarks",
                token=self.environment["MILAI_AGENT_READER_TOKEN"],
            )
            canonical_position = int(snapshot["canonical_snapshot"])
            status = "CANONICAL_READY"
        projection_wait_ms = (time.perf_counter() - projection_wait_started) * 1_000
        receipt = BuildReceipt(
            workload_fingerprint=fingerprint,
            status=status,
            canonical_position=canonical_position,
            product_usage={
                "build_calls": 1,
                "immutable_workload_reused": False,
                "history_items": len(history.items),
                "history_sessions": len(sessions),
                "evidence_captures": len(sessions),
                "proposal_creates": len(sessions),
                "steward_reviews": len(sessions),
                "claim_receipts": claim_receipts,
                "governance_stage_ms": {
                    **{name: round(value, 3) for name, value in stage_ms.items()},
                    "governance_total_ms": round(governance_total_ms, 3),
                    "projection_wait_ms": round(projection_wait_ms, 3),
                },
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            },
        )
        self._receipts[fingerprint] = receipt
        return receipt

    def apply_claim_transition(
        self,
        *,
        operation_id: str,
        operation: str,
        claim_id: str,
        expected_version_id: str,
        subject_id: str,
        observed_at: str,
        content: str,
        scope: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if operation not in {"CONTRADICT", "SUPERSEDE"}:
            raise ValueError("governed fixture transition operation is unsupported")
        if not self._runtime_started or self.spec is None:
            raise ProductRuntimeError("product runtime is not ready")
        from milai_openworker_mcp import McpUnixClient

        submitter_socket = self.spec.temporary_root.resolve() / "submitter" / "submitter.sock"
        client = McpUnixClient(
            submitter_socket,
            request_timeout_seconds=30,
            max_frame_bytes=2 * 1024 * 1024,
        )
        try:
            evidence = client.capture_evidence(
                {
                    "operation_id": operation_id + "-e",
                    "source_type": "EVALUATION_TRANSITION",
                    "source_ref": f"evaluation-transition://{operation_id}",
                    "subject_id": subject_id,
                    "observed_at": observed_at,
                    "content": content,
                    "permission_snapshot": {"readable": True, **dict(scope)},
                    "confirmation": "CAPTURE",
                    "retention_state": "READABLE",
                    "data_classification": "DEIDENTIFIED",
                }
            )
            evidence_id = str(evidence["evidence_id"])
            proposal_body: dict[str, Any] = {
                "target_claim_id": claim_id,
                "operation": operation,
                "expected_version_id": expected_version_id,
                "proposed_patch": {},
                "scope_predicate": dict(scope),
                "requested_authority": "ACTION_SAFE",
                "model_id": "deterministic-evaluation-transition",
                "template_version": "governed-fixture-transition/v1",
                "input_snapshot_hash": hashlib.sha256(content.encode()).hexdigest(),
                "derivation_policy_id": "governed-fixture-transition/v1",
            }
            if operation == "CONTRADICT":
                proposal_body["contradicting_evidence_refs"] = [evidence_id]
            else:
                proposal_body["supporting_evidence_refs"] = [evidence_id]
                proposal_body["proposed_patch"] = {
                    "payload": dict(payload or {}),
                    "authority": "ACTION_SAFE",
                    "confidence": 1.0,
                }
            proposal = client.create_proposal(
                {
                    "operation_id": operation_id + "-p",
                    "proposal": proposal_body,
                    "confirmation": "SUBMIT",
                }
            )
        finally:
            client.close()
        reviewed = self._http_json(
            "POST",
            f"/v1/proposals/{proposal['proposal_id']}/review",
            token=self.environment["MILAI_AGENT_REVIEWER_TOKEN"],
            idempotency_key=operation_id + "-r",
            body={
                "decision": "APPROVE",
                "policy_version": "evaluation-steward/v1",
                "reason_code": "SYNTHETIC_FIXTURE_TRANSITION",
            },
        )
        canonical_position = self._wait_for_projections()
        return {
            "operation": operation,
            "claim_id": str(reviewed["claim_id"]),
            "claim_version_id": str(
                reviewed.get("claim_version_id") or expected_version_id
            ),
            "evidence_id": evidence_id,
            "open_issue_id": (
                str(reviewed["open_issue_id"])
                if reviewed.get("open_issue_id") is not None
                else None
            ),
            "canonical_position": canonical_position,
        }

    def revoke_fixture_evidence(
        self, *, operation_id: str, evidence_id: str
    ) -> dict[str, Any]:
        if not self._runtime_started:
            raise ProductRuntimeError("product runtime is not ready")
        revoked = self._http_json(
            "POST",
            f"/v1/evidence/{evidence_id}/revoke",
            token=self.environment["MILAI_AGENT_REVIEWER_TOKEN"],
            idempotency_key=operation_id,
            body={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
        )
        canonical_position = self._wait_for_projections()
        return {
            "operation": "REVOKE_EVIDENCE",
            "evidence_id": evidence_id,
            "deletion_request_id": str(revoked["deletion_request_id"]),
            "logical_revocation_status": revoked["logical_revocation_status"],
            "canonical_block_status": revoked["canonical_block_status"],
            "canonical_position": canonical_position,
        }

    def close(self) -> None:
        self._stop_brokers()
        if self._api_process is not None:
            if self._api_process.poll() is None:
                self._api_process.terminate()
                try:
                    self._api_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._api_process.kill()
                    self._api_process.wait(timeout=5)
            self._api_process = None
            if self._api_log is not None:
                self._api_log.close()
                self._api_log = None
            self._runtime_started = False
        elif self._runtime_started and self._managed_operation:
            self._run_operation("stop")
            self._runtime_started = False
        self._managed_operation = False

    def destroy(self) -> None:
        self.close()
        if self.spec is None:
            return
        spec = self.spec
        if self._database_created:
            self._drop_database(spec.database_name)
        root = spec.temporary_root.resolve()
        if root.name and root != root.parent and spec.blob_root.resolve().is_relative_to(root):
            shutil.rmtree(root, ignore_errors=False)
        self.spec = None
        self.env_file = None
        self.environment = {}
        self._active_fingerprint = None
        self._receipts.clear()

    @contextmanager
    def provision(self, spec: TemporaryResourceSpec) -> Iterator[EvaluationRuntimeLease]:
        lease = self.create(spec)
        try:
            yield lease
        finally:
            lease.close()
            self.destroy()
