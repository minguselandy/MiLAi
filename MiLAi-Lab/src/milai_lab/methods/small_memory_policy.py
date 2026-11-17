"""A replaceable score adapter on the existing finite-operation executor."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from milai_lab.methods.control_observation import control_input
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
)


@dataclass
class PolicyScores:
    action_ids: list[str]
    scores: list[float]
    predicted_value: float | None = None
    predicted_cost: list[float] | None = None


class ControlScorer(Protocol):
    def score(self, online: dict[str, Any]) -> PolicyScores: ...


def bound_prior_menu(state: MemoryControlState,
                     actions: list[MemoryAction]) -> list[MemoryAction]:
    """Order a baseline's input by visible ranks/bindings, not action IDs or presentation.

    This does not prune the legal menu or read a Source. The optional model
    configuration declares this order; historical priors keep their offered order.
    """
    ranks = {p["item_index"]: p.get("control_pool_rank", p["item_index"])
             for p in state.pending_candidates}

    def order(action: MemoryAction) -> tuple[Any, ...]:
        p = action.parameters
        binding = json.dumps({"kind": action.kind, "target": action.target, "parameters": p},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if action.kind == "READ":
            index = p.get("index")
            rank = ranks.get(index, index) if isinstance(index, int) else float("inf")
            return (action.kind, rank, bool(p.get("history_directory")),
                    bool(p.get("observe_only")), not bool(p.get("expand_context")), binding)
        if action.kind == "HANDOFF":
            return (action.kind, bool(p), tuple(p.get("delivery_indices", [])),
                    tuple(p.get("retrieved_scope_indices", [])), binding)
        if action.kind == "SEARCH":
            query_order = {"request": 0, "required_point": 1, "observed_material": 2,
                           "known_material": 3}
            return (action.kind, query_order.get(p.get("query_from", "request"), 4),
                    p.get("index", -1), p.get("limit", 0), binding)
        return (action.kind, binding)

    return sorted(actions, key=order)


@dataclass
class SmallMemoryPolicy:
    scorer: ControlScorer
    record: Callable[[dict[str, Any]], None] = lambda event: None
    calls: int = field(default=0, init=False)

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        started = time.perf_counter()
        result = self.scorer.score(control_input(state, actions))
        if result.action_ids != [a.id for a in actions] or len(result.scores) != len(actions):
            raise ValueError("Policy scores must align with the complete offered menu")
        import math

        if not all(math.isfinite(s) for s in result.scores):
            raise ValueError("Policy scores must be finite")
        selected = result.action_ids[max(range(len(actions)), key=result.scores.__getitem__)]
        self.calls += 1
        self.record({"event": "small_memory_policy_result", "model_call": self.calls,
                     "selected": selected, **asdict(result),
                     "wall_seconds": time.perf_counter() - started})
        return selected


class QueryPassageEncoder(Protocol):
    def encode(self, texts: list[str], *, text_role: str = "query") -> Any: ...


@dataclass
class EncoderCosineMemoryPolicy:
    """Fixed read budget, semantic navigation ranking, then an admitted real packet.

    This baseline encodes only the supplied question and legal visible candidate
    excerpts. Reading opens the original material through the shared executor.
    Retrieval indices explicitly break score ties; aliases/menu position do not.
    """
    encoder: QueryPassageEncoder
    reads: int = 4

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        handoff = FixedContextMemoryPolicy(self.reads).choose(
            state, [a for a in actions if a.kind == "HANDOFF"])
        acquired = {item["item_index"] for item in state.observed_materials or []
                    if item["kind"] == "original_source"}
        if len(acquired) >= self.reads or state.budget.get("remaining_control_steps") == 1:
            return handoff
        search = next((a for a in actions if a.kind == "SEARCH"), None)
        if search is not None:
            return search.id
        candidates = {item["item_index"]: item for item in state.pending_candidates}
        options: dict[int, list[MemoryAction]] = {}
        for action in actions:
            index = action.parameters.get("index")
            if (action.kind == "READ" and isinstance(index, int)
                    and index in candidates and index not in acquired
                    and candidates[index]["kind"] == "original_source"
                    and not action.parameters.get("observe_only")
                    and isinstance(candidates[index].get("excerpt"), str)):
                options.setdefault(index, []).append(action)
        if not options:
            return handoff
        import torch  # type: ignore[import-not-found]

        indices = sorted(options)
        with torch.no_grad():
            query = self.encoder.encode([state.task["request"]], text_role="query")
            passages = self.encoder.encode([candidates[i]["excerpt"] for i in indices],
                                           text_role="passage")
            scores = (passages @ query[0]).float().cpu().tolist()
        import math

        if len(scores) != len(indices) or not all(math.isfinite(s) for s in scores):
            raise ValueError("Visible-candidate cosine scores must be finite and aligned")
        selected = indices[max(range(len(indices)), key=scores.__getitem__)]
        # Prefer the same original context expansion as the fixed-context baseline,
        # only when that complete bound action is actually offered.
        return max(options[selected], key=lambda a: bool(a.parameters.get("expand_context"))).id
