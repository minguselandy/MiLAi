from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any, TypeVar

_T = TypeVar("_T")

request_operation_timer: ContextVar[OperationTimer | None] = ContextVar(
    "milai_request_operation_timer", default=None
)


class OperationTimer:
    """Payload-free wall-time and call-count aggregation for product operations."""

    def __init__(self) -> None:
        self.durations_ms: dict[str, float] = defaultdict(float)
        self.counts: dict[str, int] = defaultdict(int)
        self._sequence: list[str] = []
        self._lock = RLock()

    @contextmanager
    def measure(self, operation: str) -> Iterator[None]:
        started = time.perf_counter()
        with self._lock:
            self._sequence.append(operation)
        try:
            yield
        finally:
            with self._lock:
                self.durations_ms[operation] += (time.perf_counter() - started) * 1_000
                self.counts[operation] += 1

    def call(self, operation: str, function: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        with self.measure(operation):
            return function(*args, **kwargs)

    def duration(self, operation: str) -> float:
        with self._lock:
            return round(float(self.durations_ms.get(operation, 0.0)), 3)

    def increment(self, metric: str, value: int = 1) -> None:
        with self._lock:
            self.counts[metric] += value

    def observe_duration(self, operation: str, duration_ms: float) -> None:
        """Attach a measured upstream stage while retaining one ordered trace."""
        if not operation or duration_ms < 0:
            raise ValueError("operation and non-negative duration_ms are required")
        with self._lock:
            self._sequence.append(operation)
            self.durations_ms[operation] += duration_ms
            self.counts[operation] += 1

    def sequence(self) -> tuple[str, ...]:
        """Return the payload-free operation order for access-trace construction."""
        with self._lock:
            return tuple(self._sequence)

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                "durations_ms": {
                    key: round(float(value), 3) for key, value in sorted(self.durations_ms.items())
                },
                "counts": {key: int(value) for key, value in sorted(self.counts.items())},
            }
