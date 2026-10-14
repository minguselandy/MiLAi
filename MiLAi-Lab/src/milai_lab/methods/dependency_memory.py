"""Directed update regions over actual model-formed memory.

This first slice uses the existing condition/exception relations. It does not
infer dependencies from word overlap or turn a reachable node into a deletion.
Both update context and query support use the same directed relation semantics.
"""

from __future__ import annotations

import copy
import json
from typing import Any


def dependency_region(
    state: dict[str, Any], roots: list[str], *, preserve: list[str] | None = None,
) -> dict[str, Any]:
    """Separate potentially affected successors from read-only prerequisites.

    ``preserve`` is an explicit model decision after reading the original event:
    a disjoint scope or still-supported successor needs no edit. It is retained
    as context, not removed from the graph. No semantic truth is inferred here.
    """
    ordered = [unit["unit_id"] for unit in state["units"]]
    edges = state.get("relations", [])
    preserved = set(preserve or []) - set(roots)
    affected = set(roots)
    while True:
        previous = affected.copy()
        for edge in edges:
            source, target = edge["source_unit"], edge["target_unit"]
            if source in affected and target not in preserved:
                affected.add(target)
            # A base change requires reconsidering its scoped exception, but
            # does not license changing other targets of a shared condition.
            if edge["relation_type"] == "overrides" and target in affected \
                    and source not in preserved:
                affected.add(source)
        if affected == previous:
            break
    context = set(affected)
    while True:
        previous = context.copy()
        for edge in edges:
            source, target = edge["source_unit"], edge["target_unit"]
            if target in context:
                context.add(source)
            if source in affected:
                context.add(target)
        if context == previous:
            break
    return {
        "root_units": [uid for uid in ordered if uid in roots],
        "affected_units": [uid for uid in ordered if uid in affected],
        "read_only_units": [uid for uid in ordered if uid in context - affected],
        "preserved_units": [uid for uid in ordered if uid in preserved],
        "context_units": [uid for uid in ordered if uid in context],
        "relations": [copy.deepcopy(edge) for edge in edges
                      if edge["source_unit"] in context and edge["target_unit"] in context],
    }


def query_support(
    state: dict[str, Any], roots: list[str], *, excluded: list[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Read prerequisites and scoped alternatives without expanding sibling claims.

    Exclusions are a query-specific model selection, never a persisted assertion
    of invalidity. A selected exception still opens its general rule.
    """
    omitted = set(excluded or []) - set(roots)
    selected = set(roots)
    while True:
        previous = selected.copy()
        for edge in state.get("relations", []):
            source, target = edge["source_unit"], edge["target_unit"]
            if target in selected and source not in omitted:
                selected.add(source)
            if (source in roots or (edge["relation_type"] == "overrides" and source in selected)) \
                    and target not in omitted:
                selected.add(target)
        if selected == previous:
            break
    return (
        [unit["unit_id"] for unit in state["units"] if unit["unit_id"] in selected],
        [copy.deepcopy(edge) for edge in state.get("relations", [])
         if edge["source_unit"] in selected and edge["target_unit"] in selected],
    )


def impact_request(packet: dict[str, Any], mapping: dict[str, Any], date: str) -> dict[str, Any]:
    units = list(mapping["units"])
    references = {"type": "array", "items": {"type": "string", "enum": units}}
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"roots": references, "preserve": copy.deepcopy(references)},
        "required": ["roots", "preserve"],
    }
    return {"schema": schema, "messages": [
        {"role": "system", "content": (
            "Locate the directly changed claims or conditions in this actual memory. "
            "Select their unit aliases as roots. Acknowledgments or entirely new claims "
            "can have no old roots. Read the original current event and the old support. "
            "preserve names downstream claims whose scope is disjoint or whose independent "
            "support still suffices. Do not preserve a root. These are reconsideration "
            "decisions, not edits or facts. The program follows declared outgoing "
            "condition/exception edges and opens prerequisites as read-only context. "
            "Do not select unrelated sibling claims just because they share a condition. "
            "Use the supplied schema."
        )},
        {"role": "user", "content": json.dumps(
            {"observed_date": date, "delivery": packet, "response_schema": schema},
            ensure_ascii=False, separators=(",", ":"))},
    ]}


def plan_regions(mapping: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    """Compute regions using only the aliases actually delivered to this call."""
    regions = {}
    for record_id, record in mapping["records"].items():
        aliases = {unit["unit_id"]: alias for alias, unit in mapping["units"].items()
                   if unit["record"] == record_id}
        ids = set(aliases.values())
        original = record["edit_state"]
        state = {
            "units": [{"unit_id": aliases[unit["unit_id"]]} for unit in original["units"]],
            "relations": [{"source_unit": aliases[edge["source_unit"]],
                           "target_unit": aliases[edge["target_unit"]],
                           "relation_type": edge["relation_type"]}
                          for edge in original["relations"]],
        }
        regions[record_id] = dependency_region(
            state, [uid for uid in selection["roots"] if uid in ids],
            preserve=[uid for uid in selection["preserve"] if uid in ids])
    return regions


def scoped_edit_schema(schema: dict[str, Any], regions: dict[str, Any]) -> dict[str, Any]:
    """Limit existing-unit mutations; full delivered bodies remain readable.

    New clauses remain available. No-op and exact keep references keep their
    existing semantics. The normal bound decoder and commit remain authoritative.
    """
    allowed = {uid for region in regions.values() for uid in region["affected_units"]}

    def visit(node: Any) -> Any:
        if isinstance(node, list):
            return [visit(child) for child in node]
        if not isinstance(node, dict):
            return node
        result = {key: visit(value) for key, value in node.items()}
        props = result.get("properties", {})
        if "attach_to" in props and "items" in props["attach_to"]:
            reference = props["attach_to"]["items"]
            choices = [uid for uid in reference.get("enum", []) if uid in allowed]
            if choices:
                reference["enum"] = choices
            else:
                props["attach_to"] = {"type": "array", "maxItems": 0}
        if "target_unit" in props:
            reference = props["target_unit"]
            if "const" in reference and reference["const"] not in allowed:
                return False
            if "enum" in reference:
                reference["enum"] = [uid for uid in reference["enum"] if uid in allowed]
                if not reference["enum"]:
                    if "target_unit" in result.get("required", []):
                        return False
                    props["target_unit"] = {"type": "null"}
        for key in ("oneOf", "anyOf"):
            if key in result:
                result[key] = [child for child in result[key] if child is not False]
                if not result[key]:
                    return False
        return result

    return visit(copy.deepcopy(schema))  # type: ignore[no-any-return]
