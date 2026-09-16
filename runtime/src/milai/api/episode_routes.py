from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.episodes import EpisodeService
from milai.application.errors import CanonicalOperationError, TenantMismatch
from milai.domain.episodes import EpisodeCreateRequest, EpisodeSettleRequest
from milai.persistence import SessionContext

episode_blueprint = Blueprint("episodes", __name__, url_prefix="/v1")


@episode_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> EpisodeService:
    return cast(EpisodeService, current_app.extensions["milai.episode_service"])


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


def _idempotency_key() -> str:
    value = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(value) <= 128:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Idempotency-Key must contain between 1 and 128 characters.",
            status_code=400,
        )
    return value


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


def _episode_error(error: CanonicalOperationError) -> ApiError:
    status = {
        "EPISODE_NOT_FOUND": 404,
        "EPISODE_REFERENCE_INVALID": 409,
        "EPISODE_REVISION_CONFLICT": 409,
        "IDEMPOTENCY_CONFLICT": 409,
        "INVALID_EPISODE": 400,
        "INVALID_SETTLEMENT": 400,
        "SETTLEMENT_NOT_AUTHORIZED": 403,
        "SETTLEMENT_REFERENCE_INVALID": 409,
        "TENANT_MISMATCH": 403,
    }.get(error.code, 400)
    return ApiError(
        code=error.code,
        message="The Episode operation was rejected.",
        status_code=status,
    )


@episode_blueprint.post("/episodes")
def create_episode():  # type: ignore[no-untyped-def]
    try:
        command = EpisodeCreateRequest.model_validate(_payload())
        result = _service().create(_context(), command, _idempotency_key())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CanonicalOperationError as exc:
        raise _episode_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result), 200 if result.get("replayed") else 201


@episode_blueprint.get("/episodes/<uuid:episode_id>")
def get_episode(episode_id: UUID):  # type: ignore[no-untyped-def]
    result = _service().get(_context(), episode_id)
    if result is None:
        raise ApiError(code="EPISODE_NOT_FOUND", message="Episode was not found.", status_code=404)
    result["request_id"] = g.request_id
    return jsonify(result)


@episode_blueprint.post("/episodes/<uuid:episode_id>/settle")
def settle_episode(episode_id: UUID):  # type: ignore[no-untyped-def]
    try:
        command = EpisodeSettleRequest.model_validate(_payload())
        result = _service().settle(_context(), episode_id, command, _idempotency_key())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CanonicalOperationError as exc:
        raise _episode_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result)
