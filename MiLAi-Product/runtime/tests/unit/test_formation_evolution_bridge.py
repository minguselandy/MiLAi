from __future__ import annotations

from uuid import uuid4

import pytest

from milai.application.derivation import CommitPolicy, DeriveAndDiagnose
from milai.application.formation_evolution_bridge import (
    EvolutionCurrentClaimV01,
    FormationEvolutionBridgeError,
    map_state_artifact_to_proposal,
)
from milai.application.formation_generalization import build_generalized_formation
from milai.application.state_change_formation import build_state_change_sidecar


def test_move_maps_to_reviewed_supercede_with_exact_lineage() -> None:
    sidecar = build_state_change_sidecar(
        [
            _source(
                "move",
                "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job.",
            )
        ]
    )
    assertion = sidecar.assertions[0]
    transition = sidecar.transitions[0]
    current = _current("residence", {"location": "Shanghai"})

    request = map_state_artifact_to_proposal(
        assertion,
        transition=transition,
        current_claim=current,
        governed_evidence_ref=uuid4(),
        scope_predicate={"project_ids": ["milai"]},
    )

    assert request is not None
    assert request.operation == "SUPERSEDE"
    assert request.target_claim_id == current.claim_id
    assert request.expected_version_id == current.claim_version_id
    assert request.proposed_patch["payload"] == {"location": "Hangzhou"}
    assert request.proposed_patch["valid_time_from"] == "2026-08-12T00:00:00+08:00"
    assert "valid_time_to" not in request.proposed_patch
    validated = DeriveAndDiagnose().derive(
        request,
        {
            "claim_version_id": str(current.claim_version_id),
            "effective_status": current.effective_status,
        },
    )
    assert validated.relation == "UPDATE"
    assert validated.expected_head_matches is True
    assert CommitPolicy().decide(validated).decision == "USER_REVIEW"


def test_temporary_state_preserves_valid_time_in_create_proposal() -> None:
    sidecar = build_state_change_sidecar(
        [
            _source(
                "temporary",
                "Until September 5, 2026, I'm staying in Suzhou for a conference.",
            )
        ]
    )

    request = map_state_artifact_to_proposal(
        sidecar.assertions[0],
        transition=sidecar.transitions[0],
        governed_evidence_ref=uuid4(),
        scope_predicate={"project_ids": ["milai"]},
    )

    assert request is not None
    assert request.operation == "CREATE"
    assert str(request.proposed_patch["valid_time_to"]).startswith(
        "2026-09-05T23:59:59.999999"
    )


def test_query_local_hypothesis_never_emits_operation_proposal() -> None:
    sidecar = build_state_change_sidecar(
        [_source("intent", "I'm thinking of going back to Denver for another concert")]
    )

    request = map_state_artifact_to_proposal(
        sidecar.assertions[0],
        governed_evidence_ref=uuid4(),
        scope_predicate={"project_ids": ["milai"]},
    )

    assert request is None


def test_wrong_previous_state_is_rejected_before_proposal_creation() -> None:
    sidecar = build_state_change_sidecar(
        [
            _source(
                "move",
                "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job.",
            )
        ]
    )

    with pytest.raises(FormationEvolutionBridgeError, match="PREVIOUS_STATE_MISMATCH"):
        map_state_artifact_to_proposal(
            sidecar.assertions[0],
            transition=sidecar.transitions[0],
            current_claim=_current("residence", {"location": "Beijing"}),
            governed_evidence_ref=uuid4(),
            scope_predicate={"project_ids": ["milai"]},
        )


def test_revoke_maps_to_weaken_without_erasing_canonical_payload() -> None:
    bundle = build_generalized_formation(
        [
            {
                **_source(
                    "revoke-allergy",
                    "That peanut allergy was incorrect; I revoke it.",
                ),
                "scope_id": "scope-a",
                "speaker": "user",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "access_decision": "ALLOWED",
            }
        ]
    )
    assertion = bundle.state_changes.assertions[0]
    transition = bundle.state_changes.transitions[0]
    current = EvolutionCurrentClaimV01(
        claim_id=uuid4(),
        claim_version_id=uuid4(),
        subject_id="scope-a:self",
        predicate="allergy",
        payload={"item": "peanut"},
        effective_status="EFFECTIVE",
    )

    request = map_state_artifact_to_proposal(
        assertion,
        transition=transition,
        current_claim=current,
        governed_evidence_ref=uuid4(),
        scope_predicate={"project_ids": ["scope-a"]},
    )

    assert request is not None
    assert request.operation == "WEAKEN"
    assert request.proposed_patch["payload"] == {"item": "peanut"}


def test_conflicting_establishment_maps_to_open_issue_branch() -> None:
    bundle = build_generalized_formation(
        [
            {
                **_source("conflict", "I live in Beijing."),
                "scope_id": "scope-a",
                "speaker": "user",
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
                "access_decision": "ALLOWED",
            }
        ]
    )
    assertion = bundle.state_changes.assertions[0]
    transition = bundle.state_changes.transitions[0]
    current = EvolutionCurrentClaimV01(
        claim_id=uuid4(),
        claim_version_id=uuid4(),
        subject_id="scope-a:self",
        predicate="residence",
        payload={"location": "Shanghai"},
        effective_status="EFFECTIVE",
    )

    request = map_state_artifact_to_proposal(
        assertion,
        transition=transition,
        current_claim=current,
        governed_evidence_ref=uuid4(),
        scope_predicate={"project_ids": ["scope-a"]},
    )

    assert request is not None
    assert request.operation == "CONTRADICT"
    assert request.proposed_patch == {}
    assert request.supporting_evidence_refs == []
    assert len(request.contradicting_evidence_refs) == 1


def _source(evidence_id: str, content: str) -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "source_ref": f"memory://{evidence_id}",
        "content": content,
        "observed_at": "2026-08-16T11:00:00+08:00",
    }


def _current(predicate: str, payload: object) -> EvolutionCurrentClaimV01:
    return EvolutionCurrentClaimV01(
        claim_id=uuid4(),
        claim_version_id=uuid4(),
        subject_id="subject:self",
        predicate=predicate,
        payload=payload,  # type: ignore[arg-type]
        effective_status="EFFECTIVE",
    )
