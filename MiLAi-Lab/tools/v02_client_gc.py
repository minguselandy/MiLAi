"""Optional bounded observations of the load client's existing GC, never GC policy."""

from __future__ import annotations

import gc
import time
from contextlib import contextmanager
from pathlib import Path

from check_v02_service_concurrency import write


@contextmanager
def observe(
    root: Path, *, enabled: bool, limit: int = 8192,
    output_name: str = "client-gc.json", scope: str = "LOAD_CLIENT_ONLY_AROUND_ASYNCIO_RUN",
):
    if not enabled:
        yield
        return
    events, dropped = [], 0
    started = time.monotonic()
    initial = {"enabled": gc.isenabled(), "thresholds": gc.get_threshold()}

    def callback(phase, info):
        nonlocal dropped
        if len(events) < limit:
            events.append((phase, time.monotonic(), info["generation"]))
        else:
            dropped += 1

    gc.callbacks.append(callback)
    try:
        yield
    finally:
        ended = time.monotonic()
        gc.callbacks.remove(callback)
        write(
            root / output_name,
            {
                "scope": scope,
                "started_s": started,
                "ended_s": ended,
                "initial_policy": initial,
                "final_policy": {"enabled": gc.isenabled(), "thresholds": gc.get_threshold()},
                "events": events,
                "dropped_events": dropped,
                "clock": "time.monotonic",
                "policy_changed_by_probe": False,
            },
        )


def spans(observation: dict) -> list[tuple[float, float, int]] | None:
    """Incomplete capture must stay unknown; it cannot turn into zero GC overlap."""
    if observation["dropped_events"]:
        return None
    result, pending, previous = [], None, observation.get("started_s", float("-inf"))
    for phase, at, generation in observation["events"]:
        if at < previous:
            return None
        previous = at
        if phase == "start" and pending is None:
            pending = (at, generation)
        elif phase == "stop" and pending is not None:
            if generation != pending[1] or at < pending[0]:
                return None
            result.append((pending[0], at, generation))
            pending = None
        else:
            return None
    return None if pending is not None else result


def overlap_ms(start: float, end: float, intervals: list[tuple[float, float, int]]) -> float:
    return 1000 * sum(max(0, min(end, stop) - max(start, begin)) for begin, stop, _ in intervals)
