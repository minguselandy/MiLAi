"""Model-hidden observation context for the LangMem B1 arm."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from milai_lab.baselines.langmem_revision_store import RevisionSidecar, canonical_json

T = TypeVar("T")


class InstrumentationIncomplete(RuntimeError):
    """The main result remains authoritative, but its provenance is incomplete."""


@dataclass
class CallContext:
    call_key: str
    thread_id: str
    generation_id: str
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    attempt_no: int
    ordinal: int = 0
    search_ids: list[str] = field(default_factory=list)

    def next_ordinal(self) -> int:
        self.ordinal += 1
        return self.ordinal


class ProvenanceObserver:
    """Explicit per-call context; sidecar errors never masquerade as tool errors."""

    def __init__(self, sidecar: RevisionSidecar, run_id: str, arm_id: str) -> None:
        self.sidecar = sidecar
        self.run_id = run_id
        self.arm_id = arm_id
        self._call: ContextVar[CallContext | None] = ContextVar("b1_tool_call", default=None)
        self._request: ContextVar[str | None] = ContextVar("b1_request", default=None)
        self._actual_request: ContextVar[dict[str, Any] | None] = ContextVar(
            "b1_actual_request", default=None)
        self._projection: ContextVar[dict[str, dict[str, str]] | None] = ContextVar(
            "b1_request_projection", default=None)
        self._scope_lock = threading.RLock()
        self._public: dict[str, tuple[int, str, str]] = {}
        self._failed: list[str] = sidecar.unresolved()

    def current_call(self) -> CallContext | None:
        return self._call.get()

    def run_fixture_memory_tool(
        self, call_key: str, thread_id: str, stage: str,
        arguments: dict[str, Any], invoke: Callable[[], str],
    ) -> str:
        """Bind an explicitly external fixture call; never create a Host observation."""
        generation_id = "fixture:" + stage
        call_id = generation_id + ":manage_memory"
        attempt = self.sidecar.begin_call(
            call_key, thread_id, generation_id, call_id,
            "fixture:manage_memory", arguments,
        )
        token = self._call.set(CallContext(
            call_key, thread_id, generation_id, call_id,
            "fixture:manage_memory", arguments, attempt,
        ))
        try:
            result = invoke()
        except Exception as error:
            self.sidecar.finish_call(call_key, None, "unknown", None,
                                     error=type(error).__name__)
            raise
        finally:
            self._call.reset(token)
        self.sidecar.finish_call(call_key, result, "success", None)
        return result

    def incomplete(self, reason: str) -> None:
        with self._scope_lock:
            self._failed.append(reason)
        self.sidecar.mark_incomplete(reason)

    def safe(self, function: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
        try:
            return function(*args, **kwargs)
        except Exception as error:
            self.incomplete(f"{function.__name__}:{type(error).__name__}")
            return None

    def assert_healthy(self) -> None:
        if self._failed:
            raise InstrumentationIncomplete(
                "INSTRUMENTATION_INCOMPLETE:" + ",".join(self._failed)
            )

    def begin_public_message(self, scope: Any, public_index: int, content: str) -> None:
        self.assert_healthy()
        thread_id = scope.config()["configurable"]["thread_id"]
        if scope.run_id != self.run_id or scope.arm_id != self.arm_id:
            raise ValueError("B1_OBSERVER_SCOPE_MISMATCH")
        identity = [thread_id, public_index, "user"]
        observation_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
        self.safe(
            self.sidecar.observe, observation_id, scope.run_id, scope.arm_id,
            thread_id, scope.episode_id, public_index, "user", scope.user_id,
            "public_message", content,
        )
        with self._scope_lock:
            self._public[thread_id] = (public_index, scope.episode_id, scope.user_id)
        self.assert_healthy()

    def run_tool(
        self, request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], Any],
        business_journal: Any = None,
    ) -> Any:
        call = request.tool_call
        messages = request.state["messages"]
        generated = messages[-1]
        if not isinstance(generated, AIMessage) or not generated.id:
            return execute(request)
        thread_id = request.runtime.config["configurable"]["thread_id"]
        call_id = call["id"]
        if not isinstance(call_id, str):
            return execute(request)
        # Match BusinessActionJournal's exact key serialization for direct linkage.
        key = hashlib.sha256(
            json.dumps([thread_id, generated.id, call_id], ensure_ascii=False).encode()
        ).hexdigest()
        args = call.get("args") or {}
        name = call["name"]
        is_business = (business_journal is not None
                       and name in business_journal.business_names)
        prior = (business_journal.entry_for_call(thread_id, generated.id, call_id)
                 if is_business else None)
        attempt = self.safe(
            self.sidecar.begin_call, key, thread_id, generated.id, call_id,
            name, args, replayed=prior is not None,
        )
        context = CallContext(key, thread_id, generated.id, call_id, name, args, attempt or 0)
        token = self._call.set(context)
        try:
            result = execute(request)
        except Exception as error:
            self.safe(self.sidecar.finish_call, key, None, "unknown", None,
                      error=type(error).__name__)
            raise
        finally:
            self._call.reset(token)
        current = (business_journal.entry_for_call(thread_id, generated.id, call_id)
                   if is_business else None)
        journal_status = current["status"] if current is not None else None
        if isinstance(result, ToolMessage):
            self.safe(self.sidecar.finish_call, key, result.content, result.status,
                      journal_status)
            for search_id in context.search_ids:
                self.safe(self.sidecar.finish_search_message, search_id,
                          result.content, result.status)
            if is_business and journal_status == "complete":
                with self._scope_lock:
                    scope = self._public.get(thread_id)
                if scope is None:
                    self.incomplete("BUSINESS_OBSERVATION_SCOPE_MISSING")
                else:
                    public_index, session_id, _ = scope
                    observation_id = hashlib.sha256(
                        canonical_json([key, "business_result"]).encode()
                    ).hexdigest()
                    self.safe(
                        self.sidecar.observe, observation_id, self.run_id,
                        self.arm_id, thread_id, session_id, public_index,
                        "business_tool", name, "tool_message", result.content,
                        count_redelivery=prior is not None,
                    )
        else:
            self.safe(self.sidecar.finish_call, key, None, "unknown", journal_status,
                      error="NON_TOOL_MESSAGE_RESULT")
        return result

    @contextmanager
    def request_scope(
        self, message_key: str | None, request_index: int,
        projected_material: dict[str, dict[str, str]] | None = None,
    ) -> Iterator[None]:
        self.assert_healthy()
        if message_key is None:
            raise ValueError("B1_PUBLIC_MESSAGE_KEY_MISSING")
        thread_id, index_text = message_key.rsplit(":", 1)
        public_index = int(index_text)
        request_id = hashlib.sha256(
            canonical_json([thread_id, public_index, request_index]).encode()
        ).hexdigest()
        self.safe(self.sidecar.plan_request, request_id, thread_id,
                  public_index, request_index)
        self.assert_healthy()
        token = self._request.set(request_id)
        actual_token = self._actual_request.set(None)
        projection_token = self._projection.set(projected_material)
        try:
            yield
        finally:
            self._projection.reset(projection_token)
            self._actual_request.reset(actual_token)
            self._request.reset(token)

    def current_provider_request(self) -> dict[str, Any] | None:
        """The completed wire request is available only inside its synchronous scope."""
        return self._actual_request.get()

    def capture_provider_event(
        self, event: dict[str, Any], trace_ref: dict[str, Any] | None = None,
    ) -> None:
        request_id = self._request.get()
        if request_id is None or event.get("path") != "chat/completions":
            return
        name = event.get("event")
        if name == "vllm_response":
            status = "completed"
        elif name == "vllm_error":
            status = "error" if event.get("http_status") is not None else "unknown"
        elif name in {"vllm_capacity_rejected", "vllm_budget_rejected"}:
            status = "not_sent"
        else:
            return
        self.safe(self.sidecar.finish_request, request_id, status, event, trace_ref,
                  self._projection.get())
        if status == "completed" and isinstance(event.get("request"), dict):
            self._actual_request.set(event["request"])
