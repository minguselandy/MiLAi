"""Whole-unit, explicitly partial projections of an already opened Reader View.

This pure function neither opens nor validates a stored object. Call the common
visibility/version-checked open and Reader projection first. No runtime path uses
this experimental representation by default.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any


def _references(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("View references must be lists of strings")
    return value


def project_structure_units(
    packet: dict[str, Any],
    requested_nodes: list[str],
) -> dict[str, Any]:
    """Keep requested whole nodes and every incident known rule component.

    All AND prerequisites and every OR-of-AND route survive literally. Traversal
    is conservative in both directions: selecting a premise also retains rules
    that use it, so connected exceptions/qualifications are not silently removed.
    This is closure of the recorded graph, not proof of semantic completeness.

    The caller measures the complete resulting wrapper against its actual token
    budget. A large connected component is never shortened here. Source locators
    remain navigation; this operation cannot deliver any new original evidence.
    """
    if (
        packet.get("kind") != "query_structure"
        or packet.get("visibility") not in {None, "visible"}
        or packet.get("body_delivered") is False
        or not isinstance(packet.get("interpretation"), dict)
        or "literal_map_tables" in packet
        or "unit_projection" in packet
    ):
        raise ValueError("Require a visible, plain, unprojected Reader View packet")
    structure = packet["interpretation"]
    nodes, rules, bindings = (
        structure.get("nodes"),
        structure.get("rules"),
        packet.get("source_bindings"),
    )
    if (
        not isinstance(nodes, dict)
        or not isinstance(rules, dict)
        or not isinstance(bindings, dict)
        or not all(isinstance(k, str) and k for k in [*nodes, *rules, *bindings])
        or not isinstance(structure.get("scope"), str)
    ):
        raise ValueError("Require literal node/rule maps and source bindings")
    _references(structure.get("unresolved"))
    requested = list(dict.fromkeys(_references(requested_nodes)))
    if not set(requested) <= set(nodes):
        raise ValueError("Requested node is unavailable in this exact View")
    edges: dict[str, set[str]] = {}
    for node in nodes.values():
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("text"), str)
            or node.get("kind") not in {"reported", "inferred", "uncertain"}
        ):
            raise ValueError("Require complete typed View nodes")
    for key, rule in rules.items():
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("target"), str)
            or not isinstance(rule.get("any"), list)
        ):
            raise ValueError("Require typed target/all/any rules")
        refs = {rule["target"], *_references(rule.get("all"))}
        for route in rule["any"]:
            refs.update(_references(route))
        if not refs <= set(nodes):
            raise ValueError("Dangling rule reference in the parent View")
        edges[key] = refs
    # Validate the full parent, including units that would otherwise be omitted.
    for value in [*nodes.values(), *rules.values()]:
        evidence = _references(value.get("evidence"))
        if not evidence or not set(evidence) <= set(bindings):
            raise ValueError("Dangling evidence alias in the parent View")

    selected = set(requested)
    while True:
        expanded = selected | {node for refs in edges.values() if refs & selected for node in refs}
        if expanded == selected:
            break
        selected = expanded
    if selected == set(nodes):
        return copy.deepcopy(packet)
    result = copy.deepcopy(packet)
    result["interpretation"]["nodes"] = {
        k: copy.deepcopy(v) for k, v in nodes.items() if k in selected
    }
    result["interpretation"]["rules"] = {
        k: copy.deepcopy(v) for k, v in rules.items() if edges[k] & selected
    }
    # Global scope, unknowns and all unfamiliar literal fields stay. Preserve
    # prose-only aliases as well as typed references; e1 must not match e10.
    locations = result.get("source_locations", {})
    metadata = result.get("source_metadata", {})
    if not isinstance(locations, dict) or not isinstance(metadata, dict):
        raise ValueError("Require literal source locator and metadata maps")
    per_alias = metadata.get("by_alias", {})
    if not isinstance(per_alias, dict):
        raise ValueError("Require a literal per-alias metadata map")

    def referenced_aliases(value: Any) -> set[str]:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return {
            alias
            for alias in bindings
            if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
        }

    aliases = referenced_aliases(
        {
            **{
                k: v
                for k, v in result.items()
                if k not in {"source_bindings", "source_locations", "source_metadata"}
            },
            "metadata_globals": {k: v for k, v in metadata.items() if k != "by_alias"},
        }
    )
    while True:
        linked = aliases | referenced_aliases(
            [
                {"binding": bindings[a], "location": locations.get(a), "metadata": per_alias.get(a)}
                for a in aliases
            ]
        )
        if linked == aliases:
            break
        aliases = linked
    result["source_bindings"] = {k: copy.deepcopy(v) for k, v in bindings.items() if k in aliases}
    if "source_locations" in result:
        result["source_locations"] = {
            k: v for k, v in result["source_locations"].items() if k in aliases
        }
    if "by_alias" in metadata:
        metadata["by_alias"] = {k: v for k, v in metadata["by_alias"].items() if k in aliases}
    result["unit_projection"] = {
        "format": "whole_connected_units_v1",
        "partial": True,
        "requested_nodes": requested,
        "selected_nodes": list(result["interpretation"]["nodes"]),
        "selected_rules": list(result["interpretation"]["rules"]),
        "parent_node_count": len(nodes),
        "parent_rule_count": len(rules),
        "parent_source_alias_count": len(bindings),
        "retained_source_alias_count": len(aliases),
        "known_rule_graph_closed": True,
        "semantic_completeness": "not_certified",
        "instructions": "Only selected whole nodes and all connected recorded rules are "
        "delivered. Parent scope is not complete delivery coverage. Global unresolved "
        "items remain unknown. Locators do not deliver original bodies. Recorded graph "
        "closure does not certify truth, sufficiency, or absence of unrecorded relations.",
    }
    return result
