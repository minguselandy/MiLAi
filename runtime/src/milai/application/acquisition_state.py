"""DG-18 query-local acquisition state and Evidence reference-note transitions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from milai.application.evidence_semantics import (
    evidence_source_eligible,
    verify_evidence_span,
)
from milai.application.evidence_source import (
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.requirement_state import (
    UNRESOLVED_CAPABILITY_DIGEST,
    resolve_compat_requirement_state,
    resolve_initial_requirement_state,
)
from milai.domain.acquisition import (
    AcquisitionAction,
    AcquisitionBudgetUse,
    AcquisitionPlan,
    AcquisitionRegion,
    AcquisitionRemainingBudget,
    AcquisitionState,
    AcquisitionWindowInterval,
    CandidateEnvelope,
    EvidenceQuoteSpanRef,
    EvidenceReferenceNote,
    RequirementAcquisitionCoverage,
)
from milai.domain.requirement_state import RequirementState
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    MemoryQueryIRV02,
    RequirementBinding,
)
from milai.domain.sufficiency import SufficiencyDecision

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_ModelT = TypeVar("_ModelT")
AcquisitionTransitionOutcome = Literal[
    "APPLIED",
    "REPEATED_ACTION",
    "REPEATED_WINDOW",
    "BUDGET_BLOCKED",
    "INVALID_REFERENCE",
]


class AcquisitionStateTransition(BaseModel):
    """One explainable state transition; rejected transitions preserve input state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-state-transition-v0.1"] = (
        "acquisition-state-transition-v0.1"
    )
    outcome: AcquisitionTransitionOutcome
    reason_code: str
    repeated_anchor_count: int = Field(default=0, ge=0)
    repeated_window_count: int = Field(default=0, ge=0)
    state: AcquisitionState
    canonical_mutation: Literal[False] = False


def initialize_acquisition_state(
    plan: AcquisitionPlan,
    requirements: Sequence[EvidenceRequirementV02],
    *,
    acquisition_capability_digest: str = UNRESOLVED_CAPABILITY_DIGEST,
    memory_query_ir: MemoryQueryIRV02 | None = None,
    requirement_state: RequirementState | None = None,
) -> AcquisitionState:
    """Create empty state from one immutable plan; no search work is performed."""

    required = sorted(
        (requirement for requirement in requirements if requirement.required),
        key=lambda requirement: requirement.slot_id,
    )
    requirement_ids = [requirement.slot_id for requirement in required]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("required acquisition requirement IDs must be unique")
    requirement_state = requirement_state or resolve_initial_requirement_state(
        plan,
        requirements,
        acquisition_capability_digest=acquisition_capability_digest,
        memory_query_ir=memory_query_ir,
    )
    if requirement_state.query_ir_digest != plan.query_ir_digest:
        raise ValueError("initial RequirementState query identity mismatch")
    if requirement_state.acquisition_plan_digest != _canonical_sha256(
        plan.model_dump(mode="json")
    ):
        raise ValueError("initial RequirementState plan identity mismatch")
    if [item.requirement_id for item in requirement_state.requirements] != requirement_ids:
        raise ValueError("initial RequirementState requirements mismatch")
    disposition_by_id = {
        item.requirement_id: item for item in requirement_state.requirements
    }
    candidate_refs = {
        requirement.slot_id: list(
            disposition_by_id[requirement.slot_id].accepted_evidence_refs
        )
        for requirement in required
    }
    coverage = {
        requirement.slot_id: RequirementAcquisitionCoverage(
            requirement_id=requirement.slot_id,
            required_minimum=requirement.cardinality.minimum,
            candidate_refs=candidate_refs[requirement.slot_id],
            accepted_evidence_refs=list(
                disposition_by_id[requirement.slot_id].accepted_evidence_refs
            ),
            covered_by_sufficiency=(
                disposition_by_id[requirement.slot_id].status == "SATISFIED"
            ),
        )
        for requirement in required
    }
    return AcquisitionState(
        query_ir_digest=plan.query_ir_digest,
        acquisition_plan_digest=_canonical_sha256(plan.model_dump(mode="json")),
        requirement_state=requirement_state,
        required_requirement_ids=requirement_ids,
        missing_requirement_ids=requirement_state.missing_requirement_ids,
        satisfied_requirement_ids=requirement_state.satisfied_requirement_ids,
        per_requirement_candidate_refs=candidate_refs,
        per_requirement_coverage=coverage,
        remaining_budget=AcquisitionRemainingBudget(
            model_calls=plan.residual_policy.max_model_calls,
            acquisition_passes=plan.residual_policy.max_extra_passes,
            candidate_count=plan.budget.candidate_count,
            context_tokens=plan.budget.context_tokens,
            latency_ms=float(plan.budget.latency_ms),
        ),
    )


