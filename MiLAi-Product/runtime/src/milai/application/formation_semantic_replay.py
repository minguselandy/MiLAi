"""Ground selected Formation artifacts into the existing semantic read path.

The replay is request-local, rebuildable, and noncanonical.  Formation may
propose a meaning only after every referenced byte range has been rechecked
against live, governed Evidence returned by the repository Gate.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from milai.application.evidence_semantics import evidence_source_eligible
from milai.application.evidence_source import (
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.formation_projection import FormationProjectionSelection
from milai.application.lexical_cues import compile_lexical_cue_sets
from milai.application.query_ir_compat import execution_operator_from_ir
from milai.domain.acquisition import AcquisitionPlan
from milai.domain.formation_artifact import (
    FormationEntityCandidateV01,
    FormationSourceSpanV01,
)
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateTransitionV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    MemoryQueryIRV02,
    MemoryQueryStep,
    RequirementCardinalityV02,
    RequirementSemanticRolesV02,
)

FORMATION_SEMANTIC_REPLAY_ID = "formation-semantic-replay-v0.2"

_FORMATION_REPLAY_MAX_BINDINGS = 24

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_EVENT_IDENTITY_QUERY = re.compile(
    r"\b(?:did|do|have|has)\s+(?P<left>.+?)\s+and\s+(?P<right>.+?)\s+"
    r"(?:attend|attended|join|joined|participate|participated)\b.*?"
    r"\b(?:the\s+)?(?:same|different|distinct)\s+(?P<object>[^?]+)",
    re.IGNORECASE,
)
_ANCHOR_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "did",
        "do",
        "have",
        "has",
        "my",
        "our",
        "same",
        "different",
        "distinct",
        "the",
        "their",
        "your",
    }
)


class FormationSemanticReplayError(ValueError):
    """A selected artifact cannot be proven against the live Evidence snapshot."""


@dataclass(frozen=True, slots=True)
class GroundedFormationSemantics:
    spans: tuple[EvidenceSpan, ...]
    interpretations: tuple[EvidenceInterpretationCandidate, ...]
    artifact_count: int


@dataclass(frozen=True, slots=True)
class FormationReplayPlan:
    query_plan: QueryPlan
    acquisition_plan: AcquisitionPlan
    specialization: str


def ground_formation_semantics(
    selection: FormationProjectionSelection,
    hydrated: Sequence[Mapping[str, Any]],
) -> GroundedFormationSemantics:
    """Recheck every selected artifact and materialize typed query-local meanings."""

    projection = selection.semantic_projection
    if projection is None:
        raise FormationSemanticReplayError("FORMATION_SEMANTIC_PROJECTION_MISSING")
    sources: dict[str, Mapping[str, Any]] = {}
    for item in hydrated:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        if evidence_id in sources:
            raise FormationSemanticReplayError("FORMATION_LIVE_EVIDENCE_DUPLICATED")
        if evidence_source_eligible(item):
            sources[evidence_id] = item
    if not set(selection.evidence_ids).issubset(sources):
        raise FormationSemanticReplayError("FORMATION_LIVE_EVIDENCE_INCOMPLETE")

    transition_by_assertion: dict[str, list[Any]] = {}
    for transition in projection.state_transitions:
        _verify_source_span(transition.span, sources)
        transition_by_assertion.setdefault(transition.resulting_assertion_digest, []).append(
            transition
        )
    if any(len(items) > 1 for items in transition_by_assertion.values()):
        raise FormationSemanticReplayError("FORMATION_STATE_TRANSITION_AMBIGUOUS")

    entities_by_evidence: dict[str, list[FormationEntityCandidateV01]] = {}
    for entity in projection.entity_candidates:
        _verify_source_span(entity.span, sources)
        entities_by_evidence.setdefault(entity.span.evidence_id, []).append(entity)

    spans: dict[str, EvidenceSpan] = {}
    interpretations: dict[str, EvidenceInterpretationCandidate] = {}
    for assertion in projection.state_assertions:
        span = _grounded_span(
            assertion.span,
            assertion.artifact_digest,
            sources,
            artifact_kind="STATE_ASSERTION",
            projection_digest=selection.projection_digest,
        )
        spans.setdefault(span.span_id, span)
        state_transition = next(
            iter(transition_by_assertion.get(assertion.artifact_digest, [])),
            None,
        )
        for interpretation in _state_interpretations(assertion, state_transition, span):
            interpretations.setdefault(interpretation.interpretation_id, interpretation)

    for event in projection.event_candidates:
        for anchor in event.temporal_anchor_spans:
            _verify_source_span(anchor, sources)
        span = _grounded_span(
            event.span,
            event.artifact_digest,
            sources,
            artifact_kind="EVENT_CANDIDATE",
            projection_digest=selection.projection_digest,
        )
        spans.setdefault(span.span_id, span)
        overlapping_entity_terms = [
            term
            for entity in entities_by_evidence.get(event.span.evidence_id, [])
            if _source_spans_overlap(event.span, entity.span)
            for term in (entity.span.text, entity.identity_key, entity.mention_type)
        ]
        actor_context = _event_actor_context(event.span, event.event_type, sources)
        value = {
            "text": event.span.text,
            "event_status": "NEGATED" if event.negated else "OCCURRED",
            "event_identity": event.event_identity_key,
            "event_type": event.event_type,
            "primary_subject": event.primary_subject,
            "context_participants": list(event.context_participants),
        }
        interpretation = _interpretation(
            artifact_digest=event.artifact_digest,
            span=span,
            kind="EVENT",
            value=value,
            entities=_terms(
                event.event_type,
                event.event_identity_key,
                event.primary_subject,
                *event.context_participants,
                actor_context,
                *overlapping_entity_terms,
            ),
            predicate="formation_event",
            event_time=(
                event.occurrence_time.model_copy(deep=True)
                if event.occurrence_time is not None
                else None
            ),
            time_basis=event.time_basis,
        )
        interpretations.setdefault(interpretation.interpretation_id, interpretation)

    artifact_count = (
        len(projection.state_assertions)
        + len(projection.state_transitions)
        + len(projection.event_candidates)
        + len(projection.entity_candidates)
    )
    return GroundedFormationSemantics(
        spans=tuple(
            sorted(
                spans.values(),
                key=lambda item: (
                    item.source_timestamp or datetime.min.replace(tzinfo=UTC),
                    item.source_turn_ref,
                    item.start,
                    item.span_id,
                ),
            )
        ),
        interpretations=tuple(
            sorted(
                interpretations.values(),
                key=lambda item: (item.span_id, item.kind, item.interpretation_id),
            )
        ),
        artifact_count=artifact_count,
    )


def _source_spans_overlap(
    left: FormationSourceSpanV01,
    right: FormationSourceSpanV01,
) -> bool:
    """Associate entities with events only when their exact source bytes overlap."""

    return (
        left.evidence_id == right.evidence_id
        and left.source_ref == right.source_ref
        and max(left.start, right.start) < min(left.end, right.end)
    )


def _event_actor_context(
    span: FormationSourceSpanV01,
    event_type: str,
    sources: Mapping[str, Mapping[str, Any]],
) -> str:
    """Return only the exact same-clause subject phrase for an event.

    Formation event spans sometimes begin at a participant name and omit an
    immediately preceding relation (for example, ``my colleague``).  Conversely,
    a relative-time event may mention its anchor before a comma.  Keeping only
    the subject phrase after the last comma prevents that anchor from becoming
    an entity of the target event.
    """

    source = _verify_source_span(span, sources)
    content = source.get("content")
    assert isinstance(content, str)
    action_offset = _event_action_offset(span.text, event_type)
    if action_offset is None:
        return ""
    clause_start = max(
        content.rfind(boundary, 0, span.start) for boundary in (".", "!", "?", ";", "\n")
    ) + 1
    actor = content[clause_start : span.start + action_offset]
    if "," in actor:
        actor = actor.rsplit(",", 1)[1]
    return actor.strip()


def _event_action_offset(text: str, event_type: str) -> int | None:
    base_tokens = [match.group(0).casefold() for match in _WORD.finditer(event_type)]
    if not base_tokens:
        return None
    base = base_tokens[-1]
    forms = {
        base,
        f"{base}s",
        f"{base}ed",
        f"{base}ing",
        *(  # ``visit`` -> ``visited`` and ``invite`` -> ``invited``.
            (f"{base}d", f"{base[:-1]}ing") if base.endswith("e") else ()
        ),
        *(  # ``study`` -> ``studied``.
            (f"{base[:-1]}ied",) if base.endswith("y") and len(base) > 1 else ()
        ),
    }
    irregular = {
        "buy": "bought",
        "come": "came",
        "eat": "ate",
        "fly": "flew",
        "go": "went",
        "have": "had",
        "leave": "left",
        "make": "made",
        "meet": "met",
        "run": "ran",
        "see": "saw",
        "take": "took",
    }
    if base in irregular:
        forms.add(irregular[base])
    return next(
        (
            match.start()
            for match in _WORD.finditer(text)
            if match.group(0).casefold() in forms
        ),
        None,
    )


def specialize_formation_replay_plan(
    query_plan: QueryPlan,
    acquisition_plan: AcquisitionPlan,
    selection: FormationProjectionSelection,
    *,
    query: str,
) -> FormationReplayPlan:
    """Build a CANARY-only typed plan; the frozen OFF plan is never mutated."""

    query_ir = query_plan.memory_query_ir
    if query_ir is None or query_ir.mode == "AMBIGUOUS":
        raise FormationSemanticReplayError("FORMATION_QUERY_IR_NOT_EXECUTABLE")
    facets = set(selection.required_facets)
    if {"PREFERENCE", "SHORT_LIVED_STATE"}.issubset(facets):
        specialized = _preference_short_lived_ir(query_ir)
        specialization = "PREFERENCE_SHORT_LIVED_COMPOSE"
    elif "EVENT_IDENTITY" in facets:
        specialized = _event_identity_ir(query_ir, query)
        specialization = "EVENT_IDENTITY_COMPARE"
    elif "CURRENT_STATE" in facets:
        specialized = _current_state_ir(query_ir)
        specialization = "CURRENT_STATE_REPLAY"
    elif "EVENT_TIME" in facets:
        specialized = _event_time_ir(query_ir)
        specialization = "EVENT_TIME_REPLAY"
    else:
        specialized = query_ir
        specialization = "UNCHANGED"

    operator, arguments = execution_operator_from_ir(specialized)
    if specialization != "UNCHANGED" and operator is None:
        raise FormationSemanticReplayError("FORMATION_OPERATOR_NOT_EXECUTABLE")
    replay_plan = query_plan.model_copy(
        update={
            "planner_version": f"{query_plan.planner_version}+{FORMATION_SEMANTIC_REPLAY_ID}",
            "memory_query_ir": specialized,
            "operator": operator,
            "operator_arguments": arguments,
        }
    )
    replay_acquisition = acquisition_plan.model_copy(
        update={"query_ir_digest": canonical_sha256(specialized.model_dump(mode="json"))}
    )
    return FormationReplayPlan(
        query_plan=replay_plan,
        acquisition_plan=replay_acquisition,
        specialization=specialization,
    )


def _current_state_ir(query_ir: MemoryQueryIRV02) -> MemoryQueryIRV02:
    source = next(
        (
            item
            for item in query_ir.requirements
            if item.slot_id == "CURRENT_STATE" and item.interpretation_kind == "STATE_OBSERVATION"
        ),
        None,
    )
    if source is None:
        raise FormationSemanticReplayError("FORMATION_CURRENT_STATE_SLOT_MISSING")
    requirement = source.model_copy(
        update={
            "entity_constraints": [],
            "predicate_constraints": ["formation_state_current"],
            "cardinality": RequirementCardinalityV02(
                minimum=1,
                maximum=_FORMATION_REPLAY_MAX_BINDINGS,
                distinct=False,
            ),
        }
    )
    return _rebuild_ir(
        query_ir,
        requirements=[requirement],
        operator_family="LOOKUP",
        completeness="ALL_REQUIRED_BINDINGS",
        reason="CURRENT_STATE",
    )


def _event_time_ir(query_ir: MemoryQueryIRV02) -> MemoryQueryIRV02:
    requirements = [
        item.model_copy(
            update={
                "predicate_constraints": ["formation_event"],
                "cardinality": RequirementCardinalityV02(
                    minimum=1,
                    maximum=_FORMATION_REPLAY_MAX_BINDINGS,
                    distinct=False,
                ),
            }
        )
        if item.interpretation_kind == "EVENT"
        else item
        for item in query_ir.requirements
    ]
    if len([item for item in requirements if item.interpretation_kind == "EVENT"]) < 2:
        raise FormationSemanticReplayError("FORMATION_EVENT_TIME_SLOTS_MISSING")
    return _rebuild_ir(
        query_ir,
        requirements=requirements,
        operator_family="TEMPORAL_ORDER",
        completeness="ALL_REQUIRED_BINDINGS",
        reason="EVENT_TIME",
    )


def _event_identity_ir(query_ir: MemoryQueryIRV02, query: str) -> MemoryQueryIRV02:
    anchors = _event_identity_anchors(query)
    if anchors is None:
        raise FormationSemanticReplayError("FORMATION_EVENT_IDENTITY_ANCHORS_AMBIGUOUS")
    left, right = anchors
    requirements = [
        EvidenceRequirementV02(
            slot_id="EVENT_IDENTITY_LEFT",
            interpretation_kind="EVENT",
            entity_constraints=left,
            predicate_constraints=["formation_event"],
            value_type="ENTITY",
            cardinality=RequirementCardinalityV02(
                minimum=1,
                maximum=_FORMATION_REPLAY_MAX_BINDINGS,
                distinct=False,
            ),
            join_key="event_identity_comparison",
        ),
        EvidenceRequirementV02(
            slot_id="EVENT_IDENTITY_RIGHT",
            interpretation_kind="EVENT",
            entity_constraints=right,
            predicate_constraints=["formation_event"],
            value_type="ENTITY",
            cardinality=RequirementCardinalityV02(
                minimum=1,
                maximum=_FORMATION_REPLAY_MAX_BINDINGS,
                distinct=False,
            ),
            join_key="event_identity_comparison",
        ),
    ]
    return _rebuild_ir(
        query_ir,
        requirements=requirements,
        operator_family="EVENT_IDENTITY_COMPARE",
        completeness="ALL_REQUIRED_BINDINGS",
        reason="EVENT_IDENTITY",
        mode="COMPOSE",
    )


def _preference_short_lived_ir(query_ir: MemoryQueryIRV02) -> MemoryQueryIRV02:
    source = next(
        (
            item
            for item in query_ir.requirements
            if item.slot_id == "PREFERENCE_SIGNAL_SET"
            and item.interpretation_kind == "PREFERENCE_SIGNAL"
        ),
        None,
    )
    if source is None:
        raise FormationSemanticReplayError("FORMATION_PREFERENCE_SLOT_MISSING")
    preference = source.model_copy(
        update={
            "entity_constraints": [],
            "predicate_constraints": ["formation_preference_signal"],
            "semantic_roles": RequirementSemanticRolesV02(experiencer="USER"),
            "cardinality": RequirementCardinalityV02(
                minimum=1,
                maximum=_FORMATION_REPLAY_MAX_BINDINGS,
                distinct=False,
            ),
        }
    )
    short_lived = EvidenceRequirementV02(
        slot_id="SHORT_LIVED_STATE",
        interpretation_kind="STATE_OBSERVATION",
        predicate_constraints=["formation_state_short_lived"],
        semantic_roles=RequirementSemanticRolesV02(experiencer="USER"),
        value_type="ANY",
        cardinality=RequirementCardinalityV02(
            minimum=1,
            maximum=_FORMATION_REPLAY_MAX_BINDINGS,
            distinct=False,
        ),
        join_key=preference.join_key or "preference_subject",
    )
    return _rebuild_ir(
        query_ir,
        requirements=[preference, short_lived],
        operator_family="COMPOSE_STATE",
        completeness="ALL_REQUIRED_BINDINGS",
        reason="PREFERENCE_SHORT_LIVED",
        mode="COMPOSE",
        answer_shape="STATE",
    )


def _rebuild_ir(
    query_ir: MemoryQueryIRV02,
    *,
    requirements: list[EvidenceRequirementV02],
    operator_family: str,
    completeness: str,
    reason: str,
    mode: str | None = None,
    answer_shape: str | None = None,
) -> MemoryQueryIRV02:
    steps = [
        MemoryQueryStep(
            kind="RETRIEVE",
            outputs=["candidate_spans"],
            constraints={
                "operator_family": operator_family,
                "retrieval_unit": "GOVERNED_FORMATION_SPAN",
            },
            budget={"candidate_cap_required": True},
        ),
        *[
            MemoryQueryStep(
                kind="BIND_SLOT",
                inputs=["candidate_spans"],
                outputs=[item.slot_id],
                constraints={
                    "interpretation_kind": item.interpretation_kind,
                    "binding_owner": "DETERMINISTIC_RUNTIME",
                },
            )
            for item in requirements
            if item.required
        ],
    ]
    required_slots = [item.slot_id for item in requirements if item.required]
    if len(required_slots) > 1:
        steps.append(
            MemoryQueryStep(
                kind="JOIN",
                inputs=required_slots,
                outputs=["joined_bindings"],
                constraints={"join_validation": "TYPE_ENTITY_TIME_PROVENANCE"},
            )
        )
    if operator_family in {"EVENT_IDENTITY_COMPARE", "TEMPORAL_ORDER"}:
        steps.append(
            MemoryQueryStep(
                kind="COMPARE",
                inputs=["joined_bindings"],
                outputs=["answer"],
                constraints={"operation": operator_family.casefold()},
            )
        )
    elif operator_family == "COMPOSE_STATE":
        steps.append(
            MemoryQueryStep(
                kind="REDUCE",
                inputs=["joined_bindings"],
                outputs=["answer"],
                constraints={"operation": "compose_state"},
            )
        )
    payload = query_ir.model_dump(mode="python")
    payload.update(
        {
            "mode": mode or query_ir.mode,
            "answer_shape": answer_shape or query_ir.answer_shape,
            "requirements": requirements,
            "lexical_cues": compile_lexical_cue_sets(requirements),
            "steps": steps,
            "completeness": completeness,
            "planner_trace": query_ir.planner_trace.model_copy(
                update={
                    "compiler_version": (
                        f"{query_ir.planner_trace.compiler_version}+{FORMATION_SEMANTIC_REPLAY_ID}"
                    ),
                    "reason_code": (f"{query_ir.planner_trace.reason_code}+FORMATION_{reason}"),
                }
            ),
        }
    )
    return MemoryQueryIRV02.model_validate(payload)


def _event_identity_anchors(query: str) -> tuple[list[str], list[str]] | None:
    matched = _EVENT_IDENTITY_QUERY.search(query)
    if matched is None:
        return None
    object_terms = _anchor_terms(matched.group("object"))
    object_anchor = object_terms[:1]
    left = _unique([*_anchor_terms(matched.group("left"))[:1], *object_anchor])
    right = _unique([*_anchor_terms(matched.group("right"))[:1], *object_anchor])
    return (left, right) if left and right else None


def _anchor_terms(value: str) -> list[str]:
    return [
        term
        for term in (match.group(0).casefold() for match in _WORD.finditer(value))
        if term not in _ANCHOR_STOPWORDS
    ][:16]


def _state_interpretations(
    assertion: FormationStateAssertionV01,
    transition: FormationStateTransitionV01 | None,
    span: EvidenceSpan,
) -> list[EvidenceInterpretationCandidate]:
    structured = {
        "state_predicate": assertion.predicate,
        "state_value": assertion.value,
        "state_modality": assertion.modality,
        "subject_identity": assertion.subject_identity,
        "transition_relation": transition.relation if transition is not None else None,
        "previous_value": transition.previous_value if transition is not None else None,
        "valid_time": (
            assertion.valid_time.model_dump(mode="json")
            if assertion.valid_time is not None
            else None
        ),
    }
    entities = _terms(
        assertion.subject_identity,
        assertion.predicate,
        assertion.span.text,
        assertion.value,
    )
    values: list[EvidenceInterpretationCandidate] = []
    if assertion.modality in {"ASSERTED", "TEMPORARY"}:
        values.append(
            _interpretation(
                artifact_digest=assertion.artifact_digest,
                span=span,
                kind="STATE_OBSERVATION",
                value=structured,
                entities=entities,
                predicate="formation_state_current",
                event_time=assertion.valid_time,
                time_basis=(
                    "EXPLICIT_EVENT_TIME"
                    if assertion.valid_time is not None and assertion.valid_time.start is not None
                    else "UNRESOLVED"
                ),
            )
        )
    if assertion.modality in {"INTENT", "TEMPORARY"}:
        values.append(
            _interpretation(
                artifact_digest=assertion.artifact_digest,
                span=span,
                kind="STATE_OBSERVATION",
                value=structured,
                entities=entities,
                predicate="formation_state_short_lived",
                event_time=assertion.valid_time,
                time_basis=(
                    "EXPLICIT_EVENT_TIME"
                    if assertion.valid_time is not None and assertion.valid_time.start is not None
                    else "UNRESOLVED"
                ),
            )
        )
    if assertion.modality == "PREFERENCE":
        preference = assertion.value if isinstance(assertion.value, Mapping) else {}
        values.append(
            _interpretation(
                artifact_digest=assertion.artifact_digest,
                span=span,
                kind="PREFERENCE_SIGNAL",
                value={
                    "text": assertion.span.text,
                    "stance": "POSITIVE",
                    "preferred": preference.get("preferred"),
                    "over": preference.get("over"),
                },
                entities=entities,
                predicate="formation_preference_signal",
                time_basis="UNRESOLVED",
            )
        )
    if assertion.modality == "INTENT":
        intent = assertion.value if isinstance(assertion.value, Mapping) else {}
        values.append(
            _interpretation(
                artifact_digest=assertion.artifact_digest,
                span=span,
                kind="DECISION",
                value={
                    "text": assertion.span.text,
                    "decision_status": "CURRENT_INTENT",
                    "action": intent.get("action"),
                },
                entities=entities,
                predicate="current_intent",
                time_basis="UNRESOLVED",
            )
        )
    return values


def _grounded_span(
    source_span: FormationSourceSpanV01,
    artifact_digest: str,
    sources: Mapping[str, Mapping[str, Any]],
    *,
    artifact_kind: str,
    projection_digest: str | None,
) -> EvidenceSpan:
    source = _verify_source_span(source_span, sources)
    source_identity = structured_evidence_identity(source, source_span.source_ref)
    if source_identity is None:
        raise ValueError("FORMATION_SOURCE_IDENTITY_MISSING")
    speaker, speaker_source = structured_evidence_speaker(source)
    span_identity = canonical_sha256([artifact_digest, source_span.model_dump(mode="json")])
    return EvidenceSpan(
        span_id=f"formation:{span_identity}",
        source_evidence_id=source_span.evidence_id,
        source_turn_ref=source_span.source_ref,
        subject_id=source_identity.subject_id,
        session_id=source_identity.session_id,
        turn_id=source_identity.turn_id,
        identity_source=source_identity.identity_source,
        speaker=speaker,
        start=source_span.start,
        end=source_span.end,
        text=source_span.text,
        source_timestamp=_timestamp(source.get("observed_at")),
        provenance={
            "authority_class": "EVIDENCE_ONLY",
            "speaker_source": speaker_source,
            "source_content_hash": source.get("content_hash"),
            "source_span_verified": True,
            "formation_artifact_kind": artifact_kind,
            "formation_artifact_digest": artifact_digest,
            "formation_projection_digest": projection_digest,
            "projection_persisted": False,
            "rebuildable": True,
            "canonical": False,
            "canonical_mutation": False,
        },
    )


def _verify_source_span(
    span: FormationSourceSpanV01,
    sources: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    source = sources.get(span.evidence_id)
    if source is None:
        raise FormationSemanticReplayError("FORMATION_ARTIFACT_SOURCE_NOT_LIVE")
    content = source.get("content")
    if not isinstance(content, str):
        raise FormationSemanticReplayError("FORMATION_LIVE_CONTENT_MISSING")
    if source.get("source_ref") != span.source_ref:
        raise FormationSemanticReplayError("FORMATION_LIVE_SOURCE_REF_MISMATCH")
    if span.end > len(content) or content[span.start : span.end] != span.text:
        raise FormationSemanticReplayError("FORMATION_LIVE_SPAN_MISMATCH")
    return source


def _interpretation(
    *,
    artifact_digest: str,
    span: EvidenceSpan,
    kind: str,
    value: Any,
    entities: list[str],
    predicate: str,
    time_basis: str,
    event_time: Any = None,
) -> EvidenceInterpretationCandidate:
    material = [
        artifact_digest,
        span.span_id,
        kind,
        predicate,
        value,
        event_time.model_dump(mode="json") if event_time is not None else None,
        time_basis,
    ]
    return EvidenceInterpretationCandidate.model_validate(
        {
            "interpretation_id": f"formation:{canonical_sha256(material)}",
            "span_id": span.span_id,
            "kind": kind,
            "value": value,
            "unit": None,
            "entities": entities,
            "predicate": predicate,
            "event_time": event_time,
            "time_basis": time_basis,
            "extractor_identity": FORMATION_SEMANTIC_REPLAY_ID,
            "confidence": None,
        }
    )


def _terms(*values: object) -> list[str]:
    text = " ".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, (dict, list, tuple))
        else str(value or "")
        for value in values
    )
    return _unique(match.group(0).casefold() for match in _WORD.finditer(text))[:32]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


__all__ = [
    "FORMATION_SEMANTIC_REPLAY_ID",
    "FormationReplayPlan",
    "FormationSemanticReplayError",
    "GroundedFormationSemantics",
    "ground_formation_semantics",
    "specialize_formation_replay_plan",
]
