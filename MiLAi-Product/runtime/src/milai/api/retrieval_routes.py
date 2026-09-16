from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.causality import CausalityService
from milai.application.errors import (
    CausalConsistencyError,
    RetrievalContinuationError,
    RetrievalRouteDisabled,
    TenantMismatch,
)
from milai.application.memory_resolve import MemoryResolveService
from milai.application.memory_state import MemoryStateViewService
from milai.application.projection_readiness import ProjectionReadinessService
from milai.application.query_planner import payload_free_query_plan
from milai.application.recollection import RecollectionFacade
from milai.application.retrieval import RetrievalService
from milai.domain import (
    MemoryResolveRequest,
    MemoryStateGetRequest,
    ProjectionReadinessRequest,
    RetrievalRequest,
)
from milai.persistence import DatabaseUnavailable, SessionContext

retrieval_blueprint = Blueprint("retrieval", __name__, url_prefix="/v1")


@retrieval_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> RecollectionFacade:
    return cast(RecollectionFacade, current_app.extensions["milai.retrieval_service"])


def _retrieval_operations_service() -> RetrievalService:
    """Return the concrete owner of trace and projection-status operations."""

    return cast(RetrievalService, current_app.extensions["milai.retrieval_service"])


def _memory_resolve_service() -> MemoryResolveService:
    return cast(
        MemoryResolveService,
        current_app.extensions["milai.memory_resolve_service"],
    )


def _memory_state_service() -> MemoryStateViewService:
    return cast(
        MemoryStateViewService,
        current_app.extensions["milai.memory_state_service"],
    )


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


def _causality_service() -> CausalityService:
    return cast(CausalityService, current_app.extensions["milai.causality_service"])


def _projection_readiness_service() -> ProjectionReadinessService:
    return cast(
        ProjectionReadinessService,
        current_app.extensions["milai.projection_readiness_service"],
    )


def _causal_error(error: CausalConsistencyError) -> ApiError:
    status = 404 if error.code == "OUTBOX_POSITION_NOT_FOUND" else 400
    return ApiError(
        code=error.code,
        message="The causal consistency request was rejected.",
        status_code=status,
    )


@retrieval_blueprint.post("/causal-tokens")
def issue_causal_token():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"outbox_ids"}:
        raise ApiError(
            code="INVALID_REQUEST",
            message="outbox_ids is required.",
            status_code=400,
        )
    values = payload["outbox_ids"]
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ApiError(
            code="INVALID_REQUEST",
            message="outbox_ids must contain between 1 and 16 identifiers.",
            status_code=400,
        )
    try:
        outbox_ids = [UUID(str(value)) for value in values]
    except (TypeError, ValueError) as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="outbox_ids contains an invalid identifier.",
            status_code=400,
        ) from exc
    try:
        result = _causality_service().issue(_context(), outbox_ids)
    except CausalConsistencyError as exc:
        raise _causal_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result), 201


@retrieval_blueprint.post("/retrieval/query")
@retrieval_blueprint.post("/memory/query")
def retrieve():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = RetrievalRequest.model_validate(payload)
        execution = _service().retrieve(_context(), command, g.request_id)
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Request payload validation failed.",
            status_code=400,
            details={
                "fields": [
                    {
                        "path": ".".join(str(part) for part in item["loc"]),
                        "type": item["type"],
                    }
                    for item in exc.errors(include_url=False, include_input=False)
                ]
            },
        ) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except RetrievalRouteDisabled as exc:
        raise ApiError(
            code="ROUTE_DISABLED",
            message="L2 retrieval is not enabled in Lean V1.",
            status_code=422,
        ) from exc
    except CausalConsistencyError as exc:
        raise _causal_error(exc) from exc
    public_body = dict(execution.body)
    public_body["request_id"] = g.request_id
    query_plan = public_body.get("query_plan")
    if isinstance(query_plan, dict):
        public_body["query_plan"] = payload_free_query_plan(query_plan)
    return jsonify(public_body), execution.status_code


@retrieval_blueprint.post("/memory/resolve")
def resolve_memory():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = MemoryResolveRequest.model_validate(payload)
        execution = _memory_resolve_service().resolve(_context(), command, g.request_id)
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Request payload validation failed.",
            status_code=400,
            details={
                "fields": [
                    {
                        "path": ".".join(str(part) for part in item["loc"]),
                        "type": item["type"],
                    }
                    for item in exc.errors(include_url=False, include_input=False)
                ]
            },
        ) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CausalConsistencyError as exc:
        raise _causal_error(exc) from exc
    except RetrievalContinuationError as exc:
        raise ApiError(
            code=exc.code,
            message="The retrieval continuation request was rejected.",
            status_code=409,
        ) from exc
    execution.body["request_id"] = g.request_id
    return jsonify(execution.body), execution.status_code


@retrieval_blueprint.post("/memory/get")
def get_memory_state():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = MemoryStateGetRequest.model_validate(payload)
        execution = _memory_state_service().get(_context(), command, g.request_id)
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Request payload validation failed.",
            status_code=400,
            details={
                "fields": [
                    {
                        "path": ".".join(str(part) for part in item["loc"]),
                        "type": item["type"],
                    }
                    for item in exc.errors(include_url=False, include_input=False)
                ]
            },
        ) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CausalConsistencyError as exc:
        raise _causal_error(exc) from exc
    execution.body["request_id"] = g.request_id
    return jsonify(execution.body), execution.status_code


@retrieval_blueprint.get("/retrieval-traces/<uuid:trace_id>")
def get_retrieval_trace(trace_id: UUID):  # type: ignore[no-untyped-def]
    trace = _retrieval_operations_service().get_trace(_context(), trace_id)
    if trace is None:
        raise ApiError(
            code="RETRIEVAL_TRACE_NOT_FOUND",
            message="RetrievalTrace was not found.",
            status_code=404,
        )
    trace["response_request_id"] = g.request_id
    return jsonify(trace)


def _system_status() -> dict[str, object]:
    try:
        return _retrieval_operations_service().system_status(_context())
    except DatabaseUnavailable as exc:
        raise ApiError(
            code="CANONICAL_UNAVAILABLE",
            message="Canonical storage is unavailable.",
            status_code=503,
            retryable=True,
        ) from exc


@retrieval_blueprint.get("/system/watermarks")
def get_system_watermarks():  # type: ignore[no-untyped-def]
    status = _system_status()
    return jsonify(
        {
            "canonical_snapshot": status["canonical_snapshot"],
            "watermarks": status["watermarks"],
            "request_id": g.request_id,
        }
    )


@retrieval_blueprint.post("/system/projection-readiness")
def wait_for_projection_readiness():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = ProjectionReadinessRequest.model_validate(payload)
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Request payload validation failed.",
            status_code=400,
            details={
                "fields": [
                    {
                        "path": ".".join(str(part) for part in item["loc"]),
                        "type": item["type"],
                    }
                    for item in exc.errors(include_url=False, include_input=False)
                ]
            },
        ) from exc
    result, status_code = _projection_readiness_service().wait(_context(), command)
    result["request_id"] = g.request_id
    return jsonify(result), status_code


@retrieval_blueprint.get("/system/degraded-routes")
def get_degraded_routes():  # type: ignore[no-untyped-def]
    status = _system_status()
    return jsonify({"routes": status["routes"], "request_id": g.request_id})
