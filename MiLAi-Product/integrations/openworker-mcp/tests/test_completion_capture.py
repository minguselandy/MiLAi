from __future__ import annotations

import json

import pytest

from milai_openworker_mcp.completion_capture import (
    CompletionCaptureError,
    buffer_openai_stream,
    final_assistant_content,
    replace_assistant_content,
)


def _event(value: object) -> bytes:
    return b"data: " + json.dumps(value).encode() + b"\n\n"


def test_stream_capture_keeps_original_bytes_and_collects_final_answer() -> None:
    chunks = (
        _event(
            {
                "id": "chatcmpl-synthetic-1",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "three"},
                        "finish_reason": None,
                    }
                ],
            }
        ),
        _event(
            {
                "id": "chatcmpl-synthetic-1",
                "choices": [{"delta": {"content": " trees"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            }
        ),
        b"data: [DONE]\n\n",
    )

    captured = buffer_openai_stream(iter(chunks))

    assert captured.chunks == chunks
    assert captured.content == "three trees"
    assert captured.finish_reason == "stop"
    assert captured.usage["total_tokens"] == 12


def test_stream_capture_rejects_missing_done_or_request_identity() -> None:
    with pytest.raises(CompletionCaptureError, match="INCOMPLETE"):
        buffer_openai_stream(
            iter(
                [
                    _event(
                        {
                            "choices": [
                                {"delta": {"content": "private"}, "finish_reason": "stop"}
                            ],
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "total_tokens": 2,
                            },
                        }
                    )
                ]
            )
        )


def test_nonstream_capture_and_replacement_preserve_provider_envelope() -> None:
    response = {
        "id": "chatcmpl-synthetic-2",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": '{"answer_text":"cedar"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }

    content, reason = final_assistant_content(response)
    replaced = replace_assistant_content(response, "cedar")

    assert content == '{"answer_text":"cedar"}'
    assert reason == "stop"
    assert replaced["choices"][0]["message"]["content"] == "cedar"
    assert replaced["id"] == response["id"]
    assert response["choices"][0]["message"]["content"] != "cedar"
