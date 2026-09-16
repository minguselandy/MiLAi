from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from milai.adapters.agent_prefetch import (
    PrefetchContext,
    compile_agent_messages,
    prepare_prefetch,
)
from milai.adapters.mcp_unix import McpUnixClient, McpUnixClientError
from milai.adapters.provider_execution import (
    DevRunCapability,
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)
from milai_client import (
    AgentRecallPolicy,
    ContextBudgetInfeasibleError,
    ContextIntegrityError,
    DeterministicRecallRouter,
    RecallRoutingInput,
    TaskMemoryBudget,
    TaskMemoryIdentity,
    TaskPreparedContext,
    TokenBudget,
)

from milai_openworker_mcp import TargetTokenizerCounter, build_task_memory_controller
from milai_openworker_mcp.f1_contract import MODEL_ID, parse_answer, request_payload

_parse_answer = parse_answer
_payload = request_payload

MAX_BODY_BYTES = 2 * 1024 * 1024
TASK_EPOCH_REQUESTS = 50
class OpenWorkerAdapterError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _nonnegative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(max(0.0, left - right), 3)


def _task_seed(question: str) -> int:
    return int(hashlib.sha256(question.encode()).hexdigest()[:16], 16) & ((1 << 63) - 1)


def _tool_name(tools: object) -> str | None:
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        return None
    for item in tools:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        name = function.get("name") if isinstance(function, Mapping) else None
        if isinstance(name, str) and (
            name in {"milai_recall", "milai_memory_resolve"}
            or name.endswith(("_milai_recall", "_milai_memory_resolve"))
        ):
            return name
    return None


