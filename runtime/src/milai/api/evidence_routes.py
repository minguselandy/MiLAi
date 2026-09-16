from __future__ import annotations

from typing import cast
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from milai.api.auth import authenticated_context
from milai.api.errors import ApiError
from milai.application.errors import (
    BlobPurgeRace,
    EvidenceContentUnavailable,
    EvidenceDataModeBlocked,
    EvidenceNotFound,
    EvidencePayloadTooLarge,
    IdempotencyConflict,
    TenantMismatch,
)
from milai.application.evidence import EvidenceService, EvidenceView
from milai.domain import EvidenceIngestRequest
from milai.persistence import SessionContext

evidence_blueprint = Blueprint("evidence", __name__, url_prefix="/v1/evidence")


@evidence_blueprint.before_request
def require_authentication() -> None:
    authenticated_context(current_app)


def _service() -> EvidenceService:
    return cast(EvidenceService, current_app.extensions["milai.evidence_service"])


def _context() -> SessionContext:
    return cast(SessionContext, g.session_context)


def _validation_details(error: ValidationError) -> dict[str, object]:
    return {
        "fields": [
            {"path": ".".join(str(item) for item in issue["loc"]), "type": issue["type"]}
            for issue in error.errors(include_url=False, include_input=False)
        ]
    }


@evidence_blueprint.post("")
def ingest_evidence():  # type: ignore[no-untyped-def]
    idempotency_key = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(idempotency_key) <= 128:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Idempotency-Key must contain between 1 and 128 characters.",
            status_code=400,
        )
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(
            code="INVALID_REQUEST",
            message="A JSON object body is required.",
            status_code=400,
        )
    try:
        command = EvidenceIngestRequest.model_validate(payload)
        result = _service().ingest(_context(), command, idempotency_key)
    except ValidationError as exc:
        raise ApiError(
            code="INVALID_REQUEST",
            message="Evidence payload validation failed.",
            status_code=400,
            details=_validation_details(exc),
        ) from exc
    except TenantMismatch as exc:
        raise ApiError(
            code="TENANT_MISMATCH", message="Tenant context mismatch.", status_code=403
        ) from exc
    except IdempotencyConflict as exc:
        raise ApiError(
            code="IDEMPOTENCY_CONFLICT",
            message="The idempotency key was already used for another request.",
            status_code=409,
        ) from exc
    except EvidencePayloadTooLarge as exc:
        raise ApiError(
            code="PAYLOAD_TOO_LARGE",
            message="Evidence content exceeds the configured byte limit.",
            status_code=413,
        ) from exc
    except EvidenceDataModeBlocked as exc:
        raise ApiError(
            code="DATA_MODE_BLOCKED",
            message="Evidence classification is not allowed by the active data mode.",
            status_code=403,
        ) from exc
    except BlobPurgeRace as exc:
        raise ApiError(
            code="BLOB_PURGE_RACE",
            message="Evidence content is concurrently being purged; retry with a new request.",
            status_code=409,
            retryable=True,
        ) from exc

    return (
        jsonify(
            {
                "evidence_id": str(result.evidence_id),
                "blob_id": str(result.blob_id),
                "outbox_id": str(result.outbox_id),
                "replayed": result.replayed,
                "request_id": g.request_id,
            }
        ),
        200 if result.replayed else 201,
    )


def _evidence_payload(view: EvidenceView) -> dict[str, object]:
    record = view.record
    return {
        "tenant_id": str(record.tenant_id),
        "evidence_id": str(record.evidence_id),
        "source_type": record.source_type,
        "source_ref": record.source_ref,
        "subject_id": record.subject_id,
        "speaker": record.source_speaker or "unknown",
        "speaker_source": record.speaker_source,
        "source_context": (
            {
                "session_id": record.source_session_id,
                "turn_id": record.source_turn_id,
                "turn_ordinal": record.source_turn_ordinal,
                "round_id": record.source_round_id,
                "round_ordinal": record.source_round_ordinal,
                "previous_turn_id": record.previous_source_turn_id,
                "next_turn_id": record.next_source_turn_id,
            }
            if record.source_context_source != "UNKNOWN"
            else None
        ),
        "source_context_source": record.source_context_source,
        "observed_at": record.observed_at.isoformat(),
        "captured_at": record.captured_at.isoformat(),
        "blob_id": str(record.blob_id),
        "content_hash": record.content_hash,
        "media_type": record.media_type,
        "permission_snapshot": record.permission_snapshot,
        "retention_state": record.retention_state,
        "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
        "revocation_reason": record.revocation_reason,
        "content": view.content,
    }


@evidence_blueprint.get("/<uuid:evidence_id>")
def get_evidence(evidence_id: UUID):  # type: ignore[no-untyped-def]
    try:
        view = _service().get(_context(), evidence_id)
    except EvidenceNotFound as exc:
        raise ApiError(
            code="EVIDENCE_NOT_FOUND", message="Evidence was not found.", status_code=404
        ) from exc
    except EvidenceContentUnavailable as exc:
        raise ApiError(
            code="EVIDENCE_UNAVAILABLE",
            message="Evidence content failed integrity or availability checks.",
            status_code=503,
            retryable=False,
        ) from exc
    payload = _evidence_payload(view)
    payload["request_id"] = g.request_id
    return jsonify(payload)


@evidence_blueprint.get("/<uuid:evidence_id>/lineage")
def get_evidence_lineage(evidence_id: UUID):  # type: ignore[no-untyped-def]
    try:
        view, claim_versions, open_issues = _service().lineage(_context(), evidence_id)
    except EvidenceNotFound as exc:
        raise ApiError(
            code="EVIDENCE_NOT_FOUND", message="Evidence was not found.", status_code=404
        ) from exc
    return jsonify(
        {
            "evidence": _evidence_payload(view),
            "claim_version_refs": claim_versions,
            "open_issue_refs": open_issues,
            "request_id": g.request_id,
        }
    )
