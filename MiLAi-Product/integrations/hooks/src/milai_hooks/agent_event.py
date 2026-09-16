from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Protocol, cast

from milai_client import EvidenceCaptureRequest, EvidenceSourceContext

EventType = Literal[
    "USER_MESSAGE",
    "ASSISTANT_MESSAGE",
    "TOOL_RESULT",
    "ARTIFACT_CHANGE",
    "SESSION_MARKER",
]

_SOURCE_TYPE: dict[EventType, str] = {
    "USER_MESSAGE": "USER_OBSERVATION",
    "ASSISTANT_MESSAGE": "ASSISTANT_OBSERVATION",
    "TOOL_RESULT": "TOOL_OBSERVATION",
    "ARTIFACT_CHANGE": "ARTIFACT_OBSERVATION",
    "SESSION_MARKER": "HOST_SESSION_MARKER",
}
_SPEAKER = {
    "USER_MESSAGE": "user",
    "ASSISTANT_MESSAGE": "assistant",
    "TOOL_RESULT": "tool",
    "ARTIFACT_CHANGE": "tool",
    "SESSION_MARKER": "system",
}
_SPARSE_JOURNAL_TYPES: dict[EventType, tuple[str, str, dict[str, str]]] = {
    "USER_MESSAGE": ("DIALOGUE", "MESSAGE", {"role": "USER"}),
    "ASSISTANT_MESSAGE": ("DIALOGUE", "MESSAGE", {"role": "ASSISTANT"}),
    "SESSION_MARKER": ("LIFECYCLE", "SESSION_BOUNDARY", {}),
}


class EvidenceCaptureClient(Protocol):
    def capture_evidence(self, payload: EvidenceCaptureRequest, *, operation_id: str) -> Any: ...


class HostEventJournalClient(Protocol):
    def append_host_execution_event(
        self,
        payload: Mapping[str, Any],
        *,
        operation_id: str,
    ) -> dict[str, Any]: ...


def capture_host_agent_event(
    client: EvidenceCaptureClient,
    raw_event: Mapping[str, Any],
    *,
    permission_snapshot: Mapping[str, Any],
    data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"] = "PERSONAL",
) -> dict[str, Any]:
    """Persist one Host-authored event as Raw Evidence without canonical promotion."""

    event = _event(raw_event)
    event_type = cast(EventType, event["event_type"])
    source_context = _source_context(event)
    request = EvidenceCaptureRequest(
        source_type=_SOURCE_TYPE[event_type],
        source_ref=event["source_id"],
        subject_id=event["subject_id"],
        speaker=cast(Any, _SPEAKER[event_type]),
        source_context=source_context,
        observed_at=event["observed_at"],
        content=event["content"],
        data_classification=data_classification,
        permission_snapshot=dict(permission_snapshot),
        retention_state="READABLE",
    )
    operation_identity = f"{event['source_id']}\0{event['event_id']}"
    operation_id = "host-agent-event:" + hashlib.sha256(operation_identity.encode()).hexdigest()
    receipt = client.capture_evidence(request, operation_id=operation_id)
    raw_receipt = getattr(receipt, "raw", receipt)
    return {
        "status": "RAW_EVIDENCE_CAPTURED",
        "event_id": event["event_id"],
        "event_type": event_type,
        "operation_id": operation_id,
        "canonical_mutation": False,
        "receipt": raw_receipt,
    }