def build_acquisition_action(
    *,
    action_kind: Literal[
        "DETERMINISTIC_PASS",
        "EXPAND_NEIGHBORS",
        "EXPAND_EPISODE",
        "RESIDUAL_PASS",
    ],
    pass_index: int,
    requirement_ids: Sequence[str] = (),
    probe_ids: Sequence[str] = (),
) -> AcquisitionAction:
    """Build a canonical action identity without query or cue text."""

    requirements = sorted(set(requirement_ids))
    probes = sorted(set(probe_ids))
    material = {
        "schema_version": "acquisition-action-v0.1",
        "action_kind": action_kind,
        "pass_index": pass_index,
        "requirement_ids": requirements,
        "probe_ids": probes,
    }
    return AcquisitionAction(
        action_digest=_canonical_sha256(material),
        action_kind=action_kind,
        pass_index=pass_index,
        requirement_ids=requirements,
        probe_ids=probes,
    )


def build_acquisition_window(
    *, session_id: str, turn_start: int, turn_end_exclusive: int
) -> AcquisitionWindowInterval:
    """Build an exact window identity independent of the requirement using it."""

    material = {
        "schema_version": "acquisition-window-v0.1",
        "session_id": session_id,
        "turn_start": turn_start,
        "turn_end_exclusive": turn_end_exclusive,
    }
    return AcquisitionWindowInterval(
        window_digest=_canonical_sha256(material),
        session_id=session_id,
        turn_start=turn_start,
        turn_end_exclusive=turn_end_exclusive,
    )


def build_acquisition_region(
    window: AcquisitionWindowInterval,
    action: AcquisitionAction,
    requirement_ids: Sequence[str],
) -> AcquisitionRegion:
    """Bind a window inspection to its action and still-missing requirement set."""

    requirements = sorted(set(requirement_ids))
    material = {
        "schema_version": "acquisition-region-v0.1",
        "window_digest": window.window_digest,
        "action_digest": action.action_digest,
        "requirement_ids": requirements,
    }
    return AcquisitionRegion(
        region_digest=_canonical_sha256(material),
        window_digest=window.window_digest,
        action_digest=action.action_digest,
        requirement_ids=requirements,
    )


