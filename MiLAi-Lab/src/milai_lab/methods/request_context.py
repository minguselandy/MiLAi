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


def json_action_calls(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One history encoder, shared by boundary and historical JSON request paths."""
    encoded = []
    for call in calls:
        function = call["function"]
        try:
            arguments = json.loads(function["arguments"])
        except (TypeError, ValueError) as exc:
            raise ValueError("JSON_ACTION_HISTORY_INVALID_ARGUMENTS") from exc
        if not isinstance(arguments, dict):
            raise ValueError("JSON_ACTION_HISTORY_ARGUMENTS_NOT_OBJECT")
        encoded.append({"name": function["name"], "arguments": arguments})
    return {"calls": encoded}


def record_material(records: Sequence[Mapping[str, Any]],
                    model_view: ModelView = ModelView.FULL) -> str:
    rows: Sequence[Mapping[str, Any]] = records
    if model_view is ModelView.COMPACT_V6:
        projected = []
        for record in records:
            value = record.get("value")
            # Unknown fields remain intact; no field is classified as non-semantic here.
            projected.append({"id": record["id"], "content": value["content"]}
                if set(record) == {"id", "value"} and isinstance(value, Mapping)
                and set(value) == {"content"} else record)
        rows = projected
    return "[DURABLE MEMORY]\n" + json.dumps(rows, ensure_ascii=False) + "\n[/DURABLE MEMORY]"


def render_system(context: RequestContext, placement: MemoryPlacement) -> str:
    """Retain the original separator even when memory is carried by the user copy."""
    state = context.working_state
    if context.model_view is ModelView.COMPACT_V6 and state is not None:
        state = {key: value for key, value in state.items()
                 if key not in {"active_refs", "open_questions"} or value != []}
    return (
        (context.action_protocol + "\n" if context.action_protocol is not None else "")
        + context.base_system
        + ("\n" + context.boundary_protocol if context.boundary_protocol is not None else "")
        + "\n"
        + (record_material(context.durable_records, context.model_view)
           if placement is MemoryPlacement.SYSTEM else "")
        + context.system_tail
        + ("\n[WORKING HYPOTHESIS - current task references]\n"
           + json.dumps(state, ensure_ascii=False) if state is not None else "")
    )


def render_request(context: RequestContext, placement: MemoryPlacement) -> list[dict[str, Any]]:
    system = dict(context.system_message)
    system["content"] = render_system(context, placement)
    messages = [dict(message) for message in context.messages]
    for history_index, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            if context.history_protocol == "json_action":
                body = json.dumps(json_action_calls(message["tool_calls"]), ensure_ascii=False)
                message.pop("tool_calls")
            else:
                body = message["content"]
            label = context.assistant_call_labels.get(history_index)
            message["content"] = (label + "\n" if label else "") + body
    for observation_index, observation in context.tool_observations.items():
        metadata = {key: value for key, value in observation.items()
                    if context.model_view is ModelView.FULL or key != "content_sha256"}
        messages[observation_index]["content"] = (
            "[TOOL OBSERVATION] " + json.dumps(metadata, ensure_ascii=False)
            + "\n" + messages[observation_index]["content"])
    if placement is MemoryPlacement.CURRENT_REQUEST:
        position = context.current_user_index
        if position is None or not 0 <= position < len(messages) or (
            messages[position].get("role") != "user"
        ):
            raise ValueError("MEMORY_BOUNDARY_CURRENT_USER_MISSING")
        messages[position]["content"] = (
            record_material(context.durable_records, context.model_view)
            + "\n" + messages[position]["content"])
    return [system, *messages]
