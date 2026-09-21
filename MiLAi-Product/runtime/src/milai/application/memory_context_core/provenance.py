"""Source-provenance helpers for memory-context compilation."""

from __future__ import annotations

from typing import Any

from milai.application.memory_context_core.common import _unique
from milai.application.memory_context_core.semantics import _validated_operand


def _required_sources(raw: object) -> tuple[list[str], list[str]]:
    if (
        not isinstance(raw, dict)
        or raw.get("canonical_mutation") is not False
        or raw.get("status") in {"ABSTAINED", "ERROR", "UNSATISFIED"}
    ):
        return [], []
    evidence_ids = _provenance_values(raw, ("evidence_refs",))
    source_refs = _provenance_values(raw, ("source_turn_refs",))
    raw_operands = raw.get("operands")
    operands = raw_operands if isinstance(raw_operands, list) else []
    for operand in operands:
        if not isinstance(operand, dict) or not _validated_operand(operand):
            continue
        operand_evidence_ids, operand_source_refs = _operand_sources(operand)
        evidence_ids.extend(operand_evidence_ids)
        source_refs.extend(operand_source_refs)
    return _unique(evidence_ids), _unique(source_refs)


def _operand_sources(operand: dict[str, Any]) -> tuple[list[str], list[str]]:
    evidence_ids = _provenance_values(
        operand,
        (
            "evidence_id",
            "evidence_ids",
            "evidence_refs",
            "source_evidence_id",
            "source_evidence_ids",
        ),
    )
    source_refs = _provenance_values(
        operand,
        ("source_ref", "source_refs", "source_turn_ref", "source_turn_refs"),
    )
    nested = operand.get("operands")
    if isinstance(nested, list):
        for child in nested:
            if not isinstance(child, dict) or not _validated_operand(child):
                continue
            child_evidence_ids, child_source_refs = _operand_sources(child)
            evidence_ids.extend(child_evidence_ids)
            source_refs.extend(child_source_refs)
    return evidence_ids, source_refs


def _provenance_values(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return values


def _canonical_item_sources(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Read only explicit, Runtime-returned support attached to one canonical item."""

    evidence_ids = _provenance_values(
        item,
        (
            "evidence_id",
            "evidence_ids",
            "evidence_refs",
            "source_evidence_id",
            "source_evidence_ids",
        ),
    )
    source_refs = _provenance_values(
        item,
        ("source_ref", "source_refs", "source_turn_ref", "source_turn_refs"),
    )
    return _unique(evidence_ids), _unique(source_refs)


def _canonical_sources(
    items: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    evidence_ids: list[str] = []
    source_refs: list[str] = []
    for item in items:
        item_evidence_ids, item_source_refs = _canonical_item_sources(item)
        evidence_ids.extend(item_evidence_ids)
        source_refs.extend(item_source_refs)
    return _unique(evidence_ids), _unique(source_refs)

