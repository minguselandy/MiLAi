from __future__ import annotations

import base64
import os
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from milai.adapters import LocalContentAddressedBlobStore
from milai.config import RuntimeSettings, SettingsError, load_settings
from milai.operations.local_runtime import local_profile_running

_PASSWORD_NAMES = ("OWNER", "API", "STEWARD", "WORKER", "AUDIT")
_TOKEN_NAMES = (
    "MILAI_API_TOKEN",
    "MILAI_CAUSAL_TOKEN_SECRET",
    "MILAI_AGENT_READER_TOKEN",
    "MILAI_AGENT_SUBMITTER_TOKEN",
    "MILAI_AGENT_OPERATOR_TOKEN",
    "MILAI_AGENT_REVIEWER_TOKEN",
)
_URL_ROLES = {
    "MILAI_DATABASE_URL": ("milai_api", "API"),
    "MILAI_STEWARD_DATABASE_URL": ("milai_steward", "STEWARD"),
    "MILAI_WORKER_DATABASE_URL": ("milai_worker", "WORKER"),
    "MILAI_MIGRATION_DATABASE_URL": ("milai_owner", "OWNER"),
    "MILAI_AUDIT_DATABASE_URL": ("milai_audit", "AUDIT"),
}


def rotate_local_credentials(
    env_file: Path,
    *,
    confirmation: str,
) -> dict[str, object]:
    """Rotate an exposed local profile without emitting or retaining secret values."""
    if confirmation != "ROTATE_EXPOSED_LOCAL_CREDENTIALS":
        raise SettingsError(
            "credential rotation requires ROTATE_EXPOSED_LOCAL_CREDENTIALS confirmation"
        )
    target = env_file.expanduser().resolve(strict=True)
    if target.is_symlink() or not target.is_file():
        raise SettingsError("environment file must be a regular non-symlink file")
    if target.stat().st_mode & 0o077:
        raise SettingsError("environment file must not be readable by group or others")

    original_text = target.read_text(encoding="utf-8")
    original = _parse_environment(original_text)
    required = {
        *(f"MILAI_{name}_DB_PASSWORD" for name in _PASSWORD_NAMES),
        *_TOKEN_NAMES,
        *_URL_ROLES,
        "MILAI_BLOB_KEK_B64",
        "MILAI_BLOB_KEY_REFERENCE",
    }
    missing = sorted(required - original.keys())
    if missing:
        raise SettingsError("environment file is missing required rotation fields")
    settings = load_settings(original)
    if local_profile_running(settings.bind_host, settings.bind_port):
        raise SettingsError("stop the local Runtime before rotating credentials")
    if settings.blob_kek is None:
        raise SettingsError("encrypted Blob KEK is required for credential rotation")

    passwords = {name: secrets.token_urlsafe(36) for name in _PASSWORD_NAMES}
    tokens = {name: secrets.token_urlsafe(48) for name in _TOKEN_NAMES}
    new_kek = secrets.token_bytes(32)
    new_reference = f"local-kek-{secrets.token_hex(8)}"
    replacements = {
        **{f"MILAI_{name}_DB_PASSWORD": value for name, value in passwords.items()},
        **tokens,
        "MILAI_BLOB_KEK_B64": base64.b64encode(new_kek).decode("ascii"),
        "MILAI_BLOB_KEY_REFERENCE": new_reference,
    }
    for variable, (role, password_name) in _URL_ROLES.items():
        replacements[variable] = _replace_url_credentials(
            original[variable], role, passwords[password_name]
        )
    rotated_text = _replace_environment_values(original_text, replacements)

    blob_rotated = False
    try:
        _rotate_blob_material(settings, new_kek, new_reference)
        blob_rotated = True
        with psycopg.connect(original["MILAI_MIGRATION_DATABASE_URL"]) as connection:
            current = connection.execute("SELECT current_user").fetchone()
            if current is None or current[0] != "milai_owner":
                raise SettingsError("credential rotation requires the exact milai_owner role")
            for role, password_name in (
                ("milai_api", "API"),
                ("milai_steward", "STEWARD"),
                ("milai_worker", "WORKER"),
                ("milai_audit", "AUDIT"),
                ("milai_owner", "OWNER"),
            ):
                connection.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(passwords[password_name])
                    )
                )
            _atomic_replace(target, rotated_text)
    except Exception as exc:
        _atomic_replace(target, original_text)
        if blob_rotated:
            try:
                _rotate_blob_material_back(settings, new_kek, new_reference)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic I/O failure
                raise SettingsError(
                    "credential rotation failed and Blob key rollback also failed"
                ) from rollback_exc
        if isinstance(exc, SettingsError):
            raise
        raise SettingsError("credential rotation failed without exposing details") from exc

    rotated = _parse_environment(rotated_text)
    verified_roles = _verify_database_credentials(rotated)
    old_rejected = _verify_old_database_credentials_rejected(original)
    return {
        "status": "ROTATED",
        "env_file": str(target),
        "mode": "0600",
        "database_roles_verified": verified_roles,
        "old_database_credentials_rejected": old_rejected,
        "tokens_rotated": 6,
        "blob_key_reference": new_reference,
        "old_api_tokens_require_post_restart_rejection_check": True,
        "secret_values_emitted": False,
        "old_environment_backup_retained": False,
    }


