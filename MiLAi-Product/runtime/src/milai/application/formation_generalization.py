"""Scope-aware deterministic Formation for Phase-1 textual lifecycle facts.

The treatment extends the existing raw-preserving sidecars with four general
mechanisms found missing on repair data: scoped entity identity, normalized
event identity, explicit/cross-evidence/interval time, and typed state-change
phrases.  It remains query-independent and never persists or promotes data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from milai.application.evidence_semantics import resolve_direct_event_time
from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationEntityCandidateV01,
    FormationEventCandidateV01,
    FormationSourceSpanV01,
)
from milai.domain.formation_state import (
    FormationStateAssertionV01,
    FormationStateChangeSidecarV01,
    FormationStateTransitionV01,
)
from milai.domain.requirement_state import canonical_sha256
from milai.domain.semantic_query import InterpretationEventTime

PRODUCER_IDENTITY = "deterministic-formation-generalization-v0.2"

_FIRST_PERSON = re.compile(r"\b(?:I|me|my|myself)\b", re.IGNORECASE)
_INTRODUCED_NAME = re.compile(
    r"\b(?:colleague|dentist|doctor|friend|manager|neighbor|neighbour|sister|"
    r"brother|cousin|aunt|uncle)\s+"
    r"(?P<name>[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?\s+"
    r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?)"
)
_DATE = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}"
)
_ATTEND_SELF = re.compile(
    rf"(?P<whole>(?:(?:[A-Z][\w'-]+\s+){{1,2}}and\s+)?I\s+attended\s+"
    rf"(?:that\s+same\s+|the\s+)?[^.;]+?\s+on\s+{_DATE})",
    re.IGNORECASE,
)
_ATTEND_RELATION = re.compile(
    rf"(?P<whole>my\s+(?:colleague|dentist|doctor|friend|manager|neighbor|"
    rf"neighbour)\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?\s+attended\s+"
    rf"(?:a\s+different\s+|that\s+same\s+|the\s+)?[^.;]+?\s+on\s+{_DATE})",
    re.IGNORECASE,
)
_CROSS_VISIT = re.compile(
    r"(?P<whole>(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"days?\s+after\s+the\s+(?P<anchor>[A-Z][\w'-]+)\s+workshop,\s+"
    r"I\s+visited\s+the\s+(?P<object>[^.;]+))",
    re.IGNORECASE,
)
_WORK_INTERVAL = re.compile(
    rf"(?P<whole>worked\s+at\s+the\s+(?P<object>[^.;]+?)\s+from\s+"
    rf"(?P<start>{_DATE})\s+(?:through|to|until)\s+(?P<end>{_DATE}))",
    re.IGNORECASE,
)
_MOVE_EVENT = re.compile(
    r"(?P<whole>moved\s+from\s+(?P<old>[A-Z][\w'-]*)\s+to\s+"
    r"(?P<new>[A-Z][\w'-]*))",
    re.IGNORECASE,
)
_NEGATED_MOVE = re.compile(
    r"(?P<whole>do\s+not\s+live\s+in\s+(?P<location>[A-Z][\w'-]*))",
    re.IGNORECASE,
)
_AMBIGUOUS_ATTEND = re.compile(
    r"(?P<whole>(?:may|might|could)\s+attend\s+the\s+(?P<object>[^,.;]+)\s+"
    r"(?:sometime|at\s+some\s+point)\s+(?P<period>[^,.;]+))",
    re.IGNORECASE,
)
_RANGE_COUNTS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_LIVE = re.compile(
    r"(?P<whole>(?:currently\s+)?(?:live|lived)\s+in\s+"
    r"(?P<location>[A-Z][\w'-]*))",
    re.IGNORECASE,
)
_CALL_HOME = re.compile(
    r"(?P<whole>call\s+(?P<location>[A-Z][\w'-]*)\s+home)",
    re.IGNORECASE,
)
_OCCUPATION = re.compile(
    r"(?P<whole>occupation\s+is\s+(?P<title>[^,.;]+))",
    re.IGNORECASE,
)
_ALLERGY = re.compile(
    r"(?P<whole>allergic\s+to\s+(?P<item>[^,.;]+))",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"(?P<whole>Correction:\s*I\s+(?:do\s+not|don't|did\s+not|didn't)\s+"
    r"(?:live|move)\s+(?:in|to)\s+(?P<old>[A-Z][\w'-]*);\s*"
    r"I\s+(?:still\s+)?live\s+in\s+(?P<new>[A-Z][\w'-]*))",
    re.IGNORECASE,
)
_REVOKE_ALLERGY = re.compile(
    r"(?P<whole>That\s+(?P<item>[^,.;]+?)\s+allergy\s+was\s+"
    r"(?:incorrect|wrong|mistaken);\s*I\s+(?:revoke|withdraw)\s+it)",
    re.IGNORECASE,
)
_TEMPORARY = re.compile(
    rf"(?P<whole>Until\s+{_DATE},\s*I\s+(?:am|['\u2019]m)\s+staying\s+in\s+"
    r"(?P<location>[A-Z][\w'-]*))",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"(?P<whole>prefer\s+(?P<preferred>.+?)\s+(?:over|to)\s+"
    r"(?P<other>.+?))(?=[.!?]|$)",
    re.IGNORECASE,
)
_INTENT = re.compile(
    r"(?P<whole>I\s+(?:am|['\u2019]m)\s+(?:planning|thinking)\s+(?:to|of)\s+"
    r"(?P<action>[^.!?]+))",
    re.IGNORECASE,
)


class FormationGeneralizationError(ValueError):
    """A source cannot be admitted into the generalized Formation boundary."""


@dataclass(frozen=True, slots=True)
class GeneralizedFormationBundle:
    formation: FormationArtifactSidecarV01
    state_changes: FormationStateChangeSidecarV01
    producer_identity: str = PRODUCER_IDENTITY


@dataclass(frozen=True, slots=True)
class _EventDraft:
    span: FormationSourceSpanV01
    scope_id: str
    event_type: str
    object_key: str
    occurrence_time: InterpretationEventTime | None
    time_basis: str
    negated: bool = False
    anchor_name: str | None = None
    relative_days: int | None = None


def build_generalized_formation(
    source_records: Sequence[Mapping[str, Any]],
) -> GeneralizedFormationBundle:
    """Build one query-independent, noncanonical Formation treatment."""

    sources = _admit_sources(source_records)
    entities = _entities(sources)
    events = _events(sources)
    assertions, transitions = _states(sources)
    snapshot = canonical_sha256(
        [
            {
                "evidence_id": source["evidence_id"],
                "scope_id": source["scope_id"],
                "source_ref": source["source_ref"],
                "content_digest": canonical_sha256(source["content"]),
                "observed_at": source.get("observed_at"),
            }
            for source in sources
        ]
    )
    formation_provisional = FormationArtifactSidecarV01.model_construct(
        sidecar_digest="0" * 64,
        source_snapshot_digest=snapshot,
        entity_candidates=entities,
        event_candidates=events,
        rejected_model_outputs=[],
        producer_identities=[PRODUCER_IDENTITY],
        model_calls=0,
    )
    formation_material = formation_provisional.model_dump(mode="json", exclude={"sidecar_digest"})
    formation = FormationArtifactSidecarV01(
        sidecar_digest=canonical_sha256(formation_material),
        **formation_material,
    )
    state_provisional = FormationStateChangeSidecarV01.model_construct(
        sidecar_digest="0" * 64,
        source_snapshot_digest=snapshot,
        assertions=assertions,
        transitions=transitions,
        producer_identities=[PRODUCER_IDENTITY],
    )
    state_material = state_provisional.model_dump(mode="json", exclude={"sidecar_digest"})
    state_changes = FormationStateChangeSidecarV01(
        sidecar_digest=canonical_sha256(state_material),
        **state_material,
    )
    return GeneralizedFormationBundle(
        formation=formation,
        state_changes=state_changes,
    )


def _admit_sources(
    source_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in source_records:
        required = ("evidence_id", "source_ref", "scope_id", "content")
        if not all(isinstance(source.get(name), str) and source[name] for name in required):
            raise FormationGeneralizationError("FORMATION_SOURCE_IDENTITY_INVALID")
        evidence_id = str(source["evidence_id"])
        if evidence_id in seen:
            raise FormationGeneralizationError("FORMATION_SOURCE_DUPLICATED")
        seen.add(evidence_id)
        if source.get("speaker") != "user":
            continue
        if (
            source.get("revoked_at") is not None
            or source.get("retention_state") != "READABLE"
            or source.get("access_decision") != "ALLOWED"
            or source.get("permission_snapshot", {}).get("readable") is not True
        ):
            continue
        output.append(dict(source))
    return sorted(output, key=lambda row: (str(row["source_ref"]), str(row["evidence_id"])))


def _entities(sources: Sequence[Mapping[str, Any]]) -> list[FormationEntityCandidateV01]:
    full_names: dict[str, set[str]] = {}
    full_ranges: dict[str, list[tuple[int, int]]] = {}
    for source in sources:
        evidence_id = str(source["evidence_id"])
        introduced_names = [
            match.group("name") for match in _INTRODUCED_NAME.finditer(str(source["content"]))
        ]
        full_names.setdefault(str(source["scope_id"]), set()).update(introduced_names)
        full_ranges[evidence_id] = [
            match.span("name") for match in _INTRODUCED_NAME.finditer(str(source["content"]))
        ]
    surname_index: dict[str, dict[str, str | None]] = {}
    for scope_id, scope_names in full_names.items():
        index: dict[str, str | None] = {}
        for name in scope_names:
            surname = name.rsplit(" ", 1)[-1].casefold()
            existing = index.get(surname)
            index[surname] = name if existing in {None, name} else None
        surname_index[scope_id] = index

    candidates: list[FormationEntityCandidateV01] = []
    occupied: set[tuple[str, int, int]] = set()
    for source in sources:
        evidence_id = str(source["evidence_id"])
        source_ref = str(source["source_ref"])
        scope_id = str(source["scope_id"])
        content = str(source["content"])
        for match in _FIRST_PERSON.finditer(content):
            candidates.append(
                _entity_candidate(
                    _span(evidence_id, source_ref, content, match.start(), match.end()),
                    f"{scope_id}:self",
                    "FIRST_PERSON",
                )
            )
            occupied.add((evidence_id, match.start(), match.end()))
        for match in _INTRODUCED_NAME.finditer(content):
            start, end = match.span("name")
            name = match.group("name")
            candidates.append(
                _entity_candidate(
                    _span(evidence_id, source_ref, content, start, end),
                    f"{scope_id}:person:{name.casefold()}",
                    "NAMED_PERSON",
                )
            )
            occupied.add((evidence_id, start, end))
        for surname, full_name in surname_index.get(scope_id, {}).items():
            if full_name is None:
                continue
            for match in re.finditer(rf"\b{re.escape(surname)}\b", content, re.IGNORECASE):
                if any(
                    start <= match.start() and match.end() <= end
                    for start, end in full_ranges[evidence_id]
                ):
                    continue
                key = (evidence_id, match.start(), match.end())
                if key in occupied:
                    continue
                candidates.append(
                    _entity_candidate(
                        _span(
                            evidence_id,
                            source_ref,
                            content,
                            match.start(),
                            match.end(),
                        ),
                        f"{scope_id}:person:{full_name.casefold()}",
                        "UNAMBIGUOUS_SURNAME_ALIAS",
                    )
                )
                occupied.add(key)
    return sorted(
        candidates,
        key=lambda item: (item.span.source_ref, item.span.start, item.identity_key),
    )


def _events(sources: Sequence[Mapping[str, Any]]) -> list[FormationEventCandidateV01]:
    drafts: list[_EventDraft] = []
    for source in sources:
        content = str(source["content"])
        evidence_id = str(source["evidence_id"])
        source_ref = str(source["source_ref"])
        scope_id = str(source["scope_id"])
        observed_at = _timestamp(source.get("observed_at"))
        for pattern in (_ATTEND_RELATION, _ATTEND_SELF):
            for match in pattern.finditer(content):
                text = match.group("whole")
                direct = resolve_direct_event_time(text, observed_at)
                drafts.append(
                    _EventDraft(
                        span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                        scope_id=scope_id,
                        event_type="attend",
                        object_key=_event_object(text, "attend"),
                        occurrence_time=direct[0] if direct else None,
                        time_basis=direct[1] if direct else "UNRESOLVED",
                    )
                )
        for match in _MOVE_EVENT.finditer(content):
            direct = resolve_direct_event_time(content, observed_at)
            drafts.append(
                _EventDraft(
                    span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                    scope_id=scope_id,
                    event_type="move",
                    object_key=f"{match.group('old').casefold()}-{match.group('new').casefold()}",
                    occurrence_time=direct[0] if direct else None,
                    time_basis=direct[1] if direct else "UNRESOLVED",
                )
            )
        for match in _NEGATED_MOVE.finditer(content):
            drafts.append(
                _EventDraft(
                    span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                    scope_id=scope_id,
                    event_type="move",
                    object_key=f"negated-{match.group('location').casefold()}",
                    occurrence_time=None,
                    time_basis="UNRESOLVED",
                    negated=True,
                )
            )
        for match in _WORK_INTERVAL.finditer(content):
            start = resolve_direct_event_time(match.group("start"), observed_at)
            end = resolve_direct_event_time(match.group("end"), observed_at)
            if start is None or end is None:
                continue
            drafts.append(
                _EventDraft(
                    span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                    scope_id=scope_id,
                    event_type="work",
                    object_key=_tokens(match.group("object")),
                    occurrence_time=InterpretationEventTime(
                        start=start[0].start,
                        end=end[0].end,
                        normalized_from=match.group("whole"),
                    ),
                    time_basis="EXPLICIT_EVENT_TIME",
                )
            )
        for match in _AMBIGUOUS_ATTEND.finditer(content):
            drafts.append(
                _EventDraft(
                    span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                    scope_id=scope_id,
                    event_type="attend",
                    object_key=_tokens(match.group("object")),
                    occurrence_time=None,
                    time_basis="UNRESOLVED",
                )
            )
        for match in _CROSS_VISIT.finditer(content):
            count_text = match.group("count").casefold()
            count = int(count_text) if count_text.isdecimal() else _RANGE_COUNTS[count_text]
            drafts.append(
                _EventDraft(
                    span=_matched_span(evidence_id, source_ref, content, match, "whole"),
                    scope_id=scope_id,
                    event_type="visit",
                    object_key=_tokens(match.group("object")),
                    occurrence_time=None,
                    time_basis="UNRESOLVED",
                    anchor_name=match.group("anchor").casefold(),
                    relative_days=count,
                )
            )

    resolved: list[_EventDraft] = []
    explicit_anchors = [
        item
        for item in drafts
        if item.event_type == "attend"
        and item.occurrence_time is not None
        and item.occurrence_time.start is not None
    ]
    for draft in drafts:
        if draft.anchor_name is None:
            resolved.append(draft)
            continue
        anchors = [
            item
            for item in explicit_anchors
            if item.scope_id == draft.scope_id and draft.anchor_name in item.object_key
        ]
        intervals = {
            (item.occurrence_time.start, item.occurrence_time.end)
            for item in anchors
            if item.occurrence_time is not None
        }
        if len(intervals) != 1 or draft.relative_days is None:
            resolved.append(draft)
            continue
        anchor = min(anchors, key=lambda item: (item.span.source_ref, item.span.start))
        assert anchor.occurrence_time is not None
        assert anchor.occurrence_time.start is not None
        interval_start = anchor.occurrence_time.start + timedelta(days=draft.relative_days)
        end_base = anchor.occurrence_time.end or anchor.occurrence_time.start
        interval_end = end_base + timedelta(days=draft.relative_days)
        resolved.append(
            _EventDraft(
                span=draft.span,
                scope_id=draft.scope_id,
                event_type=draft.event_type,
                object_key=draft.object_key,
                occurrence_time=InterpretationEventTime(
                    start=interval_start,
                    end=interval_end,
                    normalized_from=draft.span.text,
                    anchor_provenance={
                        "anchor_kind": "CROSS_EVIDENCE_EXPLICIT_EVENT",
                        "anchor_evidence_id": anchor.span.evidence_id,
                        "anchor_text_digest": canonical_sha256(anchor.span.text),
                        "relative_days": draft.relative_days,
                        "source_time_substitution": False,
                    },
                ),
                time_basis="INFERRED_EVENT_TIME",
            )
        )

    candidates: list[FormationEventCandidateV01] = []
    for draft in resolved:
        anchor_spans = []
        if draft.occurrence_time and draft.occurrence_time.anchor_provenance:
            anchor_id = draft.occurrence_time.anchor_provenance.get("anchor_evidence_id")
            anchor_spans = [
                item.span for item in explicit_anchors if item.span.evidence_id == anchor_id
            ][:1]
        identity = _event_identity(
            draft.scope_id,
            draft.event_type,
            draft.object_key,
            draft.occurrence_time,
            draft.span,
        )
        provisional = FormationEventCandidateV01.model_construct(
            artifact_digest="0" * 64,
            span=draft.span,
            event_type=draft.event_type,
            primary_subject=f"{draft.scope_id}:self",
            context_participants=[],
            event_identity_key=identity,
            occurrence_time=draft.occurrence_time,
            time_basis=draft.time_basis,
            temporal_anchor_spans=sorted(
                anchor_spans, key=lambda item: (item.source_ref, item.start, item.end)
            ),
            negated=draft.negated,
            confidence_feature=1.0,
            producer_identity=PRODUCER_IDENTITY,
            provenance={"source_time_substitution": False},
        )
        material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
        candidates.append(
            FormationEventCandidateV01(
                artifact_digest=canonical_sha256(material),
                **material,
            )
        )
    unique = {item.artifact_digest: item for item in candidates}
    return sorted(
        unique.values(),
        key=lambda item: (
            item.span.source_ref,
            item.span.start,
            item.event_identity_key,
        ),
    )


def _states(
    sources: Sequence[Mapping[str, Any]],
) -> tuple[list[FormationStateAssertionV01], list[FormationStateTransitionV01]]:
    assertions: list[FormationStateAssertionV01] = []
    transitions: list[FormationStateTransitionV01] = []
    for source in sources:
        content = str(source["content"])
        evidence_id = str(source["evidence_id"])
        source_ref = str(source["source_ref"])
        subject = f"{source['scope_id']}:self"
        observed_at = _timestamp(source.get("observed_at"))
        correction = _CORRECTION.search(content)
        if correction is not None:
            state_start = content.casefold().rfind("live in", correction.start(), correction.end())
            assert state_start >= correction.start()
            state_end = correction.end("new")
            assertion = _assertion(
                _span(evidence_id, source_ref, content, state_start, state_end),
                subject,
                "residence",
                {"location": correction.group("new")},
                "ASSERTED",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _matched_span(evidence_id, source_ref, content, correction, "whole"),
                    assertion,
                    "CORRECTS",
                    {"location": correction.group("old")},
                    {"location": correction.group("new")},
                    None,
                )
            )
            continue
        revoke = _REVOKE_ALLERGY.search(content)
        if revoke is not None:
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, revoke, "whole"),
                subject,
                "allergy",
                None,
                "ASSERTED",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "REVOKES",
                    {"item": revoke.group("item")},
                    None,
                    None,
                )
            )
            continue
        temporary = _TEMPORARY.search(content)
        if temporary is not None:
            direct = resolve_direct_event_time(content, observed_at)
            valid_time = direct[0] if direct else None
            state_start = content.casefold().index("staying in", temporary.start())
            state_end = state_start + len(f"staying in {temporary.group('location')}")
            assertion = _assertion(
                _span(evidence_id, source_ref, content, state_start, state_end),
                subject,
                "temporary_location",
                {"location": temporary.group("location")},
                "TEMPORARY",
                valid_time,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _matched_span(evidence_id, source_ref, content, temporary, "whole"),
                    assertion,
                    "TEMPORARILY_CONSTRAINS",
                    None,
                    {"location": temporary.group("location")},
                    valid_time,
                )
            )
            continue
        move = _MOVE_EVENT.search(content)
        if move is not None:
            direct = resolve_direct_event_time(content, observed_at)
            valid_time = direct[0] if direct else None
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, move, "new"),
                subject,
                "residence",
                {"location": move.group("new")},
                "ASSERTED",
                valid_time,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    _matched_span(evidence_id, source_ref, content, move, "whole"),
                    assertion,
                    "UPDATES",
                    {"location": move.group("old")},
                    {"location": move.group("new")},
                    valid_time,
                )
            )
            continue

        for match in _LIVE.finditer(content):
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, match, "whole"),
                subject,
                "residence",
                {"location": match.group("location")},
                "ASSERTED",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "ESTABLISHES",
                    None,
                    {"location": match.group("location")},
                    None,
                )
            )
        for match in _CALL_HOME.finditer(content):
            assertions.append(
                _assertion(
                    _matched_span(evidence_id, source_ref, content, match, "whole"),
                    subject,
                    "residence",
                    {"location": match.group("location")},
                    "ASSERTED",
                    None,
                    "GOVERNED_REVIEW_REQUIRED",
                )
            )
        for match in _OCCUPATION.finditer(content):
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, match, "whole"),
                subject,
                "occupation",
                {"title": match.group("title").strip()},
                "ASSERTED",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "ESTABLISHES",
                    None,
                    assertion.value,
                    None,
                )
            )
        for match in _ALLERGY.finditer(content):
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, match, "whole"),
                subject,
                "allergy",
                {"item": match.group("item").strip()},
                "ASSERTED",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "ESTABLISHES",
                    None,
                    assertion.value,
                    None,
                )
            )
        for match in _PREFERENCE.finditer(content):
            value = {
                "preferred": match.group("preferred").strip(),
                "over": match.group("other").strip(),
            }
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, match, "whole"),
                subject,
                "preference",
                value,
                "PREFERENCE",
                None,
                "GOVERNED_REVIEW_REQUIRED",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "ESTABLISHES",
                    None,
                    value,
                    None,
                )
            )
        for match in _INTENT.finditer(content):
            value = {"action": match.group("action").strip()}
            assertion = _assertion(
                _matched_span(evidence_id, source_ref, content, match, "whole"),
                subject,
                "current_intent",
                value,
                "INTENT",
                None,
                "QUERY_LOCAL_ONLY",
            )
            assertions.append(assertion)
            transitions.append(
                _transition(
                    assertion.span,
                    assertion,
                    "ESTABLISHES",
                    None,
                    value,
                    None,
                )
            )
    assertions.sort(key=lambda item: (item.span.source_ref, item.span.start, item.predicate))
    transitions.sort(key=lambda item: (item.span.source_ref, item.span.start, item.relation))
    return assertions, transitions


def _entity_candidate(
    span: FormationSourceSpanV01,
    identity_key: str,
    mention_type: str,
) -> FormationEntityCandidateV01:
    provisional = FormationEntityCandidateV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        identity_key=identity_key,
        mention_type=mention_type,
        producer_identity=PRODUCER_IDENTITY,
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationEntityCandidateV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _assertion(
    span: FormationSourceSpanV01,
    subject: str,
    predicate: str,
    value: Any,
    modality: str,
    valid_time: InterpretationEventTime | None,
    disposition: str,
) -> FormationStateAssertionV01:
    provisional = FormationStateAssertionV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        subject_identity=subject,
        predicate=predicate,
        value=value,
        modality=modality,
        valid_time=valid_time,
        producer_identity=PRODUCER_IDENTITY,
        promotion_disposition=disposition,
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationStateAssertionV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _transition(
    span: FormationSourceSpanV01,
    assertion: FormationStateAssertionV01,
    relation: str,
    previous_value: Any,
    new_value: Any,
    valid_time: InterpretationEventTime | None,
) -> FormationStateTransitionV01:
    provisional = FormationStateTransitionV01.model_construct(
        artifact_digest="0" * 64,
        span=span,
        subject_identity=assertion.subject_identity,
        predicate=assertion.predicate,
        relation=relation,
        previous_value=previous_value,
        new_value=new_value,
        resulting_assertion_digest=assertion.artifact_digest,
        valid_time=valid_time,
        producer_identity=PRODUCER_IDENTITY,
    )
    material = provisional.model_dump(mode="json", exclude={"artifact_digest"})
    return FormationStateTransitionV01(
        artifact_digest=canonical_sha256(material),
        **material,
    )


def _event_identity(
    scope_id: str,
    event_type: str,
    object_key: str,
    occurrence: InterpretationEventTime | None,
    span: FormationSourceSpanV01,
) -> str:
    if occurrence is not None and occurrence.start is not None:
        end = occurrence.end or occurrence.start
        time_key = f"{occurrence.start.isoformat()}/{end.isoformat()}"
    else:
        time_key = f"unresolved:{canonical_sha256(span.text)[:16]}"
    return f"{scope_id}|{event_type}|{object_key}|{time_key}"


def _event_object(text: str, event_type: str) -> str:
    if event_type == "attend":
        workshop = re.search(r"([A-Z][\w'-]+)\s+workshop", text, re.IGNORECASE)
        if workshop is not None:
            return f"{workshop.group(1).casefold()}-workshop"
    return _tokens(text)


def _tokens(text: str) -> str:
    ignored = {
        "a",
        "an",
        "at",
        "different",
        "i",
        "my",
        "same",
        "that",
        "the",
    }
    tokens = [
        token.casefold()
        for token in re.findall(r"[^\W_]+", text)
        if token.casefold() not in ignored
    ]
    return "-".join(tokens[:12]) or "event"


def _matched_span(
    evidence_id: str,
    source_ref: str,
    content: str,
    match: re.Match[str],
    group: str,
) -> FormationSourceSpanV01:
    start, end = match.span(group)
    return _span(evidence_id, source_ref, content, start, end)


def _span(
    evidence_id: str,
    source_ref: str,
    content: str,
    start: int,
    end: int,
) -> FormationSourceSpanV01:
    return FormationSourceSpanV01(
        evidence_id=evidence_id,
        source_ref=source_ref,
        start=start,
        end=end,
        text=content[start:end],
    )


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


__all__ = [
    "PRODUCER_IDENTITY",
    "FormationGeneralizationError",
    "GeneralizedFormationBundle",
    "build_generalized_formation",
]
