from __future__ import annotations

from pathlib import Path

from milai.api import create_app
from milai.config.settings import load_settings, prepare_runtime_directories


class FakeDatabase:
    def ping(self) -> None:
        return None


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
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
    database = FakeDatabase()
    return create_app(settings, database=database, steward_database=database)  # type: ignore[arg-type]


def test_evidence_routes_require_authentication(tmp_path: Path) -> None:
    response = _app(tmp_path).test_client().post("/v1/evidence")
    assert response.status_code == 401
    assert response.json["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_wrong_bearer_token_is_not_distinguished(tmp_path: Path) -> None:
    response = (
        _app(tmp_path)
        .test_client()
        .post(
            "/v1/evidence",
            headers={"Authorization": "Bearer definitely-not-the-right-token"},
        )
    )
    assert response.status_code == 401
    assert response.json["error"]["code"] == "AUTHENTICATION_REQUIRED"
