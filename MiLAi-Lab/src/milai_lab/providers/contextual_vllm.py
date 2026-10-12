"""Shared synchronous vLLM transport for contextual Host and offline Judge."""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from milai_lab.harness.contextual_artifacts import BudgetExceeded, RunBudget, current_http_budget
from milai_lab.harness.http_ownership import HttpOwnership, HttpOwnershipError, settings_profile
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


def ownership_client_configs(settings: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Actual existing DTO defaults, checked before an entry loads its ledger."""
    if settings_profile(settings) == "legacy":
        return None
    return [
        asdict(VLLMConfig(**settings[name])) for name in ("host", "embedding") if name in settings
    ]


class VLLMClient:
    """Synchronous vLLM chat/completions and embeddings client with trace events."""

    def __init__(
        self,
        config: VLLMConfig,
        emit: Emit | None = None,
        transport: httpx.BaseTransport | None = None,
        budget: RunBudget | None = None,
        capacity: HostCapacity | None = None,
        http_owner: HttpOwnership | None = None,
    ) -> None:
        if (
            capacity is not None
            and config.enable_thinking is not None
            and config.enable_thinking != capacity.enable_thinking
        ):
            raise ValueError("HOST_CAPACITY_THINKING_MODE_MISMATCH")
        active_budget = current_http_budget()
        if active_budget is not None and budget is not active_budget:
            raise HttpOwnershipError("HTTP_OWNER_EXACT_BUDGET_REQUIRED")
        self.config = config
        self.emit = emit
        self.budget = budget
        self.capacity = capacity
        self.generation_holdback_tokens = 0
        self.generation_holdback_requests = 0
        adopted = budget.http_owner if budget is not None else None
        if http_owner is not None and adopted is not http_owner:
            raise HttpOwnershipError("HTTP_OWNER_EXPLICIT_BUDGET_CONFLICT")
        self._http_owner = adopted
        if adopted is not None:
            adopted.register_client(self, budget, asdict(config))
        try:
            self._client = httpx.Client(
                base_url=config.base_url.rstrip("/"),
                timeout=config.timeout,
                transport=transport,
            )
            if adopted is not None:
                adopted.assert_client(self, budget, asdict(config), str(self._client.base_url))
        except BaseException as initialization_error:
            if adopted is not None:
                if hasattr(self, "_client"):
                    try:
                        self.close()
                    except BaseException as cleanup_error:
                        # Keep the original refusal and the actual cleanup failure.
                        # closing_client retains registration/lease on any failure;
                        # HTTPX's CLOSED flag alone cannot prove transport cleanup.
                        raise initialization_error from cleanup_error
                else:
                    adopted.abort_client(self)
            raise

    def __enter__(self) -> VLLMClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._http_owner is None:
            self._client.close()
        else:
            with self._http_owner.closing_client(self):
                self._client.close()
                if not self._client.is_closed:
                    raise HttpOwnershipError("HTTP_OWNER_CLIENT_CLOSE_INCOMPLETE")

    def _check_owner(self) -> None:
        if self._http_owner is not None:
            if self._client.timeout != httpx.Timeout(self.config.timeout):
                raise HttpOwnershipError("HTTP_OWNER_CLIENT_TIMEOUT_CHANGED")
            self._http_owner.assert_client(
                self, self.budget, asdict(self.config), str(self._client.base_url)
            )

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
        top_p: float | None = None,
        presence_penalty: float | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        self._check_owner()
        if enable_thinking is not None and type(enable_thinking) is not bool:
            raise ValueError("enable_thinking must be a boolean or None")
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        thinking = (
            enable_thinking if enable_thinking is not None else
            self.capacity.enable_thinking
            if self.capacity is not None
            else self.config.enable_thinking
        )
        if thinking is not None:
            request["chat_template_kwargs"] = {"enable_thinking": thinking}
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = tool_choice or "auto"
        if top_p is not None:
            request["top_p"] = top_p
        if presence_penalty is not None:
            request["presence_penalty"] = presence_penalty
        selected_format = (
            response_format if response_format is not None else self.config.response_format
        )
        if selected_format is not None:
            request["response_format"] = generation_schema(selected_format)
        capacity_receipt = None
        if self.capacity is not None:
            try:
                capacity_receipt = self.capacity.check(
                    request["messages"],
                    self.config.max_tokens,
                    request.get("tools"),
                    **({"enable_thinking": enable_thinking}
                       if enable_thinking is not None else {}),
                )
            except CapacityExceeded as error:
                if self.emit:
                    self.emit(
                        {
                            "event": "vllm_capacity_rejected",
                            "path": "chat/completions",
                            "capacity": error.receipt,
                        }
                    )
                raise
        return self._post("chat/completions", request, capacity_receipt=capacity_receipt)

    def embed(
        self, texts: Sequence[str] | Sequence[Sequence[int]], model: str
    ) -> list[list[float]]:
        """Embed a batch in one API request and return vectors in response order."""
        self._check_owner()
        if not texts:
            return []
        response = self._post("embeddings", {"model": model, "input": list(texts)})
        data = response["data"]
        return [list(item["embedding"]) for item in sorted(data, key=lambda item: item["index"])]

    def native_post(
        self, path: str, request: dict[str, Any], *,
        generation_output_bound: int | None = None, on_event: Emit | None = None,
    ) -> dict[str, Any]:
        """Meter an original native JSON request without projecting its parameters.

        Only the accounting copy normalizes max_completion_tokens or an explicit
        deployment output bound to RunBudget's max_tokens field. The actual wire
        keeps every original field. Streaming requires a different receipt contract
        and is rejected. Unknown native usage keeps the original reservation.
        """
        if on_event:
            on_event({"event": "vllm_native_validation", "path": path,
                      "request": request, "request_sent": False})
        self._check_owner()
        if path not in {"chat/completions", "embeddings"} or self.budget is None:
            raise ValueError("NATIVE_POST_REQUIRES_ORIGINAL_BUDGET_AND_ROUTE")
        if request.get("model") != self.config.model:
            raise HttpOwnershipError("HTTP_OWNER_REQUEST_DOMAIN_CHANGED")
        accounting = dict(request)
        capacity_receipt = None
        if path == "chat/completions":
            if request.get("stream", False) is not False:
                raise ValueError("NATIVE_STREAMING_NOT_SUPPORTED")
            if not isinstance(request.get("messages"), list):
                raise ValueError("NATIVE_MESSAGES_REQUIRED")
            explicit = [request[field] for field in ("max_tokens", "max_completion_tokens")
                        if request.get(field) is not None]
            if len(explicit) == 2 and explicit[0] != explicit[1]:
                raise ValueError("NATIVE_OUTPUT_LIMIT_AMBIGUOUS")
            output = explicit[0] if explicit else generation_output_bound
            if type(output) is not int or output <= 0:
                raise ValueError("NATIVE_FINITE_OUTPUT_BOUND_REQUIRED")
            choices = request.get("n", 1)
            if type(choices) is not int or choices <= 0:
                raise ValueError("NATIVE_GENERATION_COUNT_INVALID")
            accounting["max_tokens"] = output * choices
            # A bound for an omitted limit is a ledger upper bound, not a
            # generation setting or a capacity reservation sent to the server.
            if self.capacity is not None and explicit:
                template = request.get("chat_template_kwargs") or {}
                capacity_receipt = self.capacity.check(
                    request["messages"], output, request.get("tools"),
                    enable_thinking=template.get("enable_thinking"),
                )
        else:
            inputs = request.get("input")
            if isinstance(inputs, str):
                accounting["input"] = [inputs]
            elif isinstance(inputs, list) and inputs and all(type(row) is int for row in inputs):
                accounting["input"] = [inputs]
            elif (not isinstance(inputs, list) or not inputs
                  or not all(isinstance(row, str) or (
                      isinstance(row, list) and all(type(token) is int for token in row)
                  ) for row in inputs)):
                raise ValueError("NATIVE_EMBEDDING_INPUT_INVALID")
            if self.emit:
                self.emit({"event": "embedding_request", "model": request["model"],
                           "input": inputs})
        return self._post(path, request, capacity_receipt=capacity_receipt,
                          accounting_request=accounting, on_event=on_event)

    def _post(
        self,
        path: str,
        request: dict[str, Any],
        *,
        capacity_receipt: dict[str, Any] | None = None,
        accounting_request: dict[str, Any] | None = None,
        on_event: Emit | None = None,
    ) -> dict[str, Any]:
        if self._http_owner is None:
            return self._post_request(path, request, capacity_receipt=capacity_receipt,
                                      accounting_request=accounting_request, on_event=on_event)
        self._check_owner()
        actual_url = str(self._client.build_request("POST", path).url)
        with self._http_owner.request(
            self,
            self.budget,
            asdict(self.config),
            str(self._client.base_url),
            path,
            actual_url,
            request.get("model"),
        ):
            return self._post_request(path, request, capacity_receipt=capacity_receipt,
                                      accounting_request=accounting_request, on_event=on_event)

    def _post_request(
        self,
        path: str,
        request: dict[str, Any],
        *,
        capacity_receipt: dict[str, Any] | None = None,
        accounting_request: dict[str, Any] | None = None,
        on_event: Emit | None = None,
    ) -> dict[str, Any]:
        def emit(event: dict[str, Any]) -> None:
            if self.emit:
                self.emit(event)
            if on_event:
                on_event(event)

        try:
            reservation = (
                self.budget.reserve(
                    path,
                    request if accounting_request is None else accounting_request,
                    generation_holdback_tokens=(
                        self.generation_holdback_tokens if path == "chat/completions" else 0
                    ),
                    generation_holdback_requests=(
                        self.generation_holdback_requests if path == "chat/completions" else 0
                    ),
                    generation_input_tokens=(
                        capacity_receipt["prompt_tokens"] + capacity_receipt.get("safety_tokens", 0)
                        if path == "chat/completions" and capacity_receipt is not None
                        else None
                    ),
                )
                if self.budget
                else None
            )
        except BudgetExceeded as error:
            emit({"event": "vllm_budget_rejected", "path": path,
                  "request_sent": False, "reason": str(error)})
            raise
        started = time.monotonic()
        event: dict[str, Any] = {"event": "vllm_request", "path": path, "request": request}
        if capacity_receipt is not None:
            event["capacity"] = capacity_receipt
        try:
            if accounting_request is None:
                response = self._client.post(path, json=request)
            else:
                wire = self._client.build_request("POST", path, json=request)
                event.update({"request_url": str(wire.url), "request_method": wire.method,
                              "request_headers": list(wire.headers.multi_items()),
                              "request_body": wire.content.decode("utf-8"),
                              "accounting_request": accounting_request,
                              "accounting_scope": "reservation_upper_bound_not_actual_usage",
                              "request_sent": True})
                if on_event:
                    on_event(event)
                response = self._client.send(wire)
                event["response_headers"] = list(response.headers.multi_items())
                event["response_body_base64"] = base64.b64encode(response.content).decode("ascii")
            event["wall_seconds"] = time.monotonic() - started
            event["http_status"] = response.status_code
            event["response_text"] = response.text
            if accounting_request is None:
                response.raise_for_status()
            try:
                receipt: dict[str, Any] = response.json()
            except ValueError:
                # Preserve the actual HTTP error for a non-JSON error body.
                response.raise_for_status()
                raise
            event["receipt"] = receipt
            if accounting_request is not None:
                event["usage"] = (
                    receipt.get("usage", "unknown") if isinstance(receipt, dict) else "unknown"
                )
                usage = event["usage"]
                fields = ("prompt_tokens", "completion_tokens", "total_tokens") if (
                    path == "chat/completions"
                ) else ("prompt_tokens", "total_tokens")
                event["usage_confirmed"] = (
                    isinstance(usage, dict)
                    and all(type(usage.get(field)) is int and usage[field] >= 0 for field in fields)
                    and usage["total_tokens"] == sum(usage[field] for field in fields[:-1])
                )
                response.raise_for_status()
                if not isinstance(receipt, dict):
                    raise ValueError("NATIVE_RESPONSE_OBJECT_REQUIRED")
            else:
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
                        if type(actual_prompt) is int
                        else None
                    ),
                    "output_reserve_minus_actual_tokens": (
                        capacity_receipt["output_reserve_tokens"] - actual_completion
                        if type(actual_completion) is int
                        else None
                    ),
                }
            event["event"] = "vllm_response"
            emit(event)
            return receipt
        except (httpx.HTTPError, ValueError) as exc:
            event.setdefault("wall_seconds", time.monotonic() - started)
            event["exception"] = {"type": type(exc).__name__, "message": str(exc)}
            event["event"] = "vllm_error"
            emit(event)
            raise
        finally:
            if self.budget is not None and reservation is not None:
                usage = event.get("usage") if (
                    accounting_request is None or event.get("usage_confirmed") is True
                ) else None
                self.budget.finish(reservation, usage)
