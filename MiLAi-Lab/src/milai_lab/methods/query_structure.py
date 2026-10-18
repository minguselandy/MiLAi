"""Task-local source interpretations, with one bounded cache in the existing Store.

The cache contains source-bound propositions and rules, never final answers.
Every refresh receives new arrivals, including events absent from old dependencies.
The first implementation scans Source metadata; that cost is reported explicitly.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any, Literal

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from milai_lab.memory.functional_state import FunctionalRejection, body_text
from milai_lab.memory.service import MemoryService

QueryStructurePolicy = Literal["rebuild", "version_cache", "incremental"]
POLICIES = ("rebuild", "version_cache", "incremental")

INSTRUCTIONS = (
    "Build a reusable local interpretation of the delivered source scope. Keep self-contained "
    "facts, conditional rules, temporal boundaries and uncertainty, not an answer to this query. "
    "Capture the independently changeable facts in the selected scope, so another wording or "
    "task can use them. scope describes that scope, not proof that all history was examined. "
    "Old nodes and rules in previous are model interpretations, not original evidence. "
    "sources contains newly delivered original bodies. source_directory binds the old and new "
    "e aliases; an old alias without a body does not supply its semantic content. "
    "New arrivals can introduce an overriding rule even if they are absent from old support. "
    "Use nodes/rules to add or replace only changed interpretations and remove/remove_rules "
    "for withdrawn ones. Unlisted prior nodes/rules stay. An unrelated new event can leave "
    "the structure unchanged. Distinguish new facts from corrections of earlier history. "
    "State dates and scopes in full text and temporal when the source supplies them. "
    "reported_at is when a source reports something; ingestion_observations records when this "
    "system received it. Neither establishes an event or effective date. Use the clock matching "
    "the requested meaning, and retain unknown dates as unknown. Preserve future rules and "
    "their effective boundaries for the Reader's query time. A rule needs every all prerequisite "
    "and one any route; each route "
    "itself requires every member. any=[[]] adds no alternative prerequisite to all; any=[] "
    "means no available support route. These are different logical states, both representable. "
    "An uncertain or unavailable premise is unknown, never its negation. Rules express "
    "source-supported implications, not an assurance that their premises hold. If the source "
    "does not support a relation, retain plain text. Return the supplied schema."
)
EXPLICIT_REFRESH_INSTRUCTIONS = (
    " Prior assistant answers are model interpretations, not independent factual support; "
    "user questions are requests, not assertions. Preserve the original source attribution. "
    "Keep temporal rules instead of replacing them with values evaluated only at the query date."
    " Every rule target and prerequisite must be a node actually defined in previous or nodes."
    " Direct reports need no rule edge. If a prerequisite is absent or false, keep the conditional"
    " rule as text; do not invent an asserted positive premise to fill the graph."
)


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def structure_schema(bindings: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    refs = {"type": "array", "minItems": 1,
            "items": {"type": "string", "enum": list(bindings)}}
    node_id = {"type": "string", "pattern": "^n[0-9]+$"}
    rule_id = {"type": "string", "pattern": "^g[0-9]+$"}

    def removal(names: list[str]) -> dict[str, Any]:
        return {"type": "array", "items": {"enum": names}} if names else {
            "type": "array", "maxItems": 0}

    return _object({
        "scope": text,
        "nodes": {"type": "array", "items": _object({"id": node_id, "text": text,
            "evidence": refs, "kind": {"enum": ["reported", "inferred", "uncertain"]},
            "temporal": {"type": "string"}}, ["id", "text", "evidence", "kind"])},
        "remove": removal(list(previous.get("nodes", {}))),
        "rules": {"type": "array", "items": _object({"id": rule_id,
            "target": node_id, "all": {"type": "array", "items": node_id},
            "any": {"type": "array",
                    "description": "OR of AND routes: [[]] adds no condition; [] has no route.",
                    "items": {"type": "array", "items": node_id}},
            "evidence": refs}, ["id", "target", "all", "any", "evidence"])},
        "remove_rules": removal(list(previous.get("rules", {}))),
        "unresolved": {"type": "array", "items": text},
    }, ["scope", "nodes", "remove", "rules", "remove_rules", "unresolved"])


def _sources_valid(service: MemoryService, bindings: dict[str, Any]) -> bool:
    return all((source := service.source(binding["source_ref"])) is not None
               and source.get("source_revision", 1) == binding["source_revision"]
               for binding in bindings.values())


def open_structure(service: MemoryService, item: dict[str, Any]) -> dict[str, Any]:
    """Recheck actual visibility when the common Reader opens the cached view."""
    if not _sources_valid(service, item["source_bindings"]):
        return {"id": item["id"], "kind": "query_structure", "body_delivered": False,
                "visibility": "support_unavailable"}
    return copy.deepcopy(item)


def cached_structure(service: MemoryService, slot: str = "current") -> dict[str, Any] | None:
    """Locate the existing slot without triggering retrieval or generation."""
    item = service.store.get((*service.namespace, "query_structure_v1"), slot)
    return copy.deepcopy(item.value) if item else None


def structure_slots(capacity: int) -> list[str]:
    if capacity not in (1, 2, 4):
        raise ValueError("QUERY_STRUCTURE_CAPACITY_INVALID")
    return ["current", *(f"slot{i}" for i in range(1, capacity))]


def cached_structures(service: MemoryService, capacity: int) -> dict[str, dict[str, Any]]:
    return {slot: item for slot in structure_slots(capacity)
            if (item := cached_structure(service, slot)) is not None}


def touch_structure(service: MemoryService, slot: str) -> None:
    namespace = (*service.namespace, "query_structure_v1")
    previous = service.store.get(namespace, "slot_recency")
    order = previous.value["slots"] if previous else []
    service.store.put(namespace, "slot_recency",
                      {"slots": [s for s in order if s != slot] + [slot]},
                      index=False)


def next_structure_slot(service: MemoryService, capacity: int) -> str:
    slots = structure_slots(capacity)
    occupied = cached_structures(service, capacity)
    for slot in slots:
        if slot not in occupied:
            return slot
    recency = service.store.get((*service.namespace, "query_structure_v1"), "slot_recency")
    order = recency.value["slots"] if recency else slots
    return next(slot for slot in order if slot in occupied)


def build_query_structure(
    service: MemoryService, question: str, date: str, source_refs: list[str], *,
    policy: QueryStructurePolicy,
    call: Callable[[list[dict[str, str]], dict[str, Any]], dict[str, Any]],
    source_events: list[dict[str, Any]] | None = None,
    force_refresh: bool = False,
    slot: str = "current",
    capacity: int = 1,
    replace_slot: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Reuse, reconstruct or incrementally refresh the same actually retrieved scope.

    A changed retrieval scope triggers interpretation even if all source versions
    are unchanged. A new arrival triggers it even if retrieval misses that source.
    Different question wording/time alone does not invalidate the intermediate
    rules: their current application belongs to the common Reader.
    """
    if policy not in POLICIES:
        raise ValueError("QUERY_STRUCTURE_POLICY_INVALID")
    started = time.perf_counter()
    namespace = (*service.namespace, "query_structure_v1")
    if slot not in structure_slots(capacity):
        raise ValueError("QUERY_STRUCTURE_SLOT_INVALID")
    cached = service.store.get(namespace, slot)
    prior = copy.deepcopy(cached.value) if cached and not replace_slot else None
    events = service.sources() if source_events is None else source_events
    by_ref = {source["event_id"]: source for source in events}
    pool = sorted(set(source_refs) & set(by_ref))
    cursor = max(([source["observed_at"], source["event_id"]] for source in events), default=[])
    valid = prior is not None and prior["policy"] == policy and _sources_valid(
        service, prior["source_bindings"])
    arrivals = ([source["event_id"] for source in events
                 if [source["observed_at"], source["event_id"]] > prior["arrival_cursor"]]
                if prior is not None and prior["policy"] == policy else [])
    report: dict[str, Any] = {"policy": policy, "visible_sources_enumerated": len(events),
        "source_inventory": "MemoryService.sources full enumeration; "
                            "hidden-row scan count unobserved",
        "retrieved_sources": len(pool), "new_arrivals": len(arrivals), "model_calls": 0,
        "source_bodies_delivered": 0,
        "cache_capacity": capacity, "slot": slot, "replaced_view": cached.value["id"]
        if cached and replace_slot else None, "query_time": date,
        "scope_claim": "retrieved scope plus new arrivals, not full-history semantic coverage"}
    if not force_refresh and policy != "rebuild" and valid and prior is not None \
            and prior["retrieved_sources"] == pool and not arrivals:
        item = copy.deepcopy(prior)
        item["query_time"] = date
        report.update(action="reuse", elapsed_ms=(time.perf_counter() - started) * 1000)
        return item, report

    incremental = policy == "incremental" and valid
    previous = copy.deepcopy(prior["structure"]) if incremental and prior else {}
    bindings = copy.deepcopy(prior["source_bindings"]) if incremental and prior else {}
    known_refs = {binding["source_ref"] for binding in bindings.values()}
    wanted = list(dict.fromkeys([*pool, *arrivals]))
    # A newly selected old Source must be interpreted too, even if it is below
    # the arrival cursor. This prevents source-version caching from hiding scope changes.
    old_pool = set(prior["retrieved_sources"]) if prior else set()
    reopen = set(pool) - old_pool
    if force_refresh:
        # Explicit control supplied these actually opened supports for this refresh.
        # Do not drop their bodies while delivering a newer assistant paraphrase.
        reopen.update(pool)
    if old_pool - set(pool):
        reopen.update(pool)
    delivered = ([ref for ref in wanted
                  if ref not in known_refs or ref in reopen]
                 if incremental else wanted)
    if not bindings and not delivered:
        report.update(action="empty_source_pool", elapsed_ms=(time.perf_counter() - started) * 1000)
        return None, report
    sources = []
    aliases = {binding["source_ref"]: alias for alias, binding in bindings.items()}
    for ref in delivered:
        source = by_ref[ref]
        alias = aliases.get(ref, f"e{len(bindings)}")
        bindings[alias] = {"source_ref": ref, "source_revision": source.get("source_revision", 1)}
        sources.append({"id": alias, "text": body_text(source), "role": source["role"],
            "reported_at": source.get("occurred_at"),
            "calendar_context": source.get("calendar_context")})
    schema = structure_schema(bindings, previous)
    delivered_aliases = {item["id"] for item in sources}
    messages = [{"role": "system", "content": INSTRUCTIONS + (
                    EXPLICIT_REFRESH_INSTRUCTIONS if force_refresh else "")},
                {"role": "user", "content": json.dumps({
                    "question": question, "query_time": date,
                    "previous": previous, "sources": sources,
                    "ingestion_observations": [{"source": alias,
                        "source_revision": binding["source_revision"],
                        "captured_at": by_ref[binding["source_ref"]]["observed_at"]}
                        for alias, binding in bindings.items()],
                    "source_directory": [{"id": key, "body_delivered": key in delivered_aliases,
                        "role": by_ref[binding["source_ref"]]["role"],
                        "reported_at": by_ref[binding["source_ref"]].get("occurred_at")}
                        for key, binding in bindings.items()], "current_scope_sources": [
                        key for key, binding in bindings.items() if binding["source_ref"] in pool],
                    "response_schema": schema,
                }, ensure_ascii=False, separators=(",", ":"))}]
    response = call(messages, schema)
    Draft202012Validator(schema).validate(response)
    nodes = copy.deepcopy(previous.get("nodes", {}))
    rules = copy.deepcopy(previous.get("rules", {}))
    for key in response["remove"]:
        nodes.pop(key)
    for key in response["remove_rules"]:
        rules.pop(key)
    for key, target in (("nodes", nodes), ("rules", rules)):
        updates = {item["id"]: {k: copy.deepcopy(v) for k, v in item.items() if k != "id"}
                   for item in response[key]}
        if len(updates) != len(response[key]):
            raise FunctionalRejection("QUERY_STRUCTURE_NAME_REPEATED")
        target.update(updates)
    for rule in rules.values():
        names = {rule["target"], *rule["all"], *(ref for route in rule["any"] for ref in route)}
        if not names <= set(nodes):
            raise FunctionalRejection("QUERY_STRUCTURE_RULE_NODE_UNAVAILABLE")
    structure = {"scope": response["scope"], "nodes": nodes, "rules": rules,
                 "unresolved": response["unresolved"]}
    revision = cached.value["revision"] + 1 if cached else 1
    identifier = (f"query-structure:{revision}" if slot == "current"
                  else f"query-structure:{slot}:{revision}")
    item = {"id": identifier, "kind": "query_structure", "policy": policy,
        "revision": revision, "structure": structure, "source_bindings": bindings,
        "built_for": question, "slot": slot,
        "arrival_cursor": cursor, "retrieved_sources": pool, "query_time": date,
        "arrival_boundary_refs": [s["event_id"] for s in events
                                  if cursor and s["observed_at"] == cursor[0]],
        "index_text": response["scope"], "visibility": "visible", "body_delivered": True,
        "semantics": "source_bound_model_interpretation; all AND (OR of AND any routes); "
                     "unknown is not false; apply temporal rules at current query time"}
    saved = copy.deepcopy(item)
    if policy == "rebuild":
        # Only the observed arrival cursor is retained in the no-cache control;
        # it receives the same newly arrived events as the cached conditions.
        saved.update(structure={}, source_bindings={})
    service.store.put(namespace, slot, saved, index=False)
    if capacity > 1:
        touch_structure(service, slot)
    report.update(action="refresh" if incremental else "build", model_calls=1,
                  source_bodies_delivered=len(sources), node_count=len(nodes),
                  rule_count=len(rules),
                  elapsed_ms=(time.perf_counter() - started) * 1000)
    return item, report
