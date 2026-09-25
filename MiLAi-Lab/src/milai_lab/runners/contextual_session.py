"""The live conversation and exact material visibility of one Host session."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from milai_lab.methods.contextual_memory.material_view import MaterialBinding, MaterialView
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.runners.contextual_delivery import DeliveryLedger


@dataclass
class HostSession:
    session_id: str
    memory: ContextualMemory | None
    transcript: list[dict[str, Any]] = field(
        default_factory=lambda: [{"role": "system", "content": ""}]
    )
    turn_index: int = 0
    turn_id: str = ""
    closed: bool = False
    read_cache: dict[str, int] = field(default_factory=dict)
    observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    maintenance: dict[str, Any] = field(default_factory=dict)
    visible_bindings: dict[str, MaterialBinding] = field(default_factory=dict)
    deliveries: list[tuple[dict[str, Any], str, dict[str, MaterialBinding]]] = field(
        default_factory=list
    )
    material_view: MaterialView | None = field(init=False)
    delivery: DeliveryLedger = field(init=False)
    task_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.delivery = DeliveryLedger(self.session_id)
        self.material_view = (
            MaterialView(self.session_id, self.memory) if self.memory is not None else None
        )
        self.task_id = self.memory.state.task_id if self.memory is not None else ""

    def begin_turn(self, turn_id: str = "") -> None:
        if self.closed:
            raise ValueError("HOST_SESSION_CLOSED")
        if self.memory is not None and self.memory.state.task_id != self.task_id:
            raise ValueError("HOST_SESSION_TASK_CHANGED")
        self.turn_index += 1
        self.turn_id = turn_id or str(self.turn_index)
        self.read_cache.clear()
        for key in ("last_review", "turn_calls", "turn_usage", "call_ordinal"):
            self.maintenance.pop(key, None)
        self.refresh_visibility()

    def record_delivery(self, message: dict[str, Any], projected: dict[str, Any]) -> None:
        """Authorize only material present in an actual, unchanged transcript message."""
        if not any(item is message for item in self.transcript):
            raise ValueError("MATERIAL_MESSAGE_NOT_IN_TRANSCRIPT")
        self.delivery.record(message, projected)
        if self.material_view is not None:
            bindings = self.material_view.visible_bindings(projected)
            issued = self.maintenance.setdefault("issued_tokens", [])
            for alias in bindings:
                if alias not in {"unknown"} and alias not in issued:
                    issued.append(alias)
            self.deliveries.append((
                message, message["content"], bindings,
            ))
            self.refresh_visibility()

    def refresh_visibility(self) -> None:
        if self.memory is None or self.material_view is None:
            return
        old = set(self.visible_bindings)
        self.deliveries = [
            item for item in self.deliveries
            if any(message is item[0] for message in self.transcript)
            and item[0]["content"] == item[1]
        ]
        self.visible_bindings = {
            alias: binding for _, _, bindings in self.deliveries
            for alias, binding in bindings.items()
        }
        removed = old - self.visible_bindings.keys()
        if removed:
            self.material_view.revoke(removed)
            self.read_cache.clear()
        self.memory.seen = {
            binding.exact_ref for binding in self.visible_bindings.values() if binding.spans
        }
        ranges: dict[str, set[tuple[int, int]]] = {}
        for binding in self.visible_bindings.values():
            if binding.kind == "source" and binding.spans:
                ranges.setdefault(binding.exact_ref, set()).update(binding.spans)
        self.memory.visible_source_ranges = ranges

    def visible_body_spans(self, alias: str) -> tuple[tuple[int, int], ...]:
        """Current resident body ranges for the alias's exact immutable version."""
        self.refresh_visibility()
        locator = self.visible_bindings.get(alias)
        if locator is None or self.memory is None:
            return ()
        try:
            body = self.memory._view(locator.exact_ref, False)[
                "content" if locator.kind == "source" else "text"
            ]
        except (KeyError, ValueError):
            return ()
        digest = hashlib.sha256(body.encode()).hexdigest()
        return tuple(sorted({span
                            for binding in self.visible_bindings.values()
                            if binding.exact_ref == locator.exact_ref
                            and binding.kind == locator.kind
                            and binding.content_sha256 == digest
                            for span in binding.spans}))

    def append_material(
        self, projected: dict[str, Any], *, label: str = "Acquired observation",
    ) -> dict[str, Any]:
        message = {"role": "user", "content": label + ": " + json.dumps(
            projected, ensure_ascii=False,
        )}
        self.transcript.append(message)
        self.record_delivery(message, projected)
        return message

    def close(self) -> None:
        if (self.maintenance.get("protocol") in {"turn-maintenance-v4", "turn-maintenance-v5"}
                and self.maintenance.get("failed_attempts")):
            raise ValueError("PENDING_WRITE_REPAIR")
        self.closed = True
        self.read_cache.clear()
