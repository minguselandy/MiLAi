"""Typed, generic hooks around one synchronous chat request and response."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]]
    graph_messages: list[Any]
    tools: list[dict[str, Any]]
    native: bool
    options: dict[str, Any]


@dataclass
class PreparedRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    schema: dict[str, Any] | None = None
    attachment: object | None = None


@dataclass
class ResponseEvent:
    stage: Literal[
        "schema_outcome", "validated_action", "final_action", "message_metadata", "decoded_message"
    ]
    request: PreparedRequest
    receipt: dict[str, Any]
    message_id: str
    action: Any = None
    schema_error: Exception | None = None
    accept_schema_failure: bool = False
    completion_metadata: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    message: Any = None


@runtime_checkable
class RequestTransform(Protocol):
    def validate(self, request: ChatRequest) -> None: ...

    def project(self, request: ChatRequest) -> PreparedRequest: ...


@runtime_checkable
class DeliveryObserver(Protocol):
    def request_scope(
        self, request: PreparedRequest, request_index: int
    ) -> AbstractContextManager[Any]: ...

    def record_delivery(
        self, request: PreparedRequest, receipt: dict[str, Any], request_index: int
    ) -> None: ...

    def after_delivery(self, request: PreparedRequest, request_index: int) -> None: ...


@runtime_checkable
class ResponseHook(Protocol):
    def on_response(self, event: ResponseEvent) -> None: ...
