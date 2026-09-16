from __future__ import annotations

import logging
import re
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast
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
from milai.adapters.http_models import HTTPEmbedding, HTTPReranker
from milai.adapters.reranker import CrossEncoderReranker
from milai.api.canonical_routes import canonical_blueprint
from milai.api.capability_routes import capability_blueprint
from milai.api.context_routes import context_blueprint
from milai.api.deletion_routes import deletion_blueprint
from milai.api.episode_routes import episode_blueprint
from milai.api.errors import ApiError
from milai.api.evidence_routes import evidence_blueprint
from milai.api.host_event_routes import host_event_blueprint
from milai.api.note_routes import note_blueprint
from milai.api.retrieval_routes import retrieval_blueprint
from milai.api.ui_routes import ui_blueprint
from milai.api.working_state_routes import working_state_blueprint
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
from milai.application.host_cognitive_state import HostCognitiveStateService
from milai.application.host_execution_event import HostExecutionEventService
from milai.application.host_note import HostNoteService
from milai.application.intra_source_acquisition import IntraSourceAcquisitionService
from milai.application.retrieval_continuation import RetrievalContinuationService
from milai.config import RuntimeSettings, load_settings
from milai.domain import CausalTokenCodec, ContextValidationTokenCodec
from milai.observability.metrics import OperationTimer, request_operation_timer
from milai.persistence import Database, DatabaseCapacityError, DatabaseUnavailable
from milai.persistence.canonical_repository import CanonicalRepository
from milai.persistence.context_repository import ContextRepository
from milai.persistence.deletion_repository import DeletionRepository
from milai.persistence.episode_repository import EpisodeRepository
from milai.persistence.evidence_repository import EvidenceRepository
from milai.persistence.host_cognitive_state_repository import HostCognitiveStateRepository
from milai.persistence.host_execution_event_repository import HostExecutionEventRepository
from milai.persistence.host_note_repository import HostNoteRepository
from milai.persistence.memory_state_repository import StateAddressRepository
from milai.persistence.projection_repository import ProjectionRepository
from milai.persistence.retrieval_continuation_repository import (
    RetrievalContinuationRepository,
)
from milai.persistence.retrieval_repository import RetrievalRepository