def journal_sparse_host_agent_event(
    client: HostEventJournalClient,
    raw_event: Mapping[str, Any],
    *,
    evidence_id: str,
    principal_binding_digest: str,
    project_id: str,
    task_ref: str,
) -> dict[str, Any]:
    """Index one low-volume Host observation without copying its Evidence content."""

    event = _event(raw_event)
    event_type = cast(EventType, event["event_type"])
    mapping = _SPARSE_JOURNAL_TYPES.get(event_type)
    if mapping is None:
        return {
            "status": "NOT_JOURNALED_REQUIRES_AGGREGATION",
            "event_id": event["event_id"],
            "event_type": event_type,
        }
    binding = validate_host_event_binding(
        principal_binding_digest=principal_binding_digest,
        project_id=project_id,
        task_ref=task_ref,
    )
    if not evidence_id.strip():
        raise ValueError("Host Event Evidence identity is required")

    event_family, journal_event_type, bounded_payload = mapping
    operation_identity = f"{event['source_id']}\0{event['event_id']}\0sparse-journal-v1"
    operation_id = "host-execution-event:" + hashlib.sha256(operation_identity.encode()).hexdigest()
    receipt = client.append_host_execution_event(
        {
            **binding,
            "event_family": event_family,
            "event_type": journal_event_type,
            "observed_at": event["observed_at"],
            "evidence_refs": [evidence_id],
            "bounded_payload": bounded_payload,
        },
        operation_id=operation_id,
    )
    return {
        "status": "SHADOW_EVENT_JOURNALED",
        "event_id": event["event_id"],
        "event_type": event_type,
        "operation_id": operation_id,
        "canonical_mutation": False,
        "working_state_mutation": False,
        "receipt": receipt,
    }


def validate_host_event_binding(
    *,
    principal_binding_digest: str,
    project_id: str,
    task_ref: str,
) -> dict[str, str]:
    """Validate trusted Host configuration before any Evidence write occurs."""

    if re.fullmatch(r"[0-9a-f]{64}", principal_binding_digest) is None:
        raise ValueError("Host Event principal binding digest is invalid")
    if not project_id.strip() or not task_ref.strip():
        raise ValueError("Host Event project and task bindings are required")
    return {
        "principal_binding_digest": principal_binding_digest,
        "project_id": project_id,
        "task_ref": task_ref,
    }


def _event(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "event_id",
        "event_type",
        "session_id",
        "source_id",
        "subject_id",
        "observed_at",
        "content",
        "turn_id",
        "turn_ordinal",
        "round_id",
        "round_ordinal",
        "previous_turn_id",
        "next_turn_id",
    }
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError("HostAgentEvent contains unsupported fields: " + ", ".join(unexpected))
    if value.get("schema_version") != "host-agent-event-v1":
        raise ValueError("HostAgentEvent schema_version is invalid")
    event_type = value.get("event_type")
    if event_type not in _SOURCE_TYPE:
        raise ValueError("HostAgentEvent event_type is invalid")
    event: dict[str, Any] = dict(value)
    for key in ("event_id", "session_id", "source_id", "subject_id", "content"):
        field = event.get(key)
        if not isinstance(field, str) or not field.strip():
            raise ValueError(f"HostAgentEvent {key} is required")
    if len(cast(str, event["event_id"])) > 96:
        raise ValueError("HostAgentEvent event_id is too long")
    observed_at = event.get("observed_at")
    if not isinstance(observed_at, str):
        raise ValueError("HostAgentEvent observed_at is required")
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("HostAgentEvent observed_at is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValueError("HostAgentEvent observed_at must be timezone-aware")
    if event_type != "SESSION_MARKER":
        if not isinstance(event.get("turn_id"), str) or not event["turn_id"]:
            raise ValueError("HostAgentEvent turn_id is required for content events")
        ordinal = event.get("turn_ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise ValueError("HostAgentEvent turn_ordinal is required for content events")
    return event


def _source_context(event: Mapping[str, Any]) -> EvidenceSourceContext | None:
    turn_id = event.get("turn_id")
    turn_ordinal = event.get("turn_ordinal")
    if not isinstance(turn_id, str) or not isinstance(turn_ordinal, int):
        return None
    round_id = event.get("round_id", turn_id)
    round_ordinal = event.get("round_ordinal", turn_ordinal)
    return EvidenceSourceContext(
        session_id=cast(str, event["session_id"]),
        turn_id=turn_id,
        turn_ordinal=turn_ordinal,
        round_id=cast(str, round_id),
        round_ordinal=cast(int, round_ordinal),
        previous_turn_id=cast(str | None, event.get("previous_turn_id")),
        next_turn_id=cast(str | None, event.get("next_turn_id")),
    )
