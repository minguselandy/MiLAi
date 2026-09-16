from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from milai.config import SettingsError
from milai.operations import credential_rotation, load_runtime_environment, local_runtime
from milai.operations.cli import _agent_config, _initialize_environment, _parser
from milai.operations.smoke import _database_url, _drop_database


def _rotation_environment() -> str:
    password = "old-password"
    lines = [
        *(
            f"MILAI_{name}_DB_PASSWORD={password}-{name.lower()}"
            for name in credential_rotation._PASSWORD_NAMES
        ),
        *(
            f"{name}=old-{name.lower()}-with-at-least-32-characters"
            for name in credential_rotation._TOKEN_NAMES
        ),
        "MILAI_DATABASE_URL=postgresql://milai_api:old@127.0.0.1:15432/milai",
        "MILAI_STEWARD_DATABASE_URL=postgresql://milai_steward:old@127.0.0.1:15432/milai",
        "MILAI_WORKER_DATABASE_URL=postgresql://milai_worker:old@127.0.0.1:15432/milai",
        "MILAI_MIGRATION_DATABASE_URL=postgresql://milai_owner:old@127.0.0.1:15432/milai",
        "MILAI_AUDIT_DATABASE_URL=postgresql://milai_audit:old@127.0.0.1:15432/milai",
        "MILAI_BLOB_KEK_B64=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "MILAI_BLOB_KEY_REFERENCE=local-kek-old",
        "MILAI_BIND_PORT=18080",
        "",
    ]
    return "\n".join(lines)


class _RotationConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[Any, Any]] = []

    def __enter__(self) -> _RotationConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: Any, parameters: Any = None) -> Any:
        self.executed.append((query, parameters))
        if query == "SELECT current_user":
            return SimpleNamespace(fetchone=lambda: ("milai_owner",))
        return SimpleNamespace(fetchone=lambda: None)