def build_evidence_reference_note(
    source: Mapping[str, Any],
    span: EvidenceSpan,
    interpretation: EvidenceInterpretationCandidate,
    binding: RequirementBinding,
) -> EvidenceReferenceNote:
    """Build a note only from live source bytes and an existing MATCH Binding."""

    permission = source.get("permission_snapshot")
    if (
        not isinstance(permission, Mapping)
        or permission.get("readable") is not True
        or source.get("retention_state") != "READABLE"
        or not evidence_source_eligible(source)
    ):
        raise ValueError("EVIDENCE_REFERENCE_SOURCE_NOT_ELIGIBLE")
    content = source.get("content")
    if not isinstance(content, str) or not verify_evidence_span(span, content):
        raise ValueError("EVIDENCE_REFERENCE_SPAN_MISMATCH")
    if source.get("evidence_id") != span.source_evidence_id:
        raise ValueError("EVIDENCE_REFERENCE_EVIDENCE_ID_MISMATCH")
    if source.get("source_ref") != span.source_turn_ref:
        raise ValueError("EVIDENCE_REFERENCE_SOURCE_TURN_MISMATCH")
    source_identity = structured_evidence_identity(source, span.source_turn_ref)
    if source_identity is None or source_identity.subject_id != span.subject_id:
        raise ValueError("EVIDENCE_REFERENCE_SUBJECT_MISMATCH")
    if source_identity.session_id != span.session_id:
        raise ValueError("EVIDENCE_REFERENCE_SESSION_MISMATCH")
    if source_identity.turn_id != span.turn_id:
        raise ValueError("EVIDENCE_REFERENCE_TURN_MISMATCH")
    if source_identity.identity_source != span.identity_source:
        raise ValueError("EVIDENCE_REFERENCE_IDENTITY_LINEAGE_MISMATCH")
    source_speaker, _source_speaker_lineage = structured_evidence_speaker(source)
    if source_speaker != span.speaker:
        raise ValueError("EVIDENCE_REFERENCE_SPEAKER_MISMATCH")
    source_observed_time = _aware_datetime(source.get("observed_at"))
    if source_observed_time != span.source_timestamp:
        raise ValueError("EVIDENCE_REFERENCE_SOURCE_TIME_MISMATCH")
    if interpretation.span_id != span.span_id:
        raise ValueError("EVIDENCE_REFERENCE_INTERPRETATION_SPAN_MISMATCH")
    if binding.interpretation_id != interpretation.interpretation_id:
        raise ValueError("EVIDENCE_REFERENCE_BINDING_INTERPRETATION_MISMATCH")
    if binding.status != "MATCH":
        raise ValueError("EVIDENCE_REFERENCE_BINDING_NOT_MATCHED")

    quote_sha256 = hashlib.sha256(span.text.encode("utf-8")).hexdigest()
    event_time = (
        interpretation.event_time.model_dump(mode="json")
        if interpretation.event_time is not None
        else None
    )
    observed_terms = _observed_terms(span.text)
    note_material = {
        "schema_version": "evidence-reference-note-v0.2",
        "requirement_id": binding.requirement_id,
        "evidence_id": span.source_evidence_id,
        "source_turn_ref": span.source_turn_ref,
        "subject_id": span.subject_id,
        "session_id": span.session_id,
        "turn_id": span.turn_id,
        "identity_source": span.identity_source,
        "span_id": span.span_id,
        "start": span.start,
        "end": span.end,
        "quote_sha256": quote_sha256,
        "interpretation_ref": interpretation.interpretation_id,
        "observed_terms": observed_terms,
        "source_observed_time": (
            span.source_timestamp.isoformat()
            if span.source_timestamp is not None
            else None
        ),
        "event_time": event_time,
        "note_reason": binding.reason_code,
        "authority_class": "EVIDENCE_ONLY",
        "canonical": False,
        "canonical_mutation": False,
    }
    return EvidenceReferenceNote(
        note_id=_canonical_sha256(note_material),
        requirement_id=binding.requirement_id,
        evidence_id=span.source_evidence_id,
        source_turn_ref=span.source_turn_ref,
        subject_id=span.subject_id,
        session_id=span.session_id,
        turn_id=span.turn_id,
        identity_source=span.identity_source,
        quote_span=EvidenceQuoteSpanRef(
            span_id=span.span_id,
            start=span.start,
            end=span.end,
            quote_sha256=quote_sha256,
        ),
        interpretation_ref=interpretation.interpretation_id,
        observed_terms=observed_terms,
        source_observed_time=span.source_timestamp,
        event_time=event_time,
        note_reason=binding.reason_code,
    )


