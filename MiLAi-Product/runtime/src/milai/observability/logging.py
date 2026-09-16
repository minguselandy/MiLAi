from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

_SAFE_EVENT = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_METADATA = re.compile(r"^[A-Za-z0-9_.:@/-]{1,255}$")
_SAFE_METADATA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_MAX_METADATA_DEPTH = 4
_MAX_METADATA_ITEMS = 256


def _event_name(record: logging.LogRecord) -> str:
    value = record.msg if isinstance(record.msg, str) else "application_event"
    return value if _SAFE_EVENT.fullmatch(value) else "application_event"


def _safe_metadata(value: object) -> object | None:
    if isinstance(value, bool | int | float):
        return value
    text = str(value)
    return text if _SAFE_METADATA.fullmatch(text) else None


def _safe_metadata_tree(value: object, *, depth: int = 0) -> object | None:
    """Retain bounded payload-free operational metrics without rendering payloads."""

    if depth > _MAX_METADATA_DEPTH:
        return None
    if isinstance(value, Mapping):
        if len(value) > _MAX_METADATA_ITEMS:
            return None
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if not _SAFE_METADATA_KEY.fullmatch(key):
                continue
            safe_value = _safe_metadata_tree(raw_value, depth=depth + 1)
            if safe_value is not None:
                result[key] = safe_value
        return result
    if isinstance(value, list | tuple):
        if len(value) > _MAX_METADATA_ITEMS:
            return None
        items = [
            safe_value
            for item in value
            if (safe_value := _safe_metadata_tree(item, depth=depth + 1))
            is not None
        ]
        return items
    return _safe_metadata(value)


class JsonFormatter(logging.Formatter):
    """Small JSON formatter that intentionally excludes message payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": _event_name(record),
        }
        request_id = getattr(record, "request_id", None)
        if request_id is not None:
            payload["request_id_fingerprint"] = hashlib.sha256(
                str(request_id).encode("utf-8")
            ).hexdigest()[:16]
        for key in (
            "operation_family",
            "reason_code",
            "outbox_event_id",
            "projection_name",
            "route",
        ):
            value = getattr(record, key, None)
            safe_value = _safe_metadata(value) if value is not None else None
            if safe_value is not None:
                payload[key] = safe_value
        safe_metadata = _safe_metadata_tree(getattr(record, "safe_metadata", None))
        if isinstance(safe_metadata, dict) and safe_metadata:
            payload["safe_metadata"] = safe_metadata
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class SafeTextFormatter(logging.Formatter):
    """Text logs retain only safe event names and exception types."""

    def format(self, record: logging.LogRecord) -> str:
        exception = ""
        if record.exc_info and record.exc_info[0] is not None:
            exception = f" exception_type={record.exc_info[0].__name__}"
        return f"{record.levelname} {record.name} {_event_name(record)}{exception}"


def configure_logging(level: str, output_format: Literal["json", "text"]) -> None:
    handler = logging.StreamHandler()
    if output_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(SafeTextFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
