"""Strict HTTP JSON and POSIX wall-clock bounds for single-thread cold workers."""

from __future__ import annotations

import json
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL
from v0220_action_contract import unique_object
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import encoded


def strict_http_json(raw: str):
    value = json.loads(raw, object_pairs_hook=unique_object)
    encoded(value)
    return value


@contextmanager
def wall_bound(seconds: float):
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        raise ProviderStop("HTTP_WALL_BOUND_REQUIRES_MAIN_THREAD_AND_POSITIVE_TIME")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise ProviderStop("EXISTING_PROCESS_TIMER_CANNOT_BE_REPLACED")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise httpx.ReadTimeout("HTTP_TOTAL_WALL_CLOCK_DEADLINE")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def bounded_request(client: httpx.Client, method: str, route: str, *, timeout: float, **kwargs):
    # httpx phase timeouts alone do not bound total response time.
    with wall_bound(timeout):
        return client.request(method, route, timeout=timeout, **kwargs)


def http_identity(client: httpx.Client, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    values = {}
    for name, route in (("models", "/v1/models"), ("version", "/version")):
        save(directory / (name + "-attempt.json"), {"method": "GET", "route": route})
        started = time.monotonic()
        try:
            response = bounded_request(client, "GET", route, timeout=5)
        except Exception as exc:
            save(
                directory / (name + "-error.json"),
                {"exception_type": type(exc).__name__, "seconds": time.monotonic() - started},
            )
            raise
        save(
            directory / (name + ".json"),
            {
                "status_code": response.status_code,
                "body": response.text,
                "seconds": time.monotonic() - started,
            },
        )
        response.raise_for_status()
        values[name] = strict_http_json(response.text)
    models = values["models"]["data"]
    if len(models) != 1 or models[0]["id"] != MODEL or models[0]["max_model_len"] != 65536:
        raise ProviderStop("HTTP_MODEL_OR_CONTEXT_DRIFT")
    return {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "context": 65536,
        "version": values["version"]["version"],
    }
