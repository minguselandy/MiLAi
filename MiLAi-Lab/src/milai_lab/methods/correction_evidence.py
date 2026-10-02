"""Ordered source selection and complete evidence packing; not yet Chain-RAG."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from milai_lab.contracts.correction_relation import (
    DeliveredSpan,
    DeliveryReceipt,
    ResearchSnapshot,
    SelectionPlan,
    canonical,
    text_sha256,
)


def source_unit(source_ref: str, role: str, observed_at: str, body: str) -> dict[str, Any]:
    return {"source_ref": source_ref, "role": role, "observed_at": observed_at,
            "range": [0, len(body)], "content": body}


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
            selected.append(candidate.source_ref)
            used += candidate.unit_tokens
        else:
            omitted.append(candidate.source_ref)
    return SelectionPlan(snapshot.snapshot_sha256, tuple(selected), tuple(omitted),
                         evidence_budget, used)


def pack_complete(
    snapshot: ResearchSnapshot, plan: SelectionPlan, units: list[dict[str, Any]], *,
    token_count: Callable[[str], int],
) -> tuple[str, DeliveryReceipt]:
    """Never truncate, reorder, silently reread, or substitute an omitted source."""
    pool = {c.source_ref: c for c in snapshot.candidates}
    if (plan.snapshot_sha256 != snapshot.snapshot_sha256
            or type(plan.evidence_budget) is not int or plan.evidence_budget <= 0
            or [unit.get("source_ref") for unit in units] != list(plan.selected_ids)
            or len(set(plan.selected_ids)) != len(plan.selected_ids)
            or len(set(plan.omitted_ids)) != len(plan.omitted_ids)
            or set(plan.selected_ids) & set(plan.omitted_ids)
            or set(plan.selected_ids) | set(plan.omitted_ids) != set(pool)
            or tuple(ref for ref in pool if ref in plan.selected_ids) != plan.selected_ids):
        raise ValueError("CORRECTION_SELECTION_BINDING_CHANGED")
    chosen: list[dict[str, Any]] = []
    spans = []
    for unit in units:
        candidate = pool[unit["source_ref"]]
        body = unit.get("content")
        if (type(body) is not str or text_sha256(body) != candidate.body_text_sha256
                or len(body) != candidate.codepoints
                or unit != source_unit(candidate.source_ref, candidate.role,
                                       candidate.observed_at, body)):
            raise ValueError("CORRECTION_SELECTED_BODY_CHANGED")
        if token_count(render_material([*chosen, unit])) > plan.evidence_budget:
            continue
        chosen.append(unit)
        spans.append(DeliveredSpan(candidate.source_ref, candidate.source_sha256,
                                   candidate.body_text_sha256, 0, len(body), text_sha256(body)))
    material = render_material(chosen)
    tokens = token_count(material)
    if tokens > plan.evidence_budget:
        raise ValueError("CORRECTION_METADATA_EXCEEDS_BUDGET")
    delivered_ids = {span.source_ref for span in spans}
    return material, DeliveryReceipt(
        snapshot.snapshot_sha256, plan.selected_ids, tuple(u["source_ref"] for u in units),
        tuple(spans), tuple(c.source_ref for c in snapshot.candidates
                           if c.source_ref not in delivered_ids),
        text_sha256(material), tokens, plan.evidence_budget, snapshot.tokenizer_sha256,
    )
