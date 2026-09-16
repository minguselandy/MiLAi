from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from milai_client import EvidenceCaptureRequest

from milai_hooks.agent_event import capture_host_agent_event, journal_sparse_host_agent_event


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[EvidenceCaptureRequest, str]] = []
        self.journal_calls: list[tuple[dict[str, Any], str]] = []

    def capture_evidence(self, payload: EvidenceCaptureRequest, *, operation_id: str) -> Any:
        self.calls.append((payload, operation_id))
        return SimpleNamespace(raw={"evidence_id": "evidence-1", "replayed": False})

    def append_host_execution_event(
        self,
        payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self.journal_calls.append((payload, operation_id))
        return {"status": "APPENDED", "event": {"event_id": "journal-1"}}


def _event(event_type: str = "USER_MESSAGE") -> dict[str, object]:
    return {
        "schema_version": "host-agent-event-v1",
        "event_id": "event-1",
        "event_type": event_type,
        "session_id": "session-1",
        "source_id": "codex:session-1:turn-1",
        "subject_id": "user-1",
        "observed_at": "2026-09-03T10:00:00+08:00",
        "content": "Remember the deployment decision.",
        "turn_id": "turn-1",
        "turn_ordinal": 1,
    }


@pytest.mark.parametrize(
    ("event_type", "source_type", "speaker"),
    [
        ("USER_MESSAGE", "USER_OBSERVATION", "user"),
        ("ASSISTANT_MESSAGE", "ASSISTANT_OBSERVATION", "assistant"),
        ("TOOL_RESULT", "TOOL_OBSERVATION", "tool"),
    ],
)
def test_host_event_is_raw_evidence_without_canonical_promotion(
    event_type: str, source_type: str, speaker: str
) -> None:
    client = _Client()
    result = capture_host_agent_event(
        client,
        _event(event_type),
        permission_snapshot={"readable": True, "project_ids": ["p08"]},
    )

    request, operation_id = client.calls[0]
    assert request.source_type == source_type
    assert request.speaker == speaker
    assert request.source_context is not None
    assert request.source_context.session_id == "session-1"
    assert request.source_context.turn_id == "turn-1"
    assert request.permission_snapshot == {
        "readable": True,
        "project_ids": ["p08"],
    }
    expected_identity = hashlib.sha256(b"codex:session-1:turn-1\0event-1").hexdigest()
    assert operation_id == f"host-agent-event:{expected_identity}"
    assert result["canonical_mutation"] is False


def test_content_event_requires_real_turn_identity() -> None:
    event = _event()
    event.pop("turn_id")
    with pytest.raises(ValueError, match="turn_id is required"):
        capture_host_agent_event(
            _Client(),
            event,
            permission_snapshot={"readable": True},
        )


@pytest.mark.parametrize(
    ("event_type", "event_family", "journal_type", "bounded_payload"),
    [
        ("USER_MESSAGE", "DIALOGUE", "MESSAGE", {"role": "USER"}),
        ("ASSISTANT_MESSAGE", "DIALOGUE", "MESSAGE", {"role": "ASSISTANT"}),
        ("SESSION_MARKER", "LIFECYCLE", "SESSION_BOUNDARY", {}),
    ],
)
def test_sparse_journal_keeps_content_in_exact_evidence_only(
    event_type: str,
    event_family: str,
    journal_type: str,
    bounded_payload: dict[str, str],
) -> None:
    client = _Client()
    event = _event(event_type)
    if event_type == "SESSION_MARKER":
        event.pop("turn_id")
        event.pop("turn_ordinal")
    result = journal_sparse_host_agent_event(
        client,
        event,
        evidence_id="11111111-1111-4111-8111-111111111111",
        principal_binding_digest="a" * 64,
        project_id="project-one",
        task_ref="task-one",
    )

    payload, operation_id = client.journal_calls[0]
    assert payload["event_family"] == event_family
    assert payload["event_type"] == journal_type
    assert payload["bounded_payload"] == bounded_payload
    assert payload["evidence_refs"] == ["11111111-1111-4111-8111-111111111111"]
    assert "content" not in payload
    assert operation_id.startswith("host-execution-event:")
    assert result["canonical_mutation"] is False
    assert result["working_state_mutation"] is False


@pytest.mark.parametrize("event_type", ["TOOL_RESULT", "ARTIFACT_CHANGE"])
def test_high_volume_observations_require_later_aggregation(event_type: str) -> None:
    client = _Client()
    result = journal_sparse_host_agent_event(
        client,
        _event(event_type),
        evidence_id="11111111-1111-4111-8111-111111111111",
        principal_binding_digest="a" * 64,
        project_id="project-one",
        task_ref="task-one",
    )

    assert result["status"] == "NOT_JOURNALED_REQUIRES_AGGREGATION"
    assert client.journal_calls == []
