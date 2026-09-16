from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from milai.domain.host_execution_event import (
    HOST_EXECUTION_EVENT_WIRE_SCHEMA,
    HostExecutionEventAppendRequest,
    HostExecutionEventWindowRequest,
    host_execution_event_idempotency_key,
    host_execution_event_request_fingerprint,
)
from milai.persistence import SessionContext
from milai.persistence.host_execution_event_repository import (
    HostExecutionEventAppend,
    HostExecutionEventRecord,
    HostExecutionEventRepository,
)


@dataclass(frozen=True, slots=True)
class HostExecutionEventExecution:
    body: dict[str, Any]
    status_code: int = 200


class HostExecutionEventService:
    """Store observations without interpreting them as cognitive or Canonical truth."""

    def __init__(self, repository: HostExecutionEventRepository) -> None:
        self._repository = repository

    def append(
        self,
        context: SessionContext,
        request: HostExecutionEventAppendRequest,
        operation_id: str,
    ) -> HostExecutionEventExecution:
        result = self._repository.append(
            context,
            HostExecutionEventAppend(
                request=request,
                operation_id=host_execution_event_idempotency_key(
                    actor_id=context.actor_id,
                    request=request,
                    public_operation_id=operation_id,
                ),
                request_fingerprint=host_execution_event_request_fingerprint(
                    tenant_id=context.tenant_id,
                    actor_id=context.actor_id,
                    request=request,
                ),
            ),
        )
        return HostExecutionEventExecution(
            {
                "schema_version": HOST_EXECUTION_EVENT_WIRE_SCHEMA,
                "status": "APPENDED",
                "event": _record_envelope(result.record),
                "replayed": result.replayed,
            },
            status_code=200 if result.replayed else 201,
        )

    def read_window(
        self,
        context: SessionContext,
        request: HostExecutionEventWindowRequest,
    ) -> HostExecutionEventExecution:
        result = self._repository.read_window(context, request)
        return HostExecutionEventExecution(
            {
                "schema_version": HOST_EXECUTION_EVENT_WIRE_SCHEMA,
                "status": "WINDOW",
                "after_position": result.after_position,
                "next_position": result.next_position,
                "visible_high_watermark": result.visible_high_watermark,
                "has_more": result.has_more,
                "events": [_record_envelope(event) for event in result.events],
            }
        )


def _record_envelope(record: HostExecutionEventRecord) -> dict[str, Any]:
    return {
        "event_id": str(record.event_id),
        "position": record.position,
        "event_family": record.event_family,
        "event_type": record.event_type,
        "observed_at": record.observed_at.isoformat(),
        "bounded_payload": record.bounded_payload,
        "evidence_refs": [str(item) for item in record.evidence_refs],
        "warnings": [
            {
                "code": "EVIDENCE_REFERENCE_STALE_OR_UNREADABLE",
                "evidence_id": str(item),
            }
            for item in record.stale_evidence_refs
        ],
        "created_at": record.created_at.isoformat(),
    }