def advance_acquisition_state(
    state: AcquisitionState,
    action: AcquisitionAction,
    *,
    candidates: Sequence[CandidateEnvelope] = (),
    bindings: Sequence[RequirementBinding] = (),
    notes: Sequence[EvidenceReferenceNote] = (),
    seen_anchor_ids: Sequence[str] = (),
    windows: Sequence[AcquisitionWindowInterval] = (),
    inspected_regions: Sequence[AcquisitionRegion] = (),
    exhausted_regions: Sequence[AcquisitionRegion] = (),
    sufficiency_decision: SufficiencyDecision | None = None,
    requirement_state: RequirementState | None = None,
    budget_use: AcquisitionBudgetUse | None = None,
) -> AcquisitionStateTransition:
    """Apply one bounded pass without assigning truth, authority, or completeness."""

    if action.action_digest in {item.action_digest for item in state.prior_actions}:
        return _unchanged(state, "REPEATED_ACTION", "ACQUISITION_ACTION_ALREADY_EXECUTED")
    if len(state.prior_actions) >= 2:
        return _unchanged(state, "BUDGET_BLOCKED", "ACQUISITION_PASS_LIMIT_REACHED")

    use = budget_use or AcquisitionBudgetUse()
    if action.action_kind == "DETERMINISTIC_PASS" and (
        state.prior_actions or use.model_calls or use.acquisition_passes
    ):
        return _unchanged(
            state,
            "INVALID_REFERENCE",
            "DETERMINISTIC_PASS_ORDER_OR_COST_INVALID",
        )
    if action.action_kind != "DETERMINISTIC_PASS" and (
        not state.prior_actions
        or state.prior_actions[0].action_kind != "DETERMINISTIC_PASS"
        or use.acquisition_passes != 1
    ):
        return _unchanged(
            state,
            "INVALID_REFERENCE",
            "RESIDUAL_PASS_ORDER_OR_COST_INVALID",
        )

    required = set(state.required_requirement_ids)
    if not set(action.requirement_ids).issubset(set(state.missing_requirement_ids)):
        return _unchanged(
            state,
            "INVALID_REFERENCE",
            "ACTION_MUST_TARGET_CURRENT_MISSING_REQUIREMENTS",
        )
    if any(not set(region.requirement_ids).issubset(required) for region in inspected_regions):
        return _unchanged(state, "INVALID_REFERENCE", "REGION_REQUIREMENT_UNKNOWN")
    if any(region.action_digest != action.action_digest for region in inspected_regions):
        return _unchanged(state, "INVALID_REFERENCE", "REGION_ACTION_MISMATCH")
    known_windows = {
        item.window_digest for item in [*state.seen_window_intervals, *windows]
    }
    if any(region.window_digest not in known_windows for region in inspected_regions):
        return _unchanged(state, "INVALID_REFERENCE", "REGION_WINDOW_UNKNOWN")
    inspected_by_id = {
        item.region_digest: item for item in [*state.inspected_regions, *inspected_regions]
    }
    if any(region.region_digest not in inspected_by_id for region in exhausted_regions):
        return _unchanged(state, "INVALID_REFERENCE", "EXHAUSTED_REGION_NOT_INSPECTED")

    binding_index = {
        (binding.requirement_id, binding.interpretation_id): binding for binding in bindings
    }
    for note in notes:
        if note.requirement_id not in required:
            return _unchanged(state, "INVALID_REFERENCE", "NOTE_REQUIREMENT_UNKNOWN")
        binding = binding_index.get((note.requirement_id, note.interpretation_ref))
        if binding is None or binding.status != "MATCH":
            return _unchanged(state, "INVALID_REFERENCE", "NOTE_MATCH_BINDING_MISSING")

    remaining = state.remaining_budget
    if (
        use.model_calls > remaining.model_calls
        or use.acquisition_passes > remaining.acquisition_passes
        or use.candidate_count > remaining.candidate_count
        or use.context_tokens > remaining.context_tokens
        or use.latency_ms > remaining.latency_ms
    ):
        return _unchanged(state, "BUDGET_BLOCKED", "ACQUISITION_BUDGET_EXCEEDED")

    existing_windows = {item.window_digest for item in state.seen_window_intervals}
    new_windows = _unique_models(windows, "window_digest", existing_windows)
    repeated_window_count = len(windows) - len(new_windows)
    if windows and not new_windows and not candidates and not notes and not inspected_regions:
        return AcquisitionStateTransition(
            outcome="REPEATED_WINDOW",
            reason_code="ACQUISITION_WINDOW_ALREADY_INSPECTED",
            repeated_window_count=repeated_window_count,
            state=state,
        )

    candidate_refs = {
        requirement_id: list(state.per_requirement_candidate_refs[requirement_id])
        for requirement_id in state.required_requirement_ids
    }
    for candidate in candidates:
        for requirement_id in candidate.matched_slots:
            if requirement_id in candidate_refs:
                _append_unique(candidate_refs[requirement_id], candidate.source_evidence_id)
    for note in notes:
        _append_unique(candidate_refs[note.requirement_id], note.evidence_id)

    prior_notes = {note.note_id: note for note in state.accepted_evidence_refs}
    for note in notes:
        prior_notes.setdefault(note.note_id, note)
    next_requirement_state = requirement_state or resolve_compat_requirement_state(
        state.requirement_state,
        candidate_refs=candidate_refs,
        bindings=bindings,
        notes=list(prior_notes.values()),
        sufficiency_decision=sufficiency_decision,
    )
    if not _requirement_state_transition_valid(state.requirement_state, next_requirement_state):
        return _unchanged(
            state,
            "INVALID_REFERENCE",
            "REQUIREMENT_STATE_IDENTITY_OR_EPOCH_MISMATCH",
        )
    satisfied = next_requirement_state.satisfied_requirement_ids
    missing = next_requirement_state.missing_requirement_ids
    coverage = _updated_coverage(
        state,
        candidate_refs,
        bindings,
        list(prior_notes.values()),
        satisfied,
    )

    prior_anchor_ids = set(state.seen_anchor_ids)
    anchor_values = [
        *seen_anchor_ids,
        *(candidate.source_evidence_id for candidate in candidates),
    ]
    repeated_anchor_count = sum(value in prior_anchor_ids for value in set(anchor_values))
    all_anchor_ids = list(state.seen_anchor_ids)
    for value in anchor_values:
        _append_unique(all_anchor_ids, value)

    updated = state.model_copy(
        update={
            "requirement_state": next_requirement_state,
            "missing_requirement_ids": missing,
            "satisfied_requirement_ids": satisfied,
            "prior_actions": [*state.prior_actions, action],
            "seen_anchor_ids": all_anchor_ids,
            "seen_window_intervals": [*state.seen_window_intervals, *new_windows],
            "inspected_regions": _merge_by_identity(
                state.inspected_regions, inspected_regions, "region_digest"
            ),
            "exhausted_regions": _merge_by_identity(
                state.exhausted_regions, exhausted_regions, "region_digest"
            ),
            "accepted_evidence_refs": list(prior_notes.values()),
            "per_requirement_candidate_refs": candidate_refs,
            "per_requirement_coverage": coverage,
            "remaining_budget": AcquisitionRemainingBudget(
                model_calls=remaining.model_calls - use.model_calls,
                acquisition_passes=(remaining.acquisition_passes - use.acquisition_passes),
                candidate_count=remaining.candidate_count - use.candidate_count,
                context_tokens=remaining.context_tokens - use.context_tokens,
                latency_ms=round(remaining.latency_ms - use.latency_ms, 3),
            ),
        }
    )
    # ``model_copy`` intentionally skips validation in Pydantic; revalidate the
    # complete state so a transition cannot bypass the domain invariants.
    validated = AcquisitionState.model_validate(updated.model_dump(mode="json"))
    return AcquisitionStateTransition(
        outcome="APPLIED",
        reason_code="ACQUISITION_STATE_ADVANCED",
        repeated_anchor_count=repeated_anchor_count,
        repeated_window_count=repeated_window_count,
        state=validated,
    )


