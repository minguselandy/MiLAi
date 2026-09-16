from __future__ import annotations

from uuid import uuid4

from milai.application.derivation import CommitPolicy, DeriveAndDiagnose
from milai.domain import ProposalCreateRequest


def _create_request(authority: str = "INFORMATIONAL") -> ProposalCreateRequest:
    return ProposalCreateRequest.model_validate(
        {
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": "synthetic",
                "predicate": "profile.preference",
                "claim_type": "PREFERENCE",
                "payload": {"value": "concise"},
                "authority": authority,
                "confidence": 0.8,
            },
            "supporting_evidence_refs": [str(uuid4())],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": authority,
            "derivation_policy_id": "unit-derive-v1",
            "derivation_snapshot": {"fixture": "synthetic"},
        }
    )


def test_derive_and_diagnose_produces_typed_replayable_diagnosis() -> None:
    validated = DeriveAndDiagnose().derive(_create_request(), None)
    assert validated.relation == "CREATE"
    assert validated.expected_head_matches is None
    assert validated.trace()["version"] == "derive-diagnose-v1"
    assert "ABSENCE_CAS_REQUIRED" in validated.diagnostic_codes


def test_commit_policy_is_versioned_and_never_auto_commits_lean_candidate() -> None:
    validated = DeriveAndDiagnose().derive(_create_request("ACTION_SAFE"), None)
    result = CommitPolicy().decide(validated)
    assert result.decision == "USER_REVIEW"
    assert result.policy_version == "lean-commit-policy-v1"
    assert "NON_INFORMATIONAL_AUTHORITY_REQUIRES_REVIEW" in result.reason_codes
