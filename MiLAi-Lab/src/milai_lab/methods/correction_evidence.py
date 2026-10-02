"""Opt-in ordered source and relation-group selection with complete evidence packing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import Any

from milai_lab.contracts.correction_relation import (
    ChainDeliveryReceipt,
    ChainGroupCostDecision,
    ChainResearchSnapshot,
    ChainSelectionPlan,
    DeliveredEvidenceSpan,
    DeliveredSpan,
    DeliveryReceipt,
    EvidenceSpanCandidate,
    ResearchSnapshot,
    SelectionPlan,
    candidate_identity,
    canonical,
    text_sha256,
)


def source_unit(
    source_ref: str, role: str, observed_at: str, body: str, *, start: int = 0,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    result = {"source_ref": source_ref, "role": role, "observed_at": observed_at,
              "range": [start, start + len(body)], "content": body}
    if candidate_id is not None:
        result["candidate_id"] = candidate_id
    return result


def render_material(units: list[dict[str, Any]]) -> str:
    return canonical({"schema": "correction_source_material_v1", "sources": units})


def ordered_source_plan(
    snapshot: ResearchSnapshot, *, evidence_budget: int, token_count: Callable[[str], int],
) -> SelectionPlan:
    """No content parsing: use frozen unit costs and retain common retrieval order.

    Per-unit costs are a planning estimate; concatenation can change tokenizer merges.
    The common packer separately enforces the exact final material token budget.
    """
    if type(evidence_budget) is not int or evidence_budget <= 0:
        raise ValueError("CORRECTION_EVIDENCE_BUDGET_INVALID")
    used = token_count(render_material([]))
    if used > evidence_budget:
        raise ValueError("CORRECTION_METADATA_EXCEEDS_BUDGET")
    selected, omitted = [], []
    for candidate in snapshot.candidates:
        if used + candidate.unit_tokens <= evidence_budget:
            selected.append(candidate_identity(candidate))
            used += candidate.unit_tokens
        else:
            omitted.append(candidate_identity(candidate))
    return SelectionPlan(snapshot.snapshot_sha256, tuple(selected), tuple(omitted),
                         evidence_budget, used)


def chain_rag_plan(
    snapshot: ChainResearchSnapshot, *, evidence_budget: int,
    token_count: Callable[[str], int],
) -> ChainSelectionPlan:
    """Prefer whole actual relation components; preserve explicit partial-chain failures.

    A first complete group uses its exact query-free rendered cost, avoiding a
    systematic rejection from summing per-span wrappers. Later concatenations use
    an estimate and are checked atomically by the common material packer.
    """
    if type(evidence_budget) is not int or evidence_budget <= 0:
        raise ValueError("CORRECTION_EVIDENCE_BUDGET_INVALID")
    empty_cost = token_count(render_material([]))
    if empty_cost > evidence_budget:
        raise ValueError("CORRECTION_METADATA_EXCEEDS_BUDGET")
    pool = {candidate_identity(candidate): candidate for candidate in snapshot.candidates}
    by_member = {key: group for group in snapshot.groups for key in group.candidate_ids}
    groups, seen = [], set()
    for seed in (*snapshot.ordinary_seed_ids, *pool):
        group = by_member[seed]
        if group.group_id not in seen:
            groups.append(group)
            seen.add(group.group_id)
    selected: list[str] = []
    complete, incomplete = [], []
    decisions = []
    used = empty_cost
    for group in groups:
        available = [key for key in group.candidate_ids if key in pool]
        estimated = (group.material_tokens if not selected else
                     used + max(0, group.material_tokens - empty_cost) + token_count(","))
        available_in_pool = len(available) == len(group.candidate_ids)
        selected_as_complete = available_in_pool and estimated <= evidence_budget
        decisions.append(ChainGroupCostDecision(
            group.group_id, available_in_pool, group.material_tokens, estimated,
            selected_as_complete))
        if selected_as_complete:
            selected.extend(available)
            complete.append(group.group_id)
            used = estimated
            continue
        incomplete.append(group.group_id)
        for key in available:
            if used + pool[key].unit_tokens <= evidence_budget:
                selected.append(key)
                used += pool[key].unit_tokens
    return ChainSelectionPlan(
        snapshot.snapshot_sha256, tuple(selected),
        tuple(key for key in pool if key not in selected),
        evidence_budget, used, "chain_rag_v1", complete_group_ids=tuple(complete),
        incomplete_group_ids=tuple(incomplete), group_cost_decisions=tuple(decisions))


def pack_complete(
    snapshot: ResearchSnapshot, plan: SelectionPlan, units: list[dict[str, Any]], *,
    token_count: Callable[[str], int],
) -> tuple[str, DeliveryReceipt]:
    """Never truncate, reorder, silently reread, or substitute an omitted source."""
    pool = {candidate_identity(c): c for c in snapshot.candidates}
    if (plan.snapshot_sha256 != snapshot.snapshot_sha256
            or type(plan.evidence_budget) is not int or plan.evidence_budget <= 0
            or [unit.get("candidate_id", unit.get("source_ref")) for unit in units]
            != list(plan.selected_ids)
            or len(set(plan.selected_ids)) != len(plan.selected_ids)
            or len(set(plan.omitted_ids)) != len(plan.omitted_ids)
            or set(plan.selected_ids) & set(plan.omitted_ids)
            or set(plan.selected_ids) | set(plan.omitted_ids) != set(pool)
            or (not isinstance(plan, ChainSelectionPlan)
                and tuple(ref for ref in pool if ref in plan.selected_ids) != plan.selected_ids)):
        raise ValueError("CORRECTION_SELECTION_BINDING_CHANGED")
    if isinstance(plan, ChainSelectionPlan) and not isinstance(snapshot, ChainResearchSnapshot):
        raise ValueError("CORRECTION_CHAIN_SNAPSHOT_REQUIRED")
    chosen: list[dict[str, Any]] = []
    spans: list[DeliveredSpan] = []
    span_by_id = {}
    for unit in units:
        candidate = pool[unit.get("candidate_id", unit["source_ref"])]
        body = unit.get("content")
        is_span = isinstance(candidate, EvidenceSpanCandidate)
        start, end = (0, candidate.codepoints)
        expected_sha = candidate.body_text_sha256
        if isinstance(candidate, EvidenceSpanCandidate):
            start, end, expected_sha = candidate.start, candidate.end, candidate.span_sha256
        if (type(body) is not str or text_sha256(body) != expected_sha
                or len(body) != end - start
                or unit != source_unit(candidate.source_ref, candidate.role,
                                       candidate.observed_at, body, start=start,
                                       candidate_id=candidate_identity(candidate)
                                       if is_span else None)):
            raise ValueError("CORRECTION_SELECTED_BODY_CHANGED")
        identity = (candidate.source_ref, candidate.source_sha256, candidate.body_text_sha256,
                    start, end, text_sha256(body))
        span_by_id[candidate_identity(candidate)] = (
            DeliveredEvidenceSpan(*identity, candidate_id=candidate_identity(candidate))
            if is_span else DeliveredSpan(*identity))
    unit_by_id = {unit.get("candidate_id", unit["source_ref"]): unit for unit in units}
    atomic = {}
    if isinstance(plan, ChainSelectionPlan) and isinstance(snapshot, ChainResearchSnapshot):
        known_groups = {group.group_id: group for group in snapshot.groups}
        for group_id in plan.complete_group_ids:
            if group_id not in known_groups:
                raise ValueError("CORRECTION_CHAIN_GROUP_INVALID")
            ids = known_groups[group_id].candidate_ids
            if not set(ids) <= set(plan.selected_ids):
                raise ValueError("CORRECTION_CHAIN_GROUP_INCOMPLETE")
            position = plan.selected_ids.index(ids[0])
            if plan.selected_ids[position:position + len(ids)] != ids:
                raise ValueError("CORRECTION_CHAIN_GROUP_ORDER_CHANGED")
            atomic.update({key: ids for key in ids})
    processed: set[str] = set()
    for key in plan.selected_ids:
        if key in processed:
            continue
        bundle = atomic.get(key, (key,))
        processed.update(bundle)
        values = [unit_by_id[member] for member in bundle]
        if token_count(render_material([*chosen, *values])) <= plan.evidence_budget:
            chosen.extend(values)
            spans.extend(span_by_id[member] for member in bundle)
    material = render_material(chosen)
    tokens = token_count(material)
    if tokens > plan.evidence_budget:
        raise ValueError("CORRECTION_METADATA_EXCEEDS_BUDGET")
    delivered_ids = {span.candidate_id if isinstance(span, DeliveredEvidenceSpan)
                     else span.source_ref for span in spans}
    receipt = DeliveryReceipt(
        snapshot.snapshot_sha256, plan.selected_ids,
        tuple(u.get("candidate_id", u["source_ref"]) for u in units),
        tuple(spans), tuple(candidate_identity(c) for c in snapshot.candidates
                           if candidate_identity(c) not in delivered_ids),
        text_sha256(material), tokens, plan.evidence_budget, snapshot.tokenizer_sha256,
    )
    if isinstance(plan, ChainSelectionPlan) and isinstance(snapshot, ChainResearchSnapshot):
        receipt = ChainDeliveryReceipt(**{field.name: getattr(receipt, field.name)
                                          for field in fields(receipt)},
            complete_group_ids=tuple(group.group_id for group in snapshot.groups
                                     if set(group.candidate_ids) <= delivered_ids),
            incomplete_group_ids=tuple(group.group_id for group in snapshot.groups
                                       if not set(group.candidate_ids) <= delivered_ids),
            unclosed_relation_ids=snapshot.unclosed_relation_ids,
            group_cost_decisions=plan.group_cost_decisions,
            planning_estimated_tokens=plan.estimated_tokens,
            planning_minus_material_tokens=plan.estimated_tokens - tokens,
            packing_omitted_ids=tuple(key for key in plan.selected_ids
                                      if key not in delivered_ids))
    return material, receipt
