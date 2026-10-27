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
QueryStructureBuilder = Literal["generated", "extractive"]
BUILDERS = ("generated", "extractive")
EXTRACTIVE_SEMANTICS = (
    "source_bound_literal_excerpts; each node quotes one selected source body verbatim. "
    "Use its source metadata for role and reporting context. Questions, proposals, conditions "
    "and prior assistant text retain their original meaning; quoting does not confirm them. "
    "No semantic classification, inferred rule or event date has been added."
)

INSTRUCTIONS = (
    "Build a reusable local interpretation of the delivered source scope. Keep self-contained "
    "facts, conditional rules, temporal boundaries and uncertainty, not an answer to this query. "
    "Capture the independently changeable facts in the selected scope, so another wording or "
    "task can use them. scope describes that scope, not proof that all history was examined. "
    "Old nodes and rules in previous are model interpretations, not original evidence. "
    "sources contains newly delivered original bodies in capture order, with session identifiers "
    "and capture context. given_retrieval_request marks a supplied memory query; it does not "
    "provide a new domain observation or independently confirm the queried facts. "
    "for captured conversation context. source_directory binds the old and new "
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
    "does not support a relation, retain plain text. Return the supplied schema. "
    "Examples of faithful source-to-node transformations (not additional evidence): "
    "User: 'Could you confirm the transfer completed?' -> reported node: "
    "'The user asks whether the transfer completed'; unresolved: 'Transfer completion "
    "has not been established by this question.' Do not write 'The user confirmed completion'. "
    "Tool: {status: preview, proposed_amount: 40} -> reported node: "
    "'The preview proposes an amount of 40; execution is not established.' "
    "Source: 'Access is allowed if training is complete and the permit is valid' -> "
    "self-contained node: 'If training is complete AND the permit is valid, access is allowed.' "
    "This source does not assert either prerequisite or current access. "
    "Source reported_at=null with a captured_at value -> omit temporal unless the body "
    "itself states an event or effective date; the capture time stays in ingestion metadata. "
    "A direct statement such as 'The agreed limit is 40' can remain a plain reported node."
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
    sources = {}
    for alias, binding in item["source_bindings"].items():
        source = service.source(binding["source_ref"])
        if source is None or source.get("source_revision", 1) != binding["source_revision"]:
            return {"id": item["id"], "kind": "query_structure", "body_delivered": False,
                    "visibility": "support_unavailable"}
        sources[alias] = source
    # Read authoritative capture metadata, including for older cached Views.
    # No original body is projected and no cache migration/write is required.
    return {**copy.deepcopy(item), "source_metadata": _source_metadata(sources)}


def _source_metadata(sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {alias: {"role": source["role"], "origin": source["origin"],
        "session": source["session"], "reported_at": source.get("occurred_at"),
        "captured_at": source["observed_at"],
        **{key: source[key] for key in ("capture_context", "calendar_context") if key in source}}
        for alias, source in sources.items()}


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
    builder: QueryStructureBuilder = "generated",
    source_events: list[dict[str, Any]] | None = None,
    force_refresh: bool = False,
    slot: str = "current",
    capacity: int = 1,
    replace_slot: bool = False,
    retrieval_request: dict[str, Any] | None = None,
    arrival_coverage: dict[str, Any] | None = None,
    excluded_source_refs: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Reuse, reconstruct or incrementally refresh the same actually retrieved scope.

    A changed retrieval scope triggers interpretation even if all source versions
    are unchanged. A new arrival triggers it even if retrieval misses that source.
    Different question wording/time alone does not invalidate the intermediate
    rules: their current application belongs to the common Reader.
    """
    if policy not in POLICIES:
        raise ValueError("QUERY_STRUCTURE_POLICY_INVALID")
    if builder not in BUILDERS:
        raise ValueError("QUERY_STRUCTURE_BUILDER_INVALID")
    started = time.perf_counter()
    namespace = (*service.namespace, "query_structure_v1")
    if slot not in structure_slots(capacity):
        raise ValueError("QUERY_STRUCTURE_SLOT_INVALID")
    cached = service.store.get(namespace, slot)
    prior = copy.deepcopy(cached.value) if cached and not replace_slot else None
    # Existing caches without this field were built by the generator. Changing
    # the builder starts from the selected sources, not the other builder's text.
    if prior is not None and prior.get("builder", "generated") != builder:
        prior = None
    events = service.sources() if source_events is None else source_events
    by_ref = {source["event_id"]: source for source in events}
    pool = sorted(set(source_refs) & set(by_ref))
    observed_cursor = max(([source["observed_at"], source["event_id"]]
                           for source in events), default=[])
    observed_boundary = [source["event_id"] for source in events
                         if observed_cursor and source["observed_at"] == observed_cursor[0]]
    if arrival_coverage is not None:
        # Search may select a source beyond the observed arrival prefix. Its body
        # can support a view without acknowledging the intervening unseen sources.
        observed_cursor = arrival_coverage["cursor"]
        observed_boundary = arrival_coverage["boundary_refs"]
    # Reopening a deferred source below the watermark must not forget later arrivals.
    cursor = max(prior["arrival_cursor"] if prior else [], observed_cursor)
    boundary_refs = list(dict.fromkeys([
        *(prior.get("arrival_boundary_refs", [prior["arrival_cursor"][1]])
          if prior and prior["arrival_cursor"] and cursor
          and prior["arrival_cursor"][0] == cursor[0] else []),
        *(observed_boundary if observed_cursor and cursor
          and observed_cursor[0] == cursor[0] else [])]))
    valid = prior is not None and prior["policy"] == policy and _sources_valid(
        service, prior["source_bindings"])
    arrivals = ([source["event_id"] for source in events
                 if source["event_id"] in prior.get("deferred_source_refs", [])
                 or not prior["arrival_cursor"]
                 or source["observed_at"] > prior["arrival_cursor"][0]
                 or (source["observed_at"] == prior["arrival_cursor"][0]
                     and source["event_id"] not in prior.get(
                         "arrival_boundary_refs", [prior["arrival_cursor"][1]]))]
                if prior is not None and prior["policy"] == policy else [])
    report: dict[str, Any] = {"policy": policy, "visible_sources_enumerated": len(events),
        **({"builder": builder} if builder != "generated" else {}),
        "source_inventory": ("MemoryService.sources full enumeration; "
                             "hidden-row scan count unobserved" if source_events is None else
                             "explicit source events; upstream discovery counted separately"),
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
    # Allocate new aliases in presentation order; existing cache bindings stay fixed.
    for ref in sorted(delivered, key=lambda ref: (by_ref[ref]["observed_at"], ref)):
        source = by_ref[ref]
        alias = aliases.get(ref, f"e{len(bindings)}")
        bindings[alias] = {"source_ref": ref, "source_revision": source.get("source_revision", 1)}
        sources.append({"id": alias, "text": body_text(source), "role": source["role"],
            "origin": source["origin"],
            **({"capture_context": source["capture_context"]}
               if "capture_context" in source else {}),
            "session": source["session"],
            "reported_at": source.get("occurred_at"),
            "calendar_context": source.get("calendar_context")})
    schema = structure_schema(bindings, previous)
    response: dict[str, Any]
    if builder == "extractive":
        # The retrieved scope is already selected by the ordinary source path.
        # Keep whole bodies, including questions and conditions; no sentence filter
        # or synthesized fact is needed for this generation-free baseline.
        response = {"scope": "Literal source excerpts.",
            "nodes": [{"id": "n" + source["id"][1:], "text": source["text"],
                       "kind": "reported", "evidence": [source["id"]]}
                      for source in sources],
            "remove": [], "rules": [], "remove_rules": [], "unresolved": []}
    else:
        delivered_aliases = {item["id"] for item in sources}
        messages = [{"role": "system", "content": INSTRUCTIONS + (
                        EXPLICIT_REFRESH_INSTRUCTIONS if force_refresh else "")},
                    {"role": "user", "content": json.dumps({
                        "question": question, "query_time": date,
                        **({"retrieval_request": retrieval_request} if retrieval_request else {}),
                        "previous": previous, "sources": sources,
                        "ingestion_observations": [{"source": alias,
                            "source_revision": binding["source_revision"],
                            "captured_at": by_ref[binding["source_ref"]]["observed_at"]}
                            for alias, binding in bindings.items()],
                        "source_directory": [{"id": key, "body_delivered": key in delivered_aliases,
                            "role": by_ref[binding["source_ref"]]["role"],
                            "origin": by_ref[binding["source_ref"]]["origin"],
                            **{field: by_ref[binding["source_ref"]][field]
                               for field in ("capture_context", "calendar_context")
                               if field in by_ref[binding["source_ref"]]},
                            "session": by_ref[binding["source_ref"]]["session"],
                            "reported_at": by_ref[binding["source_ref"]].get("occurred_at")}
                            for key, binding in bindings.items()], "current_scope_sources": [
                            key for key, binding in bindings.items()
                            if binding["source_ref"] in pool],
                        "response_schema": schema,
                    }, ensure_ascii=False, separators=(",", ":"))}]
        response = call(messages, schema)
    Draft202012Validator(schema).validate(response)
    nodes = copy.deepcopy(previous.get("nodes", {}))
    rules = copy.deepcopy(previous.get("rules", {}))
    # Removal lists name a set of prior objects; repeating a name adds no operation.
    for key in dict.fromkeys(response["remove"]):
        nodes.pop(key)
    for key in dict.fromkeys(response["remove_rules"]):
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
    # A current request can precede a later tool arrival that advances the cursor.
    # Keep that occurrence pending until a future refresh actually receives its body.
    interpreted = {binding["source_ref"] for binding in bindings.values()}
    deferred_candidates = [ref for ref in dict.fromkeys([
        *(prior.get("deferred_source_refs", []) if prior else []), *excluded_source_refs])
        if ref not in interpreted]
    deferred = [ref for ref in deferred_candidates if service.source(ref) is not None]
    if deferred_candidates:
        report["deferred_source_visibility_checks"] = len(deferred_candidates)
    revision = cached.value["revision"] + 1 if cached else 1
    identifier = (f"query-structure:{revision}" if slot == "current"
                  else f"query-structure:{slot}:{revision}")
    item = {"id": identifier, "kind": "query_structure", "policy": policy,
        **({"builder": builder} if builder != "generated" else {}),
        "revision": revision, "structure": structure, "source_bindings": bindings,
        "source_metadata": _source_metadata({alias: by_ref[binding["source_ref"]]
                                             for alias, binding in bindings.items()}),
        "built_for": question, "slot": slot,
        **({"retrieval_request": retrieval_request} if retrieval_request else {}),
        "arrival_cursor": cursor, "retrieved_sources": pool, "query_time": date,
        "arrival_boundary_refs": boundary_refs,
        **({"deferred_source_refs": deferred} if deferred else {}),
        "index_text": response["scope"], "visibility": "visible", "body_delivered": True,
        "semantics": (EXTRACTIVE_SEMANTICS if builder == "extractive" else
                      "source_bound_model_interpretation; all AND (OR of AND any routes); "
                      "unknown is not false; apply temporal rules at current query time")}
    saved = copy.deepcopy(item)
    if policy == "rebuild":
        # Only the observed arrival cursor is retained in the no-cache control;
        # it receives the same newly arrived events as the cached conditions.
        saved.update(structure={}, source_bindings={}, source_metadata={})
    service.store.put(namespace, slot, saved, index=False)
    if capacity > 1:
        touch_structure(service, slot)
    report.update(action="refresh" if incremental else "build",
                  model_calls=int(builder == "generated"),
                  source_bodies_delivered=len(sources), node_count=len(nodes),
                  rule_count=len(rules),
                  elapsed_ms=(time.perf_counter() - started) * 1000)
    return item, report
