"""Bound, query-free cue projections and conservative metadata-only B2/B3 selectors."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date
from fractions import Fraction
from typing import Any

from milai_lab.contracts.correction_relation import (
    ChainSelectionPlan,
    EvidenceCueView,
    EvidenceSpanCandidate,
    FrozenEvidenceCue,
    MetadataChainSnapshot,
    candidate_identity,
    canonical,
    digest,
    text_sha256,
)
from milai_lab.methods.correction_evidence import chain_rag_plan, render_material

_WORDS = re.compile(r"[a-z0-9_]+")
_DATES = re.compile(r"(?<![\w.\-])\d{4}(?:-\d{2}(?:-\d{2})?)?(?![\w.\-])")
_VERSION_PREFIX = re.compile(r"\b(?:rfc|version|ver|v)\s*[:=]?\s*$", re.IGNORECASE)
_CLAUSES = re.compile(r"[^,;.!?\n]+")
_UNSAFE_TIME = {"before", "after", "since", "until", "earlier", "later", "latest", "current",
                "currently", "now",
                "no", "not", "never", "neither", "nor", "without"}
_AXES = {
    "publication": {"publish", "published", "publication", "issued"},
    "report": {"report", "reported", "reporting"},
    "verification": {"verify", "verified", "verification"},
    "effective": {"effective", "effect", "valid", "validity"},
}
_STOP = set("a an the and or of to in on at for from with by is are was were be been "
            "this that these those it its as".split())


def _date_atoms(text: str) -> list[tuple[str, int, int]]:
    found = []
    for match in _DATES.finditer(text):
        if _VERSION_PREFIX.search(text[:match.start()]):
            continue
        value = match.group()
        parts = [int(part) for part in value.split("-")]
        try:
            date(parts[0], parts[1] if len(parts) > 1 else 1,
                 parts[2] if len(parts) > 2 else 1)
        except ValueError:
            continue
        found.append((value, match.start(), match.end()))
    return found


def literal_dates(text: str) -> tuple[str, ...]:
    """Longest lexical ISO dates/months or standalone years; no month-name conversion."""
    return tuple(sorted({value for value, _, _ in _date_atoms(text)}))


def query_time_pairs(question: str) -> tuple[tuple[str, str], ...]:
    """Only one explicit axis and date per unambiguous non-comparative clause."""
    atoms = _date_atoms(question)
    pairs = set()
    for clause in _CLAUSES.finditer(question):
        text = clause.group().casefold()
        words = set(_WORDS.findall(text))
        axes = {axis for axis, values in _AXES.items() if values.intersection(words)}
        dates = [(value, start, end) for value, start, end in atoms
                 if clause.start() <= start < end <= clause.end()]
        if (len(axes) != 1 or len(dates) != 1 or _UNSAFE_TIME.intersection(words)
                or re.search(r"\bas\s+of\b", text) or "n't" in text or "n\u2019t" in text):
            continue
        pairs.add((next(iter(axes)), dates[0][0]))
    return tuple(sorted((axis, value) for axis, value in pairs if not any(
        other_axis == axis and other.startswith(value + "-")
        for other_axis, other in pairs)))


@dataclass(frozen=True)
class CompiledEvidenceMetadata:
    cues: tuple[EvidenceCueView, ...]
    metadata_sha256: str
    receipt: dict[str, Any]


def compile_cues(
    cues: tuple[FrozenEvidenceCue, ...], candidates: list[EvidenceSpanCandidate],
    sources: dict[str, dict[str, Any]], token_count: Callable[[str], int],
) -> CompiledEvidenceMetadata:
    """Check complete literal quote matches, then project only intersecting span identities.

    This validates provenance locations, not cue meaning, axis correctness or truth.
    Source DTOs are reused from the accounted query-free source index read.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    views = []
    seen: set[str] = set()
    validation_bytes = 0
    time_sources, effective_sources, scope_sources = set(), set(), set()
    for cue in cues:
        if cue.cue_id in seen:
            raise ValueError("CORRECTION_DUPLICATE_CUE")
        seen.add(cue.cue_id)
        first = cue.quote_spans[0]
        source = sources.get(first.source_ref)
        if source is None:
            raise ValueError("CORRECTION_CUE_SOURCE_UNAVAILABLE_OR_AFTER_CUTOFF")
        value = source["content"]
        body = value if type(value) is str else canonical(value)
        validation_bytes += len(body.encode())
        quote = body[first.start:first.end]
        if (source["content_sha256"] != first.source_sha256
                or text_sha256(body) != first.body_text_sha256
                or any(span.end > len(body) or body[span.start:span.end] != quote
                       or text_sha256(body[span.start:span.end]) != span.span_sha256
                       for span in cue.quote_spans)):
            raise ValueError("CORRECTION_CUE_SOURCE_SPAN_CHANGED")
        actual_ranges = []
        start = body.find(quote)
        while start != -1:
            actual_ranges.append((start, start + len(quote)))
            start = body.find(quote, start + 1)
        if sorted((span.start, span.end) for span in cue.quote_spans) != actual_ranges:
            raise ValueError("CORRECTION_CUE_ALL_QUOTE_MATCHES_REQUIRED")
        projected = tuple(candidate.candidate_id for candidate in candidates
                          if candidate.source_ref == first.source_ref
                          and any(candidate.start < span.end and candidate.end > span.start
                                  for span in cue.quote_spans))
        if not projected:
            raise ValueError("CORRECTION_CUE_NOT_INDEXED")
        partial = tuple(candidate.candidate_id for candidate in candidates
                        if candidate.candidate_id in projected
                        and not any(candidate.start <= span.start and candidate.end >= span.end
                                    for span in cue.quote_spans))
        dates = literal_dates(quote) if cue.dimension == "time" else ()
        quote_words = set(_WORDS.findall(quote.casefold()))
        quote_axes = {axis for axis, words in _AXES.items() if words.intersection(quote_words)}
        if len(dates) != 1 or (quote_axes and quote_axes != {cue.time_axis}):
            dates = ()
        if cue.time_axis is not None and dates:
            time_sources.add(first.source_ref)
            if cue.time_axis == "effective":
                effective_sources.add(first.source_ref)
        if cue.dimension == "scope":
            scope_sources.add(first.source_ref)
        views.append(EvidenceCueView(cue.cue_id, cue.dimension, cue.value, cue.provenance,
                                     cue.time_axis, dates, projected, len(projected), partial,
                                     len(actual_ranges)))
    serialized = canonical([asdict(cue) for cue in cues])
    projected_json = canonical([asdict(view) for view in views])
    identity = digest({"cues": [asdict(cue) for cue in cues],
                       "projections": [asdict(view) for view in views]})
    receipt = {
        "event": "correction_cue_index", "query_free": True, "metadata_sha256": identity,
        "cue_count": len(views), "input_logical_bytes": len(serialized.encode()),
        "input_serialized_tokens": token_count(serialized),
        "projection_logical_bytes": len(projected_json.encode()),
        "projection_serialized_tokens": token_count(projected_json),
        "quote_validation_logical_body_bytes": validation_bytes,
        "source_read_scope": "reuses accounted source index DTOs; no additional Store reads",
        "physical_io_bytes": None, "eligible_sources": len(sources),
        "date_cue_sources": len(time_sources), "effective_date_cue_sources": len(effective_sources),
        "scope_cue_sources": len(scope_sources),
        "date_cue_source_fraction": len(time_sources) / len(sources) if sources else 0.0,
        "scope_cue_source_fraction": len(scope_sources) / len(sources) if sources else 0.0,
        "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu,
        "validation": "literal source/quote binding only; semantic hypotheses remain unverified",
        "projection_semantics": "intersection only; a partial candidate contains no complete "
                                "quote occurrence; pool omissions are a separate measure",
    }
    return CompiledEvidenceMetadata(tuple(views), identity, receipt)


