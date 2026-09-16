from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import AuthenticatedPrincipal, authenticated_context
from milai.api.errors import ApiError
from milai.application.chat import ChatService
from milai.application.context import ContextService
from milai.application.context_preparation import PrepareContextService
from milai.application.errors import ContextOperationError, TenantMismatch
from milai.domain import ChatRequest, ContextBuildRequest, PrepareContextRequest
from milai.persistence import SessionContext

context_blueprint = Blueprint("context", __name__, url_prefix="/v1")


@context_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _context_service() -> ContextService:
    return cast(ContextService, current_app.extensions["milai.context_service"])


def _chat_service() -> ChatService:
    return cast(ChatService, current_app.extensions["milai.chat_service"])


def _prepare_service() -> PrepareContextService:
    return cast(
        PrepareContextService,
        current_app.extensions["milai.prepare_context_service"],
    )


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


def _payload() -> dict[str, object]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    return value


def _validation_error(error: ValidationError) -> ApiError:
    return ApiError(
        code="INVALID_REQUEST",
        message="Request payload validation failed.",
        status_code=400,
        details={
            "fields": [
                {
                    "path": ".".join(str(part) for part in item["loc"]),
                    "type": item["type"],
                }
                for item in error.errors(include_url=False, include_input=False)
            ]
        },
    )


def _context_error(error: ContextOperationError) -> ApiError:
    status = {
        "CHAT_LINEAGE_INVALID": 409,
        "CONTEXT_BUDGET_INFEASIBLE": 422,
        "CONTEXT_ISSUE_OMITTED": 409,
        "CONTEXT_POINTER_INVALID": 409,
        "CONTEXT_POINTER_NOT_FOUND": 404,
        "CONTEXT_VALIDATION_TOKEN_INVALID": 409,
        "CONTEXT_CANONICAL_POSITION_MISSING": 409,
        "LIVE_CONFIRMATION_REQUIRED": 409,
        "RETRIEVAL_TRACE_NOT_FOUND": 404,
    }.get(error.code, 400)
    return ApiError(
        code=error.code,
        message="The governed context operation was rejected.",
        status_code=status,
    )


@context_blueprint.post("/memory/prepare-context")
def prepare_context():  # type: ignore[no-untyped-def]
    try:
        command = PrepareContextRequest.model_validate(_payload())
        principal = cast(AuthenticatedPrincipal, g.milai_principal)
        execution = _prepare_service().prepare(_context(), principal.profile, command, g.request_id)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except ContextOperationError as exc:
        raise _context_error(exc) from exc
    execution.body["request_id"] = g.request_id
    return jsonify(execution.body), execution.status_code


@context_blueprint.post("/context-capsules")
def create_context_capsule():  # type: ignore[no-untyped-def]
    try:
        command = ContextBuildRequest.model_validate(_payload())
        result = _context_service().build(_context(), command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except ContextOperationError as exc:
        raise _context_error(exc) from exc
    body = dict(result.capsule)
    body["compression_level"] = result.compression_level
    body["protected_sections"] = result.sections
    body["request_id"] = g.request_id
    return jsonify(body), 201


@context_blueprint.get("/context-capsules/<uuid:capsule_id>")
def get_context_capsule(capsule_id: UUID):  # type: ignore[no-untyped-def]
    result = _context_service().get(_context(), capsule_id)
    if result is None:
        raise ApiError(
            code="CONTEXT_CAPSULE_NOT_FOUND",
            message="ContextCapsule was not found.",
            status_code=404,
        )
    result["request_id"] = g.request_id
    return jsonify(result)


@context_blueprint.get("/context-pointers/<uuid:pointer_id>/recover")
def recover_context_pointer(pointer_id: UUID):  # type: ignore[no-untyped-def]
    try:
        result = _context_service().recover(_context(), pointer_id)
    except ContextOperationError as exc:
        raise _context_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result)


@context_blueprint.post("/chat")
def chat():  # type: ignore[no-untyped-def]
    try:
        command = ChatRequest.model_validate(_payload())
        result = _chat_service().chat(_context(), command, g.request_id)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except ContextOperationError as exc:
        raise _context_error(exc) from exc
    result.body["request_id"] = g.request_id
    return jsonify(result.body), result.status_code


@context_blueprint.get("/chat-turns/<uuid:chat_turn_id>")
def get_chat_turn(chat_turn_id: UUID):  # type: ignore[no-untyped-def]
    result = _chat_service().get(_context(), chat_turn_id)
    if result is None:
        raise ApiError(
            code="CHAT_TURN_NOT_FOUND", message="ChatTurn was not found.", status_code=404
        )
    result["response_request_id"] = g.request_id
    return jsonify(result)
