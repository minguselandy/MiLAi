"""Candidate fusion, identity, ranking, and diversity helpers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from milai.application.acquisition import rank_evidence_turns
from milai.application.retrieval_core.policy import _retrieval_policy
from milai.persistence.retrieval_repository import (
    RetrievalCandidate,
    evidence_query_terms,
)

_QUANTITY_QUESTION = re.compile(r"\bhow\s+(many|much|long)\b", re.IGNORECASE)
_QUANTITY_VALUE = re.compile(
    r"(?:[$€£]\s*\d)|(?:\b\d+(?:\.\d+)?\b)|"
    r"(?:\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\b)|"
    r"(?:\b(?:over|under|about|nearly|almost)\s+(?:a|an|one)\s+"
    r"(?:day|week|month|year)s?\b)",
    re.IGNORECASE,
)
_DURATION_VALUE = re.compile(
    r"\b(?:over|under|about|nearly|almost)\s+(?:a|an|one)\s+"
    r"(?:day|week|month|year)s?\b|\b\d+(?:\.\d+)?\s+"
    r"(?:day|week|month|year)s?\b",
    re.IGNORECASE,
)


def _merge_candidates(
    groups: list[list[RetrievalCandidate]],
    limit: int,
    *,
    source_weights: dict[str, float] | None = None,
) -> tuple[list[RetrievalCandidate], dict[UUID, list[str]]]:
    """Fuse already-filtered lanes with deterministic weighted reciprocal rank fusion."""
    weights = source_weights or _retrieval_policy("")[0]
    rrf_constant = 10
    contributions: dict[UUID, list[float]] = {}
    sources: dict[UUID, set[str]] = {}
    for group in groups:
        for rank, candidate in enumerate(group):
            weighted = weights[candidate.source] / (rrf_constant + rank + 1)
            contributions.setdefault(candidate.claim_version_id, []).append(weighted)
            sources.setdefault(candidate.claim_version_id, set()).add(candidate.source)
    scores = {version_id: sum(values) for version_id, values in contributions.items()}
    ranked = [
        RetrievalCandidate(version_id, score, "canonical")
        for version_id, score in scores.items()
    ]
    ranked.sort(key=lambda candidate: (-candidate.score, str(candidate.claim_version_id)))
    ranked = ranked[:limit]
    return ranked, {version_id: sorted(values) for version_id, values in sources.items()}


def _deduplicate_evidence(
    evidence_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in evidence_results:
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str) and evidence_id:
            unique.setdefault(evidence_id, item)
    return list(unique.values())


def _diversify_evidence_by_subject(
    evidence_results: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Round-robin ranked sessions before the conservative context byte cap.

    The projection returns complete turns from each ranked session.  Keeping that
    session-major order let early, non-matching turns from the first session use
    the whole context budget.  Anchor turns remain first within each session,
    while one turn from every higher-ranked session is considered before a second
    turn from any session.
    """

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence_results:
        subject_id = item.get("subject_id")
        if isinstance(subject_id, str) and subject_id:
            grouped[subject_id].append(item)
    if not grouped:
        return evidence_results

    def score(item: dict[str, Any]) -> float:
        value = item.get("relevance_score")
        return (
            float(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else 0.0
        )

    query_terms = set(evidence_query_terms(query))

    def coverage(item: dict[str, Any]) -> int:
        content = str(item.get("content", "")).casefold()
        content_terms = set(re.findall(r"[^\W_]+", content, re.UNICODE))
        return len(query_terms & content_terms)

    def is_user_observation(item: dict[str, Any]) -> bool:
        return str(item.get("content", "")).lstrip().casefold().startswith("user:")

    def has_quantity_answer_signal(item: dict[str, Any]) -> bool:
        question = _QUANTITY_QUESTION.search(query)
        content = str(item.get("content", ""))
        if question is None:
            return False
        if question.group(1).casefold() == "long":
            return _DURATION_VALUE.search(content) is not None
        for value in _QUANTITY_VALUE.finditer(content):
            neighborhood = content[
                max(0, value.start() - 72) : min(len(content), value.end() + 72)
            ]
            nearby_terms = set(re.findall(r"[^\W_]+", neighborhood.casefold(), re.UNICODE))
            if query_terms & nearby_terms:
                return True
        return False

    def session_coverage(items: list[dict[str, Any]]) -> int:
        user_items = [item for item in items if is_user_observation(item)]
        return max(coverage(item) for item in (user_items or items))

    sessions = sorted(
        grouped.items(),
        key=lambda pair: (
            -session_coverage(pair[1]),
            -max(score(item) for item in pair[1]),
            pair[0],
        ),
    )
    ordered_groups: list[list[dict[str, Any]]] = []
    for _subject_id, items in sessions:
        ordered_groups.append(
            sorted(
                items,
                key=lambda item: (
                    item.get("anchor_match") is not True,
                    not is_user_observation(item),
                    not has_quantity_answer_signal(item),
                    -coverage(item),
                    -score(item),
                    str(item.get("observed_at", "")),
                    str(item.get("source_ref", "")),
                ),
            )
        )
    diversified: list[dict[str, Any]] = []
    for ordinal in range(max(len(items) for items in ordered_groups)):
        diversified.extend(items[ordinal] for items in ordered_groups if ordinal < len(items))
    return diversified


def _rank_evidence_turns(
    evidence_results: list[dict[str, Any]],
    query: str,
    *,
    preferred_speakers: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Backward-compatible alias for the shared official acquisition ranker."""

    return rank_evidence_turns(
        evidence_results,
        query,
        preferred_speakers=preferred_speakers,
    )


def _result_identity(item: dict[str, object]) -> tuple[str, str] | None:
    claim_version_id = item.get("claim_version_id")
    if isinstance(claim_version_id, (str, UUID)) and str(claim_version_id):
        return "claim_version", str(claim_version_id)
    evidence_id = item.get("evidence_id")
    if isinstance(evidence_id, (str, UUID)) and str(evidence_id):
        return "evidence", str(evidence_id)
    return None
