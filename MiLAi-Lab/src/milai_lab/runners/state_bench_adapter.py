"""Research adapter: STATE executes domain tools; MiLAi supplies bounded evidence.

The optional upstream package is imported only when constructing its BaseAgent.
This module does not load tasks, judges, credentials, or official protocol checks.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.memory.functional_state import canonical
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory


def learning_envelope(packet: dict[str, Any]) -> dict[str, list[str]]:
    """One complete evidence receipt, within STATE's at-most-three-string contract."""
    return {"learnings": [canonical(packet)]}


MEMORY_SCHEMA = {
    "type": "function", "name": "retrieve_learnings",
    "description": "Retrieve source-bound historical evidence relevant to the current task. "
                   "An interpretation is not an original statement or current business state. "
                   "Use domain tools for current state and actions.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string"}, "top_k": {"type": "integer", "const": 3}},
        "required": ["query"], "additionalProperties": False},
}

RETRIEVAL_INSTRUCTION = (
    "Before your first substantive answer, call retrieve_learnings with a query based on "
    "the actual user request and visible conversation. You may retrieve again when needed. "
    "Its at-most-three strings contain bounded MiLAi evidence receipts, not task solutions "
    "or business authorization. Apply historical guidance only when relevant and consistent "
    "with current domain tools, results and policies. Keep other users and past transactions "
    "distinct from the current user and task."
)


def conversation_messages(conversation: list[dict[str, Any]]) -> list[BaseMessage]:
    """Render the upstream canonical transcript, including executed tool results once."""
    messages: list[BaseMessage] = []
    for index, row in enumerate(conversation):
        if row["role"] == "user":
            messages.append(HumanMessage(content=row["content"]))
        elif row["role"] == "assistant":
            records = row.get("tool_calls") or []
            calls = [{"name": call["name"], "args": call["arguments"],
                      "id": f"state-{index}-{number}", "type": "tool_call"}
                     for number, call in enumerate(records)]
            messages.append(AIMessage(content=row.get("content") or "", tool_calls=calls))
            messages.extend(ToolMessage(content=canonical(call["result"]), name=call["name"],
                tool_call_id=calls[number]["id"]) for number, call in enumerate(records))
        elif row["role"] == "system":
            messages.append(SystemMessage(content=row["content"]))
        elif row["role"] != "tool":
            raise ValueError(f"Unsupported STATE conversation role: {row['role']}")
        # The upstream's extra tool row repeats the preceding assistant's executed records.
    return messages


class StateMemoryHook:
    """Bind actual public turns and call the existing registered retrieval tool."""

    def __init__(self, memory: IntentRetrievalMemory, *, session: str, now: str,
                 domain: str, user_id: str, config_version: str,
                 record: Callable[[dict[str, Any]], None]) -> None:
        self.memory, self.session, self.now = memory, session, now
        self.domain, self.user_id, self.config_version = domain, user_id, config_version
        self.record = record
        self.memory.return_envelope = learning_envelope
        self.turn: str | None = None
        self.config: RunnableConfig | None = None
        self.references: list[dict[str, Any]] = []
        self.calls = 0

    def bind_conversation(self, conversation: list[dict[str, Any]]) -> bool:
        users = [row for row in conversation if row["role"] == "user"]
        turn = f"turn-{len(users)}"
        if turn == self.turn:
            return False
        content = users[-1]["content"]
        service = self.memory.service
        source = service.capture_user(self.session, turn, content)
        service.bind_source_boundary(self.session, turn, [source["source_ref"]])
        service.bind_public_turn(self.session, turn, source["source_ref"],
                                config_version=self.config_version, phase="start")
        self.turn = turn
        self.config = cast(RunnableConfig, {"configurable": {"user_id": service.owner,
            "v13_session": self.session, "v13_turn_id": turn,
            "v13_config_version": self.config_version}})
        return True

    def retrieve(self, arguments: dict[str, Any]) -> dict[str, list[str]]:
        if self.config is None:
            raise ValueError("STATE retrieval requires an observed public user turn")
        self.calls += 1
        request = {"query": arguments["query"], "task_context": {
            "as_of": self.now, "target_scope": {"domain": self.domain, "user_id": self.user_id},
            "known_evidence_refs": list(self.references)}}
        response = self.memory.tools()[0].invoke({"type": "tool_call", "name": "milai_retrieve",
            "id": f"state-retrieve-{self.calls}", "args": request}, config=self.config)
        packet = json.loads(response.content)
        for item in packet["evidence"]:
            if item["ref"] not in self.references:
                self.references.append(item["ref"])
        envelope = learning_envelope(packet)
        self.record({"event": "state_memory_delivery", "public_turn": self.turn,
            "request": request, "packet": packet, "envelope": envelope,
            "complete_return_tokens": self.memory.return_tokens(packet)})
        return envelope


def make_state_agent(model: Any, hook: StateMemoryHook, runtime_context: Any) -> Any:
    """Use the public BaseAgent hook without retaining hidden evaluator context."""
    from state_bench.agents.base import AgentRuntimeContext, AgentTurnResponse, BaseAgent

    public_context = AgentRuntimeContext(task_id=hook.session,
        user_id=runtime_context.user_id, domain=runtime_context.domain, now=runtime_context.now)

    class MiLAiStateAgent(BaseAgent):  # type: ignore[misc]  # Optional upstream SDK.
        def memory_tool_schemas(self) -> list[dict[str, Any]]:
            return [MEMORY_SCHEMA]

        def memory_tool_handlers(self) -> dict[str, Any]:
            return {"retrieve_learnings": hook.retrieve}

        def generate_next_turn(self, *, system_prompt: str, conversation: list[dict[str, Any]],
                               tools: list[dict[str, Any]]) -> Any:
            if hook.bind_conversation(conversation):
                model.begin_public_message(hook.turn)
            messages = [SystemMessage(content=system_prompt + "\n\n" + RETRIEVAL_INSTRUCTION),
                        *conversation_messages(conversation)]
            # STATE publishes flat Responses schemas; the chat bridge uses nested functions.
            chat_tools = [{"type": "function", "function": {
                key: value for key, value in tool.items() if key != "type"}} for tool in tools]
            result = model.bind_tools(chat_tools).invoke(messages)
            if result.usage_metadata:
                self.add_token_usage(input_tokens=result.usage_metadata["input_tokens"],
                                     output_tokens=result.usage_metadata["output_tokens"])
            return AgentTurnResponse(text=result.content, tool_calls=[
                {"name": call["name"], "arguments": call["args"]} for call in result.tool_calls])

    return MiLAiStateAgent(runtime_context=public_context)
