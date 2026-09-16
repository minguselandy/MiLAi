"""Finite open-loop client arrivals with explicit local refusal and timeout accounting."""

from __future__ import annotations

import asyncio
import time

from check_v02_service_concurrency import distribution


async def arrivals(
    *, count, rate, capacity, timeout, operation, label, events, start, abort,
    queue_capacity=0, queue_timeout=0,
):
    if capacity < 1 or queue_capacity < 0 or (queue_capacity and queue_timeout <= 0):
        raise ValueError("Positive in-flight capacity and bounded optional queue required")
    pending: set[asyncio.Task] = set()
    slots = asyncio.Semaphore(capacity) if queue_capacity else None
    active = 0
    planned = [
        {"label": label, "index": i, "due_s": start + i / rate, "status": "PLANNED"}
        for i in range(count)
    ]
    events.extend(planned)

    async def dispatch(index, event):
        nonlocal active
        acquired = False
        try:
            if slots is not None:
                remaining = event["due_s"] + queue_timeout - time.monotonic()
                if remaining <= 0:
                    event["status"] = "NOT_SENT_QUEUE_TIMEOUT"
                    return
                try:
                    await asyncio.wait_for(slots.acquire(), remaining)
                except TimeoutError:
                    event["status"] = "NOT_SENT_QUEUE_TIMEOUT"
                    return
                acquired = True
                event["queue_wait_ms"] = 1000 * (time.monotonic() - event["enqueued_s"])
                if abort.is_set():
                    event["status"] = "NOT_SENT_AFTER_FAILURE"
                    return
            event["dispatch_s"] = time.monotonic()
            active += 1
            result = await asyncio.wait_for(operation(index), timeout)
            event.update(status="COMPLETED", result=result)
        except TimeoutError:
            event["status"] = "TIMEOUT_RESULT_UNKNOWN"
            abort.set()
        except asyncio.CancelledError:
            event["status"] = (
                "CANCELLED_RESULT_UNKNOWN" if "dispatch_s" in event else "NOT_SENT_AFTER_CANCEL"
            )
            abort.set()
            raise
        except Exception as exc:
            event.update(status="FAILED", error_type=type(exc).__name__)
            abort.set()
        finally:
            event["observed_end_s"] = time.monotonic()
            event["observed_since_due_ms"] = 1000 * (event["observed_end_s"] - event["due_s"])
            if "enqueued_s" in event and "queue_wait_ms" not in event:
                event["queue_wait_ms"] = 1000 * (event["observed_end_s"] - event["enqueued_s"])
            if "dispatch_s" in event:
                active -= 1
                event["call_ms"] = 1000 * (event["observed_end_s"] - event["dispatch_s"])
            if acquired:
                slots.release()

    try:
        for event in planned:
            due = event["due_s"]
            await asyncio.sleep(max(0, due - time.monotonic()))
            pending = {task for task in pending if not task.done()}
            event["inflight_before"] = active if slots is not None else len(pending)
            if slots is not None:
                event["queued_before"] = len(pending) - active
            if abort.is_set() or len(pending) >= capacity + queue_capacity:
                event.update(
                    status="NOT_SENT_AFTER_FAILURE"
                    if abort.is_set()
                    else "CLIENT_CAPACITY_REJECTED",
                    observed_end_s=time.monotonic(),
                )
                event["observed_since_due_ms"] = 1000 * (event["observed_end_s"] - due)
                continue
            if slots is not None:
                event["enqueued_s"] = time.monotonic()
            pending.add(asyncio.create_task(dispatch(event["index"], event)))
        await asyncio.gather(*pending)
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for event in planned:
            if event["status"] == "PLANNED":
                event["status"] = "NOT_SENT_AFTER_CANCEL"


def summarize(events, *, duration, target_ms):
    completed = [e for e in events if e["status"] == "COMPLETED"]
    statuses = {
        status: sum(e["status"] == status for e in events)
        for status in sorted({e["status"] for e in events})
    }
    latency = distribution([e["observed_since_due_ms"] for e in completed])
    good = sum(e["observed_since_due_ms"] <= target_ms for e in completed)
    return {
        "planned": len(events),
        "sent": sum("dispatch_s" in e for e in events),
        "status_counts": statuses,
        "completed": len(completed),
        "scheduled_to_complete": latency,
        "completed_calls": distribution([e["call_ms"] for e in completed]),
        "queue_wait": distribution([e["queue_wait_ms"] for e in events if "queue_wait_ms" in e]),
        "goodput_per_offered_second": good / duration,
        "offered_per_second": len(events) / duration,
        "candidate_target_met": bool(events)
        and len(completed) == len(events)
        and latency["p95_ms"] <= target_ms,
    }
