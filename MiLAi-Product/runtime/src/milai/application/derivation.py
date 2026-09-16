from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from milai.domain.proposals import ProposalCreateRequest

DiagnosticRelation = Literal["CREATE", "UPDATE", "CONFLICT", "NO_CHANGE"]
CommitPolicyDecision = Literal["AUTO_COMMIT", "USER_REVIEW", "REJECT", "NO_CHANGE"]


@dataclass(frozen=True, slots=True)
class ValidatedProposal:
    """Deterministically validated proposal plus the observed canonical diagnosis."""

    request: ProposalCreateRequest
    relation: DiagnosticRelation
    observed_claim_version_id: str | None
    observed_effective_status: str | None
    expected_head_matches: bool | None
    diagnostic_codes: tuple[str, ...]

    def trace(self) -> dict[str, object]:
        return {
            "component": "DeriveAndDiagnose",
            "version": "derive-diagnose-v1",
            "relation": self.relation,
            "observed_claim_version_id": self.observed_claim_version_id,
            "observed_effective_status": self.observed_effective_status,
            "expected_head_matches": self.expected_head_matches,
            "diagnostic_codes": list(self.diagnostic_codes),
        }


@dataclass(frozen=True, slots=True)
class CommitPolicyResult:
    decision: CommitPolicyDecision
    policy_version: str
    reason_codes: tuple[str, ...]

    def trace(self) -> dict[str, object]:
        return {
            "component": "CommitPolicy",
            "decision": self.decision,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
        }


class DeriveAndDiagnose:
    """Classify an already schema-validated candidate outside the canonical TX."""

    _RELATIONS: ClassVar[dict[str, DiagnosticRelation]] = {
        "CREATE": "CREATE",
        "CONTRADICT": "CONFLICT",
        "NO_CHANGE": "NO_CHANGE",
        "SUPPORT": "UPDATE",
        "WEAKEN": "UPDATE",
        "REVALIDATE": "UPDATE",
        "REGROUND": "UPDATE",
        "SUPERSEDE": "UPDATE",
        "CONTEXTUALIZE": "UPDATE",
        "SPLIT": "UPDATE",
    }

    def derive(
        self,
        request: ProposalCreateRequest,
        current_claim: dict[str, Any] | None,
    ) -> ValidatedProposal:
        observed_version = (
            str(current_claim["claim_version_id"])
            if current_claim is not None and current_claim.get("claim_version_id") is not None
            else None
        )
        expected_matches = (
            request.expected_version_id is not None
            and observed_version == str(request.expected_version_id)
            if request.target_claim_id is not None
            else None
        )
        codes: list[str] = ["SCHEMA_VALIDATED", "EVIDENCE_REFS_TYPED"]
        if request.target_claim_id is None:
            codes.append("ABSENCE_CAS_REQUIRED")
        elif current_claim is None:
            codes.append("TARGET_NOT_OBSERVED")
        elif expected_matches:
            codes.append("EXPECTED_HEAD_OBSERVED")
        else:
            codes.append("STALE_OR_UNKNOWN_EXPECTED_HEAD")
        if request.operation == "CONTRADICT":
            codes.append("OPEN_ISSUE_PATH_REQUIRED")
        if request.requested_authority != "INFORMATIONAL":
            codes.append("AUTHORITY_REVIEW_REQUIRED")
        return ValidatedProposal(
            request=request,
            relation=self._RELATIONS[request.operation],
            observed_claim_version_id=observed_version,
            observed_effective_status=(
                str(current_claim["effective_status"])
                if current_claim is not None and current_claim.get("effective_status") is not None
                else None
            ),
            expected_head_matches=expected_matches,
            diagnostic_codes=tuple(codes),
        )


class CommitPolicy:
    """Versioned safe policy; Lean V1 intentionally disables automatic commit."""

    VERSION = "lean-commit-policy-v1"

    def decide(self, proposal: ValidatedProposal) -> CommitPolicyResult:
        reasons = ["AUTO_COMMIT_DISABLED_UNTIL_FROZEN_CROSSWALK"]
        if proposal.relation == "CONFLICT":
            reasons.append("CONFLICT_REQUIRES_STEWARD_REVIEW")
        if proposal.request.requested_authority != "INFORMATIONAL":
            reasons.append("NON_INFORMATIONAL_AUTHORITY_REQUIRES_REVIEW")
        if proposal.expected_head_matches is False:
            reasons.append("CANONICAL_PROCEDURE_MUST_RECHECK_HEAD")
        return CommitPolicyResult("USER_REVIEW", self.VERSION, tuple(reasons))
