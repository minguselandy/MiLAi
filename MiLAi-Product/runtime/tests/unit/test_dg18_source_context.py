from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from milai.application.evidence import _request_fingerprint
from milai.domain.evidence import EvidenceIngestRequest


def _payload() -> dict[str, object]:
    return {
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": "opaque://turn-one",
        "subject_id": "subject-not-session",
        "speaker": "user",
        "source_context": {
            "session_id": "session-a",
            "turn_id": "turn-1",
            "turn_ordinal": 1,
            "round_id": "round-0",
            "round_ordinal": 0,
            "previous_turn_id": "turn-0",
            "next_turn_id": None,
        },
        "observed_at": "2026-08-27T00:00:00+00:00",
        "content": "Structured source context is independent of body text.",
        "permission_snapshot": {"readable": True},
    }


def test_r1b_optional_source_context_is_typed_and_part_of_idempotency_identity() -> None:
    tenant_id = UUID("11111111-1111-4111-8111-111111111111")
    first = EvidenceIngestRequest.model_validate(_payload())
    changed_payload = _payload()
    changed_context = dict(changed_payload["source_context"])  # type: ignore[arg-type]
    changed_context["round_ordinal"] = 1
    changed_context["round_id"] = "round-1"
    changed_payload["source_context"] = changed_context
    changed = EvidenceIngestRequest.model_validate(changed_payload)

    assert first.source_context is not None
    assert first.source_context.session_id == "session-a"
    assert first.source_context.turn_ordinal == 1
    assert _request_fingerprint(tenant_id, first) != _request_fingerprint(tenant_id, changed)


def test_r1b_partial_or_self_referential_source_context_fails_closed() -> None:
    partial = _payload()
    partial["source_context"] = {"session_id": "session-a", "turn_id": "turn-1"}
    with pytest.raises(ValidationError):
        EvidenceIngestRequest.model_validate(partial)

    self_adjacent = _payload()
    source_context = dict(self_adjacent["source_context"])  # type: ignore[arg-type]
    source_context["previous_turn_id"] = "turn-1"
    self_adjacent["source_context"] = source_context
    with pytest.raises(ValidationError, match="cannot be adjacent to itself"):
        EvidenceIngestRequest.model_validate(self_adjacent)


def test_r1b_legacy_capture_without_source_context_remains_valid() -> None:
    payload = _payload()
    payload.pop("source_context")
    request = EvidenceIngestRequest.model_validate(payload)

    assert request.source_context is None

