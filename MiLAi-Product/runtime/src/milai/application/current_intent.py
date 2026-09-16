"""Deterministic recognition of explicit first-person current intent."""

from __future__ import annotations

import re

_EXPLICIT_CURRENT_INTENT = re.compile(
    r"\b(?:"
    r"i(?:'m| am)\s+(?:currently\s+)?"
    r"(?:planning|considering|thinking|hoping|intending)\b|"
    r"i\s+(?:currently\s+)?(?:plan|intend|want|hope)\s+to\b|"
    r"i(?:'m| am)\s+(?:currently\s+)?"
    r"(?:going|travell?ing|visiting|returning)\b|"
    r"i(?:'ll| will)\s+(?:be\s+)?"
    r"(?:going|travell?ing|visiting|returning)\b|"
    r"my\s+(?:current|upcoming)\s+(?:plan|trip|visit)\b"
    r")",
    re.IGNORECASE,
)


def has_explicit_current_intent(text: str) -> bool:
    """Return true only for an explicit present/prospective first-person intent."""

    return _EXPLICIT_CURRENT_INTENT.search(text) is not None


__all__ = ["has_explicit_current_intent"]
