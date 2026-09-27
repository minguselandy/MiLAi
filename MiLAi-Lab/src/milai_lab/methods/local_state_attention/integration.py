"""Graph v1 input view; checkpoint messages and business ToolMessages stay intact."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.methods.local_state_attention.bank import LocalStateBank, StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController

SOURCE_VIEW_HEADER = "Referenced source events from delivered States:"


def _source_id(thread_id: str, position: int, message: BaseMessage) -> str:
    if isinstance(message, ToolMessage) and message.tool_call_id:
        return "tool:" + hashlib.sha256(json.dumps(
            [thread_id, message.tool_call_id], ensure_ascii=False).encode()).hexdigest()
    if message.id:
        return "message:" + message.id
    return "message:" + hashlib.sha256(json.dumps(
        [thread_id, position, message.type, message.content],
        ensure_ascii=False, default=str).encode()).hexdigest()


def make_pre_model_hook(controller: LocalStateController,
                        system_prompt: str, read_policy: str = "focus",
                        source_view_max_bytes: int | None = None) -> Any:
    if read_policy not in {"focus", "all", "all_sources", "focus_sources"}:
        raise ValueError("LSA_READ_POLICY_UNKNOWN")
    if read_policy in {"all_sources", "focus_sources"} and (
        type(source_view_max_bytes) is not int or source_view_max_bytes <= 0
    ):
        raise ValueError("LSA_SOURCE_VIEW_BUDGET_INVALID")

    def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        cfg = config["configurable"]
        scope = StateScope(cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"])
        thread_id = cfg["thread_id"]
        messages: list[BaseMessage] = state["messages"]
        latest_user: tuple[str, str] | None = None
        input_messages: list[BaseMessage] = []
        forgotten_positions: list[int] = []
        for position, message in enumerate(messages):
            if not isinstance(message, (HumanMessage, ToolMessage)):
                input_messages.append(message)
                continue
            source_id = _source_id(thread_id, position, message)
            if controller.bank.is_forgotten(scope, source_id):
                forgotten_positions.append(position)
                input_messages.append(message.model_copy(
                    update={"content": "[authorized source deletion]"}))
                continue
            input_messages.append(message)
            kind = "user" if isinstance(message, HumanMessage) else "tool"
            event = {"id": source_id, "kind": kind, "content": message.content,
                     "thread_id": thread_id,
                     "actor": (cfg["user_id"] if kind == "user"
                               else message.name or "tool"),
                     "tool_call_id": (message.tool_call_id
                                      if isinstance(message, ToolMessage) else None)}
            controller.bank.record_event(scope, event)
            if isinstance(message, HumanMessage):
                latest_user = (source_id, str(message.content))
        if latest_user is None:
            raise ValueError("LSA_CURRENT_USER_MISSING")
        if forgotten_positions:
            # An old assistant answer may repeat deleted source content. Resume the
            # working view at the next genuine user turn after the deletion marker.
            restart = next((index for index, message in enumerate(messages)
                            if index > max(forgotten_positions)
                            and isinstance(message, HumanMessage)), None)
            if restart is not None:
                input_messages = input_messages[restart:]
        public_index = sum(isinstance(message, HumanMessage) for message in messages) - 1
        result = controller.prepare(scope, *latest_user,
                                    message_key=f"{thread_id}:{public_index}")
        controller_focus = result["focus"]
        states = controller.bank.states(scope)
        if read_policy in {"focus", "focus_sources"}:
            selected = set(controller_focus)
            states = [row for row in states if row["id"] in selected]
        pending = controller.bank.pending(scope)
        source_lines: list[str] = []
        source_trace: dict[str, Any] = {}
        if read_policy in {"all_sources", "focus_sources"}:
            assert source_view_max_bytes is not None
            source_lines, source_trace = _source_view(
                controller.bank, scope, states, source_view_max_bytes)
        view = _render_view(states, pending, source_lines)
        if controller.emit is not None:
            controller.emit({"event": "lsa_view", "message_key":
                             f"{thread_id}:{public_index}", "user_id": scope.user_id,
                             "focus": controller_focus, "controller_focus": controller_focus,
                             "delivered_state_ids": [row["id"] for row in states],
                             "read_policy": read_policy, "states": states,
                             "pending_source_ids": [row["id"] for row in pending],
                             "degraded": result["degraded"], "view": view,
                             **source_trace})
        prompt = system_prompt + ("\n" + view if view else "")
        # One first system copy, just as the ordinary prompt path delivers. All graph
        # messages remain their original objects and IDs; no synthetic tool evidence.
        return {"llm_input_messages": [SystemMessage(content=prompt), *input_messages]}

    return hook


def _source_view(bank: LocalStateBank, scope: StateScope,
                 states: list[dict[str, Any]], max_bytes: int,
                 ) -> tuple[list[str], dict[str, Any]]:
    source_ids: list[str] = []
    invalid_refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for state in states:
        refs = state.get("evidence_refs", [])
        if not isinstance(refs, list):
            invalid_refs.append({"state_id": state["id"], "reference": repr(refs)})
            continue
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                invalid_refs.append({"state_id": state["id"], "reference": repr(ref)})
            elif ref not in seen:
                seen.add(ref)
                source_ids.append(ref)
    resolution = bank.resolve_evidence(scope, source_ids)
    events = sorted(resolution.events, key=lambda row: (row["arrival_index"], row["id"]))
    lines = [SOURCE_VIEW_HEADER]
    used_bytes = len(("\n" + SOURCE_VIEW_HEADER).encode("utf-8"))
    delivered_ids: list[str] = []
    omitted: list[dict[str, int | str]] = []
    for event in events:
        visible = {key: event.get(key) for key in (
            "id", "kind", "actor", "tool_call_id", "content")}
        line = json.dumps(visible, ensure_ascii=False)
        line_bytes = len(("\n" + line).encode("utf-8"))
        if used_bytes + line_bytes > max_bytes:
            omitted.append({"id": event["id"], "bytes": line_bytes})
            continue
        lines.append(line)
        delivered_ids.append(event["id"])
        used_bytes += line_bytes
    if not delivered_ids:
        lines = []
        used_bytes = 0
    trace = {"source_view_max_bytes": max_bytes,
             "source_view_bytes": used_bytes,
             "source_requested_ids": source_ids,
             "source_delivered_ids": delivered_ids,
             "source_deleted_ids": resolution.deleted_source_ids,
             "source_missing_ids": resolution.missing_source_ids,
             "source_invalid_refs": invalid_refs,
             "source_omitted": omitted}
    return lines, trace


def _render_view(states: list[dict[str, Any]], pending: list[dict[str, Any]],
                 source_lines: list[str] | None = None) -> str:
    if not states and not pending and not source_lines:
        return ""
    rows = ["[Local State working view: model estimates, source IDs are references. "
            "Current user and tool messages below remain authoritative observations.] "]
    for state in states:
        rows.append(json.dumps({key: state[key] for key in (
            "title", "content", "needs", "evidence_refs")},
            ensure_ascii=False))
    if source_lines:
        rows.extend(source_lines)
    if pending:
        rows.append("Unprocessed current observations; stored States may not incorporate them:")
        rows.extend(json.dumps({key: row[key] for key in ("id", "kind", "content")},
                               ensure_ascii=False) for row in pending)
    return "\n".join(rows)
