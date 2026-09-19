"""Request-to-session binding identities for context preparation."""

from __future__ import annotations

from milai.application.context_prepare.serialization import sha256
from milai.domain import PrepareContextRequest
from milai.persistence import SessionContext


def binding_digest(
    context: SessionContext,
    principal_profile: str,
    request: PrepareContextRequest,
) -> str:
    return sha256(
        {
            "tenant_id": str(context.tenant_id),
            "principal_profile": principal_profile,
            "session_id": request.session_id,
            "agent_id": request.agent_id,
            "profile_id": request.profile_id,
            "task_epoch": request.task_epoch,
            "active_goal": request.active_goal,
            "requested_scope": request.requested_scope,
            "required_authority": request.required_authority,
            "consistency": request.consistency,
            "limit": request.limit,
            "constraints": request.constraints,
            "byte_budget": request.byte_budget,
            "memory_token_budget": request.memory_token_budget,
            "slot_ttl_seconds": request.slot_ttl_seconds,
            "compiler_digest": request.compiler_digest,
            "router_digest": request.router_digest,
            "tokenizer_digest": request.tokenizer_digest,
            "policy_digest": request.policy_digest,
            "budget": request.budget.model_dump(mode="json"),
            "action_digest": request.action_digest,
        }
    )


def policy_identity(principal_profile: str, request: PrepareContextRequest) -> str:
    return sha256(
        {
            "principal_profile": principal_profile,
            "profile_id": request.profile_id,
            "scope": request.requested_scope,
            "authority": request.required_authority,
            "consistency": request.consistency,
            "policy_digest": request.policy_digest,
        }
    )


__all__ = ["binding_digest", "policy_identity"]
