"""Loopback vLLM transport for strict structured semantic-hint shadow calls."""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urlparse

from milai.application.semantic_hint import (
    SemanticHintCompletion,
    SemanticHintError,
)


class LoopbackVllmSemanticProvider:
    """One tokenizer request plus one generation; automatic retry is zero."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:7860",
        model: str,
        timeout_seconds: float = 30.0,
        transport_mode: Literal["non-streaming", "streaming"] = "streaming",
    ) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port is None
            or parsed.path not in {"", "/v1"}
        ):
            raise ValueError("semantic hint provider must be an explicit loopback vLLM")
        if (
            not model
            or not 1.0 <= timeout_seconds <= 120.0
            or transport_mode not in {"non-streaming", "streaming"}
        ):
            raise ValueError("semantic hint provider configuration is invalid")
        self._host = parsed.hostname
        self._port = parsed.port
        self._model = model
        self._timeout = timeout_seconds
        self._transport_mode = transport_mode

    @property
    def transport_mode(self) -> Literal["non-streaming", "streaming"]:
        return self._transport_mode

    def complete_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        schema_name: str,
        schema: Mapping[str, Any],
        max_completion_tokens: int,
        seed: int,
    ) -> SemanticHintCompletion:
        prompt_tokens, tokenizer_latency_ms = self._tokenize(messages)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "temperature": 0,
            "top_p": 1,
            "seed": seed,
            "max_tokens": max_completion_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": dict(schema),
                },
            },
        }
        if self._transport_mode == "streaming":
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            return self._complete_streaming(
                payload=payload,
                prompt_tokens=prompt_tokens,
                tokenizer_latency_ms=tokenizer_latency_ms,
            )
        payload["stream"] = False
        return self._complete_non_streaming(
            payload=payload,
            prompt_tokens=prompt_tokens,
            tokenizer_latency_ms=tokenizer_latency_ms,
        )

    def _complete_non_streaming(
        self,
        *,
        payload: Mapping[str, Any],
        prompt_tokens: int,
        tokenizer_latency_ms: float,
    ) -> SemanticHintCompletion:
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
        started = time.perf_counter()
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read()
            ended = time.perf_counter()
            if response.status != 200:
                error_type, error_code = _response_error_identity(body)
                raise SemanticHintError(
                    f"SEMANTIC_HINT_PROVIDER_HTTP_{response.status}",
                    transport_mode="non-streaming",
                    http_status=response.status,
                    stream_finish_state="not_applicable",
                    sse_error_type=error_type,
                    sse_error_code=error_code,
                    latency_ms=(ended - started) * 1_000,
                )
            queue_ms = _nonnegative_header_ms(response.getheaders())
            decoded = json.loads(body)
            if not isinstance(decoded, Mapping):
                raise SemanticHintError(
                    "SEMANTIC_HINT_PROVIDER_RESPONSE_INVALID",
                    transport_mode="non-streaming",
                    http_status=response.status,
                    stream_finish_state="not_applicable",
                    latency_ms=(ended - started) * 1_000,
                )
            error = decoded.get("error")
            if isinstance(error, Mapping):
                error_type, error_code = _provider_error_identity(error)
                raise SemanticHintError(
                    "SEMANTIC_HINT_PROVIDER_RESPONSE_ERROR",
                    transport_mode="non-streaming",
                    http_status=response.status,
                    stream_finish_state="not_applicable",
                    sse_error_type=error_type,
                    sse_error_code=error_code,
                    latency_ms=(ended - started) * 1_000,
                )
            choices = decoded.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(
                choices[0], Mapping
            ):
                raise SemanticHintError(
                    "SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT",
                    transport_mode="non-streaming",
                    http_status=response.status,
                    stream_finish_state="not_applicable",
                    latency_ms=(ended - started) * 1_000,
                )
            message = choices[0].get("message")
            content = message.get("content") if isinstance(message, Mapping) else None
            finish_reason = choices[0].get("finish_reason")
            usage = decoded.get("usage")
            if not isinstance(usage, Mapping):
                usage = {}
        except SemanticHintError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_TRANSPORT_FAILED",
                transport_mode="non-streaming",
            ) from exc
        finally:
            connection.close()
        if not isinstance(content, str) or not content:
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT",
                transport_mode="non-streaming",
                http_status=200,
                stream_finish_state="not_applicable",
                finish_reason=(finish_reason if isinstance(finish_reason, str) else None),
                completion_tokens=_nonnegative_int(usage.get("completion_tokens")),
                latency_ms=(ended - started) * 1_000,
            )
        total_ms = (ended - started) * 1_000
        queue_ms = min(queue_ms, total_ms)
        ttft_ms = max(0.0, total_ms - queue_ms)
        observed_prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
        completion_tokens = _nonnegative_int(usage.get("completion_tokens"))
        _validate_prompt_accounting(observed_prompt_tokens, prompt_tokens)
        return SemanticHintCompletion(
            content=content,
            provider="local-vllm-openai-compatible",
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tokenizer_latency_ms=tokenizer_latency_ms,
            queue_ms=queue_ms,
            ttft_ms=ttft_ms,
            decode_ms=0.0,
            total_ms=total_ms,
            provider_calls=1,
            automatic_retry_count=0,
            finish_reason=(finish_reason if isinstance(finish_reason, str) else "unknown"),
            transport_mode="non-streaming",
            http_status=200,
            stream_finish_state="not_applicable",
            sse_error_observed=False,
        )

    def _complete_streaming(
        self,
        *,
        payload: Mapping[str, Any],
        prompt_tokens: int,
        tokenizer_latency_ms: float,
    ) -> SemanticHintCompletion:
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
        started = time.perf_counter()
        first_content_at: float | None = None
        content_parts: list[str] = []
        usage: Mapping[str, Any] = {}
        finish_reason = ""
        saw_done = False
        sse_error_type: str | None = None
        sse_error_code: int | str | None = None
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                body = response.read(1_000)
                error_type, error_code = _response_error_identity(body)
                raise SemanticHintError(
                    f"SEMANTIC_HINT_PROVIDER_HTTP_{response.status}",
                    transport_mode="streaming",
                    http_status=response.status,
                    stream_finish_state="http_error",
                    sse_error_type=error_type,
                    sse_error_code=error_code,
                    latency_ms=(time.perf_counter() - started) * 1_000,
                )
            queue_ms = _nonnegative_header_ms(response.getheaders())
            while True:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode(errors="strict").strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                event = json.loads(data)
                if not isinstance(event, Mapping):
                    continue
                error = event.get("error")
                if isinstance(error, Mapping):
                    sse_error_type, sse_error_code = _provider_error_identity(error)
                    continue
                event_usage = event.get("usage")
                if isinstance(event_usage, Mapping):
                    usage = event_usage
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(
                    choices[0], Mapping
                ):
                    continue
                observed_finish_reason = choices[0].get("finish_reason")
                if isinstance(observed_finish_reason, str):
                    finish_reason = observed_finish_reason
                delta = choices[0].get("delta")
                if not isinstance(delta, Mapping):
                    continue
                part = delta.get("content")
                if isinstance(part, str) and part:
                    if first_content_at is None:
                        first_content_at = time.perf_counter()
                    content_parts.append(part)
        except SemanticHintError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_TRANSPORT_FAILED",
                transport_mode="streaming",
            ) from exc
        finally:
            connection.close()
        ended = time.perf_counter()
        stream_finish_state = "done" if saw_done else "eof_without_done"
        completion_tokens = _nonnegative_int(usage.get("completion_tokens"))
        if sse_error_type is not None or sse_error_code is not None:
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_SSE_ERROR",
                transport_mode="streaming",
                http_status=200,
                stream_finish_state=stream_finish_state,
                sse_error_type=sse_error_type,
                sse_error_code=sse_error_code,
                finish_reason=finish_reason or None,
                completion_tokens=completion_tokens,
                latency_ms=(ended - started) * 1_000,
            )
        if first_content_at is None or not content_parts:
            raise SemanticHintError(
                "SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT",
                transport_mode="streaming",
                http_status=200,
                stream_finish_state=stream_finish_state,
                finish_reason=finish_reason or None,
                completion_tokens=completion_tokens,
                latency_ms=(ended - started) * 1_000,
            )
        total_ms = (ended - started) * 1_000
        observed_first_ms = (first_content_at - started) * 1_000
        queue_ms = min(queue_ms, observed_first_ms)
        ttft_ms = max(0.0, observed_first_ms - queue_ms)
        decode_ms = max(0.0, total_ms - queue_ms - ttft_ms)
        observed_prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
        _validate_prompt_accounting(observed_prompt_tokens, prompt_tokens)
        return SemanticHintCompletion(
            content="".join(content_parts),
            provider="local-vllm-openai-compatible",
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tokenizer_latency_ms=tokenizer_latency_ms,
            queue_ms=queue_ms,
            ttft_ms=ttft_ms,
            decode_ms=decode_ms,
            total_ms=total_ms,
            provider_calls=1,
            automatic_retry_count=0,
            finish_reason=finish_reason or "unknown",
            transport_mode="streaming",
            http_status=200,
            stream_finish_state=stream_finish_state,
            sse_error_observed=False,
        )

    def _tokenize(
        self, messages: Sequence[Mapping[str, str]]
    ) -> tuple[int, float]:
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
        payload = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "add_generation_prompt": True,
            "add_special_tokens": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        started = time.perf_counter()
        try:
            connection.request(
                "POST",
                "/tokenize",
                body=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                raise SemanticHintError(
                    f"SEMANTIC_HINT_TOKENIZER_HTTP_{response.status}"
                )
            decoded = json.loads(body)
        except (OSError, json.JSONDecodeError) as exc:
            raise SemanticHintError("SEMANTIC_HINT_TOKENIZER_FAILED") from exc
        finally:
            connection.close()
        count = decoded.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise SemanticHintError("SEMANTIC_HINT_TOKENIZER_RESPONSE_INVALID")
        return count, (time.perf_counter() - started) * 1_000


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _validate_prompt_accounting(observed: int, tokenized: int) -> None:
    if observed not in {0, tokenized}:
        raise SemanticHintError("SEMANTIC_HINT_PROMPT_ACCOUNTING_MISMATCH")


def _provider_error_identity(
    error: Mapping[str, Any],
) -> tuple[str | None, int | str | None]:
    raw_type = error.get("type")
    error_type = raw_type if isinstance(raw_type, str) and raw_type else None
    raw_code = error.get("code")
    error_code = (
        raw_code
        if isinstance(raw_code, (int, str)) and not isinstance(raw_code, bool)
        else None
    )
    return error_type, error_code


def _response_error_identity(body: bytes) -> tuple[str | None, int | str | None]:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(decoded, Mapping):
        return None, None
    error = decoded.get("error")
    if not isinstance(error, Mapping):
        return None, None
    return _provider_error_identity(error)


def _nonnegative_header_ms(headers: Sequence[tuple[str, str]]) -> float:
    normalized = {key.casefold(): value for key, value in headers}
    for key in ("x-vllm-queue-time-ms", "x-queue-time-ms"):
        raw = normalized.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value >= 0:
            return value
    return 0.0


__all__ = ["LoopbackVllmSemanticProvider"]
