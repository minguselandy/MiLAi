"""Ordinary tool compatibility and OpenAI SSE wire adaptation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from milai_openworker_mcp.host.request_contract import (
    MODEL_ID,
    OpenWorkerAdapterError,
    _tool_choice_name,
    _tool_definition_name,
)
from milai_openworker_mcp.provider_execution import ProviderTransportError, _SseObserver

_ORDINARY_READ_PATH = "/openworker/runtime/opencode.json"
_VLLM_JSON_SCHEMA_NAMED_TOOL = "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER"


class OrdinaryToolCompatibilityError(OpenWorkerAdapterError):
    """A deterministic structured-output-to-tool-call conversion failure."""


def _apply_single_ordinary_tool_required_once(
    payload: dict[str, Any], tool_name: str
) -> dict[str, Any]:
    """Adapt one explicit ordinary tool turn to vLLM's named/none capability.

    This is deliberately not general ``auto`` tool choice emulation.  It is a
    fail-closed compatibility contract for one synchronous ``read`` call:
    named function calling on the first provider round and ``none`` only after
    the matching OpenCode tool result is present on the second round.
    """

    if tool_name != "read":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes)):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    ordinary_names = [_tool_definition_name(tool) for tool in raw_tools]
    if ordinary_names != [tool_name]:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    if payload.get("tool_choice") != "auto":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_CHOICE_INVALID")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    messages = list(raw_messages)
    last_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], Mapping) and messages[index].get("role") == "user"
        ),
        None,
    )
    if last_user is None:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    suffix = messages[last_user + 1 :]
    tool_name_sha256 = hashlib.sha256(tool_name.encode()).hexdigest()
    if not suffix:
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_name},
        }
        return {
            "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
            "round": "CALL",
            "requested_tool_choice": "AUTO",
            "effective_tool_choice": "NAMED",
            "ordinary_tool_count": 1,
            "ordinary_tool_name_sha256": tool_name_sha256,
            "assistant_tool_call_count": 0,
            "tool_result_count": 0,
            "matching_tool_result_count": 0,
            "tool_call_id_sha256": None,
        }

    if (
        len(suffix) != 2
        or not isinstance(suffix[0], Mapping)
        or suffix[0].get("role") != "assistant"
        or not isinstance(suffix[1], Mapping)
        or suffix[1].get("role") != "tool"
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    raw_calls = suffix[0].get("tool_calls")
    if (
        not isinstance(raw_calls, Sequence)
        or isinstance(raw_calls, (str, bytes))
        or len(raw_calls) != 1
        or not isinstance(raw_calls[0], Mapping)
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    call = raw_calls[0]
    function = call.get("function")
    call_id = call.get("id")
    arguments = function.get("arguments") if isinstance(function, Mapping) else None
    if (
        call.get("type") != "function"
        or not isinstance(call_id, str)
        or not call_id.strip()
        or not isinstance(function, Mapping)
        or function.get("name") != tool_name
        or not isinstance(arguments, str)
        or suffix[1].get("tool_call_id") != call_id
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    try:
        decoded_arguments = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID") from exc
    if not isinstance(decoded_arguments, Mapping):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    payload["tool_choice"] = "none"
    return {
        "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
        "round": "FINAL",
        "requested_tool_choice": "AUTO",
        "effective_tool_choice": "NONE",
        "ordinary_tool_count": 1,
        "ordinary_tool_name_sha256": tool_name_sha256,
        "assistant_tool_call_count": 1,
        "tool_result_count": 1,
        "matching_tool_result_count": 1,
        "tool_call_id_sha256": hashlib.sha256(call_id.encode()).hexdigest(),
    }


def _apply_vllm_json_schema_named_tool_compatibility(
    payload: dict[str, Any], policy: Mapping[str, Any]
) -> bool:
    """Use vLLM structured output when its server has no tool parser.

    Only the forced first ``read`` round is adapted.  The upstream response is
    later validated in memory and rendered back to the OpenAI tool-call shape;
    the final round keeps the paired tool result and ``tool_choice=none``.
    """

    if policy.get("round") != "CALL":
        return False
    if payload.get("response_format") is not None:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_CONFLICT")
    if [_tool_definition_name(tool) for tool in payload.get("tools", [])] != [
        "read"
    ] or _tool_choice_name(payload.get("tool_choice")) != "read":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    payload.pop("tools")
    payload.pop("tool_choice")
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "dg13u_read_arguments",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"filePath": {"type": "string", "enum": [_ORDINARY_READ_PATH]}},
                "required": ["filePath"],
                "additionalProperties": False,
            },
        },
    }
    return True


def _ordinary_read_completion(
    native_request_id: str, *, prompt_tokens: int, completion_tokens: int
) -> dict[str, Any]:
    arguments = {"filePath": _ORDINARY_READ_PATH}
    call_id = (
        "call_"
        + hashlib.sha256(native_request_id.encode() + b":" + _canonical(arguments)).hexdigest()[:24]
    )
    return {
        "id": native_request_id,
        "object": "chat.completion",
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "read",
                                "arguments": _canonical(arguments).decode(),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _vllm_json_schema_named_tool_chunks(source: Iterator[bytes]) -> Iterator[bytes]:
    """Validate a native structured-output stream, then deliver one read call."""

    observer = _SseObserver()
    content: list[str] = []
    try:
        for raw_chunk in source:
            observer.observe(raw_chunk)
            for line in raw_chunk.decode("utf-8", errors="strict").splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                if not isinstance(event, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                choices = event.get("choices")
                if not isinstance(choices, list) or len(choices) > 1:
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if not choices:
                    if not isinstance(event.get("usage"), Mapping):
                        raise OrdinaryToolCompatibilityError(
                            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                        )
                    continue
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                delta = choice.get("delta")
                if not isinstance(delta, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if "tool_calls" in delta or "function_call" in delta:
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if not set(delta).issubset({"content", "role", "reasoning", "reasoning_content"}):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                role = delta.get("role")
                if role is not None and role != "assistant":
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                for reasoning_field in ("reasoning", "reasoning_content"):
                    reasoning = delta.get(reasoning_field)
                    if reasoning not in {None, ""}:
                        raise OrdinaryToolCompatibilityError(
                            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                        )
                part = delta.get("content")
                if part is not None and not isinstance(part, str):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if isinstance(part, str):
                    content.append(part)
    except OrdinaryToolCompatibilityError:
        raise
    except (UnicodeError, json.JSONDecodeError, ProviderTransportError) as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
    try:
        response = observer.response()
    except ProviderTransportError as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    try:
        arguments = json.loads("".join(content))
    except json.JSONDecodeError as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    if response.finish_reason != "stop" or arguments != {"filePath": _ORDINARY_READ_PATH}:
        raise OrdinaryToolCompatibilityError("PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID")
    completion = _ordinary_read_completion(
        response.native_request_id,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
    )
    yield _sse(completion)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sse(completion: Mapping[str, Any]) -> bytes:
    choice = completion["choices"][0]
    message = choice["message"]
    delta: dict[str, Any] = {"role": "assistant"}
    if message.get("tool_calls"):
        call = message["tool_calls"][0]
        delta["tool_calls"] = [
            {
                "index": 0,
                "id": call["id"],
                "type": "function",
                "function": call["function"],
            }
        ]
    else:
        delta["content"] = message.get("content", "")
    events = [
        {
            "id": completion["id"],
            "object": "chat.completion.chunk",
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        },
        {
            "id": completion["id"],
            "object": "chat.completion.chunk",
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": choice["finish_reason"],
                }
            ],
            "usage": completion["usage"],
        },
    ]
    return (
        b"".join(b"data: " + _canonical(event) + b"\n\n" for event in events) + b"data: [DONE]\n\n"
    )
