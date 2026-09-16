from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from milai.application.errors import TenantMismatch
from milai.domain.episodes import EpisodeCreateRequest, EpisodeSettleRequest
from milai.persistence import SessionContext
from milai.persistence.episode_repository import (
    CreateEpisodeCommand,
    EpisodeRepository,
    SettleEpisodeCommand,
)


class EpisodeService:
    def __init__(self, repository: EpisodeRepository) -> None:
        self._repository = repository

    def create(
        self,
        context: SessionContext,
        request: EpisodeCreateRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _check_tenant(context, request.tenant_id)
        payload = request.model_dump(mode="json")
        return self._repository.create(
            context,
            CreateEpisodeCommand(
                subject_id=request.subject_id,
                evidence_refs=request.evidence_refs,
                chat_turn_refs=request.chat_turn_refs,
                context_capsule_refs=request.context_capsule_refs,
                idempotency_key=idempotency_key,
                request_fingerprint=_fingerprint(context.tenant_id, payload),
            ),
        )

    def settle(
        self,
        context: SessionContext,
        episode_id: UUID,
        request: EpisodeSettleRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _check_tenant(context, request.tenant_id)
        payload = request.model_dump(mode="json")
        payload["episode_id"] = str(episode_id)
        return self._repository.settle(
            context,
            SettleEpisodeCommand(
                episode_id=episode_id,
                expected_revision=request.expected_revision,
                residual_proposal_ids=request.residual_proposal_ids,
                open_issue_ids=request.open_issue_ids,
                confirmation=request.confirmation,
                idempotency_key=idempotency_key,
                request_fingerprint=_fingerprint(context.tenant_id, payload),
            ),
        )

    def get(self, context: SessionContext, episode_id: UUID) -> dict[str, Any] | None:
        return self._repository.get(context, episode_id)


def _check_tenant(context: SessionContext, body_tenant: UUID | None) -> None:
    if body_tenant is not None and body_tenant != context.tenant_id:
        raise TenantMismatch("body tenant does not match authenticated tenant")


def _fingerprint(tenant_id: UUID, payload: dict[str, Any]) -> str:
    canonical = dict(payload)
    canonical["authenticated_tenant_id"] = str(tenant_id)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
