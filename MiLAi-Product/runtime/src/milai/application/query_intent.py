"""Small shared recognizers for query intent.

The recognizers describe grammar, not benchmark entities.  In particular,
``number of`` is a count only when ``number`` is the head of the phrase
(``the number of orders``).  In a compound attribute such as ``phone number
of the office``, ``number`` is a scalar identifier and the query is a lookup.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STRONG_COUNT = re.compile(r"\b(?:how\s+many|count(?:\s+of)?)\b", re.IGNORECASE)
_NUMBER_OF = re.compile(r"\bnumber\s+of\b", re.IGNORECASE)
_COUNT_HEAD_PREDECESSORS = frozenset(
    {"a", "an", "exact", "exactly", "overall", "the", "total", "what"}
)


def count_intent_spans(query: str) -> tuple[tuple[int, int], ...]:
    """Return non-overlapping spans that express collection cardinality."""

    spans = [(match.start(), match.end()) for match in _STRONG_COUNT.finditer(query)]
    for match in _NUMBER_OF.finditer(query):
        prefix_words = [value.casefold() for value in _WORD.findall(query[: match.start()])]
        if not prefix_words or prefix_words[-1] in _COUNT_HEAD_PREDECESSORS:
            spans.append((match.start(), match.end()))
    return tuple(sorted(set(spans)))


def has_count_intent(query: str) -> bool:
    """Whether the query asks for the cardinality of a collection."""

    return bool(count_intent_spans(query))


def strip_count_intent(query: str) -> str:
    """Remove recognized count cues while preserving identifier attributes."""

    spans = count_intent_spans(query)
    if not spans:
        return query
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(query[cursor:start])
        parts.append(" ")
        cursor = end
    parts.append(query[cursor:])
    return "".join(parts)


__all__ = ["count_intent_spans", "has_count_intent", "strip_count_intent"]
