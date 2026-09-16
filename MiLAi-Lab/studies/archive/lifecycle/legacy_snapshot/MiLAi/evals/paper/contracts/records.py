"""Strict context archive records shared by all paper benchmark runners."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ContextArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextRecord:
    case_id: str
    method_id: str
    track: str
    context: str
    source_ids: tuple[str, ...]
    trace: tuple[Mapping[str, Any], ...]
    declared_tokens: int
    latency_ms: float
    usage: Mapping[str, int | float | str | bool]
    terminal_status: str = "SUCCEEDED"

    def __post_init__(self) -> None:
        if not self.case_id or not self.method_id or not self.track:
            raise ValueError("context record identity is required")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("context source IDs must be unique")
        if self.declared_tokens < 0 or self.latency_ms < 0:
            raise ValueError("context accounting values cannot be negative")
        if self.terminal_status not in {
            "SUCCEEDED",
            "CAPABILITY_UNSUPPORTED",
            "INFRASTRUCTURE_FAILURE",
        }:
            raise ValueError("unknown context terminal status")

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(self.context.encode()).hexdigest()

    def to_json(self) -> dict[str, Any]:
        value = asdict(self)
        value["context_sha256"] = self.context_sha256
        value["source_ids"] = list(self.source_ids)
        value["trace"] = [dict(item) for item in self.trace]
        value["usage"] = dict(self.usage)
        return value

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> ContextRecord:
        required = {
            "case_id",
            "method_id",
            "track",
            "context",
            "source_ids",
            "trace",
            "declared_tokens",
            "latency_ms",
            "usage",
            "terminal_status",
            "context_sha256",
        }
        if set(value) != required:
            raise ContextArchiveError("context record field set drifted")
        context = value["context"]
        source_ids = value["source_ids"]
        trace = value["trace"]
        usage = value["usage"]
        if (
            not isinstance(context, str)
            or not isinstance(source_ids, list)
            or not all(isinstance(item, str) for item in source_ids)
            or not isinstance(trace, list)
            or not all(isinstance(item, dict) for item in trace)
            or not isinstance(usage, dict)
        ):
            raise ContextArchiveError("context record types drifted")
        record = cls(
            case_id=str(value["case_id"]),
            method_id=str(value["method_id"]),
            track=str(value["track"]),
            context=context,
            source_ids=tuple(source_ids),
            trace=tuple(trace),
            declared_tokens=int(value["declared_tokens"]),
            latency_ms=float(value["latency_ms"]),
            usage=usage,
            terminal_status=str(value["terminal_status"]),
        )
        if record.context_sha256 != value["context_sha256"]:
            raise ContextArchiveError("context record digest mismatch")
        return record


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def write_context_archive(
    path: Path,
    *,
    run_id: str,
    benchmark_id: str,
    records: Sequence[ContextRecord],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pairs = [(record.case_id, record.method_id) for record in records]
    if not run_id or not benchmark_id or len(pairs) != len(set(pairs)):
        raise ContextArchiveError("context archive identity or denominator is invalid")
    payload = {
        "benchmark_id": benchmark_id,
        "record_count": len(records),
        "records": [record.to_json() for record in records],
        "run_id": run_id,
        "schema": "milai.dg11.paper-context-archive.v1",
    }
    if metadata:
        reserved = set(payload).intersection(metadata)
        if reserved:
            raise ContextArchiveError(
                f"context archive metadata shadows reserved fields: {sorted(reserved)}"
            )
        payload.update(metadata)
    _atomic_json(path, payload)
    return payload


def read_context_archive(path: Path) -> tuple[ContextRecord, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextArchiveError(f"invalid context archive: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "milai.dg11.paper-context-archive.v1"
        or not isinstance(payload.get("records"), list)
        or payload.get("record_count") != len(payload["records"])
    ):
        raise ContextArchiveError("context archive envelope drifted")
    records = tuple(ContextRecord.from_json(value) for value in payload["records"])
    pairs = [(record.case_id, record.method_id) for record in records]
    if len(pairs) != len(set(pairs)):
        raise ContextArchiveError(
            "context archive contains duplicate case/method pairs"
        )
    return records
