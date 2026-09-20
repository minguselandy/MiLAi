from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from milai.application.context_prepare.binding import binding_digest
from milai.domain import (
    ChatRequest,
    PrepareContextRequest,
    action_identity_digest,
    canonical_sha256,
)
from milai.persistence import SessionContext

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DIGEST = "a" * 64
ACTION = {"tool": "deploy", "arguments": {"environment": "staging"}}


def _prepare_request(**updates: object) -> PrepareContextRequest:
    value: dict[str, object] = {
        "query": "Deploy the current release",
        "active_goal": "Release safely",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "profile_id": "operator",
        "task_epoch": "task-1",
        "event": "ACTION_PROPOSED",
        "requested_scope": {"project_ids": ["milai"], "environment": "staging"},
        "required_authority": "ACTION_SAFE",
        "consistency": "CANONICAL_REQUIRED",
        "action_digest": canonical_sha256(ACTION),
        "compiler_digest": DIGEST,
        "router_digest": DIGEST,
        "tokenizer_digest": DIGEST,
        "policy_digest": DIGEST,
    }
    value.update(updates)
    return PrepareContextRequest.model_validate(value)


def test_action_identity_is_canonical_and_shared_with_prepare_binding() -> None:
    request = _prepare_request()
    identity = action_identity_digest(
        tenant_id=TENANT_ID,
        query=request.query,
        active_goal=request.active_goal,
        requested_scope=request.requested_scope,
        required_authority=request.required_authority,
        action_digest=request.action_digest or "",
    )
    reordered_identity = action_identity_digest(
        tenant_id=TENANT_ID,
        query=request.query,
        active_goal=request.active_goal,
        requested_scope={"environment": "staging", "project_ids": ["milai"]},
        required_authority=request.required_authority,
        action_digest=request.action_digest or "",
    )
    assert identity == reordered_identity
    assert len(identity) == 64

    context = SessionContext(TENANT_ID, ACTOR_ID)
    original_binding = binding_digest(context, "operator", request)
    assert (
        binding_digest(
            context,
            "operator",
            _prepare_request(query="Deploy a different release"),
        )
        != original_binding
    )
    assert (
        binding_digest(
            context,
            "operator",
            _prepare_request(action_digest="b" * 64),
        )
        != original_binding
    )


def test_action_sensitive_chat_requires_action_identity_contract() -> None:
    base: dict[str, object] = {
        "query": "Deploy the current release",
        "active_goal": "Release safely",
        "requested_scope": {"project_ids": ["milai"]},
        "required_authority": "ACTION_SAFE",
        "action_sensitive": True,
    }
    request = ChatRequest.model_validate({**base, "action_digest": canonical_sha256(ACTION)})
    assert request.action_digest == canonical_sha256(ACTION)

    with pytest.raises(ValidationError, match="action_digest"):
        ChatRequest.model_validate(base)
    with pytest.raises(ValidationError, match="only valid for action-sensitive"):
        ChatRequest.model_validate(
            {
                "query": "Read state",
                "active_goal": "Inspect",
                "action_digest": canonical_sha256(ACTION),
            }
        )