def _messages(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise OpenWorkerAdapterError("messages must be an array")
    result: list[dict[str, Any]] = []
    for message in value:
        if not isinstance(message, Mapping) or not isinstance(message.get("role"), str):
            raise OpenWorkerAdapterError("message contract failed")
        result.append(dict(message))
    if not result:
        raise OpenWorkerAdapterError("messages cannot be empty")
    return result


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "\n".join(
            str(part.get("text"))
            for part in value
            if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    return ""


def _question(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            value = _text(message.get("content")).strip()
            if value:
                return value[:2000]
    return "What governed memory is available?"


def _recall_query(question: str) -> str:
    return question[:2000]


def _should_recall(memory_mode: str) -> bool:
    if memory_mode == "none":
        return False
    if memory_mode == "prefetch":
        return True
    if memory_mode == "auto":
        return True
    raise ValueError("unknown memory mode")


def _recall_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        if (
            isinstance(value.get("status"), str)
            and isinstance(value.get("items"), list)
            and isinstance(value.get("open_issue_ids"), list)
        ):
            return dict(value)
        for nested in value.values():
            found = _recall_object(nested)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            found = _recall_object(nested)
            if found is not None:
                return found
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _recall_object(decoded)
    return None


def _recall_from_messages(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") not in {"tool", "user"}:
            continue
        found = _recall_object(message.get("content"))
        if found is not None:
            return found
    return None


def _prepared_prefetch(prepared: TaskPreparedContext) -> PrefetchContext:
    if prepared.status == "READY":
        if prepared.delta is None or prepared.delta.delta.rendered_context is None:
            raise OpenWorkerAdapterError("READY task context omitted rendered memory")
        slot = prepared.delta.slot
        issue_ids = slot.live_issue_ids if slot is not None else ()
        status = "UNCERTAIN" if issue_ids else "AVAILABLE"
        rendered = prepared.delta.delta.rendered_context
        object_ids = slot.object_ids if slot is not None else ()
        return PrefetchContext(
            status=status,
            rendered=rendered,
            context_sha256=hashlib.sha256(rendered.encode()).hexdigest(),
            trace_id=prepared.trace_pointer,
            request_id=None,
            claim_refs=tuple(sorted(set(object_ids) - set(issue_ids))),
            evidence_refs=(),
            open_issue_ids=issue_ids,
            degraded_components=(),
            abstention_reason="OPEN_ISSUE" if issue_ids else None,
        )
    if prepared.status in {"NEEDS_RECOVERY", "DEGRADED", "BUDGET_EXHAUSTED"}:
        return PrefetchContext.unavailable(prepared.reason or prepared.status)
    if prepared.status == "ABSTAIN":
        return prepare_prefetch(
            {
                "status": "ABSTAINED",
                "items": [],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": prepared.reason or "NO_SAFE_MEMORY",
                "trace_id": prepared.trace_pointer,
            }
        )
    raise OpenWorkerAdapterError("UNCHANGED task context requires a retained host slot")


def _completion(
    *,
    request_id: str,
    content: str | None,
    finish_reason: str,
    usage: Mapping[str, int],
    tool_name: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_name is not None:
        arguments = {"query": query or "memory"}
        message["tool_calls"] = [
            {
                "id": "call_" + hashlib.sha256(_canonical(arguments)).hexdigest()[:24],
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": _canonical(arguments).decode(),
                },
            }
        ]
    return {
        "id": request_id,
        "object": "chat.completion",
        "model": MODEL_ID,
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
        "usage": dict(usage),
    }


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
        b"".join(b"data: " + _canonical(event) + b"\n\n" for event in events)
        + b"data: [DONE]\n\n"
    )


class OpenWorkerProviderAdapter:
    def __init__(
        self,
        manifest: Path,
        ledger: Path,
        trace: Path,
        *,
        memory_mode: str = "auto",
        prefetch_socket: Path | None = None,
        tokenizer_json: Path | None = None,
        task_session_id: str | None = None,
    ) -> None:
        if memory_mode not in {"auto", "none", "prefetch"}:
            raise ValueError("unknown memory mode")
        if memory_mode == "prefetch" and prefetch_socket is None:
            raise ValueError("prefetch mode requires a host MCP socket")
        if memory_mode != "prefetch" and prefetch_socket is not None:
            raise ValueError("host MCP socket is only valid in prefetch mode")
        if memory_mode == "prefetch" and tokenizer_json is None:
            raise ValueError("prefetch mode requires the target tokenizer.json")
        if memory_mode != "prefetch" and tokenizer_json is not None:
            raise ValueError("target tokenizer is only valid in prefetch mode")
        if task_session_id is not None and (
            not task_session_id.strip() or len(task_session_id) > 256
        ):
            raise ValueError("task_session_id must contain 1-256 characters")
        self.gateway = ProviderExecutionGateway(manifest, ledger)
        self.transport = JsonCompletionTransport()
        capability = DevRunCapability.load(manifest)
        self.run_id = capability.run_id
        self.trace = trace
        self.memory_mode = memory_mode
        self.task_session_id = task_session_id.strip() if task_session_id is not None else None
        self.host_mcp = (
            McpUnixClient(prefetch_socket) if prefetch_socket is not None else None
        )
        self.target_counter = (
            TargetTokenizerCounter(tokenizer_json) if tokenizer_json is not None else None
        )
        digest_input = {
            "integration": "milai-openworker-mcp-v1",
            "profile": "reader-lite",
            "model_id": capability.model_id,
            "representation": "dg11-grouped-compact-v1",
        }
        integration_digest = hashlib.sha256(_canonical(digest_input)).hexdigest()
        self.task_memory = (
            build_task_memory_controller(
                self.host_mcp,
                compiler_digest=integration_digest,
                router_digest=integration_digest,
                policy_digest=integration_digest,
            )
            if self.host_mcp is not None
            else None
        )
        self.task_policy = AgentRecallPolicy(
            scope={"host_policy": "reader-lite"},
            authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=3,
        )
        self.router = DeterministicRecallRouter()
        self.task_budget = TaskMemoryBudget(
            max_prepare_context_calls=64,
            max_validation_calls=63,
            memory_deadline_ms=5_000,
        )
        self.token_budget = (
            TokenBudget.for_class("STANDARD", counter=self.target_counter)
            if self.target_counter is not None
            else None
        )
        self._task_contexts: dict[str, PrefetchContext] = {}
        self._task_lock = threading.Lock()
        self._task_sequence = 0
        self._task_session_turns: defaultdict[str, int] = defaultdict(int)
        self._active_task_key_by_session: dict[str, str] = {}
        self._lock = threading.Lock()
        self._sequence = 0
        self._pending_recall: defaultdict[str, deque[float]] = defaultdict(deque)
        self._pending_lock = threading.Lock()

    def close(self) -> None:
        if self.host_mcp is not None:
            self.host_mcp.close()

    def _record(self, event: Mapping[str, Any]) -> None:
        self.trace.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _logical_request_id(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"{self.run_id}-ow-{self._sequence:02d}"

    def _task_identity(
        self, incoming: Mapping[str, Any], question: str
    ) -> tuple[TaskMemoryIdentity, str, str]:
        raw_user = incoming.get("user")
        if isinstance(raw_user, str) and raw_user.strip():
            session_id = raw_user.strip()[:256]
        elif self.task_session_id is not None:
            session_id = self.task_session_id
        else:
            with self._task_lock:
                self._task_sequence += 1
                task_sequence = self._task_sequence
            session_id = "openworker-request-" + hashlib.sha256(
                _canonical({"question": question, "sequence": task_sequence})
            ).hexdigest()[:32]
        active_goal = question
        session_binding = hashlib.sha256(
            _canonical({"session_id": session_id, "active_goal": active_goal})
        ).hexdigest()
        with self._task_lock:
            ordinal = self._task_session_turns[session_binding]
            self._task_session_turns[session_binding] += 1
        epoch_index = ordinal // TASK_EPOCH_REQUESTS
        task_epoch = "task-" + hashlib.sha256(
            f"{session_id}:{epoch_index}".encode()
        ).hexdigest()[:32]
        identity = TaskMemoryIdentity(
            tenant_id="mcp-socket-capability",
            session_id=session_id,
            agent_id="openworker",
            profile_id="reader-lite",
            task_epoch=task_epoch,
        )
        task_key = hashlib.sha256(
            _canonical(
                {
                    "session_id": session_id,
                    "task_epoch": task_epoch,
                    "active_goal": active_goal,
                }
            )
        ).hexdigest()
        with self._task_lock:
            previous_key = self._active_task_key_by_session.get(session_binding)
            if previous_key is not None and previous_key != task_key:
                self._task_contexts.pop(previous_key, None)
            self._active_task_key_by_session[session_binding] = task_key
        return identity, active_goal, task_key

    def complete(
        self,
        incoming: Mapping[str, Any],
        *,
        request_parse_ms: float | None = None,
    ) -> tuple[dict[str, Any], str]:
        adapter_started = time.perf_counter()
        messages = _messages(incoming.get("messages"))
        recall_name = _tool_name(incoming.get("tools"))
        recall = _recall_from_messages(messages)
        question = _question(messages)
        question_sha256 = hashlib.sha256(question.encode()).hexdigest()
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        memory_control_ms: float | None = None
        memory_source = "NO_MEMORY"
        mcp_calls = 0
        context: PrefetchContext | None = None
        prepared: TaskPreparedContext | None = None
        router_decision = (
            self.router.decide(
                RecallRoutingInput(
                    current_turn=question,
                    requested_scope=self.task_policy.scope,
                    required_authority=self.task_policy.authority,
                    consistency_floor=self.task_policy.consistency_floor,
                )
            )
            if self.memory_mode == "prefetch" and recall is None
            else None
        )
        if router_decision is not None and router_decision.route == "NONE":
            context = PrefetchContext.no_memory()
            memory_source = "HOST_ROUTER_NONE"
            self._record(
                {
                    "event": "HOST_MEMORY_ROUTE_NONE",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "route": "NONE",
                    "reason": router_decision.reason_code,
                    "mcp_calls": 0,
                    "compiled_memory_tokens": 0,
                }
            )
        elif self.memory_mode == "prefetch" and recall is None:
            if (
                self.task_memory is None
                or self.target_counter is None
                or self.token_budget is None
            ):  # pragma: no cover - constructor invariant
                raise OpenWorkerAdapterError("host task-memory controller is absent")
            identity, active_goal, task_key = self._task_identity(incoming, question)
            with self._task_lock:
                retained = self._task_contexts.get(task_key)
                event = (
                    "TOOL_RESULT"
                    if has_tool_result
                    else ("MODEL_RETRY" if retained is not None else "TASK_START")
                )
            recalled_at = time.perf_counter()
            try:
                prepared = self.task_memory.prepare_context(
                    _recall_query(question),
                    identity=identity,
                    event=event,
                    active_goal=active_goal,
                    recall_policy=self.task_policy,
                    token_counter=self.target_counter,
                    token_budget=self.token_budget,
                    task_budget=self.task_budget,
                )
            except McpUnixClientError as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
                request_id = "chatcmpl-unavailable-" + hashlib.sha256(
                    _canonical(incoming)
                ).hexdigest()[:18]
                answer = {
                    "answer": "UNKNOWN",
                    "status": "UNKNOWN",
                    "memory_used": False,
                }
                self._record(
                    {
                        "event": "HOST_MCP_PREFETCH_FAILED",
                        "provider_call": False,
                        "request_id": request_id,
                        "question_sha256": question_sha256,
                        "memory_mode": self.memory_mode,
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_code": str(exc),
                    }
                )
                return (
                    _completion(
                        request_id=request_id,
                        content=_canonical(answer).decode(),
                        finish_reason="stop",
                        usage={
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    ),
                    "HOST_MCP_PREFETCH_FAILED",
                )
            except (ContextBudgetInfeasibleError, ContextIntegrityError, RuntimeError) as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
                self._record(
                    {
                        "event": "HOST_TASK_CONTEXT_REJECTED",
                        "provider_call": False,
                        "question_sha256": question_sha256,
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_type": type(exc).__name__,
                        "failure_code": str(exc),
                    }
                )
                raise OpenWorkerAdapterError("host task context was rejected") from exc
            if prepared.status == "UNCHANGED":
                if retained is None:
                    context = PrefetchContext.no_memory()
                else:
                    context = retained
            else:
                context = _prepared_prefetch(prepared)
                with self._task_lock:
                    if prepared.status == "READY":
                        self._task_contexts[task_key] = context
                    else:
                        self._task_contexts.pop(task_key, None)
            memory_control_ms = (time.perf_counter() - recalled_at) * 1000
            memory_source = "HOST_MCP_COMPOSITE"
            mcp_calls = 1
            timing = prepared.timing or {}
            uds_roundtrip_ms = timing.get("uds_roundtrip_ms")
            mcp_handler_ms = timing.get("mcp_handler_ms")
            runtime_total_ms = timing.get("runtime_total_ms")
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_CONTEXT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "memory_control_ms": round(memory_control_ms, 3),
                    "memory_status": context.status,
                    "route": prepared.route,
                    "prepare_status": prepared.status,
                    "prepare_reason": prepared.reason,
                    "usage": prepared.usage,
                    "trace_id": prepared.trace_pointer,
                    "timing": {
                        **timing,
                        "broker_transport_ms": _nonnegative_difference(
                            uds_roundtrip_ms, mcp_handler_ms
                        ),
                        "mcp_overhead_ms": _nonnegative_difference(
                            mcp_handler_ms, runtime_total_ms
                        ),
                        "context_compile_ms": timing.get("context_compile_ms", 0.0),
                    },
                    "compiled_memory_tokens": (
                        prepared.delta.metrics.actual_tokens
                        if prepared.delta is not None
                        else None
                    ),
                    "representation_tiers": (
                        [list(value) for value in prepared.delta.metrics.representation_tiers]
                        if prepared.delta is not None
                        else []
                    ),
                }
            )
            if context.status == "UNAVAILABLE":
                request_id = "chatcmpl-unavailable-" + hashlib.sha256(
                    _canonical(incoming)
                ).hexdigest()[:18]
                answer = {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
                return (
                    _completion(
                        request_id=request_id,
                        content=_canonical(answer).decode(),
                        finish_reason="stop",
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    ),
                    "HOST_MCP_PREFETCH_FAILED",
                )
        if (
            recall_name is not None
            and recall is None
            and context is None
            and not has_tool_result
            and _should_recall(self.memory_mode)
        ):
            request_id = "chatcmpl-route-" + hashlib.sha256(_canonical(incoming)).hexdigest()[:24]
            with self._pending_lock:
                self._pending_recall[question_sha256].append(time.perf_counter())
            self._record(
                {
                    "event": "MCP_ROUTE",
                    "provider_call": False,
                    "request_id": request_id,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "adapter_route_ms": round(
                        (time.perf_counter() - adapter_started) * 1000, 3
                    ),
                }
            )
            return (
                _completion(
                    request_id=request_id,
                    content=None,
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    tool_name=recall_name,
                    query=_recall_query(question),
                ),
                "MCP_ROUTE",
            )

        if context is None and recall is None and (recall_name is None or has_tool_result):
            answer = {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
            request_id = "chatcmpl-unavailable-" + hashlib.sha256(
                _canonical(incoming)
            ).hexdigest()[:18]
            self._record(
                {
                    "event": "MCP_UNAVAILABLE_NO_PROVIDER",
                    "provider_call": False,
                    "request_id": request_id,
                    "answer": answer,
                }
            )
            return (
                _completion(
                    request_id=request_id,
                    content=_canonical(answer).decode(),
                    finish_reason="stop",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                ),
                "MCP_UNAVAILABLE_NO_PROVIDER",
            )

        if context is None:
            context = (
                prepare_prefetch(recall)
                if recall is not None
                else PrefetchContext.no_memory()
            )
        if recall is not None and memory_source == "NO_MEMORY":
            memory_source = "OPENWORKER_MCP_TOOL"
            mcp_calls = 1
            with self._pending_lock:
                pending = self._pending_recall.get(question_sha256)
                recalled_at = pending.popleft() if pending else None
                if pending is not None and not pending:
                    self._pending_recall.pop(question_sha256, None)
            if recalled_at is not None:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
        compiled, sidecar = compile_agent_messages(question, context)
        logical_request_id = self._logical_request_id()
        payload = _payload(compiled, logical_request_id)
        payload["seed"] = _task_seed(question)
        provider_started = time.perf_counter()
        result = self.gateway.execute(
            ProviderRequest(
                logical_request_id=logical_request_id,
                transport="json",
                payload=payload,
                prompt_token_budget=768,
                completion_token_budget=96,
                timeout_seconds=180,
            ),
            self.transport,
            _parse_answer,
        )
        provider_prefill_answer_ms = (time.perf_counter() - provider_started) * 1000
        self._record(
            {
                "event": "PROVIDER_ANSWER",
                "provider_call": True,
                "logical_request_id": logical_request_id,
                "native_request_id": result.native_request_id,
                "memory_status": context.status,
                "memory_mode": self.memory_mode,
                "memory_source": memory_source,
                "mcp_calls": mcp_calls,
                "memory_control_ms": (
                    round(memory_control_ms, 3) if memory_control_ms is not None else None
                ),
                "adapter_total_ms": round(
                    (time.perf_counter() - adapter_started) * 1000, 3
                ),
                "request_parse_ms": (
                    round(request_parse_ms, 3) if request_parse_ms is not None else None
                ),
                "provider_prefill_answer_ms": round(provider_prefill_answer_ms, 3),
                "context_sha256": context.context_sha256,
                "context_in_prompt": sidecar["context_in_prompt"],
                "trace_id": context.trace_id,
                "claim_refs": list(context.claim_refs),
                "open_issue_ids": list(context.open_issue_ids),
                "provider_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
                "answer": result.value,
            }
        )
        return (
            _completion(
                request_id=result.native_request_id,
                content=_canonical(result.value).decode(),
                finish_reason=result.finish_reason,
                usage={
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "total_tokens": result.prompt_tokens + result.completion_tokens,
                },
            ),
            f"PROVIDER_{context.status}",
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "MiLAiOpenWorkerF1Adapter/1"

    @property
    def adapter(self) -> OpenWorkerProviderAdapter:
        value = getattr(self.server, "adapter", None)
        if not isinstance(value, OpenWorkerProviderAdapter):
            raise OpenWorkerAdapterError("adapter is unavailable")
        return value

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _write(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path != "/v1/models":
            self._write(404, b'{}', "application/json")
            return
        payload = {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "owned_by": "milai-local"}],
        }
        self._write(200, _canonical(payload), "application/json")

    def do_POST(self) -> None:
        parse_started = time.perf_counter()
        try:
            if self.path != "/v1/chat/completions":
                raise OpenWorkerAdapterError("path is not allowlisted")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise OpenWorkerAdapterError("request body boundary failed")
            incoming = json.loads(self.rfile.read(length))
            if not isinstance(incoming, dict):
                raise OpenWorkerAdapterError("request must be an object")
            request_parse_ms = (time.perf_counter() - parse_started) * 1000
            completion, route = self.adapter.complete(
                incoming, request_parse_ms=request_parse_ms
            )
            stream = incoming.get("stream") is True
            payload = _sse(completion) if stream else _canonical(completion)
            print(
                json.dumps({"event": "OPENWORKER_F1_ROUTE", "route": route}, sort_keys=True),
                flush=True,
            )
            self._write(
                200,
                payload,
                "text/event-stream" if stream else "application/json",
            )
        except (OpenWorkerAdapterError, ValueError, json.JSONDecodeError) as exc:
            payload = {
                "error": {
                    "message": "OpenWorker F1 adapter request failed",
                    "type": "local_adapter_error",
                    "reason_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
                }
            }
            self._write(400, _canonical(payload), "application/json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve OpenWorker F1 through the provider gateway")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument(
        "--memory-mode",
        choices=("auto", "none", "prefetch"),
        default="auto",
    )
    parser.add_argument("--prefetch-socket", type=Path)
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--task-session-id")
    args = parser.parse_args()
    if not 1 <= args.listen_port <= 65535:
        raise SystemExit("listen port is invalid")
    adapter = OpenWorkerProviderAdapter(
        args.manifest,
        args.ledger,
        args.trace,
        memory_mode=args.memory_mode,
        prefetch_socket=args.prefetch_socket,
        tokenizer_json=args.tokenizer_json,
        task_session_id=args.task_session_id,
    )
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        adapter.close()
        server.server_close()


if __name__ == "__main__":
    main()
