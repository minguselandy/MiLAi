"""Deterministic relation readiness for ordinary grounded lookups."""

from __future__ import annotations

import re
from typing import Literal

LookupRelationReadiness = Literal[
    "READY",
    "QUESTION_PARAPHRASE",
    "NON_ASSERTIVE_INTENTION",
    "RELATION_UNPROVEN",
]

_QUESTION_PREFIX = re.compile(
    r"^\s*(?:assistant\s*:\s*|user\s*:\s*)?"
    r"(?:who|what|when|where|which|why|how|do|does|did|is|are|was|were|"
    r"can|could|would|should|will)\b",
    re.IGNORECASE,
)
_QUESTION_ZH = re.compile(
    "(?:什么|谁|哪(?:里|儿|个)?|何时|几时|怎么|为何|为什么)"
)
_INTENTION = re.compile(
    r"\b(?:want(?:ed)?\s+to|plan(?:ned|ning)?\s+to|consider(?:ed|ing)?|"
    r"hope(?:d|ing)?\s+to|intend(?:ed|ing)?\s+to|would\s+like\s+to|"
    r"might|maybe|perhaps|possibly)\b|(?:想要|想去|计划|打算|考虑|希望|也许|可能)",
    re.IGNORECASE,
)
_ASSERTIVE_RELATION = re.compile(
    r"\b(?:am|is|are|was|were|became?|becomes?|have|has|had|live[ds]?|"
    r"stay(?:ed|s)?|bought|got|(?:pre[- ]?)?approved|chose|selected|"
    r"use[ds]?|lead|manage[ds]?|"
    r"work(?:ed|s)?|named|called|cost|paid|wear|wore)\b|"
    r"(?:是|为|叫|住在|位于|有|买了|选择了|用了|使用|带领|管理|花了|支付了)",
    re.IGNORECASE,
)


def classify_lookup_relation(text: str) -> LookupRelationReadiness:
    """Classify only whether one exact span asserts an ordinary relation."""

    stripped = text.strip()
    if not stripped:
        return "RELATION_UNPROVEN"
    is_question = (
        stripped.endswith(("?", "\uFF1F"))
        or _QUESTION_PREFIX.search(stripped)
        or _QUESTION_ZH.search(stripped)
    )
    if is_question:
        return "QUESTION_PARAPHRASE"
    if _INTENTION.search(stripped):
        return "NON_ASSERTIVE_INTENTION"
    if _ASSERTIVE_RELATION.search(stripped) is None:
        return "RELATION_UNPROVEN"
    return "READY"


__all__ = ["LookupRelationReadiness", "classify_lookup_relation"]
