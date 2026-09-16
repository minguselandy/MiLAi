"""Typed bridge from noncanonical Formation artifacts to governed proposals."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue

from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateTransitionV01,
)
from milai.domain.proposals import Operation, ProposalCreateRequest
from milai.domain.requirement_state import canonical_sha256


class FormationEvolutionBridgeError(ValueError):
    """A Formation artifact cannot safely enter the existing proposal path."""


@dataclass(frozen=True, slots=True)
class EvolutionCurrentClaimV01:
    claim_id: UUID
    claim_version_id: UUID
    subject_id: str
    predicate: str
    payload: JsonValue
    effective_status: str


def map_state_artifact_to_proposal(
    assertion: FormationStateAssertionV01,
    *,
    governed_evidence_ref: UUID,
    scope_predicate: dict[str, JsonValue],
    transition: FormationStateTransitionV01 | None = None,
    current_claim: EvolutionCurrentClaimV01 | None = None,
) -> ProposalCreateRequest | None:
    """Map one grounded artifact to a review-only OperationProposal request.

    Query-local hypotheses deliberately return ``None``.  This function never
    persists or approves the request; the existing validator, CommitPolicy and
    Steward procedure remain the only Canonical path.
    """

    if assertion.promotion_disposition == "QUERY_LOCAL_ONLY":
        return None
    if transition is not None:
        if transition.resulting_assertion_digest != assertion.artifact_digest:
            raise FormationEvolutionBridgeError("FORMATION_TRANSITION_ASSERTION_MISMATCH")
        if transition.predicate != assertion.predicate:
            raise FormationEvolutionBridgeError("FORMATION_TRANSITION_PREDICATE_MISMATCH")
    if current_claim is not None and (
        current_claim.subject_id != assertion.subject_identity
        or current_claim.predicate != assertion.predicate
    ):
        raise FormationEvolutionBridgeError("FORMATION_CURRENT_CLAIM_IDENTITY_MISMATCH")

    operation = _operation(assertion, transition, current_claim)
    payload = (
        current_claim.payload
        if operation == "WEAKEN" and current_claim is not None
        else assertion.value
    )
    patch: dict[str, JsonValue] = (
        {}
        if operation == "CONTRADICT"
        else {
            "payload": payload,
            "authority": "INFORMATIONAL",
            "confidence": 0.8,
        }
    )
    if assertion.valid_time is not None and operation != "CONTRADICT":
        patch["valid_time_from"] = (
            assertion.valid_time.start.isoformat()
            if assertion.valid_time.start is not None
            else None
        )
        if assertion.modality == "TEMPORARY":
            patch["valid_time_to"] = (
                assertion.valid_time.end.isoformat()
                if assertion.valid_time.end is not None
                else None
            )
    if operation == "CREATE":
        patch.update(
            {
                "subject_id": assertion.subject_identity,
                "predicate": assertion.predicate,
                "claim_type": _claim_type(assertion),
            }
        )

    span_lineage: dict[str, JsonValue] = {
        "source_evidence_id": assertion.span.evidence_id,
        "source_ref": assertion.span.source_ref,
        "start": assertion.span.start,
        "end": assertion.span.end,
        "text_digest": canonical_sha256(assertion.span.text),
    }
    return ProposalCreateRequest(
        target_claim_id=(current_claim.claim_id if current_claim else None),
        operation=operation,
        expected_version_id=(
            current_claim.claim_version_id if current_claim else None
        ),
        proposed_patch=patch,
        supporting_evidence_refs=(
            [] if operation == "CONTRADICT" else [governed_evidence_ref]
        ),
        contradicting_evidence_refs=(
            [governed_evidence_ref] if operation == "CONTRADICT" else []
        ),
        scope_predicate=scope_predicate,
        requested_authority="INFORMATIONAL",
        derivation_policy_id="formation-evolution-bridge-v0.1",
        template_id="formation-state-change-v0.1",
        derivation_snapshot={
            "formation_artifact_digest": assertion.artifact_digest,
            "transition_artifact_digest": (
                transition.artifact_digest if transition is not None else None
            ),
            "transition_relation": transition.relation if transition is not None else None,
            "source_span": span_lineage,
            "canonical_commit_authorized": False,
        },
    )


def _operation(
    assertion: FormationStateAssertionV01,
    transition: FormationStateTransitionV01 | None,
    current_claim: EvolutionCurrentClaimV01 | None,
) -> Operation:
    if current_claim is None:
        if transition is not None and transition.relation in {"UPDATES", "CORRECTS"}:
            raise FormationEvolutionBridgeError("FORMATION_CURRENT_CLAIM_REQUIRED")
        return "CREATE"

    if (
        current_claim.effective_status == "BLOCKED"
        and current_claim.payload == assertion.value
    ):
        return "REGROUND"
    if transition is None:
        if current_claim.payload == assertion.value:
            return "SUPPORT"
        raise FormationEvolutionBridgeError("FORMATION_UNTYPED_STATE_CHANGE_AMBIGUOUS")
    if transition.relation in {"UPDATES", "CORRECTS"}:
        if current_claim.payload != transition.previous_value:
            raise FormationEvolutionBridgeError("FORMATION_PREVIOUS_STATE_MISMATCH")
        return "SUPERSEDE"
    if transition.relation == "TEMPORARILY_CONSTRAINS":
        return "CONTEXTUALIZE"
    if transition.relation == "REVOKES":
        return "WEAKEN"
    if transition.relation == "ESTABLISHES":
        return "SUPPORT" if current_claim.payload == assertion.value else "CONTRADICT"
    raise FormationEvolutionBridgeError("FORMATION_TRANSITION_NOT_SUPPORTED")


def _claim_type(assertion: FormationStateAssertionV01) -> str:
    if assertion.modality == "PREFERENCE":
        return "PREFERENCE"
    if assertion.modality == "TEMPORARY":
        return "TEMPORARY_STATE"
    return "STATE"


__all__ = [
    "EvolutionCurrentClaimV01",
    "FormationEvolutionBridgeError",
    "map_state_artifact_to_proposal",
]
