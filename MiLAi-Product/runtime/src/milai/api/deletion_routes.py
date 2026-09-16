from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application import DeletionService
from milai.application.errors import CanonicalOperationError, TenantMismatch
from milai.domain import EvidenceRevocationRequest, NamespaceCleanupRequest
from milai.persistence import SessionContext

deletion_blueprint = Blueprint("deletion", __name__, url_prefix="/v1")


@deletion_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> DeletionService:
    return cast(DeletionService, current_app.extensions["milai.deletion_service"])


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


@deletion_blueprint.post("/evidence/<uuid:evidence_id>/revoke")
def revoke_evidence(evidence_id: UUID):  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = EvidenceRevocationRequest.model_validate(payload)
        result = _service().revoke(_context(), evidence_id, command, _idempotency_key())
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Revocation request validation failed.",
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
    except CanonicalOperationError as exc:
        status = {
            "EVIDENCE_NOT_FOUND": 404,
            "IDEMPOTENCY_CONFLICT": 409,
            "REVOCATION_NOT_AUTHORIZED": 403,
            "TENANT_MISMATCH": 403,
        }.get(exc.code, 400)
        raise ApiError(
            code=exc.code,
            message="Evidence revocation was rejected.",
            status_code=status,
        ) from exc
    result["request_id"] = g.request_id
    return jsonify(result), 200 if result.get("replayed") else 202


@deletion_blueprint.get("/deletion-requests/<uuid:deletion_request_id>")
@deletion_blueprint.get("/deletions/<uuid:deletion_request_id>")
def get_deletion_request(deletion_request_id: UUID):  # type: ignore[no-untyped-def]
    result = _service().get(_context(), deletion_request_id)
    if result is None:
        raise ApiError(
            code="DELETION_REQUEST_NOT_FOUND",
            message="Deletion request was not found.",
            status_code=404,
        )
    result["request_id"] = g.request_id
    return jsonify(result)


@deletion_blueprint.get("/evidence/<uuid:evidence_id>/deletion-status")
def get_evidence_deletion_status(evidence_id: UUID):  # type: ignore[no-untyped-def]
    result = _service().get_for_evidence(_context(), evidence_id)
    if result is None:
        raise ApiError(
            code="DELETION_REQUEST_NOT_FOUND",
            message="No deletion request exists for this Evidence.",
            status_code=404,
        )
    result["request_id"] = g.request_id
    return jsonify(result)


@deletion_blueprint.post("/namespace-cleanups")
def submit_namespace_cleanup():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = NamespaceCleanupRequest.model_validate(payload)
        result = _service().submit_namespace_cleanup(
            _context(), command, _idempotency_key()
        )
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Namespace cleanup request validation failed.",
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
    except CanonicalOperationError as exc:
        status = 409 if exc.code == "IDEMPOTENCY_CONFLICT" else 403
        raise ApiError(
            code=exc.code,
            message="Namespace cleanup was rejected.",
            status_code=status,
        ) from exc
    result["request_id"] = g.request_id
    return jsonify(result), 200 if result.get("replayed") else 202


@deletion_blueprint.get("/namespace-cleanups/<uuid:cleanup_job_id>")
def get_namespace_cleanup_status(cleanup_job_id: UUID):  # type: ignore[no-untyped-def]
    raw_offset = request.args.get("offset", "0")
    raw_limit = request.args.get("limit", "100")
    try:
        offset = int(raw_offset)
        limit = int(raw_limit)
    except ValueError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="offset and limit must be integers.",
            status_code=400,
        ) from exc
    if offset < 0 or not 1 <= limit <= 200:
        raise ApiError(
            code="INVALID_REQUEST",
            message="offset must be non-negative and limit between 1 and 200.",
            status_code=400,
        )
    result = _service().namespace_cleanup_status(
        _context(), cleanup_job_id, offset=offset, limit=limit
    )
    if result is None:
        raise ApiError(
            code="NAMESPACE_CLEANUP_NOT_FOUND",
            message="Namespace cleanup job was not found.",
            status_code=404,
        )
    result["request_id"] = g.request_id
    return jsonify(result)
