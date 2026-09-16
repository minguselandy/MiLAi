"""One-pass, raw-preserving consumption of noncanonical Formation sidecars."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from milai.domain.formation_artifact import (
    FormationArtifactSidecarV01,
    FormationSourceSpanV01,
)
from milai.domain.formation_state import FormationStateChangeSidecarV01

RepresentationArm = Literal["FORMED_PLUS_RAW", "FORMED_ONLY"]
Facet = Literal[
    "CURRENT_STATE",
    "PREFERENCE",
    "SHORT_LIVED_STATE",
    "EVENT_IDENTITY",
    "EVENT_TIME",
    "GENERIC",
]

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CURRENT = re.compile(
    r"\b(?:current|currently|latest|state|live|location|allerg\w*)\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(r"\b(?:prefer\w*|preference|favorite|favourite)\b", re.IGNORECASE)
_SHORT_LIVED = re.compile(
    r"\b(?:intent|plan\w*|temporary|temporarily|short[- ]lived|constraint)\b",
    re.IGNORECASE,
)
_EVENT_IDENTITY = re.compile(
    r"\b(?:same|different|distinct|identity)\b.*\b(?:event|attend\w*|workshop)\b|"
    r"\b(?:event|attend\w*|workshop)\b.*\b(?:same|different|distinct|identity)\b",
    re.IGNORECASE,
)
_EVENT_TIME = re.compile(
    r"\b(?:which|what)\b.*\b(?:first|earlier)\b|"
    r"\b(?:when|temporal|order|before|after)\b",
    re.IGNORECASE,
)
_STATE_PREDICATES = frozenset({"residence", "allergy", "occupation", "temporary_location"})
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "after",
        "and",
        "did",
        "do",
        "first",
        "happened",
        "i",
        "is",
        "latest",
        "my",
        "or",
        "should",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
    }
)


class FormationRecollectionError(ValueError):
    """A sidecar cannot be consumed against the supplied Raw snapshot."""


@dataclass(frozen=True, slots=True)
class FormationRecollectionResult:
    representation: RepresentationArm
    required_facets: tuple[Facet, ...]
    covered_facets: tuple[Facet, ...]
    accepted_evidence_ids: tuple[str, ...]
    formed_evidence_ids: tuple[str, ...]
    raw_fallback_evidence_ids: tuple[str, ...]
    complete: bool
    selected_state_assertion_digests: tuple[str, ...] = ()
    selected_state_transition_digests: tuple[str, ...] = ()
    selected_event_candidate_digests: tuple[str, ...] = ()
    selected_entity_candidate_digests: tuple[str, ...] = ()
    canonical_mutation: bool = False
    model_calls: int = 0
    official_acquisition_actions: int = 1


def recollect_with_formation(
    *,
    query: str,
    formation: FormationArtifactSidecarV01,
    state_changes: FormationStateChangeSidecarV01,
    source_records: Sequence[Mapping[str, Any]],
    raw_candidate_evidence_ids: Sequence[str],
    representation: RepresentationArm,
) -> FormationRecollectionResult:
    """Select grounded source Evidence once, with an optional Raw fallback.

    Formation remains a query-independent input.  Query-time consumption only
    selects source spans; it neither materializes a Claim nor treats a derived
    artifact as independent evidence.
    """

    if formation.source_snapshot_digest != state_changes.source_snapshot_digest:
        raise FormationRecollectionError("FORMATION_SOURCE_SNAPSHOT_MISMATCH")
    sources = _admissible_sources(source_records)
    required = _required_facets(query)
    selected: set[str] = set()
    covered: set[Facet] = set()
    selected_state_digests: set[str] = set()
    selected_event_digests: set[str] = set()
    selected_entity_digests: set[str] = set()

    state_assertions = [
        item for item in state_changes.assertions if _valid_span(item.span, sources)
    ]
    events = [item for item in formation.event_candidates if _valid_span(item.span, sources)]
    entities = [item for item in formation.entity_candidates if _valid_span(item.span, sources)]

    for facet in required:
        if facet == "CURRENT_STATE":
            matching = _matching_states(query, state_assertions)
            selected.update(item.span.evidence_id for item in matching)
            selected_state_digests.update(item.artifact_digest for item in matching)
            if matching:
                covered.add(facet)
        elif facet == "PREFERENCE":
            matching = [item for item in state_assertions if item.modality == "PREFERENCE"]
            selected.update(item.span.evidence_id for item in matching)
            selected_state_digests.update(item.artifact_digest for item in matching)
            if matching:
                covered.add(facet)
        elif facet == "SHORT_LIVED_STATE":
            matching = [
                item for item in state_assertions if item.modality in {"INTENT", "TEMPORARY"}
            ]
            selected.update(item.span.evidence_id for item in matching)
            selected_state_digests.update(item.artifact_digest for item in matching)
            if matching:
                covered.add(facet)
        elif facet == "EVENT_IDENTITY":
            matching_events = _matching_events(query, events)
            selected.update(item.span.evidence_id for item in matching_events)
            selected.update(item.span.evidence_id for item in entities)
            selected_event_digests.update(item.artifact_digest for item in matching_events)
            selected_entity_digests.update(item.artifact_digest for item in entities)
            if len({item.event_identity_key for item in matching_events}) >= 2:
                covered.add(facet)
        elif facet == "EVENT_TIME":
            matching_events = _matching_events(query, events)
            selected.update(item.span.evidence_id for item in matching_events)
            selected_event_digests.update(item.artifact_digest for item in matching_events)
            resolved = [item for item in matching_events if item.occurrence_time is not None]
            if len(resolved) >= 2:
                covered.add(facet)
        else:
            matching_states = _matching_states(query, state_assertions, broad=False)
            matching_events = _matching_events(query, events, fallback_all=False)
            selected.update(item.span.evidence_id for item in matching_states)
            selected.update(item.span.evidence_id for item in matching_events)
            selected_state_digests.update(item.artifact_digest for item in matching_states)
            selected_event_digests.update(item.artifact_digest for item in matching_events)
            if matching_states or matching_events:
                covered.add(facet)

    formed = tuple(sorted(selected, key=lambda value: _source_order(value, sources)))
    fallback: tuple[str, ...] = ()
    if representation == "FORMED_PLUS_RAW" and set(required) != covered:
        fallback = tuple(
            sorted(
                {
                    evidence_id
                    for evidence_id in raw_candidate_evidence_ids
                    if evidence_id in sources and evidence_id not in selected
                },
                key=lambda value: _source_order(value, sources),
            )
        )
    accepted = tuple(
        sorted(set(formed) | set(fallback), key=lambda value: _source_order(value, sources))
    )
    return FormationRecollectionResult(
        representation=representation,
        required_facets=required,
        covered_facets=tuple(facet for facet in required if facet in covered),
        accepted_evidence_ids=accepted,
        formed_evidence_ids=formed,
        raw_fallback_evidence_ids=fallback,
        selected_state_assertion_digests=tuple(sorted(selected_state_digests)),
        selected_state_transition_digests=tuple(
            sorted(
                item.artifact_digest
                for item in state_changes.transitions
                if item.resulting_assertion_digest in selected_state_digests
                and _valid_span(item.span, sources)
            )
        ),
        selected_event_candidate_digests=tuple(sorted(selected_event_digests)),
        selected_entity_candidate_digests=tuple(sorted(selected_entity_digests)),
        complete=set(required) == covered,
    )


def _required_facets(query: str) -> tuple[Facet, ...]:
    facets: list[Facet] = []
    for facet, pattern in (
        ("CURRENT_STATE", _CURRENT),
        ("PREFERENCE", _PREFERENCE),
        ("SHORT_LIVED_STATE", _SHORT_LIVED),
        ("EVENT_IDENTITY", _EVENT_IDENTITY),
        ("EVENT_TIME", _EVENT_TIME),
    ):
        if pattern.search(query):
            facets.append(facet)  # type: ignore[arg-type]
    return tuple(facets or ["GENERIC"])


def _admissible_sources(
    source_records: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    sources: dict[str, Mapping[str, Any]] = {}
    scopes: set[str] = set()
    for source in source_records:
        evidence_id = source.get("evidence_id")
        scope_id = source.get("scope_id")
        if not isinstance(evidence_id, str) or not isinstance(scope_id, str):
            raise FormationRecollectionError("FORMATION_SOURCE_IDENTITY_INVALID")
        if evidence_id in sources:
            raise FormationRecollectionError("FORMATION_SOURCE_DUPLICATED")
        scopes.add(scope_id)
        if (
            source.get("speaker") == "user"
            and source.get("retention_state") == "READABLE"
            and source.get("revoked_at") is None
            and source.get("access_decision") == "ALLOWED"
            and isinstance(source.get("permission_snapshot"), Mapping)
            and source["permission_snapshot"].get("readable") is True
        ):
            sources[evidence_id] = source
    if len(scopes) > 1:
        raise FormationRecollectionError("FORMATION_CROSS_SCOPE_INPUT")
    return sources


def _valid_span(
    span: FormationSourceSpanV01,
    sources: Mapping[str, Mapping[str, Any]],
) -> bool:
    source = sources.get(span.evidence_id)
    if source is None:
        return False
    content = source.get("content")
    if not isinstance(content, str):
        raise FormationRecollectionError("FORMATION_SOURCE_CONTENT_INVALID")
    if source.get("source_ref") != span.source_ref:
        raise FormationRecollectionError("FORMATION_SOURCE_REF_MISMATCH")
    if content[span.start : span.end] != span.text:
        raise FormationRecollectionError("FORMATION_SOURCE_SPAN_MISMATCH")
    return True


def _matching_states(
    query: str,
    assertions: Sequence[Any],
    *,
    broad: bool = True,
) -> list[Any]:
    normalized = query.casefold()
    if "allerg" in normalized and not any(
        word in normalized for word in ("location", "live", "residence")
    ):
        allowed = {"allergy"}
    elif any(word in normalized for word in ("location", "live", "residence")):
        allowed = {"residence", "temporary_location"}
        if "allerg" in normalized:
            allowed.add("allergy")
    else:
        allowed = set(_STATE_PREDICATES)
    terms = _query_terms(query)
    return [
        item
        for item in assertions
        if (broad and item.predicate in allowed)
        or (
            (not broad or item.modality in {"PREFERENCE", "INTENT", "TEMPORARY"})
            and bool(terms & _artifact_terms(item.predicate, item.value))
        )
    ]


def _matching_events(
    query: str,
    events: Sequence[Any],
    *,
    fallback_all: bool = True,
) -> list[Any]:
    terms = _query_terms(query)
    lexical = [
        item
        for item in events
        if terms
        & _artifact_terms(
            item.event_type,
            item.event_identity_key,
            item.span.text,
        )
    ]
    return lexical or (list(events) if fallback_all else [])


def _query_terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(value)
        if token.casefold() not in _QUERY_STOPWORDS and len(token) > 2
    }


def _artifact_terms(*values: object) -> set[str]:
    return {token.casefold() for token in _WORD.findall(" ".join(map(str, values)))}


def _source_order(
    evidence_id: str,
    sources: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    source = sources[evidence_id]
    return str(source.get("source_ref", "")), evidence_id


__all__ = [
    "FormationRecollectionError",
    "FormationRecollectionResult",
    "recollect_with_formation",
]
