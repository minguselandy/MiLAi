"""Inclusive phase intervals with explicit nesting, rather than summed task latency."""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComputeProfile:
    intervals: list[dict[str, Any]] = field(default_factory=list)
    _active: list[int] = field(default_factory=list, repr=False)

    @contextmanager
    def span(self, stage: str) -> Iterator[None]:
        """Measure this process; no estimate of external service GPU/CPU work."""
        index = len(self.intervals)
        event: dict[str, Any] = {"stage": stage,
                 "parent": self._active[-1] if self._active else None,
                 "start_seconds": time.perf_counter(), "cpu_start_seconds": time.process_time(),
                 "status": "RUNNING"}
        self.intervals.append(event)
        self._active.append(index)
        try:
            yield
            event["status"] = "COMPLETED"
        except BaseException:
            event["status"] = "FAILED"
            raise
        finally:
            event["end_seconds"] = time.perf_counter()
            event["wall_seconds"] = event["end_seconds"] - event["start_seconds"]
            event["cpu_seconds"] = time.process_time() - event["cpu_start_seconds"]
            self._active.pop()

    def report(self) -> dict[str, Any]:
        if self._active:
            raise ValueError("Close measured phases before reporting")
        return {"schema": "memory_compute_profile_v1", "intervals": self.intervals,
                "time_accounting": "Inclusive intervals; use task interval for end-to-end. "
                    "Parent/child and overlapping intervals must not be added.",
                "external_service_cpu_seconds": None, "measured_gpu_kernel_seconds": None,
                "physical_source_read_bytes": None, "host_device_bytes": None}
