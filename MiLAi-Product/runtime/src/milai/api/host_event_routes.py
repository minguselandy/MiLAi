from __future__ import annotations

from typing import cast

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.errors import HostExecutionEventError, IdempotencyConflict
from milai.application.host_execution_event import HostExecutionEventService
from milai.domain.host_execution_event import (
    HostExecutionEventAppendRequest,
    HostExecutionEventWindowRequest,
)
from milai.persistence import SessionContext

host_event_blueprint = Blueprint("host_events", __name__, url_prefix="/v1/host-events")


@host_event_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> HostExecutionEventService:
    return cast(
        HostExecutionEventService,
        current_app.extensions["milai.host_execution_event_service"],
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
        message="Host execution Event payload validation failed.",
        status_code=400,
        details={
            "fields": [
                {"path": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
                for item in error.errors(include_url=False, include_input=False)
            ]
        },
    )


@host_event_blueprint.post("/append")
def append_host_event():  # type: ignore[no-untyped-def]
    operation_id = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(operation_id) <= 128:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Idempotency-Key must contain between 1 and 128 characters.",
            status_code=400,
        )
    try:
        command = HostExecutionEventAppendRequest.model_validate(_payload())
        result = _service().append(_context(), command, operation_id)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except IdempotencyConflict as exc:
        raise ApiError(
            code="OPERATION_CONFLICT",
            message="The operation ID was already used for another Host Event append.",
            status_code=409,
        ) from exc
    except HostExecutionEventError as exc:
        status = {
            "EVIDENCE_REFERENCE_INVALID": 409,
            "INVALID_HOST_EXECUTION_EVENT": 400,
            "TENANT_MISMATCH": 403,
        }.get(exc.code, 400)
        raise ApiError(
            code=exc.code,
            message="Host execution Event append was rejected.",
            status_code=status,
            details=exc.details or None,
        ) from exc
    result.body["request_id"] = g.request_id
    return jsonify(result.body), result.status_code


@host_event_blueprint.post("/window")
def read_host_event_window():  # type: ignore[no-untyped-def]
    try:
        query = HostExecutionEventWindowRequest.model_validate(_payload())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    result = _service().read_window(_context(), query)
    result.body["request_id"] = g.request_id
    return jsonify(result.body), result.status_code
