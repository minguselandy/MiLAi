from __future__ import annotations

import pytest
from pydantic import ValidationError

from milai.domain.context_preparation import MemoryNeedSignature, PrepareContextRequest, StateKeyRef


def _signature() -> MemoryNeedSignature:
    return MemoryNeedSignature(
        scope={"project_ids": ["release"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        claim_ids=[],
        state_keys=[
            StateKeyRef(
                scope={"project_ids": ["release"]},
                subject="release",
                predicate="release.target",
                claim_type="PROJECT_STATE",
            )
        ],
        open_issue_ids=[],
        temporal_need="CURRENT",
        evidence_need="SUPPORT_POINTERS",
        intent_class="CURRENT_STATE",
    )


def _request_payload() -> dict[str, object]:
    signature = _signature()
    return {
        "query": "current target",
        "active_goal": "prepare release",
        "session_id": "session",
        "agent_id": "agent",
        "profile_id": "reader-lite",
        "task_epoch": "epoch",
        "event": "EXPLICIT_MEMORY_REQUEST",
        "requested_route": "L0",
        "need_signature_id": signature.signature_id,
        "memory_need_signature": signature.model_dump(mode="json"),
        "state_key_ref": signature.state_keys[0].model_dump(mode="json"),
        "requested_scope": {"project_ids": ["release"]},
        "required_authority": "INFORMATIONAL",
        "consistency": "CANONICAL_REQUIRED",
        "compiler_digest": "a" * 64,
        "router_digest": "b" * 64,
        "tokenizer_digest": "c" * 64,
        "policy_digest": "d" * 64,
    }


def test_typed_need_signature_and_state_key_validate() -> None:
    request = PrepareContextRequest.model_validate(_request_payload())
    assert request.memory_need_signature is not None
    assert request.need_signature_id == request.memory_need_signature.signature_id
    assert request.state_key_ref is not None
    assert request.state_key_ref.predicate == "release.target"


def test_known_object_accepts_a_typed_state_key_without_claim_id() -> None:
    payload = _request_payload()
    payload["event"] = "KNOWN_OBJECT"

    request = PrepareContextRequest.model_validate(payload)

    assert request.known_claim_id is None
    assert request.state_key_ref is not None


def test_need_signature_identity_fails_closed_at_the_schema_boundary() -> None:
    payload = _request_payload()
    payload["need_signature_id"] = "need:" + "0" * 64
    with pytest.raises(ValidationError, match="identity"):
        PrepareContextRequest.model_validate(payload)

    payload = _request_payload()
    payload["memory_need_signature"] = None
    with pytest.raises(ValidationError, match="typed memory_need_signature"):
        PrepareContextRequest.model_validate(payload)