def scope_words(text: str) -> set[str]:
    return {word for word in _WORDS.findall(text.casefold()) if len(word) > 1 and word not in _STOP}


def temporal_scope_plan(
    snapshot: MetadataChainSnapshot, *, evidence_budget: int,
    token_count: Callable[[str], int],
) -> tuple[ChainSelectionPlan, dict[str, Any]]:
    baseline = chain_rag_plan(snapshot, evidence_budget=evidence_budget, token_count=token_count)
    order = tuple(decision.group_id for decision in baseline.group_cost_decisions)
    groups = {group.group_id: group for group in snapshot.groups}
    time_pairs = query_time_pairs(snapshot.query.question)
    question_scope = scope_words(snapshot.query.question)
    features = {}
    for group_id in order:
        members = set(groups[group_id].candidate_ids)
        visible = [cue for cue in snapshot.cue_projections
                   if members.intersection(cue.candidate_ids)]
        time_matches: set[tuple[str, str]] = set()
        overlap = Fraction(0)
        for cue in visible:
            if cue.dimension == "time":
                time_matches.update((axis, value) for axis, value in time_pairs
                                    if axis == cue.time_axis and any(
                                        len(literal) >= len(value) and literal.startswith(value)
                                        for literal in cue.date_literals))
            if cue.dimension == "scope":
                words = scope_words(cue.value)
                union = words | question_scope
                if union:
                    overlap = max(overlap, Fraction(len(words & question_scope), len(union)))
        features[group_id] = (len(time_matches), overlap)
    ranked = tuple(sorted(order, key=lambda gid: (-features[gid][0], -features[gid][1],
                                                 order.index(gid))))
    fallback = all(time_score == 0 and overlap == 0 for time_score, overlap in features.values())
    if fallback or ranked == order:
        plan = baseline
    else:
        plan = chain_rag_plan(snapshot, evidence_budget=evidence_budget, token_count=token_count,
                              group_priority=ranked)
    if not fallback:
        plan = replace(plan, strategy="temporal_scope_chain_v1")
    diagnostics = {
        "requested_method": "temporal_scope_chain_v1", "effective_method": plan.strategy,
        "fallback_to_b1": fallback, "fallback_reason": "all_group_T_L_zero" if fallback else None,
        "reordered": ranked != order,
        "same_selected_ids_as_b1": plan.selected_ids == baseline.selected_ids,
        "b1_group_order": order, "method_group_order": ranked,
        "question_axis_date_pairs": time_pairs,
        "group_features": [{"group_id": gid, "T": features[gid][0],
                            "L_numerator": features[gid][1].numerator,
                            "L_denominator": features[gid][1].denominator,
                            "b1_rank": rank} for rank, gid in enumerate(order)],
    }
    return plan, diagnostics


