from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg

from milai.config import SettingsError, load_settings
from milai.operations.backup import (
    BackupError,
    create_backup,
    expire_backup,
    restore_backup,
    verify_backup,
)
from milai.operations.doctor import run_doctor
from milai.operations.full_gate import run_runtime_full_gate
from milai.operations.import_dry_run import dry_run_import
from milai.operations.local_runtime import (
    load_runtime_environment,
    managed_process_status,
    start_local,
    stop_local,
)
from milai.operations.packaging import (
    build_package_release_manifest,
    run_package_clean_install_gate,
)
from milai.operations.smoke import run_isolated_smoke

# Frozen evaluation sources import the former private name. It remains a
# logic-free alias until those source-bound artifacts age out.
_load_environment_file = load_runtime_environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MiLAi local operational controls")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="create a secure local .env")
    initialize.add_argument("--env-file", type=Path, default=Path(".env"))
    initialize.add_argument("--blob-root", default="./var/blobs")
    initialize.add_argument("--postgres-port", type=int, default=15432)
    initialize.add_argument("--api-port", type=int, default=18080)
    doctor = commands.add_parser("doctor", help="run non-destructive prerequisite checks")
    doctor.add_argument("--json", action="store_true", dest="json_output")
    doctor.add_argument("--env-file", type=Path, default=Path(".env"))
    status = commands.add_parser("status", help="query the running local service")
    status.add_argument("--json", action="store_true", dest="json_output")
    status.add_argument("--env-file", type=Path, default=Path(".env"))
    smoke = commands.add_parser("smoke-test", help="run an isolated synthetic full-chain smoke")
    smoke.add_argument("--env-file", type=Path, default=Path(".env"))
    start = commands.add_parser("start", help="start the tested local Runtime profile")
    start.add_argument("--env-file", type=Path, default=Path(".env"))
    start.add_argument("--background", action="store_true")
    start.add_argument("--compose-project", default="milai-lean-v1")
    stop = commands.add_parser("stop", help="stop the managed local Runtime and preserve data")
    stop.add_argument("--env-file", type=Path, default=Path(".env"))
    agent = commands.add_parser("agent-config", help="emit a secret-free MCP host config")
    agent.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    agent.add_argument("--url", default="http://127.0.0.1:7337/mcp")
    agent.add_argument(
        "--profile",
        choices=(
            "agent-memory",
            "reader-lite",
            "reader-detail",
            "reader",
            "submitter",
            "operator",
            "reviewer",
        ),
        default="reader-lite",
    )
    backup = commands.add_parser("backup", help="create a quiescent consistency archive")
    backup.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-backup", help="verify hashes and dump readability")
    verify.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser("restore", help="restore into an explicitly empty target")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--target-blob-root", type=Path, required=True)
    restore.add_argument("--confirm-empty-target", action="store_true")
    expire = commands.add_parser("expire-backup", help="erase an archive and reconcile deletion")
    expire.add_argument("--archive", type=Path, required=True)
    expire.add_argument("--confirm", required=True)
    rebuild = commands.add_parser("rebuild-projection", help="reset a derived search projection")
    rebuild.add_argument("--projection", choices=("fts", "vector"), required=True)
    rebuild.add_argument("--confirm", required=True)
    rotate = commands.add_parser("rotate-blob-key", help="resumably rotate encrypted Blobs")
    rotate.add_argument("--new-key-reference", required=True)
    rotate.add_argument("--new-kek-env", default="MILAI_NEW_BLOB_KEK_B64")
    rotate.add_argument("--confirm", required=True)
    credentials = commands.add_parser(
        "rotate-local-credentials",
        help="rotate credentials and Blob KEK after a local secret exposure",
    )
    credentials.add_argument("--env-file", type=Path, default=Path(".env"))
    credentials.add_argument("--confirm", required=True)
    import_dry_run = commands.add_parser(
        "import-dry-run", help="inventory an external memory export without writing state"
    )
    import_dry_run.add_argument("--env-file", type=Path, default=Path(".env"))
    import_dry_run.add_argument(
        "--source",
        choices=("mem0-json-v1", "graphiti-json-v1", "hindsight-json-v1"),
        required=True,
    )
    import_dry_run.add_argument("--input", type=Path, required=True)
    import_dry_run.add_argument("--report", type=Path, required=True)
    full_gate = commands.add_parser(
        "runtime-full-gate", help="run all Runtime tests against a fresh database"
    )
    full_gate.add_argument("--env-file", type=Path, default=Path(".env"))
    full_gate.add_argument("--report", type=Path, required=True)
    package_manifest = commands.add_parser(
        "package-manifest", help="build the canonical local package release manifest"
    )
    package_manifest.add_argument("--workspace-root", type=Path, default=Path.cwd())
    package_manifest.add_argument("--output", type=Path, required=True)
    package_install = commands.add_parser(
        "package-clean-install", help="clean-install and import every canonical wheel"
    )
    package_install.add_argument("--workspace-root", type=Path, default=Path.cwd())
    package_install.add_argument("--wheel-root", type=Path)
    package_install.add_argument("--output", type=Path, required=True)
    return parser


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "init":
            result = _initialize_environment(
                args.env_file,
                args.blob_root,
                postgres_port=args.postgres_port,
                api_port=args.api_port,
            )
        elif args.command == "agent-config":
            result = _agent_config(
                args.profile,
                transport=args.transport,
                url=args.url,
            )
        elif args.command == "package-manifest":
            result = build_package_release_manifest(args.workspace_root, args.output)
        elif args.command == "package-clean-install":
            result = run_package_clean_install_gate(
                args.workspace_root,
                args.output,
                wheel_root=args.wheel_root,
            )
        else:
            env_file = getattr(args, "env_file", Path(".env"))
            load_runtime_environment(env_file)
            if args.command == "doctor":
                result = run_doctor(env_file)
            elif args.command == "status":
                result = _runtime_status()
            elif args.command == "smoke-test":
                result = run_isolated_smoke()
            elif args.command == "start":
                result = start_local(
                    env_file,
                    background=args.background,
                    compose_project=args.compose_project,
                )
            elif args.command == "stop":
                result = stop_local(env_file)
            elif args.command == "runtime-full-gate":
                result = run_runtime_full_gate(env_file, args.report)
            elif args.command == "verify-backup":
                verified = verify_backup(args.archive)
                result = {
                    "status": "VERIFIED",
                    "backup_id": verified.manifest["backup_id"],
                    "consistency_fingerprint": verified.manifest["consistency_fingerprint"],
                }
            elif args.command == "restore":
                result = restore_backup(
                    args.archive,
                    args.target_blob_root,
                    target_database_url=_required_environment("MILAI_RESTORE_DATABASE_URL"),
                    confirm_empty_target=args.confirm_empty_target,
                )
            elif args.command == "rotate-local-credentials":
                from milai.operations.credential_rotation import rotate_local_credentials

                result = rotate_local_credentials(
                    env_file,
                    confirmation=args.confirm,
                )
            else:
                settings = load_settings()
                if args.command == "backup":
                    result = create_backup(
                        settings,
                        args.output,
                        owner_database_url=_required_environment("MILAI_MIGRATION_DATABASE_URL"),
                        audit_database_url=_required_environment("MILAI_AUDIT_DATABASE_URL"),
                    )
                elif args.command == "expire-backup":
                    result = expire_backup(
                        settings,
                        args.archive,
                        audit_database_url=_required_environment("MILAI_AUDIT_DATABASE_URL"),
                        confirmation=args.confirm,
                    )
                elif args.command == "rotate-blob-key":
                    result = _rotate_blob_key(
                        settings,
                        new_key_reference=args.new_key_reference,
                        new_kek_env=args.new_kek_env,
                        confirmation=args.confirm,
                    )
                elif args.command == "import-dry-run":
                    result = dry_run_import(
                        settings,
                        source=args.source,
                        input_path=args.input,
                        report_path=args.report,
                    )
                else:
                    result = _rebuild_projection(
                        settings.tenant_id,
                        settings.local_actor_id,
                        args.projection,
                        args.confirm,
                        settings.steward_database_dsn,
                    )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result.get("status") == "BLOCKED":
            raise SystemExit(2)
        if args.command == "runtime-full-gate" and result.get("status") != "PASS":
            raise SystemExit(1)
        if args.command == "package-clean-install" and result.get("status") != "PASS":
            raise SystemExit(1)
    except (BackupError, SettingsError) as exc:
        raise SystemExit(str(exc)) from exc


