"""Query-time preference evidence synthesis without canonical promotion."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, cast

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.application.query_ir_compat import infer_operator_family
from milai.domain.preference_evidence import (
    PreferenceEvidenceSignal,
    PreferenceEvidenceView,
    PreferenceRequirementSlot,
    PreferenceViewCompleteness,
)
from milai.domain.retrieval import QueryPlan


def synthesize_preference_evidence_view(
    plan: QueryPlan,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Build an evidence-only view and leave currentness/authority unresolved."""

    query_ir = plan.memory_query_ir
    if query_ir is None or infer_operator_family(query_ir) != "PREFERENCE_RESOLVE":
        return None
    preference_requirements = [
        requirement
        for requirement in query_ir.requirements
        if requirement.slot_id == "PREFERENCE_SIGNAL_SET"
        and requirement.interpretation_kind == "PREFERENCE_SIGNAL"
    ]
    current_intent_requirements = [
        requirement
        for requirement in query_ir.requirements
        if requirement.slot_id == "CURRENT_INTENT" and requirement.interpretation_kind == "DECISION"
    ]
    if len(preference_requirements) != 1 or len(current_intent_requirements) > 1:
        return _view(
            [],
            [],
            "ABSENT",
            "OPERATOR_SLOT_SCHEMA_INVALID",
            [],
            current_intent_required=False,
            current_intent_evidence_refs=[],
            current_intent_source_turn_refs=[],
        )
    requirements = [*preference_requirements, *current_intent_requirements]
    spans = project_evidence_spans(evidence)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(requirements, interpretations, spans)
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation for interpretation in interpretations
    }
    signals: dict[str, PreferenceEvidenceSignal] = {}
    current_intent_evidence_refs: list[str] = []
    current_intent_source_turn_refs: list[str] = []
    for binding in bindings:
        if binding.status != "MATCH":
            continue
        interpretation = interpretation_by_id[binding.interpretation_id]
        span = span_by_id[interpretation.span_id]
        if binding.requirement_id == "CURRENT_INTENT":
            current_intent_evidence_refs.append(span.source_evidence_id)
            current_intent_source_turn_refs.append(span.source_turn_ref)
            continue
        if binding.requirement_id != "PREFERENCE_SIGNAL_SET":
            continue
        if not isinstance(interpretation.value, Mapping):
            continue
        stance = interpretation.value.get("stance")
        if stance not in {"POSITIVE", "NEGATIVE"}:
            continue
        signal = PreferenceEvidenceSignal(
            evidence_id=span.source_evidence_id,
            source_turn_ref=span.source_turn_ref,
            session_id=span.session_id,
            stance=cast(Literal["POSITIVE", "NEGATIVE"], stance),
            text=span.text,
            observed_at=(
                span.source_timestamp.isoformat() if span.source_timestamp is not None else None
            ),
            span=span.model_dump(mode="json"),
            interpretation=interpretation.model_dump(mode="json"),
            requirement_binding=binding.model_dump(mode="json"),
        )
        signals.setdefault(interpretation.interpretation_id, signal)
    ordered = sorted(
        signals.values(),
        key=lambda item: (
            item.observed_at or "",
            item.source_turn_ref,
            item.evidence_id,
        ),
    )
    subject_terms = list(preference_requirements[0].entity_constraints)
    current_required = bool(current_intent_requirements)
    current_evidence = _unique(current_intent_evidence_refs)
    current_sources = _unique(current_intent_source_turn_refs)
    if not ordered:
        return _view(
            [],
            subject_terms,
            "ABSENT",
            "PREFERENCE_SIGNAL_MISSING",
            (["CURRENT_INTENT_MISSING"] if current_required and not current_evidence else []),
            current_intent_required=current_required,
            current_intent_evidence_refs=current_evidence,
            current_intent_source_turn_refs=current_sources,
        )
    stances = {signal.stance for signal in ordered}
    if len(stances) > 1:
        return _view(
            ordered,
            subject_terms,
            "CONTESTED",
            "PREFERENCE_EVIDENCE_CONFLICT",
            [
                "CONFLICT_UNRESOLVED",
                "CANONICAL_CURRENTNESS_UNPROVEN",
                *(["CURRENT_INTENT_MISSING"] if current_required and not current_evidence else []),
            ],
            current_intent_required=current_required,
            current_intent_evidence_refs=current_evidence,
            current_intent_source_turn_refs=current_sources,
        )
    return _view(
        ordered,
        subject_terms,
        "PARTIAL",
        "NON_CANONICAL_PREFERENCE_EVIDENCE",
        [
            "CANONICAL_CURRENTNESS_UNPROVEN",
            *(["CURRENT_INTENT_MISSING"] if current_required and not current_evidence else []),
        ],
        current_intent_required=current_required,
        current_intent_evidence_refs=current_evidence,
        current_intent_source_turn_refs=current_sources,
    )


def prioritize_preference_evidence(
    evidence: Sequence[dict[str, Any]], derived: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    if derived is None or derived.get("kind") != "PREFERENCE_EVIDENCE_VIEW":
        return list(evidence)
    refs = [str(value) for value in derived.get("evidence_refs", []) if isinstance(value, str)]
    priority = {evidence_id: index for index, evidence_id in enumerate(refs)}
    return sorted(
        evidence,
        key=lambda item: (
            priority.get(str(item.get("evidence_id")), len(priority)),
            str(item.get("evidence_id", "")),
        ),
    )


def _view(
    signals: Sequence[PreferenceEvidenceSignal],
    subject_terms: list[str],
    status: Literal["PARTIAL", "ABSENT", "CONTESTED"],
    reason: str,
    unresolved: list[str],
    *,
    current_intent_required: bool,
    current_intent_evidence_refs: list[str],
    current_intent_source_turn_refs: list[str],
) -> dict[str, Any]:
    signal_values = list(signals)
    evidence_refs = _unique(
        [
            *(signal.evidence_id for signal in signal_values),
            *current_intent_evidence_refs,
        ]
    )
    source_refs = _unique(
        [
            *(signal.source_turn_ref for signal in signal_values),
            *current_intent_source_turn_refs,
        ]
    )
    support_met = bool(signal_values)
    required_slots: list[PreferenceRequirementSlot] = ["PREFERENCE_SIGNAL_SET"]
    if current_intent_required:
        required_slots.append("CURRENT_INTENT")
    filled_slots: list[PreferenceRequirementSlot] = []
    if support_met:
        filled_slots.append("PREFERENCE_SIGNAL_SET")
    if current_intent_evidence_refs:
        filled_slots.append("CURRENT_INTENT")
    return PreferenceEvidenceView.model_validate(
        {
            "status": status,
            "value": signal_values,
            "display_value": (f"{len(signal_values)} non-canonical preference evidence signal(s)"),
            "reason": reason,
            "subject_terms": subject_terms,
            "evidence_refs": evidence_refs,
            "source_turn_refs": source_refs,
            "current_intent_evidence_refs": current_intent_evidence_refs,
            "current_intent_source_turn_refs": current_intent_source_turn_refs,
            "completeness": PreferenceViewCompleteness(
                required_slots=required_slots,
                filled_slots=filled_slots,
                support_threshold_met=support_met,
                unresolved_reasons=unresolved,
            ),
        }
    ).payload()


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "prioritize_preference_evidence",
    "synthesize_preference_evidence_view",
]
