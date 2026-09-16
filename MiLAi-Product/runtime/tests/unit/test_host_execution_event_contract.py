from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from milai.domain.host_execution_event import (
    HOST_EXECUTION_EVENT_WIRE_SCHEMA,
    HostExecutionEventAppendRequest,
    HostExecutionEventWindowRequest,
    host_execution_event_idempotency_key,
    host_execution_event_request_fingerprint,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EVIDENCE_ID = UUID("22222222-2222-4222-8222-222222222222")


def _append(**overrides: object) -> HostExecutionEventAppendRequest:
    value: dict[str, object] = {
        "principal_binding_digest": "a" * 64,
        "project_id": "project-one",
        "task_ref": "task-one",
        "event_family": "EXECUTION",
        "event_type": "TEST_RESULT",
        "observed_at": datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        "evidence_refs": [],
        "bounded_payload": {"status": "FAILED", "suite": "unit"},
    }
    value.update(overrides)
    return HostExecutionEventAppendRequest.model_validate(value)


def test_event_contract_is_extensible_and_fingerprint_is_stable() -> None:
    request = _append(event_family="BROWSER", event_type="NAVIGATION_RESULT")
    first = host_execution_event_request_fingerprint(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        request=request,
    )
    second = host_execution_event_request_fingerprint(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        request=request,
    )
    assert first == second
    assert len(first) == 64
    assert HOST_EXECUTION_EVENT_WIRE_SCHEMA == "host-execution-event-v1"


def test_idempotency_key_is_stable_and_namespaced_to_exact_binding() -> None:
    request = _append()
    first = host_execution_event_idempotency_key(
        actor_id=ACTOR_ID,
        request=request,
        public_operation_id="public-operation",
    )
    replay = host_execution_event_idempotency_key(
        actor_id=ACTOR_ID,
        request=request,
        public_operation_id="public-operation",
    )
    other_principal = host_execution_event_idempotency_key(
        actor_id=ACTOR_ID,
        request=request.model_copy(update={"principal_binding_digest": "b" * 64}),
        public_operation_id="public-operation",
    )

    assert first == replay
    assert first != other_principal
    assert len(first) == 64


def test_dialogue_is_reference_only_and_never_copies_message_content() -> None:
    request = _append(
        event_family="DIALOGUE",
        event_type="MESSAGE",
        evidence_refs=[EVIDENCE_ID],
        bounded_payload={"role": "USER"},
    )
    assert request.evidence_refs == [EVIDENCE_ID]

    for overrides, message in (
        ({"evidence_refs": []}, "Evidence ref"),
        ({"bounded_payload": {}}, "role"),
        ({"bounded_payload": {"role": "USER", "content": "raw"}}, "role metadata"),
    ):
        invalid = {
            "event_family": "DIALOGUE",
            "event_type": "MESSAGE",
            "evidence_refs": [EVIDENCE_ID],
            "bounded_payload": {"role": "USER"},
            **overrides,
        }
        with pytest.raises(ValidationError, match=message):
            _append(**invalid)


def test_event_payload_and_reference_bounds_fail_closed() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _append(evidence_refs=[EVIDENCE_ID, EVIDENCE_ID])
    with pytest.raises(ValidationError, match="16384"):
        _append(bounded_payload={"value": "x" * 17_000})
    with pytest.raises(ValidationError, match="explicit UTC offset"):
        _append(observed_at=datetime(2026, 9, 5, 1, 0))


def test_window_is_bounded_and_binding_rejects_client_authority_fields() -> None:
    window = HostExecutionEventWindowRequest.model_validate(
        {
            "principal_binding_digest": "a" * 64,
            "project_id": "project-one",
            "task_ref": "task-one",
        }
    )
    assert window.after_position == 0
    assert window.limit == 100
    with pytest.raises(ValidationError):
        HostExecutionEventWindowRequest.model_validate(
            {
                **window.model_dump(),
                "limit": 201,
                "tenant_id": str(TENANT_ID),
            }
        )
