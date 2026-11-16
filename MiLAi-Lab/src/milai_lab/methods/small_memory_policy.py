"""A replaceable score adapter on the existing finite-operation executor."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from milai_lab.methods.control_observation import control_input
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


@dataclass
class PolicyScores:
    action_ids: list[str]
    scores: list[float]
    predicted_value: float | None = None
    predicted_cost: list[float] | None = None


class ControlScorer(Protocol):
    def score(self, online: dict[str, Any]) -> PolicyScores: ...


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