def _initialize_environment(
    path: Path,
    blob_root: str,
    *,
    postgres_port: int = 15432,
    api_port: int = 18080,
) -> dict[str, object]:
    if not 1 <= postgres_port <= 65535 or not 1 <= api_port <= 65535:
        raise SettingsError("ports must be between 1 and 65535")
    if postgres_port == api_port:
        raise SettingsError("PostgreSQL and API ports must be distinct")
    target = path.expanduser().resolve(strict=False)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    password_names = ("OWNER", "API", "STEWARD", "WORKER", "AUDIT")
    passwords = {name: secrets.token_urlsafe(36) for name in password_names}
    api_token = secrets.token_urlsafe(48)
    causal_secret = secrets.token_urlsafe(48)
    reader_token = secrets.token_urlsafe(48)
    submitter_token = secrets.token_urlsafe(48)
    operator_token = secrets.token_urlsafe(48)
    reviewer_token = secrets.token_urlsafe(48)
    blob_kek = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    database = "milai"
    model_path = (Path.cwd() / "var/models/all-MiniLM-L6-v2").resolve(strict=False)
    real_model_ready = (model_path / "onnx/model.onnx").is_file() and (
        model_path / "tokenizer.json"
    ).is_file()

    def database_url(role: str, password: str) -> str:
        return (
            f"postgresql://{role}:{quote(password, safe='')}@127.0.0.1:{postgres_port}/{database}"
        )

    lines = [
        "# Generated by milai-ops init. Keep this file private and never commit it.",
        f"MILAI_POSTGRES_PORT={postgres_port}",
        f"MILAI_POSTGRES_DB={database}",
        *(f"MILAI_{name}_DB_PASSWORD={value}" for name, value in passwords.items()),
        f"MILAI_DATABASE_URL={database_url('milai_api', passwords['API'])}",
        f"MILAI_STEWARD_DATABASE_URL={database_url('milai_steward', passwords['STEWARD'])}",
        f"MILAI_WORKER_DATABASE_URL={database_url('milai_worker', passwords['WORKER'])}",
        f"MILAI_MIGRATION_DATABASE_URL={database_url('milai_owner', passwords['OWNER'])}",
        f"MILAI_AUDIT_DATABASE_URL={database_url('milai_audit', passwords['AUDIT'])}",
        f"MILAI_BLOB_ROOT={blob_root}",
        f"MILAI_TENANT_ID={uuid4()}",
        f"MILAI_LOCAL_ACTOR_ID={uuid4()}",
        f"MILAI_API_TOKEN={api_token}",
        f"MILAI_CAUSAL_TOKEN_SECRET={causal_secret}",
        f"MILAI_AGENT_READER_TOKEN={reader_token}",
        f"MILAI_AGENT_SUBMITTER_TOKEN={submitter_token}",
        f"MILAI_AGENT_OPERATOR_TOKEN={operator_token}",
        f"MILAI_AGENT_REVIEWER_TOKEN={reviewer_token}",
        "MILAI_BIND_HOST=127.0.0.1",
        f"MILAI_BIND_PORT={api_port}",
        f"MILAI_BASE_URL=http://127.0.0.1:{api_port}",
        "MILAI_DATA_MODE=SYNTHETIC_ONLY",
        "MILAI_BLOB_ENCRYPTION=AES_256_GCM",
        f"MILAI_BLOB_KEK_B64={blob_kek}",
        "MILAI_BLOB_KEY_REFERENCE=local-kek-v1",
        "MILAI_BACKUP_KEY_RECOVERY_CONFIRMED=false",
        (
            "MILAI_EMBEDDING_PROVIDER=onnx_sentence_transformer"
            if real_model_ready
            else "MILAI_EMBEDDING_PROVIDER=deterministic_hash"
        ),
        (
            "MILAI_EMBEDDING_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2"
            if real_model_ready
            else "MILAI_EMBEDDING_MODEL_ID=deterministic-hash-v1"
        ),
        f"MILAI_EMBEDDING_SOURCE_DIMENSIONS={384 if real_model_ready else 16}",
        *([f"MILAI_EMBEDDING_MODEL_PATH={model_path}"] if real_model_ready else []),
        "MILAI_LOG_LEVEL=INFO",
        "MILAI_LOG_FORMAT=json",
        "",
    ]
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SettingsError("environment file already exists; init never overwrites it") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "status": "INITIALIZED",
        "env_file": str(target),
        "mode": "0600",
        "data_mode": "SYNTHETIC_ONLY",
        "embedding_provider": (
            "onnx_sentence_transformer" if real_model_ready else "deterministic_hash"
        ),
        "next": ["uv sync --frozen --dev --extra embedding", "milai-ops doctor --json"],
    }