def test_init_is_private_distinct_and_never_overwrites(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime" / ".env"
    result = _initialize_environment(env_file, "./var/blobs")
    content = env_file.read_text(encoding="utf-8")
    assert result["status"] == "INITIALIZED"
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert "SYNTHETIC_ONLY" in content
    assert "replace-with" not in content
    assert "MILAI_AGENT_READER_TOKEN=" in content
    assert "MILAI_AGENT_REVIEWER_TOKEN=" in content
    assert "MILAI_API_TOKEN" not in repr(result)
    with pytest.raises(SettingsError, match="never overwrites"):
        _initialize_environment(env_file, "./var/blobs")


def test_env_loader_does_not_override_host_environment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MILAI_BIND_PORT=19000\n", encoding="utf-8")
    previous = os.environ.get("MILAI_BIND_PORT")
    os.environ["MILAI_BIND_PORT"] = "18080"
    try:
        load_runtime_environment(env_file)
        assert os.environ["MILAI_BIND_PORT"] == "18080"
    finally:
        if previous is None:
            os.environ.pop("MILAI_BIND_PORT", None)
        else:
            os.environ["MILAI_BIND_PORT"] = previous


def test_agent_config_contains_reference_not_secret() -> None:
    config = _agent_config("reader-lite")
    serialized = repr(config)
    assert "${MILAI_AGENT_READER_TOKEN}" in serialized
    assert "MILAI_AGENT_CONSISTENCY_FLOOR" in serialized
    assert "MILAI_AGENT_MAX_LIMIT" in serialized
    assert "'3'" in serialized
    assert "reader-lite" in serialized
    assert "proposal_review" not in serialized
    server = config["mcpServers"]["milai"]  # type: ignore[index]
    assert server["command"] == "milai-mcp"  # type: ignore[index]
    assert server["args"] == [  # type: ignore[index]
        "--profile",
        "reader-lite",
        "--max-retries",
        "0",
    ]


def test_agent_config_cli_can_provision_reviewer_profile() -> None:
    parsed = _parser().parse_args(["agent-config", "--profile", "reviewer"])
    assert parsed.profile == "reviewer"
    config = _agent_config(parsed.profile)
    serialized = repr(config)
    assert "${MILAI_AGENT_REVIEWER_TOKEN}" in serialized
    server = config["mcpServers"]["milai"]  # type: ignore[index]
    assert server["args"] == [  # type: ignore[index]
        "--profile",
        "reviewer",
        "--max-retries",
        "0",
    ]


def test_smoke_database_helpers_reject_non_ephemeral_target() -> None:
    result = _drop_database(
        "postgresql://milai_owner:secret@127.0.0.1:15432/milai",
        "milai",
    )
    assert result == {"status": "BLOCKED", "reason": "UNSAFE_SMOKE_DATABASE_NAME"}
    changed = _database_url(
        "postgresql://milai_api:secret@127.0.0.1:15432/milai",
        "milai_smoke_1234",
    )
    assert changed.endswith("/milai_smoke_1234")


def test_local_child_environments_remove_owner_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MILAI_MIGRATION_DATABASE_URL", "owner-secret")
    monkeypatch.setenv("MILAI_OWNER_DB_PASSWORD", "owner-secret")
    monkeypatch.setenv("MILAI_AUDIT_DATABASE_URL", "audit-secret")
    monkeypatch.setenv("MILAI_WORKER_DATABASE_URL", "worker-secret")
    api = local_runtime._safe_child_environment(worker=False)
    worker = local_runtime._safe_child_environment(worker=True)
    for environment in (api, worker):
        assert "MILAI_MIGRATION_DATABASE_URL" not in environment
        assert "MILAI_OWNER_DB_PASSWORD" not in environment
        assert "MILAI_AUDIT_DATABASE_URL" not in environment
    assert "MILAI_WORKER_DATABASE_URL" not in api
    assert worker["MILAI_WORKER_DATABASE_URL"] == "worker-secret"


def test_exposure_rotation_is_private_complete_and_secret_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    original = _rotation_environment()
    env_file.write_text(original, encoding="utf-8")
    env_file.chmod(0o600)
    connection = _RotationConnection()
    monkeypatch.setattr(
        credential_rotation,
        "load_settings",
        lambda _values: SimpleNamespace(
            bind_host="127.0.0.1",
            bind_port=18080,
            blob_kek=b"o" * 32,
            blob_key_reference="local-kek-old",
        ),
    )
    monkeypatch.setattr(credential_rotation, "local_profile_running", lambda *_args: False)
    monkeypatch.setattr(credential_rotation, "_rotate_blob_material", lambda *_args: None)
    monkeypatch.setattr(
        credential_rotation.psycopg, "connect", lambda *_args, **_kwargs: connection
    )
    monkeypatch.setattr(
        credential_rotation,
        "_verify_database_credentials",
        lambda _values: [
            "milai_api",
            "milai_audit",
            "milai_owner",
            "milai_steward",
            "milai_worker",
        ],
    )
    monkeypatch.setattr(
        credential_rotation,
        "_verify_old_database_credentials_rejected",
        lambda _values: True,
    )

    result = credential_rotation.rotate_local_credentials(
        env_file,
        confirmation="ROTATE_EXPOSED_LOCAL_CREDENTIALS",
    )
    rotated = env_file.read_text(encoding="utf-8")
    assert result["status"] == "ROTATED"
    assert result["secret_values_emitted"] is False
    assert result["old_environment_backup_retained"] is False
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert rotated != original
    assert "old-password" not in rotated
    assert "old-milai_" not in rotated
    assert len([item for item in connection.executed if item[0] != "SELECT current_user"]) == 5


def test_exposure_rotation_requires_stopped_runtime_and_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    original = _rotation_environment()
    env_file.write_text(original, encoding="utf-8")
    env_file.chmod(0o600)
    with pytest.raises(SettingsError, match="requires"):
        credential_rotation.rotate_local_credentials(env_file, confirmation="NO")
    monkeypatch.setattr(
        credential_rotation,
        "load_settings",
        lambda _values: SimpleNamespace(
            bind_host="127.0.0.1",
            bind_port=18080,
            blob_kek=b"o" * 32,
        ),
    )
    monkeypatch.setattr(credential_rotation, "local_profile_running", lambda *_args: True)
    with pytest.raises(SettingsError, match="stop"):
        credential_rotation.rotate_local_credentials(
            env_file,
            confirmation="ROTATE_EXPOSED_LOCAL_CREDENTIALS",
        )
    assert env_file.read_text(encoding="utf-8") == original
