"""Explicit request-part contracts; stored messages remain untouched."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class MemoryPlacement(StrEnum):
    SYSTEM = "system"
    CURRENT_REQUEST = "current_request"


class ModelView(StrEnum):
    FULL = "full"
    COMPACT_V6 = "compact_v6"


@dataclass(frozen=True)
class RequestContext:
    base_system: str
    durable_records: tuple[Mapping[str, Any], ...]
    boundary_protocol: str | None = None
    system_tail: str = ""
    working_state: Mapping[str, Any] | None = None
    messages: tuple[Mapping[str, Any], ...] = ()
    current_user_index: int | None = None
    system_message: Mapping[str, Any] = field(default_factory=lambda: {"role": "system"})
    action_protocol: str | None = None
    model_view: ModelView = ModelView.FULL
    tool_observations: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    history_protocol: str = "json_action"
    assistant_call_labels: Mapping[int, str] = field(default_factory=dict)

    def with_records(self, records: Sequence[Mapping[str, Any]]) -> RequestContext:
        return replace(self, durable_records=tuple(records))

    def with_action_protocol(self, protocol: str | None) -> RequestContext:
        return replace(self, action_protocol=protocol)

    def with_model_view(self, model_view: ModelView) -> RequestContext:
        return replace(self, model_view=model_view)

    def with_protocol(self, protocol: str, boundary_protocol: str | None) -> RequestContext:
        if protocol not in {"json_action", "native"}:
            raise ValueError("MEMORY_BOUNDARY_PROTOCOL_UNKNOWN")
        return replace(self, history_protocol=protocol, boundary_protocol=boundary_protocol)
