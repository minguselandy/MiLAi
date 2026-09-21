"""Activation, fallback snapshot, and evidence-view helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal, cast

from milai.application.evidence_source import structured_evidence_speaker
from milai.application.memory_context_core.common import (
    _estimated_tokens,
    _sha256,
    _string_values,
    _unique,
)
from milai.application.memory_context_core.provenance import _provenance_values
from milai.application.memory_context_core.semantics import (
    _query_ir_has_temporal_constraint,
    _query_ir_operator_family,
    _reader_semantic_value,
    _validated_operand,
)
from milai.application.memory_context_core.units import _render_reader_units
from milai.application.reader_evidence_plan import build_decision_snapshot
from milai.domain.memory_context import (
    EvidenceSourceContextLineage,
    EvidenceSpeaker,
    EvidenceView,
    MemoryContextWindow,
)
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    AcceptedBindingSpan,
    DecisionSnapshot,
    ReaderEvidenceUnit,
)

_TERM = re.compile(r"[^\W_]+", re.UNICODE)
_VALUE = re.compile(
    r"(?:[$€£]\s*\d)|(?:\b\d+(?:\.\d+)?\b)|"
    r"(?:\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\b)|(?:\b(?:day|week|month|year)s?\b)",
    re.IGNORECASE,
)
_MULTI_SESSION = re.compile(
    r"\b(?:both|each|across|between|compare|respectively|per\s+\w+|"
    r"how\s+many\s+(?:times|appointments?|sessions?|events?))\b",
    re.IGNORECASE,
)
_LOCAL_CONTEXT = re.compile(
    r"\b(?:same\s+(?:session|conversation|round)|adjacent\s+(?:turn|round)|"
    r"previous\s+turn|next\s+turn|conversation\s+context|"
    r"what\s+did\s+(?:you|the\s+assistant)\s+(?:say|reply|respond))\b",
    re.IGNORECASE,
)
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "am",
        "an",
        "and",
        "are",
        "as",
        "at",
        "average",
        "be",
        "been",
        "being",
        "both",
        "by",
        "compared",
        "did",
        "do",
        "does",
        "each",
        "evidence",
        "for",
        "from",
        "had",
        "has",
        "history",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "many",
        "me",
        "memory",
        "more",
        "most",
        "much",
        "my",
        "of",
        "on",
        "or",
        "our",
        "ours",
        "per",
        "previous",
        "recall",
        "that",
        "the",
        "their",
        "them",
        "they",
        "this",
        "those",
        "through",
        "to",
        "us",
        "was",
        "were",
        "what",
        "when",
        "which",
        "with",
        "you",
        "your",
    }
)


def _conditional_activation_thresholds(
    protected: list[ReaderEvidenceUnit],
    conditional: list[ReaderEvidenceUnit],
    *,
    token_counter: Callable[[str], int] | None = None,
    soft_ranked: bool = False,
) -> dict[str, int]:
    """Assign monotone admission thresholds while retaining stable render order."""

    count = token_counter or _estimated_tokens
    admitted: set[str] = set()
    previous = count(_render_reader_units(protected))
    thresholds: dict[str, int] = {}
    ordered = (
        conditional
        if soft_ranked
        else sorted(
            conditional,
            key=lambda value: (value.estimated_tokens, value.unit_id),
        )
    )
    for unit in ordered:
        admitted.add(unit.unit_id)
        selected = [
            *protected,
            *(candidate for candidate in conditional if candidate.unit_id in admitted),
        ]
        threshold = max(previous, count(_render_reader_units(selected)))
        thresholds[unit.unit_id] = threshold
        previous = threshold
    return dict(sorted(thresholds.items()))


def _admissible_conditional_gain(
    window: MemoryContextWindow,
    query: str,
    *,
    governance_admitted: bool = False,
) -> bool:
    if governance_admitted:
        return True
    if window.answer_signal or any(expansion.coverage_delta > 0 for expansion in window.expansions):
        return True
    query_folded = query.casefold()
    provenance_requested = any(
        phrase in query_folded
        for phrase in (
            "source",
            "provenance",
            "who said",
            "when did",
            "speaker",
            "conversation context",
        )
    )
    return provenance_requested and window.query_overlap > 0


def _stable_evidence_views(views: list[EvidenceView]) -> list[EvidenceView]:
    """Replace repository ordinals with deterministic semantic/source ordinals."""

    ordered = sorted(
        views,
        key=lambda view: (
            view.source_turn_ref,
            view.evidence_id,
            view.observed_at or "",
            view.speaker,
        ),
    )
    return [
        view.model_copy(update={"source_rank": ordinal})
        for ordinal, view in enumerate(ordered, start=1)
    ]


def _normalized_unit_semantics(text: str) -> str:
    return " ".join(_TERM.findall(text.casefold()))


def _breadth_first_binding_spans(snapshot: DecisionSnapshot) -> list[AcceptedBindingSpan]:
    """Order one atomic accepted span per role before same-role depth."""

    remaining = list(snapshot.accepted_binding_spans)
    selected: list[AcceptedBindingSpan] = []
    selected_keys: set[tuple[str, int, int, str]] = set()
    for requirement_id in snapshot.required_requirement_ids:
        span = next(
            (
                item
                for item in remaining
                if requirement_id in item.requirement_ids
                and (
                    item.source_turn_ref,
                    item.start,
                    item.end,
                    item.evidence_id,
                )
                not in selected_keys
            ),
            None,
        )
        if span is None:
            continue
        selected.append(span)
        selected_keys.add((span.source_turn_ref, span.start, span.end, span.evidence_id))
    selected.extend(
        item
        for item in remaining
        if (item.source_turn_ref, item.start, item.end, item.evidence_id) not in selected_keys
    )
    return selected


def _canonical_item_identity(item: dict[str, Any]) -> object:
    for key in ("claim_version_id", "claim_id", "state_key"):
        value = item.get(key)
        if value is not None:
            return {"kind": item.get("kind"), key: str(value)}
    return _reader_semantic_value(item)


def _canonical_item_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("kind", "CANONICAL_STATE")), _sha256(_canonical_item_identity(item))


def _fallback_decision_snapshot(
    request: MemoryResolveRequest,
    outcome: dict[str, Any],
    items: list[dict[str, Any]],
) -> DecisionSnapshot:
    """Build a budget-free compatibility snapshot when Retrieval has no typed one."""

    ordered_items = sorted(items, key=_candidate_item_sort_key)
    query_ir = outcome.get("memory_query_ir") or {
        "query": request.query,
        "interpretation": outcome.get("interpretation"),
    }
    search_trace = outcome.get("search_trace")
    search_values = search_trace if isinstance(search_trace, dict) else {}
    acquisition_plan = search_values.get("acquisition_plan") or {
        "identity": "COMPATIBILITY_ACQUISITION_PLAN_ABSENT"
    }
    decision = outcome.get("sufficiency_decision")
    decision_values = decision if isinstance(decision, dict) else {}
    required = _required_requirement_ids(query_ir)
    unresolved = [
        value
        for value in _string_values(decision_values.get("missing_slots"))
        if value in set(required)
    ]
    accepted_evidence_ids = sorted(
        {
            str(item["evidence_id"])
            for item in ordered_items
            if item.get("kind") == "EVIDENCE_OBSERVATION"
            and isinstance(item.get("evidence_id"), str)
        }
    )
    return build_decision_snapshot(
        source_snapshot_material={
            "canonical_position": outcome.get("canonical_position"),
            "sources": [
                {
                    "evidence_id": item.get("evidence_id"),
                    "source_ref": item.get("source_ref"),
                    "content_digest": _sha256(item.get("content")),
                }
                for item in ordered_items
                if item.get("kind") == "EVIDENCE_OBSERVATION"
            ],
        },
        query_ir_material=query_ir,
        acquisition_plan_material=_without_presentation_budget(acquisition_plan),
        candidate_snapshot_material=ordered_items,
        gate_material=[
            {
                key: item.get(key)
                for key in (
                    "evidence_id",
                    "claim_version_id",
                    "permission_snapshot",
                    "retention_state",
                    "access_decision",
                    "authority_class",
                )
                if key in item
            }
            for item in ordered_items
        ],
        binding_material={
            "semantic_audit": search_values.get("semantic_audit"),
            "derived_result": outcome.get("derived_result"),
        },
        requirement_state_material={
            "acquisition_state": search_values.get("acquisition_state"),
            "required": required,
            "unresolved": unresolved,
        },
        sufficiency_material=decision_values,
        operator_result_material=outcome.get("derived_result"),
        accepted_evidence_ids=accepted_evidence_ids,
        required_requirement_ids=required,
        unresolved_requirement_ids=unresolved,
    )


def _candidate_item_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("kind", "")),
        str(item.get("source_ref", item.get("claim_version_id", ""))),
        str(item.get("evidence_id", item.get("claim_id", ""))),
    )


def _required_requirement_ids(query_ir: object) -> list[str]:
    if not isinstance(query_ir, dict):
        return []
    requirements = query_ir.get("requirements")
    if not isinstance(requirements, list):
        return []
    return sorted(
        {
            str(item["slot_id"])
            for item in requirements
            if isinstance(item, dict)
            and item.get("required", True) is True
            and isinstance(item.get("slot_id"), str)
        }
    )


def _without_presentation_budget(value: object) -> object:
    presentation_keys = {
        "available_memory_tokens",
        "context_budget",
        "context_token_budget",
        "context_tokens",
        "max_context_tokens",
        "requested_cap",
        "token_budget",
    }
    if isinstance(value, dict):
        return {
            str(key): _without_presentation_budget(item)
            for key, item in value.items()
            if str(key) not in presentation_keys
        }
    if isinstance(value, list):
        return [_without_presentation_budget(item) for item in value]
    return value


def _local_context_activation(
    request: MemoryResolveRequest,
    outcome: dict[str, Any],
    *,
    has_reader: bool,
    has_session_context: bool,
    structured_anchor_count: int,
    query_preserving_union: bool = False,
) -> dict[str, object]:
    decision_accepted_only = outcome.get("_reader_evidence_boundary") == "DECISION_ACCEPTED_ONLY"
    decision = outcome.get("sufficiency_decision")
    decision_values = decision if isinstance(decision, dict) else {}
    missing_slots = _unique(
        str(value)
        for value in decision_values.get("missing_slots", [])
        if isinstance(value, str) and value
    )
    query_ir = outcome.get("memory_query_ir")
    operator_family = _query_ir_operator_family(query_ir)
    signals: list[str] = []
    if query_preserving_union:
        signals.append("QUERY_PRESERVING_SESSION_LOCALITY")
    if missing_slots:
        signals.append("MISSING_REQUIREMENTS")
    if request.temporal or _query_ir_has_temporal_constraint(query_ir):
        signals.append("TEMPORAL_QUERY")
    if operator_family is not None and operator_family != "LOOKUP":
        signals.append("OPERATOR_QUERY")
    if _MULTI_SESSION.search(request.query):
        signals.append("MULTI_CONTEXT_QUERY")
    if _LOCAL_CONTEXT.search(request.query):
        signals.append("EXPLICIT_LOCAL_CONTEXT_QUERY")

    eligible = (
        has_reader
        and has_session_context
        and structured_anchor_count > 0
        and not request.state_keys
        and not request.claim_ids
    )
    if decision_accepted_only:
        reason = "DECISION_ACCEPTED_ONLY"
    elif not has_reader:
        reason = "ADJACENCY_READER_UNAVAILABLE"
    elif not has_session_context:
        reason = "SESSION_CONTEXT_UNAVAILABLE"
    elif request.state_keys or request.claim_ids:
        reason = "EXACT_CURRENT_QUERY"
    elif structured_anchor_count == 0:
        reason = "NO_STRUCTURED_EVIDENCE_ANCHOR"
    elif signals:
        reason = signals[0]
    elif decision_values.get("status") == "COMPLETE":
        reason = "ALREADY_COMPLETE"
    else:
        reason = "NO_MISSING_OR_CONTEXT_REQUIREMENT"
    return {
        "eligible": eligible,
        "activated": eligible and bool(signals) and not decision_accepted_only,
        "reason": reason,
        "signals": signals,
        "missing_slots": missing_slots,
        "structured_anchor_count": structured_anchor_count,
    }


def _evidence_views(
    items: list[dict[str, Any]],
    query: str,
    query_terms: frozenset[str],
    *,
    member_enumeration: bool,
) -> list[EvidenceView]:
    views: list[EvidenceView] = []
    for rank, item in enumerate(items, start=1):
        if item.get("kind") != "EVIDENCE_OBSERVATION":
            continue
        evidence_id = item.get("evidence_id")
        source_ref = item.get("source_ref")
        content = item.get("content")
        if not all(
            isinstance(value, str) and value for value in (evidence_id, source_ref, content)
        ):
            continue
        assert isinstance(evidence_id, str)
        assert isinstance(source_ref, str)
        assert isinstance(content, str)
        raw_speaker, _speaker_source = structured_evidence_speaker(item)
        speaker = cast(EvidenceSpeaker, raw_speaker.upper())
        source_context = _structured_source_context(item)
        session_id = (
            str(source_context["session_id"])
            if source_context is not None
            else _legacy_session_identity(item, source_ref)
        )
        expansion = item.get("context_expansion")
        expanded_from = (
            str(expansion["source_evidence_id"])
            if isinstance(expansion, dict) and isinstance(expansion.get("source_evidence_id"), str)
            else None
        )
        expansion_trigger = (
            cast(str, expansion.get("trigger"))
            if isinstance(expansion, dict)
            and expansion.get("trigger") in {"SAME_ROUND", "ADJACENT_ROUND"}
            else None
        )
        body = content.strip()
        raw_score = item.get("relevance_score")
        score = (
            float(raw_score)
            if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
            else None
        )
        content_terms = frozenset(_TERM.findall(body.casefold()))
        views.append(
            EvidenceView(
                evidence_id=evidence_id,
                source_turn_ref=source_ref,
                session_id=session_id,
                turn_id=(str(source_context["turn_id"]) if source_context is not None else None),
                turn_ordinal=(
                    int(source_context["turn_ordinal"]) if source_context is not None else None
                ),
                round_id=(str(source_context["round_id"]) if source_context is not None else None),
                round_ordinal=(
                    int(source_context["round_ordinal"]) if source_context is not None else None
                ),
                previous_turn_id=(
                    cast(str | None, source_context.get("previous_turn_id"))
                    if source_context is not None
                    else None
                ),
                next_turn_id=(
                    cast(str | None, source_context.get("next_turn_id"))
                    if source_context is not None
                    else None
                ),
                source_context_source=(
                    cast(EvidenceSourceContextLineage, item["source_context_source"])
                    if source_context is not None
                    else "UNKNOWN"
                ),
                speaker=speaker,
                content=body,
                observed_at=(
                    str(item["observed_at"]) if item.get("observed_at") is not None else None
                ),
                relevance_score=score,
                source_rank=rank,
                query_overlap=len(query_terms & content_terms),
                answer_signal=_answer_signal(
                    query,
                    query_terms,
                    body,
                    member_enumeration=member_enumeration,
                ),
                anchor_match=item.get("anchor_match") is True,
                expanded_from_evidence_id=expanded_from,
                expansion_trigger=cast(
                    Literal["SAME_ROUND", "ADJACENT_ROUND"] | None,
                    expansion_trigger,
                ),
            )
        )
    return views


def _derived_operand_views(
    raw: object,
    query: str,
    query_terms: frozenset[str],
    *,
    existing_views: list[EvidenceView],
    member_enumeration: bool,
) -> list[EvidenceView]:
    """Recover exact Runtime-derived operand spans omitted from the result list."""

    if (
        not isinstance(raw, dict)
        or raw.get("canonical_mutation") is not False
        or raw.get("status") in {"ABSTAINED", "ERROR", "UNSATISFIED"}
    ):
        return []
    existing_evidence_ids = {view.evidence_id for view in existing_views}
    existing_source_refs = {view.source_turn_ref for view in existing_views}
    recovered: list[EvidenceView] = []

    def visit(operand: object) -> None:
        if not isinstance(operand, dict) or not _validated_operand(operand):
            return
        direct_evidence_ids = _provenance_values(
            operand,
            (
                "evidence_id",
                "evidence_ids",
                "evidence_refs",
                "source_evidence_id",
                "source_evidence_ids",
            ),
        )
        direct_source_refs = _provenance_values(
            operand,
            ("source_ref", "source_refs", "source_turn_ref", "source_turn_refs"),
        )
        source_span = operand.get("source_span")
        source_timestamp = operand.get("source_timestamp")
        if (
            operand.get("authority_class") == "EVIDENCE_ONLY"
            and len(direct_evidence_ids) == 1
            and len(direct_source_refs) == 1
            and isinstance(source_span, str)
            and bool(source_span.strip())
            and isinstance(source_timestamp, str)
            and bool(source_timestamp)
        ):
            evidence_id = direct_evidence_ids[0]
            source_ref = direct_source_refs[0]
            if evidence_id not in existing_evidence_ids and source_ref not in existing_source_refs:
                body = source_span.strip()
                content_terms = frozenset(_TERM.findall(body.casefold()))
                recovered.append(
                    EvidenceView(
                        evidence_id=evidence_id,
                        source_turn_ref=source_ref,
                        session_id=f"derived-operand-{_sha256(source_ref)[:20]}",
                        speaker="UNKNOWN",
                        content=body,
                        observed_at=source_timestamp,
                        source_rank=len(existing_views) + len(recovered) + 1,
                        query_overlap=len(query_terms & content_terms),
                        answer_signal=_answer_signal(
                            query,
                            query_terms,
                            body,
                            member_enumeration=member_enumeration,
                        ),
                        anchor_match=True,
                    )
                )
                existing_evidence_ids.add(evidence_id)
                existing_source_refs.add(source_ref)
        nested = operand.get("operands")
        if isinstance(nested, list):
            for child in nested:
                visit(child)

    operands = raw.get("operands")
    if isinstance(operands, list):
        for operand in operands:
            visit(operand)
    return recovered


def _query_terms(query: str) -> frozenset[str]:
    return frozenset(_TERM.findall(query.casefold())) - _QUERY_STOPWORDS


def _answer_signal(
    query: str,
    query_terms: frozenset[str],
    content: str,
    *,
    member_enumeration: bool,
) -> bool:
    values = tuple(_VALUE.finditer(content))
    if not values:
        return False
    if member_enumeration:
        return False
    for value in values:
        neighborhood = content[max(0, value.start() - 72) : min(len(content), value.end() + 72)]
        terms = frozenset(_TERM.findall(neighborhood.casefold()))
        if query_terms & terms:
            return True
    return False


def _legacy_session_identity(item: dict[str, Any], source_ref: str) -> str:
    subject_id = item.get("subject_id")
    if isinstance(subject_id, str) and subject_id:
        return subject_id
    return f"source-{_sha256(source_ref)[:20]}"


def _structured_source_context(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("source_context_source") not in {
        "STRUCTURED_TURN_METADATA",
        "AUTHORITATIVE_BACKFILL",
    }:
        return None
    value = item.get("source_context")
    if not isinstance(value, dict):
        return None
    required_text = ("session_id", "turn_id", "round_id")
    required_ordinals = ("turn_ordinal", "round_ordinal")
    if any(not isinstance(value.get(key), str) or not value[key] for key in required_text):
        return None
    if any(
        not isinstance(value.get(key), int) or isinstance(value[key], bool) or value[key] < 0
        for key in required_ordinals
    ):
        return None
    if any(
        item_value is not None and not isinstance(item_value, str)
        for item_value in (value.get("previous_turn_id"), value.get("next_turn_id"))
    ):
        return None
    return value
