"""Generic LangGraph chat bridge over the Lab's accounted vLLM transport."""

from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from jsonschema import ValidationError, validate  # type: ignore[import-untyped]
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict, Field, PrivateAttr

from milai_lab.contracts.read_protocol import present_catalog as receipt_catalog
from milai_lab.contracts.read_protocol import profile, save_guidance
from milai_lab.contracts.tool_schema_communication import (
    present_catalog,
    shape_guidance,
)
from milai_lab.contracts.tool_schema_communication import (
    profile as communication_profile,
)
from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.memory.presentation import json_action_calls
from milai_lab.providers.contextual_vllm import VLLMClient
from milai_lab.providers.generation_admission import DurableGenerationAdmission
from milai_lab.providers.request_pipeline import (
    ChatRequest,
    DeliveryObserver,
    PreparedRequest,
    RequestTransform,
    ResponseEvent,
    ResponseHook,
)


class IncompleteChatResponse(ValueError):
    """The provider response cannot safely be interpreted or executed."""


def _action_schema(
    tools: list[dict[str, Any]],
    *,
    generation_only: bool = False,
) -> dict[str, Any]:
    branches = []
    for item in tools:
        function = item["function"]
        branches.append(
            {
                "type": "object",
                "properties": {
                    "name": {"const": function["name"]},
                    "arguments": {"type": "object"} if generation_only else function["parameters"],
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
        )
    final: dict[str, Any] = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    return {
        "oneOf": [
            final,
            {
                "type": "object",
                "properties": {
                    "calls": {
                        "type": "array",
                        "items": {"oneOf": branches},
                        "minItems": 1,
                    }
                },
                "required": ["calls"],
                "additionalProperties": False,
            },
        ],
    }


def _action_prompt(
    tools: list[dict[str, Any]], *, tool_schema_communication: str = "legacy",
    tool_save_communication: str = "legacy"
) -> str:
    catalog = [item["function"] for item in receipt_catalog(
        present_catalog(tools, tool_schema_communication), tool_save_communication)]
    prompt = (
        'Reply as exactly one JSON object. For a final reply use {"answer":"..."}. '
        'To call tools use {"calls":[{"name":"...","arguments":{...}}]}. '
        "You may include several calls; they execute in listed order. "
        "Use the tool names, descriptions and argument schemas below exactly. "
        "A tool result will be returned before your next reply.\n"
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    )
    return (
        prompt + shape_guidance(tools, tool_schema_communication)
        + save_guidance(tool_save_communication)
    )


def _json_action_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render prior graph calls in the same JSON-action format the model emitted."""
    rendered = []
    for message in messages:
        if message["role"] != "assistant" or not message.get("tool_calls"):
            rendered.append(message)
            continue
        try:
            action = json_action_calls(message["tool_calls"])
        except ValueError as exc:
            raise IncompleteChatResponse(str(exc)) from exc
        history_message = {key: value for key, value in message.items() if key != "tool_calls"}
        history_message["content"] = json.dumps(action, ensure_ascii=False)
        rendered.append(history_message)
    return rendered


def _protocol_messages(messages: list[dict[str, Any]], protocol: str) -> list[dict[str, Any]]:
    if messages and messages[0]["role"] == "system":
        first = dict(messages[0])
        if not isinstance(first.get("content"), str):
            raise ValueError("JSON_ACTION_SYSTEM_CONTENT_NOT_TEXT")
        first["content"] = protocol + "\n" + first["content"]
        return [first, *messages[1:]]
    return [{"role": "system", "content": protocol}, *messages]


class VLLMChatModel(BaseChatModel):
    """Keep one HTTP and accounting owner while accepting explicit generic hooks."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    allow_required_tool_choice: bool = Field(default=False, exclude=True)
    preserve_tool_reasoning: bool = Field(default=False, exclude=True)
    client: VLLMClient
    max_calls_per_message: int = 12
    calls_in_message: int = 0
    capacity_path: Path | None = None
    active_message_key: str | None = None
    generation_admission_profile: Literal["legacy", "durable_shared_v1"] = Field(
        default="legacy", frozen=True
    )
    tool_schema_communication: Literal["legacy", "shape_feedback_v1"] = Field(
        default="legacy", frozen=True, exclude=True, repr=False
    )
    unknown_tool_feedback: bool = Field(default=False, frozen=True, exclude=True, repr=False)
    tool_save_communication: Literal["legacy", "completed_receipt_v1"] = Field(
        default="legacy", frozen=True, exclude=True, repr=False
    )
    _generation_admission: DurableGenerationAdmission | None = PrivateAttr(default=None)
    request_transform: RequestTransform | None = Field(default=None, exclude=True, repr=False)
    delivery_observer: DeliveryObserver | None = Field(default=None, exclude=True, repr=False)
    response_hook: ResponseHook | None = Field(default=None, exclude=True, repr=False)

    @property
    def _llm_type(self) -> str:
        return f"milai_vllm_{self.client.config.tool_mode}"

    def begin_public_message(
        self, key: str, checkpoint_calls: int = 0, *,
        admission_phase: Literal["start", "resume"] | None = None,
        admission_scope: dict[str, Any] | None = None,
    ) -> None:
        if self.generation_admission_profile == "durable_shared_v1":
            self._generation_admission = None
            self.active_message_key = None
            self.calls_in_message = 0
            if self.capacity_path is None or admission_phase is None or admission_scope is None:
                raise ValueError("GENERATION_ADMISSION_EXPLICIT_CONTEXT_REQUIRED")
            gate = DurableGenerationAdmission(
                self.capacity_path, key, admission_scope, asdict(self.client.config),
                self.max_calls_per_message, admission_phase, checkpoint_calls,
            )
            self._generation_admission = gate
            self.active_message_key = key
            self.calls_in_message = gate.count
            return
        self.active_message_key = key
        if self.capacity_path is None:
            self.calls_in_message = checkpoint_calls
            return
        state = read_json(self.capacity_path) if self.capacity_path.exists() else {}
        self.calls_in_message = max(state.get(key, 0), checkpoint_calls)

    def _reserve_request(self, *, origin: str | None = None) -> None:
        if self.generation_admission_profile == "durable_shared_v1":
            if self._generation_admission is None:
                raise ValueError("GENERATION_ADMISSION_NOT_STARTED")
            if self.active_message_key != self._generation_admission.identity["public_message_id"]:
                raise ValueError("GENERATION_ADMISSION_ACTIVE_MESSAGE_CHANGED")
            self.calls_in_message = self._generation_admission.reserve(
                asdict(self.client.config), self.max_calls_per_message, origin,
            )
            return
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

    def _notify_response(self, event: ResponseEvent) -> None:
        if self.response_hook is not None:
            self.response_hook.on_response(event)

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
        native = self.client.config.tool_mode == "native"
        if self.preserve_tool_reasoning:
            if not native:
                raise ValueError("TOOL_REASONING_HISTORY_REQUIRES_NATIVE")
            last_user = max((i for i, row in enumerate(wire_messages) if row["role"] == "user"),
                            default=-1)
            for index, (original, wire) in enumerate(zip(messages, wire_messages, strict=True)):
                if (last_user < 0 or index <= last_user or not isinstance(original, AIMessage)
                        or not original.tool_calls):
                    continue
                reasoning = original.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    if not isinstance(reasoning, str):
                        raise ValueError("VLLM_CHAT_INVALID_REASONING_HISTORY")
                    wire["reasoning_content"] = reasoning
        selected_communication = communication_profile(self.tool_schema_communication)
        if native and selected_communication != "legacy":
            wire_messages = _protocol_messages(
                wire_messages, shape_guidance(tools, selected_communication)
            )
            tools = present_catalog(tools, selected_communication)
        selected_save = profile("tool_save_communication", self.tool_save_communication)
        if native and selected_save != "legacy":
            wire_messages = _protocol_messages(wire_messages, save_guidance(selected_save))
            tools = receipt_catalog(tools, selected_save)
        request = ChatRequest(wire_messages, messages, tools, native, kwargs)
        if self.request_transform is not None:
            self.request_transform.validate(request)
        if native and (
            kwargs.get("tool_choice") not in (None, "auto", "none", "required")
            or (kwargs.get("tool_choice") == "required"
                and (not self.allow_required_tool_choice or not tools))
            or self.client.config.response_format is not None
        ):
            raise ValueError("NATIVE_CHAT_PROTOCOL_UNSUPPORTED")
        if self.request_transform is not None:
            prepared = self.request_transform.project(request)
        elif native:
            prepared = PreparedRequest(wire_messages, tools)
        else:
            prepared = PreparedRequest(
                _protocol_messages(
                    _json_action_history(wire_messages),
                    _action_prompt(tools, tool_schema_communication=selected_communication,
                                   tool_save_communication=selected_save),
                ),
                tools,
                _action_schema(tools, generation_only=True),
            )
        tools = prepared.tools
        if self.generation_admission_profile == "durable_shared_v1":
            self._reserve_request(origin="model_invoke")
        else:
            self._reserve_request()
        scope = (
            self.delivery_observer.request_scope(prepared, self.calls_in_message)
            if self.delivery_observer is not None
            else nullcontext()
        )
        with scope:
            if native:
                receipt = self.client.chat(
                    prepared.messages, tools=tools, tool_choice=kwargs.get("tool_choice")
                )
            else:
                receipt = self.client.chat(
                    prepared.messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "langmem_json_action_v1",
                            "strict": True,
                            "schema": prepared.schema,
                        },
                    },
                )
            if self.delivery_observer is not None:
                self.delivery_observer.record_delivery(prepared, receipt, self.calls_in_message)
        if self.delivery_observer is not None:
            self.delivery_observer.after_delivery(prepared, self.calls_in_message)
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
        completion_metadata: dict[str, Any] = {}
        if self.client.config.tool_mode == "json_action":
            if wire_message.get("tool_calls"):
                raise IncompleteChatResponse("JSON_ACTION_UNEXPECTED_NATIVE_TOOL_CALL")
            try:
                action = json.loads(wire_message["content"])
            except (TypeError, ValueError) as exc:
                raise IncompleteChatResponse("JSON_ACTION_MALFORMED") from exc
            event = ResponseEvent(
                "schema_outcome",
                prepared,
                receipt,
                message_id,
                action=action,
                completion_metadata=completion_metadata,
            )
            try:
                validate(action, prepared.schema)
            except ValidationError as exc:
                event.schema_error = exc
                self._notify_response(event)
                if not event.accept_schema_failure:
                    raise IncompleteChatResponse("JSON_ACTION_SCHEMA_INVALID") from exc
            else:
                self._notify_response(event)
            event.stage = "validated_action"
            self._notify_response(event)
            if "calls" in action:
                for index, call in enumerate(action["calls"]):
                    calls.append(
                        {
                            "name": call["name"],
                            "args": call["arguments"],
                            "id": f"{message_id}:tool:{index}",
                        }
                    )
                content = ""
            else:
                content = action["answer"]
                event.stage = "final_action"
                self._notify_response(event)
        else:
            native_calls = wire_message.get("tool_calls")
            if native_calls is None:
                native_calls = []
            if not isinstance(native_calls, list):
                raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_CALL")
            names = {item["function"]["name"] for item in tools}
            seen = {
                call["id"]
                for row in messages
                if isinstance(row, AIMessage)
                for call in row.tool_calls
            }
            for call in native_calls:
                if not isinstance(call, dict):
                    raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_CALL")
                function = call.get("function")
                if (
                    not isinstance(function, dict)
                    or call.get("type") != "function"
                    or not isinstance(call.get("id"), str)
                    or not call["id"]
                    or not isinstance(function.get("name"), str)
                ):
                    raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_CALL")
                if call["id"] in seen:
                    raise IncompleteChatResponse("VLLM_CHAT_DUPLICATE_TOOL_CALL_ID")
                if function["name"] not in names:
                    if (not self.unknown_tool_feedback or not names
                            or kwargs.get("tool_choice") == "none" or not function["name"]):
                        raise IncompleteChatResponse("VLLM_CHAT_UNKNOWN_TOOL")
                seen.add(call["id"])
                try:
                    args = json.loads(function["arguments"])
                except (TypeError, ValueError) as exc:
                    raise IncompleteChatResponse("VLLM_CHAT_INVALID_TOOL_ARGUMENTS") from exc
                if not isinstance(args, dict):
                    raise IncompleteChatResponse("VLLM_CHAT_TOOL_ARGUMENTS_NOT_OBJECT")
                calls.append({"name": function["name"], "args": args, "id": call["id"]})
            if bool(calls) != (choice["finish_reason"] == "tool_calls"):
                raise IncompleteChatResponse("VLLM_CHAT_TOOL_FINISH_MISMATCH")
            native_content = wire_message.get("content")
            if native_content is None and calls:
                native_content = ""
            if not isinstance(native_content, str):
                raise IncompleteChatResponse("VLLM_CHAT_INVALID_CONTENT")
            content = native_content
            if calls and content:
                completion_metadata["tool_narrative_status"] = "proposal_not_execution"
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
        response_metadata = {
            "finish_reason": choice["finish_reason"],
            "model": receipt.get("model"),
        }
        event = ResponseEvent(
            "message_metadata",
            prepared,
            receipt,
            message_id,
            completion_metadata=completion_metadata,
            response_metadata=response_metadata,
        )
        self._notify_response(event)
        response_metadata.update(completion_metadata)
        additional_kwargs: dict[str, Any] = {}
        if self.preserve_tool_reasoning and native and calls:
            fields = [wire_message[key] for key in ("reasoning", "reasoning_content")
                      if wire_message.get(key) is not None]
            if any(not isinstance(value, str) for value in fields) or (
                    len(fields) == 2 and fields[0] != fields[1]):
                raise IncompleteChatResponse("VLLM_CHAT_INVALID_REASONING_HISTORY")
            if fields and fields[0]:
                additional_kwargs["reasoning_content"] = fields[0]
        message = AIMessage(
            id=message_id,
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=calls,
            usage_metadata=usage_metadata,
            response_metadata=response_metadata,
        )
        event.stage, event.message = "decoded_message", message
        self._notify_response(event)
        return ChatResult(generations=[ChatGeneration(message=message)])
