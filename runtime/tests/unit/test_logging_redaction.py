from __future__ import annotations

import logging

from milai.observability.logging import JsonFormatter, SafeTextFormatter


def _record(message: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
    return logging.LogRecord("milai.test", logging.ERROR, __file__, 1, message, args, None)


def test_json_formatter_never_interpolates_payload_or_unsafe_metadata() -> None:
    secret = "secret-token-value-should-never-appear"
    record = _record("request failed with %s", (secret,))
    record.request_id = secret  # type: ignore[attr-defined]
    rendered = JsonFormatter().format(record)
    assert secret not in rendered
    assert '"event":"application_event"' in rendered


def test_json_formatter_emits_only_safe_route_metadata() -> None:
    record = _record("unhandled_api_error")
    record.route = "/v1/open-issues"  # type: ignore[attr-defined]
    rendered = JsonFormatter().format(record)
    assert '"route":"/v1/open-issues"' in rendered

    record.route = "/v1/items?token=not-safe"  # type: ignore[attr-defined]
    rendered = JsonFormatter().format(record)
    assert "not-safe" not in rendered


def test_json_formatter_emits_bounded_payload_free_stage_metrics() -> None:
    secret = "unsafe value with spaces and payload text"
    record = _record("outbox_worker_cycle")
    record.safe_metadata = {  # type: ignore[attr-defined]
        "processed": 3,
        "stage_metrics": {
            "counts": {"embedding_inference_batches": 2},
            "durations_ms": {"projection_write_ms": 12.5},
        },
        "unsafe_payload": secret,
    }

    payload = __import__("json").loads(JsonFormatter().format(record))

    assert payload["safe_metadata"] == {
        "processed": 3,
        "stage_metrics": {
            "counts": {"embedding_inference_batches": 2},
            "durations_ms": {"projection_write_ms": 12.5},
        },
    }
    assert secret not in JsonFormatter().format(record)


def test_text_formatter_never_interpolates_payload_or_exception_message() -> None:
    secret = "database-password-should-never-appear"
    try:
        raise RuntimeError(secret)
    except RuntimeError:
        record = _record("unsafe %s", (secret,))
        record.exc_info = __import__("sys").exc_info()
    rendered = SafeTextFormatter().format(record)
    assert secret not in rendered
    assert "RuntimeError" in rendered
