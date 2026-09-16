"""Deterministic two-slot quantity composition over governed Raw Evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from milai.application.evidence_semantics import (
    bind_requirements,
    interpret_evidence_spans,
    project_evidence_spans,
)
from milai.domain.evidence_composition import (
    CompositionCompleteness,
    EvidenceApplicabilityResult,
    EvidenceCompositionResult,
    EvidenceSlot,
    OperatorTrace,
    QuerySpec,
    SlotName,
    query_spec_from_plan,
)
from milai.domain.retrieval import QueryPlan
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceRequirementV02,
    EvidenceSpan,
    RequirementBinding,
)

_PURCHASE = re.compile(r"\b(?:bought|got|ordered|picked up|purchased)\b", re.I)
_SPEND = re.compile(r"\b(?:cost|paid|spend|spent|total)\b", re.I)
_PURPOSE = re.compile(
    r"\bfor\s+(?:my|our|the)\s+(?P<purpose>[a-z][a-z0-9 '-]{0,80}?)(?:[,.!?;]|$)",
    re.I,
)


def composition_evidence_queries(plan: QueryPlan) -> tuple[str, str] | None:
    """Return one label-free retrieval query per required quantity slot."""

    if plan.operator != "DIVIDE_EVIDENCE_VALUES":
        return None
    terms = _entity_terms(plan)
    if not terms:
        return None
    entity = " ".join(terms)
    return (
        f"{entity} spent paid cost price total",
        f"{entity} purchased bought ordered count number",
    )


def compose_divide_evidence_values(
    plan: QueryPlan, evidence: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Fill TOTAL_PRICE and ITEM_COUNT, then divide with no model call."""

    spec = query_spec_from_plan(plan)
    if spec is None or spec.operator != "DIVIDE_EVIDENCE_VALUES":
        return None
    entity_terms = _entity_terms(plan)
    if not entity_terms:
        return _partial(plan, spec, "OPERATOR_SLOT_SCHEMA_INVALID", [], [])
    requirements = _quantity_requirements(plan)
    if requirements is None:
        return _partial(plan, spec, "OPERATOR_SLOT_SCHEMA_INVALID", [], [])
    spans = project_evidence_spans(evidence)
    interpretations = interpret_evidence_spans(spans)
    bindings = bind_requirements(requirements, interpretations, spans)
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation for interpretation in interpretations
    }
    operands_by_slot: dict[str, list[dict[str, Any]]] = {
        "TOTAL_PRICE": [],
        "ITEM_COUNT": [],
    }
    for binding in bindings:
        if binding.status != "MATCH" or binding.requirement_id not in operands_by_slot:
            continue
        interpretation = interpretation_by_id[binding.interpretation_id]
        span = span_by_id[interpretation.span_id]
        if not _predicate_applicable(binding, span):
            continue
        operands_by_slot[binding.requirement_id].append(_operand(span, interpretation, binding))
    prices = operands_by_slot["TOTAL_PRICE"]
    counts = operands_by_slot["ITEM_COUNT"]
    prices = _deduplicate(prices)
    counts = _deduplicate(counts)
    filled: list[str] = []
    if len(prices) == 1:
        filled.append("TOTAL_PRICE")
    if len(counts) == 1:
        filled.append("ITEM_COUNT")
    if len(prices) != 1 or len(counts) != 1:
        reason = (
            "OPERAND_AMBIGUOUS" if len(prices) > 1 or len(counts) > 1 else "REQUIRED_SLOT_MISSING"
        )
        return _partial(plan, spec, reason, [*prices, *counts], filled)
    if not _purpose_compatible(prices[0], counts[0]):
        return _partial(
            plan,
            spec,
            "JOIN_PURPOSE_INCOMPATIBLE",
            [*prices, *counts],
            filled,
        )
    price = Decimal(str(prices[0]["value"]))
    count = Decimal(str(counts[0]["value"]))
    if count <= 0:
        return _partial(plan, spec, "INVALID_DIVISOR", [*prices, *counts], filled)
    unit_price = price / count
    exponent = unit_price.as_tuple().exponent
    if not isinstance(exponent, int):
        return _partial(plan, spec, "NON_FINITE_CURRENCY_RESULT", [*prices, *counts], filled)
    if exponent < -2:
        return _partial(plan, spec, "NON_TERMINATING_CURRENCY_RESULT", [*prices, *counts], filled)
    currency = str(prices[0]["unit"])
    value = int(unit_price) if unit_price == unit_price.to_integral() else float(unit_price)
    operands = [*prices, *counts]
    trace = _trace(spec, operands, "COMPLETE")
    return EvidenceCompositionResult(
        status="COMPLETE",
        operator=spec.operator,
        result=value,
        unit=f"{currency}_PER_ITEM",
        display_value=f"{_currency_symbol(currency)}{unit_price} per item",
        route_reason=str(plan.operator_arguments["route_reason"]),
        slot_schema_version=str(plan.operator_arguments["slot_schema_version"]),
        operands=operands,
        evidence_refs=[prices[0]["evidence_id"], counts[0]["evidence_id"]],
        source_turn_refs=[prices[0]["source_ref"], counts[0]["source_ref"]],
        completeness=CompositionCompleteness(
            required_slots=["TOTAL_PRICE", "ITEM_COUNT"],
            filled_slots=["TOTAL_PRICE", "ITEM_COUNT"],
            bounded_scan_complete=False,
            unresolved_reasons=[],
        ),
        trace=trace,
        entity_compatibility="PASS",
        unit_compatibility="PASS",
    ).payload()


