from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class HistoryItem:
    item_id: str
    session_id: str
    role: Role
    content: str
    occurred_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.item_id or not self.session_id or not self.content:
            raise ValueError("history item identity, session, and content are required")

    def canonical(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "occurred_at": self.occurred_at,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class WorkloadHistory:
    workload_id: str
    dataset_id: str
    items: tuple[HistoryItem, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workload_id or not self.dataset_id:
            raise ValueError("workload and dataset identity are required")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("history item identities must be unique")

    @property
    def fingerprint(self) -> str:
        payload = {
            "workload_id": self.workload_id,
            "dataset_id": self.dataset_id,
            "items": [item.canonical() for item in self.items],
            "metadata": self.metadata,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ResultRecord:
    method_id: str
    workload_id: str
    question_id: str
    status: str
    items: tuple[dict[str, Any], ...]
    elapsed_ms: float
    product_usage: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