def reserve_residual_controller_call(
    state: AcquisitionState, plan: AcquisitionPlan
) -> AcquisitionStateTransition:
    """Atomically reserve the one controller call from the query-local state."""

    if (
        state.query_ir_digest != plan.query_ir_digest
        or state.acquisition_plan_digest
        != _canonical_sha256(plan.model_dump(mode="json"))
    ):
        return _unchanged(
            state,
            "INVALID_REFERENCE",
            "ACQUISITION_PLAN_IDENTITY_MISMATCH",
        )
    if (
        not plan.residual_policy.allowed
        or not state.missing_requirement_ids
        or not state.prior_actions
        or state.prior_actions[0].action_kind != "DETERMINISTIC_PASS"
    ):
        return _unchanged(state, "INVALID_REFERENCE", "RESIDUAL_CONTROLLER_NOT_ELIGIBLE")
    remaining = state.remaining_budget
    if (
        state.residual_model_call_count != 0
        or remaining.model_calls < 1
        or remaining.acquisition_passes < 1
        or remaining.candidate_count < 1
        or remaining.context_tokens < 1
        or remaining.latency_ms <= 0
    ):
        return _unchanged(
            state,
            "BUDGET_BLOCKED",
            "RESIDUAL_CONTROLLER_BUDGET_EXHAUSTED",
        )
    updated = state.model_copy(
        update={
            "residual_model_call_count": 1,
            "remaining_budget": remaining.model_copy(
                update={"model_calls": remaining.model_calls - 1}
            ),
        }
    )
    return AcquisitionStateTransition(
        outcome="APPLIED",
        reason_code="RESIDUAL_CONTROLLER_CALL_RESERVED",
        state=AcquisitionState.model_validate(updated.model_dump(mode="json")),
    )


