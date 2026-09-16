from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid5

from flask import Flask, g, request

from milai.api.errors import ApiError
from milai.config import RuntimeSettings
from milai.persistence import SessionContext

MEMORY_READ = "memory:read"
EVIDENCE_CAPTURE = "evidence:capture"
PROPOSAL_CREATE = "proposal:create"
EVIDENCE_REVOKE = "evidence:revoke"
PROPOSAL_REVIEW = "proposal:review"
OPERATIONS_ADMIN = "operations:admin"

ALL_CAPABILITIES = frozenset(
    {
        MEMORY_READ,
        EVIDENCE_CAPTURE,
        PROPOSAL_CREATE,
        EVIDENCE_REVOKE,
        PROPOSAL_REVIEW,
        OPERATIONS_ADMIN,
    }
)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    profile: str
    capabilities: frozenset[str]
    actor_id: UUID


_ENDPOINT_CAPABILITY = {
    "evidence.ingest_evidence": EVIDENCE_CAPTURE,
    "canonical.create_proposal": PROPOSAL_CREATE,
    "canonical.list_proposals": PROPOSAL_REVIEW,
    "canonical.get_proposal": PROPOSAL_REVIEW,
    "canonical.review_proposal": PROPOSAL_REVIEW,
    "deletion.revoke_evidence": EVIDENCE_REVOKE,
    "deletion.submit_namespace_cleanup": EVIDENCE_REVOKE,
    "deletion.get_namespace_cleanup_status": EVIDENCE_REVOKE,
    "episodes.create_episode": EVIDENCE_CAPTURE,
    "episodes.settle_episode": PROPOSAL_REVIEW,
}


def _configured_principals(settings: RuntimeSettings) -> list[tuple[str, str, frozenset[str]]]:
    result = [("legacy-local", settings.api_token.get_secret_value(), ALL_CAPABILITIES)]
    configured = (
        ("reader", settings.agent_reader_token, frozenset({MEMORY_READ})),
        (
            "submitter",
            settings.agent_submitter_token,
            frozenset({MEMORY_READ, EVIDENCE_CAPTURE, PROPOSAL_CREATE}),
        ),
        (
            "operator",
            settings.agent_operator_token,
            frozenset({MEMORY_READ, EVIDENCE_REVOKE}),
        ),
        (
            "reviewer",
            settings.agent_reviewer_token,
            frozenset({MEMORY_READ, PROPOSAL_REVIEW}),
        ),
    )
    for profile, secret, capabilities in configured:
        if secret is not None:
            result.append((profile, secret.get_secret_value(), capabilities))
    return result


def profile_actor_id(settings: RuntimeSettings, profile: str) -> UUID:
    """Bind named capability credentials to stable, mutually distinct local actors."""
    if profile == "legacy-local":
        return settings.local_actor_id
    return uuid5(settings.local_actor_id, f"io.milai.agent-profile/{profile}")


def authenticated_context(app: Flask, required_capability: str | None = None) -> SessionContext:
    settings = cast(RuntimeSettings, app.extensions["milai.settings"])
    authorization = request.headers.get("Authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    matched: AuthenticatedPrincipal | None = None
    if separator == " " and scheme.lower() == "bearer" and supplied:
        for profile, expected, capabilities in _configured_principals(settings):
            if hmac.compare_digest(supplied, expected):
                matched = AuthenticatedPrincipal(
                    profile,
                    capabilities,
                    profile_actor_id(settings, profile),
                )
    if matched is None:
        raise ApiError(
            code="AUTHENTICATION_REQUIRED",
            message="A valid local bearer token is required.",
            status_code=401,
        )
    required = required_capability or _ENDPOINT_CAPABILITY.get(request.endpoint or "", MEMORY_READ)
    if required not in matched.capabilities:
        raise ApiError(
            code="CAPABILITY_REQUIRED",
            message="The authenticated principal lacks the required capability.",
            status_code=403,
            details={"required_capability": required},
        )
    context = SessionContext(settings.tenant_id, matched.actor_id)
    g.session_context = context
    g.milai_principal = matched
    return context
