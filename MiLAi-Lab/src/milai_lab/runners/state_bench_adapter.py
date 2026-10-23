"""Research adapter: STATE executes domain tools; MiLAi supplies bounded evidence.

The optional upstream package is imported only when constructing its BaseAgent.
This module does not load tasks, judges, credentials, or official protocol checks.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.functional_state import canonical
from milai_lab.memory.retrieval_request import RetrievalRequest, StructuredReadGoal
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.readonly_retrieval import ReadOnlyRetrieval


def learning_envelope(packet: dict[str, Any]) -> dict[str, list[str]]:
    """One complete evidence receipt, within STATE's at-most-three-string contract."""
    return {"learnings": [canonical(packet)]}


MEMORY_SCHEMA = {
    "type": "function", "name": "retrieve_learnings",
    "description": "Retrieve source-bound historical evidence relevant to the current task. "
                   "An interpretation is not an original statement or current business state. "
                   "Use domain tools for current state and actions.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string"}, "top_k": {"type": "integer", "const": 3},
        "read_goal": StructuredReadGoal.model_json_schema()},
        "required": ["query"], "additionalProperties": False},
}

RETRIEVAL_INSTRUCTION = (
    "Before your first substantive answer, call retrieve_learnings with a query based on "
    "the actual user request and visible conversation. You may retrieve again when needed. "
    "When useful, specify read_goal with your purpose, required_points and evidence type. "
    "Its at-most-three strings contain bounded MiLAi evidence receipts, not task solutions "
    "or business authorization. Apply historical guidance only when relevant and consistent "
    "with current domain tools, results and policies. Keep other users and past transactions "
    "distinct from the current user and task."
)


def run_with_domain_snapshots(environment: Any, output: Path,
                              operation: Callable[[], Any]) -> Any:
    """Preserve sandbox effects even if a later Host/simulator call fails."""
    from state_bench.schemas import StateDiff

    before = environment.get_full_snapshot()
    write_json(output / "state-before.json", before)
    try:
        return operation()
    finally:
        after = environment.get_full_snapshot()
        write_json(output / "state-after.json", after)
        write_json(output / "state-diff.json", StateDiff.compute(before, after).to_dict())


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
    """Local dynamic protocol: capture public observations and retrieve bounded evidence.

    This hook writes Sources and request receipts. It is not the official read-only
    Learning Track hook. Business effects remain in STATE's domain handlers.
    """

    schema = MEMORY_SCHEMA

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
        self.captured_events: set[str] = set()

    def bind_conversation(self, conversation: list[dict[str, Any]]) -> bool:
        service = self.memory.service
        previous_turn = self.turn
        user_number, tool_number, final_text = 0, 0, ""
        for row in conversation:
            if row["role"] == "user":
                # The next user closes the preceding assistant turn. STATE may
                # have folded all its tool rounds into one transcript row.
                final_key = f"turn-{user_number}-assistant"
                if final_text and final_key not in self.captured_events:
                    receipt = service.capture_assistant(self.session, final_key, final_text)
                    if not receipt["ok"]:
                        raise ValueError("STATE_PUBLIC_SOURCE_CAPTURE_FAILED:" + receipt["status"])
                    self.captured_events.add(final_key)
                user_number, tool_number, final_text = user_number + 1, 0, ""
                turn = f"turn-{user_number}"
                if turn not in self.captured_events:
                    source = service.capture_user(self.session, turn, row["content"])
                    service.bind_source_boundary(self.session, turn, [source["source_ref"]])
                    service.bind_public_turn(self.session, turn, source["source_ref"],
                        config_version=self.config_version, phase="start")
                    self.captured_events.add(turn)
                    self.turn = turn
                    self.config = cast(RunnableConfig, {"configurable": {
                        "user_id": service.owner, "v13_session": self.session,
                        "v13_turn_id": turn, "v13_config_version": self.config_version}})
            elif row["role"] == "assistant":
                for call in row.get("tool_calls") or []:
                    tool_number += 1
                    key = f"turn-{user_number}-tool-{tool_number}"
                    # Retrieval receipts already retain their source references;
                    # copying them into a new Source would invent independent support.
                    if call["name"] != "retrieve_learnings" and key not in self.captured_events:
                        receipt = service.capture_tool(self.session, key, call["name"],
                            canonical({field: call[field]
                                       for field in ("name", "arguments", "result")}), None)
                        if not receipt["ok"]:
                            raise ValueError("STATE_PUBLIC_SOURCE_CAPTURE_FAILED:"
                                             + receipt["status"])
                        self.captured_events.add(key)
                final_text = row.get("content") or ""
            # Upstream tool rows repeat the preceding assistant's executed calls.
        return self.turn != previous_turn

    def retrieve(self, arguments: dict[str, Any]) -> dict[str, list[str]]:
        if self.config is None:
            raise ValueError("STATE retrieval requires an observed public user turn")
        self.calls += 1
        request = {"query": arguments["query"], "task_context": {
            "as_of": self.now, "target_scope": {"domain": self.domain, "user_id": self.user_id},
            "known_evidence_refs": list(self.references)}}
        if "read_goal" in arguments:
            request["read_goal"] = arguments["read_goal"]
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


