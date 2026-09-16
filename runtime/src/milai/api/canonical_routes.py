from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.errors import CanonicalOperationError, TenantMismatch
from milai.application.proposals import ProposalService
from milai.domain import ProposalCreateRequest, ProposalReviewRequest
from milai.persistence import SessionContext

canonical_blueprint = Blueprint("canonical", __name__, url_prefix="/v1")

_ISSUE_STATUSES = {
    "OPEN",
    "WAITING_EVIDENCE",
    "WAITING_USER",
    "READY_FOR_REVIEW",
    "RESOLVED",
    "DISMISSED",
}
_PROPOSAL_STATUSES = {"PENDING_REVIEW", "DEFERRED", "APPLIED", "REJECTED"}


@canonical_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> ProposalService:
    return cast(ProposalService, current_app.extensions["milai.proposal_service"])


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


def _validation_error(error: ValidationError) -> ApiError:
    return ApiError(
        code="INVALID_REQUEST",
        message="Request payload validation failed.",
        status_code=400,
        details={
            "fields": [
                {"path": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
                for item in error.errors(include_url=False, include_input=False)
            ]
        },
    )


def _canonical_error(error: CanonicalOperationError) -> ApiError:
    status = {
        "AUTHORITY_INSUFFICIENT": 403,
        "GROUNDING_BLOCKED": 409,
        "IDEMPOTENCY_CONFLICT": 409,
        "ISSUE_REVISION_CONFLICT": 409,
        "OPERATION_NOT_ENABLED": 422,
        "PROPOSAL_ALREADY_DECIDED": 409,
        "PROPOSAL_NOT_FOUND": 404,
        "SELF_REVIEW_FORBIDDEN": 403,
        "TENANT_MISMATCH": 403,
        "VERSION_CONFLICT": 409,
    }.get(error.code, 400)
    return ApiError(
        code=error.code, message="Canonical operation was rejected.", status_code=status
    )


@canonical_blueprint.post("/proposals")
def create_proposal():  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = ProposalCreateRequest.model_validate(payload)
        result = _service().create(_context(), command, _idempotency_key())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CanonicalOperationError as exc:
        raise _canonical_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result), 200 if result.get("replayed") else 201


@canonical_blueprint.get("/proposals")
def list_proposals():  # type: ignore[no-untyped-def]
    status = request.args.get("status")
    if status is not None and status not in _PROPOSAL_STATUSES:
        raise ApiError(code="INVALID_REQUEST", message="Unknown proposal status.", status_code=400)
    raw_limit = request.args.get("limit", "50")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ApiError(
            code="INVALID_REQUEST", message="Proposal limit must be an integer.", status_code=400
        ) from exc
    if not 1 <= limit <= 100:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Proposal limit must be between 1 and 100.",
            status_code=400,
        )
    proposals = _service().list_proposals(_context(), status, limit)
    return jsonify({"proposals": proposals, "request_id": g.request_id})


@canonical_blueprint.get("/proposals/<uuid:proposal_id>")
def get_proposal(proposal_id: UUID):  # type: ignore[no-untyped-def]
    result = _service().get(_context(), proposal_id)
    if result is None:
        raise ApiError(
            code="PROPOSAL_NOT_FOUND", message="Proposal was not found.", status_code=404
        )
    result["request_id"] = g.request_id
    return jsonify(result)


@canonical_blueprint.post("/proposals/<uuid:proposal_id>/review")
def review_proposal(proposal_id: UUID):  # type: ignore[no-untyped-def]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST", message="A JSON object is required.", status_code=400
        )
    try:
        command = ProposalReviewRequest.model_validate(payload)
        result = _service().review(_context(), proposal_id, command, _idempotency_key())
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    except TenantMismatch as exc:
        raise ApiError(code="TENANT_MISMATCH", message="Tenant mismatch.", status_code=403) from exc
    except CanonicalOperationError as exc:
        raise _canonical_error(exc) from exc
    result["request_id"] = g.request_id
    return jsonify(result)


@canonical_blueprint.get("/claims/<uuid:claim_id>")
def get_claim(claim_id: UUID):  # type: ignore[no-untyped-def]
    result = _service().get_claim(_context(), claim_id)
    if result is None:
        raise ApiError(code="CLAIM_NOT_FOUND", message="Claim was not found.", status_code=404)
    result["request_id"] = g.request_id
    return jsonify(result)


@canonical_blueprint.get("/claims/<uuid:claim_id>/versions")
def get_claim_versions(claim_id: UUID):  # type: ignore[no-untyped-def]
    versions = _service().get_claim_versions(_context(), claim_id)
    if not versions:
        raise ApiError(code="CLAIM_NOT_FOUND", message="Claim was not found.", status_code=404)
    return jsonify({"claim_id": str(claim_id), "versions": versions, "request_id": g.request_id})


@canonical_blueprint.get("/open-issues")
def list_open_issues():  # type: ignore[no-untyped-def]
    status = request.args.get("status")
    if status is not None and status not in _ISSUE_STATUSES:
        raise ApiError(code="INVALID_REQUEST", message="Unknown issue status.", status_code=400)
    issues = _service().list_open_issues(_context(), status)
    return jsonify({"issues": issues, "request_id": g.request_id})


@canonical_blueprint.get("/open-issues/<uuid:issue_id>")
def get_open_issue(issue_id: UUID):  # type: ignore[no-untyped-def]
    issue = _service().get_open_issue(_context(), issue_id)
    if issue is None:
        raise ApiError(
            code="OPEN_ISSUE_NOT_FOUND", message="OpenIssue was not found.", status_code=404
        )
    issue["request_id"] = g.request_id
    return jsonify(issue)
