"""Single deterministic owner of final DG-27 Binding and Sufficiency decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, cast

from milai.application.evidence_semantics import (
    bind_requirements,
    evidence_source_eligible,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.formation_identity import select_event_identity_representatives
from milai.application.requirement_state import resolve_requirement_state
from milai.domain.acquisition import AcquisitionPlan, CandidateEnvelope
from milai.domain.decision_boundary import (
    AcceptedBindingV02,
    DecisionBoundaryResultV02,
    ProvisionalBindingV01,
    SemanticHypothesisV02,
    SemanticInterpretationSetV02,
)
from milai.domain.formation_artifact import FormationEventCandidateV01
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    InterpretationEventTime,
    MemoryQueryIRV02,
    RequirementBinding,
)
from milai.domain.sufficiency import SufficiencyDecision, SufficiencyProof

_FINAL_PROFILE = "decision-boundary-v0.2"


class DecisionBoundaryError(ValueError):
    """A candidate, hypothesis, or source identity violated the final boundary."""


def build_provisional_bindings(
    requirement_id: str,
    interpretation_sets: Sequence[SemanticInterpretationSetV02],
) -> list[ProvisionalBindingV01]:
    """Preserve ambiguity without creating an AcceptedBinding."""

    provisional: list[ProvisionalBindingV01] = []
    for interpretation_set in sorted(
        interpretation_sets, key=lambda item: item.candidate_id
    ):
        hypotheses = interpretation_set.hypotheses
        substantive = [item for item in hypotheses if item.relation != "IRRELEVANT"]
        support = [
            item for item in substantive if item.relation in {"SUPPORT", "UPDATE"}
        ]
        contradict = [item for item in substantive if item.relation == "CONTRADICT"]
        semantic_signatures = {
            canonical_sha256(
                {
                    "relation": item.relation,
                    "subjects": item.normalized_subjects,
                    "predicate": item.normalized_predicate,
                    "value": item.normalized_value,
                    "unit": item.normalized_unit,
                    "event_time": (
                        item.event_time_hypothesis.model_dump(mode="json")
                        if item.event_time_hypothesis is not None
                        else None
                    ),
                }
            )
            for item in substantive
        }
        unresolved = set(interpretation_set.ambiguity_reasons)
        if not substantive:
            status: Literal["POSSIBLE", "AMBIGUOUS", "CONTRADICTORY", "IRRELEVANT"] = (
                "AMBIGUOUS" if unresolved else "IRRELEVANT"
            )
        elif support and contradict:
            status = "AMBIGUOUS"
            unresolved.add("CONFLICTING_SEMANTIC_RELATIONS")
        elif len(semantic_signatures) > 1 or unresolved:
            status = "AMBIGUOUS"
            unresolved.add("MULTIPLE_SEMANTIC_HYPOTHESES")
        elif contradict:
            status = "CONTRADICTORY"
        else:
            status = "POSSIBLE"
        provisional.append(
            ProvisionalBindingV01(
                candidate_id=interpretation_set.candidate_id,
                requirement_id=requirement_id,
                status=status,
                supporting_interpretation_ids=sorted(
                    item.hypothesis_id for item in substantive
                ),
                unresolved_checks=sorted(unresolved),
            )
        )
    return provisional


def decide_deterministic_boundary(
    *,
    plan: AcquisitionPlan,
    query_ir: MemoryQueryIRV02,
    acquisition_capability_digest: str,
    candidates: Sequence[CandidateEnvelope],
    source_records: Sequence[Mapping[str, Any]],
    completion_proof: SufficiencyProof,
    formation_events: Sequence[FormationEventCandidateV01] = (),
    state_epoch: int = 0,
) -> DecisionBoundaryResultV02:
    """Run existing deterministic interpretation, then decide exactly once."""

    spans = project_evidence_spans(source_records)
    interpretations = interpret_evidence_spans(spans, resolve_local_anchors=True)
    spans, interpretations = _merge_formation_events(
        source_records,
        spans,
        interpretations,
        formation_events,
    )
    bindings = bind_requirements(
        query_ir.requirements,
        interpretations,
        spans,
        compatibility_profile="dg22-v0.2",
    )
    source_by_span = {item.span_id: item.source_evidence_id for item in spans}
    interpretation_by_id = {
        item.interpretation_id: item for item in interpretations
    }
    admitted_by_requirement = {
        requirement.slot_id: {
            candidate.source_evidence_id
            for candidate in candidates
            if requirement.slot_id in candidate.matched_slots
        }
        for requirement in query_ir.requirements
        if requirement.required
    }
    bindings = [
        binding
        for binding in bindings
        if source_by_span[
            interpretation_by_id[binding.interpretation_id].span_id
        ]
        in admitted_by_requirement.get(binding.requirement_id, set())
    ]
    return _finalize(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest=acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        provisional_bindings=[],
        rejected_hypotheses={},
        completion_proof=completion_proof,
        state_epoch=state_epoch,
    )


def _merge_formation_events(
    source_records: Sequence[Mapping[str, Any]],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    formation_events: Sequence[FormationEventCandidateV01],
) -> tuple[list[EvidenceSpan], list[EvidenceInterpretationCandidate]]:
    """Add exact noncanonical Formation events and replace weaker local readings."""

    if not formation_events:
        return list(spans), list(interpretations)
    source_by_id = {
        str(item["evidence_id"]): item
        for item in source_records
        if isinstance(item.get("evidence_id"), str)
    }
    span_by_id = {item.span_id: item for item in spans}
    output_interpretations = list(interpretations)
    output_spans = list(spans)
    for event in sorted(formation_events, key=lambda item: item.artifact_digest):
        if event.negated:
            continue
        source = source_by_id.get(event.span.evidence_id)
        if source is None or not evidence_source_eligible(source):
            raise DecisionBoundaryError("FORMATION_EVENT_SOURCE_NOT_ADMITTED")
        if str(source.get("source_ref")) != event.span.source_ref:
            raise DecisionBoundaryError("FORMATION_EVENT_SOURCE_IDENTITY_MISMATCH")
        content = source.get("content")
        if (
            not isinstance(content, str)
            or event.span.end > len(content)
            or content[event.span.start : event.span.end] != event.span.text
        ):
            raise DecisionBoundaryError("FORMATION_EVENT_SPAN_NOT_SOURCE_EXACT")
        covering = next(
            (
                item
                for item in spans
                if item.source_evidence_id == event.span.evidence_id
                and item.start <= event.span.start
                and item.end >= event.span.end
            ),
            None,
        )
        if covering is None:
            raise DecisionBoundaryError("FORMATION_EVENT_NOT_IN_PROJECTED_SOURCE")
        formed_span_id = canonical_sha256(
            {
                "kind": "formation-event-span-v0.1",
                "artifact_digest": event.artifact_digest,
                "evidence_id": event.span.evidence_id,
                "start": event.span.start,
                "end": event.span.end,
                "text": event.span.text,
            }
        )
        formed_span = EvidenceSpan(
            span_id=formed_span_id,
            source_evidence_id=event.span.evidence_id,
            source_turn_ref=event.span.source_ref,
            subject_id=covering.subject_id,
            session_id=covering.session_id,
            turn_id=covering.turn_id,
            identity_source=covering.identity_source,
            speaker=covering.speaker,
            start=event.span.start,
            end=event.span.end,
            text=event.span.text,
            source_timestamp=covering.source_timestamp,
            provenance={
                **covering.provenance,
                "formation_artifact_digest": event.artifact_digest,
                "formation_noncanonical": True,
            },
        )
        formed_interpretation_id = canonical_sha256(
            {
                "kind": "formation-event-interpretation-v0.1",
                "artifact_digest": event.artifact_digest,
                "span_id": formed_span_id,
            }
        )
        local_event_entities = {
            entity
            for item in interpret_evidence_spans([formed_span])
            if item.kind == "EVENT"
            for entity in item.entities
        }
        formed_interpretation = EvidenceInterpretationCandidate(
            interpretation_id=formed_interpretation_id,
            span_id=formed_span_id,
            kind="EVENT",
            value={
                "text": event.span.text,
                "event_status": "OCCURRED",
                "event_identity": event.event_identity_key,
            },
            entities=sorted(
                {
                    value
                    for value in (event.primary_subject, *event.context_participants)
                    if value
                }
                | local_event_entities
            ),
            predicate="event_observation",
            event_time=event.occurrence_time,
            time_basis=event.time_basis,
            extractor_identity=f"formation-sidecar:{event.producer_identity}",
            confidence=event.confidence_feature,
        )
        replaced_interpretation_ids = {
            item.interpretation_id
            for item in output_interpretations
            if item.kind == "EVENT"
            and item.event_time is None
            and (base_span := span_by_id.get(item.span_id)) is not None
            and base_span.source_evidence_id == event.span.evidence_id
            and base_span.start < event.span.end
            and event.span.start < base_span.end
        }
        output_interpretations = [
            item
            for item in output_interpretations
            if item.interpretation_id not in replaced_interpretation_ids
        ]
        output_spans.append(formed_span)
        output_interpretations.append(formed_interpretation)
    return output_spans, output_interpretations


def decide_semantic_boundary(
    *,
    plan: AcquisitionPlan,
    query_ir: MemoryQueryIRV02,
    acquisition_capability_digest: str,
    candidates: Sequence[CandidateEnvelope],
    source_records: Sequence[Mapping[str, Any]],
    interpretation_sets_by_requirement: Mapping[
        str, Sequence[SemanticInterpretationSetV02]
    ],
    completion_proof: SufficiencyProof,
    state_epoch: int = 0,
) -> DecisionBoundaryResultV02:
    """Validate N-best semantics while preserving deterministic baseline ability.

    Model interpretations are additive assistance.  When they produce no valid
    binding for a requirement, Runtime falls back to its existing exact-source
    interpretation for that requirement instead of turning a model omission
    into a correct-case regression.
    """

    required = [item for item in query_ir.requirements if item.required]
    required_ids = {item.slot_id for item in required}
    if set(interpretation_sets_by_requirement) != required_ids:
        raise DecisionBoundaryError("SEMANTIC_REQUIREMENT_SET_MISMATCH")
    source_by_id = {
        str(item["evidence_id"]): item
        for item in source_records
        if isinstance(item.get("evidence_id"), str)
    }
    candidate_by_id = {item.candidate_id: item for item in candidates}
    if len(candidate_by_id) != len(candidates):
        raise DecisionBoundaryError("DUPLICATE_CANDIDATE_ID")

    spans: list[EvidenceSpan] = []
    interpretations: list[EvidenceInterpretationCandidate] = []
    hypothesis_by_interpretation: dict[str, tuple[str, SemanticHypothesisV02]] = {}
    rejected: dict[str, str] = {}
    provisional: list[ProvisionalBindingV01] = []
    for requirement in sorted(required, key=lambda item: item.slot_id):
        sets = sorted(
            interpretation_sets_by_requirement[requirement.slot_id],
            key=lambda item: item.candidate_id,
        )
        expected_candidates = sorted(
            item.candidate_id
            for item in candidates
            if requirement.slot_id in item.matched_slots
        )
        if [item.candidate_id for item in sets] != expected_candidates:
            raise DecisionBoundaryError("SEMANTIC_CANDIDATE_SET_MISMATCH")
        provisional.extend(build_provisional_bindings(requirement.slot_id, sets))
        for interpretation_set in sets:
            candidate = candidate_by_id[interpretation_set.candidate_id]
            source = source_by_id.get(candidate.source_evidence_id)
            if source is None:
                raise DecisionBoundaryError("CANDIDATE_SOURCE_MISSING")
            if str(source.get("source_ref")) != candidate.source_turn_ref:
                raise DecisionBoundaryError("CANDIDATE_SOURCE_IDENTITY_MISMATCH")
            if not evidence_source_eligible(source):
                for hypothesis in interpretation_set.hypotheses:
                    rejected[hypothesis.hypothesis_id] = "SOURCE_GATE_REJECTED"
                continue
            for hypothesis in interpretation_set.hypotheses:
                if hypothesis.relation not in {"SUPPORT", "UPDATE"}:
                    rejected[hypothesis.hypothesis_id] = (
                        f"RELATION_{hypothesis.relation}_NOT_ACCEPTABLE"
                    )
                    continue
                try:
                    additions = _materialize_hypothesis(
                        requirement,
                        candidate,
                        source,
                        hypothesis,
                    )
                except DecisionBoundaryError as error:
                    rejected[hypothesis.hypothesis_id] = str(error)
                    continue
                for span, interpretation in additions:
                    spans.append(span)
                    interpretations.append(interpretation)
                    hypothesis_by_interpretation[interpretation.interpretation_id] = (
                        interpretation_set.candidate_id,
                        hypothesis,
                    )

    bindings = bind_requirements(
        required,
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile="dg22-v0.2",
    )
    for binding in bindings:
        if binding.status != "MATCH":
            _candidate_id, hypothesis = hypothesis_by_interpretation[
                binding.interpretation_id
            ]
            rejected.setdefault(hypothesis.hypothesis_id, binding.reason_code)
    model_matched_requirements = {
        binding.requirement_id for binding in bindings if binding.status == "MATCH"
    }
    fallback_requirement_ids = required_ids - model_matched_requirements
    if fallback_requirement_ids:
        fallback_spans = project_evidence_spans(source_records)
        fallback_interpretations = interpret_evidence_spans(
            fallback_spans,
            resolve_local_anchors=True,
        )
        fallback_bindings = bind_requirements(
            [
                requirement
                for requirement in required
                if requirement.slot_id in fallback_requirement_ids
            ],
            fallback_interpretations,
            fallback_spans,
            type_compatible_only=True,
            compatibility_profile="dg22-v0.2",
        )
        admitted_source_by_requirement = {
            requirement_id: {
                candidate.source_evidence_id
                for candidate in candidates
                if requirement_id in candidate.matched_slots
            }
            for requirement_id in fallback_requirement_ids
        }
        fallback_span_by_id = {item.span_id: item for item in fallback_spans}
        fallback_interpretation_by_id = {
            item.interpretation_id: item for item in fallback_interpretations
        }
        fallback_bindings = [
            binding
            for binding in fallback_bindings
            if fallback_span_by_id[
                fallback_interpretation_by_id[binding.interpretation_id].span_id
            ].source_evidence_id
            in admitted_source_by_requirement[binding.requirement_id]
        ]
        referenced_interpretations = {
            item.interpretation_id for item in fallback_bindings
        }
        referenced_spans = {
            fallback_interpretation_by_id[item].span_id
            for item in referenced_interpretations
        }
        spans.extend(
            item for item in fallback_spans if item.span_id in referenced_spans
        )
        interpretations.extend(
            item
            for item in fallback_interpretations
            if item.interpretation_id in referenced_interpretations
        )
        bindings.extend(fallback_bindings)
    return _finalize(
        plan=plan,
        query_ir=query_ir,
        acquisition_capability_digest=acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        provisional_bindings=provisional,
        rejected_hypotheses=dict(sorted(rejected.items())),
        completion_proof=completion_proof,
        state_epoch=state_epoch,
        hypothesis_by_interpretation=hypothesis_by_interpretation,
    )


def _materialize_hypothesis(
    requirement: EvidenceRequirementV02,
    candidate: CandidateEnvelope,
    source: Mapping[str, Any],
    hypothesis: SemanticHypothesisV02,
) -> list[tuple[EvidenceSpan, EvidenceInterpretationCandidate]]:
    content = source.get("content")
    if not isinstance(content, str) or not content:
        raise DecisionBoundaryError("SOURCE_CONTENT_MISSING")
    if not hypothesis.grounded_spans:
        raise DecisionBoundaryError("GROUNDED_SPAN_MISSING")
    source_time = _timestamp(source.get("observed_at"))
    event_time = hypothesis.event_time_hypothesis
    resolved_event_time: InterpretationEventTime | None = None
    time_basis = "UNRESOLVED"
    if event_time is not None:
        time_basis = event_time.time_basis
        if event_time.start is not None:
            resolved_event_time = InterpretationEventTime(
                start=event_time.start,
                end=event_time.end,
                normalized_from=event_time.normalized_from,
                anchor_provenance={
                    "owner": "DG27_MODEL_HYPOTHESIS_RUNTIME_VALIDATED",
                    "source_time_used_as_event_time": False,
                },
            )
    values: list[tuple[EvidenceSpan, EvidenceInterpretationCandidate]] = []
    for index, grounded in enumerate(hypothesis.grounded_spans):
        if grounded.end > len(content) or content[grounded.start : grounded.end] != grounded.text:
            raise DecisionBoundaryError("GROUNDED_SPAN_NOT_SOURCE_EXACT")
        span_id = canonical_sha256(
            {
                "kind": "dg27-v02-span",
                "evidence_id": candidate.source_evidence_id,
                "start": grounded.start,
                "end": grounded.end,
                "text": grounded.text,
            }
        )
        span = EvidenceSpan(
            span_id=span_id,
            source_evidence_id=candidate.source_evidence_id,
            source_turn_ref=candidate.source_turn_ref,
            subject_id=candidate.subject_id,
            session_id=candidate.session_id,
            turn_id=candidate.turn_id,
            identity_source=candidate.identity_source,
            speaker=cast(Any, candidate.speaker),
            start=grounded.start,
            end=grounded.end,
            text=grounded.text,
            source_timestamp=source_time,
            provenance={
                "authority_class": "EVIDENCE_ONLY",
                "source_content_hash": source.get("content_hash"),
                "source_span_verified": True,
                "semantic_hypothesis_id": hypothesis.hypothesis_id,
            },
        )
        interpretation_id = canonical_sha256(
            {
                "kind": "dg27-v02-interpretation",
                "requirement_id": requirement.slot_id,
                "hypothesis_id": hypothesis.hypothesis_id,
                "span_id": span_id,
                "span_index": index,
            }
        )
        interpretation = EvidenceInterpretationCandidate(
            interpretation_id=interpretation_id,
            span_id=span_id,
            kind=requirement.interpretation_kind,
            value=hypothesis.normalized_value,
            unit=hypothesis.normalized_unit,
            entities=hypothesis.normalized_subjects,
            predicate=hypothesis.normalized_predicate,
            event_time=resolved_event_time,
            time_basis=cast(Any, time_basis),
            extractor_identity="dg27-semantic-interpretation-v0.2",
            confidence=hypothesis.confidence_feature,
        )
        values.append((span, interpretation))
    return values


def _finalize(
    *,
    plan: AcquisitionPlan,
    query_ir: MemoryQueryIRV02,
    acquisition_capability_digest: str,
    candidates: Sequence[CandidateEnvelope],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
    provisional_bindings: Sequence[ProvisionalBindingV01],
    rejected_hypotheses: Mapping[str, str],
    completion_proof: SufficiencyProof,
    state_epoch: int,
    hypothesis_by_interpretation: Mapping[
        str, tuple[str, SemanticHypothesisV02]
    ] | None = None,
) -> DecisionBoundaryResultV02:
    bindings, _identity_sidecar = select_event_identity_representatives(
        query_ir.requirements,
        bindings,
        interpretations,
        spans,
    )
    required_ids = sorted(item.slot_id for item in query_ir.requirements if item.required)
    proposed = SufficiencyDecision(
        status="COMPLETE",
        covered_slots=required_ids,
        proof=completion_proof,
        stop_reason="REQUIREMENT_SATISFIED",
    )
    initial_state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        sufficiency_decision=proposed,
        state_epoch=state_epoch,
        memory_query_ir=query_ir,
    )
    missing = initial_state.missing_requirement_ids
    satisfied = initial_state.satisfied_requirement_ids
    final_decision = (
        proposed
        if not missing
        else SufficiencyDecision(
            status="PARTIAL" if satisfied else "UNSATISFIED",
            covered_slots=satisfied,
            missing_slots=missing,
            proof=completion_proof,
            stop_reason="SEARCH_SPACE_EXHAUSTED",
        )
    )
    final_state = resolve_requirement_state(
        plan=plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=acquisition_capability_digest,
        candidates=candidates,
        spans=spans,
        interpretations=interpretations,
        bindings=bindings,
        sufficiency_decision=final_decision,
        state_epoch=state_epoch,
        memory_query_ir=query_ir,
    )
    span_by_id = {item.span_id: item for item in spans}
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    accepted: list[AcceptedBindingV02] = []
    seen: set[tuple[str, str, str]] = set()
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretation_by_id[binding.interpretation_id]
        span = span_by_id[interpretation.span_id]
        if hypothesis_by_interpretation is None:
            candidate_id = span.source_evidence_id
        elif interpretation.interpretation_id in hypothesis_by_interpretation:
            candidate_id, _hypothesis = hypothesis_by_interpretation[
                interpretation.interpretation_id
            ]
        else:
            candidate_id = span.source_evidence_id
        identity = (binding.requirement_id, span.source_evidence_id, candidate_id)
        if identity in seen:
            continue
        seen.add(identity)
        material = {
            "candidate_id": candidate_id,
            "evidence_id": span.source_evidence_id,
            "requirement_id": binding.requirement_id,
            "interpretation_id": binding.interpretation_id,
            "span_ids": [span.span_id],
            "validation_profile": _FINAL_PROFILE,
        }
        accepted.append(
            AcceptedBindingV02(
                accepted_binding_id=canonical_sha256(material),
                candidate_id=candidate_id,
                evidence_id=span.source_evidence_id,
                requirement_id=binding.requirement_id,
                interpretation_id=binding.interpretation_id,
                grounded_span_ids=[span.span_id],
            )
        )
    accepted.sort(
        key=lambda item: (item.requirement_id, item.evidence_id, item.interpretation_id)
    )
    provisional = sorted(
        provisional_bindings,
        key=lambda item: (item.requirement_id, item.candidate_id),
    )
    decision_material = {
        "profile": _FINAL_PROFILE,
        "candidate_snapshot": sorted(item.candidate_id for item in candidates),
        "provisional": [item.model_dump(mode="json") for item in provisional],
        "accepted": [item.model_dump(mode="json") for item in accepted],
        "rejected": dict(sorted(rejected_hypotheses.items())),
        "requirement_state": final_state.state_digest,
        "sufficiency": final_decision.model_dump(mode="json"),
    }
    return DecisionBoundaryResultV02(
        decision_id=canonical_sha256(decision_material),
        provisional_bindings=provisional,
        accepted_bindings=accepted,
        rejected_hypotheses=dict(sorted(rejected_hypotheses.items())),
        requirement_state=final_state,
        sufficiency_decision=final_decision,
        operator_ready=final_decision.complete and not final_state.missing_requirement_ids,
    )


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
    return None


__all__ = [
    "DecisionBoundaryError",
    "build_provisional_bindings",
    "decide_deterministic_boundary",
    "decide_semantic_boundary",
]
