from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

HOST_EXECUTION_EVENT_WIRE_SCHEMA = "host-execution-event-v1"
MAX_HOST_EXECUTION_EVENT_PAYLOAD_BYTES = 16_384
MAX_HOST_EXECUTION_EVENT_EVIDENCE_REFS = 64
MAX_HOST_EXECUTION_EVENT_WINDOW = 200


class HostExecutionEventBinding(BaseModel):
    """Host-owned task binding; MCP/model inputs never control these fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    principal_binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1, max_length=512)
    task_ref: str = Field(min_length=1, max_length=1024)


class HostExecutionEventAppendRequest(HostExecutionEventBinding):
    """One sparse, observation-first Event append request."""

    event_family: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )
    event_type: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )
    observed_at: datetime
    evidence_refs: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_HOST_EXECUTION_EVENT_EVIDENCE_REFS,
    )
    bounded_payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include an explicit UTC offset")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs must be unique")
        if len(_canonical_json(self.bounded_payload)) > MAX_HOST_EXECUTION_EVENT_PAYLOAD_BYTES:
            raise ValueError("bounded_payload exceeds 16384 bytes")
        if self.event_family == "DIALOGUE" and self.event_type == "MESSAGE":
            if not self.evidence_refs:
                raise ValueError("DIALOGUE/MESSAGE requires at least one exact Evidence ref")
            if set(self.bounded_payload) - {"role"}:
                raise ValueError("DIALOGUE/MESSAGE payload may contain only role metadata")
            if self.bounded_payload.get("role") not in {"USER", "ASSISTANT"}:
                raise ValueError("DIALOGUE/MESSAGE role must be USER or ASSISTANT")
        return self


class HostExecutionEventWindowRequest(HostExecutionEventBinding):
    """Read a bounded task-local window after an exclusive position watermark."""

    after_position: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=MAX_HOST_EXECUTION_EVENT_WINDOW)


def host_execution_event_request_fingerprint(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    request: HostExecutionEventAppendRequest,
) -> str:
    material: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "actor_id": str(actor_id),
        **request.model_dump(mode="json"),
        "contract": HOST_EXECUTION_EVENT_WIRE_SCHEMA,
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def host_execution_event_idempotency_key(
    *,
    actor_id: UUID,
    request: HostExecutionEventAppendRequest,
    public_operation_id: str,
) -> str:
    """Namespace a Host-provided retry key to its exact actor/task binding."""

    material = {
        "actor_id": str(actor_id),
        "principal_binding_digest": request.principal_binding_digest,
        "project_id": request.project_id,
        "task_ref": request.task_ref,
        "public_operation_id": public_operation_id,
        "operation": "HOST_EXECUTION_EVENT_APPEND",
    }
    return hashlib.sha256(_canonical_json(material)).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Host execution Event payload must be canonical JSON") from exc
