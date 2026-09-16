from __future__ import annotations

import base64
import binascii
import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from milai import IMPLEMENTATION_STATUS, SCHEMA_FREEZE_STATUS, SCHEMA_STATUS


class SettingsError(RuntimeError):
    """Raised when runtime configuration is missing or unsafe."""


class CommonSettings(BaseSettings):
    """Fields intentionally safe to share across API and worker processes."""

    model_config = SettingsConfigDict(extra="forbid", frozen=True)


class ApiSettings(CommonSettings):
    """Strict settings for the online API process."""

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    environment: Literal["development", "test", "local_beta"] = "development"
    database_url: SecretStr
    steward_database_url: SecretStr
    blob_root: Path
    tenant_id: UUID
    local_actor_id: UUID
    api_token: SecretStr
    causal_token_secret: SecretStr
    agent_reader_token: SecretStr | None = None
    agent_submitter_token: SecretStr | None = None
    agent_operator_token: SecretStr | None = None
    agent_reviewer_token: SecretStr | None = None
    data_mode: Literal["SYNTHETIC_ONLY", "DEIDENTIFIED_ALLOWED", "LOCAL_PERSONAL_DATA"] = (
        "SYNTHETIC_ONLY"
    )
    blob_encryption: Literal["PLAINTEXT", "AES_256_GCM"] = "PLAINTEXT"
    blob_kek_b64: SecretStr | None = None
    blob_key_reference: str = Field(default="local-kek-v1", min_length=1, max_length=128)
    backup_key_recovery_confirmed: bool = False
    embedding_provider: Literal[
        "deterministic_hash", "sentence_transformers", "onnx_sentence_transformer"
    ] = "deterministic_hash"
    embedding_model_path: Path | None = None
    embedding_model_id: str = Field(default="deterministic-hash-v1", min_length=1, max_length=255)
    embedding_source_dimensions: int = Field(default=16, ge=1, le=8192)
    embedding_projection_dimensions: int = Field(default=16, ge=16, le=128)
    embedding_prewarm: bool = True
    embedding_max_concurrency: int = Field(default=4, ge=1, le=64)
    embedding_batch_size: int = Field(default=32, ge=1, le=1024)
    retrieval_mmr_enabled: bool = False
    retrieval_mmr_lambda: float = Field(default=0.8, ge=0.5, le=1.0)
    retrieval_evidence_dense_enabled: bool = False
    retrieval_deterministic_recovery_enabled: bool = False
    retrieval_type_directed_acquisition_enabled: bool = False
    budget_invariant_context_v0_1: bool = False
    feature_profile: Literal["BASELINE", "FORMED_SHADOW", "FORMED_CANARY"] = "BASELINE"
    progressive_context_evidence_v0_1: bool = False
    retrieval_acquisition_execution_policy_version: Literal[
        "dg21-opened-dev-v0.1"
    ] = "dg21-opened-dev-v0.1"
    retrieval_reranker_provider: Literal["none", "onnx_cross_encoder"] = "none"
    retrieval_reranker_model_path: Path | None = None
    retrieval_reranker_model_id: str = Field(default="disabled", min_length=1, max_length=255)
    retrieval_reranker_revision: str = Field(default="disabled", min_length=1, max_length=255)
    retrieval_reranker_model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retrieval_reranker_pool_size: int = Field(default=10, ge=4, le=20)
    retrieval_temporal_reranker_pool_size: int = Field(default=20, ge=4, le=20)
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=18080, ge=1, le=65535)
    api_threads: int = Field(default=4, ge=1, le=64)
    database_pool_min_size: int = Field(default=1, ge=1, le=32)
    database_pool_max_size: int = Field(default=5, ge=1, le=64)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_lease_seconds: int = Field(default=30, ge=1, le=300)
    worker_max_attempts: int = Field(default=5, ge=1, le=100)
    worker_retry_delay_seconds: int = Field(default=1, ge=0, le=86400)
    worker_event_limit: int = Field(default=256, ge=1, le=10000)
    worker_projection_batch_size: int = Field(default=32, ge=1, le=128)
    max_evidence_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @model_validator(mode="before")
    @classmethod
    def translate_legacy_formation_mode(cls, value: object) -> object:
        if not isinstance(value, Mapping) or "memory_formation_mode" not in value:
            return value
        translated = dict(value)
        legacy = translated.pop("memory_formation_mode")
        profile = {
            "OFF": "BASELINE",
            "SHADOW": "FORMED_SHADOW",
            "CANARY": "FORMED_CANARY",
        }.get(str(legacy))
        if profile is None:
            raise ValueError("memory_formation_mode is invalid")
        declared = translated.get("feature_profile")
        if declared is not None and declared != profile:
            raise ValueError("feature_profile conflicts with legacy memory_formation_mode")
        translated["feature_profile"] = profile
        return translated

    @field_validator("database_url", "steward_database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        parsed = urlsplit(raw)
        if parsed.scheme not in {"postgresql", "postgres"}:
            raise ValueError("database_url must use PostgreSQL")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("database_url must include host and database")
        return value

    @field_validator("blob_root")
    @classmethod
    def validate_blob_root(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve(strict=False)
        if resolved == Path("/") or resolved == Path.home().resolve():
            raise ValueError("blob_root cannot be a broad system or home directory")
        return resolved

    @field_validator("embedding_projection_dimensions")
    @classmethod
    def validate_embedding_projection_dimensions(cls, value: int) -> int:
        if value not in {16, 128}:
            raise ValueError("embedding_projection_dimensions must be 16 or 128")
        return value

    @field_validator("bind_host")
    @classmethod
    def validate_bind_host(cls, value: str) -> str:
        if value == "localhost":
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("bind_host must be a loopback IP address or localhost") from exc
        if not address.is_loopback:
            raise ValueError("remote bind is outside the Lean V1 security boundary")
        return value

    @field_validator("api_token", "causal_token_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("runtime secrets must contain at least 32 characters")
        return value

    @field_validator(
        "agent_reader_token",
        "agent_submitter_token",
        "agent_operator_token",
        "agent_reviewer_token",
    )
    @classmethod
    def validate_optional_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("agent capability tokens must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_pool_bounds(self) -> ApiSettings:
        if self.database_pool_min_size > self.database_pool_max_size:
            raise ValueError("database_pool_min_size cannot exceed database_pool_max_size")
        api_user = urlsplit(self.database_dsn).username
        steward_user = urlsplit(self.steward_database_dsn).username
        if api_user != "milai_api":
            raise ValueError("database_url must use the exact milai_api login role")
        if steward_user != "milai_steward":
            raise ValueError("steward_database_url must use the exact milai_steward login role")
        if self.api_token.get_secret_value() == self.causal_token_secret.get_secret_value():
            raise ValueError("api_token and causal_token_secret must be independent")
        capability_tokens = [
            item.get_secret_value()
            for item in (
                self.agent_reader_token,
                self.agent_submitter_token,
                self.agent_operator_token,
                self.agent_reviewer_token,
            )
            if item is not None
        ]
        all_tokens = [
            *capability_tokens,
            self.api_token.get_secret_value(),
            self.causal_token_secret.get_secret_value(),
        ]
        if len(all_tokens) != len(set(all_tokens)):
            raise ValueError("all runtime and capability secrets must be independent")
        if self.blob_encryption == "AES_256_GCM" and self.blob_kek_b64 is None:
            raise ValueError("blob_kek_b64 is required for AES_256_GCM")
        if self.blob_kek_b64 is not None:
            try:
                decoded_key = base64.b64decode(self.blob_kek_b64.get_secret_value(), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("blob_kek_b64 must be valid base64") from exc
            if len(decoded_key) != 32:
                raise ValueError("blob_kek_b64 must decode to exactly 32 bytes")
        if self.data_mode == "LOCAL_PERSONAL_DATA" and (
            self.blob_encryption != "AES_256_GCM"
            or self.blob_kek_b64 is None
            or not self.backup_key_recovery_confirmed
        ):
            raise ValueError(
                "LOCAL_PERSONAL_DATA requires encryption and a confirmed key recovery gate"
            )
        if self.embedding_provider in {
            "sentence_transformers",
            "onnx_sentence_transformer",
        }:
            if self.embedding_model_path is None or not self.embedding_model_path.is_dir():
                raise ValueError(
                    "real embedding provider requires an existing local embedding_model_path"
                )
            if self.embedding_source_dimensions == 16:
                raise ValueError("real embedding source dimensions must be configured")
        elif self.embedding_projection_dimensions != 16:
            raise ValueError("deterministic_hash only supports the 16d projection")
        if self.retrieval_reranker_provider == "onnx_cross_encoder":
            if (
                self.retrieval_reranker_model_path is None
                or not self.retrieval_reranker_model_path.is_dir()
                or self.retrieval_reranker_model_sha256 is None
            ):
                raise ValueError("onnx_cross_encoder requires a local model path and frozen digest")
        elif (
            self.retrieval_reranker_model_path is not None
            or self.retrieval_reranker_model_sha256 is not None
        ):
            raise ValueError("disabled retrieval reranker cannot declare model files")
        return self

    @property
    def database_dsn(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def steward_database_dsn(self) -> str:
        return self.steward_database_url.get_secret_value()

    def safe_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "blob_root": str(self.blob_root),
            "tenant_id": str(self.tenant_id),
            "schema_status": SCHEMA_STATUS,
            "implementation_status": IMPLEMENTATION_STATUS,
            "schema_freeze": SCHEMA_FREEZE_STATUS,
            "data_mode": self.data_mode,
            "blob_encryption": self.blob_encryption,
            "blob_key_reference": self.blob_key_reference,
            "embedding_provider": self.embedding_provider,
            "embedding_model_id": self.embedding_model_id,
            "embedding_projection_dimensions": self.embedding_projection_dimensions,
            "embedding_prewarm": self.embedding_prewarm,
            "embedding_max_concurrency": self.embedding_max_concurrency,
            "embedding_batch_size": self.embedding_batch_size,
            "retrieval_mmr_enabled": self.retrieval_mmr_enabled,
            "retrieval_mmr_lambda": self.retrieval_mmr_lambda,
            "retrieval_evidence_dense_enabled": self.retrieval_evidence_dense_enabled,
            "retrieval_deterministic_recovery_enabled": (
                self.retrieval_deterministic_recovery_enabled
            ),
            "retrieval_type_directed_acquisition_enabled": (
                self.retrieval_type_directed_acquisition_enabled
            ),
            "budget_invariant_context_v0_1": self.budget_invariant_context_v0_1,
            "feature_profile": self.feature_profile,
            "progressive_context_evidence_v0_1": (self.progressive_context_evidence_v0_1),
            "retrieval_acquisition_execution_policy_version": (
                self.retrieval_acquisition_execution_policy_version
            ),
            "retrieval_reranker_provider": self.retrieval_reranker_provider,
            "retrieval_reranker_model_id": self.retrieval_reranker_model_id,
            "retrieval_reranker_revision": self.retrieval_reranker_revision,
            "retrieval_reranker_pool_size": self.retrieval_reranker_pool_size,
            "retrieval_temporal_reranker_pool_size": (self.retrieval_temporal_reranker_pool_size),
        }

    @property
    def blob_kek(self) -> bytes | None:
        if self.blob_kek_b64 is None:
            return None
        return base64.b64decode(self.blob_kek_b64.get_secret_value(), validate=True)

    @property
    def formation_mode(self) -> Literal["OFF", "SHADOW", "CANARY"]:
        return cast(
            Literal["OFF", "SHADOW", "CANARY"],
            {
                "BASELINE": "OFF",
                "FORMED_SHADOW": "SHADOW",
                "FORMED_CANARY": "CANARY",
            }[self.feature_profile],
        )

    @property
    def memory_formation_mode(self) -> Literal["OFF", "SHADOW", "CANARY"]:
        """Read-only compatibility view; product configuration uses feature_profile."""

        return self.formation_mode


# Compatibility name for existing API callers and historic artifacts.
RuntimeSettings = ApiSettings


class WorkerSettings(CommonSettings):
    """Least-privilege worker configuration loaded from an explicit allowlist."""

    environment: Literal["development", "test", "local_beta"] = "development"
    worker_database_url: SecretStr
    blob_root: Path
    tenant_id: UUID
    local_actor_id: UUID
    data_mode: Literal["SYNTHETIC_ONLY", "DEIDENTIFIED_ALLOWED", "LOCAL_PERSONAL_DATA"] = (
        "SYNTHETIC_ONLY"
    )
    blob_encryption: Literal["PLAINTEXT", "AES_256_GCM"] = "PLAINTEXT"
    blob_kek_b64: SecretStr | None = None
    blob_key_reference: str = Field(default="local-kek-v1", min_length=1, max_length=128)
    embedding_provider: Literal[
        "deterministic_hash", "sentence_transformers", "onnx_sentence_transformer"
    ] = "deterministic_hash"
    embedding_model_path: Path | None = None
    embedding_model_id: str = Field(default="deterministic-hash-v1", min_length=1, max_length=255)
    embedding_source_dimensions: int = Field(default=16, ge=1, le=8192)
    embedding_projection_dimensions: int = Field(default=16, ge=16, le=128)
    embedding_prewarm: bool = True
    embedding_max_concurrency: int = Field(default=4, ge=1, le=64)
    embedding_batch_size: int = Field(default=32, ge=1, le=1024)
    database_pool_min_size: int = Field(default=1, ge=1, le=32)
    database_pool_max_size: int = Field(default=5, ge=1, le=64)
    database_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_lease_seconds: int = Field(default=30, ge=1, le=300)
    worker_max_attempts: int = Field(default=5, ge=1, le=100)
    worker_retry_delay_seconds: int = Field(default=1, ge=0, le=86400)
    worker_event_limit: int = Field(default=256, ge=1, le=10000)
    worker_projection_batch_size: int = Field(default=32, ge=1, le=128)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @field_validator("worker_database_url", mode="before")
    @classmethod
    def validate_worker_database_url(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        parsed = urlsplit(raw)
        if parsed.scheme not in {"postgresql", "postgres"} or parsed.username != "milai_worker":
            raise ValueError("worker_database_url must use the exact milai_worker PostgreSQL role")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("worker_database_url must include host and database")
        return value

    @field_validator("blob_root")
    @classmethod
    def validate_worker_blob_root(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve(strict=False)
        if resolved == Path("/") or resolved == Path.home().resolve():
            raise ValueError("blob_root cannot be a broad system or home directory")
        return resolved

    @model_validator(mode="after")
    def validate_worker_bounds(self) -> WorkerSettings:
        if self.database_pool_min_size > self.database_pool_max_size:
            raise ValueError("database_pool_min_size cannot exceed database_pool_max_size")
        if self.blob_encryption == "AES_256_GCM" and self.blob_kek_b64 is None:
            raise ValueError("blob_kek_b64 is required for AES_256_GCM")
        if self.blob_kek_b64 is not None:
            try:
                decoded_key = base64.b64decode(
                    self.blob_kek_b64.get_secret_value(), validate=True
                )
            except (binascii.Error, ValueError) as exc:
                raise ValueError("blob_kek_b64 must be valid base64") from exc
            if len(decoded_key) != 32:
                raise ValueError("blob_kek_b64 must decode to exactly 32 bytes")
        if self.data_mode == "LOCAL_PERSONAL_DATA" and (
            self.blob_encryption != "AES_256_GCM" or self.blob_kek_b64 is None
        ):
            raise ValueError("LOCAL_PERSONAL_DATA requires encrypted Blob storage")
        if self.embedding_provider in {
            "sentence_transformers",
            "onnx_sentence_transformer",
        }:
            if self.embedding_model_path is None or not self.embedding_model_path.is_dir():
                raise ValueError(
                    "real embedding provider requires an existing local embedding_model_path"
                )
            if self.embedding_source_dimensions == 16:
                raise ValueError("real embedding source dimensions must be configured")
        elif self.embedding_projection_dimensions != 16:
            raise ValueError("deterministic_hash only supports the 16d projection")
        return self

    @property
    def worker_database_dsn(self) -> str:
        return self.worker_database_url.get_secret_value()

    @property
    def blob_kek(self) -> bytes | None:
        if self.blob_kek_b64 is None:
            return None
        value = base64.b64decode(self.blob_kek_b64.get_secret_value(), validate=True)
        if len(value) != 32:
            raise SettingsError("blob_kek_b64 must decode to exactly 32 bytes")
        return value


_FIELD_ENV = {
    f"MILAI_{field_name.upper()}": field_name for field_name in RuntimeSettings.model_fields
}

_WORKER_FIELD_ENV = {
    f"MILAI_{field_name.upper()}": field_name for field_name in WorkerSettings.model_fields
}
WORKER_ENV_ALLOWLIST = frozenset(_WORKER_FIELD_ENV)

# Known variables consumed by Compose, migrations, or a separate worker process. They are
# accepted in a shared exported .env but are never copied into RuntimeSettings.
_AUXILIARY_ENV = {
    "MILAI_BASE_URL",
    "MILAI_AGENT_TOKEN",
    "MILAI_AGENT_SCOPE_JSON",
    "MILAI_AGENT_REQUIRED_AUTHORITY",
    "MILAI_AGENT_CONSISTENCY_FLOOR",
    "MILAI_AGENT_MAX_LIMIT",
    "MILAI_POSTGRES_PORT",
    "MILAI_POSTGRES_DB",
    "MILAI_OWNER_DB_PASSWORD",
    "MILAI_API_DB_PASSWORD",
    "MILAI_STEWARD_DB_PASSWORD",
    "MILAI_WORKER_DB_PASSWORD",
    "MILAI_AUDIT_DB_PASSWORD",
    "MILAI_AUDIT_DATABASE_URL",
    "MILAI_MIGRATION_DATABASE_URL",
    "MILAI_WORKER_DATABASE_URL",
    "MILAI_TEST_DATABASE_URL",
    "MILAI_TEST_API_DATABASE_URL",
    "MILAI_TEST_STEWARD_DATABASE_URL",
    "MILAI_TEST_WORKER_DATABASE_URL",
    "MILAI_TEST_AUDIT_DATABASE_URL",
    "MILAI_RESTORE_DATABASE_URL",
    "MILAI_MEMORY_FORMATION_MODE",
}


def load_settings(environ: Mapping[str, str] | None = None) -> RuntimeSettings:
    source = os.environ if environ is None else environ
    unknown = sorted(
        name
        for name in source
        if name.startswith("MILAI_") and name not in _FIELD_ENV and name not in _AUXILIARY_ENV
    )
    if unknown:
        raise SettingsError(f"unknown MiLAi configuration variables: {', '.join(unknown)}")

    values = {
        field_name: source[env_name]
        for env_name, field_name in _FIELD_ENV.items()
        if env_name in source
    }
    legacy_mode = source.get("MILAI_MEMORY_FORMATION_MODE")
    if legacy_mode is not None:
        legacy_profile = {
            "OFF": "BASELINE",
            "SHADOW": "FORMED_SHADOW",
            "CANARY": "FORMED_CANARY",
        }.get(legacy_mode)
        if legacy_profile is None:
            raise SettingsError("invalid MiLAi configuration field: memory_formation_mode")
        declared_profile = values.get("feature_profile")
        if declared_profile is not None and declared_profile != legacy_profile:
            raise SettingsError("feature_profile conflicts with memory_formation_mode")
        values["feature_profile"] = legacy_profile
    try:
        return RuntimeSettings.model_validate(values)
    except ValidationError as exc:
        fields = sorted(
            {
                str(error["loc"][0]) if error["loc"] else "runtime settings"
                for error in exc.errors(include_url=False)
            }
        )
        label = ", ".join(fields) if fields else "runtime settings"
        raise SettingsError(f"invalid or missing MiLAi configuration fields: {label}") from exc


def load_worker_settings(environ: Mapping[str, str] | None = None) -> WorkerSettings:
    """Load only worker-owned fields; API/Steward/Agent/audit secrets are ignored."""

    source = os.environ if environ is None else environ
    values = {
        field_name: source[env_name]
        for env_name, field_name in _WORKER_FIELD_ENV.items()
        if env_name in source
    }
    try:
        return WorkerSettings.model_validate(values)
    except ValidationError as exc:
        fields = sorted(
            {
                str(error["loc"][0]) if error["loc"] else "worker settings"
                for error in exc.errors(include_url=False)
            }
        )
        raise SettingsError(
            f"invalid or missing MiLAi worker configuration fields: {', '.join(fields)}"
        ) from exc


def prepare_runtime_directories(settings: RuntimeSettings | WorkerSettings) -> None:
    settings.blob_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if settings.blob_root.is_symlink() or not settings.blob_root.is_dir():
        raise SettingsError("blob_root must be a real local directory")
    settings.blob_root.chmod(0o700)
