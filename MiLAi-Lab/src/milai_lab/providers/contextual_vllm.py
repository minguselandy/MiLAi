"""Shared synchronous vLLM transport for contextual Host and offline Judge."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity

Emit = Callable[[dict[str, Any]], None]


def generation_schema(value: Any) -> Any:
    """Project the finite tool schema onto deployed vLLM's grammar support.

    vLLM 0.27.1 rejects uniqueItems in both available grammar backends. Uniqueness
    remains enforced by the original tool/proposal schema before execution; required
    fields, constants and other generation constraints are preserved.
    """
    if isinstance(value, dict):
        return {key: generation_schema(item) for key, item in value.items() if key != "uniqueItems"}
    if isinstance(value, list):
        return [generation_schema(item) for item in value]
    return value


@dataclass(frozen=True)
class VLLMConfig:
    """Connection and generation settings for an OpenAI-compatible vLLM server."""

    base_url: str
    model: str
    temperature: float = 0
    max_tokens: int = 2048
    timeout: float = 120
    tool_mode: str = "json_action"
    max_calls: int = 12
    response_format: dict[str, Any] | None = None
    enable_thinking: bool | None = None

    def __post_init__(self) -> None:
        if self.tool_mode not in {"json_action", "native"}:
            raise ValueError("tool_mode must be 'json_action' or 'native'")
        if type(self.max_calls) is not int or self.max_calls < 0:
            raise ValueError("max_calls must be non-negative")
        if self.enable_thinking is not None and type(self.enable_thinking) is not bool:
            raise ValueError("enable_thinking must be a boolean or None")


class VLLMClient:
    """Synchronous vLLM chat/completions and embeddings client with trace events."""

    def __init__(
        self,
        config: VLLMConfig,
        emit: Emit | None = None,
        transport: httpx.BaseTransport | None = None,
        budget: RunBudget | None = None,
        capacity: HostCapacity | None = None,
    ) -> None:
        if (capacity is not None and config.enable_thinking is not None
                and config.enable_thinking != capacity.enable_thinking):
            raise ValueError("HOST_CAPACITY_THINKING_MODE_MISMATCH")
        self.config = config
        self.emit = emit
        self.budget = budget
        self.capacity = capacity
        self.generation_holdback_tokens = 0
        self.generation_holdback_requests = 0
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout,
            transport=transport,
        )

    def __enter__(self) -> VLLMClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        thinking = (self.capacity.enable_thinking
                    if self.capacity is not None else self.config.enable_thinking)
        if thinking is not None:
            request["chat_template_kwargs"] = {"enable_thinking": thinking}
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = tool_choice or "auto"
        selected_format = (
            response_format if response_format is not None else self.config.response_format
        )
        if selected_format is not None:
            request["response_format"] = generation_schema(selected_format)
        capacity_receipt = None
        if self.capacity is not None:
            try:
                capacity_receipt = self.capacity.check(
                    request["messages"], self.config.max_tokens,
                    request.get("tools"),
                )
            except CapacityExceeded as error:
                if self.emit:
                    self.emit({
                        "event": "vllm_capacity_rejected", "path": "chat/completions",
                        "capacity": error.receipt,
                    })
                raise
        return self._post("chat/completions", request, capacity_receipt=capacity_receipt)

    def embed(
        self, texts: Sequence[str] | Sequence[Sequence[int]], model: str
    ) -> list[list[float]]:
        """Embed a batch in one API request and return vectors in response order."""
        if not texts:
            return []
        response = self._post("embeddings", {"model": model, "input": list(texts)})
        data = response["data"]
        return [list(item["embedding"]) for item in sorted(data, key=lambda item: item["index"])]

    def _post(
        self, path: str, request: dict[str, Any], *,
        capacity_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            reservation = (
                self.budget.reserve(
                    path, request,
                    generation_holdback_tokens=(
                        self.generation_holdback_tokens if path == "chat/completions" else 0
                    ),
                    generation_holdback_requests=(
                        self.generation_holdback_requests if path == "chat/completions" else 0
                    ),
                    generation_input_tokens=(
                        capacity_receipt["prompt_tokens"] + capacity_receipt.get("safety_tokens", 0)
                        if path == "chat/completions" and capacity_receipt is not None else None
                    ),
                ) if self.budget else None
            )
        except BudgetExceeded as error:
            if self.emit:
                self.emit({"event": "vllm_budget_rejected", "path": path,
                           "request_sent": False, "reason": str(error)})
            raise
        started = time.monotonic()
        event: dict[str, Any] = {"event": "vllm_request", "path": path, "request": request}
        if capacity_receipt is not None:
            event["capacity"] = capacity_receipt
        try:
            response = self._client.post(path, json=request)
            event["wall_seconds"] = time.monotonic() - started
            event["http_status"] = response.status_code
            event["response_text"] = response.text
            response.raise_for_status()
            receipt: dict[str, Any] = response.json()
            event["receipt"] = receipt
            event["usage"] = receipt.get("usage", "unknown")
            if capacity_receipt is not None:
                usage = event["usage"]
                actual_prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else None
                actual_completion = (
                    usage.get("completion_tokens") if isinstance(usage, dict) else None
                )
                event["capacity_comparison"] = {
                    "actual_prompt_tokens": actual_prompt if type(actual_prompt) is int else None,
                    "actual_completion_tokens": (
                        actual_completion if type(actual_completion) is int else None
                    ),
                    "prompt_estimate_error_tokens": (
                        actual_prompt - capacity_receipt["prompt_tokens"]
                        if type(actual_prompt) is int else None
                    ),
                    "output_reserve_minus_actual_tokens": (
                        capacity_receipt["output_reserve_tokens"] - actual_completion
                        if type(actual_completion) is int else None
                    ),
                }
            event["event"] = "vllm_response"
            if self.emit:
                self.emit(event)
            return receipt
        except (httpx.HTTPError, ValueError) as exc:
            event.setdefault("wall_seconds", time.monotonic() - started)
            event["exception"] = {"type": type(exc).__name__, "message": str(exc)}
            event["event"] = "vllm_error"
            if self.emit:
                self.emit(event)
            raise
        finally:
            if self.budget is not None and reservation is not None:
                self.budget.finish(reservation, event.get("usage"))
