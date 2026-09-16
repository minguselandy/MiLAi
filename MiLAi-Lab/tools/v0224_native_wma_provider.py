"""Bounded native WMA calls; official judging prompts remain owned by WMA."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:7860"
MODEL = "Qwen3.6-35B-A3B-FP8"


def _integer(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _strict(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def number(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("nonfinite JSON number")
        return parsed

    def constant(value: str) -> Any:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def _judge_object(text: str, finish_reason: str) -> dict[str, Any]:
    if finish_reason != "stop":
        raise ValueError("judge completion did not stop normally")
    stripped = text.strip()
    if stripped.startswith("```json\n") and stripped.endswith("\n```"):
        stripped = stripped[8:-4]
    result = _strict(stripped)
    if not isinstance(result, dict):
        raise ValueError("judge must return one complete JSON object")
    return result


def parse_judge(text: str, finish_reason: str) -> dict[str, Any]:
    result = _judge_object(text, finish_reason)
    if (
        set(result) != {"evaluation_result", "reasoning"}
        or result["evaluation_result"] not in ("Correct", "Hallucination", "Omission")
        or not isinstance(result["reasoning"], str)
    ):
        raise ValueError("invalid QA judge schema")
    return result


def parse_evidence(text: str, finish_reason: str, expected_total: int) -> dict[str, Any]:
    result = _judge_object(text, finish_reason)
    if (
        not _integer(expected_total)
        or set(result) != {"covered_count", "total", "reasoning"}
        or not _integer(result["covered_count"])
        or not _integer(result["total"])
        or result["total"] != expected_total
        or result["covered_count"] > result["total"]
        or not isinstance(result["reasoning"], str)
    ):
        raise ValueError("invalid evidence judge schema")
    return result


class NativeProvider:
    """One process-local serial budget, with durable raw attempts and no retries."""

    def __init__(
        self,
        directory: str | Path,
        *,
        max_generations: int,
        max_http: int,
        request_seconds: float = 120,
        context: int = 65536,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not _integer(max_generations, minimum=1) or not _integer(max_http, minimum=1):
            raise ValueError("positive integer budgets required")
        if not _integer(context, minimum=1) or context > 65536:
            raise ValueError("invalid context")
        if (
            type(request_seconds) not in (int, float)
            or not math.isfinite(request_seconds)
            or request_seconds <= 0
        ):
            raise ValueError("invalid request timeout")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.owner = (os.getpid(), threading.get_ident())
        self.lock = threading.Lock()
        self.max_generations, self.max_http = max_generations, max_http
        self.context = context
        self.http_attempts = self.generations = 0
        self.blocked = False
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._save(
            "manifest.json",
            {
                "base_url": BASE_URL,
                "model": MODEL,
                "max_generations": max_generations,
                "max_http": max_http,
                "request_seconds": request_seconds,
                "context": context,
                "temperature": 0,
                "top_p": 1,
                "seed": 2240401,
                "enable_thinking": False,
            },
        )
        self.client = httpx.Client(
            base_url=BASE_URL,
            timeout=request_seconds,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    def _save(self, name: str, value: Any) -> None:
        with (self.directory / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.http_attempts >= self.max_http:
            raise RuntimeError("HTTP budget exhausted")
        self.http_attempts += 1
        prefix = f"http-{self.http_attempts:04d}"
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        (self.directory / (prefix + ".request.json")).write_bytes(raw)
        http_started = time.monotonic()
        http_elapsed: float | None = None
        try:
            response = self.client.post(
                endpoint, content=raw, headers={"Content-Type": "application/json"}
            )
            http_elapsed = time.monotonic() - http_started
            (self.directory / (prefix + ".response.raw")).write_bytes(response.content)
            self._save(
                prefix + ".response-meta.json",
                {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "endpoint": endpoint,
                    "elapsed_seconds": http_elapsed,
                },
            )
            response.raise_for_status()
            result = _strict(response.text)
            if not isinstance(result, dict):
                raise ValueError("response is not object")
            return result
        except BaseException as exc:
            self._save(
                prefix + ".error.json",
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "elapsed_seconds": (
                        time.monotonic() - http_started if http_elapsed is None else http_elapsed
                    ),
                },
            )
            raise

    def generate(
        self,
        kind: str,
        messages: list,
        max_tokens: int = 1024,
        *,
        response_format=None,
        structured_outputs=None,
    ) -> dict[str, Any]:
        if (os.getpid(), threading.get_ident()) != self.owner:
            raise RuntimeError("provider owner mismatch")
        with self.lock:
            if self.blocked:
                raise RuntimeError("provider blocked after unresolved attempt")
            if self.generations >= self.max_generations or self.http_attempts + 2 > self.max_http:
                raise RuntimeError("provider budget exhausted")
            if (
                not isinstance(kind, str)
                or not kind
                or not isinstance(messages, list)
                or not messages
            ):
                raise ValueError("kind and messages required")
            if not _integer(max_tokens, minimum=1):
                raise ValueError("invalid max_tokens")
            # Freeze the exact multimodal messages used by both requests.
            frozen = _strict(json.dumps(messages, ensure_ascii=False, allow_nan=False))
            if response_format is not None and structured_outputs is not None:
                raise ValueError("response_format and structured_outputs are mutually exclusive")
            frozen_structured = None
            if structured_outputs is not None:
                if not isinstance(structured_outputs, dict):
                    raise ValueError("structured_outputs must be an object")
                frozen_structured = _strict(
                    json.dumps(structured_outputs, ensure_ascii=False, allow_nan=False)
                )
            frozen_format = None
            if response_format is not None:
                if not isinstance(response_format, dict):
                    raise ValueError("response_format must be an object")
                frozen_format = _strict(
                    json.dumps(response_format, ensure_ascii=False, allow_nan=False)
                )
            observed_usage: Any = None
            usage_valid = False
            generation_started = time.monotonic()
            try:
                tokenized = self._post(
                    "/tokenize",
                    {
                        "model": MODEL,
                        "messages": frozen,
                        "add_generation_prompt": True,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                count = tokenized.get("count")
                if not _integer(count) or count + max_tokens > self.context:
                    raise ValueError("invalid tokenization or context overflow")
                self.generations += 1
                response = self._post(
                    "/v1/chat/completions",
                    {
                        "model": MODEL,
                        "messages": frozen,
                        "max_tokens": max_tokens,
                        "temperature": 0,
                        "top_p": 1,
                        "seed": 2240401,
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                        **({"response_format": frozen_format} if frozen_format is not None else {}),
                        **(
                            {"structured_outputs": frozen_structured}
                            if frozen_structured is not None
                            else {}
                        ),
                    },
                )
                observed_usage = response.get("usage")
                if (
                    not isinstance(observed_usage, dict)
                    or not all(_integer(observed_usage.get(k)) for k in self.usage)
                    or observed_usage["prompt_tokens"] != count
                    or (
                        observed_usage["total_tokens"]
                        != observed_usage["prompt_tokens"] + observed_usage["completion_tokens"]
                    )
                    or observed_usage["completion_tokens"] > max_tokens
                ):
                    raise ValueError("unknown or inconsistent generation usage")
                usage_valid = True
                usage = {k: observed_usage[k] for k in self.usage}
                for key, value in usage.items():
                    self.usage[key] += value
                choices = response.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError("expected one completion")
                choice = choices[0]
                text = choice["message"]["content"]
                finish = choice["finish_reason"]
                request_id = response.get("id")
                if (
                    not isinstance(text, str)
                    or not isinstance(finish, str)
                    or not isinstance(request_id, str)
                    or not request_id
                ):
                    raise ValueError("invalid completion fields")
                result = {
                    "text": text,
                    "usage": usage,
                    "finish_reason": finish,
                    "request_id": request_id,
                    "elapsed_seconds": time.monotonic() - generation_started,
                }
                self._save(f"generation-{self.generations:04d}.json", {"kind": kind, **result})
                return result
            except BaseException as exc:
                self.blocked = True
                self._save(
                    "blocked.json",
                    {
                        "error": type(exc).__name__,
                        "message": str(exc),
                        "http_attempts": self.http_attempts,
                        "generation_attempts": self.generations,
                        "observed_usage": observed_usage,
                        "known_usage": self.usage,
                        "unresolved_usage": not usage_valid,
                        "elapsed_seconds": time.monotonic() - generation_started,
                    },
                )
                raise

    def close(self) -> None:
        self.client.close()
