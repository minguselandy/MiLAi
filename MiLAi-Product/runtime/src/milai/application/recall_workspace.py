"""Query-local soft EvidenceSet selection without Memory authority.

The workspace in this module is an ephemeral ordering aid.  It never becomes
Canonical State, a RequirementState, or a completion decision, and every input
candidate remains in the returned order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    candidate_id: str
    evidence_ids: tuple[str, ...]
    session_id: str
    region_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]
    target_hints: tuple[str, ...]
    semantic_terms: frozenset[str]
    base_rank: int
    query_overlap: int
    answer_signal: bool
    estimated_tokens: int
    protected: bool = False


@dataclass(frozen=True, slots=True)
class RecallWorkspace:
    original_query: str
    anchors_found: tuple[str, ...]
    semantic_target_hints: tuple[str, ...]
    covered_target_hints: tuple[str, ...]
    uncovered_target_hints: tuple[str, ...]
    selected_evidence_ids: tuple[str, ...]
    seen_session_ids: tuple[str, ...]
    seen_region_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecallSelection:
    ordered_candidate_ids: tuple[str, ...]
    backbone_candidate_ids: tuple[str, ...]
    promoted_candidate_ids: tuple[str, ...]
    workspace: RecallWorkspace


def marginal_evidence_order(
    original_query: str,
    semantic_target_hints: tuple[str, ...],
    candidates: tuple[RecallCandidate, ...],
    *,
    max_promotions: int = 4,
    backbone_token_budget: int | None = None,
) -> RecallSelection:
    """Promote soft target gains, then preserve the complete backbone order.

    The first relevant anchor and every protected candidate remain ahead of the
    marginal search.  A promotion must cover at least one previously unseen
    query-local hint.  Once no such gain exists, the untouched B0 order is
    appended, so a weak target decomposition cannot filter evidence.
    """

    target_hints = tuple(dict.fromkeys(semantic_target_hints))
    anchors = tuple(
        item.candidate_id
        for item in candidates
        if item.protected or item.answer_signal or item.query_overlap > 0
    )
    frontier: list[RecallCandidate] = [item for item in candidates if item.protected]
    if backbone_token_budget is not None:
        used_tokens = 0
        for item in candidates:
            if item.protected:
                continue
            if used_tokens and used_tokens + item.estimated_tokens > backbone_token_budget:
                break
            frontier.append(item)
            used_tokens += item.estimated_tokens
    else:
        seed = next(
            (
                item
                for item in candidates
                if not item.protected and (item.answer_signal or item.query_overlap > 0)
            ),
            next((item for item in candidates if not item.protected), None),
        )
        if seed is not None:
            frontier.append(seed)
    frontier = list({item.candidate_id: item for item in frontier}.values())
    backbone_ids = tuple(item.candidate_id for item in frontier)
    covered = {
        hint for item in frontier for hint in item.target_hints if hint in target_hints
    }
    seen_sessions = {item.session_id for item in frontier}
    seen_regions = {region for item in frontier for region in item.region_ids}
    seen_channels = {channel for item in frontier for channel in item.channel_ids}
    selected_terms = [item.semantic_terms for item in frontier]
    promoted: list[RecallCandidate] = []
    remaining = [item for item in candidates if item not in frontier]

    while len(promoted) < max_promotions:
        gainful = [
            item
            for item in remaining
            if set(item.target_hints).difference(covered)
        ]
        if not gainful:
            break

        def priority(item: RecallCandidate) -> tuple[object, ...]:
            new_targets = set(item.target_hints).difference(covered)
            regions = set(item.region_ids)
            channels = set(item.channel_ids)
            redundancy = max(
                (_jaccard(item.semantic_terms, terms) for terms in selected_terms),
                default=0.0,
            )
            return (
                len(new_targets),
                int(item.session_id not in seen_sessions),
                len(regions.difference(seen_regions)),
                len(channels.difference(seen_channels)),
                1.0 - redundancy,
                item.query_overlap,
                int(item.answer_signal),
                -item.estimated_tokens,
                -item.base_rank,
            )

        chosen = max(gainful, key=priority)
        promoted.append(chosen)
        frontier.append(chosen)
        remaining.remove(chosen)
        covered.update(chosen.target_hints)
        seen_sessions.add(chosen.session_id)
        seen_regions.update(chosen.region_ids)
        seen_channels.update(chosen.channel_ids)
        selected_terms.append(chosen.semantic_terms)

    frontier_ids = {item.candidate_id for item in frontier}
    ordered = [*frontier, *(item for item in candidates if item.candidate_id not in frontier_ids)]
    workspace = RecallWorkspace(
        original_query=original_query,
        anchors_found=anchors,
        semantic_target_hints=target_hints or (original_query.strip(),),
        covered_target_hints=tuple(hint for hint in target_hints if hint in covered),
        uncovered_target_hints=tuple(hint for hint in target_hints if hint not in covered),
        selected_evidence_ids=tuple(
            dict.fromkeys(evidence_id for item in frontier for evidence_id in item.evidence_ids)
        ),
        seen_session_ids=tuple(dict.fromkeys(item.session_id for item in frontier)),
        seen_region_ids=tuple(
            dict.fromkeys(region for item in frontier for region in item.region_ids)
        ),
    )
    return RecallSelection(
        ordered_candidate_ids=tuple(item.candidate_id for item in ordered),
        backbone_candidate_ids=backbone_ids,
        promoted_candidate_ids=tuple(item.candidate_id for item in promoted),
        workspace=workspace,
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


__all__ = [
    "RecallCandidate",
    "RecallSelection",
    "RecallWorkspace",
    "marginal_evidence_order",
]
