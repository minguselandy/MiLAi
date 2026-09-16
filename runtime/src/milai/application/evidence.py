from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from milai.adapters.blob_store import BlobIntegrityError, LocalContentAddressedBlobStore
from milai.application.errors import (
    EvidenceContentUnavailable,
    EvidenceDataModeBlocked,
    EvidenceNotFound,
    EvidencePayloadTooLarge,
    TenantMismatch,
)
from milai.domain.evidence import EvidenceIngestRequest
from milai.persistence import SessionContext
from milai.persistence.evidence_repository import (
    EvidenceRecord,
    EvidenceRepository,
    IngestEvidenceCommand,
)


@dataclass(frozen=True, slots=True)
class EvidenceIngested:
    evidence_id: UUID
    blob_id: UUID
    outbox_id: UUID
    replayed: bool


@dataclass(frozen=True, slots=True)
class EvidenceView:
    record: EvidenceRecord
    content: str | None


class EvidenceService:
    def __init__(
        self,
        repository: EvidenceRepository,
        blob_store: LocalContentAddressedBlobStore,
        *,
        max_evidence_bytes: int,
        data_mode: Literal["SYNTHETIC_ONLY", "DEIDENTIFIED_ALLOWED", "LOCAL_PERSONAL_DATA"],
        ingest_observer: Callable[
            [SessionContext, EvidenceIngestRequest, EvidenceIngested], None
        ]
        | None = None,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._max_evidence_bytes = max_evidence_bytes
        self._data_mode = data_mode
        self._ingest_observer = ingest_observer

    def ingest(
        self,
        context: SessionContext,
        request: EvidenceIngestRequest,
        idempotency_key: str,
    ) -> EvidenceIngested:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        allowed = {
            "SYNTHETIC_ONLY": {"SYNTHETIC"},
            "DEIDENTIFIED_ALLOWED": {"SYNTHETIC", "DEIDENTIFIED"},
            "LOCAL_PERSONAL_DATA": {"SYNTHETIC", "DEIDENTIFIED", "PERSONAL"},
        }[self._data_mode]
        if request.data_classification not in allowed:
            raise EvidenceDataModeBlocked("Evidence classification is blocked by data mode")
        content = request.content.encode("utf-8")
        if len(content) > self._max_evidence_bytes:
            raise EvidencePayloadTooLarge("evidence content exceeds configured byte limit")
        stored = self._blob_store.write(context.tenant_id, content, request.media_type)
        fingerprint = _request_fingerprint(context.tenant_id, request)
        permission_snapshot: dict[str, object] = dict(request.permission_snapshot)
        permission_snapshot["data_classification"] = request.data_classification
        result = self._repository.ingest(
            context,
            IngestEvidenceCommand(
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                source_type=request.source_type,
                source_ref=request.source_ref,
                subject_id=request.subject_id,
                source_speaker=request.speaker,
                source_context=(
                    request.source_context.model_dump(mode="json")
                    if request.source_context is not None
                    else None
                ),
                observed_at=request.observed_at,
                content_hash=stored.content_hash,
                storage_uri=stored.storage_uri,
                byte_length=stored.byte_length,
                media_type=request.media_type,
                permission_snapshot=permission_snapshot,
                retention_state=request.retention_state,
            ),
        )
        ingested = EvidenceIngested(
            evidence_id=result.evidence_id,
            blob_id=result.blob_id,
            outbox_id=result.outbox_id,
            replayed=result.replayed,
        )
        if self._ingest_observer is not None:
            try:
                self._ingest_observer(context, request, ingested)
            except Exception:
                logging.getLogger(__name__).exception(
                    "noncanonical_evidence_ingest_observer_failed",
                    extra={"evidence_id": str(ingested.evidence_id)},
                )
        return ingested

    def get(self, context: SessionContext, evidence_id: UUID) -> EvidenceView:
        record = self._repository.get(context, evidence_id)
        if record is None:
            raise EvidenceNotFound("evidence does not exist in the authenticated tenant")
        if (
            record.revoked_at is not None
            or record.retention_state != "READABLE"
            or record.permission_snapshot.get("readable") is not True
        ):
            return EvidenceView(record=record, content=None)
        try:
            raw_content = self._blob_store.read(
                context.tenant_id,
                record.storage_uri,
                record.content_hash,
                record.byte_length,
            )
            content = raw_content.decode("utf-8")
        except (BlobIntegrityError, UnicodeDecodeError) as exc:
            raise EvidenceContentUnavailable("evidence content is unavailable") from exc
        return EvidenceView(record=record, content=content)

    def lineage(
        self, context: SessionContext, evidence_id: UUID
    ) -> tuple[EvidenceView, list[dict[str, str]], list[dict[str, str]]]:
        view = self.get(context, evidence_id)
        claim_versions, open_issues = self._repository.lineage(context, evidence_id)
        return view, claim_versions, open_issues


def _request_fingerprint(tenant_id: UUID, request: EvidenceIngestRequest) -> str:
    canonical = request.model_dump(mode="json", exclude_none=False)
    canonical["authenticated_tenant_id"] = str(tenant_id)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
