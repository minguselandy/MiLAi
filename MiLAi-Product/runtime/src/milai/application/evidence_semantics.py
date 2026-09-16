"""DG-17 source-span, interpretation, and requirement-binding pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NamedTuple

from pydantic import JsonValue

from milai.application.current_intent import has_explicit_current_intent
from milai.application.evidence_source import (
    evidence_source_turn_identity,
    structured_evidence_identity,
    structured_evidence_speaker,
)
from milai.application.lookup_readiness import LookupRelationReadiness, classify_lookup_relation
from milai.domain.semantic_query import (
    BindingCompatibility,
    CompatibilityStatus,
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    InterpretationEventTime,
    InterpretationKind,
    InterpretationTimeBasis,
    NonTemporalApplicability,
    RequirementBinding,
    TypeDirectedSemanticAudit,
)

_LINE = re.compile(r"[^\r\n]+")
_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
_NON_TERMINAL_ABBREVIATION = re.compile(
    r"(?:\b(?:dr|jr|mr|mrs|ms|prof|sr|st|vs)|\b[A-Z])\.$",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(
    r"(?<![\w.])(?P<currency>[$£€])?\s*"
    r"(?P<value>[-+]?\d+(?:,\d{3})*(?:\.\d+)?)(?!\w|\.\d)"
)
_MONTH_DATE = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?\b",
    re.I,
)
_NUMERIC_DATE = re.compile(
    r"(?<![\d/])(?P<month>1[0-2]|0?[1-9])/(?P<day>3[01]|[12]\d|0?[1-9])"
    r"(?:/(?P<year>\d{2}|\d{4}))?(?![\d/])"
)
_ISO_DATE = re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?!\d)")
_RELATIVE_AGO = re.compile(
    r"\b(?:(?:about|around)\s+)?"
    r"(?P<count>a|an|few|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?|years?)\s+ago\b",
    re.I,
)
_RELATIVE_DAY = re.compile(r"\b(?P<day>today|yesterday)\b", re.I)
_RELATIVE_WEEKDAY = re.compile(
    r"\b(?:(?P<last>last)\s+)?"
    r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_LAST_WEEKEND = re.compile(r"\blast weekend\b", re.I)
_MONTH_ONLY = re.compile(
    r"\b(?:in|during)\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
    r"(?:\s+(?P<year>\d{4}))?\b",
    re.I,
)
_UNTIL_PREFIX = re.compile(r"\b(?:through|until)\s*$", re.I)
_DATE_PATTERNS = (
    _ISO_DATE,
    _MONTH_DATE,
    _NUMERIC_DATE,
    _RELATIVE_AGO,
    _RELATIVE_DAY,
    _RELATIVE_WEEKDAY,
    _LAST_WEEKEND,
    _MONTH_ONLY,
)
_PREFERENCE = re.compile(
    r"\b(?:prefer|preferred|favorite|favourite|like|liked|love|loved|enjoy|"
    r"enjoyed|dislike|disliked|hate|hated|avoid|avoided|allergic)\b",
    re.I,
)
_NEGATIVE_PREFERENCE = re.compile(
    r"\b(?:dislike|disliked|hate|hated|avoid|avoided|allergic|do not like|don't like)\b",
    re.I,
)
_EVENT_SIGNAL = re.compile(
    r"\b(?:attend(?:ed|ing)?|baked|beat|bought|born|cancel(?:led|ed)?|completed|"
    r"decided|finished|got|happened|had|made|met|moved|paint(?:ed|ing)?|"
    r"launch(?:ed|ing)?|participat(?:e|ed|ing)|plant(?:ed|ing)?|"
    r"prepar(?:e|ed|ing)|read|"
    r"repair(?:ed|ing)?|scheduled|shared|started|tried|used|visited|"
    r"sign(?:ed|ing)?|volunteer(?:ed|ing)?|went|"
    r"welcom(?:e|ed|ing)|won)\b",
    re.I,
)
_PLANNED_EVENT = re.compile(
    r"\b(?:considering|plan(?:ned|ning)?|schedul(?:e|ed|ing)|upcoming|will)\b",
    re.I,
)
_CANCELLED_EVENT = re.compile(
    r"\b(?:cancel(?:led|ed)?|missed)\b|"
    r"\b(?:did not|didn't|have not|haven't)\s+"
    r"(?:attend|bake|buy|complete|finish|go|make|meet|tr(?:y|ied)|use|visit)\b",
    re.I,
)
_PAST_EVENT_SIGNAL = re.compile(
    r"\b(?:attended|baked|beat|bought|born|completed|decided|finished|got|had|"
    r"made|met|moved|painted|participated|planted|read|repaired|shared|started|"
    r"tried|used|visited|volunteered|welcomed|went|won)\b",
    re.I,
)
_BIRTH_SIGNAL = re.compile(r"\b(?:bab(?:y|ies)|born|twins?|welcomed)\b", re.I)
_INCIDENTAL_EVENT_MENTION = re.compile(
    r"\b(?:for\s+example|for\s+instance|like\s+when|such\s+as|"
    r"as\s+an\s+example)\b",
    re.IGNORECASE,
)
_SOURCE_DERIVED_EVENT_MENTION = re.compile(
    r"\b(?:you\s+(?:mentioned|said|told\s+me)|i\s+noticed\s+that\s+you|"
    r"as\s+(?:i|we)\s+(?:mentioned|said)|according\s+to\s+what\s+you\s+said)\b",
    re.IGNORECASE,
)
_SECONDARY_EVENT_INDEX = re.compile(
    r"\b(?:add|adding|record|recording|list|listing|note|noting|track|tracking|"
    r"remember|remembering)\b[^.!?]{0,100}\b(?:birthday|calendar|event|"
    r"milestone|reminder|schedule)\b|"
    r"\b(?:let\s+me\s+not\s+forget|(?:i|we)\s+should\s+also\s+add|"
    r"(?:i|we)(?:'ll|\s+will)\s+add)\b",
    re.IGNORECASE,
)
_TWINS_NAMED = re.compile(
    r"\btwins?\s*,?\s*(?P<first>[A-Z][a-z]+)\s+and\s+(?P<second>[A-Z][a-z]+)\b"
)
_BABY_NAMED = re.compile(
    r"\b(?:baby|boy|girl|child)(?:\s+(?:boy|girl))?\s+named\s+(?P<name>[A-Z][a-z]+)\b",
    re.I,
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
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
    "few": 3,
}
_WEEKDAYS = {
    name: index
    for index, name in enumerate(
        (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    )
}
# Every supported date expression contains a decimal digit or one of these
# whole words. A positive signal is not a date: the original patterns still
# decide ranges, priority and validity. Keep Unicode/IGNORECASE regex semantics.
_DATE_SIGNAL = re.compile(
    r"\d|\b(?:"
    + "|".join((*_MONTHS, *_WEEKDAYS, "ago", "today", "yesterday", "weekend"))
    + r")\b",
    re.I,
)
_CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR"}
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "assistant",
        "at",
        "for",
        "family",
        "from",
        "had",
        "has",
        "have",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "the",
        "to",
        "user",
        "was",
        "were",
        "with",
    }
)
_SYNONYMS = {
    "babies": "birth",
    "baby": "birth",
    "born": "birth",
    "newborn": "birth",
    "welcomed": "birth",
    "baked": "bake",
    "baking": "bake",
    "baguette": "bake",
    "bread": "bake",
    "cake": "bake",
    "celebration": "festival",
    "cookies": "bake",
    "cookie": "bake",
    "cooking": "bake",
    "oven": "bake",
    "bicycle": "bike",
    "bicycles": "bike",
    "bought": "buy",
    "aunt": "family",
    "aunts": "family",
    "cousin": "family",
    "cousins": "family",
    "got": "buy",
    "relative": "family",
    "relatives": "family",
    "uncle": "family",
    "uncles": "family",
    "purchased": "buy",
    "participated": "participate",
    "participating": "participate",
    "gaming": "game",
    "repaired": "repair",
    "repairing": "repair",
}
_EVENT_ACTION_TERMS = frozenset(
    {
        "attend",
        "bake",
        "beat",
        "birth",
        "buy",
        "cancel",
        "complete",
        "decid",
        "finish",
        "had",
        "launch",
        "make",
        "meet",
        "move",
        "paint",
        "participate",
        "plant",
        "prepar",
        "read",
        "repair",
        "servic",
        "share",
        "sign",
        "start",
        "take",
        "try",
        "use",
        "visit",
        "volunteer",
        "welcome",
        "win",
    }
)
_GENERIC_EVENT_ENTITY_TERMS = frozenset({"activity", "event"})
BindingOutcome = Literal["MATCH", "POSSIBLE", "REJECTED"]


def project_evidence_spans(
    evidence: Sequence[Mapping[str, Any]],
) -> list[EvidenceSpan]:
    """Project exact governed source pointers without assigning semantic roles."""

    spans: list[EvidenceSpan] = []
    for item in evidence:
        prepared = _source_span_inputs(item)
        if prepared is None:
            continue
        content, metadata = prepared
        for start, end in _source_offsets(content):
            spans.append(_project_evidence_span(content, metadata, start, end))
    return sorted(
        spans,
        key=lambda span: (
            span.source_timestamp or datetime.min.replace(tzinfo=UTC),
            span.source_turn_ref,
            span.start,
            span.span_id,
        ),
    )


def _source_span_inputs(item: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if not evidence_source_eligible(item):
        return None
    content, evidence_id, source_ref = (
        item.get("content"), item.get("evidence_id"), item.get("source_ref")
    )
    if not all(isinstance(value, str) and value for value in (content, evidence_id, source_ref)):
        return None
    assert isinstance(content, str) and isinstance(source_ref, str)
    source_timestamp = _timestamp(item.get("observed_at"))
    system_timestamp = _timestamp(item.get("captured_at") or item.get("system_time"))
    identity = structured_evidence_identity(item, source_ref)
    if identity is None:
        return None
    speaker, speaker_source = structured_evidence_speaker(item)
    return content, {
        "source_evidence_id": evidence_id, "source_turn_ref": source_ref,
        "subject_id": identity.subject_id, "session_id": identity.session_id,
        "turn_id": identity.turn_id, "identity_source": identity.identity_source,
        "speaker": speaker, "source_timestamp": source_timestamp,
        "provenance": {
            "authority_class": "EVIDENCE_ONLY",
            "system_timestamp": (
                system_timestamp.isoformat() if system_timestamp is not None else None
            ),
            "source_content_hash": item.get("content_hash"), "speaker_source": speaker_source,
            "projection_persisted": False, "source_span_verified": True,
        },
    }


def _project_evidence_span(
    content: str, metadata: Mapping[str, Any], start: int, end: int,
) -> EvidenceSpan:
    text = content[start:end]
    span = EvidenceSpan(
        **metadata,
        span_id=_identity("span", [metadata["source_evidence_id"], start, end, text]),
        start=start, end=end, text=text,
    )
    if not verify_evidence_span(span, content):
        raise AssertionError("EvidenceSpan projection is not source-exact")
    return span


def deduplicate_projected_spans(spans: Sequence[EvidenceSpan]) -> list[EvidenceSpan]:
    """Preserve the existing post-projection last-wins order and timezone fallback."""
    values = {span.span_id: span for span in spans}
    zone = next((span.source_timestamp.tzinfo for span in spans if span.source_timestamp), UTC)
    return sorted(values.values(), key=lambda span: (
        span.source_timestamp or datetime.min.replace(tzinfo=zone),
        span.source_turn_ref, span.start, span.span_id,
    ))


def interpret_evidence_spans(
    spans: Sequence[EvidenceSpan],
    *,
    allowed_kinds: Collection[InterpretationKind] | None = None,
    resolve_local_anchors: bool = False,
) -> list[EvidenceInterpretationCandidate]:
    """Produce 0..N fallible meanings per span, never requirement bindings."""

    interpretations, _ = _interpret_evidence_spans(
        spans,
        allowed_kinds=allowed_kinds,
        resolve_local_anchors=resolve_local_anchors,
    )
    return interpretations


def resolve_direct_event_time(
    text: str,
    source_timestamp: datetime | None,
) -> tuple[InterpretationEventTime, InterpretationTimeBasis] | None:
    """Resolve time expressed by one exact Evidence span.

    Formation and query-time interpretation share this deterministic
    normalizer so a derived sidecar cannot silently invent a second temporal
    convention.  ``source_timestamp`` is only a calendar/timezone anchor for
    relative wording; it is never returned as event time by substitution.
    """

    return _explicit_event_time(text, source_timestamp)


def direct_event_time_expression_count(text: str) -> int:
    """Count distinct temporal expressions without double-counting overlaps.

    A phrase such as ``in March 2026`` may be recognized by more than one
    normalizer pattern.  Overlapping matches are therefore one expression,
    while two disjoint dates in one span remain two.  Formation uses this to
    avoid treating a multi-event sentence as an unambiguous temporal anchor.
    """

    merged: list[tuple[int, int]] = []
    for start, end in sorted(_date_match_ranges(text)):
        if merged and start < merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return len(merged)


class _TextAnalysis(NamedTuple):
    entities: list[str]
    date_ranges: list[tuple[int, int]]
    first_dates: dict[re.Pattern[str], re.Match[str] | None]
    numbers: tuple[re.Match[str], ...]
    event_signal: bool
    preference: bool
    current_intent: bool


def _analyze_text(text: str) -> _TextAnalysis:
    first_dates: dict[re.Pattern[str], re.Match[str] | None] = {}
    date_ranges = _date_match_ranges(text, first_matches=first_dates)
    return _TextAnalysis(
        sorted(_semantic_terms(_WORD.findall(text)))[:32],
        date_ranges,
        first_dates,
        tuple(_NUMBER.finditer(text)),
        _EVENT_SIGNAL.search(text) is not None,
        _PREFERENCE.search(text) is not None,
        has_explicit_current_intent(text),
    )


def _interpret_evidence_spans(
    spans: Sequence[EvidenceSpan],
    *,
    allowed_kinds: Collection[InterpretationKind] | None,
    resolve_local_anchors: bool = False,
) -> tuple[list[EvidenceInterpretationCandidate], int]:
    interpretations: dict[str, EvidenceInterpretationCandidate] = {}
    allowed = set(allowed_kinds) if allowed_kinds is not None else None
    suppressed = 0
    # Reuse lexical scans only within this invocation. Source-time normalization,
    # speaker checks and provenance remain per span; unique texts are not retained.
    text_counts = Counter(span.text for span in spans)
    text_analysis: dict[str, _TextAnalysis] = {}
    for span in spans:
        analysis = text_analysis.get(span.text)
        if analysis is None:
            analysis = _analyze_text(span.text)
            if text_counts[span.text] > 1:
                text_analysis[span.text] = analysis
        entities = analysis.entities
        date_ranges = analysis.date_ranges
        explicit_time = _explicit_event_time(
            span.text, span.source_timestamp, first_matches=analysis.first_dates
        )
        if explicit_time is not None:
            event_time, basis = explicit_time
            explicit_time = (
                event_time.model_copy(
                    update={
                        "anchor_provenance": {
                            "anchor_kind": (
                                "EXPLICIT_TEXT_SPAN"
                                if basis == "EXPLICIT_EVENT_TIME"
                                else "BOUNDED_RELATIVE_TO_SOURCE_OBSERVED_AT"
                            ),
                            "source_turn_ref": span.source_turn_ref,
                            "span_id": span.span_id,
                            "normalized_from": event_time.normalized_from,
                            "relation_to_event_span": "SAME_SPAN",
                            "normalizer_version": "deterministic-event-time-v0.2",
                            "precision": "DAY",
                            "timezone": _timezone_name(event_time.start),
                            "ambiguity_disposition": "UNAMBIGUOUS_SINGLE_PARSE",
                            "source_time_substitution": False,
                        }
                    }
                ),
                basis,
            )

        for match in analysis.numbers:
            if any(_overlaps(match.span(), date_range) for date_range in date_ranges):
                continue
            try:
                decimal_value = Decimal(match.group("value").replace(",", ""))
            except InvalidOperation:
                continue
            value: JsonValue = (
                int(decimal_value)
                if decimal_value == decimal_value.to_integral()
                else float(decimal_value)
            )
            currency = match.group("currency")
            unit = _CURRENCY.get(currency) if currency else "COUNT"
            predicate = "money" if currency else "integer_count"
            if allowed is not None and "QUANTITY" not in allowed:
                suppressed += 1
                continue
            candidate = _interpretation(
                span,
                kind="QUANTITY",
                value=value,
                unit=unit,
                entities=entities,
                predicate=predicate,
                time_basis="UNRESOLVED",
                discriminator=[match.start(), match.end(), predicate, value, unit],
            )
            interpretations.setdefault(candidate.interpretation_id, candidate)

        if explicit_time is not None or analysis.event_signal:
            candidate_event_time: InterpretationEventTime | None
            candidate_time_basis: InterpretationTimeBasis
            if explicit_time is not None:
                candidate_event_time, candidate_time_basis = explicit_time
            else:
                candidate_event_time = None
                candidate_time_basis = (
                    "SOURCE_OBSERVED_TIME" if span.source_timestamp is not None else "UNRESOLVED"
                )
            event_identities: Sequence[str | None] = _event_identities(span.text) or (None,)
            for event_identity in event_identities:
                if allowed is not None and "EVENT" not in allowed:
                    suppressed += 1
                    continue
                candidate = _interpretation(
                    span,
                    kind="EVENT",
                    value={
                        "text": span.text,
                        "event_status": _event_status(span.text),
                        "event_identity": event_identity,
                    },
                    unit=None,
                    entities=entities,
                    predicate="event_observation",
                    event_time=candidate_event_time,
                    time_basis=candidate_time_basis,
                    discriminator=["event", candidate_time_basis, event_identity],
                )
                interpretations.setdefault(candidate.interpretation_id, candidate)

        if analysis.preference:
            if allowed is not None and "PREFERENCE_SIGNAL" not in allowed:
                suppressed += 1
            else:
                stance = "NEGATIVE" if _NEGATIVE_PREFERENCE.search(span.text) else "POSITIVE"
                candidate = _interpretation(
                    span,
                    kind="PREFERENCE_SIGNAL",
                    value={"text": span.text, "stance": stance},
                    unit=None,
                    entities=entities,
                    predicate="preference_signal",
                    time_basis="UNRESOLVED",
                    discriminator=["preference", stance],
                )
                interpretations.setdefault(candidate.interpretation_id, candidate)

        if analysis.current_intent and span.speaker == "user":
            if allowed is not None and "DECISION" not in allowed:
                suppressed += 1
            else:
                candidate = _interpretation(
                    span,
                    kind="DECISION",
                    value={"text": span.text, "decision_status": "CURRENT_INTENT"},
                    unit=None,
                    entities=entities,
                    predicate="current_intent",
                    time_basis="UNRESOLVED",
                    discriminator=["current-intent", "explicit-first-person"],
                )
                interpretations.setdefault(candidate.interpretation_id, candidate)

        if span.text.strip() and (allowed is None or "STATE_OBSERVATION" in allowed):
            candidate = _interpretation(
                span,
                kind="STATE_OBSERVATION",
                value=span.text,
                unit=None,
                entities=entities,
                predicate="source_observation",
                time_basis="UNRESOLVED",
                discriminator=["state-observation"],
            )
            interpretations.setdefault(candidate.interpretation_id, candidate)
        elif span.text.strip():
            suppressed += 1
    ordered = sorted(
        interpretations.values(),
        key=lambda item: (item.span_id, item.kind, item.interpretation_id),
    )
    if resolve_local_anchors:
        ordered = resolve_local_event_time_anchors(ordered, spans)
    return ordered, suppressed


def resolve_local_event_time_anchors(
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
    *,
    radius: int = 2,
) -> list[EvidenceInterpretationCandidate]:
    """Resolve only unambiguous local event-time anchors with explicit provenance."""
    if radius < 0 or radius > 2:
        raise ValueError("local event-time anchor radius must be between 0 and 2")
    span_by_id = {span.span_id: span for span in spans}
    explicit: list[tuple[tuple[str, int], EvidenceInterpretationCandidate]] = []
    for item in interpretations:
        span = span_by_id.get(item.span_id)
        identity = _turn_identity(span.source_turn_ref) if span is not None else None
        if (
            identity is not None
            and item.kind == "EVENT"
            and item.time_basis == "EXPLICIT_EVENT_TIME"
            and item.event_time is not None
        ):
            explicit.append((identity, item))
    resolved = []
    for item in interpretations:
        span = span_by_id.get(item.span_id)
        if span is None:
            resolved.append(item)
            continue
        identity = _turn_identity(span.source_turn_ref)
        if (
            identity is None
            or item.kind != "EVENT"
            or item.event_time is not None
            or item.time_basis not in {"UNRESOLVED", "SOURCE_OBSERVED_TIME"}
        ):
            resolved.append(item)
            continue
        candidates = [
            (abs(identity[1] - anchor_identity[1]), anchor)
            for anchor_identity, anchor in explicit
            if anchor_identity[0] == identity[0]
            and (
                anchor_identity != identity
                or _same_turn_event_anchor_compatible(
                    span.text,
                    span_by_id[anchor.span_id].text,
                )
            )
            and abs(identity[1] - anchor_identity[1]) <= radius
        ]
        if not candidates:
            resolved.append(item)
            continue
        nearest_distance = min(distance for distance, _anchor in candidates)
        nearest = [anchor for distance, anchor in candidates if distance == nearest_distance]
        intervals = {
            (
                anchor.event_time.start,
                anchor.event_time.end,
            )
            for anchor in nearest
            if anchor.event_time is not None
        }
        if len(intervals) != 1:
            resolved.append(item)
            continue
        anchor = nearest[0]
        assert anchor.event_time is not None
        event_time = anchor.event_time.model_copy(
            update={
                "anchor_provenance": {
                    "anchor_kind": "LOCAL_EXPLICIT_EVENT_TIME",
                    "anchor_interpretation_id": anchor.interpretation_id,
                    "anchor_source_turn_ref": span_by_id[anchor.span_id].source_turn_ref,
                    "anchor_span_id": anchor.span_id,
                    "target_source_turn_ref": span.source_turn_ref,
                    "turn_radius": nearest_distance,
                    "relation_to_event_span": "ADJACENT_TURN",
                    "normalizer_version": "deterministic-event-time-v0.2",
                    "precision": "DAY",
                    "timezone": _timezone_name(anchor.event_time.start),
                    "ambiguity_disposition": "UNAMBIGUOUS_NEAREST_INTERVAL",
                    "source_time_substitution": False,
                }
            }
        )
        resolved.append(
            item.model_copy(
                update={
                    "interpretation_id": _identity(
                        "interpretation-anchor",
                        [item.interpretation_id, anchor.interpretation_id, nearest_distance],
                    ),
                    "event_time": event_time,
                    "time_basis": "INFERRED_EVENT_TIME",
                }
            )
        )
    return sorted(
        resolved,
        key=lambda candidate: (
            candidate.span_id,
            candidate.kind,
            candidate.interpretation_id,
        ),
    )


def _same_turn_event_anchor_compatible(target_text: str, anchor_text: str) -> bool:
    """Allow cross-sentence time transfer only for the same action family."""

    target_actions = _semantic_terms(_WORD.findall(target_text)).intersection(
        _EVENT_ACTION_TERMS
    )
    anchor_actions = _semantic_terms(_WORD.findall(anchor_text)).intersection(
        _EVENT_ACTION_TERMS
    )
    return bool(target_actions.intersection(anchor_actions))


def _turn_identity(source_turn_ref: str) -> tuple[str, int] | None:
    return evidence_source_turn_identity(source_turn_ref)


def bind_requirements(
    requirements: Sequence[EvidenceRequirementV02],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
    *,
    type_compatible_only: bool = False,
    compatibility_profile: Literal["legacy-v0.1", "dg22-v0.2"] = "legacy-v0.1",
) -> list[RequirementBinding]:
    """Validate type/entity/unit/time compatibility without model authority."""

    span_by_id = {span.span_id: span for span in spans}
    bindings: list[RequirementBinding] = []
    # Only relation-text classification is shared; compatibility remains per source.
    lookup_readiness: dict[str, LookupRelationReadiness] = {}
    for requirement in requirements:
        required_entities = _semantic_terms(requirement.entity_constraints)
        for interpretation in interpretations:
            if type_compatible_only and (interpretation.kind != requirement.interpretation_kind):
                continue
            span = span_by_id.get(interpretation.span_id)
            if span is None:
                raise ValueError("INTERPRETATION_SOURCE_SPAN_MISSING")
            type_status: CompatibilityStatus = (
                "PASS" if interpretation.kind == requirement.interpretation_kind else "FAIL"
            )
            entity_status = _entity_compatibility(
                requirement,
                interpretation,
                span,
                require_all=compatibility_profile == "dg22-v0.2",
                required_terms=required_entities,
            )
            if compatibility_profile == "dg22-v0.2":
                predicate_status = _predicate_compatibility(
                    requirement, interpretation, span, lookup_readiness=lookup_readiness
                )
                source_status = _source_compatibility(requirement, span)
                role_status = _role_compatibility(requirement, interpretation, span)
            else:
                predicate_status = "NOT_APPLICABLE"
                source_status = "NOT_APPLICABLE"
                role_status = "NOT_APPLICABLE"
            unit_status = _unit_compatibility(requirement, interpretation)
            temporal_status = _temporal_compatibility(
                requirement,
                interpretation,
                span,
                unknown_on_unresolved=compatibility_profile == "dg22-v0.2",
            )
            compatibility = BindingCompatibility(
                type=type_status,
                entity=entity_status,
                predicate=predicate_status,
                source=source_status,
                role=role_status,
                unit=unit_status,
                temporal=temporal_status,
                episode=_episode_compatibility(requirement, interpretation, span),
            )
            statuses = compatibility.model_dump().values()
            if "FAIL" in statuses:
                status: BindingOutcome = "REJECTED"
                reason = _first_failure(compatibility)
            elif "UNKNOWN" in statuses:
                status = "POSSIBLE"
                reason = "COMPATIBILITY_UNPROVEN"
            else:
                status = "MATCH"
                reason = "ALL_BINDING_CONSTRAINTS_SATISFIED"
            bindings.append(
                RequirementBinding(
                    schema_version=(
                        "requirement-binding-v0.2"
                        if compatibility_profile == "dg22-v0.2"
                        else "requirement-binding-v0.1"
                    ),
                    requirement_id=requirement.slot_id,
                    interpretation_id=interpretation.interpretation_id,
                    status=status,
                    compatibility=compatibility,
                    reason_code=reason,
                )
            )
    return sorted(
        bindings,
        key=lambda binding: (
            binding.requirement_id,
            binding.status != "MATCH",
            binding.interpretation_id,
        ),
    )


def run_type_directed_semantics(
    requirements: Sequence[EvidenceRequirementV02],
    spans: Sequence[EvidenceSpan],
    *,
    compatibility_profile: Literal["legacy-v0.1", "dg22-v0.2"] = "legacy-v0.1",
) -> tuple[
    list[EvidenceInterpretationCandidate],
    list[RequirementBinding],
    TypeDirectedSemanticAudit,
]:
    """Interpret and bind only requirement-compatible kinds with full cost accounting."""

    allowed = sorted({requirement.interpretation_kind for requirement in requirements})
    if any(span.provenance.get("source_span_verified") is not True for span in spans):
        raise ValueError("TYPE_DIRECTED_SEMANTICS_REQUIRES_EXACT_SOURCE_SPANS")
    interpretations, suppressed = _interpret_evidence_spans(
        spans,
        allowed_kinds=allowed,
        resolve_local_anchors=compatibility_profile == "dg22-v0.2",
    )
    bindings = bind_requirements(
        requirements,
        interpretations,
        spans,
        type_compatible_only=True,
        compatibility_profile=compatibility_profile,
    )
    materialized_cross_product = len(requirements) * len(interpretations)
    legacy_evaluations = len(requirements) * (len(interpretations) + suppressed)
    type_pruned = legacy_evaluations - len(bindings)
    audit = TypeDirectedSemanticAudit(
        allowed_interpretation_kinds=allowed,
        span_count=len(spans),
        suppressed_interpretation_count=suppressed,
        materialized_interpretation_count=len(interpretations),
        legacy_binding_evaluation_count=legacy_evaluations,
        binding_evaluation_count=len(bindings),
        type_pruned_before_binding_count=type_pruned,
        materialized_type_mismatch_count=0,
        exact_source_span_failure_count=0,
    )
    if materialized_cross_product < len(bindings):
        raise AssertionError("type-directed binding exceeded its materialized cross product")
    return interpretations, bindings, audit


def matched_bindings_by_slot(
    bindings: Sequence[RequirementBinding],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for binding in bindings:
        if binding.status == "MATCH":
            result.setdefault(binding.requirement_id, []).append(binding.interpretation_id)
    return result


def verify_evidence_span(span: EvidenceSpan, source_content: str) -> bool:
    return span.end <= len(source_content) and source_content[span.start : span.end] == span.text


def evidence_source_eligible(item: Mapping[str, Any]) -> bool:
    if item.get("revoked_at") is not None or item.get("deleted_at") is not None:
        return False
    if item.get("retention_state") not in {None, "READABLE"}:
        return False
    if item.get("lifecycle") in {"DELETED", "REVOKED", "PURGED"}:
        return False
    permission = item.get("permission_snapshot")
    if isinstance(permission, Mapping) and permission.get("readable") is not True:
        return False
    return item.get("access_decision") not in {"DENIED", "SCOPE_MISMATCH"}


def _interpretation(
    span: EvidenceSpan,
    *,
    kind: str,
    value: JsonValue,
    unit: str | None,
    entities: list[str],
    predicate: str,
    time_basis: str,
    discriminator: list[JsonValue],
    event_time: InterpretationEventTime | None = None,
) -> EvidenceInterpretationCandidate:
    interpretation_id = _identity(
        "interpretation",
        [span.span_id, kind, predicate, value, unit, *discriminator],
    )
    return EvidenceInterpretationCandidate.model_validate(
        {
            "interpretation_id": interpretation_id,
            "span_id": span.span_id,
            "kind": kind,
            "value": value,
            "unit": unit,
            "entities": entities,
            "predicate": predicate,
            "event_time": event_time,
            "time_basis": time_basis,
            "extractor_identity": "deterministic-evidence-interpreter-v0.1",
            "confidence": None,
        }
    )


def _entity_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
    *,
    require_all: bool = False,
    required_terms: set[str] | None = None,
) -> CompatibilityStatus:
    required = (
        _semantic_terms(requirement.entity_constraints)
        if required_terms is None
        else required_terms
    )
    if not required:
        return "NOT_APPLICABLE"

    # A span may support more than one interpretation (for example, two
    # purchases with different entities and dates).  Once an interpreter has
    # supplied a grounded entity projection, that projection is the boundary
    # for this interpretation.  Unioning every word from the shared span here
    # leaks entities between sibling interpretations and can make both bind to
    # the same requirement.  Source terms remain a compatibility fallback for
    # older or deliberately entity-free interpretations.
    interpreted_entities = _semantic_terms(interpretation.entities)
    observed = interpreted_entities or _semantic_terms(_WORD.findall(span.text))
    if interpretation.kind != "EVENT":
        if "answer_bearing" in requirement.predicate_constraints:
            # Ordinary lookup requirements describe the remembered subject and
            # relation, not an exact bag-of-words quotation of the question.
            # Keep short anchors exact, while allowing one longer query anchor
            # to be expressed implicitly or by a deterministic morphology
            # variant.  Predicate/source/semantic-role compatibility remain
            # independent gates in the DG-22 profile below.
            overlap_count = len(required.intersection(observed))
            minimum = len(required) if len(required) <= 2 else len(required) - 1
            return "PASS" if overlap_count >= minimum else "FAIL"
        return "PASS" if required.issubset(observed) else "FAIL"
    if require_all:
        action_anchors = required.intersection(_EVENT_ACTION_TERMS)
        specific_anchors = required.difference(_GENERIC_EVENT_ENTITY_TERMS)
        entity_anchors = specific_anchors.difference(action_anchors)
        # Strict event matching always requires every action anchor and a
        # concrete entity anchor.  A multi-term noun phrase may contain one
        # implicit descriptive modifier (for example, a category qualifier),
        # but generic event words never substitute for its concrete head.
        minimum_entity_overlap = (
            0 if not entity_anchors else max(1, len(entity_anchors) - 1)
        )
        return (
            "PASS"
            if action_anchors.issubset(observed)
            and len(entity_anchors.intersection(observed)) >= minimum_entity_overlap
            else "FAIL"
        )
    overlap_count = len(required.intersection(observed))
    minimum = 1 if len(required) == 1 else (len(required) + 1) // 2
    return "PASS" if overlap_count >= minimum else "FAIL"


def _unit_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
) -> CompatibilityStatus:
    if requirement.interpretation_kind != "QUANTITY":
        return "NOT_APPLICABLE"
    price_role = requirement.slot_id in {"TOTAL_PRICE", "MONEY"} or any(
        value in {"total", "money", "price"} for value in requirement.predicate_constraints
    )
    count_role = requirement.slot_id in {"ITEM_COUNT", "COUNT"} or any(
        value in {"count", "integer_count"} for value in requirement.predicate_constraints
    )
    if price_role:
        return "PASS" if interpretation.unit in _CURRENCY.values() else "FAIL"
    if count_role:
        value = interpretation.value
        return (
            "PASS"
            if interpretation.unit == "COUNT"
            and isinstance(value, int)
            and not isinstance(value, bool)
            else "FAIL"
        )
    return "PASS" if requirement.value_type in {None, "NUMBER", "ANY"} else "UNKNOWN"


def _predicate_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
    *,
    lookup_readiness: dict[str, LookupRelationReadiness] | None = None,
) -> CompatibilityStatus:
    required = set(requirement.predicate_constraints)
    if not required:
        return "NOT_APPLICABLE"
    observed = interpretation.predicate
    if "answer_bearing" in required and interpretation.kind == "STATE_OBSERVATION":
        readiness = lookup_readiness.get(span.text) if lookup_readiness is not None else None
        if readiness is None:
            readiness = classify_lookup_relation(span.text)
            if lookup_readiness is not None:
                lookup_readiness[span.text] = readiness
        if readiness == "READY":
            return "PASS"
        if readiness in {"QUESTION_PARAPHRASE", "NON_ASSERTIVE_INTENTION"}:
            return "FAIL"
        return "UNKNOWN"
    structural_event = {
        "answer_bearing",
        "deduplicate",
        "event_at_time",
        "event_time",
        "matches_range",
    }
    if interpretation.kind == "EVENT":
        if (
            required.intersection({"event_at_time", "event_time"})
            and (
                interpretation.event_time is None
                or interpretation.event_time.start is None
            )
        ):
            # A temporal value predicate is a value contract, not merely an
            # EVENT-kind tag.  The candidate can remain visible, but it is
            # definitively incompatible with a DATETIME-valued slot and must
            # not be classified as semantic-owner ambiguity.
            return "FAIL"
        event_families = [
            value.removeprefix("event_type:")
            for value in required
            if value.startswith("event_type:")
        ]
        if event_families:
            observed_terms = _semantic_terms(interpretation.entities)
            family_match = all(
                _semantic_terms(re.split(r"[_-]+", family)).issubset(observed_terms)
                for family in event_families
            )
            if not family_match:
                return "FAIL"
        social_circle = "participant_relation:social_circle" in required
        if social_circle:
            # ``family`` is intentionally ignored for ordinary entity matching,
            # but it is a first-class predicate value on the relation axis.
            observed_terms = _relation_terms(interpretation.entities)
            if not observed_terms.intersection({"friend", "family"}):
                return "FAIL"
        if all(
            value in structural_event
            or value.startswith(
                ("distance_unit:", "relation:", "event_type:", "participant_relation:")
            )
            for value in required
        ):
            return "PASS"
    aliases = {
        "supports_preference": {"preference_signal"},
        "current_intent": {"current_intent"},
        "scalar_count_fact": {"integer_count"},
        "count": {"integer_count"},
        "money": {"money"},
        "price": {"money"},
        "total": {"money"},
        "current_state": {"source_observation"},
        "user_fact": {"source_observation"},
    }
    accepted = {candidate for value in required for candidate in aliases.get(value, {value})}
    if observed is None:
        return "UNKNOWN"
    if observed in accepted:
        return "PASS"
    return "FAIL" if any(value in aliases for value in required) else "UNKNOWN"


def _source_compatibility(
    requirement: EvidenceRequirementV02,
    span: EvidenceSpan,
) -> CompatibilityStatus:
    if span.identity_source == "UNKNOWN":
        return "UNKNOWN"
    allowed = requirement.evidence_source.allowed_speakers
    if allowed is None:
        return "NOT_APPLICABLE"
    if span.speaker == "unknown":
        return "UNKNOWN"
    return "PASS" if span.speaker.upper() in set(allowed) else "FAIL"


def _role_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> CompatibilityStatus:
    roles = requirement.semantic_roles.model_dump(mode="json")
    required = [str(value) for value in roles.values() if value]
    if not required:
        return "NOT_APPLICABLE"
    observed = _semantic_terms([*interpretation.entities, *_WORD.findall(span.text)])
    for value in required:
        if value.upper() in {"USER", "ASSISTANT", "SYSTEM", "TOOL"}:
            if span.speaker == "unknown":
                return "UNKNOWN"
            if span.speaker.upper() != value.upper():
                return "FAIL"
        elif not _semantic_terms([value]).issubset(observed):
            return "UNKNOWN"
    return "PASS"


def derive_non_temporal_applicability(
    bindings: Sequence[RequirementBinding],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    spans: Sequence[EvidenceSpan],
) -> list[NonTemporalApplicability]:
    """Project the five independent non-temporal axes with exact source pointers."""
    interpretation_by_id = {item.interpretation_id: item for item in interpretations}
    span_by_id = {item.span_id: item for item in spans}
    results: list[NonTemporalApplicability] = []
    for binding in bindings:
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if interpretation is None or interpretation.span_id not in span_by_id:
            raise ValueError("BINDING_APPLICABILITY_SOURCE_MISSING")
        span = span_by_id[interpretation.span_id]
        axes = {
            "type": binding.compatibility.type,
            "entity": binding.compatibility.entity,
            "predicate": binding.compatibility.predicate,
            "source": binding.compatibility.source,
            "role": binding.compatibility.role,
        }
        if "FAIL" in axes.values():
            status: BindingOutcome = "REJECTED"
            reason = next(
                f"{name.upper()}_INCOMPATIBLE" for name, value in axes.items() if value == "FAIL"
            )
        elif "UNKNOWN" in axes.values():
            status = "POSSIBLE"
            reason = "NON_TEMPORAL_APPLICABILITY_UNPROVEN"
        else:
            status = "MATCH"
            reason = "ALL_NON_TEMPORAL_AXES_SATISFIED"
        results.append(
            NonTemporalApplicability(
                requirement_id=binding.requirement_id,
                interpretation_id=binding.interpretation_id,
                span_id=span.span_id,
                source_turn_ref=span.source_turn_ref,
                status=status,
                reason_code=reason,
                type=axes["type"],
                entity=axes["entity"],
                predicate=axes["predicate"],
                source=axes["source"],
                role=axes["role"],
            )
        )
    return sorted(
        results,
        key=lambda item: (item.requirement_id, item.interpretation_id),
    )


def adapt_requirement_binding_v01(payload: Mapping[str, Any]) -> RequirementBinding:
    """Read a sealed v0.1 Binding into v0.2 without inventing new-axis evidence."""
    value = dict(payload)
    if value.get("schema_version", "requirement-binding-v0.1") == "requirement-binding-v0.1":
        compatibility = dict(value.get("compatibility", {}))
        for axis in ("predicate", "source", "role"):
            compatibility.setdefault(axis, "NOT_APPLICABLE")
        value["compatibility"] = compatibility
        value["schema_version"] = "requirement-binding-v0.2"
    return RequirementBinding.model_validate(value)


def _temporal_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
    *,
    unknown_on_unresolved: bool = False,
) -> CompatibilityStatus:
    constraint = requirement.temporal_constraints
    if constraint is None:
        return "NOT_APPLICABLE"
    if constraint.time_axis == "SOURCE_OBSERVED_TIME":
        source_at = span.source_timestamp
        if source_at is None:
            return "UNKNOWN"
        if constraint.boundary == "POINT":
            return "PASS" if source_at.date() == constraint.start.date() else "FAIL"  # type: ignore[union-attr]
        if constraint.boundary == "UNBOUNDED":
            return "PASS"
        assert constraint.start is not None and constraint.end is not None
        if constraint.boundary == "CLOSED_OPEN":
            return "PASS" if constraint.start <= source_at < constraint.end else "FAIL"
        return "PASS" if constraint.start <= source_at <= constraint.end else "FAIL"
    if interpretation.time_basis == "SOURCE_OBSERVED_TIME":
        return "UNKNOWN" if unknown_on_unresolved else "FAIL"
    event_time = interpretation.event_time
    event_at = event_time.start if event_time is not None else None
    if event_at is None:
        return "UNKNOWN" if unknown_on_unresolved else "FAIL"
    if constraint.boundary == "UNBOUNDED":
        return "PASS"
    if constraint.boundary == "POINT":
        return "PASS" if event_at.date() == constraint.start.date() else "FAIL"  # type: ignore[union-attr]
    assert constraint.start is not None and constraint.end is not None
    if constraint.boundary == "CLOSED_OPEN":
        event_end = event_time.end if event_time is not None else None
        if event_end is not None and event_end > event_at:
            compatible = event_at < constraint.end and event_end > constraint.start
        else:
            compatible = constraint.start <= event_at < constraint.end
    else:
        compatible = constraint.start <= event_at <= constraint.end
    if compatible or _same_deictic_answer_cue(requirement, interpretation):
        return "PASS"
    return "FAIL"


def _same_deictic_answer_cue(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
) -> bool:
    """Treat repeated relative wording as a lookup cue, not a shifted hard date.

    This exception is deliberately limited to single-valued answer-bearing
    lookup requirements.  Range, count, and set semantics continue to require
    interval compatibility and therefore cannot inherit this relaxation.
    """

    constraint = requirement.temporal_constraints
    event_time = interpretation.event_time
    if (
        constraint is None
        or interpretation.time_basis != "INFERRED_EVENT_TIME"
        or event_time is None
        or event_time.normalized_from is None
        or "answer_bearing" not in requirement.predicate_constraints
        or requirement.cardinality.maximum != 1
        or requirement.cardinality.distinct
    ):
        return False
    query_cues = {item.text.casefold().strip() for item in constraint.normalized_from}
    return event_time.normalized_from.casefold().strip() in query_cues


def _episode_compatibility(
    requirement: EvidenceRequirementV02,
    interpretation: EvidenceInterpretationCandidate,
    span: EvidenceSpan,
) -> CompatibilityStatus:
    """Reject mentions that cannot prove a distinct primary event occurrence."""

    if requirement.interpretation_kind != "EVENT":
        return "NOT_APPLICABLE"
    if any(
        pattern.search(span.text)
        for pattern in (
            _INCIDENTAL_EVENT_MENTION,
            _SOURCE_DERIVED_EVENT_MENTION,
            _SECONDARY_EVENT_INDEX,
        )
    ):
        return "FAIL"
    if not (
        requirement.cardinality.maximum is None
        and requirement.cardinality.distinct
    ):
        # Primary-occurrence checks apply to every event value.  Exhaustive
        # queries additionally use this axis for episode deduplication, but a
        # single-valued event still cannot be proved by an incidental example,
        # a conversational restatement, or a secondary index entry.
        return "PASS"
    return "PASS"


def _first_failure(compatibility: BindingCompatibility) -> str:
    for name, status in compatibility.model_dump().items():
        if status == "FAIL":
            return f"{name.upper()}_INCOMPATIBLE"
    raise AssertionError("failure reason requested without a failed dimension")


def _event_status(text: str) -> str:
    if _CANCELLED_EVENT.search(text) is not None:
        return "CANCELLED"
    if _PLANNED_EVENT.search(text) is not None and _PAST_EVENT_SIGNAL.search(text) is None:
        return "PLANNED"
    return "OCCURRED"


def _event_identities(text: str) -> list[str]:
    if _BIRTH_SIGNAL.search(text) is None:
        return []
    values: list[str] = []
    twins = _TWINS_NAMED.search(text)
    if twins is not None:
        values.extend((twins.group("first"), twins.group("second")))
    values.extend(match.group("name") for match in _BABY_NAMED.finditer(text))
    return list(dict.fromkeys(value.casefold() for value in values))


def _source_offsets(content: str) -> list[tuple[int, int]]:
    """Split exact spans without interpreting body text as source metadata."""

    return list(_iter_source_offsets(content))


def _iter_source_offsets(content: str) -> Iterator[tuple[int, int]]:
    for line in _LINE.finditer(content):
        line_text = line.group(0)
        sentence_start: int | None = None
        for sentence_match in _SENTENCE.finditer(line_text):
            if sentence_start is None:
                sentence_start = sentence_match.start()
            raw_fragment = sentence_match.group(0)
            if (
                raw_fragment.rstrip().endswith(".")
                and _NON_TERMINAL_ABBREVIATION.search(raw_fragment.rstrip()) is not None
                and sentence_match.end() < len(line_text)
            ):
                continue
            raw = line_text[sentence_start : sentence_match.end()]
            left_trim = len(raw) - len(raw.lstrip())
            right_trim = len(raw.rstrip())
            if right_trim <= left_trim:
                sentence_start = None
                continue
            start = line.start() + sentence_start + left_trim
            end = line.start() + sentence_start + right_trim
            yield start, end
            sentence_start = None


def _explicit_event_time(
    text: str,
    source_timestamp: datetime | None,
    *,
    first_matches: Mapping[re.Pattern[str], re.Match[str] | None] | None = None,
) -> tuple[InterpretationEventTime, InterpretationTimeBasis] | None:
    def search(pattern: re.Pattern[str]) -> re.Match[str] | None:
        return pattern.search(text) if first_matches is None else first_matches[pattern]

    for pattern in (_ISO_DATE, _MONTH_DATE, _NUMERIC_DATE):
        matched = search(pattern)
        if matched is None:
            continue
        groups = matched.groupdict()
        year_raw = groups.get("year")
        year = int(year_raw) if year_raw else source_timestamp.year if source_timestamp else None
        if year is None:
            return None
        if year < 100:
            year += 2000
        month_raw = matched.group("month")
        month = int(month_raw) if month_raw.isdecimal() else _MONTHS[month_raw.casefold()]
        try:
            value = datetime(
                year,
                month,
                int(matched.group("day")),
                tzinfo=(source_timestamp.tzinfo if source_timestamp else UTC),
            )
        except ValueError:
            return None
        prefix = text[max(0, matched.start() - 16) : matched.start()]
        until = _UNTIL_PREFIX.search(prefix)
        if until is not None:
            normalized_start = max(0, matched.start() - 16) + until.start()
            end_of_day = value + timedelta(days=1) - timedelta(microseconds=1)
            interval_start = source_timestamp or value
            if interval_start > end_of_day:
                return None
            return (
                InterpretationEventTime(
                    start=interval_start,
                    end=end_of_day,
                    normalized_from=text[normalized_start : matched.end()],
                ),
                "INFERRED_EVENT_TIME",
            )
        return (
            InterpretationEventTime(
                start=value,
                end=value,
                normalized_from=matched.group(0),
            ),
            "EXPLICIT_EVENT_TIME",
        )
    relative = search(_RELATIVE_AGO)
    if relative is not None and source_timestamp is not None:
        count_raw = relative.group("count").casefold()
        count = int(count_raw) if count_raw.isdecimal() else _NUMBER_WORDS[count_raw]
        unit = relative.group("unit").casefold().rstrip("s")
        shifted = _shift_event_time(source_timestamp, count, unit)
        if shifted is None:
            return None
        return (
            InterpretationEventTime(
                start=shifted,
                end=shifted,
                normalized_from=relative.group(0),
            ),
            "INFERRED_EVENT_TIME",
        )
    relative_day = search(_RELATIVE_DAY)
    if relative_day is not None and source_timestamp is not None:
        source_day = source_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        value = (
            source_day
            if relative_day.group("day").casefold() == "today"
            else source_day - timedelta(days=1)
        )
        return (
            InterpretationEventTime(
                start=value,
                end=value + timedelta(days=1),
                normalized_from=relative_day.group(0),
            ),
            "INFERRED_EVENT_TIME",
        )
    weekend = search(_LAST_WEEKEND)
    if weekend is not None and source_timestamp is not None:
        source_day = source_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = source_day - timedelta(days=source_day.weekday())
        start = week_start - timedelta(days=2)
        end = week_start
        return (
            InterpretationEventTime(
                start=start,
                end=end,
                normalized_from=weekend.group(0),
            ),
            "INFERRED_EVENT_TIME",
        )
    weekday = search(_RELATIVE_WEEKDAY)
    if weekday is not None and source_timestamp is not None:
        target = _WEEKDAYS[weekday.group("weekday").casefold()]
        delta = (source_timestamp.weekday() - target) % 7 or 7
        value = source_timestamp.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=delta
        )
        return (
            InterpretationEventTime(
                start=value,
                end=value + timedelta(days=1),
                normalized_from=weekday.group(0),
            ),
            "INFERRED_EVENT_TIME",
        )
    month_only = search(_MONTH_ONLY)
    if month_only is not None:
        year_raw = month_only.group("year")
        year = int(year_raw) if year_raw else source_timestamp.year if source_timestamp else None
        if year is None:
            return None
        month = _MONTHS[month_only.group("month").casefold()]
        timezone = source_timestamp.tzinfo if source_timestamp is not None else UTC
        start = datetime(year, month, 1, tzinfo=timezone)
        end = (
            datetime(year + 1, 1, 1, tzinfo=timezone)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=timezone)
        )
        return (
            InterpretationEventTime(
                start=start,
                end=end,
                normalized_from=month_only.group(0),
            ),
            "EXPLICIT_EVENT_TIME" if year_raw else "INFERRED_EVENT_TIME",
        )
    return None


def _shift_event_time(
    value: datetime, count: int, unit: str
) -> datetime | None:
    """Return a representable inferred event time or reject the candidate."""

    try:
        if unit == "day":
            return value - timedelta(days=count)
        if unit == "week":
            return value - timedelta(days=count * 7)
        months = count * (12 if unit == "year" else 1)
        absolute = value.year * 12 + value.month - 1 - months
        year, month_index = divmod(absolute, 12)
        if not 1 <= year <= 9999:
            return None
        month = month_index + 1
        day = value.day
        while day > 28:
            try:
                return value.replace(year=year, month=month, day=day)
            except ValueError:
                day -= 1
        return value.replace(year=year, month=month, day=day)
    except (OverflowError, ValueError):
        return None


def _date_match_ranges(
    text: str,
    *,
    first_matches: dict[re.Pattern[str], re.Match[str] | None] | None = None,
) -> list[tuple[int, int]]:
    if _DATE_SIGNAL.search(text) is None:
        if first_matches is not None:
            first_matches.update(dict.fromkeys(_DATE_PATTERNS))
        return []
    ranges: list[tuple[int, int]] = []
    for pattern in _DATE_PATTERNS:
        matches = pattern.finditer(text)
        first = next(matches, None)
        if first_matches is not None:
            # Interpretation already needs every date range to exclude date digits
            # from quantities. Reuse the first match without rescanning this span.
            first_matches[pattern] = first
        if first is not None:
            ranges.append(first.span())
            ranges.extend(match.span() for match in matches)
    return ranges


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


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


def _timezone_name(value: datetime | None) -> str | None:
    if value is None or value.tzinfo is None:
        return None
    key = getattr(value.tzinfo, "key", None)
    if isinstance(key, str) and key:
        return key
    offset = value.utcoffset()
    if offset is None:
        return None
    seconds = int(offset.total_seconds())
    if seconds == 0:
        return "UTC"
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3_600)
    return f"{sign}{hours:02d}:{remainder // 60:02d}"


def _semantic_terms(values: Sequence[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        term = value.casefold().strip()
        if not term or term in _STOPWORDS:
            continue
        if term in _SYNONYMS:
            result.add(_SYNONYMS[term])
            continue
        if len(term) > 5 and term.endswith("ing"):
            term = term[:-3]
        elif len(term) > 4 and term.endswith("ed"):
            term = term[:-2]
        elif len(term) > 4 and term.endswith("ies"):
            term = f"{term[:-3]}y"
        elif len(term) > 3 and term.endswith("s"):
            term = term[:-1]
        result.add(_SYNONYMS.get(term, term))
    return result


def _relation_terms(values: Sequence[str]) -> set[str]:
    result = _semantic_terms(values)
    for value in values:
        for raw in _WORD.findall(value.casefold()):
            normalized = _SYNONYMS.get(raw, raw)
            if normalized in {"friend", "family"}:
                result.add(normalized)
    return result


def _identity(kind: str, material: list[JsonValue]) -> str:
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{kind}:" + hashlib.sha256(encoded.encode()).hexdigest()


__all__ = [
    "adapt_requirement_binding_v01",
    "bind_requirements",
    "derive_non_temporal_applicability",
    "direct_event_time_expression_count",
    "evidence_source_eligible",
    "interpret_evidence_spans",
    "matched_bindings_by_slot",
    "project_evidence_spans",
    "resolve_direct_event_time",
    "resolve_local_event_time_anchors",
    "run_type_directed_semantics",
    "verify_evidence_span",
]
