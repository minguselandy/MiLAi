"""Isolated event trajectories through injected ordinary public memory calls.

This layer owns only time and dispatch. Tools/runners construct a separate
owner, temporary Store and actual application sandbox, then bind the existing
ingest/maintain/recall/consolidate/resume/forget calls. Evaluation truth and
future events are never passed to runtime callbacks.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

SimulationOperation = Literal["ingest", "maintain", "recall", "consolidate", "resume", "forget"]
PublicCall = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(slots=True)
class VirtualClock:
    """UTC clock passed directly to MemoryService; gaps change no factual record."""

    current: datetime

    def __post_init__(self) -> None:
        if self.current.tzinfo is None:
            raise ValueError("SIMULATION_CLOCK_REQUIRES_TIMEZONE")
        self.current = self.current.astimezone(UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, elapsed: timedelta) -> datetime:
        if elapsed < timedelta():
            raise ValueError("SIMULATION_CLOCK_CANNOT_MOVE_BACKWARD")
        self.current += elapsed
        return self.current


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    event_id: str
    operation: SimulationOperation | Literal["gap"]
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SimulationCallbacks:
    """Caller-bound public paths; no simulator-specific correct-state mutation."""

    ingest: PublicCall
    maintain: PublicCall
    recall: PublicCall
    consolidate: PublicCall
    resume: PublicCall
    forget: PublicCall
    snapshot: Callable[[], dict[str, Any]]


def fact(
    event_id: str,
    content: str,
    *,
    role: Literal["user", "assistant"] = "user",
) -> SimulationEvent:
    return SimulationEvent(event_id, "ingest", {"content": content, "role": role})


def correction(event_id: str, content: str) -> SimulationEvent:
    """A current explicit statement; its past/future scope remains in actual text."""
    return fact(event_id, content)


def exception(event_id: str, content: str) -> SimulationEvent:
    return fact(event_id, content)


def cancellation(event_id: str, content: str) -> SimulationEvent:
    return fact(event_id, content)


def gap(event_id: str, *, days: float = 0, seconds: float = 0) -> SimulationEvent:
    return SimulationEvent(
        event_id, "gap", {"seconds": timedelta(days=days, seconds=seconds).total_seconds()}
    )


def action(event_id: str, operation: SimulationOperation, **input: Any) -> SimulationEvent:
    return SimulationEvent(event_id, operation, input)


class MemorySimulation:
    """One browsing trajectory with a virtual clock and caller-owned isolation."""

    def __init__(
        self,
        *,
        owner: str,
        clock: VirtualClock,
        callbacks: SimulationCallbacks,
    ) -> None:
        self.owner, self.clock, self.callbacks = owner, clock, callbacks
        self.trajectory: list[dict[str, Any]] = []

    def step(self, event: SimulationEvent) -> dict[str, Any]:
        if not event.event_id:
            raise ValueError("SIMULATION_EVENT_ID_REQUIRED")
        if event.operation == "gap":
            self.clock.advance(timedelta(seconds=event.input["seconds"]))
            result: dict[str, Any] = {"status": "elapsed", "now": self.clock().isoformat()}
        else:
            # Only this event reaches the same call used by the ordinary Host.
            call: PublicCall = getattr(self.callbacks, event.operation)
            result = call(event.event_id, copy.deepcopy(event.input))
        snapshot = self.callbacks.snapshot()
        if snapshot["owner"] != self.owner:
            raise ValueError("SIMULATION_SNAPSHOT_OWNER_CHANGED")
        row = {
            "event_id": event.event_id,
            "operation": event.operation,
            "at": self.clock().isoformat(),
            "result": copy.deepcopy(result),
            "snapshot": copy.deepcopy(snapshot),
        }
        self.trajectory.append(row)
        return copy.deepcopy(row)

    def run(self, events: Sequence[SimulationEvent]) -> list[dict[str, Any]]:
        for event in events:
            self.step(event)
        return copy.deepcopy(self.trajectory)
