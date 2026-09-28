"""Explicit request parts and one renderer; stored messages remain untouched."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class MemoryPlacement(StrEnum):
    SYSTEM = "system"
    CURRENT_REQUEST = "current_request"


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

    def with_records(self, records: Sequence[Mapping[str, Any]]) -> RequestContext:
        return replace(self, durable_records=tuple(records))

    def with_action_protocol(self, protocol: str) -> RequestContext:
        return replace(self, action_protocol=protocol)


def record_material(records: Sequence[Mapping[str, Any]]) -> str:
    return "[DURABLE MEMORY]\n" + json.dumps(records, ensure_ascii=False) + "\n[/DURABLE MEMORY]"


def render_system(context: RequestContext, placement: MemoryPlacement) -> str:
    """Retain the original separator even when memory is carried by the user copy."""
    return (
        (context.action_protocol + "\n" if context.action_protocol is not None else "")
        + context.base_system
        + ("\n" + context.boundary_protocol if context.boundary_protocol is not None else "")
        + "\n"
        + (record_material(context.durable_records) if placement is MemoryPlacement.SYSTEM else "")
        + context.system_tail
        + ("\n[WORKING HYPOTHESIS - current task references]\n"
           + json.dumps(context.working_state, ensure_ascii=False)
           if context.working_state is not None else "")
    )


def render_request(context: RequestContext, placement: MemoryPlacement) -> list[dict[str, Any]]:
    system = dict(context.system_message)
    system["content"] = render_system(context, placement)
    messages = [dict(message) for message in context.messages]
    if placement is MemoryPlacement.CURRENT_REQUEST:
        position = context.current_user_index
        if position is None or not 0 <= position < len(messages) or (
            messages[position].get("role") != "user"
        ):
            raise ValueError("MEMORY_BOUNDARY_CURRENT_USER_MISSING")
        messages[position]["content"] = (
            record_material(context.durable_records) + "\n" + messages[position]["content"])
    return [system, *messages]
