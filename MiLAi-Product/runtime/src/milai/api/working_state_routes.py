from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.errors import HostCognitiveStateError, IdempotencyConflict
from milai.application.host_cognitive_state import HostCognitiveStateService
from milai.domain.host_cognitive_state import (
    HostCognitiveStateGetRequest,
    HostCognitiveStateUpdateRequest,
)
from milai.persistence import SessionContext

working_state_blueprint = Blueprint("working_state", __name__, url_prefix="/v1/working-state")


@working_state_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> HostCognitiveStateService:
    return cast(
        HostCognitiveStateService,
        current_app.extensions["milai.host_cognitive_state_service"],
    )


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


def _payload() -> dict[str, object]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST",
            message="A JSON object body is required.",
            status_code=400,
        )
    return payload


def _validation_error(error: ValidationError) -> ApiError:
    return ApiError(
        code="INVALID_REQUEST",
        message="Host working-state payload validation failed.",
        status_code=400,
        details={
            "fields": [
                {"path": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
                for item in error.errors(include_url=False, include_input=False)
            ]
        },
    )


@working_state_blueprint.post("/get")
def get_working_state():  # type: ignore[no-untyped-def]
    try:
        command = HostCognitiveStateGetRequest.model_validate(_payload())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    result = _service().get(_context(), command)
    result.body["request_id"] = g.request_id
    return jsonify(result.body), result.status_code


@working_state_blueprint.post("/update")
def update_working_state():  # type: ignore[no-untyped-def]
    operation_id = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(operation_id) <= 128:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Idempotency-Key must contain between 1 and 128 characters.",
            status_code=400,
        )
    try:
        command = HostCognitiveStateUpdateRequest.model_validate(_payload())
        result = _service().update(_context(), command, operation_id)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except IdempotencyConflict as exc:
        raise ApiError(
            code="OPERATION_CONFLICT",
            message="The operation ID was already used for another working-state update.",
            status_code=409,
        ) from exc
    except HostCognitiveStateError as exc:
        status = {
            "EVIDENCE_REFERENCE_INVALID": 409,
            "HOST_WORKING_STATE_EXPIRED": 409,
            "HOST_WORKING_STATE_NOT_FOUND": 404,
            "HOST_WORKING_STATE_SCOPE_DENIED": 403,
            "INVALID_HOST_WORKING_STATE": 400,
            "STALE_WORKING_STATE": 409,
            "TENANT_MISMATCH": 403,
        }.get(exc.code, 400)
        raise ApiError(
            code=exc.code,
            message="Host working-state update was rejected.",
            status_code=status,
            details=exc.details or None,
        ) from exc
    result.body["request_id"] = g.request_id
    return jsonify(result.body), result.status_code
