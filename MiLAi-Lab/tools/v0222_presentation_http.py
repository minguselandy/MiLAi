"""Identity evidence with fresh admission after persistence and before every GET."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import save
from v0220_provider_hardened import ProviderStop
from v0222_http import bounded_request, strict_http_json


def identity(
    client: httpx.Client, directory: Path, *, admit: Callable, on_failure: Callable
) -> dict:
    try:
        directory.mkdir(parents=True, exist_ok=False)
        values = {}
        for name, route in (("models", "/v1/models"), ("version", "/version")):
            save(directory / (name + "-attempt.json"), {"method": "GET", "route": route})
            # No intervening disk write: stop/deadline/source checks cover the actual send.
            admit()
            started = time.monotonic()
            try:
                response = bounded_request(client, "GET", route, timeout=5)
            except BaseException as exc:
                on_failure(exc)
                try:
                    save(
                        directory / (name + "-error.json"),
                        {
                            "exception_type": type(exc).__name__,
                            "seconds": time.monotonic() - started,
                        },
                    )
                except Exception as report_error:
                    # Preserve the lock and original exception if its report cannot be saved.
                    exc.add_note("Identity error report failed: " + type(report_error).__name__)
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
        on_failure(exc)
        raise
