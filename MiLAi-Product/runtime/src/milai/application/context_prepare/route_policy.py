"""Route validation and typed-need policy checks."""

from __future__ import annotations

from milai.application.context_prepare.contracts import ExecutionRoute
from milai.domain import PrepareContextRequest


def validated_route(request: PrepareContextRequest) -> tuple[ExecutionRoute, str | None]:
    if (
        request.event in {"MEMORY_AFFECTING_TOOL_RESULT", "CANONICAL_POSITION_CHANGED"}
        and request.requested_route in {"NONE", "CACHE"}
        and not (
            request.requested_route == "CACHE"
            and request.memory_need_signature is not None
            and request.memory_need_signature.temporal_need == "CURRENT"
            and bool(
                request.memory_need_signature.claim_ids or request.memory_need_signature.state_keys
            )
        )
    ):
        return "L1", "CANONICAL_CHANGE_REQUIRES_REFRESH"
    if request.event == "ACTION_PROPOSED" and request.requested_route != "L1":
        return "L1", "ACTION_SAFE_REQUIRES_CANONICAL_RECALL"
    if (
        request.requested_route == "L0"
        and request.known_claim_id is None
        and request.state_key_ref is None
    ):
        return "L1", "L0_LOCATOR_UNAVAILABLE"
    return request.requested_route, None


def typed_need_policy_rejection(request: PrepareContextRequest) -> str | None:
    signature = request.memory_need_signature
    if signature is not None:
        if signature.scope != request.requested_scope:
            return "NEED_SCOPE_MISMATCH"
        if any(key.scope != request.requested_scope for key in signature.state_keys):
            return "NEED_STATE_KEY_SCOPE_MISMATCH"
        if signature.required_authority != request.required_authority:
            return "NEED_AUTHORITY_MISMATCH"
        if signature.consistency_floor != request.consistency:
            return "NEED_CONSISTENCY_MISMATCH"
    if request.state_key_ref is not None and request.state_key_ref.scope != request.requested_scope:
        return "STATE_KEY_SCOPE_MISMATCH"
    return None


__all__ = ["typed_need_policy_rejection", "validated_route"]
