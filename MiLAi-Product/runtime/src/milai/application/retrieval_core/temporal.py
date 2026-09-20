"""Pure temporal query and candidate ordering helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from milai.domain.retrieval import QueryPlan

_TEMPORAL_RELATION = re.compile(
    r"\b(?P<direction>before|prior\s+to|earlier\s+than|after|following)\b",
    re.IGNORECASE,
)
_TEMPORAL_RECENCY = re.compile(
    r"\b(?:most\s+recent(?:ly)?|latest|last)\b",
    re.IGNORECASE,
)
_TEMPORAL_AGO = re.compile(
    r"\b(?P<count>an?|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)
_TEMPORAL_RELATIVE_DAY = re.compile(r"\b(?P<day>today|yesterday)\b", re.IGNORECASE)
_TEMPORAL_ALTERNATIVES = re.compile(
    r"\b(?:a|an|the)?\s*(?P<left>[^\W\d_]+)\s+or\s+"
    r"(?:a|an|the)?\s*(?P<right>[^\W\d_]+)\b",
    re.IGNORECASE | re.UNICODE,
)
_TEMPORAL_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_TEMPORAL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "before",
        "buying",
        "did",
        "do",
        "does",
        "for",
        "from",
        "getting",
        "had",
        "has",
        "have",
        "i",
        "in",
        "is",
        "it",
        "last",
        "latest",
        "me",
        "most",
        "my",
        "of",
        "on",
        "or",
        "purchasing",
        "recent",
        "recently",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)

_TEMPORAL_AMOUNT = {
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
}
_TEMPORAL_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

_ACQUISITION_TERMS = frozenset(
    {
        "acquire",
        "acquired",
        "bought",
        "buy",
        "get",
        "getting",
        "got",
        "order",
        "ordered",
        "purchase",
        "purchased",
    }
)


def _binary_event_anchor_terms(
    plan: QueryPlan | None,
) -> tuple[frozenset[str], frozenset[str]] | None:
    if plan is None or plan.operator != "TEMPORAL_BEFORE_AFTER":
        return None
    if plan.operator_arguments.get("target_mode") != "binary_ordering":
        return None
    raw = plan.operator_arguments.get("event_anchor_terms")
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    values: list[frozenset[str]] = []
    for anchor in raw:
        if not isinstance(anchor, list):
            return None
        terms = frozenset(term.casefold() for term in anchor if isinstance(term, str) and term)
        if not terms:
            return None
        values.append(terms)
    return values[0], values[1]


def _binary_event_anchor_queries(plan: QueryPlan) -> tuple[str, ...]:
    anchors = _binary_event_anchor_terms(plan)
    if anchors is None:
        return ()
    return tuple(" ".join(sorted(anchor)) for anchor in anchors)


def _binary_anchor_cover(
    candidates: list[dict[str, Any]],
    anchors: tuple[frozenset[str], frozenset[str]],
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0 or not candidates:
        return []
    token_sets = [_temporal_tokens(_temporal_text(candidate)) for candidate in candidates]

    def matches(index: int, anchor: frozenset[str]) -> bool:
        overlap = len(token_sets[index].intersection(anchor))
        required = 1 if len(anchor) == 1 else 2
        return overlap >= required and overlap / len(anchor) >= 0.5

    pairs = [
        (left_index, right_index)
        for left_index in range(len(candidates))
        if matches(left_index, anchors[0])
        for right_index in range(len(candidates))
        if left_index != right_index and matches(right_index, anchors[1])
    ]
    if not pairs:
        return candidates[:limit]

    def pair_score(pair: tuple[int, int]) -> tuple[float, float, int, int]:
        left_index, right_index = pair
        coverages = [
            len(token_sets[index].intersection(anchor)) / len(anchor)
            for index, anchor in zip(pair, anchors, strict=True)
        ]
        return (
            min(coverages),
            sum(coverages),
            -left_index,
            -right_index,
        )

    left_index, right_index = max(pairs, key=pair_score)
    priority = [left_index, right_index]
    priority.extend(index for index in range(len(candidates)) if index not in priority)
    return [candidates[index] for index in priority[:limit]]


def _relative_point_target(plan: QueryPlan | None) -> datetime | None:
    if plan is None or plan.operator != "TEMPORAL_BEFORE_AFTER":
        return None
    if plan.operator_arguments.get("target_mode") != "relative_point":
        return None
    raw_count = plan.operator_arguments.get("offset_count")
    unit = plan.operator_arguments.get("offset_unit")
    if not isinstance(raw_count, str) or not isinstance(unit, str):
        return None
    count = int(raw_count) if raw_count.isdecimal() else _TEMPORAL_AMOUNT.get(raw_count.casefold())
    days = _TEMPORAL_UNIT_DAYS.get(unit.casefold())
    if count is None or days is None:
        return None
    return plan.time_reference - timedelta(days=count * days)


def _relative_point_cover(
    candidates: list[dict[str, Any]], target: datetime, limit: int, *, query: str
) -> list[dict[str, Any]]:
    """Keep the best reranked candidate nearest an explicit relative time point."""
    if limit <= 0 or not candidates:
        return []
    timed = [
        (
            distance,
            -_relative_event_intent_overlap(candidate, target, query),
            index,
        )
        for index, candidate in enumerate(candidates)
        if (distance := _relative_event_distance(candidate, target, allow_canonical=False))
        is not None
    ]
    if not timed:
        return candidates[:limit]
    _distance, _negative_overlap, nearest_index = min(timed)
    priority = [nearest_index]
    priority.extend(index for index in range(len(candidates)) if index != nearest_index)
    return [candidates[index] for index in priority[:limit]]


def _temporal_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in (match.group(0).casefold() for match in _TEMPORAL_WORD.finditer(value))
        if len(token) > 2 and token not in _TEMPORAL_STOPWORDS
    )


def _temporal_text(candidate: dict[str, Any]) -> str:
    payload = candidate.get("payload")
    if not isinstance(payload, dict):
        return ""
    memory_text = payload.get("memory_text")
    return memory_text if isinstance(memory_text, str) else ""


def _temporal_timestamp(candidate: dict[str, Any]) -> datetime | None:
    value = candidate.get("valid_time_from")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _temporal_subject_indices(candidates: list[dict[str, Any]], query: str) -> list[int]:
    token_sets = [_temporal_tokens(_temporal_text(candidate)) for candidate in candidates]
    alternatives = _TEMPORAL_ALTERNATIVES.search(query)
    if alternatives is not None:
        choice_tokens = {
            alternatives.group("left").casefold(),
            alternatives.group("right").casefold(),
        }
        matched = [index for index, tokens in enumerate(token_sets) if tokens & choice_tokens]
        if matched:
            return matched

    query_tokens = _temporal_tokens(query)
    overlaps = [len(tokens & query_tokens) for tokens in token_sets]
    maximum = max(overlaps, default=0)
    if maximum == 0:
        return []
    return [index for index, overlap in enumerate(overlaps) if overlap == maximum]


def _relative_target(query: str, reference_time: datetime | None) -> datetime | None:
    if reference_time is None or reference_time.tzinfo is None:
        return None
    relation = _TEMPORAL_AGO.search(query)
    if relation is None:
        return None
    raw_count = relation.group("count").casefold()
    count = int(raw_count) if raw_count.isdecimal() else _TEMPORAL_AMOUNT[raw_count]
    days = count * _TEMPORAL_UNIT_DAYS[relation.group("unit").casefold()]
    return reference_time - timedelta(days=days)


def _rerank_by_reference(
    candidates: list[dict[str, Any]],
    query: str,
    reference_time: datetime | None,
) -> list[dict[str, Any]] | None:
    target = _relative_target(query, reference_time)
    recency = _TEMPORAL_RECENCY.search(query) is not None
    if target is None and not recency:
        return None
    if target is not None:
        # Relative-point queries bind time before semantics. Date proximity
        # builds the bounded pool and the existing cross-encoder supplies the
        # semantic ordering in one batch, even when query and source use
        # different ordinary wording.
        timed_by_event = [
            (
                index,
                _relative_event_distance(candidate, target),
                bool(_relative_event_dates(candidate)),
                len(_temporal_tokens(_temporal_text(candidate)) & _temporal_tokens(query)),
            )
            for index, candidate in enumerate(candidates)
        ]
        timed_by_event = [item for item in timed_by_event if item[1] is not None]
        if not timed_by_event:
            return None
        timed_by_event.sort(key=lambda item: (not item[2], item[1], -item[3], item[0]))
        priority = [index for index, _distance, _explicit, _overlap in timed_by_event]
        priority.extend(index for index in range(len(candidates)) if index not in priority)
        return [candidates[index] for index in priority]
    subject_indices = _temporal_subject_indices(candidates, query)
    timed = [
        (index, timestamp)
        for index in subject_indices
        if (timestamp := _temporal_timestamp(candidates[index])) is not None
    ]
    if not timed:
        return None
    if target is not None:
        timed.sort(key=lambda item: (abs((item[1] - target).total_seconds()), item[0]))
    else:
        timed.sort(key=lambda item: (-item[1].timestamp(), item[0]))
    priority = [index for index, _timestamp in timed]
    priority.extend(index for index in range(len(candidates)) if index not in priority)
    return [candidates[index] for index in priority]


def _relative_event_dates(candidate: dict[str, Any]) -> list[datetime]:
    reference = _temporal_timestamp(candidate)
    if reference is None:
        return []
    text = _temporal_text(candidate)
    event_dates: list[datetime] = []
    for match in _TEMPORAL_AGO.finditer(text):
        raw_count = match.group("count").casefold()
        count = int(raw_count) if raw_count.isdecimal() else _TEMPORAL_AMOUNT[raw_count]
        days = count * _TEMPORAL_UNIT_DAYS[match.group("unit").casefold()]
        event_dates.append(reference - timedelta(days=days))
    for match in _TEMPORAL_RELATIVE_DAY.finditer(text):
        event_dates.append(
            reference if match.group("day").casefold() == "today" else reference - timedelta(days=1)
        )
    return event_dates


def _intent_tokens(value: str) -> frozenset[str]:
    tokens = set(_temporal_tokens(value))
    raw = {match.group(0).casefold() for match in _TEMPORAL_WORD.finditer(value)}
    if raw.intersection(_ACQUISITION_TERMS):
        tokens.add("acquisition")
    return frozenset(tokens)


def _relative_event_intent_overlap(candidate: dict[str, Any], target: datetime, query: str) -> int:
    reference = _temporal_timestamp(candidate)
    if reference is None:
        return 0
    query_tokens = _intent_tokens(query)
    best = 0
    for line in _temporal_text(candidate).splitlines():
        if not line.strip():
            continue
        event_dates: list[datetime] = []
        for match in _TEMPORAL_AGO.finditer(line):
            raw_count = match.group("count").casefold()
            count = int(raw_count) if raw_count.isdecimal() else _TEMPORAL_AMOUNT[raw_count]
            days = count * _TEMPORAL_UNIT_DAYS[match.group("unit").casefold()]
            event_dates.append(reference - timedelta(days=days))
        for match in _TEMPORAL_RELATIVE_DAY.finditer(line):
            event_dates.append(
                reference
                if match.group("day").casefold() == "today"
                else reference - timedelta(days=1)
            )
        if (
            event_dates
            and min(abs((event.date() - target.date()).days) for event in event_dates) == 0
        ):
            best = max(best, len(query_tokens.intersection(_intent_tokens(line))))
    return best


def _relative_event_distance(
    candidate: dict[str, Any], target: datetime, *, allow_canonical: bool = True
) -> int | None:
    event_dates = _relative_event_dates(candidate)
    if not event_dates and allow_canonical:
        reference = _temporal_timestamp(candidate)
        if reference is not None:
            event_dates.append(reference)
    if not event_dates:
        return None
    return min(abs((event.date() - target.date()).days) for event in event_dates)


def _temporal_rerank(
    candidates: list[dict[str, Any]],
    query: str | None,
    *,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rerank canonical candidates for explicit temporal relations and reference time."""
    if not query or len(candidates) < 2:
        return candidates
    reference_ranked = _rerank_by_reference(candidates, query, reference_time)
    if reference_ranked is not None:
        return reference_ranked
    relation = _TEMPORAL_RELATION.search(query)
    if relation is None:
        return candidates
    anchor_terms = _temporal_tokens(query[relation.end() :])
    if not anchor_terms:
        return candidates

    token_sets = [_temporal_tokens(_temporal_text(candidate)) for candidate in candidates]
    anchor_index = next(
        (index for index, tokens in enumerate(token_sets) if anchor_terms.issubset(tokens)),
        None,
    )
    if anchor_index is None:
        return candidates
    anchor_time = _temporal_timestamp(candidates[anchor_index])
    if anchor_time is None:
        return candidates

    direction = relation.group("direction").casefold()
    wants_before = direction in {"before", "prior to", "earlier than"}
    anchor_tokens = token_sets[anchor_index]
    related: list[tuple[float, float, int]] = []
    for index, (candidate, tokens) in enumerate(zip(candidates, token_sets, strict=True)):
        if index == anchor_index or not tokens:
            continue
        candidate_time = _temporal_timestamp(candidate)
        if candidate_time is None:
            continue
        delta_seconds = (candidate_time - anchor_time).total_seconds()
        if (wants_before and delta_seconds >= 0) or (not wants_before and delta_seconds <= 0):
            continue
        union = anchor_tokens | tokens
        similarity = len(anchor_tokens & tokens) / len(union) if union else 0.0
        related.append((similarity, -abs(delta_seconds), index))
    if not related:
        return candidates
    similarity, _proximity, related_index = max(
        related, key=lambda item: (item[0], item[1], -item[2])
    )
    if similarity < 0.08:
        return candidates

    priority = [related_index, anchor_index]
    priority.extend(index for index in range(len(candidates)) if index not in priority)
    return [candidates[index] for index in priority]
