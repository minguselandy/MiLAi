from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from milai.domain import (
    ContextValidationState,
    ContextValidationTokenCodec,
    ContextValidationTokenError,
    DependencyFrontier,
    MemorySlotCoverage,
    PrepareContextRequest,
)

SECRET = "context-validation-secret-that-is-long-enough"
DIGEST = "a" * 64


def _coverage() -> MemorySlotCoverage:
    return MemorySlotCoverage(
        scope={"project_ids": ["milai"]},
        authority_supported="INFORMATIONAL",
        consistency_supported="CANONICAL_REQUIRED",
        temporal_coverage="CURRENT",
        evidence_depth="NONE",
        policy_identity="d" * 64,
        dependency_frontier=DependencyFrontier(canonical_position=7),
    )


def _state() -> ContextValidationState:
    issued_at = datetime(2026, 8, 23, tzinfo=UTC)
    return ContextValidationState(
        tenant_id=uuid4(),
        principal_profile="reader",
        binding_digest=DIGEST,
        canonical_position=7,
        issue_revision_digest="b" * 64,
        issue_ids=("issue-1",),
        slot_coverage=_coverage(),
        capsule_id="capsule-1",
        context_hash="c" * 64,
        prepare_calls=1,
        full_recall_calls=1,
        delta_refreshes=0,
        validation_calls=0,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )


def test_context_validation_token_is_bound_and_expires() -> None:
    state = _state()
    codec = ContextValidationTokenCodec(SECRET)
    token = codec.issue(state)

    assert (
        codec.decode(
            token,
            expected_tenant_id=state.tenant_id,
            expected_profile=state.principal_profile,
            expected_binding_digest=state.binding_digest,
            now=state.issued_at + timedelta(seconds=1),
        )
        == state
    )
    with pytest.raises(ContextValidationTokenError, match="profile mismatch"):
        codec.decode(
            token,
            expected_tenant_id=state.tenant_id,
            expected_profile="submitter",
            expected_binding_digest=state.binding_digest,
            now=state.issued_at + timedelta(seconds=1),
        )
    with pytest.raises(ContextValidationTokenError, match="binding mismatch"):
        codec.decode(
            token,
            expected_tenant_id=state.tenant_id,
            expected_profile=state.principal_profile,
            expected_binding_digest="d" * 64,
            now=state.issued_at + timedelta(seconds=1),
        )
    with pytest.raises(ContextValidationTokenError, match="expired"):
        codec.decode(
            token,
            expected_tenant_id=state.tenant_id,
            expected_profile=state.principal_profile,
            expected_binding_digest=state.binding_digest,
            now=state.expires_at,
        )


def test_context_validation_token_rejects_forgery_and_invalid_state() -> None:
    state = _state()
    codec = ContextValidationTokenCodec(SECRET)
    token = codec.issue(state)
    with pytest.raises(ContextValidationTokenError, match="invalid"):
        codec.decode(
            token[:-1] + ("a" if token[-1] != "a" else "b"),
            expected_tenant_id=state.tenant_id,
            expected_profile=state.principal_profile,
            expected_binding_digest=state.binding_digest,
            now=state.issued_at,
        )
    with pytest.raises(ValueError, match="expiry"):
        codec.issue(replace(state, expires_at=state.issued_at))


def test_prepare_context_contract_is_closed_and_action_safe() -> None:
    base = {
        "query": "current project state",
        "active_goal": "finish project",
        "session_id": "session-1",
        "agent_id": "openworker-1",
        "profile_id": "reader-lite",
        "task_epoch": "task-1",
        "event": "TASK_START",
        "compiler_digest": DIGEST,
        "router_digest": DIGEST,
        "tokenizer_digest": DIGEST,
        "policy_digest": DIGEST,
    }
    request = PrepareContextRequest.model_validate(base)
    assert request.memory_token_budget == 512
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PrepareContextRequest.model_validate({**base, "cache_validated": True})
    with pytest.raises(ValidationError, match="ACTION_SAFE"):
        PrepareContextRequest.model_validate({**base, "event": "ACTION_PROPOSED"})
