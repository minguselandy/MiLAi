from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request

from milai import IMPLEMENTATION_STATUS, SCHEMA_FREEZE_STATUS, SCHEMA_STATUS, __version__
from milai.adapters import (
    BoundedEmbeddingProvider,
    DeterministicHashEmbedding,
    EmbeddingProvider,
    FrozenOnnxCrossEncoderReranker,
    LocalContentAddressedBlobStore,
    OnnxSentenceTransformerEmbedding,
    SentenceTransformerEmbedding,
)
from milai.api.canonical_routes import canonical_blueprint
from milai.api.capability_routes import capability_blueprint
from milai.api.context_routes import context_blueprint
from milai.api.deletion_routes import deletion_blueprint
from milai.api.episode_routes import episode_blueprint
from milai.api.errors import ApiError
from milai.api.evidence_routes import evidence_blueprint
from milai.api.retrieval_routes import retrieval_blueprint
from milai.api.ui_routes import ui_blueprint
from milai.application import (
    CausalityService,
    ChatService,
    ContextReceiptService,
    ContextService,
    DeletionService,
    EpisodeService,
    EvidenceService,
    FormationProjectionStore,
    MemoryContextCompiler,
    MemoryResolveService,
    MemoryStateViewService,
    PrepareContextService,
    ProjectionReadinessService,
    ProposalService,
    RetrievalService,
    StateAddressService,
)
from milai.config import RuntimeSettings, load_settings
from milai.domain import CausalTokenCodec, ContextValidationTokenCodec
from milai.persistence import Database, DatabaseUnavailable
from milai.persistence.canonical_repository import CanonicalRepository
from milai.persistence.context_repository import ContextRepository
from milai.persistence.deletion_repository import DeletionRepository
from milai.persistence.episode_repository import EpisodeRepository
from milai.persistence.evidence_repository import EvidenceRepository
from milai.persistence.memory_state_repository import StateAddressRepository
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_repository import RetrievalRepository

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id() -> str:
    supplied = request.headers.get("X-Request-ID", "")
    return supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())


def _error_response(error: ApiError) -> tuple[Response, int]:
    body: dict[str, object] = {
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
        "request_id": getattr(g, "request_id", str(uuid4())),
    }
    if error.details:
        body["error"]["details"] = error.details  # type: ignore[index]
    return jsonify(body), error.status_code


