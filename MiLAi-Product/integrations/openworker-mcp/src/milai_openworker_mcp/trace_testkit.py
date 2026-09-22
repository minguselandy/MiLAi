"""Explicit, read-only Host/Provider observation for isolated non-stream test runs.

The default adapter never imports this module. Observation delegates the original
request, response and exception unchanged; it cannot authorize calls or infer use.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

from milai_openworker_mcp.host.provider_bridge import OpenWorkerProviderAdapter
from milai_openworker_mcp.host.request_contract import OpenAIChatRequest, StreamingCompletion
from milai_openworker_mcp.provider_execution import (
    DevRunCapability,
    NativeProviderResponse,
    ProviderRequest,
    ProviderTransport,
    ProviderTransportError,
)
from milai_openworker_mcp.task_binding import NativeTaskMetadata
from milai_openworker_mcp.transport import McpUnixClient

__all__ = [
    "DevRunCapability", "NativeProviderResponse", "NativeTaskMetadata",
    "ObservedOpenWorkerProviderAdapter", "OpenAIChatRequest", "ProviderRequest",
    "ProviderTransportError",
]

_EVENTS = frozenset({
    "HOST_NATIVE_REQUEST_OBSERVED", "HOST_MCP_PREPARE_ATTEMPT", "HOST_MCP_PREPARE_CONTEXT",
    "HOST_MCP_PREPARE_FAILED", "HOST_MCP_MEMORY_INSUFFICIENT", "HOST_MEMORY_ROUTE_NONE",
    "PROVIDER_ANSWER", "MCP_ROUTE",
})


def _digest(value: object) -> str:
    wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode()).hexdigest()


def _ref(kind: str, value: object) -> str | None:
    return f"{kind}:{_digest(value)}" if isinstance(value, str) and value else None


class _ObservedMcp:
    def __init__(
        self, delegate: McpUnixClient, attempt: dict[str, Any],
        contexts: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.delegate, self.attempt, self.contexts = delegate, attempt, contexts

    def resolve_memory(
        self, query: str, *, previous_context_id: str | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "invocation_id": "mcp-invocation:" + uuid4().hex,
            "host_attempt_trace_id": self.attempt["host_attempt_trace_id"],
            "retrieval_trace_ref": None, "status": "FAILURE", "receipt_reused": False,
        }
        self.attempt["mcp_invocations"].append(row)
        response = self.delegate.resolve_memory(query, previous_context_id=previous_context_id)
        row.update(
            status="SUCCESS", retrieval_trace_ref=_ref("retrieval", response.get("trace_id")),
            receipt_reused=response.get("receipt_reused") is True,
        )
        context = response.get("memory_context")
        if isinstance(context, Mapping) and isinstance(context.get("text"), str):
            text = context["text"]
            ids = context.get("selected_evidence_ids")
            binding = {
                "mcp_invocation_id": row["invocation_id"],
                "retrieval_trace_ref": row["retrieval_trace_ref"],
                "reader_context_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "selected_evidence_refs": (
                    [_ref("evidence", value) for value in ids] if isinstance(ids, list) else None
                ),
            }
            # Raw text is ephemeral and never placed in a published attempt.
            self.contexts.append((text, binding))
        return response


class _ObservedTransport:
    def __init__(
        self, delegate: ProviderTransport, attempt: dict[str, Any],
        contexts: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.name = delegate.name
        self.delegate = delegate
        self.attempt = attempt
        self.contexts = contexts

    def invoke(
        self, request: ProviderRequest, capability: DevRunCapability,
    ) -> NativeProviderResponse:
        bindings = []
        messages = request.payload.get("messages", [])
        for text, binding in self.contexts:
            framed = "MILAI_CONTEXT_BEGIN\n" + text + "\nMILAI_CONTEXT_END"
            if any(
                isinstance(message, Mapping) and message.get("role") == "system"
                and isinstance(message.get("content"), str) and framed in message["content"]
                for message in messages
            ):
                bindings.append(copy.deepcopy(binding))
        row: dict[str, Any] = {
            "request_ref": _ref("request", request.logical_request_id),
            "host_attempt_trace_id": self.attempt["host_attempt_trace_id"],
            "payload_sha256": _digest(request.payload),
            "native_request_ref": None,
            "status": "UNKNOWN",
            "request_started": None,
            "input_tokens": None,
            "output_tokens": None,
            "prepared_context_bindings": bindings,
            "context_bindings": [],
            "exposure_status": "UNKNOWN",
        }
        self.attempt["provider_requests"].append(row)
        try:
            response = self.delegate.invoke(request, capability)
        except ProviderTransportError as exc:
            row.update(
                status="FAILURE", request_started=exc.request_started,
                native_request_ref=_ref("native", exc.native_request_id),
                context_bindings=copy.deepcopy(bindings) if exc.request_started else [],
                exposure_status="DISPATCHED" if exc.request_started else "NOT_STARTED",
            )
            raise
        # Unknown exceptions intentionally preserve UNKNOWN and unknown usage.
        row.update(
            status="SUCCESS", request_started=True,
            native_request_ref=_ref("native", response.native_request_id),
            input_tokens=response.prompt_tokens, output_tokens=response.completion_tokens,
            context_bindings=copy.deepcopy(bindings), exposure_status="DISPATCHED",
        )
        return response


class ObservedOpenWorkerProviderAdapter(OpenWorkerProviderAdapter):
    """Opt-in public testkit; serial non-stream calls, original gateway budgets.

    Snapshots contain only allowlisted owner metadata and digests, not raw Host
    traces, prompts, answers or error messages. They are partial producer facts,
    not the complete Runtime/MCP/version join and not observable-use evidence.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._observation_lock = threading.Lock()
        self._owner_attempt: dict[str, Any] | None = None
        self._owner_attempts: list[dict[str, Any]] = []
        super().__init__(*args, **kwargs)

    def owner_traces(self) -> list[dict[str, Any]]:
        """Return detached terminal snapshots; never expose mutable live state."""
        if not self._observation_lock.acquire(blocking=False):
            raise RuntimeError("HOST_OWNER_TRACE_ATTEMPT_ACTIVE")
        try:
            return copy.deepcopy(self._owner_attempts)
        finally:
            self._observation_lock.release()

    def _record(self, event: Mapping[str, Any]) -> None:
        super()._record(event)
        attempt = self._owner_attempt
        if attempt is None:
            return
        # Do not copy free-form reasons or nested payloads from the legacy trace.
        name = event.get("event")
        if not isinstance(name, str) or name not in _EVENTS:
            return
        row: dict[str, Any] = {
            "event": name,
            "ordinal": len(attempt["host_events"]),
            "host_attempt_trace_id": attempt["host_attempt_trace_id"],
            "request_ref": _ref("request", event.get("logical_request_id")),
            "retrieval_trace_ref": _ref("retrieval", event.get("trace_id")),
            "legacy_attempt_ref": _ref("legacy-attempt", event.get("attempt_trace_id")),
        }
        for key in ("context_sha256", "provider_payload_sha256"):
            value = event.get(key)
            row[key] = value if (
                isinstance(value, str) and len(value) == 64
                and all(char in "0123456789abcdef" for char in value)
            ) else None
        for key in ("context_in_prompt", "fresh_resolve"):
            value = event.get(key)
            row[key] = value if isinstance(value, bool) else None
        cache = event.get("cache_validation_outcome")
        row["cache_reused"] = True if cache in {"HIT", "REUSED"} else (
            False if cache == "MISS" else None
        )
        attempt["host_events"].append(row)

    def complete(
        self, incoming: OpenAIChatRequest, metadata: NativeTaskMetadata,
        *, request_parse_ms: float | None = None, retry_of: str | None = None,
    ) -> tuple[dict[str, Any] | StreamingCompletion, str]:
        # Lazy stream completion requires a lifetime-spanning observer; this
        # version rejects it before the original adapter or transport is invoked.
        if incoming.stream:
            raise ValueError("HOST_OWNER_TRACE_STREAM_NOT_SUPPORTED")
        if not self._observation_lock.acquire(blocking=False):
            raise RuntimeError("HOST_OWNER_TRACE_CONCURRENT_ATTEMPT")
        original_transport = self.transport
        original_mcp = self.host_mcp
        try:
            task_digest = _digest([self.run_id, metadata.host_instance, metadata.task_session])
            if retry_of is not None and not any(
                item["host_attempt_trace_id"] == retry_of
                and item["task_identity_digest"] == task_digest
                for item in self._owner_attempts
            ):
                raise ValueError("HOST_OWNER_TRACE_UNBOUND_RETRY")
            attempt: dict[str, Any] = {
                "schema_version": "milai-host-owner-trace-v1",
                "run_ref": _ref("run", self.run_id),
                "host_attempt_trace_id": "host-attempt:" + uuid4().hex,
                "task_identity_digest": task_digest,
                "operation_digest": _digest(metadata.task_operation),
                "retry_of": retry_of,
                "terminal": "FAILURE",
                "route_ref": None,
                "host_events": [],
                "provider_requests": [],
                "mcp_invocations": [],
            }
            self._owner_attempt = attempt
            self._owner_attempts.append(attempt)
            contexts: list[tuple[str, dict[str, Any]]] = []
            self.transport = _ObservedTransport(original_transport, attempt, contexts)
            if original_mcp is not None and self.memory_mode == "query-first":
                # Only resolve_memory is used by this serial query-first call;
                # restore the original concrete client before close/other routes.
                self.host_mcp = cast(McpUnixClient, _ObservedMcp(original_mcp, attempt, contexts))
            response, route = super().complete(
                incoming, metadata, request_parse_ms=request_parse_ms,
            )
            attempt["terminal"] = "RETURNED"
            attempt["route_ref"] = _ref("route", route)
            return response, route
        finally:
            self.transport = original_transport
            self.host_mcp = original_mcp
            self._owner_attempt = None
            self._observation_lock.release()
