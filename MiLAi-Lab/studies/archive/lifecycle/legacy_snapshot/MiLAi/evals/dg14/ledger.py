"""Append-only, hash-chained stage ledger for DG-14 characterization runs."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ZERO_SHA256 = "0" * 64
STAGES = frozenset(
    {
        "reset",
        "ingest",
        "finalize",
        "mcp",
        "runtime",
        "context",
        "provider_tokenize",
        "provider",
        "provider_binding",
        "score",
        "e2e",
        "cleanup",
    }
)
STATUSES = frozenset({"SUCCEEDED", "FAILED", "SKIPPED"})


class DG14LedgerError(RuntimeError):
    """Raised when a stage event or persisted chain violates the ledger contract."""


@dataclass(frozen=True, slots=True)
class DG14StageEvent:
    """One terminal stage observation.

    ``logical_calls`` counts product/provider calls, not Python helper invocations.
    DG-14 never retries automatically, so ``retry_count`` is fixed to zero.
    """

    run_id: str
    stage: str
    status: Literal["SUCCEEDED", "FAILED", "SKIPPED"]
    duration_ms: float
    case_id: str | None = None
    method_id: str | None = None
    token_budget: int | None = None
    logical_request_id: str | None = None
    logical_calls: int = 0
    retry_count: int = 0
    candidate_count: int | None = None
    retrieval_route: str | None = None
    memory_tokens: int | None = None
    prompt_tokens: int | None = None
    failure_type: str | None = None
    failure_code: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("stage event run_id is required")
        if self.stage not in STAGES:
            raise ValueError(f"unknown DG-14 stage: {self.stage}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown DG-14 stage status: {self.status}")
        if self.duration_ms < 0:
            raise ValueError("stage duration cannot be negative")
        if self.logical_calls < 0 or self.retry_count != 0:
            raise ValueError("DG-14 logical calls must be non-negative and retries zero")
        for value, label in (
            (self.token_budget, "token budget"),
            (self.candidate_count, "candidate count"),
            (self.memory_tokens, "memory tokens"),
            (self.prompt_tokens, "prompt tokens"),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.status == "FAILED" and not self.failure_type:
            raise ValueError("failed stage requires a typed failure")
        if self.status != "FAILED" and (
            self.failure_type is not None or self.failure_code is not None
        ):
            raise ValueError("successful/skipped stage cannot carry failure fields")
        try:
            _canonical(dict(self.details))
        except (TypeError, ValueError) as exc:
            raise ValueError("stage details must be JSON serializable") from exc

    def to_json(self) -> dict[str, Any]:
        value = asdict(self)
        value["details"] = dict(self.details)
        return value


@dataclass(frozen=True, slots=True)
class DG14LedgerVerification:
    events: tuple[Mapping[str, Any], ...]
    root_sha256: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class DG14StageLedger:
    """Thread-safe JSONL ledger whose envelope digests bind every prior event."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cached_signature: tuple[int, int, int, int] | None = None
        self._cached_count = 0
        self._cached_root = ZERO_SHA256

    def _signature(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _verify_file(self) -> DG14LedgerVerification:
        if not self.path.exists():
            return DG14LedgerVerification((), ZERO_SHA256)
        events: list[Mapping[str, Any]] = []
        previous = ZERO_SHA256
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                envelope = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DG14LedgerError(
                    f"invalid DG-14 ledger JSON at line {line_number}"
                ) from exc
            required = {
                "event",
                "event_sha256",
                "occurred_at",
                "previous_sha256",
                "sequence",
            }
            if not isinstance(envelope, dict) or set(envelope) != required:
                raise DG14LedgerError(
                    f"invalid DG-14 ledger fields at line {line_number}"
                )
            if (
                envelope["sequence"] != line_number
                or envelope["previous_sha256"] != previous
            ):
                raise DG14LedgerError(
                    f"broken DG-14 ledger chain at line {line_number}"
                )
            event = envelope["event"]
            if not isinstance(event, dict):
                raise DG14LedgerError(
                    f"invalid DG-14 stage event at line {line_number}"
                )
            try:
                DG14StageEvent(**event)
            except (TypeError, ValueError) as exc:
                raise DG14LedgerError(
                    f"invalid DG-14 stage contract at line {line_number}"
                ) from exc
            body = {key: envelope[key] for key in required if key != "event_sha256"}
            expected = hashlib.sha256(_canonical(body)).hexdigest()
            if envelope["event_sha256"] != expected:
                raise DG14LedgerError(
                    f"invalid DG-14 ledger digest at line {line_number}"
                )
            previous = expected
            events.append(envelope)
        return DG14LedgerVerification(tuple(events), previous)

    def _verified_head(self) -> tuple[int, str]:
        signature = self._signature()
        if signature != self._cached_signature:
            verified = self._verify_file()
            self._cached_count = len(verified.events)
            self._cached_root = verified.root_sha256
            self._cached_signature = self._signature()
        return self._cached_count, self._cached_root

    def append(self, event: DG14StageEvent) -> Mapping[str, Any]:
        """Verify the current file, then durably append one terminal event."""

        return self.append_many((event,))[0]

    def append_many(
        self, events: Sequence[DG14StageEvent]
    ) -> tuple[Mapping[str, Any], ...]:
        """Append one verified hash-chain segment with a single durability sync."""

        if not events:
            return ()
        if any(not isinstance(event, DG14StageEvent) for event in events):
            raise TypeError("DG-14 ledger accepts DG14StageEvent values only")
        with self._lock:
            count, root = self._verified_head()
            envelopes: list[Mapping[str, Any]] = []
            previous = root
            for offset, event in enumerate(events, start=1):
                body = {
                    "event": event.to_json(),
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "previous_sha256": previous,
                    "sequence": count + offset,
                }
                digest = hashlib.sha256(_canonical(body)).hexdigest()
                envelope = {**body, "event_sha256": digest}
                envelopes.append(envelope)
                previous = digest
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            try:
                with os.fdopen(descriptor, "ab", closefd=False) as handle:
                    handle.write(
                        b"".join(_canonical(envelope) + b"\n" for envelope in envelopes)
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                os.close(descriptor)
            self._cached_count = count + len(envelopes)
            self._cached_root = previous
            self._cached_signature = self._signature()
            return tuple(envelopes)

    def verify(self) -> DG14LedgerVerification:
        with self._lock:
            verified = self._verify_file()
            self._cached_count = len(verified.events)
            self._cached_root = verified.root_sha256
            self._cached_signature = self._signature()
            return verified


# Short aliases keep injected unit fakes and CLI callers pleasantly small.
HashChainStageLedger = DG14StageLedger
StageEvent = DG14StageEvent
