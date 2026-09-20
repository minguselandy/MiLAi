"""Pure Retrieval policy and deadline helpers."""

from __future__ import annotations

import re
from time import perf_counter

from milai.application.memory_access import MemoryAccessPlan
from milai.domain.retrieval import QueryPlan
from milai.persistence import DatabaseStatementTimeout

_RECENT_RETRIEVAL_INTENT = re.compile(
    r"\b(?:latest|last|recent|recently|newest|new|since|before|after|ago|"
    r"started|changed|current|currently|now)\b",
    re.IGNORECASE,
)
_STATE_COUNT_RETRIEVAL_INTENT = re.compile(
    r"\bhow many\b.*(?:\b(?:have|has)\b|\bdo\s+i\s+(?:have|own)\b|"
    r"\bare\s+there\b|\bso far\b)",
    re.IGNORECASE,
)
_PREFERENCE_RETRIEVAL_INTENT = re.compile(
    r"\b(?:prefer|preference|favorite|favourite|like|dislike|avoid|usually|"
    r"dietary|allerg|constraint)\w*\b",
    re.IGNORECASE,
)
_ASSISTANT_RETRIEVAL_INTENT = re.compile(
    r"\b(?:you|your)\b.*\b(?:recommend|suggest|tell|told|answer|advice|said)\w*\b|"
    r"\b(?:recommend|suggest|advice)\w*\b.*\b(?:you|your)\b",
    re.IGNORECASE,
)
_MULTI_RETRIEVAL_INTENT = re.compile(
    r"\b(?:how many|total|combined|all|both|between|compare|since|before|after)\b",
    re.IGNORECASE,
)


def _retrieval_policy(query: str) -> tuple[dict[str, float], bool, bool]:
    weights = {
        "l0": 1.0,
        "exact": 1.0,
        "canonical": 1.0,
        "fts": 1.0,
        "vector": 0.4,
        "recent": 0.7,
    }
    if _PREFERENCE_RETRIEVAL_INTENT.search(query):
        weights["vector"] = 1.0
    elif _ASSISTANT_RETRIEVAL_INTENT.search(query):
        weights["vector"] = 0.8
    return (
        weights,
        (
            _RECENT_RETRIEVAL_INTENT.search(query) is not None
            or _STATE_COUNT_RETRIEVAL_INTENT.search(query) is not None
        ),
        _MULTI_RETRIEVAL_INTENT.search(query) is not None,
    )


def _candidate_pool_floor(plan: QueryPlan, multi_intent: bool) -> int:
    temporal_operator = plan.operator in {"TEMPORAL_BEFORE_AFTER", "TEMPORAL_DISTANCE"}
    return 30 if multi_intent or temporal_operator else 12


def _remaining_timeout_ms(access_plan: MemoryAccessPlan | None, started: float) -> int | None:
    if access_plan is None:
        return None
    elapsed_ms = (perf_counter() - started) * 1_000
    remaining = access_plan.deadline_ms - elapsed_ms
    if remaining <= 0:
        raise DatabaseStatementTimeout("search deadline exhausted")
    return max(1, int(remaining))


def _deadline_exhausted(access_plan: MemoryAccessPlan, started: float) -> bool:
    return (perf_counter() - started) * 1_000 >= access_plan.deadline_ms