def acquisition_state_trace_summary(state: AcquisitionState) -> dict[str, Any]:
    """Return bounded trace metadata with no query, cue, snippet, or source text."""

    return {
        "schema_version": "acquisition-state-trace-v0.1",
        "query_ir_digest": state.query_ir_digest,
        "acquisition_plan_digest": state.acquisition_plan_digest,
        "requirement_state_digest": state.requirement_state.state_digest,
        "requirement_state_epoch": state.requirement_state.state_epoch,
        "acquisition_capability_digest": (
            state.requirement_state.acquisition_capability_digest
        ),
        "missing_requirement_ids": list(state.missing_requirement_ids),
        "satisfied_requirement_ids": list(state.satisfied_requirement_ids),
        "prior_action_digests": [item.action_digest for item in state.prior_actions],
        "residual_model_call_count": state.residual_model_call_count,
        "seen_anchor_count": len(state.seen_anchor_ids),
        "seen_window_digests": [
            item.window_digest for item in state.seen_window_intervals
        ],
        "inspected_region_digests": [
            item.region_digest for item in state.inspected_regions
        ],
        "exhausted_region_digests": [
            item.region_digest for item in state.exhausted_regions
        ],
        "accepted_evidence_note_count": len(state.accepted_evidence_refs),
        "per_requirement_coverage": {
            requirement_id: {
                "kind": next(
                    item.kind
                    for item in state.requirement_state.requirements
                    if item.requirement_id == requirement_id
                ),
                "status": next(
                    item.status
                    for item in state.requirement_state.requirements
                    if item.requirement_id == requirement_id
                ),
                "proof_status": next(
                    item.proof_status
                    for item in state.requirement_state.requirements
                    if item.requirement_id == requirement_id
                ),
                "candidate_count": len(value.candidate_refs),
                "matched_interpretation_count": len(value.matched_interpretation_refs),
                "possible_interpretation_count": len(value.possible_interpretation_refs),
                "rejected_interpretation_count": len(value.rejected_interpretation_refs),
                "accepted_evidence_count": len(value.accepted_evidence_refs),
                "covered_by_sufficiency": value.covered_by_sufficiency,
            }
            for requirement_id, value in state.per_requirement_coverage.items()
        },
        "remaining_budget": state.remaining_budget.model_dump(mode="json"),
        "lifetime": state.lifetime,
        "canonical": state.canonical,
        "canonical_mutation": state.canonical_mutation,
    }


