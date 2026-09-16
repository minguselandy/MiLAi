from __future__ import annotations

from pathlib import Path

from milai.api import create_app
from milai.config.settings import load_settings, prepare_runtime_directories
from milai.persistence import DatabaseUnavailable


class FakeDatabase:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.ping_count = 0

    def ping(self) -> None:
        self.ping_count += 1
        if not self.available:
            raise DatabaseUnavailable("not available")


def settings_for(tmp_path: Path):  # type: ignore[no-untyped-def]
    settings = load_settings(
        {
            "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
            "MILAI_STEWARD_DATABASE_URL": "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
            "MILAI_BLOB_ROOT": str(tmp_path / "blobs"),
            "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "MILAI_API_TOKEN": "test-token-with-at-least-32-characters",
            "MILAI_CAUSAL_TOKEN_SECRET": "test-causal-secret-with-at-least-32-characters",
        }
    )
    prepare_runtime_directories(settings)
    return settings


def test_liveness_does_not_probe_canonical_database(tmp_path: Path) -> None:
    database = FakeDatabase(available=False)
    app = create_app(settings_for(tmp_path), database=database, steward_database=database)  # type: ignore[arg-type]
    response = app.test_client().get("/health/live")
    assert response.status_code == 200
    assert response.json["schema_status"] == "0.1.x EXPERIMENTAL"
    assert response.json["schema_freeze"] == "NO-GO FOR SCHEMA FREEZE"
    assert database.ping_count == 0


def test_readiness_reports_dependencies_and_request_id(tmp_path: Path) -> None:
    database = FakeDatabase()
    app = create_app(settings_for(tmp_path), database=database, steward_database=database)  # type: ignore[arg-type]
    response = app.test_client().get("/health/ready", headers={"X-Request-ID": "test-123"})
    assert response.status_code == 200
    assert response.json["dependencies"]["canonical_database"] == "ready"
    assert response.headers["X-Request-ID"] == "test-123"


def test_readiness_fails_closed_without_database(tmp_path: Path) -> None:
    database = FakeDatabase(available=False)
    app = create_app(settings_for(tmp_path), database=database, steward_database=database)  # type: ignore[arg-type]
    response = app.test_client().get("/health/ready")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "CANONICAL_UNAVAILABLE"
    assert response.json["error"]["retryable"] is True


def test_invalid_request_id_is_not_reflected(tmp_path: Path) -> None:
    database = FakeDatabase()
    app = create_app(settings_for(tmp_path), database=database, steward_database=database)  # type: ignore[arg-type]
    response = app.test_client().get("/health/live", headers={"X-Request-ID": "bad id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad id"
