"""LangGraph chat bridge over the Lab's accounted vLLM transports."""

from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.freshness_projection.projection import SOURCE_AUTHORITY
from milai_lab.methods.milai_m1.controller import M1_PROTOCOL, m1_action_schema
from milai_lab.methods.on_demand_reconstruction.schema import (
    ODR_PROTOCOL,
    ReconstructionError,
    odr_action_schema,
)
from milai_lab.providers.contextual_vllm import VLLMClient


class IncompleteChatResponse(ValueError):
    """The provider response cannot safely be interpreted or executed."""


def _action_schema(
    tools: list[dict[str, Any]], *, generation_only: bool = False,
) -> dict[str, Any]:
    branches = []
    for item in tools:
        function = item["function"]
        branches.append({
            "type": "object",
            "properties": {
                "name": {"const": function["name"]},
                "arguments": {"type": "object"} if generation_only
                else function["parameters"],
            },
            "required": ["name", "arguments"],
            "additionalProperties": False,
        })
    return {
        "oneOf": [
            {"type": "object", "properties": {"answer": {"type": "string"}},
             "required": ["answer"], "additionalProperties": False},
            {"type": "object", "properties": {"calls": {
                "type": "array", "items": {"oneOf": branches}, "minItems": 1,
            }}, "required": ["calls"], "additionalProperties": False},
        ],
    }


def _action_prompt(tools: list[dict[str, Any]]) -> str:
    catalog = [item["function"] for item in tools]
    return (
        "Reply as exactly one JSON object. For a final reply use {\"answer\":\"...\"}. "
        "To call tools use {\"calls\":[{\"name\":\"...\",\"arguments\":{...}}]}. "
        "You may include several calls; they execute in listed order. "
        "Use the tool names, descriptions and argument schemas below exactly. "
        "A tool result will be returned before your next reply.\n"
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    )


