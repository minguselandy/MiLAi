from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from milai.application.derivation import CommitPolicy, DeriveAndDiagnose
from milai.application.errors import TenantMismatch
from milai.domain.proposals import ProposalCreateRequest, ProposalReviewRequest
from milai.persistence import SessionContext
from milai.persistence.canonical_repository import (
    CanonicalRepository,
    CreateProposalCommand,
    ReviewProposalCommand,
)


class ProposalService:
    def __init__(
        self,
        repository: CanonicalRepository,
        derive_and_diagnose: DeriveAndDiagnose | None = None,
        commit_policy: CommitPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._derive_and_diagnose = derive_and_diagnose or DeriveAndDiagnose()
        self._commit_policy = commit_policy or CommitPolicy()

    def create(
        self,
        context: SessionContext,
        request: ProposalCreateRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _check_tenant(context, request.tenant_id)
        current_claim = (
            self._repository.get_claim(context, request.target_claim_id)
            if request.target_claim_id is not None
            else None
        )
        validated = self._derive_and_diagnose.derive(request, current_claim)
        policy_result = self._commit_policy.decide(validated)
        derivation_snapshot: dict[str, object] = {
            key: value for key, value in request.derivation_snapshot.items()
        }
        derivation_snapshot["milai_derive_and_diagnose"] = validated.trace()
        derivation_snapshot["milai_commit_policy"] = policy_result.trace()
        result = self._repository.create_proposal(
            context,
            CreateProposalCommand(
                idempotency_key=idempotency_key,
                request_fingerprint=_fingerprint(
                    context.tenant_id, request.model_dump(mode="json")
                ),
                target_claim_id=request.target_claim_id,
                operation=request.operation,
                expected_version_id=request.expected_version_id,
                proposed_patch=dict(request.proposed_patch),
                supporting_evidence_refs=request.supporting_evidence_refs,
                contradicting_evidence_refs=request.contradicting_evidence_refs,
                scope_predicate=dict(request.scope_predicate),
                requested_authority=request.requested_authority,
                derivation_policy_id=request.derivation_policy_id,
                model_id=request.model_id,
                template_id=request.template_id,
                derivation_snapshot=derivation_snapshot,
            ),
        )
        stored = self._repository.get_proposal(context, UUID(str(result["proposal_id"])))
        if stored is None:
            raise RuntimeError("persisted proposal could not be replayed")
        stored_snapshot = stored.get("derivation_snapshot")
        stored_policy = (
            stored_snapshot.get("milai_commit_policy")
            if isinstance(stored_snapshot, dict)
            else None
        )
        if isinstance(stored_policy, dict):
            result["commit_policy_decision"] = stored_policy["decision"]
            result["commit_policy_version"] = stored_policy["policy_version"]
            result["commit_policy_reason_codes"] = stored_policy["reason_codes"]
        else:
            result["commit_policy_decision"] = "USER_REVIEW"
            result["commit_policy_version"] = "legacy-pre-derive-diagnose-v1"
            result["commit_policy_reason_codes"] = ["LEGACY_PROPOSAL_REQUIRES_REVIEW"]
        return result

    def review(
        self,
        context: SessionContext,
        proposal_id: UUID,
        request: ProposalReviewRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _check_tenant(context, request.tenant_id)
        payload = request.model_dump(mode="json")
        payload["proposal_id"] = str(proposal_id)
        return self._repository.review_proposal(
            context,
            ReviewProposalCommand(
                proposal_id=proposal_id,
                decision=request.decision,
                policy_version=request.policy_version,
                reason_code=request.reason_code,
                idempotency_key=idempotency_key,
                request_fingerprint=_fingerprint(context.tenant_id, payload),
            ),
        )

    def get(self, context: SessionContext, proposal_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_proposal(context, proposal_id)

    def list_proposals(
        self, context: SessionContext, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        return self._repository.list_proposals(context, status, limit)

    def get_claim(self, context: SessionContext, claim_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_claim(context, claim_id)

    def get_claim_versions(self, context: SessionContext, claim_id: UUID) -> list[dict[str, Any]]:
        return self._repository.get_claim_versions(context, claim_id)

    def list_open_issues(self, context: SessionContext, status: str | None) -> list[dict[str, Any]]:
        return self._repository.list_open_issues(context, status)

    def get_open_issue(self, context: SessionContext, issue_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_open_issue(context, issue_id)


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
