from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider
from milai.application.semantic_hint import SemanticHintError


class _Response:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        lines: Sequence[bytes] = (),
    ) -> None:
        self.status = status
        self._body = body
        self._lines = iter(lines)

    def read(self, _limit: int | None = None) -> bytes:
        return self._body

    def readline(self) -> bytes:
        return next(self._lines, b"")

    def getheaders(self) -> list[tuple[str, str]]:
        return []


class _Connection:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.payload: dict[str, Any] | None = None

    def request(
        self,
        _method: str,
        _path: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
    ) -> None:
        del headers
        self.payload = json.loads(body)

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        return None


def _install_generation_connection(
    monkeypatch: pytest.MonkeyPatch, response: _Response
) -> _Connection:
    connection = _Connection(response)
    monkeypatch.setattr(
        LoopbackVllmSemanticProvider,
        "_tokenize",
        lambda _self, _messages: (11, 0.25),
    )
    monkeypatch.setattr(
        "milai.adapters.semantic_hint.http.client.HTTPConnection",
        lambda _host, _port, timeout: connection,
    )
    return connection


def _complete(provider: LoopbackVllmSemanticProvider):  # type: ignore[no-untyped-def]
    return provider.complete_structured(
        messages=[{"role": "user", "content": "synthetic"}],
        schema_name="residual_cue_proposal_v01",
        schema={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["NO_ACTION"]}},
            "required": ["action"],
            "additionalProperties": False,
        },
        max_completion_tokens=32,
        seed=7,
    )


def test_streaming_top_level_sse_error_is_typed_before_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_message = "private provider implementation detail"
    response = _Response(
        lines=[
            (
                "data: "
                + json.dumps(
                    {
                        "error": {
                            "message": private_message,
                            "type": "InternalServerError",
                            "code": 500,
                        }
                    }
                )
                + "\n"
            ).encode(),
            b"data: [DONE]\n",
        ]
    )
    _install_generation_connection(monkeypatch, response)
    provider = LoopbackVllmSemanticProvider(
        model="local-model", transport_mode="streaming"
    )

    with pytest.raises(SemanticHintError) as raised:
        _complete(provider)

    error = raised.value
    assert error.code == "SEMANTIC_HINT_PROVIDER_SSE_ERROR"
    assert error.transport_mode == "streaming"
    assert error.http_status == 200
    assert error.stream_finish_state == "done"
    assert error.sse_error_type == "InternalServerError"
    assert error.sse_error_code == 500
    assert "EMPTY_OUTPUT" not in str(error)
    assert private_message not in str(error)


@pytest.mark.parametrize("transport_mode", ["non-streaming", "streaming"])
def test_non_streaming_and_streaming_are_independent_conformance_cells(
    monkeypatch: pytest.MonkeyPatch, transport_mode: str
) -> None:
    content = json.dumps({"action": "NO_ACTION"})
    if transport_mode == "non-streaming":
        response = _Response(
            body=json.dumps(
                {
                    "choices": [
                        {"message": {"content": content}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 5},
                }
            ).encode()
        )
    else:
        response = _Response(
            lines=[
                (
                    "data: "
                    + json.dumps(
                        {
                            "choices": [
                                {"delta": {"content": content}, "finish_reason": "stop"}
                            ]
                        }
                    )
                    + "\n"
                ).encode(),
                (
                    "data: "
                    + json.dumps(
                        {
                            "choices": [],
                            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
                        }
                    )
                    + "\n"
                ).encode(),
                b"data: [DONE]\n",
            ]
        )
    connection = _install_generation_connection(monkeypatch, response)
    provider = LoopbackVllmSemanticProvider(
        model="local-model", transport_mode=transport_mode  # type: ignore[arg-type]
    )

    completion = _complete(provider)

    assert completion.content == content
    assert completion.transport_mode == transport_mode
    assert completion.http_status == 200
    assert connection.payload is not None
    assert connection.payload["stream"] is (transport_mode == "streaming")
    assert ("stream_options" in connection.payload) is (
        transport_mode == "streaming"
    )


def test_non_streaming_http_error_is_typed_and_body_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_message = "private xgrammar traceback"
    response = _Response(
        status=500,
        body=json.dumps(
            {
                "error": {
                    "message": private_message,
                    "type": "InternalServerError",
                    "code": 500,
                }
            }
        ).encode(),
    )
    _install_generation_connection(monkeypatch, response)
    provider = LoopbackVllmSemanticProvider(
        model="local-model", transport_mode="non-streaming"
    )

    with pytest.raises(SemanticHintError) as raised:
        _complete(provider)

    assert raised.value.code == "SEMANTIC_HINT_PROVIDER_HTTP_500"
    assert raised.value.transport_mode == "non-streaming"
    assert raised.value.http_status == 500
    assert raised.value.sse_error_type == "InternalServerError"
    assert private_message not in str(raised.value)
