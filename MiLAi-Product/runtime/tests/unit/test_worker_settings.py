from __future__ import annotations

from pathlib import Path

import pytest

from milai.config.settings import WORKER_ENV_ALLOWLIST, SettingsError, load_worker_settings
from milai.workers.main import _worker_dsn


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "MILAI_WORKER_DATABASE_URL": (
            "postgresql://milai_worker:secret@127.0.0.1:15432/milai"
        ),
        "MILAI_BLOB_ROOT": str(tmp_path / "blobs"),
        "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }


def test_worker_requires_a_separate_database_url(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment.pop("MILAI_WORKER_DATABASE_URL")
    with pytest.raises(SettingsError, match="worker_database_url"):
        load_worker_settings(environment)


def test_worker_uses_its_dedicated_database_url(tmp_path: Path) -> None:
    settings = load_worker_settings(_environment(tmp_path))
    assert _worker_dsn(settings).startswith("postgresql://milai_worker:")
    assert settings.database_pool_max_waiting == 32
    environment = {**_environment(tmp_path), "MILAI_DATABASE_POOL_MAX_WAITING": "1"}
    assert load_worker_settings(environment).database_pool_max_waiting == 1
    environment["MILAI_DATABASE_POOL_MAX_WAITING"] = "0"
    with pytest.raises(SettingsError):
        load_worker_settings(environment)


def test_worker_rejects_non_worker_login(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["MILAI_WORKER_DATABASE_URL"] = (
        "postgresql://milai_steward:secret@127.0.0.1:15432/milai"
    )
    with pytest.raises(SettingsError, match="worker_database_url"):
        load_worker_settings(environment)


def test_worker_loader_does_not_accept_api_or_steward_secrets(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment.update(
        {
            "MILAI_API_TOKEN": "api-secret-that-must-never-enter-worker-settings",
            "MILAI_STEWARD_DATABASE_URL": (
                "postgresql://milai_steward:secret@127.0.0.1:15432/milai"
            ),
            "MILAI_AGENT_REVIEWER_TOKEN": "reviewer-secret-that-must-not-enter-worker",
            "MILAI_AUDIT_DATABASE_URL": (
                "postgresql://milai_audit:secret@127.0.0.1:15432/milai"
            ),
        }
    )
    settings = load_worker_settings(environment)
    serialized = repr(settings)
    assert "api-secret" not in serialized
    assert "reviewer-secret" not in serialized
    assert "milai_steward" not in serialized
    assert "milai_audit" not in serialized
    assert "MILAI_API_TOKEN" not in WORKER_ENV_ALLOWLIST
