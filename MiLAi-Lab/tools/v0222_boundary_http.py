"""Strict HTTP-only identity, with a fresh external admission before each GET."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0222_http import bounded_request, strict_http_json


def boundary_identity(client: httpx.Client, directory: Path, admit: Callable) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    values = {}
    for name, route in (("models", "/v1/models"), ("version", "/version")):
        # Dependency/stop checks must not consume the bounded network timer.
        admit()
        save(directory / (name + "-attempt.json"), {"method": "GET", "route": route})
        started = time.monotonic()
        try:
            response = bounded_request(client, "GET", route, timeout=5)
        except Exception as exc:
            save(
                directory / (name + "-error.json"),
                {
                    "exception_type": type(exc).__name__,
                    "seconds": time.monotonic() - started,
                },
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
