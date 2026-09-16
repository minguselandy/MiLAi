from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from milai import IMPLEMENTATION_STATUS, SCHEMA_FREEZE_STATUS, SCHEMA_STATUS
from milai.config import RuntimeSettings

_FORMAT_VERSION = "milai-backup-v1"
_INVENTORY_TABLES = (
    "backup_deletion_obligation",
    "backup_manifest",
    "chat_turn",
    "content_blob",
    "evidence_record",
    "claim",
    "claim_version",
    "claim_head",
    "version_transition",
    "grounding_relation",
    "grounding_block",
    "operation_proposal",
    "steward_decision",
    "open_issue",
    "open_issue_transition",
    "legacy_issue_transition_quarantine",
    "legacy_grounding_relation_quarantine",
    "idempotency_record",
    "episode",
    "episode_settlement",
    "episode_transition",
    "context_capsule",
    "context_pointer",
    "outbox_event",
    "projection_delivery",
    "index_watermark",
    "search_document",
    "search_document_fragment",
    "search_embedding",
    "search_embedding_window_128",
    "evidence_search_document",
    "evidence_dense_embedding_128",
    "host_cognitive_state",
    "host_cognitive_state_version",
    "host_cognitive_state_evidence_ref",
    "host_note",
    "host_note_version",
    "host_note_evidence_ref",
    "host_execution_event",
    "host_execution_event_evidence_ref",
    "retrieval_continuation_state",
    "namespace_cleanup_job",
    "namespace_cleanup_item",
    "retrieval_trace",
    "operational_event",
    "deletion_request",
)
_ONLINE_ROLES = ("milai_api", "milai_steward", "milai_worker")


class BackupError(RuntimeError):
    """Safe operational backup/restore failure without embedded credentials."""


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    root: Path
    manifest: dict[str, Any]


