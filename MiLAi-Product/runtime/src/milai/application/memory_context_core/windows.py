"""Evidence-window construction and deterministic ordering."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any, cast

from milai.application.memory_context_core.activation import (
    _QUERY_STOPWORDS,
    _TERM,
    _structured_source_context,
)
from milai.application.memory_context_core.common import _estimated_tokens, _sha256
from milai.application.memory_context_core.rendering import _render_context
from milai.application.recall_workspace import RecallCandidate, marginal_evidence_order
from milai.domain.memory_context import (
    ContextExpansion,
    EvidenceView,
    MemoryContextWindow,
)
from milai.domain.reader_evidence_plan import ReaderEvidenceUnit

_WORKSPACE_WRAPPER_TERMS = frozenset(
    {
        "answer",
        "concisely",
        "date",
        "governed",
        "have",
        "memory",
        "only",
        "operation",
        "provided",
        "reference",
        "supplied",
        "using",
    }
)
_SOFT_WINDOW_TOKEN_CAP = 2_048
_SOFT_SESSION_DIVERSITY_PREFIX = 4


def _build_windows(
    views: list[EvidenceView],
    *,
    required_evidence_ids: list[str],
    required_source_refs: list[str],
    session_landmark_pairing: bool = False,
    optional_member_token_cap: int | None = None,
) -> list[MemoryContextWindow]:
    required_ids = set(required_evidence_ids)
    required_refs = set(required_source_refs)
    grouped: defaultdict[str, list[EvidenceView]] = defaultdict(list)
    for view in views:
        grouped[view.session_id].append(view)
    for group in grouped.values():
        group.sort(key=lambda value: (_turn_sort(value), value.source_rank))

    ranked = sorted(
        views,
        key=lambda value: (
            not (value.evidence_id in required_ids or value.source_turn_ref in required_refs),
            not value.answer_signal,
            not value.anchor_match,
            -value.query_overlap,
            -(value.relevance_score or 0.0),
            value.source_rank,
            value.source_turn_ref,
        ),
    )
    consumed: set[str] = set()
    windows: list[MemoryContextWindow] = []
    for anchor in ranked:
        if anchor.evidence_id in consumed:
            continue
        selected = [anchor]
        landmark = (
            _session_landmark(anchor, grouped[anchor.session_id])
            if session_landmark_pairing
            else None
        )
        expansions: list[ContextExpansion] = []
        if landmark is not None and landmark.evidence_id not in consumed:
            landmark_neighbor = _speaker_neighbor(
                landmark,
                grouped[anchor.session_id],
            )
            linked_neighbor = _linked_context_neighbor(
                anchor,
                grouped[anchor.session_id],
            )
            # Prefer query-linked and same-round context over a generic session
            # landmark.  A very long optional turn must not turn one otherwise
            # useful candidate into a window that consumes the whole Reader
            # budget.  Skipped members remain unconsumed and receive their own
            # lossless atomic window later.
            selected = _bounded_window_members(
                anchor,
                [linked_neighbor, landmark_neighbor, landmark],
                optional_member_token_cap,
            )
            if landmark_neighbor is not None and landmark_neighbor.evidence_id in {
                value.evidence_id for value in selected
            }:
                expansions.append(
                    ContextExpansion(
                        trigger="SAME_ROUND",
                        source_evidence_id=landmark.evidence_id,
                        expanded_evidence_ids=[landmark_neighbor.evidence_id],
                        cost=1,
                        coverage_delta=int(landmark_neighbor.query_overlap > 0),
                        stop_reason="EXPANDED",
                    )
                )
            if linked_neighbor is not None and linked_neighbor.evidence_id in {
                value.evidence_id for value in selected
            }:
                expansions.append(
                    ContextExpansion(
                        trigger=linked_neighbor.expansion_trigger or "ADJACENT_ROUND",
                        source_evidence_id=anchor.evidence_id,
                        expanded_evidence_ids=[linked_neighbor.evidence_id],
                        cost=1,
                        coverage_delta=int(linked_neighbor.query_overlap > 0),
                        stop_reason="EXPANDED",
                    )
                )
        else:
            neighbor = _speaker_neighbor(anchor, grouped[anchor.session_id])
            if neighbor is not None and neighbor.evidence_id not in consumed:
                selected = _bounded_window_members(
                    anchor,
                    [neighbor],
                    optional_member_token_cap,
                )
                if neighbor.evidence_id in {value.evidence_id for value in selected}:
                    expansions.append(
                        ContextExpansion(
                            trigger=neighbor.expansion_trigger or "SAME_ROUND",
                            source_evidence_id=anchor.evidence_id,
                            expanded_evidence_ids=[neighbor.evidence_id],
                            cost=1,
                            coverage_delta=int(neighbor.query_overlap > 0),
                            stop_reason="EXPANDED",
                        )
                    )
        consumed.update(value.evidence_id for value in selected)
        source_refs = [value.source_turn_ref for value in selected]
        requirement_priority = any(
            value.evidence_id in required_ids or value.source_turn_ref in required_refs
            for value in selected
        )
        text = "\n".join(f"{value.speaker}: {value.content}" for value in selected)
        windows.append(
            MemoryContextWindow(
                window_id=f"window-{_sha256(source_refs)[:20]}",
                session_id=anchor.session_id,
                evidence_ids=[value.evidence_id for value in selected],
                source_turn_refs=source_refs,
                speakers=[value.speaker for value in selected],
                observed_at=next(
                    (value.observed_at for value in selected if value.observed_at), None
                ),
                text=text,
                source_rank=min(value.source_rank for value in selected),
                query_overlap=max(value.query_overlap for value in selected),
                answer_signal=any(value.answer_signal for value in selected),
                requirement_priority=requirement_priority,
                expansions=expansions,
            )
        )
    return windows


def _bounded_window_members(
    anchor: EvidenceView,
    optional: Sequence[EvidenceView | None],
    token_cap: int | None,
) -> list[EvidenceView]:
    """Build one atomic window without letting optional context crowd out recall."""

    selected = [anchor]
    selected_ids = {anchor.evidence_id}
    for value in optional:
        if value is None or value.evidence_id in selected_ids:
            continue
        candidate = [*selected, value]
        candidate_text = "\n".join(f"{item.speaker}: {item.content}" for item in candidate)
        if token_cap is not None and _estimated_tokens(candidate_text) > token_cap:
            continue
        selected.append(value)
        selected_ids.add(value.evidence_id)
    return sorted(selected, key=lambda value: _turn_sort(value))


def _session_landmark(
    anchor: EvidenceView,
    session_views: list[EvidenceView],
) -> EvidenceView | None:
    """Return the earliest available real-session turn paired with a query anchor."""

    candidates = [view for view in session_views if view.source_context_source != "UNKNOWN"]
    return (
        min(candidates, key=lambda value: (_turn_sort(value), value.source_rank))
        if candidates
        else None
    )


def _linked_context_neighbor(
    anchor: EvidenceView,
    session_views: list[EvidenceView],
) -> EvidenceView | None:
    candidates = [
        view
        for view in session_views
        if view.evidence_id != anchor.evidence_id
        and view.expanded_from_evidence_id == anchor.evidence_id
    ]
    return (
        min(
            candidates,
            key=lambda value: (
                value.expansion_trigger != "SAME_ROUND",
                -value.query_overlap,
                value.source_rank,
                _turn_sort(value),
            ),
        )
        if candidates
        else None
    )


def _marginal_window_order(
    query: str,
    query_terms: frozenset[str],
    windows: list[MemoryContextWindow],
    items: list[dict[str, Any]],
    context_token_budget: int,
) -> tuple[list[MemoryContextWindow], dict[str, object]]:
    """Apply a soft same-pool target frontier without filtering candidates."""

    provenance = _workspace_candidate_provenance(items)
    target_hints = _workspace_target_hints(query, query_terms)
    candidates: list[RecallCandidate] = []
    for base_rank, window in enumerate(windows, start=1):
        semantic_terms = frozenset(
            term
            for term in _TERM.findall(window.text.casefold())
            if len(term) >= 3 and term not in _QUERY_STOPWORDS
        )
        regions: list[str] = []
        channels: list[str] = []
        for evidence_id in window.evidence_ids:
            evidence_regions, evidence_channels = provenance.get(evidence_id, ((), ()))
            regions.extend(evidence_regions)
            channels.extend(evidence_channels)
        candidates.append(
            RecallCandidate(
                candidate_id=window.window_id,
                evidence_ids=tuple(window.evidence_ids),
                session_id=window.session_id,
                region_ids=tuple(dict.fromkeys(regions)) or (window.window_id,),
                channel_ids=tuple(dict.fromkeys(channels)) or ("UNATTRIBUTED",),
                target_hints=tuple(hint for hint in target_hints if hint in semantic_terms),
                semantic_terms=semantic_terms,
                base_rank=base_rank,
                query_overlap=window.query_overlap,
                answer_signal=window.answer_signal,
                estimated_tokens=_estimated_tokens(window.text),
                protected=window.requirement_priority,
            )
        )
    backbone_token_budget = max(1, context_token_budget // 3)
    selection = marginal_evidence_order(
        query,
        target_hints,
        tuple(candidates),
        backbone_token_budget=backbone_token_budget,
    )
    by_id = {window.window_id: window for window in windows}
    ordered = [by_id[candidate_id] for candidate_id in selection.ordered_candidate_ids]
    workspace = selection.workspace
    trace: dict[str, object] = {
        "policy": "SOFT_TARGET_FRONTIER_WITH_B0_FALLBACK_V01",
        "candidate_count": len(candidates),
        "anchor_count": len(workspace.anchors_found),
        "semantic_target_hint_count": len(workspace.semantic_target_hints),
        "semantic_target_hint_sha256s": [
            _sha256(value) for value in workspace.semantic_target_hints
        ],
        "covered_target_hint_count": len(workspace.covered_target_hints),
        "uncovered_target_hint_count": len(workspace.uncovered_target_hints),
        "promoted_window_ids": list(selection.promoted_candidate_ids),
        "backbone_window_count": len(selection.backbone_candidate_ids),
        "backbone_estimated_token_cap": backbone_token_budget,
        "backbone_estimated_tokens": sum(
            item.estimated_tokens
            for item in candidates
            if item.candidate_id in set(selection.backbone_candidate_ids)
        ),
        "frontier_selected_evidence_count": len(workspace.selected_evidence_ids),
        "seen_session_count": len(workspace.seen_session_ids),
        "seen_region_count": len(workspace.seen_region_ids),
        "all_candidate_ids_retained": (
            set(selection.ordered_candidate_ids) == set(by_id)
            and len(selection.ordered_candidate_ids) == len(by_id)
        ),
        "hard_filter_applied": False,
        "persistent_state_created": False,
    }
    return ordered, trace


def _marginal_conditional_unit_order(
    query: str,
    query_terms: frozenset[str],
    conditional: list[ReaderEvidenceUnit],
    unit_windows: list[tuple[str, MemoryContextWindow]],
    items: list[dict[str, Any]],
    context_token_budget: int,
) -> tuple[list[ReaderEvidenceUnit], dict[str, object]]:
    """Reorder only the already-admissible same-pool Evidence units."""

    window_by_unit = dict(unit_windows)
    selectable_units = [unit for unit in conditional if unit.unit_id in window_by_unit]
    selectable_windows = [window_by_unit[unit.unit_id] for unit in selectable_units]
    ordered_windows, trace = _marginal_window_order(
        query,
        query_terms,
        selectable_windows,
        items,
        context_token_budget,
    )
    unit_by_window = {window_by_unit[unit.unit_id].window_id: unit for unit in selectable_units}
    ordered_ids = {unit.unit_id for unit in selectable_units}
    untouched = [unit for unit in conditional if unit.unit_id not in ordered_ids]
    reordered = [unit_by_window[window.window_id] for window in ordered_windows]
    return [*untouched, *reordered], {
        **trace,
        "selection_boundary": "POST_DEDUP_CONDITIONAL_ADMISSION",
        "same_pool_conditional_unit_count": len(selectable_units),
        "untouched_non_window_unit_count": len(untouched),
    }


def _workspace_candidate_provenance(
    items: list[dict[str, Any]],
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    result: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for item in items:
        evidence_id = item.get("evidence_id")
        if item.get("kind") != "EVIDENCE_OBSERVATION" or not isinstance(evidence_id, str):
            continue
        source_context = _structured_source_context(item)
        regions: list[str] = []
        if source_context is not None:
            session_id = source_context.get("session_id")
            round_id = source_context.get("round_id")
            turn_id = source_context.get("turn_id")
            if isinstance(session_id, str):
                local_region = round_id if isinstance(round_id, str) else turn_id
                if isinstance(local_region, str):
                    regions.append(f"{session_id}\0{local_region}")
        envelope = item.get("acquisition_candidate")
        envelope_values = envelope if isinstance(envelope, dict) else {}
        channel_ranks = envelope_values.get("channel_ranks")
        channels = (
            [str(value) for value in channel_ranks] if isinstance(channel_ranks, dict) else []
        )
        if isinstance(item.get("context_expansion"), dict):
            channels.append("ADJACENT_TURNS")
        result[evidence_id] = (
            tuple(dict.fromkeys(regions)),
            tuple(dict.fromkeys(channels)),
        )
    return result


def _workspace_target_hints(
    query: str,
    query_terms: frozenset[str],
) -> tuple[str, ...]:
    """Keep content-bearing query words while ignoring host framing tokens."""

    question_lines = [line.strip() for line in query.splitlines() if "?" in line]
    target_source = " ".join(question_lines) if question_lines else query
    return tuple(
        dict.fromkeys(
            term
            for term in _TERM.findall(target_source.casefold())
            if term in query_terms
            and not any(character.isdigit() for character in term)
            and term not in _WORKSPACE_WRAPPER_TERMS
        )
    )


def _order_windows(
    windows: list[MemoryContextWindow],
    multi_session_required: bool,
    *,
    token_efficient: bool = False,
) -> list[MemoryContextWindow]:
    ordered = sorted(
        windows,
        key=lambda value: (
            not value.requirement_priority,
            (_estimated_tokens(value.text) > _SOFT_WINDOW_TOKEN_CAP if token_efficient else False),
            not value.answer_signal,
            -value.query_overlap,
            _estimated_tokens(value.text) if token_efficient else 0,
            value.source_rank,
            value.window_id,
        ),
    )
    if not multi_session_required:
        return ordered
    first: list[MemoryContextWindow] = []
    remaining: list[MemoryContextWindow] = []
    seen: set[str] = set()
    for window in ordered:
        target = (
            first
            if window.session_id not in seen
            and (not token_efficient or len(first) < _SOFT_SESSION_DIVERSITY_PREFIX)
            else remaining
        )
        target.append(window)
        seen.add(window.session_id)
    return [*first, *remaining]


def _speaker_neighbor(
    anchor: EvidenceView, session_views: list[EvidenceView]
) -> EvidenceView | None:
    if (
        anchor.source_context_source == "UNKNOWN"
        or anchor.turn_ordinal is None
        or anchor.round_id is None
        or anchor.round_ordinal is None
    ):
        return None
    candidates = [
        view
        for view in session_views
        if view.evidence_id != anchor.evidence_id
        and view.source_context_source != "UNKNOWN"
        and view.turn_ordinal is not None
        and view.round_id == anchor.round_id
        and view.round_ordinal == anchor.round_ordinal
    ]
    if not candidates:
        return None
    anchor_turn_ordinal = anchor.turn_ordinal
    return min(
        candidates,
        key=lambda view: (
            view.speaker == anchor.speaker,
            abs(cast(int, view.turn_ordinal) - anchor_turn_ordinal),
            _turn_sort(view),
        ),
    )


def _turn_sort(view: EvidenceView) -> tuple[int, int, int]:
    return (
        view.round_ordinal if view.round_ordinal is not None else 2**31,
        view.turn_ordinal if view.turn_ordinal is not None else 2**31,
        view.source_rank,
    )


def _instance_preserving_window_order(
    query: str,
    query_terms: frozenset[str],
    outcome: dict[str, Any],
    derived: str | None,
    baseline_windows: list[MemoryContextWindow],
    candidate_windows: list[MemoryContextWindow],
    items: list[dict[str, Any]],
    context_token_budget: int,
) -> tuple[list[MemoryContextWindow], dict[str, object]]:
    """Protect the A0 high-rank prefix, then use a provenance-novel soft tail."""

    prefix_budget = max(1, context_token_budget * 2 // 3)
    candidate_by_id = {window.window_id: window for window in candidate_windows}
    protected_ids: list[str] = []
    protected_windows: list[MemoryContextWindow] = []
    for baseline in baseline_windows:
        candidate = candidate_by_id.get(baseline.window_id)
        if candidate is None:
            break
        rendered = _render_context(
            outcome,
            [],
            [*protected_windows, candidate],
            derived,
        )
        if _estimated_tokens(rendered) > prefix_budget:
            break
        protected_ids.append(candidate.window_id)
        protected_windows.append(candidate)

    protected_set = set(protected_ids)
    remaining = [window for window in candidate_windows if window.window_id not in protected_set]
    ordered_tail, workspace = _marginal_window_order(
        query,
        query_terms,
        remaining,
        items,
        max(1, context_token_budget - prefix_budget),
    )
    ordered = [*protected_windows, *ordered_tail]
    if {window.window_id for window in ordered} != set(candidate_by_id):
        raise AssertionError("INSTANCE_PRESERVING_ORDER_CHANGED_CANDIDATE_IDENTITY_SET")
    prefix_tokens = _estimated_tokens(_render_context(outcome, [], protected_windows, derived))
    return ordered, {
        **workspace,
        "policy": "A0_PREFIX_TWO_THIRDS_WITH_PROVENANCE_NOVEL_TAIL_V01",
        "baseline_candidate_count": len(baseline_windows),
        "candidate_count": len(candidate_windows),
        "protected_baseline_prefix_window_ids": protected_ids,
        "protected_baseline_prefix_count": len(protected_ids),
        "protected_baseline_prefix_token_cap": prefix_budget,
        "protected_baseline_prefix_estimated_tokens": prefix_tokens,
        "baseline_prefix_identity_preserved": True,
        "all_candidate_ids_retained": len(ordered) == len(candidate_by_id),
        "hard_filter_applied": False,
        "persistent_state_created": False,
    }
