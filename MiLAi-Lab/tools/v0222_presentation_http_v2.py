"""Scoped identity: persist attempts, then admit and bound each actual GET.

The admission callback returns the owned episode's absolute wall-clock deadline.
It must close its read scope and SQL transaction before returning. Receipt shapes
remain identical to the frozen identity protocol; this module grants no authority.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0222_http import bounded_request, strict_http_json


def owned_timeout(claim: dict, cap: float) -> float:
    deadline = claim.get("deadline")
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ProviderStop("FINITE_OWNED_HTTP_DEADLINE_REQUIRED")
    remaining = deadline - time.time()
    if remaining <= 0:
        raise ProviderStop("OWNED_HTTP_DEADLINE_EXPIRED")
    return min(cap, remaining)


def _failed(callback: Callable, exc: BaseException) -> None:
    try:
        callback(exc)
    except BaseException as secondary:
        exc.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)


def identity(
    client: httpx.Client, directory: Path, *, admit: Callable, on_failure: Callable
) -> dict:
    try:
        directory.mkdir(parents=True, exist_ok=False)
        values = {}
        for name, route in (("models", "/v1/models"), ("version", "/version")):
            save(directory / (name + "-attempt.json"), {"method": "GET", "route": route})
            claim = admit()
            timeout = owned_timeout(claim, 5)
            started = time.monotonic()
            try:
                response = bounded_request(client, "GET", route, timeout=timeout)
            except BaseException as exc:
                _failed(on_failure, exc)
                try:
                    save(
                        directory / (name + "-error.json"),
                        {
                            "exception_type": type(exc).__name__,
                            "seconds": time.monotonic() - started,
                        },
                    )
                except BaseException as secondary:
                    exc.add_note("Identity error report failed: " + type(secondary).__name__)
                raise
            save(
                directory / (name + ".json"),
                {
                    "status_code": response.status_code,
                    "body": response.text,
                    "seconds": time.monotonic() - started,
                },
            )
            if response.status_code != 200:
                raise ProviderStop("HTTP_IDENTITY_REQUIRES_200")
            values[name] = strict_http_json(response.text)
        models = values["models"]["data"]
        if (
            len(models) != 1
            or models[0]["id"] != MODEL
            or type(models[0].get("max_model_len")) is not int
            or models[0]["max_model_len"] != 65536
        ):
            raise ProviderStop("HTTP_MODEL_OR_CONTEXT_DRIFT")
        return {
            "endpoint": ENDPOINT,
            "model": MODEL,
            "context": 65536,
            "version": values["version"]["version"],
        }
    except BaseException as exc:
        _failed(on_failure, exc)
        raise
