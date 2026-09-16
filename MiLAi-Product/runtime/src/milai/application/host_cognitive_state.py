from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from milai.domain.host_cognitive_state import (
    HOST_COGNITIVE_AUTHORITY,
    HOST_COGNITIVE_SCHEMA,
    HOST_COGNITIVE_WIRE_SCHEMA,
    HostCognitiveStateGetRequest,
    HostCognitiveStateUpdateRequest,
    extract_evidence_refs,
    request_fingerprint,
    state_digest,
)
from milai.persistence import SessionContext
from milai.persistence.host_cognitive_state_repository import (
    HostCognitiveStateRecord,
    HostCognitiveStateRepository,
    HostCognitiveStateWrite,
)


@dataclass(frozen=True, slots=True)
class HostCognitiveExecution:
    body: dict[str, Any]
    status_code: int = 200


class HostCognitiveStateService:
    """Persist Host-owned semantics without interpreting or promoting them."""

    def __init__(self, repository: HostCognitiveStateRepository) -> None:
        self._repository = repository

    def get(
        self,
        context: SessionContext,
        request: HostCognitiveStateGetRequest,
    ) -> HostCognitiveExecution:
        record = self._repository.get_current(context, request)
        if record is None:
            return HostCognitiveExecution(_absent(request))
        return HostCognitiveExecution(_record_envelope(record))

    def update(
        self,
        context: SessionContext,
        request: HostCognitiveStateUpdateRequest,
        operation_id: str,
    ) -> HostCognitiveExecution:
        evidence_refs = extract_evidence_refs(request.payload)
        result = self._repository.write(
            context,
            HostCognitiveStateWrite(
                request=request,
                operation_id=operation_id,
                request_fingerprint=request_fingerprint(
                    tenant_id=context.tenant_id,
                    actor_id=context.actor_id,
                    request=request,
                ),
                state_digest=state_digest(request, request.payload),
                evidence_refs=evidence_refs,
            ),
        )
        return HostCognitiveExecution(
            _record_envelope(result.record, replayed=result.replayed),
            status_code=200 if result.replayed or result.record.version > 1 else 201,
        )


def _absent(request: HostCognitiveStateGetRequest) -> dict[str, Any]:
    return {
        "schema_version": HOST_COGNITIVE_WIRE_SCHEMA,
        "status": "ABSENT",
        "state_id": None,
        "state_version_id": None,
        "version": 0,
        "authority": HOST_COGNITIVE_AUTHORITY,
        "schema_name": HOST_COGNITIVE_SCHEMA,
        "scope": request.scope_type,
        "payload": {},
        "state_digest": None,
        "created_at": None,
        "updated_at": None,
        "expires_at": None,
        "warnings": [],
    }


def _record_envelope(
    record: HostCognitiveStateRecord,
    *,
    replayed: bool | None = None,
) -> dict[str, Any]:
    expired = record.expired
    warnings = [
        {
            "code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE",
            "evidence_id": str(evidence_id),
        }
        for evidence_id in record.stale_evidence_refs
    ]
    body: dict[str, Any] = {
        "schema_version": HOST_COGNITIVE_WIRE_SCHEMA,
        "status": "EXPIRED" if expired else record.lifecycle,
        "state_id": str(record.state_id),
        "state_version_id": str(record.state_version_id),
        "version": record.version,
        "authority": HOST_COGNITIVE_AUTHORITY,
        "schema_name": HOST_COGNITIVE_SCHEMA,
        "scope": record.scope_type,
        # Payload is opaque: an unreadable declared dependency cannot be safely
        # redacted at an inferred business-field boundary. Retain history, but
        # withhold this version's entire payload, including idempotent replays.
        "payload": {} if expired or record.lifecycle != "ACTIVE" or warnings else record.payload,
        "payload_withheld": bool(warnings),
        "state_digest": record.state_digest,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "warnings": warnings,
    }
    if replayed is not None:
        body["replayed"] = replayed
    return body
