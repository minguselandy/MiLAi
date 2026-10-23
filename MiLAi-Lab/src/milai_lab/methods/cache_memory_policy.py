"""Simple request/scope cache baseline over the same finite evidence operations."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from milai_lab.memory.retrieval import _lexical_tokens
from milai_lab.methods.evidence_selection import (
    original_evidence_action,
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
            use = next((a for a in actions if a.kind == "USE_VIEW"
                        and a.target == view["id"]), None)
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