def slot_retrieve_plan(
    snapshot: MetadataChainSnapshot, *, evidence_budget: int,
    token_count: Callable[[str], int],
) -> tuple[ChainSelectionPlan, dict[str, Any]]:
    baseline = chain_rag_plan(snapshot, evidence_budget=evidence_budget, token_count=token_count)
    dimensions = {candidate_identity(candidate): {
        cue.dimension for cue in snapshot.cue_projections
        if candidate_identity(candidate) in cue.candidate_ids} for candidate in snapshot.candidates}
    fallback = not any(dimensions.values())
    ranked = sorted(snapshot.candidates, key=lambda candidate: -Fraction(
        len(dimensions[candidate_identity(candidate)]), max(1, candidate.unit_tokens)))
    if fallback:
        plan = baseline
    else:
        selected, omitted = [], []
        used = token_count(render_material([]))
        for candidate in ranked:
            key = candidate_identity(candidate)
            if used + candidate.unit_tokens <= evidence_budget:
                selected.append(key)
                used += candidate.unit_tokens
            else:
                omitted.append(key)
        plan = ChainSelectionPlan(
            snapshot.snapshot_sha256, tuple(selected), tuple(omitted),
            evidence_budget, used, "slot_retrieve_v1",
            complete_group_ids=(), incomplete_group_ids=tuple(group.group_id for group in
                                                               snapshot.groups),
            group_cost_decisions=())
    diagnostics = {
        "requested_method": "slot_retrieve_v1", "effective_method": plan.strategy,
        "fallback_to_b1": fallback, "fallback_reason": "all_candidate_d_zero" if fallback else None,
        "reordered": tuple(candidate_identity(c) for c in ranked)
        != tuple(candidate_identity(c) for c in snapshot.candidates) if not fallback else False,
        "same_selected_ids_as_b1": plan.selected_ids == baseline.selected_ids,
        "candidate_features": [{"candidate_id": candidate_identity(candidate),
                                "dimensions": tuple(sorted(
                                    dimensions[candidate_identity(candidate)])),
                                "d": len(dimensions[candidate_identity(candidate)]),
                                "cost_denominator": max(1, candidate.unit_tokens)}
                               for candidate in snapshot.candidates],
    }
    return plan, diagnostics
