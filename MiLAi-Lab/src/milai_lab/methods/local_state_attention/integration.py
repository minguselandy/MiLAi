"""Graph v1 input view; checkpoint messages and business ToolMessages stay intact."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.methods.local_state_attention.bank import StateScope
from milai_lab.methods.local_state_attention.controller import LocalStateController


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
                        system_prompt: str) -> Any:
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
        selected = set(result["focus"])
        states = [row for row in controller.bank.states(scope) if row["id"] in selected]
        pending = controller.bank.pending(scope)
        view = _render_view(states, pending)
        if controller.emit is not None:
            controller.emit({"event": "lsa_view", "message_key":
                             f"{thread_id}:{public_index}", "user_id": scope.user_id,
                             "focus": result["focus"], "states": states,
                             "pending_source_ids": [row["id"] for row in pending],
                             "degraded": result["degraded"], "view": view})
        prompt = system_prompt + ("\n" + view if view else "")
        # One first system copy, just as the ordinary prompt path delivers. All graph
        # messages remain their original objects and IDs; no synthetic tool evidence.
        return {"llm_input_messages": [SystemMessage(content=prompt), *input_messages]}

    return hook


def _render_view(states: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
    if not states and not pending:
        return ""
    rows = ["[Local State working view: model estimates, source IDs are references. "
            "Current user and tool messages below remain authoritative observations.] "]
    for state in states:
        rows.append(json.dumps({key: state[key] for key in (
            "id", "title", "content", "needs", "evidence_refs", "revision")},
            ensure_ascii=False))
    if pending:
        rows.append("Unprocessed current observations; stored States may not incorporate them:")
        rows.extend(json.dumps({key: row[key] for key in ("id", "kind", "content")},
                               ensure_ascii=False) for row in pending)
    return "\n".join(rows)
