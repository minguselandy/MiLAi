from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from milai.application.errors import TenantMismatch
from milai.domain import EvidenceRevocationRequest, NamespaceCleanupRequest
from milai.persistence import SessionContext
from milai.persistence.deletion_repository import (
    DeletionRepository,
    RevokeEvidenceCommand,
)


class DeletionService:
    def __init__(
        self,
        repository: DeletionRepository,
        *,
        evidence_invalidator: Callable[[SessionContext, UUID], None] | None = None,
        project_invalidator: Callable[[SessionContext, str], None] | None = None,
    ) -> None:
        self._repository = repository
        self._evidence_invalidator = evidence_invalidator
        self._project_invalidator = project_invalidator

    def revoke(
        self,
        context: SessionContext,
        evidence_id: UUID,
        request: EvidenceRevocationRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        payload = request.model_dump(mode="json")
        payload["evidence_id"] = str(evidence_id)
        payload["authenticated_tenant_id"] = str(context.tenant_id)
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = self._repository.revoke(
            context,
            RevokeEvidenceCommand(
                evidence_id=evidence_id,
                reason_code=request.reason_code,
                confirmation=request.confirmation,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            ),
        )
        if self._evidence_invalidator is not None:
            try:
                self._evidence_invalidator(context, evidence_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "noncanonical_evidence_invalidation_failed",
                    extra={"evidence_id": str(evidence_id)},
                )
        return result

    def get(self, context: SessionContext, deletion_request_id: UUID) -> dict[str, Any] | None:
        return self._repository.get(context, deletion_request_id)

    def get_for_evidence(self, context: SessionContext, evidence_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_for_evidence(context, evidence_id)

    def submit_namespace_cleanup(
        self,
        context: SessionContext,
        request: NamespaceCleanupRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = request.model_dump(mode="json")
        payload["authenticated_tenant_id"] = str(context.tenant_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        result = self._repository.submit_namespace_cleanup(
            context,
            project_id=request.project_id,
            reason_code=request.reason_code,
            confirmation=request.confirmation,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        if self._project_invalidator is not None:
            try:
                self._project_invalidator(context, request.project_id)
            except Exception:
                logging.getLogger(__name__).exception(
                    "noncanonical_project_invalidation_failed",
                    extra={"project_id": request.project_id},
                )
        return result

    def namespace_cleanup_status(
        self,
        context: SessionContext,
        cleanup_job_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any] | None:
        return self._repository.namespace_cleanup_status(
            context, cleanup_job_id, offset=offset, limit=limit
        )
