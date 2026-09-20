"""Deterministic operator selection, execution, and provenance helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from milai.application.evidence_acquisition import EvidenceAcquisitionExecutionRef
from milai.application.lean_recall import lean_decision_mode
from milai.application.query_operators import (
    execute_binding_backed_query_operator,
    execute_query_operator,
)
from milai.application.retrieval_core.temporal import (
    _temporal_text,
    _temporal_timestamp,
    _temporal_tokens,
)
from milai.domain.retrieval import QueryPlan

_STATE_COUNT_VALUE = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"\d+(?:,\d{3})*)(?!\w)",
    re.IGNORECASE,
)

_COMPOUND_IDENTIFIER = re.compile(
    r"(?<![\w-])[^\W_]+(?:-[^\W_]+)+(?![\w-])",
    re.UNICODE,
)


def _explicit_compound_subject_matches(
    query: str,
    claim: Mapping[str, Any],
) -> bool:
    """Reject a shorter canonical subject hidden inside a named compound.

    Token search intentionally decomposes identifiers so that ordinary recall
    remains forgiving.  Once both the query and a canonical Claim carry a
    compound identifier, however, the full identifier is an explicit address:
    ``outside-orchid-release`` must not resolve ``orchid-release`` merely
    because all of the shorter subject's words occur inside it.
    """

    subject = claim.get("subject_id")
    if not isinstance(subject, str) or "-" not in subject:
        return True
    explicit = {
        match.group(0).casefold()
        for match in _COMPOUND_IDENTIFIER.finditer(query)
    }
    normalized_subject = subject.casefold()
    if normalized_subject in explicit:
        return True
    return not any(
        identifier.startswith(f"{normalized_subject}-")
        or identifier.endswith(f"-{normalized_subject}")
        or f"-{normalized_subject}-" in identifier
        for identifier in explicit
    )


def _state_count_cover(
    candidates: list[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    """Keep the newest strong scalar-state evidence in the visible Top-k.

    Cross-encoders favor verbose lexical matches and can rank an older value
    above a terse update.  We still let the reranker bound the candidate set,
    then reserve one slot for the newest candidate whose numeric line has
    nearly the best query-term coverage.
    """
    if limit <= 0 or not candidates:
        return []
    query_tokens = _temporal_tokens(query)
    evidence: list[tuple[int, datetime, int]] = []
    for index, candidate in enumerate(candidates):
        timestamp = _temporal_timestamp(candidate)
        if timestamp is None:
            continue
        text = _temporal_text(candidate)
        best_overlap = max(
            (
                len(query_tokens.intersection(_temporal_tokens(line)))
                for line in text.splitlines()
                if _STATE_COUNT_VALUE.search(line) is not None
                and not re.match(r"^\s*assistant:\s*\d+\.\s*$", line, re.IGNORECASE)
            ),
            default=0,
        )
        if best_overlap > 0:
            evidence.append((best_overlap, timestamp, index))
    if not evidence:
        return candidates[:limit]
    best_overlap = max(item[0] for item in evidence)
    minimum_overlap = max(1, best_overlap - 1)
    eligible = [item for item in evidence if item[0] >= minimum_overlap]
    _overlap, _timestamp, selected_index = max(
        eligible, key=lambda item: (item[1], item[0], -item[2])
    )
    priority = [selected_index]
    priority.extend(index for index in range(len(candidates)) if index != selected_index)
    return [candidates[index] for index in priority[:limit]]


def _execute_operator_with_accepted_inputs(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    execution: EvidenceAcquisitionExecutionRef | None,
) -> dict[str, Any] | None:
    canonical_results = [
        item for item in results if item.get("claim_version_id") is not None
    ]
    if lean_decision_mode(plan) == "ORDINARY_RECALL":
        if not canonical_results:
            # Raw natural language remains Reader context.  QueryIR planning
            # cannot promote it to a deterministic operand merely because a
            # lexical or model interpretation matched the question.
            return None
        canonical_result = execute_query_operator(plan, canonical_results)
        if canonical_result is None:
            return None
        return {
            **canonical_result,
            "operand_authority": "CANONICAL_GATE_ONLY",
        }
    if execution is None:
        return execute_binding_backed_query_operator(
            plan,
            results,
            (),
            (),
            (),
        )
    return execute_binding_backed_query_operator(
        plan,
        results,
        execution.spans,
        execution.interpretations,
        execution.bindings,
    )


def _operator_support_refs(
    derived_result: Mapping[str, Any] | None,
) -> tuple[set[str], set[str]]:
    """Collect only explicit operator provenance, never arbitrary string values."""

    evidence_ids: set[str] = set()
    source_refs: set[str] = set()

    def collect(value: Mapping[str, Any]) -> None:
        for key in (
            "evidence_id",
            "source_evidence_id",
        ):
            raw = value.get(key)
            if isinstance(raw, str) and raw:
                evidence_ids.add(raw)
        for key in (
            "evidence_ids",
            "evidence_refs",
            "source_evidence_ids",
        ):
            raw = value.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                evidence_ids.update(item for item in raw if isinstance(item, str) and item)
        for key in ("source_ref", "source_turn_ref"):
            raw = value.get(key)
            if isinstance(raw, str) and raw:
                source_refs.add(raw)
        for key in ("source_refs", "source_turn_refs"):
            raw = value.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                source_refs.update(item for item in raw if isinstance(item, str) and item)
        operands = value.get("operands")
        if isinstance(operands, Sequence) and not isinstance(operands, (str, bytes)):
            for operand in operands:
                if isinstance(operand, Mapping):
                    collect(operand)

    if derived_result is not None and derived_result.get("canonical_mutation") is not True:
        collect(derived_result)
    return evidence_ids, source_refs
