from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


class CompletionCaptureError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BufferedOpenAIStream:
    chunks: tuple[bytes, ...]
    native_request_id: str
    finish_reason: str
    content: str
    usage: dict[str, int]


def buffer_openai_stream(source: Iterator[bytes]) -> BufferedOpenAIStream:
    chunks = tuple(source)
    native_request_id: str | None = None
    finish_reason: str | None = None
    content: list[str] = []
    usage: dict[str, int] | None = None
    done = False
    try:
        lines = b"".join(chunks).decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID") from exc
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            done = True
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID") from exc
        if not isinstance(event, Mapping):
            raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
        event_id = event.get("id")
        if isinstance(event_id, str):
            if native_request_id is not None and event_id != native_request_id:
                raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_ID_DRIFT")
            native_request_id = event_id
        raw_usage = event.get("usage")
        if isinstance(raw_usage, Mapping):
            parsed_usage: dict[str, int] = {}
            for name in _USAGE_FIELDS:
                value = raw_usage.get(name)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
                parsed_usage[name] = value
            usage = parsed_usage
        choices = event.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
        if not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, Mapping) or not isinstance(choice.get("delta"), Mapping):
            raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
        delta = choice["delta"]
        piece = delta.get("content")
        if piece is not None:
            if not isinstance(piece, str):
                raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
            content.append(piece)
        terminal = choice.get("finish_reason")
        if terminal is not None:
            if not isinstance(terminal, str):
                raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INVALID")
            finish_reason = terminal
    if not done or native_request_id is None or finish_reason is None or usage is None:
        raise CompletionCaptureError("PROVIDER_STREAM_CAPTURE_INCOMPLETE")
    return BufferedOpenAIStream(
        chunks=chunks,
        native_request_id=native_request_id,
        finish_reason=finish_reason,
        content="".join(content),
        usage=usage,
    )


def final_assistant_content(response: Mapping[str, Any]) -> tuple[str, str]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise CompletionCaptureError("PROVIDER_COMPLETION_CAPTURE_INVALID")
    choice = choices[0]
    message = choice.get("message")
    finish_reason = choice.get("finish_reason")
    if (
        not isinstance(message, Mapping)
        or message.get("role") != "assistant"
        or not isinstance(message.get("content"), str)
        or not isinstance(finish_reason, str)
    ):
        raise CompletionCaptureError("PROVIDER_COMPLETION_CAPTURE_INVALID")
    return message["content"], finish_reason


def replace_assistant_content(
    response: Mapping[str, Any],
    content: str,
) -> dict[str, Any]:
    _, _ = final_assistant_content(response)
    result = dict(response)
    choices = list(result["choices"])
    choice = dict(choices[0])
    message = dict(choice["message"])
    message["content"] = content
    choice["message"] = message
    choices[0] = choice
    result["choices"] = choices
    return result
