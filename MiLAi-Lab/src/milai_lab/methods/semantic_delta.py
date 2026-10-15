"""One semantic delta, compiled into the existing source-bound edit proposals.

The model names changes and factors shared premises. Identity, version binding,
unchanged units and actual effects remain owned by EditMemory/MemoryService.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.functional_state import FunctionalRejection

INSTRUCTIONS = (
    "Express only the semantic changes supported by the delivered sources. Return the supplied "
    "delta schema. Each node's basis is an existing delivered e evidence reference, and kind "
    "states its attribution (reported/inferred/observed/uncertain). also can add other delivered "
    "e references needed to support the whole claim. "
    "creates contains new matters; changes is keyed by delivered record. replace changes an old "
    "u unit, append introduces a new n unit, withdraw removes a unit with cancellation evidence. "
    "Omitted units and support groups stay unchanged. Each node states one self-contained claim "
    "with its subject, scope, time and modality; preserve shared qualifications when splitting. "
    "A future change and correction of an earlier mistake have different historical meanings: "
    "state that distinction in the changed claims. Report time alone is not an effective date. "
    "Support rules describe source-supported implications, not truth assignments. For a rule, "
    "all lists common prerequisites and any lists alternative jointly sufficient routes: "
    "all=[training], any=[[card],[voucher]] means training AND (card OR voucher). An empty any "
    "means no supported route remains; any=[[]] means only the common prerequisites. A rule "
    "with remove=true withdraws that dependency assertion. New n names are local to each "
    "create/change, old u names refer to delivered units. Conditions can themselves be nodes, "
    "so they can change independently. Use rules only when the source supports them; otherwise "
    "keep self-contained source-bound text. Missing evidence is unknown, not a false premise. "
    "Changing one credential does not remove another route or its common prerequisites. "
    "No change is represented by empty creates/changes, not by restating old units."
)


def _object(fields: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": fields, "required": required,
            "additionalProperties": False}


def delta_schema(mapping: dict[str, Any], *, allow_create: bool) -> dict[str, Any]:
    evidence = list(mapping.get("evidence", {}))
    e = {"type": "string", "enum": evidence} if evidence else {"type": "string"}
    name = {"type": "string", "minLength": 1}
    applicability: dict[str, Any] = {"scope": name,
        "quantity_scope": {"enum": ["overall", "per_member"]}}
    dates = [item["id"] for item in mapping.get("time_choices", [])]
    ends = [item["id"] + ":end" for item in mapping.get("time_choices", [])
            if "day_end_exclusive" in item]
    for field in ("event_at", "effective_from", "effective_until"):
        if dates:
            applicability[field] = {"enum": dates + (ends if field == "effective_until" else [])}
    node = _object({"text": name, "basis": e,
        "also": {"type": "array", "items": e},
        "kind": {"enum": ["reported", "inferred", "observed", "uncertain"]},
        "applicability": _object(applicability, []),
        "evidence_links": _object({stance: {"type": "array", "items": e}
                                   for stance in ("supports", "opposes")}, [])},
        ["text", "basis", "kind"])
    new_ref = {"type": "string", "pattern": "^n[0-9]+$"}
    new_node = _object({**node["properties"], "id": new_ref}, ["id", "text", "basis", "kind"])

    def rules(units: list[str] | None = None) -> dict[str, Any]:
        ref = {"anyOf": [new_ref, {"enum": units}]} if units else new_ref
        choices = [_object({"target": ref, "all": {"type": "array", "items": ref},
            "any": {"type": "array", "items": {"type": "array", "items": ref}},
            "basis": e}, ["target", "all", "any", "basis"])]
        if units:
            choices.append(_object({"target": {"enum": units}, "remove": {"const": True},
                                    "basis": e}, ["target", "remove", "basis"]))
        return {"type": "array", "items": {"oneOf": choices}}
    changes = {}
    for target in mapping.get("records", {}):
        units = {alias: node for alias, unit in mapping["units"].items()
                 if unit["record"] == target}
        changes[target] = _object({"replace": _object(units, []),
            "append": {"type": "array", "items": new_node},
            "withdraw": _object({alias: e for alias in units}, []),
            "rules": rules(list(units))}, [])
    return _object({
        "creates": {"type": "array", "items": _object({"matter": name,
            "nodes": {"type": "array", "minItems": 1, "items": new_node},
            "rules": rules()}, ["matter", "nodes"]),
            **({"maxItems": 0} if not allow_create or not evidence else {})},
        "changes": _object(changes, []),
    }, ["creates", "changes"])


def delta_messages(
    packet: dict[str, Any], date: str, schema: dict[str, Any],
    prior_context: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps({"observed_date": date, "delivery": packet,
            **({"prior_context": prior_context} if prior_context else {}),
            "response_schema": schema}, ensure_ascii=False, separators=(",", ":"))},
    ]


def compile_delta(envelope: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize once; the existing proposal decoder and commit bind actual effects."""
    Draft202012Validator(delta_schema(mapping, allow_create=mapping["allow_create"])).validate(
        envelope)
    def claim(node: dict[str, Any]) -> dict[str, Any]:
        return {"text": node["text"], "evidence": list(dict.fromkeys(
            [node["basis"], *node.get("also", [])])),
            "assertion": {"source_evidence": node["basis"], "kind": node["kind"],
                **{key: copy.deepcopy(node[key]) for key in ("applicability", "evidence_links")
                   if key in node}}}

    def groups(
        item: dict[str, Any], new: dict[str, int], target: str | None,
    ) -> list[dict[str, Any]]:
        def resolve(ref: str) -> str | int:
            if ref in new:
                return new[ref] if target is None else f"n{new[ref]}"
            if target is not None and ref in mapping["units"] \
                    and mapping["units"][ref]["record"] == target:
                return ref
            raise FunctionalRejection("DELTA_RULE_REFERENCE_UNAVAILABLE: " + ref)

        result = []
        for rule in item.get("rules", []):
            group: dict[str, Any] = {"target_unit": resolve(rule["target"]),
                                    "evidence": [rule["basis"]]}
            if rule.get("remove"):
                group["operation"] = "remove"
            else:
                group["alternatives"] = [list(dict.fromkeys(
                    resolve(ref) for ref in [*rule["all"], *route])) for route in rule["any"]]
            result.append(group)
        return result

    def index(nodes: list[dict[str, Any]]) -> dict[str, int]:
        names = {node["id"]: i for i, node in enumerate(nodes)}
        if len(names) != len(nodes):
            raise FunctionalRejection("DELTA_NEW_NAME_REPEATED")
        return names

    proposals = []
    for item in envelope["creates"]:
        proposal: dict[str, Any] = {"action": "create", "matter": item["matter"],
            "clauses": [{**claim(node), "conditions": []} for node in item["nodes"]]}
        if item.get("rules"):
            proposal["support_groups"] = groups(item, index(item["nodes"]), None)
        else:
            index(item["nodes"])
        proposals.append(proposal)
    for target, item in envelope["changes"].items():
        edits = [{"operation": "replace", "target_unit": unit, **claim(node)}
                 for unit, node in item.get("replace", {}).items()]
        edits.extend({"operation": "append", "role": "content", **claim(node)}
                     for node in item.get("append", []))
        edits.extend({"operation": "retract", "target_unit": unit,
                      "evidence": [basis]}
                     for unit, basis in item.get("withdraw", {}).items())
        proposal = {"action": "edit", "target": target, "edits": edits}
        new = index(item.get("append", []))
        if item.get("rules"):
            proposal["support_groups"] = groups(item, new, target)
        if edits or item.get("rules"):
            proposals.append(proposal)
    return proposals
