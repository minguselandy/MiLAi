"""Directed update regions over actual model-formed memory.

The mechanism uses condition/exception relations and source-bound support sets. It does not
infer dependencies from word overlap or turn a reachable node into a deletion.
Both update context and query support use the same directed relation semantics.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from milai_lab.memory.dependency_groups import select_support_routes


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
    support_edges = [(uid, group["target_unit"]) for group in state.get("support_groups", [])
                     for route in group["alternatives"] for uid in route]
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
        for source, target in support_edges:
            if source in affected and target not in preserved:
                affected.add(target)
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
        for source, target in support_edges:
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
        "support_update_targets": [uid for uid in ordered if uid in affected or any(
            source in affected and target == uid for source, target in support_edges)],
        "relations": [copy.deepcopy(edge) for edge in edges
                      if edge["source_unit"] in context and edge["target_unit"] in context],
        **({"support_groups": [copy.deepcopy(group) for group in state["support_groups"]
                               if group["target_unit"] in context]}
           if "support_groups" in state else {}),
    }


def query_support(
    state: dict[str, Any], roots: list[str], *, excluded: list[str] | None = None,
    support_choices: dict[str, list[int]] | None = None,
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
        selected, _ = select_support_routes(state, selected, choices=support_choices)
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
    if any(group.get("external_units") for record in mapping["records"].values()
           for group in record["edit_state"].get("support_groups", [])):
        return cross_record_regions(mapping, selection)
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
            **({"support_groups": [{
                "target_unit": aliases[group["target_unit"]],
                "alternatives": [[aliases[uid] for uid in route]
                                 for route in group["alternatives"]],
            } for group in original["support_groups"]]} if "support_groups" in original else {}),
        }
        regions[record_id] = dependency_region(
            state, [uid for uid in selection["roots"] if uid in ids],
            preserve=[uid for uid in selection["preserve"] if uid in ids])
    return regions


def cross_record_regions(mapping: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    """One directed graph over delivered aliases, then per-record edit regions."""
    aliases = {(mapping["records"][unit["record"]]["record_id"], unit["unit_id"]): alias
               for alias, unit in mapping["units"].items()}
    graph: dict[str, Any] = {"units": [{"unit_id": key} for key in mapping["units"]],
                             "relations": [], "support_groups": []}
    for record in mapping["records"].values():
        record_id = record["record_id"]
        state = record["edit_state"]
        graph["relations"].extend({"source_unit": aliases[(record_id, e["source_unit"])],
            "target_unit": aliases[(record_id, e["target_unit"])],
            "relation_type": e["relation_type"]} for e in state["relations"])
        for group in state.get("support_groups", []):
            def premise(
                uid: str, binding: dict[str, Any] = group, owner: str = record_id,
            ) -> str:
                external = binding.get("external_units", {}).get(uid)
                key = ((external["record_id"], external["unit_id"]) if external else
                       (owner, uid))
                return str(aliases.get(key, "unavailable_external"))

            graph["support_groups"].append({
                "target_unit": aliases[(record_id, group["target_unit"])],
                "alternatives": [[premise(uid) for uid in route]
                                 for route in group["alternatives"]]})
    whole = dependency_region(graph, selection["roots"], preserve=selection["preserve"])
    regions = {}
    for record_alias in mapping["records"]:
        local = {alias for alias, unit in mapping["units"].items()
                 if unit["record"] == record_alias}
        regions[record_alias] = {
            **{key: [uid for uid in whole[key] if uid in local] for key in (
                "root_units", "affected_units", "read_only_units", "preserved_units",
                "context_units", "support_update_targets")},
            "external_context_units": [uid for uid in whole["context_units"] if uid not in local],
            "relations": [e for e in whole["relations"]
                          if e["source_unit"] in local or e["target_unit"] in local],
            "support_groups": [g for g in whole["support_groups"] if g["target_unit"] in local],
        }
    return regions


def scoped_edit_schema(schema: dict[str, Any], regions: dict[str, Any]) -> dict[str, Any]:
    """Limit existing-unit mutations; full delivered bodies remain readable.

    New clauses remain available. No-op and exact keep references keep their
    existing semantics. The normal bound decoder and commit remain authoritative.
    """
    allowed = {uid for region in regions.values() for uid in region["affected_units"]}
    support_allowed = allowed | {uid for region in regions.values()
                                 for uid in region.get("support_update_targets", [])}

    def restrict_reference(
        reference: dict[str, Any], candidates: set[str],
    ) -> dict[str, Any] | bool:
        if "anyOf" in reference:
            alternatives = [restrict_reference(ref, candidates) for ref in reference["anyOf"]]
            alternatives = [ref for ref in alternatives if ref is not False]
            return {"anyOf": alternatives} if alternatives else False
        if "const" in reference and isinstance(reference["const"], str) \
                and reference["const"] not in candidates:
            return False
        if "enum" in reference:
            reference["enum"] = [uid for uid in reference["enum"] if uid in candidates]
            if not reference["enum"]:
                return False
        elif reference.get("type") == "string" and "const" not in reference \
                and reference.get("pattern") != "^n[0-9]+$":
            if not candidates:
                return False
            reference["enum"] = sorted(candidates)
        return reference

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
            group_change = ("alternatives" in props
                            or props.get("operation", {}).get("const") == "remove")
            narrowed = restrict_reference(
                props["target_unit"], support_allowed if group_change else allowed)
            if narrowed is False:
                if "target_unit" in result.get("required", []):
                    return False
                narrowed = {"type": "null"}
            props["target_unit"] = narrowed
        for key in ("oneOf", "anyOf"):
            if key in result:
                result[key] = [child for child in result[key] if child is not False]
                if not result[key]:
                    return False
        return result

    return visit(copy.deepcopy(schema))  # type: ignore[no-any-return]
