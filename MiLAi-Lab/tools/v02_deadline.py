"""One absolute deadline for the Linux, main-thread local Host worker."""

from __future__ import annotations

import math
import signal
import time
from collections.abc import Callable
from types import FrameType, TracebackType
from typing import Any


class DeadlineExpired(BaseException):
    """Cancellation must escape ordinary tool-error and save-UNKNOWN handlers."""


class Deadline:
    def __init__(self, started: float, seconds: float, clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(started) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("INVALID_SESSION_DEADLINE")
        self.started, self.seconds, self.clock = started, seconds, clock
        self.end = started + seconds
        self.stage = "binding"
        self.finished: float | None = None
        self.armed = False
        self.previous: Any = None

    def check(self, stage: str) -> float:
        self.stage = stage
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise DeadlineExpired("SESSION_DEADLINE:" + stage)
        return remaining

    def _expired(self, _signum: int, _frame: FrameType | None) -> None:
        raise DeadlineExpired("SESSION_DEADLINE:" + self.stage)

    def __enter__(self) -> Deadline:
        remaining = self.check("binding")
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise RuntimeError("EXISTING_PROCESS_TIMER_NOT_REPLACED")
        self.previous = signal.signal(signal.SIGALRM, self._expired)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        self.armed = True
        return self

    def finish(self) -> None:
        self.check("delivery_and_required_save_confirmed")
        self.finished = self.clock()
        if self.armed:
            signal.setitimer(signal.ITIMER_REAL, 0)

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _trace: TracebackType | None,
    ) -> None:
        if self.armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.previous)
            self.armed = False

    def observation(self) -> dict[str, Any]:
        return {
            "started_monotonic": self.started,
            "limit_seconds": self.seconds,
            "stage": self.stage,
            "finished": self.finished is not None,
            "online_elapsed_seconds": (self.finished or self.clock()) - self.started,
            "scope": "binding_restore_tools_generation_delivery_required_save",
        }