def prioritize_composition_evidence(
    evidence: Sequence[dict[str, Any]], derived: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Keep provenance-bearing operands visible ahead of other search hits."""

    if derived is None or derived.get("status") != "COMPLETE":
        return list(evidence)
    refs = [str(value) for value in derived.get("evidence_refs", []) if isinstance(value, str)]
    priority = {evidence_id: index for index, evidence_id in enumerate(refs)}
    return sorted(
        evidence,
        key=lambda item: (
            priority.get(str(item.get("evidence_id")), len(priority)),
            str(item.get("evidence_id", "")),
        ),
    )


def _entity_terms(plan: QueryPlan) -> tuple[str, ...]:
    value = plan.operator_arguments.get("entity_terms")
    if not isinstance(value, list) or not value:
        return ()
    terms = tuple(item.casefold() for item in value if isinstance(item, str) and item)
    return terms if len(terms) == len(value) else ()


def _quantity_requirements(
    plan: QueryPlan,
) -> tuple[EvidenceRequirementV02, EvidenceRequirementV02] | None:
    query_ir = plan.memory_query_ir
    if query_ir is None:
        return None
    by_slot = {requirement.slot_id: requirement for requirement in query_ir.requirements}
    price = by_slot.get("TOTAL_PRICE")
    count = by_slot.get("ITEM_COUNT")
    if (
        price is None
        or count is None
        or price.interpretation_kind != "QUANTITY"
        or count.interpretation_kind != "QUANTITY"
        or price.join_key is None
        or price.join_key != count.join_key
    ):
        return None
    return price, count


def _operand(
    span: EvidenceSpan,
    interpretation: EvidenceInterpretationCandidate,
    binding: RequirementBinding,
) -> dict[str, Any]:
    value = interpretation.value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AssertionError("matched quantity interpretation must be numeric")
    return {
        "slot": binding.requirement_id,
        "value": value,
        "unit": interpretation.unit,
        "evidence_id": span.source_evidence_id,
        "source_ref": span.source_turn_ref,
        "span": {
            "text": span.text,
            "start": span.start,
            "end": span.end,
        },
        "source_role": span.speaker,
        "session_id": span.session_id,
        "purpose": _purpose_signature(span.text),
        "evidence_span": span.model_dump(mode="json"),
        "interpretation": interpretation.model_dump(mode="json"),
        "requirement_binding": binding.model_dump(mode="json"),
    }


def _deduplicate(values: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[object, object, object], dict[str, Any]] = {}
    for item in values:
        interpretation = cast(dict[str, Any], item["interpretation"])
        key = (item["slot"], item["evidence_id"], interpretation["interpretation_id"])
        unique.setdefault(key, item)
    return sorted(
        unique.values(),
        key=lambda item: (
            str(item["source_ref"]),
            str(cast(dict[str, Any], item["interpretation"])["interpretation_id"]),
        ),
    )


def _predicate_applicable(binding: RequirementBinding, span: EvidenceSpan) -> bool:
    if binding.requirement_id == "TOTAL_PRICE":
        return _SPEND.search(span.text) is not None
    if binding.requirement_id == "ITEM_COUNT":
        return _PURCHASE.search(span.text) is not None or _SPEND.search(span.text) is not None
    return False


def _purpose_signature(text: str) -> str | None:
    matched = _PURPOSE.search(text)
    if matched is None:
        return None
    return " ".join(matched.group("purpose").casefold().split())


def _purpose_compatible(price: Mapping[str, Any], count: Mapping[str, Any]) -> bool:
    price_purpose = price.get("purpose")
    count_purpose = count.get("purpose")
    return price_purpose is None or count_purpose is None or price_purpose == count_purpose


def _trace(
    spec: QuerySpec, operands: Sequence[Mapping[str, Any]], terminal_reason: str
) -> OperatorTrace:
    slots: list[EvidenceSlot] = []
    applicability: list[EvidenceApplicabilityResult] = []
    for name in ("TOTAL_PRICE", "ITEM_COUNT"):
        values = [dict(item) for item in operands if item.get("slot") == name]
        slots.append(
            EvidenceSlot(
                name=name,
                status=(
                    "FILLED" if len(values) == 1 else "AMBIGUOUS" if len(values) > 1 else "MISSING"
                ),
                operands=values,
                unresolved_reason=(
                    None
                    if len(values) == 1
                    else "OPERAND_AMBIGUOUS"
                    if len(values) > 1
                    else "REQUIRED_SLOT_MISSING"
                ),
            )
        )
        applicability.extend(
            EvidenceApplicabilityResult(
                evidence_id=str(item["evidence_id"]),
                source_turn_ref=str(item["source_ref"]),
                slot=name,
                accepted=len(values) == 1,
                reason="USER_ENTITY_QUANTITY_MATCH",
                span=item.get("span"),
            )
            for item in values
        )
    return OperatorTrace(
        query_spec=spec,
        slots=slots,
        applicability=applicability,
        retrieval_attempts=2,
        expansion=["PER_SLOT_FTS_UNION"],
        join="SAME_ENTITY_PURPOSE_VALIDATED_THEN_TOTAL_PRICE_DIVIDED_BY_ITEM_COUNT",
        terminal_reason=terminal_reason,
    )


def _partial(
    plan: QueryPlan,
    spec: QuerySpec,
    reason: str,
    operands: Sequence[Mapping[str, Any]],
    filled_slots: Sequence[str],
) -> dict[str, Any]:
    operand_values = [dict(item) for item in operands]
    return EvidenceCompositionResult(
        status="PARTIAL",
        operator=spec.operator,
        result=None,
        unit=None,
        reason=reason,
        route_reason=str(plan.operator_arguments.get("route_reason", "")),
        operands=operand_values,
        evidence_refs=[str(item["evidence_id"]) for item in operands],
        source_turn_refs=[str(item["source_ref"]) for item in operands],
        completeness=CompositionCompleteness(
            required_slots=["TOTAL_PRICE", "ITEM_COUNT"],
            filled_slots=[
                cast(SlotName, value)
                for value in ("TOTAL_PRICE", "ITEM_COUNT")
                if value in filled_slots
            ],
            bounded_scan_complete=False,
            unresolved_reasons=[reason],
        ),
        trace=_trace(spec, operands, reason),
    ).payload()


def _currency_symbol(unit: str) -> str:
    return {"USD": "$", "GBP": "£", "EUR": "€"}.get(unit, "")


__all__ = [
    "compose_divide_evidence_values",
    "composition_evidence_queries",
    "prioritize_composition_evidence",
]