if TYPE_CHECKING:
    from milai.observability.retrieval_audit import (
        RetrievalAuditObserver,
        RetrievalAuditRecordingObserver,
    )

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
    retrieval_audit_observer: RetrievalAuditObserver | None = None,
    record_retrieval_audit_repository_calls: bool = False,
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
        cursor_secret=runtime_settings.causal_token_secret.get_secret_value(),
        ingest_observer=(
            formation_projection.observe_ingest
            if formation_projection is not None
            else None
        ),
    )
    app.extensions["milai.evidence_service"] = evidence_service
    app.extensions["milai.host_note_service"] = HostNoteService(
        HostNoteRepository(runtime_database),
        runtime_settings.causal_token_secret.get_secret_value(),
    )
    app.extensions["milai.host_cognitive_state_service"] = HostCognitiveStateService(
        HostCognitiveStateRepository(runtime_database)
    )
    app.extensions["milai.host_execution_event_service"] = HostExecutionEventService(
        HostExecutionEventRepository(runtime_database)
    )
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
    if record_retrieval_audit_repository_calls:
        if retrieval_audit_observer is None:
            raise ValueError("repository audit recording requires an observer")
        if not callable(getattr(retrieval_audit_observer, "observe_repository_call", None)):
            raise TypeError("repository audit observer cannot record repository calls")
        from milai.observability.retrieval_audit import AuditRecordingRepository

        retrieval_repository = cast(
            RetrievalRepository,
            AuditRecordingRepository(
                retrieval_repository,
                cast("RetrievalAuditRecordingObserver", retrieval_audit_observer),
            ),
        )
    embedding_provider = _embedding_provider(runtime_settings)
    warmup_result = embedding_provider.warmup() if runtime_settings.embedding_prewarm else None
    app.extensions["milai.embedding_provider"] = embedding_provider
    app.extensions["milai.embedding_warmup"] = warmup_result
    simple_recall_candidate_enabled = (
        runtime_settings.retrieval_type_directed_acquisition_enabled
    )
    evidence_set_selection_enabled = (
        runtime_settings.retrieval_evidence_set_selection_enabled
    )
    query_preserving_union_enabled = (
        runtime_settings.retrieval_query_preserving_union_enabled
        or evidence_set_selection_enabled
    )
    additive_union_v0_2_enabled = (
        runtime_settings.retrieval_additive_union_v0_2_enabled
    )
    wide_union_enabled = (
        query_preserving_union_enabled or additive_union_v0_2_enabled
    )
    budget_stable_context_enabled = (
        runtime_settings.budget_invariant_context_v0_1
        or simple_recall_candidate_enabled
        or wide_union_enabled
    )
    retrieval_service = RetrievalService(
        retrieval_repository,
        embedding=embedding_provider,
        causal_tokens=causal_tokens,
        mmr_enabled=runtime_settings.retrieval_mmr_enabled,
        mmr_lambda=runtime_settings.retrieval_mmr_lambda,
        reranker=_reranker_provider(runtime_settings),
        reranker_pool_size=runtime_settings.retrieval_reranker_pool_size,
        temporal_reranker_pool_size=(runtime_settings.retrieval_temporal_reranker_pool_size),
        lexical_enrichment_enabled=simple_recall_candidate_enabled,
        evidence_dense_enabled=runtime_settings.retrieval_evidence_dense_enabled,
        deterministic_recovery_enabled=(
            runtime_settings.retrieval_deterministic_recovery_enabled
        ),
        type_directed_acquisition_enabled=(
            simple_recall_candidate_enabled
        ),
        budget_stable_context_enabled=budget_stable_context_enabled,
        formation_projection=formation_projection,
        formation_mode=runtime_settings.formation_mode,
        query_preserving_union_enabled=query_preserving_union_enabled,
        additive_union_v0_2_enabled=additive_union_v0_2_enabled,
        retrieval_audit_observer=retrieval_audit_observer,
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
        continuations=(
            RetrievalContinuationService(
                RetrievalContinuationRepository(runtime_database),
                retrieval_repository,
            )
            if runtime_settings.retrieval_continuation_v0_1_enabled
            else None
        ),
        intra_source_acquisition=(
            IntraSourceAcquisitionService(retrieval_repository)
            if runtime_settings.intra_source_acquisition_v0_1_mode == "SHADOW"
            else None
        ),
        reader_evidence_policy=runtime_settings.reader_evidence_policy_v0_1,
        informational_soft_admission_v0_2_enabled=(
            runtime_settings.reader_informational_soft_admission_v0_2_enabled
        ),
        instance_preserving_admission_v0_1_enabled=(
            runtime_settings.reader_instance_preserving_admission_v0_1_enabled
        ),
        context_compiler=MemoryContextCompiler(
            retrieval_repository,
            budget_stable_enabled=budget_stable_context_enabled,
            query_preserving_union_enabled=wide_union_enabled,
            evidence_set_selection_enabled=evidence_set_selection_enabled,
            instance_preserving_admission_enabled=(
                runtime_settings.reader_instance_preserving_admission_v0_1_enabled
            ),
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
    app.register_blueprint(note_blueprint)
    app.register_blueprint(host_event_blueprint)
    app.register_blueprint(capability_blueprint)
    app.register_blueprint(canonical_blueprint)
    app.register_blueprint(deletion_blueprint)
    app.register_blueprint(episode_blueprint)
    app.register_blueprint(retrieval_blueprint)
    app.register_blueprint(context_blueprint)
    app.register_blueprint(ui_blueprint)
    app.register_blueprint(working_state_blueprint)

    @app.before_request
    def assign_request_id() -> None:
        g.request_id = _request_id()
        if runtime_settings.request_timing_enabled:
            g.request_started = perf_counter()
            g.request_timer = OperationTimer()
            g.request_timer_token = request_operation_timer.set(g.request_timer)

    @app.after_request
    def attach_request_id(response: Response) -> Response:
        response.headers["X-Request-ID"] = g.request_id
        if runtime_settings.request_timing_enabled:
            logging.getLogger(__name__).info(
                "runtime_request_timing",
                extra={
                    "request_id": g.request_id,
                    "route": request.url_rule.rule if request.url_rule is not None else "unmatched",
                    "safe_metadata": {
                        "schema_version": "request-timing-v1",
                        "application_ms": round((perf_counter() - g.request_started) * 1000, 3),
                        "status_code": response.status_code,
                        **g.request_timer.snapshot(),
                    },
                },
            )
        return response

    @app.teardown_request
    def clear_request_timing(_error: BaseException | None) -> None:
        token = g.pop("request_timer_token", None)
        if token is not None:
            request_operation_timer.reset(token)

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError) -> tuple[Response, int]:
        return _error_response(error)

    @app.errorhandler(DatabaseCapacityError)
    def handle_database_capacity(error: DatabaseCapacityError) -> tuple[Response, int]:
        return _error_response(
            ApiError(
                code="DATABASE_CAPACITY_EXCEEDED",
                message="Database connection capacity is temporarily unavailable.",
                status_code=503,
                retryable=True,
                details={"reason": error.reason},
            )
        )

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
    provider: EmbeddingProvider
    if settings.embedding_provider == "http_embeddings":
        assert settings.embedding_endpoint is not None
        assert settings.embedding_model_revision is not None
        provider = HTTPEmbedding(
            settings.embedding_endpoint,
            model_id=settings.embedding_model_id,
            revision=settings.embedding_model_revision,
            source_dimensions=settings.embedding_source_dimensions,
            projection_dimensions=settings.embedding_projection_dimensions,
            timeout=settings.embedding_http_timeout_seconds,
        )
    elif settings.embedding_provider == "onnx_sentence_transformer":
        assert settings.embedding_model_path is not None
        provider = OnnxSentenceTransformerEmbedding(
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
        queue_timeout_seconds=(settings.embedding_http_timeout_seconds
                               if settings.embedding_provider == "http_embeddings" else None),
    )


def _reranker_provider(
    settings: RuntimeSettings,
) -> CrossEncoderReranker | None:
    if settings.retrieval_reranker_provider == "none":
        return None
    if settings.retrieval_reranker_provider == "http_reranker":
        assert settings.retrieval_reranker_endpoint is not None
        return HTTPReranker(
            settings.retrieval_reranker_endpoint,
            model_id=settings.retrieval_reranker_model_id,
            revision=settings.retrieval_reranker_revision,
            timeout=settings.retrieval_reranker_http_timeout_seconds,
            max_concurrency=settings.retrieval_reranker_max_concurrency,
        )
    assert settings.retrieval_reranker_model_path is not None
    assert settings.retrieval_reranker_model_sha256 is not None
    return FrozenOnnxCrossEncoderReranker(
        settings.retrieval_reranker_model_path,
        model_id=settings.retrieval_reranker_model_id,
        revision=settings.retrieval_reranker_revision,
        expected_model_sha256=settings.retrieval_reranker_model_sha256,
    )