def create_backup(
    settings: RuntimeSettings,
    output: Path,
    *,
    owner_database_url: str,
    audit_database_url: str,
    require_quiescent: bool = True,
) -> dict[str, Any]:
    destination = _new_archive_path(output)
    parent = destination.parent
    temporary = Path(tempfile.mkdtemp(prefix=".milai-backup-", dir=parent))
    backup_id = uuid4()
    try:
        dump_path = temporary / "database.dump"
        blob_target = temporary / "blobs"
        with psycopg.connect(owner_database_url) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if require_quiescent:
                _assert_quiescent(connection)
            _assert_single_tenant(connection, settings.tenant_id)
            _lock_tables(connection)
            snapshot_id = str(
                _scalar(connection.execute("SELECT pg_export_snapshot()").fetchone(), "snapshot")
            )
            snapshot_value = _scalar(
                connection.execute("SELECT transaction_timestamp()").fetchone(),
                "snapshot timestamp",
            )
            if not isinstance(snapshot_value, datetime):
                raise BackupError("database returned an invalid snapshot timestamp")
            snapshot_at = snapshot_value
            revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision_row is None:
                raise BackupError("database has no Alembic revision")
            revision = str(revision_row[0])
            inventory = _database_inventory(connection, settings.tenant_id)
            _run_pg_dump(owner_database_url, snapshot_id, dump_path)
            _copy_blob_tree(settings.blob_root, blob_target)

        blob_files = _file_manifest(blob_target)
        blob_manifest_hash = _json_hash(blob_files)
        inventory_hash = _json_hash(inventory)
        dump_hash = _file_hash(dump_path)
        content_hashes = sorted({str(item["sha256"]) for item in blob_files})
        core = {
            "format_version": _FORMAT_VERSION,
            "backup_id": str(backup_id),
            "tenant_id": str(settings.tenant_id),
            "snapshot_at": snapshot_at.isoformat(),
            "alembic_revision": revision,
            "schema_status": SCHEMA_STATUS,
            "implementation_status": IMPLEMENTATION_STATUS,
            "schema_freeze": SCHEMA_FREEZE_STATUS,
            "data_mode": settings.data_mode,
            "blob_encryption": {
                "algorithm": settings.blob_encryption,
                "key_reference": settings.blob_key_reference,
                "key_material_included": False,
                "recovery_confirmed_at_backup": settings.backup_key_recovery_confirmed,
            },
            "database_dump": {"path": "database.dump", "sha256": dump_hash},
            "blob_root": {"path": "blobs", "manifest_sha256": blob_manifest_hash},
            "blob_files": blob_files,
            "inventory": inventory,
            "inventory_sha256": inventory_hash,
        }
        core["consistency_fingerprint"] = _json_hash(core)
        (temporary / "manifest.json").write_text(
            json.dumps(core, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(destination)
        try:
            _record_manifest(
                audit_database_url,
                settings.tenant_id,
                settings.local_actor_id,
                backup_id,
                snapshot_at,
                destination.name,
                dump_hash,
                blob_manifest_hash,
                inventory_hash,
                content_hashes,
                inventory,
            )
        except Exception:
            shutil.rmtree(destination)
            raise
        return core
    except BackupError:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    except Exception as exc:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise BackupError("backup creation failed") from exc


def verify_backup(archive: Path) -> VerifiedBackup:
    root = archive.expanduser().resolve(strict=True)
    if not root.is_dir() or root == Path("/") or root == Path.home().resolve():
        raise BackupError("backup archive path is unsafe")
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("backup manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != _FORMAT_VERSION:
        raise BackupError("backup format is unsupported")
    expected_fingerprint = manifest.get("consistency_fingerprint")
    fingerprint_input = dict(manifest)
    fingerprint_input.pop("consistency_fingerprint", None)
    if expected_fingerprint != _json_hash(fingerprint_input):
        raise BackupError("backup consistency fingerprint mismatch")
    dump = manifest.get("database_dump")
    blob_files = manifest.get("blob_files")
    if not isinstance(dump, dict) or not isinstance(blob_files, list):
        raise BackupError("backup manifest shape is invalid")
    dump_path = _contained_path(root, str(dump.get("path", "")))
    if _file_hash(dump_path) != dump.get("sha256"):
        raise BackupError("database dump hash mismatch")
    actual_files = _file_manifest(root / "blobs")
    if actual_files != blob_files:
        raise BackupError("blob file manifest mismatch")
    blob_root = manifest.get("blob_root")
    if not isinstance(blob_root, dict) or blob_root.get("manifest_sha256") != _json_hash(
        actual_files
    ):
        raise BackupError("blob manifest hash mismatch")
    if manifest.get("inventory_sha256") != _json_hash(manifest.get("inventory")):
        raise BackupError("database inventory hash mismatch")
    try:
        subprocess.run(  # noqa: S603 -- fixed PostgreSQL tool and contained archive path
            [_postgres_tool("pg_restore"), "--list", str(dump_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("database dump cannot be listed") from exc
    return VerifiedBackup(root, manifest)


def restore_backup(
    archive: Path,
    target_blob_root: Path,
    *,
    target_database_url: str,
    confirm_empty_target: bool,
) -> dict[str, Any]:
    if not confirm_empty_target:
        raise BackupError("restore requires explicit empty-target confirmation")
    verified = verify_backup(archive)
    target_root = target_blob_root.expanduser().resolve(strict=False)
    if target_root in {Path("/"), Path.home().resolve()}:
        raise BackupError("restore blob root is unsafe")
    if target_root.exists() and any(target_root.iterdir()):
        raise BackupError("restore blob root must be empty")
    tenant_id = UUID(str(verified.manifest["tenant_id"]))
    try:
        with psycopg.connect(target_database_url) as connection:
            existing = _scalar(
                connection.execute(
                    """
                    SELECT count(*) FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    """
                ).fetchone(),
                "target table count",
            )
            if int(existing) != 0:
                raise BackupError("restore database must be empty")
        _run_pg_restore(target_database_url, verified.root / "database.dump")
        target_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copytree(verified.root / "blobs", target_root, dirs_exist_ok=True)
        with psycopg.connect(target_database_url) as connection:
            actual_inventory = _database_inventory(connection, tenant_id)
            revision = str(
                _scalar(
                    connection.execute("SELECT version_num FROM alembic_version").fetchone(),
                    "restored Alembic revision",
                )
            )
        if actual_inventory != verified.manifest["inventory"]:
            raise BackupError("restored canonical inventory does not match manifest")
        if revision != verified.manifest["alembic_revision"]:
            raise BackupError("restored Alembic revision does not match manifest")
        if _file_manifest(target_root) != verified.manifest["blob_files"]:
            raise BackupError("restored blob inventory does not match manifest")
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("restore failed") from exc
    return {
        "backup_id": verified.manifest["backup_id"],
        "tenant_id": str(tenant_id),
        "alembic_revision": revision,
        "inventory_sha256": verified.manifest["inventory_sha256"],
        "status": "RESTORED_AND_RECONCILED",
    }


def expire_backup(
    settings: RuntimeSettings,
    archive: Path,
    *,
    audit_database_url: str,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != "ERASE_BACKUP_ARCHIVE":
        raise BackupError("backup erasure requires explicit confirmation")
    verified = verify_backup(archive)
    if verified.manifest.get("tenant_id") != str(settings.tenant_id):
        raise BackupError("backup tenant does not match runtime tenant")
    backup_id = UUID(str(verified.manifest["backup_id"]))
    shutil.rmtree(verified.root)
    try:
        return _expire_manifest(
            audit_database_url, settings.tenant_id, settings.local_actor_id, backup_id
        )
    except Exception as exc:
        raise BackupError(
            f"archive erased but manifest reconciliation failed for backup {backup_id}"
        ) from exc


def _new_archive_path(path: Path) -> Path:
    value = path.expanduser().resolve(strict=False)
    if value in {Path("/"), Path.home().resolve()} or value.exists():
        raise BackupError("backup destination must be a new, narrow path")
    value.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return value


def _scalar(row: tuple[Any, ...] | None, label: str) -> Any:
    if row is None:
        raise BackupError(f"database returned no {label}")
    return row[0]


def _assert_quiescent(connection: Any) -> None:
    rows = connection.execute(
        """
        SELECT usename, count(*)
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND usename = ANY(%s)
        GROUP BY usename
        """,
        (list(_ONLINE_ROLES),),
    ).fetchall()
    if rows:
        raise BackupError("API, Steward, and Worker sessions must be stopped before backup")


def _assert_single_tenant(connection: Any, tenant_id: UUID) -> None:
    _assert_inventory_coverage(connection)
    for table in _INVENTORY_TABLES:
        statement = sql.SQL("SELECT count(*) FROM {} WHERE tenant_id IS DISTINCT FROM %s").format(
            sql.Identifier("milai", table)
        )
        foreign_rows = _scalar(
            connection.execute(statement, (tenant_id,)).fetchone(),
            f"foreign tenant count for {table}",
        )
        if int(foreign_rows) > 0:
            raise BackupError("local backup requires a single-tenant database")


def _assert_inventory_coverage(connection: Any) -> None:
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables item
        WHERE item.table_schema = 'milai' AND item.table_type = 'BASE TABLE'
          AND EXISTS (
            SELECT 1 FROM information_schema.columns column_info
            WHERE column_info.table_schema = item.table_schema
              AND column_info.table_name = item.table_name
              AND column_info.column_name = 'tenant_id'
          )
        ORDER BY table_name
        """
    ).fetchall()
    discovered = {str(row[0]) for row in rows}
    configured = set(_INVENTORY_TABLES)
    if discovered != configured:
        raise BackupError("backup inventory does not cover every tenant-owned table")


def _lock_tables(connection: Any) -> None:
    rows = connection.execute(
        """
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'milai'
        ORDER BY tablename
        """
    ).fetchall()
    if rows:
        statement = sql.SQL("LOCK TABLE {} IN SHARE MODE").format(
            sql.SQL(", ").join(sql.Identifier("milai", str(row[0])) for row in rows)
        )
        connection.execute(statement)


def _database_inventory(connection: Any, tenant_id: UUID) -> dict[str, Any]:
    _assert_inventory_coverage(connection)
    tables: dict[str, dict[str, object]] = {}
    for table in _INVENTORY_TABLES:
        statement = sql.SQL(
            "SELECT to_jsonb(item)::text FROM {} item "
            "WHERE tenant_id = %s ORDER BY to_jsonb(item)::text"
        ).format(sql.Identifier("milai", table))
        rows = connection.execute(
            statement,
            (tenant_id,),
        ).fetchall()
        digest = hashlib.sha256()
        for row in rows:
            digest.update(str(row[0]).encode("utf-8"))
            digest.update(b"\n")
        tables[table] = {"count": len(rows), "sha256": digest.hexdigest()}
    return {"tenant_id": str(tenant_id), "tables": tables}


def _copy_blob_tree(source: Path, destination: Path) -> None:
    root = source.expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise BackupError("blob root is unavailable")
    shutil.copytree(root, destination)


def _file_manifest(root: Path) -> list[dict[str, object]]:
    if not root.is_dir():
        raise BackupError("blob archive is missing")
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BackupError("blob archive contains a symbolic link")
        if path.is_file():
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _file_hash(path),
                }
            )
    return result


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise BackupError("backup file is unreadable") from exc
    return digest.hexdigest()


def _json_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _contained_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve(strict=True)
    if path.parent != root and root not in path.parents:
        raise BackupError("backup manifest path escapes the archive")
    return path


def _postgres_tool(name: str) -> str:
    candidates = sorted(
        Path("/usr/lib/postgresql").glob(f"*/bin/{name}"),
        key=lambda item: tuple(
            int(part) if part.isdigit() else 0 for part in item.parts[-3].split(".")
        ),
        reverse=True,
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve(strict=True))
    executable = shutil.which(name)
    if executable is None:
        raise BackupError(f"required PostgreSQL tool is unavailable: {name}")
    path = Path(executable).resolve(strict=True)
    if not path.is_file():
        raise BackupError(f"PostgreSQL tool path is invalid: {name}")
    return str(path)


def _libpq_environment(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise BackupError("database URL is invalid")
    result = dict(os.environ)
    result.update(
        {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": unquote(parsed.username or ""),
            "PGDATABASE": parsed.path.lstrip("/"),
        }
    )
    if parsed.password is not None:
        result["PGPASSWORD"] = unquote(parsed.password)
    return result


def _run_pg_dump(database_url: str, snapshot_id: str, output: Path) -> None:
    try:
        subprocess.run(  # noqa: S603 -- fixed PostgreSQL tool and generated output path
            [
                _postgres_tool("pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-acl",
                f"--snapshot={snapshot_id}",
                f"--file={output}",
            ],
            env=_libpq_environment(database_url),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("pg_dump failed") from exc


def _run_pg_restore(database_url: str, dump: Path) -> None:
    database_name = urlsplit(database_url).path.lstrip("/")
    try:
        subprocess.run(  # noqa: S603 -- fixed PostgreSQL tool and verified dump path
            [
                _postgres_tool("pg_restore"),
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                f"--dbname={database_name}",
                str(dump),
            ],
            env=_libpq_environment(database_url),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("pg_restore failed") from exc


def _record_manifest(
    audit_url: str,
    tenant_id: UUID,
    actor_id: UUID,
    backup_id: UUID,
    snapshot_at: datetime,
    archive_name: str,
    dump_hash: str,
    blob_hash: str,
    inventory_hash: str,
    content_hashes: list[str],
    inventory: dict[str, Any],
) -> None:
    with psycopg.connect(audit_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, true)", (str(tenant_id),))
        connection.execute("SELECT set_config('milai.actor_id', %s, true)", (str(actor_id),))
        connection.execute(
            "SELECT milai.record_backup_manifest(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                actor_id,
                backup_id,
                snapshot_at,
                archive_name,
                dump_hash,
                blob_hash,
                inventory_hash,
                Jsonb(content_hashes),
                Jsonb(inventory),
            ),
        ).fetchone()


def _expire_manifest(
    audit_url: str, tenant_id: UUID, actor_id: UUID, backup_id: UUID
) -> dict[str, Any]:
    with psycopg.connect(audit_url) as connection:
        connection.execute("SELECT set_config('milai.tenant_id', %s, true)", (str(tenant_id),))
        connection.execute("SELECT set_config('milai.actor_id', %s, true)", (str(actor_id),))
        row = connection.execute(
            "SELECT milai.expire_backup_manifest(%s, %s, %s, 'ARCHIVE_ERASED')",
            (tenant_id, actor_id, backup_id),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise BackupError("backup expiry returned no result")
    return row[0]
