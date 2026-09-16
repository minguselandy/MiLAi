"""Durable final-delivery reservations; unknown usage survives process restarts."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from v02_local_provider import append_event, read_events


@dataclass(frozen=True)
class BudgetContract:
    max_generations: int
    context_tokens: int
    output_reservation: int
    final_delivery_reserve: int
    raw_limit: int | None = None


class DeliveryBudget:
    def __init__(self, ledger: Path, contract: BudgetContract):
        self.ledger, self.contract = ledger, contract
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            contracts = [event["contract"] for event in read_events(ledger)
                         if event["event"] == "CONTRACT"]
            if contracts and contracts != [asdict(contract)]:
                raise ValueError("FROZEN_BUDGET_CONTRACT_CHANGED")
            if not contracts:
                append_event(ledger, {"event": "CONTRACT", "contract": asdict(contract)})

    @contextmanager
    def _locked(self):
        """Per-allocation ledger lock, never a service/global model lock."""
        with self.ledger.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def state(self) -> tuple[int, int, dict[str, int]]:
        with self._locked():
            return self._state()

    def _state(self) -> tuple[int, int, dict[str, int]]:
        used, sent, pending = 0, 0, {}
        for event in read_events(self.ledger):
            if event["event"] == "RESERVE":
                pending[event["request_id"]] = event["upper"]
                sent += 1
            elif event["event"] == "SETTLE":
                del pending[event["request_id"]]
                used += event["raw"]
        return used, sent, pending

    def allow(self, next_upper: int, *, final: bool = False) -> str:
        with self._locked():
            return self._allow(next_upper, final=final)

    def _allow(self, next_upper: int, *, final: bool = False) -> str:
        used, sent, pending = self._state()
        if pending:
            return "UNKNOWN_USAGE_STOP"
        if next_upper > self.contract.context_tokens:
            return "CONTEXT_LIMIT"
        if sent >= self.contract.max_generations - (0 if final else 1):
            return "FINAL_ONLY"
        reserve = 0 if final else self.contract.final_delivery_reserve
        if self.contract.raw_limit is not None and (
                used + next_upper + reserve > self.contract.raw_limit):
            return "FINAL_ONLY"
        return "ALLOW"

    def reserve(self, request_id: str, next_upper: int, *, final: bool = False) -> str:
        with self._locked():
            if any(event.get("request_id") == request_id and event["event"] == "RESERVE"
                   for event in read_events(self.ledger)):
                raise ValueError("DUPLICATE_REQUEST_ID")
            decision = self._allow(next_upper, final=final)
            if decision != "ALLOW":
                return decision
            append_event(self.ledger, {"event": "RESERVE", "request_id": request_id,
                                      "upper": next_upper, "final": final})
            return decision

    def settle(self, request_id: str, raw: int) -> None:
        with self._locked():
            upper = self._state()[2][request_id]
            if not 0 <= raw <= upper:
                raise ValueError("USAGE_BOUND_VIOLATION_RESERVATION_RETAINED")
            append_event(self.ledger, {"event": "SETTLE", "request_id": request_id, "raw": raw})