def _api_json(path: str, token: str) -> dict[str, object]:
    base = os.environ.get("MILAI_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
    parsed = urlsplit(base)
    try:
        loopback = (
            parsed.hostname == "localhost"
            or ipaddress.ip_address(parsed.hostname or "").is_loopback
        )
    except ValueError:
        loopback = False
    if parsed.scheme != "http" or not loopback or parsed.username or parsed.password:
        raise SettingsError("MILAI_BASE_URL must be an unauthenticated loopback HTTP URL")
    request = Request(  # noqa: S310 -- exact http + loopback validation above
        f"{base}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urlopen(request, timeout=3) as response:  # noqa: S310 -- validated above
            body = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SettingsError(f"local API check failed: {type(exc).__name__}") from exc
    if not isinstance(body, dict):
        raise SettingsError("local API returned an invalid response")
    return body


def _runtime_status() -> dict[str, object]:
    settings = load_settings()
    token = (settings.agent_reader_token or settings.api_token).get_secret_value()
    live = _api_json("/health/live", token)
    ready = _api_json("/health/ready", token)
    capabilities = _api_json("/v1/capabilities", token)
    watermarks = _api_json("/v1/system/watermarks", token)
    degraded_routes = _api_json("/v1/system/degraded-routes", token)
    processes = managed_process_status()
    worker = processes.get("worker")
    status = (
        "BLOCKED"
        if isinstance(worker, dict) and worker.get("alive") is False
        else "PASS"
    )
    return {
        "status": status,
        "live": live,
        "ready": ready,
        "managed_processes": processes,
        "watermarks": watermarks,
        "degraded_routes": degraded_routes,
        "capabilities": capabilities,
    }


def _agent_config(
    profile: str,
    *,
    transport: str = "stdio",
    url: str = "http://127.0.0.1:7337/mcp",
) -> dict[str, object]:
    if transport == "streamable-http":
        if profile != "agent-memory":
            raise SettingsError("Streamable HTTP config requires profile agent-memory")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SettingsError("Streamable HTTP MCP URL must be an HTTP(S) URL")
        return {
            "status": "CONFIG_READY",
            "transport": "streamable-http",
            "mcpServers": {
                "milai": {
                    "url": url,
                    "bearer_token_env_var": "MILAI_MCP_HTTP_BEARER_TOKEN",
                    "enabled": True,
                    "required": True,
                    "startup_timeout_sec": 10,
                    "tool_timeout_sec": 60,
                    "enabled_tools": ["milai_memory_resolve"],
                }
            },
        }
    if transport != "stdio":
        raise SettingsError("unsupported MCP transport")
    token_profile = (
        "reader" if profile in {"agent-memory", "reader-lite", "reader-detail"} else profile
    )
    token_variable = f"MILAI_AGENT_{token_profile.upper()}_TOKEN"
    return {
        "status": "CONFIG_READY",
        "mcpServers": {
            "milai": {
                "command": "milai-mcp",
                "args": ["--profile", profile, "--max-retries", "0"],
                "env": {
                    "MILAI_BASE_URL": os.environ.get("MILAI_BASE_URL", "http://127.0.0.1:18080"),
                    "MILAI_AGENT_TOKEN": "${" + token_variable + "}",
                    "MILAI_AGENT_SCOPE_JSON": "${MILAI_AGENT_SCOPE_JSON}",
                    "MILAI_AGENT_REQUIRED_AUTHORITY": "INFORMATIONAL",
                    "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
                    "MILAI_AGENT_MAX_LIMIT": "3",
                },
            }
        },
    }


def _rotate_blob_key(
    settings: object,
    *,
    new_key_reference: str,
    new_kek_env: str,
    confirmation: str,
) -> dict[str, object]:
    from milai.adapters import LocalContentAddressedBlobStore
    from milai.config import RuntimeSettings

    if confirmation != "ROTATE_BLOB_KEY":
        raise SettingsError("key rotation requires explicit ROTATE_BLOB_KEY confirmation")
    if not isinstance(settings, RuntimeSettings) or settings.blob_kek is None:
        raise SettingsError("current encrypted Blob settings are required")
    raw = _required_environment(new_kek_env)
    try:
        new_kek = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise SettingsError("new KEK must be valid base64") from exc
    if len(new_kek) != 32 or new_kek == settings.blob_kek:
        raise SettingsError("new KEK must be a distinct 32-byte key")
    store = LocalContentAddressedBlobStore(
        settings.blob_root,
        kek=settings.blob_kek,
        key_reference=settings.blob_key_reference,
        allow_plaintext_read=settings.data_mode != "LOCAL_PERSONAL_DATA",
    )
    return store.rotate_tenant_key(
        settings.tenant_id,
        new_kek=new_kek,
        new_key_reference=new_key_reference,
    )


def _rebuild_projection(
    tenant_id: object,
    actor_id: object,
    projection: str,
    confirmation: str,
    database_url: str,
) -> dict[str, object]:
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, true)", (str(tenant_id),))
        connection.execute("SELECT set_config('milai.actor_id', %s, true)", (str(actor_id),))
        row = connection.execute(
            "SELECT milai.rebuild_search_projection(%s, %s, %s, %s)",
            (tenant_id, actor_id, projection, confirmation),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise BackupError("projection rebuild returned no result")
    return row[0]
