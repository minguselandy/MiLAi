"""Canonical identity for action-sensitive Runtime requests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue

from milai.domain.retrieval import RetrievalAuthority


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def action_identity_digest(
    *,
    tenant_id: UUID,
    query: str,
    active_goal: str,
    requested_scope: Mapping[str, JsonValue],
    required_authority: RetrievalAuthority,
    action_digest: str,
) -> str:
    """Bind action bytes to the bounded request context that authorizes them."""

    return canonical_sha256(
        {
            "tenant_id": str(tenant_id),
            "query": query,
            "active_goal": active_goal,
            "requested_scope": dict(requested_scope),
            "required_authority": required_authority,
            "action_digest": action_digest,
        }
    )


__all__ = ["action_identity_digest", "canonical_json", "canonical_sha256"]
