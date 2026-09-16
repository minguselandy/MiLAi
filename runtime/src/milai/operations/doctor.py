from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from alembic.script import ScriptDirectory

from milai.config import RuntimeSettings, SettingsError, load_settings
from milai.operations.migrations import alembic_config

_RUNTIME_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_ROOT = _RUNTIME_ROOT.parent
_PG_VERSION = re.compile(r"\b(\d+)(?:\.\d+)?\b")


def _check(name: str, status: str, detail: str, **facts: object) -> dict[str, object]:
    result: dict[str, object] = {"name": name, "status": status, "detail": detail}
    if facts:
        result["facts"] = facts
    return result


def _command(
    arguments: list[str], *, cwd: Path | None = None, timeout: float = 15
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 -- every caller provides a fixed local argv
            arguments,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _empty_environment_fields(path: Path) -> list[str]:
    if not path.is_file():
        return []
    empty: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.startswith("MILAI_") and not value.strip():
            empty.append(name)
    return sorted(empty)


def _alembic_head() -> str:
    config = alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no unique head")
    return head


def _role_facts(connection: psycopg.Connection[Any]) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT session_user, current_user, role.rolsuper, role.rolcreatedb,
               role.rolcreaterole, role.rolbypassrls,
               EXISTS (
                 SELECT 1 FROM pg_namespace namespace
                 WHERE namespace.nspname = 'milai' AND namespace.nspowner = role.oid
               ) OR EXISTS (
                 SELECT 1
                 FROM pg_class object
                 JOIN pg_namespace namespace ON namespace.oid = object.relnamespace
                 WHERE namespace.nspname = 'milai' AND object.relowner = role.oid
               ) AS owns_milai_object
        FROM pg_roles role WHERE role.rolname = session_user
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("database role metadata is unavailable")
    return {
        "session_user": row[0],
        "current_user": row[1],
        "superuser": bool(row[2]),
        "createdb": bool(row[3]),
        "createrole": bool(row[4]),
        "bypass_rls": bool(row[5]),
        "owns_milai_object": bool(row[6]),
    }


def _database_checks(
    settings: RuntimeSettings, environ: Mapping[str, str]
) -> tuple[list[dict[str, object]], int | None]:
    checks: list[dict[str, object]] = []
    role_sources = {
        "milai_owner": environ.get("MILAI_MIGRATION_DATABASE_URL"),
        "milai_api": settings.database_dsn,
        "milai_steward": settings.steward_database_dsn,
        "milai_worker": environ.get("MILAI_WORKER_DATABASE_URL"),
        "milai_audit": environ.get("MILAI_AUDIT_DATABASE_URL"),
    }
    owner_url = role_sources["milai_owner"]
    server_major: int | None = None
    role_results: list[dict[str, object]] = []
    missing_roles = [role for role, dsn in role_sources.items() if not dsn]
    if missing_roles:
        checks.append(
            _check(
                "database_roles",
                "BLOCKED",
                "dedicated database URLs are missing",
                missing=missing_roles,
            )
        )
        return checks, server_major

    try:
        for expected, dsn in role_sources.items():
            assert dsn is not None
            with psycopg.connect(dsn, connect_timeout=3) as connection:
                facts = _role_facts(connection)
                exact = facts["session_user"] == expected and facts["current_user"] == expected
                if expected == "milai_owner":
                    safe = exact and bool(facts["owns_milai_object"])
                else:
                    safe = exact and not any(
                        bool(facts[field])
                        for field in (
                            "superuser",
                            "createdb",
                            "createrole",
                            "bypass_rls",
                            "owns_milai_object",
                        )
                    )
                role_results.append(
                    {
                        "role": expected,
                        "status": "PASS" if safe else "BLOCKED",
                        **facts,
                    }
                )
        checks.append(
            _check(
                "database_roles",
                "BLOCKED" if any(item["status"] == "BLOCKED" for item in role_results) else "PASS",
                "exact login and ownership attestation",
                roles=role_results,
            )
        )
    except (psycopg.Error, OSError, RuntimeError):
        checks.append(
            _check(
                "database_roles",
                "BLOCKED",
                "PostgreSQL or a dedicated login role is not reachable",
            )
        )
        return checks, server_major

    assert owner_url is not None
    try:
        with psycopg.connect(owner_url, connect_timeout=3) as owner:
            current_row = owner.execute("SELECT version_num FROM alembic_version").fetchone()
            current = str(current_row[0]) if current_row else "missing"
            head = _alembic_head()
            checks.append(
                _check(
                    "alembic",
                    "PASS" if current == head else "BLOCKED",
                    "current migration must equal the unique local head",
                    current=current,
                    head=head,
                )
            )
            vector_row = owner.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            checks.append(
                _check(
                    "pgvector",
                    "PASS" if vector_row else "BLOCKED",
                    "extension installed" if vector_row else "extension missing",
                    version=str(vector_row[0]) if vector_row else None,
                )
            )
            version_row = owner.execute("SHOW server_version_num").fetchone()
            if version_row:
                server_major = int(str(version_row[0])) // 10_000

            maximum_row = owner.execute(
                "SELECT COALESCE(max(outbox_sequence), 0) FROM milai.outbox_event "
                "WHERE tenant_id = %s",
                (settings.tenant_id,),
            ).fetchone()
            maximum = int(maximum_row[0]) if maximum_row else 0
            watermarks = {
                str(name): int(position)
                for name, position in owner.execute(
                    "SELECT projection_name, last_contiguous_outbox_sequence "
                    "FROM milai.index_watermark WHERE tenant_id = %s ORDER BY projection_name",
                    (settings.tenant_id,),
                ).fetchall()
            }
            delivery = owner.execute(
                """
                SELECT count(*) FILTER (WHERE state = 'DEAD_LETTER'),
                       count(*) FILTER (
                         WHERE state = 'PROCESSING' AND lease_expires_at < CURRENT_TIMESTAMP
                       )
                FROM milai.projection_delivery WHERE tenant_id = %s
                """,
                (settings.tenant_id,),
            ).fetchone()
            dead_letters = int(delivery[0]) if delivery else 0
            expired_leases = int(delivery[1]) if delivery else 0
            lag = {
                name: max(0, maximum - watermarks.get(name, 0))
                for name in ("fts", "vector", "purge")
            }
            worker_status = "BLOCKED" if dead_letters or expired_leases else "PASS"
            if worker_status == "PASS" and any(value > 0 for value in lag.values()):
                worker_status = "WARN"
            checks.append(
                _check(
                    "worker_projection",
                    worker_status,
                    "watermark, lease, and dead-letter diagnosis",
                    maximum_outbox_sequence=maximum,
                    watermarks=watermarks,
                    lag=lag,
                    dead_letters=dead_letters,
                    expired_leases=expired_leases,
                )
            )
    except (psycopg.Error, OSError, RuntimeError, ValueError):
        checks.append(
            _check(
                "database_schema",
                "BLOCKED",
                "migration, extension, or worker state could not be attested",
            )
        )
    return checks, server_major


def _backup_client_check(server_major: int | None) -> dict[str, object]:
    executable = shutil.which("pg_dump")
    if executable is None:
        return _check("backup_client", "BLOCKED", "pg_dump is missing")
    completed = _command([executable, "--version"])
    output = completed.stdout.strip() if completed and completed.returncode == 0 else ""
    match = _PG_VERSION.search(output)
    client_major = int(match.group(1)) if match else None
    status = "PASS" if client_major is not None else "BLOCKED"
    if status == "PASS" and server_major is not None and client_major != server_major:
        status = "BLOCKED"
    return _check(
        "backup_client",
        status,
        "pg_dump major must match PostgreSQL server major",
        client_major=client_major,
        server_major=server_major,
    )


def _api_json(url: str, token: str | None = None) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = Request(url, headers=headers)  # noqa: S310 -- caller supplies validated loopback URL
    with urlopen(request, timeout=2) as response:  # noqa: S310 -- loopback settings are validated
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("API response is not an object")
    return value


def _api_checks(settings: RuntimeSettings, environ: Mapping[str, str]) -> list[dict[str, object]]:
    base = environ.get(
        "MILAI_BASE_URL", f"http://{settings.bind_host}:{settings.bind_port}"
    ).rstrip("/")
    try:
        live = _api_json(f"{base}/health/live")
        ready = _api_json(f"{base}/health/ready")
        token = (settings.agent_reader_token or settings.api_token).get_secret_value()
        capabilities = _api_json(f"{base}/v1/capabilities", token)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return [
            _check("api_live_ready", "NOT_CONFIGURED", "no compatible MiLAi API is listening"),
            _check(
                "agent_compatibility",
                "NOT_CONFIGURED",
                "start the API to negotiate the agent.v1 contract",
            ),
        ]
    ready_status = live.get("status") == "ok" and ready.get("status") == "ready"
    compatible = capabilities.get("contract_version") == "agent.v1"
    return [
        _check(
            "api_live_ready",
            "PASS" if ready_status else "BLOCKED",
            "liveness and canonical readiness are reported separately",
            live=live.get("status"),
            ready=ready.get("status"),
        ),
        _check(
            "agent_compatibility",
            "PASS" if compatible else "BLOCKED",
            "runtime must negotiate the agent.v1 contract",
            contract_version=capabilities.get("contract_version"),
            runtime_version=capabilities.get("runtime_version"),
            profile=capabilities.get("profile"),
        ),
    ]


def run_doctor(
    env_file: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    source = os.environ if environ is None else environ
    checks: list[dict[str, object]] = []
    checks.append(
        _check(
            "platform",
            "PASS" if platform.system() in {"Linux", "Darwin", "Windows"} else "WARN",
            "host operating system and architecture",
            os=platform.system(),
            release=platform.release(),
            architecture=platform.machine(),
        )
    )
    python_ok = (3, 11) <= sys.version_info[:2] < (3, 13)
    checks.append(
        _check(
            "python",
            "PASS" if python_ok else "BLOCKED",
            "MiLAi requires Python >=3.11,<3.13",
            version=platform.python_version(),
        )
    )

    uv = shutil.which("uv")
    lock = _RUNTIME_ROOT / "uv.lock"
    lock_result = _command([uv, "lock", "--check"], cwd=_RUNTIME_ROOT, timeout=30) if uv else None
    checks.append(
        _check(
            "uv_lock",
            "PASS"
            if uv and lock.is_file() and lock_result is not None and lock_result.returncode == 0
            else "BLOCKED",
            "uv is available and the Runtime lock is current",
            uv_available=uv is not None,
            lock_present=lock.is_file(),
            lock_current=bool(lock_result is not None and lock_result.returncode == 0),
        )
    )

    docker = shutil.which("docker")
    compose = _command([docker, "compose", "version"], timeout=10) if docker else None
    daemon = (
        _command([docker, "info", "--format", "{{.ServerVersion}}"], timeout=10) if docker else None
    )
    checks.append(
        _check(
            "docker_compose",
            "PASS"
            if compose and compose.returncode == 0 and daemon and daemon.returncode == 0
            else "BLOCKED",
            "Docker CLI, Compose plugin, and daemon must be available",
            docker_available=docker is not None,
            compose_available=bool(compose and compose.returncode == 0),
            daemon_available=bool(daemon and daemon.returncode == 0),
        )
    )

    if not env_file.is_file():
        checks.append(_check("env_file", "NOT_CONFIGURED", "run milai-ops init"))
    else:
        mode = env_file.stat().st_mode & 0o777
        empty = _empty_environment_fields(env_file)
        checks.append(
            _check(
                "env_file",
                "PASS" if mode == 0o600 and not empty else "BLOCKED",
                "environment file permissions and non-empty field names",
                mode=f"{mode:04o}",
                empty_fields=empty,
            )
        )

    try:
        settings = load_settings(source)
    except SettingsError as exc:
        checks.append(_check("settings", "BLOCKED", str(exc)))
        overall = "BLOCKED"
        return {
            "schema": "milai.doctor.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": overall,
            "checks": checks,
            "summary": _summary(checks),
        }

    checks.append(
        _check(
            "settings",
            "PASS",
            "strict configuration accepted",
            safe_summary=settings.safe_summary(),
        )
    )
    checks.append(
        _check(
            "loopback_binding",
            "PASS",
            "RuntimeSettings rejected non-loopback binding",
            bind_host=settings.bind_host,
            bind_port=settings.bind_port,
        )
    )

    if settings.blob_root.exists():
        mode = settings.blob_root.stat().st_mode & 0o777
        blob_ok = (
            settings.blob_root.is_dir() and not settings.blob_root.is_symlink() and mode == 0o700
        )
        checks.append(
            _check(
                "blob_root",
                "PASS" if blob_ok else "BLOCKED",
                "blob root must be a real local 0700 directory",
                path=str(settings.blob_root),
                mode=f"{mode:04o}",
            )
        )
    else:
        checks.append(
            _check(
                "blob_root",
                "NOT_CONFIGURED",
                "directory will be created by the local start profile",
                path=str(settings.blob_root),
            )
        )

    database_checks, server_major = _database_checks(settings, source)
    checks.extend(database_checks)
    checks.append(_backup_client_check(server_major))
    checks.extend(_api_checks(settings, source))

    package_paths = [
        _PROJECT_ROOT / "integrations/python-client/pyproject.toml",
        _PROJECT_ROOT / "integrations/python-client/uv.lock",
        _PROJECT_ROOT / "integrations/mcp/pyproject.toml",
        _PROJECT_ROOT / "integrations/mcp/uv.lock",
    ]
    checks.append(
        _check(
            "agent_packages",
            "PASS" if all(path.is_file() for path in package_paths) else "BLOCKED",
            "versioned SDK and MCP package definitions and locks",
            present=sum(path.is_file() for path in package_paths),
            expected=len(package_paths),
        )
    )

    crypto_status = (
        "PASS"
        if settings.data_mode != "LOCAL_PERSONAL_DATA"
        else (
            "PASS"
            if settings.blob_encryption == "AES_256_GCM" and settings.backup_key_recovery_confirmed
            else "BLOCKED"
        )
    )
    checks.append(
        _check(
            "data_crypto_gate",
            crypto_status,
            "real-data mode requires encryption and confirmed recovery",
            data_mode=settings.data_mode,
            blob_encryption=settings.blob_encryption,
            recovery_confirmed=settings.backup_key_recovery_confirmed,
        )
    )
    overall = "BLOCKED" if any(item["status"] == "BLOCKED" for item in checks) else "PASS"
    return {
        "schema": "milai.doctor.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": overall,
        "checks": checks,
        "summary": _summary(checks),
    }


def _summary(checks: list[dict[str, object]]) -> dict[str, int]:
    return {
        status: sum(item["status"] == status for item in checks)
        for status in ("PASS", "WARN", "BLOCKED", "NOT_CONFIGURED")
    }
