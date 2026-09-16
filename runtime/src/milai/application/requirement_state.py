"""Deterministic RequirementState resolver owned by Runtime."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from milai.application.query_ir_compat import infer_operator_family
from milai.domain.acquisition import AcquisitionPlan, CandidateEnvelope, EvidenceReferenceNote
from milai.domain.requirement_state import (
    RejectedCandidateDisposition,
    RequirementCardinalityState,
    RequirementDisposition,
    RequirementKind,
    RequirementProofStatus,
    RequirementState,
    canonical_sha256,
)
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    MemoryQueryIRV02,
    RequirementBinding,
)
from milai.domain.sufficiency import SufficiencyDecision

SUFFICIENCY_POLICY_VERSION = "query-sufficiency-v0.1+requirement-state-v0.1"
UNRESOLVED_CAPABILITY_DIGEST = canonical_sha256(
    {"schema_version": "acquisition-capability-unresolved-v0.1"}
)


def resolve_requirement_state(
    *,
    plan: AcquisitionPlan,
    requirements: Sequence[EvidenceRequirementV02],
    acquisition_capability_digest: str,
    candidates: Sequence[CandidateEnvelope] = (),
    spans: Sequence[EvidenceSpan] = (),
    interpretations: Sequence[EvidenceInterpretationCandidate] = (),
    bindings: Sequence[RequirementBinding] = (),
    sufficiency_decision: SufficiencyDecision,
    state_epoch: int,
    memory_query_ir: MemoryQueryIRV02 | None = None,
    kind_overrides: Mapping[str, RequirementKind] | None = None,
    accepted_evidence_overrides: Mapping[str, Sequence[str]] | None = None,
) -> RequirementState:
    """Resolve a complete per-requirement state from one immutable snapshot."""

    required = sorted(
        (item for item in requirements if item.required), key=lambda item: item.slot_id
    )
    if len(required) != len({item.slot_id for item in required}):
        raise ValueError("RequirementState inputs contain duplicate required IDs")
    overrides = dict(kind_overrides or {})
    if not set(overrides).issubset({item.slot_id for item in required}):
        raise ValueError("RequirementState kind override addresses unknown requirement")
    span_by_id = {item.span_id: item for item in spans}
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    binding_rows = sorted(
        bindings,
        key=lambda item: (item.requirement_id, item.interpretation_id, item.status),
    )
    binding_digest = canonical_sha256([item.model_dump(mode="json") for item in binding_rows])
    override_evidence = {
        key: sorted(set(values))
        for key, values in sorted((accepted_evidence_overrides or {}).items())
    }
    candidate_refs = {
        requirement.slot_id: sorted(
            {
                *override_evidence.get(requirement.slot_id, []),
                *(
                    candidate.source_evidence_id
                    for candidate in candidates
                    if requirement.slot_id in candidate.matched_slots
                ),
            }
        )
        for requirement in required
    }
    candidate_refs["__ALL__"] = sorted(
        {
            *(candidate.source_evidence_id for candidate in candidates),
            *(value for values in override_evidence.values() for value in values),
        }
    )
    candidate_snapshot_digest = canonical_sha256(candidate_refs)
    sufficiency_digest = canonical_sha256(sufficiency_decision.model_dump(mode="json"))
    operator_family = (
        infer_operator_family(memory_query_ir) if memory_query_ir is not None else None
    )
    dispositions = [
        _resolve_disposition(
            requirement,
            bindings=binding_rows,
            span_by_id=span_by_id,
            interpretation_by_id=interpretation_by_id,
            sufficiency=sufficiency_decision,
            kind=overrides.get(requirement.slot_id)
            or _requirement_kind(requirement, memory_query_ir, operator_family),
            operator_family=operator_family,
            completeness=(memory_query_ir.completeness if memory_query_ir is not None else None),
            accepted_evidence_override=override_evidence.get(requirement.slot_id, []),
        )
        for requirement in required
    ]
    plan_digest = canonical_sha256(plan.model_dump(mode="json"))
    material: dict[str, Any] = {
        "schema_version": "requirement-state-v0.1",
        "query_ir_digest": plan.query_ir_digest,
        "acquisition_plan_digest": plan_digest,
        "acquisition_capability_digest": acquisition_capability_digest,
        "candidate_snapshot_digest": candidate_snapshot_digest,
        "binding_digest": binding_digest,
        "sufficiency_decision_digest": sufficiency_digest,
        "sufficiency_policy_version": SUFFICIENCY_POLICY_VERSION,
        "state_epoch": state_epoch,
        "requirements": [item.model_dump(mode="json") for item in dispositions],
        "lifetime": "MEMORY_RESOLVE",
        "canonical": False,
        "canonical_mutation": False,
    }
    return RequirementState(state_digest=canonical_sha256(material), **material)


def resolve_initial_requirement_state(
    plan: AcquisitionPlan,
    requirements: Sequence[EvidenceRequirementV02],
    *,
    acquisition_capability_digest: str = UNRESOLVED_CAPABILITY_DIGEST,
    memory_query_ir: MemoryQueryIRV02 | None = None,
) -> RequirementState:
    required_ids = sorted(item.slot_id for item in requirements if item.required)
    return resolve_requirement_state(
        plan=plan,
        requirements=requirements,
        acquisition_capability_digest=acquisition_capability_digest,
        sufficiency_decision=SufficiencyDecision(
            status="UNSATISFIED",
            missing_slots=required_ids,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        ),
        state_epoch=0,
        memory_query_ir=memory_query_ir,
    )


def advance_requirement_state(
    previous: RequirementState,
    *,
    plan: AcquisitionPlan,
    requirements: Sequence[EvidenceRequirementV02],
    candidates: Sequence[CandidateEnvelope],
    bindings: Sequence[RequirementBinding],
    notes: Sequence[EvidenceReferenceNote],
    sufficiency_decision: SufficiencyDecision,
    memory_query_ir: MemoryQueryIRV02 | None = None,
    spans: Sequence[EvidenceSpan] = (),
    interpretations: Sequence[EvidenceInterpretationCandidate] = (),
) -> RequirementState:
    accepted: dict[str, list[str]] = {}
    for note in notes:
        accepted.setdefault(note.requirement_id, []).append(note.evidence_id)
    provisional = resolve_requirement_state(
        plan=plan,
        requirements=requirements,
        acquisition_capability_digest=previous.acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        sufficiency_decision=sufficiency_decision,
        state_epoch=previous.state_epoch,
        memory_query_ir=memory_query_ir,
        kind_overrides={item.requirement_id: item.kind for item in previous.requirements},
        accepted_evidence_overrides=accepted,
    )
    epoch = previous.state_epoch + (
        provisional.candidate_snapshot_digest != previous.candidate_snapshot_digest
    )
    if epoch == provisional.state_epoch:
        return provisional
    return resolve_requirement_state(
        plan=plan,
        requirements=requirements,
        acquisition_capability_digest=previous.acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        sufficiency_decision=sufficiency_decision,
        state_epoch=epoch,
        memory_query_ir=memory_query_ir,
        kind_overrides={item.requirement_id: item.kind for item in previous.requirements},
        accepted_evidence_overrides=accepted,
    )


def resolve_compat_requirement_state(
    previous: RequirementState,
    *,
    candidate_refs: Mapping[str, Sequence[str]],
    bindings: Sequence[RequirementBinding],
    notes: Sequence[EvidenceReferenceNote],
    sufficiency_decision: SufficiencyDecision | None,
) -> RequirementState:
    """Rebuild the state when a legacy caller only retained acquisition views.

    This adapter remains fail-closed: Sufficiency covered slots without accepted
    Binding-backed Evidence cannot become SATISFIED.
    """

    decision = sufficiency_decision or SufficiencyDecision(
        status=("COMPLETE" if not previous.missing_requirement_ids else "UNSATISFIED"),
        covered_slots=previous.satisfied_requirement_ids,
        missing_slots=previous.missing_requirement_ids,
        stop_reason=(
            "REQUIREMENT_SATISFIED"
            if not previous.missing_requirement_ids
            else "SEARCH_SPACE_EXHAUSTED"
        ),
    )
    rows_by_requirement: dict[str, list[RequirementBinding]] = {
        item.requirement_id: [] for item in previous.requirements
    }
    for binding in bindings:
        if binding.requirement_id in rows_by_requirement:
            rows_by_requirement[binding.requirement_id].append(binding)
    notes_by_requirement: dict[str, set[str]] = {
        item.requirement_id: set(item.accepted_evidence_refs) for item in previous.requirements
    }
    for note in notes:
        if note.requirement_id in notes_by_requirement:
            notes_by_requirement[note.requirement_id].add(note.evidence_id)
    dispositions: list[RequirementDisposition] = []
    for prior in previous.requirements:
        rows = rows_by_requirement[prior.requirement_id]
        refs = {
            status: sorted(
                canonical_sha256(item.model_dump(mode="json"))
                for item in rows
                if item.status == status
            )
            for status in ("MATCH", "POSSIBLE", "REJECTED")
        }
        rejected = sorted(
            (
                RejectedCandidateDisposition(
                    candidate_ref=f"interpretation:{item.interpretation_id}",
                    binding_ref=canonical_sha256(item.model_dump(mode="json")),
                    reason_code=item.reason_code,
                )
                for item in rows
                if item.status == "REJECTED"
            ),
            key=lambda item: (item.candidate_ref, item.binding_ref, item.reason_code),
        )
        summary = dict(sorted(Counter(item.reason_code for item in rejected).items()))
        accepted = sorted(notes_by_requirement[prior.requirement_id])
        proof = _proof_status(prior.kind, None, None, decision)
        observed = len(accepted)
        covered = prior.requirement_id in decision.covered_slots
        if decision.status == "CONTESTED":
            status = "CONTESTED"
        elif (
            prior.required_cardinality.maximum is not None
            and observed > prior.required_cardinality.maximum
        ):
            status = "UNRESOLVED"
        elif _unresolved_closed_set(prior.kind, refs["POSSIBLE"]):
            status = "UNRESOLVED"
        elif (
            observed >= prior.required_cardinality.minimum
            and covered
            and proof in {"SATISFIED", "NOT_REQUIRED"}
        ):
            status = "SATISFIED"
        elif proof == "MISSING" and (
            observed >= prior.required_cardinality.minimum
            or prior.kind in {"RANGE_COMPLETENESS", "VERSION_CHAIN", "CARDINALITY"}
        ):
            status = "COMPLETENESS_PROOF_MISSING"
        elif observed > 0 or prior.kind in {"SET_MEMBERS", "CARDINALITY"}:
            status = "UNDER_COVERED"
        elif refs["POSSIBLE"]:
            status = "UNRESOLVED"
        else:
            status = "MISSING"
        dispositions.append(
            RequirementDisposition(
                requirement_id=prior.requirement_id,
                kind=prior.kind,
                status=status,  # type: ignore[arg-type]
                required_cardinality=prior.required_cardinality,
                observed_cardinality=observed,
                proof_status=proof,
                accepted_binding_refs=refs["MATCH"],
                possible_binding_refs=refs["POSSIBLE"],
                rejected_binding_refs=refs["REJECTED"],
                accepted_evidence_refs=accepted,
                rejected_candidates=rejected,
                rejection_summary=summary,
            )
        )
    normalized_candidates = {
        key: sorted(set(values)) for key, values in sorted(candidate_refs.items())
    }
    normalized_candidates["__ALL__"] = sorted(
        {value for values in normalized_candidates.values() for value in values}
    )
    candidate_digest = canonical_sha256(normalized_candidates)
    epoch = previous.state_epoch + (candidate_digest != previous.candidate_snapshot_digest)
    material: dict[str, Any] = {
        "schema_version": "requirement-state-v0.1",
        "query_ir_digest": previous.query_ir_digest,
        "acquisition_plan_digest": previous.acquisition_plan_digest,
        "acquisition_capability_digest": previous.acquisition_capability_digest,
        "candidate_snapshot_digest": candidate_digest,
        "binding_digest": canonical_sha256(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    bindings,
                    key=lambda item: (
                        item.requirement_id,
                        item.interpretation_id,
                        item.status,
                    ),
                )
            ]
        ),
        "sufficiency_decision_digest": canonical_sha256(decision.model_dump(mode="json")),
        "sufficiency_policy_version": previous.sufficiency_policy_version,
        "state_epoch": epoch,
        "requirements": [item.model_dump(mode="json") for item in dispositions],
        "lifetime": "MEMORY_RESOLVE",
        "canonical": False,
        "canonical_mutation": False,
    }
    return RequirementState(state_digest=canonical_sha256(material), **material)


def _resolve_disposition(
    requirement: EvidenceRequirementV02,
    *,
    bindings: Sequence[RequirementBinding],
    span_by_id: Mapping[str, EvidenceSpan],
    interpretation_by_id: Mapping[str, EvidenceInterpretationCandidate],
    sufficiency: SufficiencyDecision,
    kind: RequirementKind,
    operator_family: str | None,
    completeness: str | None,
    accepted_evidence_override: Sequence[str],
) -> RequirementDisposition:
    rows = [item for item in bindings if item.requirement_id == requirement.slot_id]
    refs = {
        status: sorted(
            canonical_sha256(item.model_dump(mode="json")) for item in rows if item.status == status
        )
        for status in ("MATCH", "POSSIBLE", "REJECTED")
    }
    accepted_evidence = set(accepted_evidence_override)
    rejected_candidates: list[RejectedCandidateDisposition] = []
    for binding in rows:
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        span = span_by_id.get(interpretation.span_id) if interpretation is not None else None
        candidate_ref = (
            span.source_evidence_id
            if span is not None
            else f"interpretation:{binding.interpretation_id}"
        )
        if binding.status == "MATCH" and span is not None:
            accepted_evidence.add(span.source_evidence_id)
        elif binding.status == "REJECTED":
            rejected_candidates.append(
                RejectedCandidateDisposition(
                    candidate_ref=candidate_ref,
                    binding_ref=canonical_sha256(binding.model_dump(mode="json")),
                    reason_code=binding.reason_code,
                )
            )
    rejected_candidates.sort(
        key=lambda item: (item.candidate_ref, item.binding_ref, item.reason_code)
    )
    summary = dict(sorted(Counter(item.reason_code for item in rejected_candidates).items()))
    accepted = sorted(accepted_evidence)
    proof = _proof_status(kind, operator_family, completeness, sufficiency)
    observed = len(accepted)
    minimum = requirement.cardinality.minimum
    covered = requirement.slot_id in sufficiency.covered_slots
    proof_good = proof in {"SATISFIED", "NOT_REQUIRED"}
    if sufficiency.status == "CONTESTED":
        status = "CONTESTED"
    elif requirement.cardinality.maximum is not None and observed > requirement.cardinality.maximum:
        status = "UNRESOLVED"
    elif _unresolved_closed_set(kind, refs["POSSIBLE"]):
        status = "UNRESOLVED"
    elif observed >= minimum and covered and proof_good:
        status = "SATISFIED"
    elif proof == "MISSING" and (
        observed >= minimum or kind in {"RANGE_COMPLETENESS", "VERSION_CHAIN", "CARDINALITY"}
    ):
        status = "COMPLETENESS_PROOF_MISSING"
    elif observed > 0 or kind in {"SET_MEMBERS", "CARDINALITY"}:
        status = "UNDER_COVERED"
    elif refs["POSSIBLE"] or proof == "UNRESOLVED":
        status = "UNRESOLVED"
    else:
        status = "MISSING"
    return RequirementDisposition(
        requirement_id=requirement.slot_id,
        kind=kind,
        status=status,  # type: ignore[arg-type]
        required_cardinality=RequirementCardinalityState(
            minimum=minimum,
            maximum=requirement.cardinality.maximum,
            distinct=requirement.cardinality.distinct,
        ),
        observed_cardinality=observed,
        proof_status=proof,
        accepted_binding_refs=refs["MATCH"],
        possible_binding_refs=refs["POSSIBLE"],
        rejected_binding_refs=refs["REJECTED"],
        accepted_evidence_refs=accepted,
        rejected_candidates=rejected_candidates,
        rejection_summary=summary,
    )


def _unresolved_closed_set(
    kind: RequirementKind,
    possible_binding_refs: Sequence[str],
) -> bool:
    """Keep set closure open while any admitted member remains unresolved."""

    return bool(possible_binding_refs) and kind in {
        "SET_MEMBERS",
        "CARDINALITY",
        "RANGE_COMPLETENESS",
    }


def _requirement_kind(
    requirement: EvidenceRequirementV02,
    query_ir: MemoryQueryIRV02 | None,
    operator_family: str | None,
) -> RequirementKind:
    slot = requirement.slot_id.upper()
    predicates = " ".join(requirement.predicate_constraints).upper()
    if "CONFLICT" in slot or "CONFLICT" in predicates:
        return "CONFLICT_SIDE"
    if query_ir is not None and query_ir.completeness == "COMPLETE_VERSION_CHAIN":
        return "VERSION_CHAIN"
    if operator_family == "WHY_CHANGE" or "PROVENANCE" in slot:
        return "PROVENANCE"
    if operator_family == "COUNT":
        return "CARDINALITY"
    if query_ir is not None and query_ir.completeness == "ALL_MATCHES_IN_RANGE":
        return "RANGE_COMPLETENESS"
    if requirement.slot_id == "CURRENT_INTENT":
        return "VALUE_SLOT"
    if (
        requirement.cardinality.minimum > 1
        or requirement.cardinality.maximum is None
        or requirement.cardinality.distinct
        or (query_ir is not None and query_ir.answer_shape == "LIST")
    ):
        return "SET_MEMBERS"
    if requirement.interpretation_kind == "EVENT":
        return "EVENT_SLOT"
    return "VALUE_SLOT"


def _proof_status(
    kind: RequirementKind,
    operator_family: str | None,
    completeness: str | None,
    sufficiency: SufficiencyDecision,
) -> RequirementProofStatus:
    if sufficiency.status == "CONTESTED":
        return "CONTESTED"
    proof = sufficiency.proof
    if kind == "VERSION_CHAIN":
        return "SATISFIED" if proof.version_chain_complete else "MISSING"
    range_proof_required = completeness == "ALL_MATCHES_IN_RANGE" or kind in {
        "RANGE_COMPLETENESS",
        "CARDINALITY",
    }
    if range_proof_required:
        complete = (
            proof.bounded_scan_completed
            and proof.source_partition_closed
            and proof.projection_watermark is not None
            and (operator_family != "COUNT" or proof.deduplication_completed)
        )
        return "SATISFIED" if complete else "MISSING"
    if kind == "PROVENANCE":
        return (
            "SATISFIED"
            if sufficiency.status == "COMPLETE" and bool(sufficiency.covered_slots)
            else "MISSING"
        )
    return "NOT_REQUIRED"


__all__ = [
    "SUFFICIENCY_POLICY_VERSION",
    "UNRESOLVED_CAPABILITY_DIGEST",
    "advance_requirement_state",
    "resolve_compat_requirement_state",
    "resolve_initial_requirement_state",
    "resolve_requirement_state",
]