class StateReadOnlyMemoryHook:
    """Learning-track retrieval boundary over a prebuilt training artifact.

    No test user, assistant or domain-tool messages enter the artifact. Turn
    allowance and references to actual returned material stay in this task only.
    This boundary alone does not supply the official simulator/judge or full run.
    """

    schema: ClassVar[dict[str, Any]] = {**MEMORY_SCHEMA, "parameters": {
        "type": "object", "properties": {
        "query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1}},
        "required": ["query"], "additionalProperties": False}}

    def __init__(self, memory: ReadOnlyRetrieval, *, session: str, now: str,
                 domain: str, user_id: str,
                 record: Callable[[dict[str, Any]], None]) -> None:
        self.memory, self.session, self.now = memory, session, now
        self.domain, self.user_id, self.record = domain, user_id, record
        self.memory.return_envelope = lambda packet: [canonical(packet)]
        self.turn: str | None = None
        self.references: list[dict[str, Any]] = []
        self.calls = 0

    def bind_conversation(self, conversation: list[dict[str, Any]]) -> bool:
        turn = f"turn-{sum(row['role'] == 'user' for row in conversation)}"
        if turn == self.turn:
            return False
        self.turn = turn
        self.memory.begin_turn(turn)
        return True

    def retrieve(self, arguments: dict[str, Any]) -> list[str]:
        self.calls += 1
        request = RetrievalRequest.model_validate({"query": arguments["query"], "task_context": {
            "as_of": self.now, "target_scope": {"domain": self.domain, "user_id": self.user_id},
            "known_evidence_refs": list(self.references)}})
        packet = self.memory.retrieve(request)
        for item in packet["evidence"]:
            if item["ref"] not in self.references:
                self.references.append(item["ref"])
        # One complete bounded receipt satisfies the configured top_k<=3 contract;
        # a model-supplied larger top_k never expands this boundary.
        envelope = [canonical(packet)]
        self.record({"event": "state_readonly_memory_delivery", "public_turn": self.turn,
            "request": request.project(), "packet": packet, "envelope": envelope,
            "complete_return_tokens": self.memory.return_tokens(packet)})
        return envelope


def make_state_agent(model: Any, hook: StateMemoryHook | StateReadOnlyMemoryHook | None,
                     runtime_context: Any, *,
                     initial_retrieval: dict[str, Any] | None = None,
                     observe_host: Callable[[dict[str, Any]], None] = lambda _: None) -> Any:
    """Use the public BaseAgent hook without retaining hidden evaluator context."""
    from state_bench.agents.base import AgentRuntimeContext, AgentTurnResponse, BaseAgent

    if initial_retrieval is not None:
        from jsonschema import validate

        validate(initial_retrieval, MEMORY_SCHEMA["parameters"])
        if hook is None:
            raise ValueError("Initial retrieval requires a memory hook")
        initial_retrieval = dict(initial_retrieval)
    public_context = AgentRuntimeContext(task_id=hook.session if hook is not None else "state-task",
        user_id=runtime_context.user_id, domain=runtime_context.domain, now=runtime_context.now)
    public_turn: str | None = None

    class MiLAiStateAgent(BaseAgent):  # type: ignore[misc]  # Optional upstream SDK.
        def memory_tool_schemas(self) -> list[dict[str, Any]]:
            return [hook.schema] if hook is not None else []

        def memory_tool_handlers(self) -> dict[str, Any]:
            return {"retrieve_learnings": hook.retrieve} if hook is not None else {}

        def generate_next_turn(self, *, system_prompt: str, conversation: list[dict[str, Any]],
                               tools: list[dict[str, Any]]) -> Any:
            nonlocal initial_retrieval, public_turn
            if hook is not None:
                if hook.bind_conversation(conversation):
                    model.begin_public_message(hook.turn)
            else:
                turn = f"turn-{sum(row['role'] == 'user' for row in conversation)}"
                if turn != public_turn:
                    model.begin_public_message(turn)
                    public_turn = turn
            if initial_retrieval is not None:
                assert hook is not None
                arguments, initial_retrieval = initial_retrieval, None
                hook.record({"event": "state_frozen_initial_retrieval", "arguments": arguments,
                             "scope": "Actual prior Host request; conditional interface probe"})
                observe_host(copy.deepcopy({"host_request_generated": False,
                    "system_prompt": system_prompt, "conversation": conversation, "tools": tools,
                    "response": {"text": "", "tool_calls": [
                        {"name": "retrieve_learnings", "arguments": arguments}]}}))
                return AgentTurnResponse(tool_calls=[
                    {"name": "retrieve_learnings", "arguments": arguments}])
            prompt = system_prompt + ("\n\n" + RETRIEVAL_INSTRUCTION if hook is not None else "")
            messages = [SystemMessage(content=prompt),
                        *conversation_messages(conversation)]
            # STATE publishes flat Responses schemas; the chat bridge uses nested functions.
            chat_tools = [{"type": "function", "function": {
                key: value for key, value in tool.items() if key != "type"}} for tool in tools]
            result = model.bind_tools(chat_tools).invoke(messages)
            observe_host(copy.deepcopy({"host_request_generated": True,
                "system_prompt": messages[0].content, "conversation": conversation,
                "tools": tools, "response": {"text": result.content, "tool_calls": [
                    {"name": call["name"], "arguments": call["args"]}
                    for call in result.tool_calls]}}))
            if result.usage_metadata:
                self.add_token_usage(input_tokens=result.usage_metadata["input_tokens"],
                                     output_tokens=result.usage_metadata["output_tokens"])
            return AgentTurnResponse(text=result.content, tool_calls=[
                {"name": call["name"], "arguments": call["args"]} for call in result.tool_calls])

    return MiLAiStateAgent(runtime_context=public_context)
