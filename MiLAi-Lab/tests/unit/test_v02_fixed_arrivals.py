from __future__ import annotations

import asyncio
import importlib
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
fixed = importlib.import_module("v02_fixed_arrivals")


@pytest.mark.parametrize("outcome", ["release", "expiry", "cancel", "failure"])
def test_bounded_queue_preserves_arrivals_and_never_invents_a_sent_operation(outcome):
    async def run():
        events, calls = [], []
        release = asyncio.Event()
        active = 0

        async def operation(index):
            nonlocal active
            active += 1
            assert active == 1
            calls.append(index)
            try:
                if index == 0:
                    await release.wait()
                    if outcome == "failure":
                        raise RuntimeError("controlled failure")
                return index
            finally:
                active -= 1

        task = asyncio.create_task(fixed.arrivals(
            count=3, rate=1000, capacity=1, timeout=1, operation=operation,
            label="import", events=events, start=time.monotonic(), abort=asyncio.Event(),
            queue_capacity=1, queue_timeout=0.04 if outcome == "expiry" else 1,
        ))
        # All three offers occur while the first is held: one active, one queued, one rejected.
        for _ in range(100):
            if len(events) == 3 and events[2]["status"] == "CLIENT_CAPACITY_REJECTED":
                break
            await asyncio.sleep(0.002)
        assert calls == [0] and events[2]["status"] == "CLIENT_CAPACITY_REJECTED"
        if outcome == "expiry":
            await asyncio.sleep(0.06)
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await task
        assert active == 0
        queued = events[1]
        assert queued["due_s"] < queued["observed_end_s"]
        assert queued["queue_wait_ms"] > 0
        expected = {"release": "COMPLETED", "expiry": "NOT_SENT_QUEUE_TIMEOUT",
                    "cancel": "NOT_SENT_AFTER_CANCEL", "failure": "NOT_SENT_AFTER_FAILURE"}
        assert queued["status"] == expected[outcome]
        assert calls == ([0, 1] if outcome == "release" else [0])
        assert ("dispatch_s" in queued) == (outcome == "release")
        if outcome == "release":
            assert queued["observed_since_due_ms"] >= queued["queue_wait_ms"]
        report = fixed.summarize(events, duration=0.003, target_ms=50)
        assert report["planned"] == 3 and report["sent"] == len(calls)
        assert not report["candidate_target_met"]

    asyncio.run(run())


def test_blocked_client_does_not_hide_arrivals_or_invent_server_rejections():
    async def run():
        events = []
        release = asyncio.Event()

        async def operation(_):
            await release.wait()

        start = time.monotonic()
        task = asyncio.create_task(
            fixed.arrivals(
                count=8,
                rate=1000,
                capacity=1,
                timeout=1,
                operation=operation,
                label="read",
                events=events,
                start=start,
                abort=asyncio.Event(),
            )
        )
        await asyncio.sleep(0.04)
        assert len(events) == 8 and not task.done()
        release.set()
        await task
        summary = fixed.summarize(events, duration=0.008, target_ms=50)
        assert summary["planned"] == 8 and summary["sent"] == 1
        assert summary["status_counts"] == {"COMPLETED": 1, "CLIENT_CAPACITY_REJECTED": 7}
        assert not summary["candidate_target_met"]
        assert events[-1]["due_s"] == start + 0.007

    asyncio.run(run())


def test_timeout_retains_unknown_and_cannot_become_success_latency():
    async def run():
        events = []

        async def operation(_):
            await asyncio.Event().wait()

        await fixed.arrivals(
            count=1,
            rate=1,
            capacity=1,
            timeout=0.001,
            operation=operation,
            label="save",
            events=events,
            start=time.monotonic(),
            abort=asyncio.Event(),
        )
        summary = fixed.summarize(events, duration=1, target_ms=50)
        assert events[0]["status"] == "TIMEOUT_RESULT_UNKNOWN"
        assert events[0]["observed_since_due_ms"] > 0
        assert summary["scheduled_to_complete"] == {"n": 0}
        assert not summary["candidate_target_met"] and summary["sent"] == 1

    asyncio.run(run())


def test_delayed_dispatch_is_part_of_latency_and_goodput():
    async def run():
        events = []

        async def operation(_):
            return "ok"

        await fixed.arrivals(
            count=1,
            rate=1,
            capacity=1,
            timeout=1,
            operation=operation,
            label="read",
            events=events,
            start=time.monotonic() - 0.1,
            abort=asyncio.Event(),
        )
        summary = fixed.summarize(events, duration=1, target_ms=50)
        assert summary["scheduled_to_complete"]["p95_ms"] >= 100
        assert summary["goodput_per_offered_second"] == 0 and not summary["candidate_target_met"]

    asyncio.run(run())


def test_outer_cancellation_keeps_full_plan_and_awaits_active_call_cleanup():
    async def run():
        events = []
        started, closed = asyncio.Event(), asyncio.Event()

        async def operation(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        task = asyncio.create_task(
            fixed.arrivals(
                count=3,
                rate=1,
                capacity=1,
                timeout=10,
                operation=operation,
                label="save",
                events=events,
                start=time.monotonic(),
                abort=asyncio.Event(),
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
        summary = fixed.summarize(events, duration=3, target_ms=50)
        assert summary["planned"] == 3 and summary["sent"] == 1
        assert summary["status_counts"] == {
            "CANCELLED_RESULT_UNKNOWN": 1,
            "NOT_SENT_AFTER_CANCEL": 2,
        }
        assert not summary["candidate_target_met"]

    asyncio.run(run())