def create_app(
    settings: RuntimeSettings | None = None,
    *,
    database: Database | None = None,
    steward_database: Database | None = None,
) -> Flask:
    runtime_settings = settings or load_settings()
    runtime_database = database or Database(runtime_settings, expected_role="milai_api")
    runtime_steward_database = steward_database or Database(
        runtime_settings,
        dsn=runtime_settings.steward_database_dsn,
        expected_role="milai_steward",
    )

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.update(
        TESTING=False,
        PROPAGATE_EXCEPTIONS=False,
        MAX_CONTENT_LENGTH=runtime_settings.max_evidence_bytes * 2,
    )
    app.extensions["milai.settings"] = runtime_settings
    app.extensions["milai.database"] = runtime_database
    app.extensions["milai.steward_database"] = runtime_steward_database
    blob_store = LocalContentAddressedBlobStore(
        runtime_settings.blob_root,
        kek=runtime_settings.blob_kek,
        key_reference=runtime_settings.blob_key_reference,
        allow_plaintext_read=runtime_settings.data_mode != "LOCAL_PERSONAL_DATA",
    )
    formation_projection = (
        FormationProjectionStore()
        if runtime_settings.formation_mode != "OFF"
        else None
    )
    app.extensions["milai.formation_projection"] = formation_projection
    evidence_service = EvidenceService(
        EvidenceRepository(runtime_database),
        blob_store,
        max_evidence_bytes=runtime_settings.max_evidence_bytes,
        data_mode=runtime_settings.data_mode,
        ingest_observer=(
            formation_projection.observe_ingest
            if formation_projection is not None
            else None
        ),
    )
    app.extensions["milai.evidence_service"] = evidence_service
    app.extensions["milai.proposal_service"] = ProposalService(
        CanonicalRepository(runtime_database, runtime_steward_database)
    )
    app.extensions["milai.episode_service"] = EpisodeService(
        EpisodeRepository(runtime_database, runtime_steward_database)
    )
    app.extensions["milai.deletion_service"] = DeletionService(
        DeletionRepository(runtime_database, runtime_steward_database),
        evidence_invalidator=(
            formation_projection.revoke if formation_projection is not None else None
        ),
        project_invalidator=(
            formation_projection.drop_project
            if formation_projection is not None
            else None
        ),
    )
    causal_tokens = CausalTokenCodec(runtime_settings.causal_token_secret.get_secret_value())
    retrieval_repository = RetrievalRepository(runtime_database)
    embedding_provider = _embedding_provider(runtime_settings)
    warmup_result = embedding_provider.warmup() if runtime_settings.embedding_prewarm else None
    app.extensions["milai.embedding_provider"] = embedding_provider
    app.extensions["milai.embedding_warmup"] = warmup_result
    retrieval_service = RetrievalService(
        retrieval_repository,
        embedding=embedding_provider,
        causal_tokens=causal_tokens,
        mmr_enabled=runtime_settings.retrieval_mmr_enabled,
        mmr_lambda=runtime_settings.retrieval_mmr_lambda,
        reranker=_reranker_provider(runtime_settings),
        reranker_pool_size=runtime_settings.retrieval_reranker_pool_size,
        temporal_reranker_pool_size=(runtime_settings.retrieval_temporal_reranker_pool_size),
        evidence_dense_enabled=runtime_settings.retrieval_evidence_dense_enabled,
        deterministic_recovery_enabled=(
            runtime_settings.retrieval_deterministic_recovery_enabled
        ),
        type_directed_acquisition_enabled=(
            runtime_settings.retrieval_type_directed_acquisition_enabled
        ),
        budget_stable_context_enabled=(
            runtime_settings.budget_invariant_context_v0_1
        ),
        formation_projection=formation_projection,
        formation_mode=runtime_settings.formation_mode,
    )
    app.extensions["milai.causality_service"] = CausalityService(
        retrieval_repository, causal_tokens
    )
    app.extensions["milai.projection_readiness_service"] = ProjectionReadinessService(
        ProjectionRepository(runtime_database)
    )
    context_repository = ContextRepository(runtime_database)
    context_service = ContextService(context_repository, blob_store)
    app.extensions["milai.retrieval_service"] = retrieval_service
    memory_state_service = MemoryStateViewService(
        StateAddressService(StateAddressRepository(runtime_database)),
        retrieval_service,
    )
    app.extensions["milai.memory_state_service"] = memory_state_service
    app.extensions["milai.memory_resolve_service"] = MemoryResolveService(
        retrieval_service,
        state_views=memory_state_service,
        receipts=ContextReceiptService(context_repository),
        progressive_context_evidence=(runtime_settings.progressive_context_evidence_v0_1),
        context_compiler=MemoryContextCompiler(
            retrieval_repository,
            budget_stable_enabled=runtime_settings.budget_invariant_context_v0_1,
        ),
    )
    app.extensions["milai.context_service"] = context_service
    app.extensions["milai.prepare_context_service"] = PrepareContextService(
        retrieval_service,
        context_service,
        context_repository,
        ContextValidationTokenCodec(runtime_settings.causal_token_secret.get_secret_value()),
    )
    app.extensions["milai.chat_service"] = ChatService(
        retrieval_service, context_service, context_repository, evidence_service
    )
    app.register_blueprint(evidence_blueprint)
    app.register_blueprint(capability_blueprint)
    app.register_blueprint(canonical_blueprint)
    app.register_blueprint(deletion_blueprint)
    app.register_blueprint(episode_blueprint)
    app.register_blueprint(retrieval_blueprint)
    app.register_blueprint(context_blueprint)
    app.register_blueprint(ui_blueprint)

    @app.before_request
    def assign_request_id() -> None:
        g.request_id = _request_id()

    @app.after_request
    def attach_request_id(response: Response) -> Response:
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError) -> tuple[Response, int]:
        return _error_response(error)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> tuple[Response, int]:
        logging.getLogger(__name__).exception(
            "unhandled_api_error",
            extra={
                "request_id": getattr(g, "request_id", None),
                "operation_family": request.method,
                "route": request.url_rule.rule if request.url_rule is not None else "unmatched",
            },
        )
        return _error_response(
            ApiError(
                code="INTERNAL_ERROR",
                message="The request could not be completed.",
                status_code=500,
            )
        )

    @app.get("/health/live")
    def live() -> Response:
        return jsonify(
            {
                "status": "ok",
                "version": __version__,
                "schema_status": SCHEMA_STATUS,
                "implementation_status": IMPLEMENTATION_STATUS,
                "schema_freeze": SCHEMA_FREEZE_STATUS,
                "request_id": g.request_id,
            }
        )

    @app.get("/health/ready")
    def ready() -> Response | tuple[Response, int]:
        try:
            runtime_database.ping()
            runtime_steward_database.ping()
        except DatabaseUnavailable:
            return _error_response(
                ApiError(
                    code="CANONICAL_UNAVAILABLE",
                    message="Canonical storage is unavailable.",
                    status_code=503,
                    retryable=True,
                )
            )
        blob_root = Path(runtime_settings.blob_root)
        if not blob_root.is_dir():
            return _error_response(
                ApiError(
                    code="RUNTIME_NOT_READY",
                    message="Local blob storage is unavailable.",
                    status_code=503,
                    retryable=True,
                )
            )
        return jsonify(
            {
                "status": "ready",
                "dependencies": {
                    "canonical_database": "ready",
                    "steward_database": "ready",
                    "blob_store": "ready",
                    "vector_embedding": embedding_provider.runtime_state.lower(),
                },
                "embedding": {
                    "provider": embedding_provider.identity.provider,
                    "model_id": embedding_provider.identity.model_id,
                    "prewarm_enabled": runtime_settings.embedding_prewarm,
                    "warmup_duration_ms": (
                        warmup_result.duration_ms if warmup_result is not None else None
                    ),
                    "error_code": embedding_provider.last_error_code,
                },
                "request_id": g.request_id,
            }
        )

    return app


def _embedding_provider(settings: RuntimeSettings) -> BoundedEmbeddingProvider:
    if settings.embedding_provider == "onnx_sentence_transformer":
        assert settings.embedding_model_path is not None
        provider: EmbeddingProvider = OnnxSentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    elif settings.embedding_provider == "sentence_transformers":
        assert settings.embedding_model_path is not None
        provider = SentenceTransformerEmbedding(
            settings.embedding_model_path,
            model_id=settings.embedding_model_id,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
        )
    else:
        provider = DeterministicHashEmbedding()
    return BoundedEmbeddingProvider(
        provider,
        max_concurrency=settings.embedding_max_concurrency,
    )


def _reranker_provider(
    settings: RuntimeSettings,
) -> FrozenOnnxCrossEncoderReranker | None:
    if settings.retrieval_reranker_provider == "none":
        return None
    assert settings.retrieval_reranker_model_path is not None
    assert settings.retrieval_reranker_model_sha256 is not None
    return FrozenOnnxCrossEncoderReranker(
        settings.retrieval_reranker_model_path,
        model_id=settings.retrieval_reranker_model_id,
        revision=settings.retrieval_reranker_revision,
        expected_model_sha256=settings.retrieval_reranker_model_sha256,
    )
