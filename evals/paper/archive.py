"""Deterministic archive scanner and strict resume classification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.paper.usage_ledger import UsageLedger


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestState:
    logical_request_id: str
    status: str
    native_request_id: str | None
    terminal: Mapping[str, Any] | None


@dataclass(frozen=True)
class ArchiveSummary:
    planned: int
    succeeded: int
    failed: int
    safe_to_resume: tuple[str, ...]
    manual_reconciliation: tuple[str, ...]
    missing: tuple[str, ...]


def scan_archive(ledger_path: Path, logical_request_ids: tuple[str, ...]) -> ArchiveSummary:
    verified = UsageLedger(ledger_path).verify()
    by_request: dict[str, list[Mapping[str, Any]]] = {request_id: [] for request_id in logical_request_ids}
    for envelope in verified.events:
        event = envelope["event"]
        if not isinstance(event, dict):
            raise ArchiveError("ledger event payload is not an object")
        request_id = event.get("logical_request_id")
        if request_id not in by_request:
            raise ArchiveError(f"ledger contains an unregistered request: {request_id}")
        by_request[request_id].append(event)
    succeeded = 0
    failed = 0
    safe: list[str] = []
    manual: list[str] = []
    missing: list[str] = []
    for request_id, events in by_request.items():
        types = [event.get("type") for event in events]
        terminals = [event for event in events if event.get("type") == "TERMINAL"]
        if len(terminals) > 1:
            raise ArchiveError(f"duplicate terminal for {request_id}")
        if terminals:
            if terminals[0].get("status") == "SUCCEEDED":
                succeeded += 1
            else:
                failed += 1
            continue
        if "PROVIDER_STARTED" in types:
            manual.append(request_id)
        elif "RESERVED" in types:
            safe.append(request_id)
        else:
            missing.append(request_id)
    return ArchiveSummary(
        planned=len(logical_request_ids),
        succeeded=succeeded,
        failed=failed,
        safe_to_resume=tuple(safe),
        manual_reconciliation=tuple(manual),
        missing=tuple(missing),
    )
