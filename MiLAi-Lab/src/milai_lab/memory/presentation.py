"""Render memory and history on request copies without changing stored messages."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from milai_lab.contracts.request import MemoryPlacement, ModelView, RequestContext


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
