"""Simple request/scope cache baseline over the same finite evidence operations."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from milai_lab.memory.retrieval import _lexical_tokens
from milai_lab.methods.evidence_selection import (
    coverage,
    interpretation_handoff,
    interpretation_only,
    original_evidence_action,
    original_terms,
    pending_content,
    request_terms,
    view_request_context,
)
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
)


def text_overlap(left: str, right: str) -> float:
    """Binary token cosine; lexical scope matching is not semantic certification."""
    a, b = set(_lexical_tokens(left)), set(_lexical_tokens(right))
    return len(a & b) / (len(a) * len(b)) ** 0.5 if a and b else 0.0


def source_relevance(view: dict[str, Any], task: dict[str, Any],
                     events: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """Rank navigation using requirements and actual visible text when available.

    A node's source association is only an interpretation. An observed original
    takes precedence over that node for its own score, including a zero match.
    Unseen bodies remain navigation-only; the policy performs no hidden reads.
    """
    needs = request_terms(task)
    context = json.dumps({"request": task["request"], "read_goal": task.get("read_goal"),
        "retrieval_request": view_request_context(task.get("retrieval_request"))},
        ensure_ascii=False)

    def relevance(text: str) -> tuple[float, float]:
        terms = set(_lexical_tokens(text))
        return sum(len(terms & point) / len(point) for point in needs), text_overlap(context, text)

    scores: dict[str, tuple[float, float]] = {}
    structure = view.get("interpretation", {})
    for node in structure.get("nodes", {}).values():
        score = relevance(node["text"])
        for alias in node.get("evidence", []):
            binding = view["source_bindings"][alias]
            ref = binding["source_ref"]
            scores[ref] = max(scores.get(ref, (0.0, 0.0)), score)
    bound = {binding["source_ref"] for binding in view["source_bindings"].values()}
    for event in events:
        if event["source_ref"] in bound:
            scores[event["source_ref"]] = relevance(event["content"])
    return scores


def _request_context(task: dict[str, Any]) -> dict[str, Any]:
    request = task.get("retrieval_request") or {"read_goal": task.get("read_goal")}
    context = view_request_context(request) or {}
    return {key: value for key, value in context.items() if key != "query" and value is not None}


@dataclass
class CacheMemoryPolicy:
    """Reuse matching clean Views, refresh on arrivals, and read requested originals.

    Scope threshold and read cap are explicit experiment parameters. Decisions use
    ordinary request text, visible View nodes/bindings and actual arrival metadata.
    No case identifiers, outcome labels or fixed domain vocabulary are consulted.
    """

    reads: int = 4
    min_scope_overlap: float = 0.35

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        original = original_evidence_action(state, actions, self.reads)
        if original is not None:
            return original
        selected_view = interpretation_handoff(state, actions)
        if selected_view is not None:
            return selected_view
        handoff = next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)
        goal = state.task.get("read_goal")
        originals = isinstance(goal, dict) and "original_source" in goal.get("evidence", [])
        views = [v for v in state.views if v["visibility"] == "visible"]
        compatible = [v for v in views if _request_context({
            "retrieval_request": v.get("retrieval_request")}) == _request_context(state.task)]
        query = state.task["request"]
        view = max(compatible or views, key=lambda v: text_overlap(
            query, str(v.get("built_for", ""))
                   + " " + str(v.get("scope", ""))), default=None)
        matching = view is not None and view in compatible and text_overlap(query,
            str(view.get("built_for", "")) + " " + str(view.get("scope", ""))) >= (
                self.min_scope_overlap)
        last = state.last_result
        delivered_view = last and last.get("ok") and last["action"]["kind"] in {
            "USE_VIEW", "REFRESH_VIEW"}
        if delivered_view and not originals:
            return handoff
        pending = view is not None and pending_content(view, state.new_events)
        if not delivered_view and not originals and (not matching or pending):
            refresh = next((a for a in actions if a.kind == "REFRESH_VIEW"
                and (view is None or a.parameters.get("slot") == view["slot"])), None)
            if refresh is not None and not (last and last["action"]["kind"] == "REFRESH_VIEW"):
                return refresh.id
        if view is not None and matching and not pending and not originals:
            uses = [a for a in actions if a.kind == "USE_VIEW" and a.target == view["id"]]
            use = max(uses, key=lambda a: interpretation_only(state.task)
                      and a.parameters.get("replace_delivery", False), default=None)
            if use is not None:
                return use.id
        if originals and view is not None:
            acquired = (state.observed_materials if state.observed_materials is not None
                        else state.visible_evidence)
            if sum(item["kind"] == "original_source" for item in acquired) >= self.reads:
                return handoff
            scores = source_relevance(view, state.task, state.new_events)
            reads = [a for a in actions if a.kind == "READ"
                     and "observed_source" in a.parameters
                     and not a.parameters.get("observe_only")]
            if reads:
                return max(reads, key=lambda a: scores.get(
                    a.parameters["observed_source"]["source_ref"], (0.0, 0.0))).id
            if any(item["kind"] == "original_source" for item in acquired):
                return handoff
        return FixedContextMemoryPolicy(self.reads).choose(state, actions)


@dataclass
class IncrementalCacheMemoryPolicy(CacheMemoryPolicy):
    """Optional request-local cache route with a bounded raw-source supplement.

    Matching retains the original purpose/object/time scope checks. Pending
    arrivals stay pending when an old View is used; a lexical READ nomination is
    navigation, not a judgment that the arrival updates or verifies a fact. The
    executor supplies every binding and admits the final complete packet.
    """

    incremental_reads: int = 1
    _state: MemoryControlState | None = field(default=None, init=False, repr=False)
    _initial_refs: set[str] | None = field(default=None, init=False, repr=False)
    _reads_chosen: int = field(default=0, init=False, repr=False)
    _view_attempted: bool = field(default=False, init=False, repr=False)
    _refresh_chosen: bool = field(default=False, init=False, repr=False)

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        if self._state is not state:
            self._state = state
            self._initial_refs = None
            self._reads_chosen = 0
            self._view_attempted = self._refresh_chosen = False
        goal_value = state.task.get("read_goal")
        goal = goal_value if isinstance(goal_value, dict) else {}
        if "original_source" in goal.get("evidence", []):
            return super().choose(state, actions)
        views = [view for view in state.views if view["visibility"] == "visible"]
        compatible = [view for view in views if _request_context({
            "retrieval_request": view.get("retrieval_request")}) == _request_context(state.task)
            and view.get("query_time") == state.task["query_time"]]
        view = max(compatible or views, key=lambda item: text_overlap(state.task["request"],
            str(item.get("built_for", "")) + " " + str(item.get("scope", ""))), default=None)
        matching = view is not None and view in compatible and text_overlap(
            state.task["request"], str(view.get("built_for", "")) + " "
            + str(view.get("scope", ""))) >= self.min_scope_overlap
        if self._initial_refs is None:
            self._initial_refs = (set(view["pending_events"]) if matching and view is not None
                                  else {event["source_ref"] for event in state.new_events})
        if not matching:
            refresh = next((action for action in actions if action.kind == "REFRESH_VIEW"
                and (view is None or action.parameters.get("slot") == view["slot"])), None)
            if refresh is not None:
                self._view_attempted = self._refresh_chosen = True
                return refresh.id
            return FixedContextMemoryPolicy(self.reads).choose(state, actions)
        assert view is not None
        if interpretation_only(state.task):
            return super().choose(state, actions)
        # Known evidence has already passed the native delivered-snapshot check.
        # Require the actual locator table, not just a revision number or text match.
        known_view = any(item["kind"] == "query_structure"
            and item.get("revision") == view["revision"]
            and item.get("query_time") == view["query_time"]
            and item.get("interpretation") == view.get("interpretation")
            and item.get("source_locations") == view["source_bindings"]
            for item in state.task.get("known_evidence", []))
        if not known_view and not self._view_attempted:
            use = next((action for action in actions if action.kind == "USE_VIEW"
                        and action.target == view["id"]), None)
            if use is not None:
                self._view_attempted = True
                return use.id
        events = {event["source_ref"]: event for event in state.new_events
                  if event["source_ref"] in self._initial_refs
                  and event.get("capture_context") != "given_retrieval_request"}
        needs = request_terms(state.task)
        context = json.dumps({"request": state.task["request"], "read_goal": goal},
                             ensure_ascii=False)

        def read_score(action: MemoryAction) -> tuple[float, float, int]:
            text = events[action.parameters["observed_source"]["source_ref"]]["content"]
            return (coverage(set(_lexical_tokens(text)), needs),
                    text_overlap(context, text), -len(text))

        reads = [action for action in actions if action.kind == "READ"
                 and action.parameters.get("observed_source", {}).get("source_ref") in events
                 and (state.observed_materials is None or action.parameters.get("observe_only"))]
        if self._reads_chosen < self.incremental_reads and reads:
            read = max(reads, key=read_score)
            if read_score(read)[:2] > (0.0, 0.0):
                self._reads_chosen += 1
                return read.id
        pending_count = view.get("pending_event_count", len(view["pending_events"]))
        if pending_count > len(view["pending_events"]) and not self._refresh_chosen:
            refresh = next((action for action in actions if action.kind == "REFRESH_VIEW"
                            and action.parameters.get("slot") == view["slot"]), None)
            if refresh is not None:
                self._view_attempted = self._refresh_chosen = True
                return refresh.id
        observed = {int(item["label"][1:]): item for item in [
            *state.visible_evidence, *(state.observed_evidence or [])]}
        current = [int(item["label"][1:]) for item in state.visible_evidence]
        retrieved = {item["item_index"]: item["evidence"] for item in state.retrieved_scopes or []}
        raw = {index for index, item in {**observed, **retrieved}.items()
               if item["kind"] == "original_source"}
        view_indices = {index for index, item in observed.items()
                        if item["kind"] == "query_structure"}
        known_terms: set[str] = set()
        for item in state.task.get("known_evidence", []):
            known_terms.update(original_terms(item))

        def delivery_score(action: MemoryAction) -> tuple[bool, bool, float, int]:
            indices = action.parameters.get("delivery_indices", current)
            narrowed = action.parameters.get("retrieved_scope_indices", [])
            packet = [retrieved[index] if index in narrowed else observed[index]
                      for index in indices]
            terms = known_terms.union(*(original_terms(item) for item in packet))
            return (bool(raw.intersection(indices)),
                    not known_view and bool(view_indices.intersection(indices)),
                    coverage(terms, needs), -len(json.dumps(packet, ensure_ascii=False)))

        return max((action for action in actions if action.kind == "HANDOFF"),
                   key=delivery_score).id
