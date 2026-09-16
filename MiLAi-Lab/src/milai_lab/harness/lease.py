from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from milai_lab.contracts.records import WorkloadHistory


@dataclass(frozen=True, slots=True)
class BuildReceipt:
    workload_fingerprint: str
    status: str
    canonical_position: int | None
    product_usage: dict[str, Any]


@dataclass(slots=True)
class EvaluationRuntimeLease:
    """A bounded lease over an already provisioned public product endpoint."""

    lease_id: str
    endpoint: str
    product_lock_digest: str
    history_loader: Callable[[WorkloadHistory], BuildReceipt]
    close_callback: Callable[[], None]
    trace_path: Path | None = None
    _closed: bool = False

    def load_history(self, history: WorkloadHistory) -> BuildReceipt:
        if self._closed:
            raise RuntimeError("evaluation lease is closed")
        receipt = self.history_loader(history)
        if receipt.workload_fingerprint != history.fingerprint:
            raise RuntimeError("product receipt does not bind the immutable workload")
        return receipt

    def close(self) -> None:
        if not self._closed:
            self.close_callback()
            self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

