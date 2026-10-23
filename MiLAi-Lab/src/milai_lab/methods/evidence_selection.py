"""Request-aware lexical baseline over actually observed original evidence.

Coverage is a policy heuristic, not semantic entailment. The executor owns source
visibility, read allowance and complete-packet admission; this module only chooses
among its supplied actions. It never reads a Store or changes a source body.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from milai_lab.memory.retrieval import _lexical_tokens

if TYPE_CHECKING:
    from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


def request_terms(task: dict[str, Any]) -> list[set[str]]:
    goal = task.get("read_goal")
    points = goal.get("required_points", []) if isinstance(goal, dict) else []
    return [terms for point in points or [task["request"]]
            if (terms := set(_lexical_tokens(point)))]


def original_terms(material: dict[str, Any]) -> set[str]:
    if material["kind"] != "original_source" or material.get("body_delivered") is False:
        return set()
    return set(_lexical_tokens(" ".join(row["content"]
        for row in material.get("evidence", [])
        if row.get("capture_context") != "given_retrieval_request")))


def coverage(terms: set[str], needs: list[set[str]]) -> float:
    return sum(len(terms & point) / len(point) for point in needs)


def pending_content(view: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    """Supplied retrieval probes remain stored requests, not new domain observations.

    Unseen pending arrivals and ordinary user messages still count. In particular,
    a user's question may also contain a new preference; no text classifier or
    identical-body deduplication is used here.
    """
    requests = sum(1 for event in events
                   if event.get("capture_context") == "given_retrieval_request"
                   and event["source_ref"] in view["pending_events"])
    count: int = view.get("pending_event_count", len(view["pending_events"]))
    return count > requests


def view_request_context(request: dict[str, Any] | None) -> dict[str, Any] | None:
    """Known deliveries and per-call limits do not change a View's semantic scope."""
    if request is None:
        return None
    scope = {key: value for key, value in request.items() if key not in {"limits", "task_context"}}
    context = {key: value for key, value in request.get("task_context", {}).items()
               if key != "known_evidence_refs"}
    if context:
        scope["task_context"] = context
    return scope


def original_evidence_action(
    state: MemoryControlState, actions: list[MemoryAction], reads: int,
) -> str | None:
    """Use observation-only reads and select the actual return packet for raw requests.

    Unstructured/summary requests retain their policy's ordinary route. Exact
    lexical coverage permits this simple baseline to stop; it is not an oracle
    and must be evaluated against actual source meaning and the Host outcome.
    """
    goal = state.task.get("read_goal")
    if (state.observed_materials is None or not isinstance(goal, dict)
            or "original_source" not in goal.get("evidence", [])):
        return None
    needs = request_terms(state.task)
    known: set[str] = set()
    for material in state.task.get("known_evidence", []):
        known.update(original_terms(material))
    observed = {int(item["label"][1:]): item
                for item in [*state.visible_evidence, *(state.observed_evidence or [])]}
    raw = {i: original_terms(item) for i, item in observed.items()
           if item["kind"] == "original_source" and any(
               row.get("capture_context") != "given_retrieval_request"
               for row in item.get("evidence", []))}
    acquired = known.union(*raw.values())
    current = [m["item_index"] for m in state.observed_materials if m["selected"]]

    def handoff() -> str:
        options = [a for a in actions if a.kind == "HANDOFF"]

        def selected(action: MemoryAction) -> list[int]:
            indices: list[int] = action.parameters.get("delivery_indices", current)
            return indices

        def score(action: MemoryAction) -> tuple[float, int]:
            indices = selected(action)
            terms = known.union(*(raw.get(i, set()) for i in indices))
            size = len(json.dumps([observed[i] for i in indices], ensure_ascii=False))
            return coverage(terms, needs), -size

        best = max(options, key=score)
        # With no lexical signal, keep a real observation rather than pretending
        # that an empty packet resolves a semantically opaque request.
        if not selected(best) and raw and coverage(known, needs) == 0:
            best = next((a for a in options if any(i in raw for i in selected(a))), best)
        return best.id

    if (len(raw) >= reads or state.budget.get("remaining_control_steps") == 1
            or (needs and coverage(acquired, needs) == len(needs))):
        return handoff()

    search = next((a for a in actions if a.kind == "SEARCH"), None)
    if not observed and not state.pending_candidates and search is not None:
        # Retrieve actual source candidates before ranking only View-bound locations.
        return search.id
    candidates = {c["item_index"]: c for c in state.pending_candidates}
    events = {e["source_ref"]: e for e in state.new_events}
    available = [a for a in actions if a.kind == "READ" and a.parameters.get("observe_only")
                 and ("observed_source" in a.parameters
                      or candidates.get(a.parameters.get("index"), {}).get("kind")
                      == "original_source")]

    def read_score(action: MemoryAction) -> float:
        if "observed_source" in action.parameters:
            event = events.get(action.parameters["observed_source"]["source_ref"], {})
            if event.get("capture_context") == "given_retrieval_request":
                return -1.0
            text = event.get("content", "")
        else:
            candidate = candidates[action.parameters["index"]]
            if candidate.get("capture_contexts") == ["given_retrieval_request"]:
                return -1.0
            text = candidate["excerpt"]
        return coverage(set(_lexical_tokens(text)) - acquired, needs)

    if available:
        best = max(available, key=lambda a: (read_score(a), "index" in a.parameters))
        if read_score(best) >= 0:
            return best.id
    return search.id if search is not None else handoff()
