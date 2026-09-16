from __future__ import annotations

import base64
from pathlib import Path

import pytest

from milai.config.settings import SettingsError, load_settings, prepare_runtime_directories


def valid_environment(blob_root: Path) -> dict[str, str]:
    return {
        "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
        "MILAI_STEWARD_DATABASE_URL": "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
        "MILAI_BLOB_ROOT": str(blob_root),
        "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "MILAI_API_TOKEN": "test-token-with-at-least-32-characters",
        "MILAI_CAUSAL_TOKEN_SECRET": "test-causal-secret-with-at-least-32-characters",
    }


def test_missing_required_configuration_fails_without_leaking_values() -> None:
    with pytest.raises(
        SettingsError,
        match=(
            "api_token, blob_root, causal_token_secret, database_url, local_actor_id, "
            "steward_database_url, tenant_id"
        ),
    ) as raised:
        load_settings({})
    assert "postgresql" not in str(raised.value)


def test_unknown_milai_variable_fails_fast(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_BIND_P0RT"] = "18080"
    with pytest.raises(SettingsError, match="MILAI_BIND_P0RT"):
        load_settings(environment)


def test_remote_bind_is_rejected(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_BIND_HOST"] = "0.0.0.0"  # noqa: S104 - unsafe value under test
    with pytest.raises(SettingsError, match="bind_host"):
        load_settings(environment)


def test_broad_blob_root_is_rejected(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_BLOB_ROOT"] = "/"
    with pytest.raises(SettingsError, match="blob_root"):
        load_settings(environment)


def test_prepare_runtime_directory_uses_private_permissions(tmp_path: Path) -> None:
    settings = load_settings(valid_environment(tmp_path / "blobs"))
    prepare_runtime_directories(settings)
    assert settings.blob_root.is_dir()
    assert settings.blob_root.stat().st_mode & 0o777 == 0o700


def test_safe_summary_never_contains_database_secret(tmp_path: Path) -> None:
    settings = load_settings(valid_environment(tmp_path / "blobs"))
    summary = repr(settings.safe_summary()) + repr(settings)
    assert "test-causal-secret-with-at-least-32-characters" not in summary
    assert "test-token-with-at-least-32-characters" not in summary
    assert "postgresql" not in summary
    assert settings.safe_summary()["embedding_batch_size"] == 32


def test_dg11_projection_dimensions_parse_from_environment_and_are_bounded(
    tmp_path: Path,
) -> None:
    environment = valid_environment(tmp_path / "blobs")
    model_path = tmp_path / "model"
    model_path.mkdir()
    environment.update(
        {
            "MILAI_EMBEDDING_PROVIDER": "onnx_sentence_transformer",
            "MILAI_EMBEDDING_MODEL_PATH": str(model_path),
            "MILAI_EMBEDDING_MODEL_ID": "synthetic-local-model",
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "384",
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "128",
        }
    )

    assert load_settings(environment).embedding_projection_dimensions == 128
    environment["MILAI_EMBEDDING_PROJECTION_DIMENSIONS"] = "64"
    with pytest.raises(SettingsError, match="embedding_projection_dimensions"):
        load_settings(environment)


def test_local_cross_encoder_settings_require_frozen_model_identity(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    model_path = tmp_path / "reranker"
    model_path.mkdir()
    environment.update(
        {
            "MILAI_RETRIEVAL_RERANKER_PROVIDER": "onnx_cross_encoder",
            "MILAI_RETRIEVAL_RERANKER_MODEL_PATH": str(model_path),
            "MILAI_RETRIEVAL_RERANKER_MODEL_ID": "synthetic-cross-encoder",
            "MILAI_RETRIEVAL_RERANKER_REVISION": "frozen-revision",
            "MILAI_RETRIEVAL_RERANKER_MODEL_SHA256": "a" * 64,
            "MILAI_RETRIEVAL_RERANKER_POOL_SIZE": "10",
            "MILAI_RETRIEVAL_TEMPORAL_RERANKER_POOL_SIZE": "20",
        }
    )

    settings = load_settings(environment)
    assert settings.retrieval_reranker_provider == "onnx_cross_encoder"
    assert settings.retrieval_reranker_pool_size == 10
    assert settings.retrieval_temporal_reranker_pool_size == 20
    assert settings.retrieval_evidence_dense_enabled is False
    assert settings.retrieval_deterministic_recovery_enabled is False
    assert settings.safe_summary()["retrieval_reranker_revision"] == "frozen-revision"

    environment.pop("MILAI_RETRIEVAL_RERANKER_MODEL_SHA256")
    with pytest.raises(SettingsError, match="runtime settings"):
        load_settings(environment)


def test_api_and_causal_secrets_must_be_independent(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_CAUSAL_TOKEN_SECRET"] = environment["MILAI_API_TOKEN"]
    with pytest.raises(SettingsError, match="runtime settings"):
        load_settings(environment)


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("MILAI_DATABASE_URL", "postgresql://milai_owner:secret@127.0.0.1:15432/milai"),
        (
            "MILAI_STEWARD_DATABASE_URL",
            "postgresql://milai_api:secret@127.0.0.1:15432/milai",
        ),
    ],
)
def test_runtime_settings_reject_owner_or_misassigned_login(
    tmp_path: Path, field: str, url: str
) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment[field] = url
    with pytest.raises(SettingsError, match="runtime settings"):
        load_settings(environment)


def test_local_personal_data_requires_encryption_key_and_recovery(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_DATA_MODE"] = "LOCAL_PERSONAL_DATA"
    with pytest.raises(SettingsError, match="runtime settings"):
        load_settings(environment)

    environment.update(
        {
            "MILAI_BLOB_ENCRYPTION": "AES_256_GCM",
            "MILAI_BLOB_KEK_B64": base64.b64encode(b"k" * 32).decode(),
            "MILAI_BACKUP_KEY_RECOVERY_CONFIRMED": "true",
        }
    )
    settings = load_settings(environment)
    assert settings.data_mode == "LOCAL_PERSONAL_DATA"
    assert settings.blob_kek == b"k" * 32


def test_capability_tokens_are_distinct_and_redacted(tmp_path: Path) -> None:
    environment = valid_environment(tmp_path / "blobs")
    environment["MILAI_AGENT_READER_TOKEN"] = "reader-token-with-at-least-32-characters"
    environment["MILAI_AGENT_SUBMITTER_TOKEN"] = environment["MILAI_AGENT_READER_TOKEN"]
    with pytest.raises(SettingsError, match="runtime settings"):
        load_settings(environment)
