"""Append-only, hash-chained accounting ledger for paper experiments."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LedgerError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


@dataclass(frozen=True)
class LedgerVerification:
    events: tuple[Mapping[str, Any], ...]
    root_sha256: str


class UsageLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cached_signature: tuple[int, int, int, int] | None = None
        self._cached_count = 0
        self._cached_root = "0" * 64

    def _signature(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _verify_file(self) -> LedgerVerification:
        if not self.path.exists():
            return LedgerVerification((), "0" * 64)
        events: list[Mapping[str, Any]] = []
        previous = "0" * 64
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"invalid ledger JSON at line {line_number}") from exc
            required = {
                "event",
                "occurred_at",
                "previous_sha256",
                "sequence",
                "event_sha256",
            }
            if not isinstance(record, dict) or set(record) != required:
                raise LedgerError(f"invalid ledger field set at line {line_number}")
            if (
                record["sequence"] != line_number
                or record["previous_sha256"] != previous
            ):
                raise LedgerError(f"broken ledger chain at line {line_number}")
            body = {key: record[key] for key in required if key != "event_sha256"}
            expected = hashlib.sha256(_canonical(body)).hexdigest()
            if record["event_sha256"] != expected:
                raise LedgerError(f"invalid ledger digest at line {line_number}")
            previous = expected
            events.append(record)
        return LedgerVerification(tuple(events), previous)

    def _verified_head(self) -> tuple[int, str]:
        signature = self._signature()
        if signature != self._cached_signature:
            verified = self._verify_file()
            self._cached_count = len(verified.events)
            self._cached_root = verified.root_sha256
            self._cached_signature = self._signature()
        return self._cached_count, self._cached_root

    def append(self, event: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            count, root = self._verified_head()
            sequence = count + 1
            body = {
                "event": dict(event),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "previous_sha256": root,
                "sequence": sequence,
            }
            event_sha256 = hashlib.sha256(_canonical(body)).hexdigest()
            record = {**body, "event_sha256": event_sha256}
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            try:
                with os.fdopen(descriptor, "ab", closefd=False) as handle:
                    handle.write(_canonical(record) + b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                os.close(descriptor)
            self._cached_count = sequence
            self._cached_root = event_sha256
            self._cached_signature = self._signature()
            return record

    def verify(self) -> LedgerVerification:
        with self._lock:
            verified = self._verify_file()
            self._cached_count = len(verified.events)
            self._cached_root = verified.root_sha256
            self._cached_signature = self._signature()
            return verified
