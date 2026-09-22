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
from typing import Any
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


class _ObservedTransport:
    def __init__(self, delegate: ProviderTransport, attempt: dict[str, Any]) -> None:
        self.name = delegate.name
        self.delegate = delegate
        self.attempt = attempt

    def invoke(
        self, request: ProviderRequest, capability: DevRunCapability,
    ) -> NativeProviderResponse:
        row: dict[str, Any] = {
            "request_ref": _ref("request", request.logical_request_id),
            "host_attempt_trace_id": self.attempt["host_attempt_trace_id"],
            "payload_sha256": _digest(request.payload),
            "native_request_ref": None,
            "status": "UNKNOWN",
            "request_started": None,
            "input_tokens": None,
            "output_tokens": None,
        }
        self.attempt["provider_requests"].append(row)
        try:
            response = self.delegate.invoke(request, capability)
        except ProviderTransportError as exc:
            row.update(
                status="FAILURE", request_started=exc.request_started,
                native_request_ref=_ref("native", exc.native_request_id),
            )
            raise
        # Unknown exceptions intentionally preserve UNKNOWN and unknown usage.
        row.update(
            status="SUCCESS", request_started=True,
            native_request_ref=_ref("native", response.native_request_id),
            input_tokens=response.prompt_tokens, output_tokens=response.completion_tokens,
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
            }
            self._owner_attempt = attempt
            self._owner_attempts.append(attempt)
            self.transport = _ObservedTransport(original_transport, attempt)
            response, route = super().complete(
                incoming, metadata, request_parse_ms=request_parse_ms,
            )
            attempt["terminal"] = "RETURNED"
            attempt["route_ref"] = _ref("route", route)
            return response, route
        finally:
            self.transport = original_transport
            self._owner_attempt = None
            self._observation_lock.release()
