"""Explicit transitional EvidenceAtom v0.1 compatibility alias.

New DG-17 code owns source spans, interpretations, and bindings separately in
``evidence_semantics``.  This module exists only for v0.1 internal consumers
during the matched transition; it never assigns a requirement slot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from milai.application.evidence_semantics import (
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.memory_query_ir import EvidenceAtom, EvidenceEventTime, EvidenceTextSpan
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import EvidenceRequirementV02

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset(
    {"a", "an", "and", "at", "for", "from", "in", "of", "on", "the", "to"}
)


def evidence_requirement_queries(plan: QueryPlan) -> tuple[str, ...]:
    """Build one label-free acquisition query per v0.2 required binding."""

    query_ir = plan.memory_query_ir
    if query_ir is None or query_ir.mode == "AMBIGUOUS":
        return ()
    queries: list[str] = []
    for requirement in query_ir.requirements:
        if not requirement.required:
            continue
        normalized = evidence_requirement_query(requirement)
        if normalized:
            queries.append(normalized)
    return tuple(queries)


def evidence_requirement_query(requirement: EvidenceRequirementV02) -> str:
    """Compile only requirement-owned surface terms into a raw-FTS cue."""

    return " ".join(_unique_terms(requirement.entity_constraints))


def project_evidence_atoms(
    plan: QueryPlan,
    evidence: Sequence[Mapping[str, Any]],
) -> list[EvidenceAtom]:
    """Translate independent interpretations to the legacy Atom DTO.

    ``plan`` is accepted for signature compatibility only.  RequirementBinding
    is deliberately not read or embedded, so one Atom cannot claim a slot.
    """

    del plan
    spans = project_evidence_spans(evidence)
    span_by_id = {span.span_id: span for span in spans}
    atoms: list[EvidenceAtom] = []
    for interpretation in interpret_evidence_spans(spans):
        span = span_by_id[interpretation.span_id]
        event_time = interpretation.event_time
        atoms.append(
            EvidenceAtom(
                atom_id=interpretation.interpretation_id.replace(
                    "interpretation:", "atom:", 1
                ),
                source_evidence_id=span.source_evidence_id,
                source_turn_ref=span.source_turn_ref,
                session_id=span.session_id,
                speaker=span.speaker,
                text_span=EvidenceTextSpan(
                    start=span.start,
                    end=span.end,
                    text=span.text,
                ),
                atom_type=interpretation.kind,
                entities=list(interpretation.entities),
                predicate=interpretation.predicate,
                value=interpretation.value,
                unit=interpretation.unit,
                event_time=EvidenceEventTime(
                    start=event_time.start if event_time is not None else None,
                    end=event_time.end if event_time is not None else None,
                    normalized_from=(
                        event_time.normalized_from if event_time is not None else None
                    ),
                    resolution_confidence=None,
                ),
                source_timestamp=span.source_timestamp,
                extractor_identity="evidence-atom-v01-compat-from-interpretation-v1",
                projection_epoch="query-time-v0.2-compat",
                provenance={
                    **span.provenance,
                    "time_basis": interpretation.time_basis,
                    "interpretation_id": interpretation.interpretation_id,
                    "compatibility_alias": True,
                    "requirement_binding_embedded": False,
                },
            )
        )
    return atoms


def atom_source_span_valid(atom: EvidenceAtom, source_content: str) -> bool:
    span = atom.text_span
    return span.end <= len(source_content) and source_content[span.start : span.end] == span.text


def _unique_terms(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for value in _WORD.findall(raw.casefold()):
            if value not in _STOPWORDS and value not in seen:
                seen.add(value)
                result.append(value)
    return result


__all__ = [
    "atom_source_span_valid",
    "evidence_requirement_queries",
    "evidence_requirement_query",
    "project_evidence_atoms",
]