def _json_action_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render prior graph calls in the same JSON-action format the model emitted."""
    rendered = []
    for message in messages:
        if message["role"] != "assistant" or not message.get("tool_calls"):
            rendered.append(message)
            continue
        calls = []
        for call in message["tool_calls"]:
            function = call["function"]
            try:
                arguments = json.loads(function["arguments"])
            except (TypeError, ValueError) as exc:
                raise IncompleteChatResponse("JSON_ACTION_HISTORY_INVALID_ARGUMENTS") from exc
            if not isinstance(arguments, dict):
                raise IncompleteChatResponse("JSON_ACTION_HISTORY_ARGUMENTS_NOT_OBJECT")
            calls.append({"name": function["name"], "arguments": arguments})
        history_message = {key: value for key, value in message.items() if key != "tool_calls"}
        history_message["content"] = json.dumps({"calls": calls}, ensure_ascii=False)
        rendered.append(history_message)
    return rendered


class VLLMChatModel(BaseChatModel):
    """Keep one HTTP and accounting owner while exposing LangChain's chat contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: VLLMClient
    max_calls_per_message: int = 12
    calls_in_message: int = 0
    capacity_path: Path | None = None
    active_message_key: str | None = None
    observer: Any = None
    m1: Any = None
    odr: Any = None
    projection: Any = None

    @property
    def _llm_type(self) -> str:
        return f"milai_vllm_{self.client.config.tool_mode}"

    def begin_public_message(self, key: str, checkpoint_calls: int = 0) -> None:
        self.active_message_key = key
        if self.capacity_path is None:
            self.calls_in_message = checkpoint_calls
            return
        state = read_json(self.capacity_path) if self.capacity_path.exists() else {}
        self.calls_in_message = max(state.get(key, 0), checkpoint_calls)

    def _reserve_request(self) -> None:
        if self.calls_in_message >= self.max_calls_per_message:
            raise ValueError("PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED")
        self.calls_in_message += 1
        if self.capacity_path is not None:
            if self.active_message_key is None:
                raise ValueError("PUBLIC_MESSAGE_CAPACITY_KEY_MISSING")
            state = read_json(self.capacity_path) if self.capacity_path.exists() else {}
            state[self.active_message_key] = self.calls_in_message
            write_json(self.capacity_path, state)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=converted, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop:
            raise ValueError("VLLM_CHAT_STOP_UNSUPPORTED")
        wire_messages = convert_to_openai_messages(messages)
        if not isinstance(wire_messages, list):
            raise TypeError("Expected a message sequence")
        tools = kwargs.get("tools") or []
        delivered_snapshot: tuple[list[dict[str, Any]], int] | None = None
        if self.client.config.tool_mode == "json_action":
            wire_messages = _json_action_history(wire_messages)
            generation_schema = _action_schema(tools, generation_only=True)
            protocol = _action_prompt(tools)
            m1_context = None
            odr_freshness = ""
            projected = None
            if self.m1 is not None:
                generation_schema = m1_action_schema(generation_schema)
                m1_context = self.m1.prompt_context(wire_messages)
                protocol += "\n" + M1_PROTOCOL + "\n" + m1_context
            if self.odr is not None:
                odr_freshness, odr_evidence = self.odr.project(wire_messages)
                if self.odr.arm == "odr":
                    generation_schema = odr_action_schema(generation_schema)
                    protocol += "\n" + ODR_PROTOCOL + "\n" + odr_evidence
                if odr_freshness:
                    protocol += "\n" + odr_freshness
            if self.projection is not None:
                projected = self.projection.project(
                    wire_messages, self.active_message_key, self.calls_in_message + 1,
                    messages)
                wire_messages = projected.messages
                protocol += "\n" + SOURCE_AUTHORITY
            if wire_messages and wire_messages[0]["role"] == "system":
                first = dict(wire_messages[0])
                if not isinstance(first.get("content"), str):
                    raise ValueError("JSON_ACTION_SYSTEM_CONTENT_NOT_TEXT")
                first["content"] = protocol + "\n" + first["content"]
                action_messages = [first, *wire_messages[1:]]
            else:
                action_messages = [{"role": "system", "content": protocol}, *wire_messages]
            self._reserve_request()
            scope = (self.observer.request_scope(
                self.active_message_key, self.calls_in_message,
                projected.materials if projected is not None else None)
                     if self.observer is not None else nullcontext())
            with scope:
                receipt = self.client.chat(
                    action_messages,
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "langmem_json_action_v1", "strict": True,
                        "schema": generation_schema,
                    }},
                )
                if projected is not None:
                    delivered_snapshot = self.projection.record_delivery(
                        self.active_message_key, self.calls_in_message,
                        projected, action_messages)
            if self.m1 is not None and self.client.emit is not None:
                self.client.emit({
                    "event": "m1_decision_context", "status": "delivered",
                    "request_id": self.m1.request_id(self.calls_in_message),
                    "text": m1_context,
                })
            if self.odr is not None and self.client.emit is not None:
                self.client.emit({
                    "event": "odr_request_projection", "arm": self.odr.arm,
                    "request_id": self.odr.request_id(self.calls_in_message),
                    "dynamic_freshness": odr_freshness,
                })
        else:
            self._reserve_request()
            scope = (self.observer.request_scope(self.active_message_key, self.calls_in_message)
                     if self.observer is not None else nullcontext())
            with scope:
                receipt = self.client.chat(
                    wire_messages,
                    tools=tools,
                    tool_choice=kwargs.get("tool_choice"),
                )
        choices = receipt.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise IncompleteChatResponse("VLLM_CHAT_EXPECTED_ONE_CHOICE")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise IncompleteChatResponse("VLLM_CHAT_TRUNCATED")
        if choice.get("finish_reason") not in {"stop", "tool_calls"}:
            raise IncompleteChatResponse("VLLM_CHAT_INVALID_FINISH_REASON")
        wire_message = choice.get("message")
        if not isinstance(wire_message, dict) or wire_message.get("role") != "assistant":
            raise IncompleteChatResponse("VLLM_CHAT_INVALID_MESSAGE")
        message_id = receipt.get("id") or uuid.uuid4().hex
        calls = []
        if self.client.config.tool_mode == "json_action":
            if wire_message.get("tool_calls"):
                raise IncompleteChatResponse("JSON_ACTION_UNEXPECTED_NATIVE_TOOL_CALL")
            try:
                action = json.loads(wire_message["content"])
            except (TypeError, ValueError) as exc:
                raise IncompleteChatResponse("JSON_ACTION_MALFORMED") from exc
            try:
                validate(action, generation_schema)
            except ValidationError as exc:
                if self.m1 is not None:
                    self.m1.record_error(
                        self.calls_in_message, message_id,
                        action.get("decision_delta") if isinstance(action, dict) else action,
                        "DECISION_ENVELOPE_SCHEMA_INVALID",
                    )
                if self.odr is not None and self.odr.arm == "odr":
                    raw = action.get("reconstruction") if isinstance(action, dict) else action
                    self.odr.reject(self.calls_in_message, message_id,
                                    "ODR_ENVELOPE_SCHEMA_INVALID", raw)
                raise IncompleteChatResponse("JSON_ACTION_SCHEMA_INVALID") from exc
            if self.m1 is not None:
                self.m1.commit(self.calls_in_message, message_id,
                               action["decision_delta"], action.get("calls"))
            if self.odr is not None and self.odr.arm == "odr":
                business_names = {item["function"]["name"] for item in tools}
                business_names -= {"manage_memory", "search_memory"}
                try:
                    self.odr.accept(self.calls_in_message, message_id,
                                    action["reconstruction"], action, business_names)
                except ReconstructionError as exc:
                    self.odr.reject(self.calls_in_message, message_id, str(exc),
                                    action.get("reconstruction"))
                    raise IncompleteChatResponse(str(exc)) from exc
            if "calls" in action:
                for index, call in enumerate(action["calls"]):
                    calls.append({"name": call["name"], "args": call["arguments"],
                                  "id": f"{message_id}:tool:{index}"})
                content = ""
            else:
                content = action["answer"]
        else:
            for call in wire_message.get("tool_calls") or []:
                function = call.get("function")
                if not isinstance(function, dict) or not call.get("id") or not function.get("name"):
                    raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_CALL")
                try:
                    args = json.loads(function["arguments"])
                except (TypeError, ValueError) as exc:
                    raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_ARGUMENTS") from exc
                if not isinstance(args, dict):
                    raise IncompleteChatResponse("VLLM_CHAT_TOOL_ARGUMENTS_NOT_OBJECT")
                calls.append({"name": function["name"], "args": args, "id": call["id"]})
            content = wire_message.get("content") or ""
        usage = receipt.get("usage") or {}
        usage_metadata = None
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            if type(prompt_tokens) is int and type(completion_tokens) is int:
                usage_metadata = {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                }
        message = AIMessage(
            id=message_id,
            content=content,
            tool_calls=calls,
            usage_metadata=usage_metadata,
            response_metadata={
                "finish_reason": choice["finish_reason"],
                "model": receipt.get("model"),
            },
        )
        if (self.projection is not None and delivered_snapshot is not None
                and not calls and isinstance(content, str)):
            exact_snapshot, unknown_items = delivered_snapshot
            self.projection.record_output(
                self.active_message_key, self.calls_in_message, message_id,
                content, exact_snapshot, unknown_items)
        return ChatResult(generations=[ChatGeneration(message=message)])