def _updated_coverage(
    state: AcquisitionState,
    candidate_refs: dict[str, list[str]],
    bindings: Sequence[RequirementBinding],
    notes: Sequence[EvidenceReferenceNote],
    satisfied: Sequence[str],
) -> dict[str, RequirementAcquisitionCoverage]:
    by_requirement: dict[str, list[RequirementBinding]] = {
        requirement_id: [] for requirement_id in state.required_requirement_ids
    }
    for binding in bindings:
        if binding.requirement_id in by_requirement:
            by_requirement[binding.requirement_id].append(binding)
    result: dict[str, RequirementAcquisitionCoverage] = {}
    for requirement_id in state.required_requirement_ids:
        previous = state.per_requirement_coverage[requirement_id]
        current = by_requirement[requirement_id]
        accepted = [
            note.evidence_id for note in notes if note.requirement_id == requirement_id
        ]
        result[requirement_id] = RequirementAcquisitionCoverage(
            requirement_id=requirement_id,
            required_minimum=previous.required_minimum,
            candidate_refs=candidate_refs[requirement_id],
            matched_interpretation_refs=_unique(
                [
                    *previous.matched_interpretation_refs,
                    *(
                        item.interpretation_id
                        for item in current
                        if item.status == "MATCH"
                    ),
                ]
            ),
            possible_interpretation_refs=_unique(
                [
                    *previous.possible_interpretation_refs,
                    *(
                        item.interpretation_id
                        for item in current
                        if item.status == "POSSIBLE"
                    ),
                ]
            ),
            rejected_interpretation_refs=_unique(
                [
                    *previous.rejected_interpretation_refs,
                    *(
                        item.interpretation_id
                        for item in current
                        if item.status == "REJECTED"
                    ),
                ]
            ),
            accepted_evidence_refs=_unique(
                [*previous.accepted_evidence_refs, *accepted]
            ),
            covered_by_sufficiency=requirement_id in satisfied,
        )
    return result


def _requirement_state_transition_valid(
    previous: RequirementState, current: RequirementState
) -> bool:
    return bool(
        previous.query_ir_digest == current.query_ir_digest
        and previous.acquisition_plan_digest == current.acquisition_plan_digest
        and previous.acquisition_capability_digest
        == current.acquisition_capability_digest
        and [item.requirement_id for item in previous.requirements]
        == [item.requirement_id for item in current.requirements]
        and current.state_epoch in {previous.state_epoch, previous.state_epoch + 1}
        and (
            current.state_epoch > previous.state_epoch
            or current.candidate_snapshot_digest
            == previous.candidate_snapshot_digest
        )
    )


def _unchanged(
    state: AcquisitionState,
    outcome: AcquisitionTransitionOutcome,
    reason_code: str,
) -> AcquisitionStateTransition:
    return AcquisitionStateTransition(
        outcome=outcome,
        reason_code=reason_code,
        state=state,
    )


def _observed_terms(text: str) -> list[str]:
    return _unique(match.group(0).casefold() for match in _WORD.finditer(text))[:32]


def _aware_datetime(value: object) -> datetime | None:
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _unique_models(
    values: Sequence[_ModelT], identity_field: str, excluded: set[str]
) -> list[_ModelT]:
    result: list[_ModelT] = []
    seen = set(excluded)
    for value in values:
        identity = str(getattr(value, identity_field))
        if identity not in seen:
            seen.add(identity)
            result.append(value)
    return result


def _merge_by_identity(
    existing: Sequence[_ModelT], incoming: Sequence[_ModelT], identity_field: str
) -> list[_ModelT]:
    excluded = {str(getattr(value, identity_field)) for value in existing}
    return [*existing, *_unique_models(incoming, identity_field, excluded)]


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AcquisitionStateTransition",
    "AcquisitionTransitionOutcome",
    "acquisition_state_trace_summary",
    "advance_acquisition_state",
    "build_acquisition_action",
    "build_acquisition_region",
    "build_acquisition_window",
    "build_evidence_reference_note",
    "initialize_acquisition_state",
    "reserve_residual_controller_call",
]