def _parse_environment(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name in values:
            raise SettingsError("environment file contains duplicate variable names")
        if name.startswith("MILAI_"):
            values[name] = value
    return values


def _replace_environment_values(text: str, replacements: Mapping[str, str]) -> str:
    found: set[str] = set()
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        name = stripped.split("=", 1)[0] if "=" in stripped else ""
        if name in replacements:
            if name in found:
                raise SettingsError("environment file contains duplicate rotation fields")
            lines.append(f"{name}={replacements[name]}")
            found.add(name)
        else:
            lines.append(raw)
    if found != set(replacements):
        raise SettingsError("environment file is missing a requested rotation field")
    return "\n".join(lines) + "\n"


def _replace_url_credentials(value: str, expected_role: str, password: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.username != expected_role:
        raise SettingsError("database URL does not use the expected local role")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SettingsError("credential rotation only supports loopback PostgreSQL")
    host = f"[{parsed.hostname}]" if ":" in (parsed.hostname or "") else parsed.hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{quote(expected_role, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _atomic_replace(target: Path, content: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".env.rotation-", dir=target.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _rotate_blob_material(settings: RuntimeSettings, new_kek: bytes, new_reference: str) -> None:
    store = LocalContentAddressedBlobStore(
        settings.blob_root,
        kek=settings.blob_kek,
        key_reference=settings.blob_key_reference,
        allow_plaintext_read=settings.data_mode != "LOCAL_PERSONAL_DATA",
    )
    store.rotate_tenant_key(
        settings.tenant_id,
        new_kek=new_kek,
        new_key_reference=new_reference,
    )


def _rotate_blob_material_back(
    settings: RuntimeSettings, new_kek: bytes, new_reference: str
) -> None:
    store = LocalContentAddressedBlobStore(
        settings.blob_root,
        kek=new_kek,
        key_reference=new_reference,
        allow_plaintext_read=False,
    )
    assert settings.blob_kek is not None
    store.rotate_tenant_key(
        settings.tenant_id,
        new_kek=settings.blob_kek,
        new_key_reference=settings.blob_key_reference,
    )


def _verify_database_credentials(values: Mapping[str, str]) -> list[str]:
    verified: list[str] = []
    for variable, (role, _password_name) in _URL_ROLES.items():
        with psycopg.connect(values[variable], connect_timeout=3) as connection:
            current = connection.execute("SELECT current_user").fetchone()
        if current is None or current[0] != role:
            raise SettingsError("rotated database credential role verification failed")
        verified.append(role)
    return sorted(verified)


def _verify_old_database_credentials_rejected(values: Mapping[str, str]) -> bool:
    for variable in _URL_ROLES:
        try:
            with psycopg.connect(values[variable], connect_timeout=2):
                pass
        except psycopg.OperationalError:
            continue
        raise SettingsError("an old database credential remained valid after rotation")
    return True
