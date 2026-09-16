from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from milai.domain.host_cognitive_state import (
    HOST_COGNITIVE_AUTHORITY,
    HostCognitiveStateUpdateRequest,
    extract_evidence_refs,
    request_fingerprint,
    state_digest,
)


def _request(**overrides: object) -> HostCognitiveStateUpdateRequest:
    value: dict[str, object] = {
        "principal_binding_digest": "a" * 64,
        "project_id": "project-one",
        "scope_type": "TASK",
        "scope_ref": "task-one",
        "state_id": None,
        "expected_version": 0,
        "payload": {
            "task": {"active_goal": "implement persisted Host state"},
            "known": [],
            "missing": [],
            "next_actions": [],
        },
    }
    value.update(overrides)
    return HostCognitiveStateUpdateRequest.model_validate(value)


def test_host_working_payload_extracts_exact_refs_without_semantic_promotion() -> None:
    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"
    payload = {
        "known": [
            {
                "text": "Host assertion only",
                "basis": [{"evidence_id": first}],
                "basis_relation": "HOST_ASSERTED",
            }
        ],
        "memory_needs": [{"evidence_refs": [second, first]}],
    }
    assert extract_evidence_refs(payload) == (UUID(first), UUID(second))
    request = _request(payload=payload)
    assert len(state_digest(request, request.payload)) == 64
    assert HOST_COGNITIVE_AUTHORITY == "HOST_WORKING"


@pytest.mark.parametrize(
    "payload",
    [
        {"known": [{"evidence_id": "not-a-uuid"}]},
        {"known": [{"evidence_refs": "not-an-array"}]},
    ],
)
def test_reserved_evidence_pointer_fields_fail_closed(payload: object) -> None:
    with pytest.raises(ValidationError, match=r"UUID|array"):
        _request(payload=payload)


def test_create_and_update_cas_shape_is_unambiguous() -> None:
    state_id = "33333333-3333-4333-8333-333333333333"
    with pytest.raises(ValidationError, match="create requires") as rejected:
        _request(state_id=state_id, expected_version=0)
    assert rejected.value.errors(include_input=False)[0]["loc"] == ("expected_version",)
    with pytest.raises(ValidationError, match="create requires"):
        _request(state_id=None, expected_version=1)
    assert _request(state_id=state_id, expected_version=4).expected_version == 4


def test_reference_capacity_preserves_every_pointer_and_bounds_unique_refs() -> None:
    refs = [str(UUID(int=i + 1)) for i in range(1024)]
    payload = {"evidence_refs": refs, "nested": {"evidence_id": refs[-1]}}
    assert _request(payload=payload).payload == payload
    assert len(extract_evidence_refs(payload)) == 1024
    with pytest.raises(ValidationError, match="more than 1024"):
        _request(payload={"evidence_refs": [*refs, str(UUID(int=1025))]})
    with pytest.raises(ValidationError, match="exceeds 65536") as rejected:
        _request(payload={"evidence_refs": refs, "text": "x" * 65536})
    assert rejected.value.errors(include_input=False)[0]["loc"] == ("payload",)


@pytest.mark.parametrize("text", ["note\n", "  indented\r\n", "\tcode\n\n", "\u3000中文\u00a0",
                                  '  "quoted" \\ escaped\n', "", "   "])
def test_payload_preserves_strings_and_distinct_keys_at_every_depth(text: str) -> None:
    payload = {"text": text, " text ": {" key ": [text, {"nested": text}]},
               "key": 1, " key": 2, "other": [None, True, 3.5]}
    request = _request(payload=payload, project_id=" project-one ", scope_ref=" task-one\n",
                       principal_binding_digest=" " + "a" * 64 + "\n")
    assert request.payload == payload
    assert request.project_id == "project-one"
    assert request.scope_ref == "task-one"
    assert request.principal_binding_digest == "a" * 64


def test_payload_whitespace_is_part_of_state_and_operation_identity() -> None:
    first = _request(payload={"text": "note"})
    second = _request(payload={"text": "note\n"})
    tenant = UUID("11111111-1111-4111-8111-111111111111")
    actor = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert state_digest(first, first.payload) != state_digest(second, second.payload)
    assert request_fingerprint(tenant_id=tenant, actor_id=actor, request=first) != (
        request_fingerprint(tenant_id=tenant, actor_id=actor, request=second)
    )
