from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from milai.adapters.blob_store import BlobIntegrityError, LocalContentAddressedBlobStore
from milai.application.errors import ContextOperationError, TenantMismatch
from milai.domain.chat import ContextBuildRequest
from milai.persistence import SessionContext
from milai.persistence.context_repository import ContextMaterial, ContextRepository


@dataclass(frozen=True, slots=True)
class ContextCapsuleBuilt:
    capsule: dict[str, Any]
    sections: dict[str, object]
    compression_level: str


class ContextService:
    def __init__(
        self,
        repository: ContextRepository,
        blob_store: LocalContentAddressedBlobStore,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store

    def build(self, context: SessionContext, request: ContextBuildRequest) -> ContextCapsuleBuilt:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        material = self._repository.material(context, request.retrieval_trace_id)
        variants = _context_variants(
            material,
            request.active_goal,
            request.constraints,
            request.detail_level,
        )
        for compression_level, sections in variants:
            if _serialized_size(sections) <= request.byte_budget:
                capsule = self._repository.create_capsule(
                    context,
                    request.retrieval_trace_id,
                    sections,
                    request.byte_budget,
                    datetime.now(UTC) + timedelta(seconds=request.ttl_seconds),
                )
                return ContextCapsuleBuilt(capsule, sections, compression_level)
        raise ContextOperationError("CONTEXT_BUDGET_INFEASIBLE")

    def get(self, context: SessionContext, capsule_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_capsule(context, capsule_id)

    def recover(self, context: SessionContext, pointer_id: UUID) -> dict[str, Any]:
        metadata = self._repository.recover_pointer(context, pointer_id)
        try:
            content = self._blob_store.read(
                context.tenant_id,
                str(metadata["storage_uri"]),
                str(metadata["content_hash"]),
                int(metadata["byte_length"]),
            )
        except BlobIntegrityError as exc:
            raise ContextOperationError("CONTEXT_POINTER_INVALID") from exc
        result = dict(metadata)
        try:
            result["content"] = content.decode("utf-8")
            result["content_encoding"] = "utf-8"
        except UnicodeDecodeError:
            result["content"] = base64.b64encode(content).decode("ascii")
            result["content_encoding"] = "base64"
        return result


def _context_variants(
    material: ContextMaterial,
    active_goal: str,
    constraints: list[str],
    detail_level: str,
) -> list[tuple[str, dict[str, object]]]:
    evidence_with_pointers = [
        {**evidence, "pointer_id": str(uuid4())} for evidence in material.evidence
    ]
    visible_evidence = evidence_with_pointers if detail_level != "ABSTRACT" else []
    full = _sections(
        material,
        active_goal,
        constraints,
        material.claims,
        material.open_issues,
        visible_evidence,
    )
    compact_claims = [
        {
            key: claim[key]
            for key in (
                "claim_version_id",
                "claim_id",
                "subject_id",
                "predicate",
                "claim_type",
                "payload",
                "authority",
                "canonical_commit_seq",
            )
        }
        for claim in material.claims
    ]
    compact_evidence = [
        {
            key: evidence[key]
            for key in (
                "pointer_id",
                "evidence_id",
                "content_hash",
                "permission_snapshot",
                "retention_state",
            )
        }
        for evidence in visible_evidence
    ]
    compact = _sections(
        material,
        active_goal,
        constraints,
        compact_claims,
        material.open_issues,
        compact_evidence,
    )
    minimal_claims = [
        {
            key: claim[key]
            for key in (
                "claim_version_id",
                "claim_id",
                "payload",
                "authority",
                "canonical_commit_seq",
            )
        }
        for claim in material.claims
    ]
    minimal_issues = [
        {
            key: issue[key]
            for key in (
                "issue_id",
                "target_claim_id",
                "issue_type",
                "status",
                "revision",
                "scope_predicate",
                "branches",
                "discharge_rule",
                "required_authority",
            )
        }
        for issue in material.open_issues
    ]
    minimal_evidence = [
        {key: evidence[key] for key in ("pointer_id", "evidence_id", "content_hash")}
        for evidence in visible_evidence
    ]
    minimal = _sections(
        material,
        active_goal,
        constraints,
        minimal_claims,
        minimal_issues,
        minimal_evidence,
    )
    return [("FULL", full), ("COMPACT", compact), ("MINIMAL", minimal)]


def _sections(
    material: ContextMaterial,
    active_goal: str,
    constraints: list[str],
    claims: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, object]:
    return {
        "ACTIVE GOAL": {"text": active_goal, "protected": True},
        "ACTIVE STATE": claims,
        "OPEN ISSUES": issues,
        "CONSTRAINTS": [{"text": value, "protected": True} for value in constraints],
        "RETRIEVED EVIDENCE": evidence,
        "TRACE POINTERS": {"retrieval_trace_id": str(material.retrieval_trace_id)},
    }


def _serialized_size(value: dict[str, object]) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
