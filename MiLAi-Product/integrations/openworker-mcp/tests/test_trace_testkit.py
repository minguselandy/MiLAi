from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from milai_openworker_mcp.host_adapter import OpenAIChatRequest, OpenWorkerProviderAdapter
from milai_openworker_mcp.provider_execution import (
    DevRunCapability,
    NativeProviderResponse,
    ProviderCallError,
    ProviderRequest,
    ProviderTransportError,
)
from milai_openworker_mcp.task_binding import NativeTaskMetadata
from milai_openworker_mcp.trace_testkit import ObservedOpenWorkerProviderAdapter
from test_host_adapter import (
    FIXTURE,
    SOCKET_ROOT,
    _provider_manifest,
    _reader_lite_policy,
    _request,
    _test_tokenizer_json,
)


class _Transport:
    name = "json"

    def __init__(self, error: Exception | None = None) -> None:
        self.requests: list[ProviderRequest] = []
        self.error = error

    def invoke(
        self, request: ProviderRequest, capability: DevRunCapability,
    ) -> NativeProviderResponse:
        del capability
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        native = f"native-{len(self.requests)}"
        return NativeProviderResponse(
            native_request_id=native, prompt_tokens=5, completion_tokens=3, finish_reason="stop",
            payload={
                "id": native, "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )


def _metadata(operation: str = "operation-1") -> NativeTaskMetadata:
    return NativeTaskMetadata("123e4567-e89b-12d3-a456-426614174000", "session-1", operation)


def _incoming(**options: object) -> OpenAIChatRequest:
    return OpenAIChatRequest.parse(_request(messages=[
        {"role": "system", "content": "Keep this system message."},
        {"role": "assistant", "content": "Earlier answer."},
        {"role": "user", "content": "What is current?"},
    ], **options))


def _adapter(
    root: Path, *, observed: bool = True, mode: str = "none",
) -> OpenWorkerProviderAdapter:
    root.mkdir()
    adapter_type = ObservedOpenWorkerProviderAdapter if observed else OpenWorkerProviderAdapter
    options: dict[str, Any] = {}
    if mode == "query-first":
        options.update(
            prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
            tokenizer_json=_test_tokenizer_json(root), broker_policy=_reader_lite_policy(root),
            task_fixture=FIXTURE,
        )
    return adapter_type(
        _provider_manifest(root / "manifest.json"), root / "ledger.jsonl", root / "trace.jsonl",
        memory_mode=mode, **options,
    )


@pytest.mark.parametrize("mode", ["none", "query-first"])
def test_observation_is_neutral_to_payload_response_budget_and_request_count(
    tmp_path: Path, mode: str,
) -> None:
    baseline = _adapter(tmp_path / "baseline", observed=False, mode=mode)
    observed = _adapter(tmp_path / "on", mode=mode)
    if mode == "query-first":
        for adapter in (baseline, observed):
            assert adapter.host_mcp is not None
            adapter.host_mcp.close()
            adapter.host_mcp = _QueryFirstMcp()  # type: ignore[assignment]
    assert isinstance(observed, ObservedOpenWorkerProviderAdapter)
    plain_transport, observed_transport = _Transport(), _Transport()
    baseline.transport, observed.transport = plain_transport, observed_transport
    incoming = _incoming()
    original = copy.deepcopy(incoming.payload)
    try:
        assert baseline.complete(incoming, _metadata()) == observed.complete(incoming, _metadata())
        assert plain_transport.requests == observed_transport.requests
        assert incoming.payload == original
        assert observed.transport is observed_transport
        traces = observed.owner_traces()
        assert len(traces) == 1
        trace = traces[0]
        assert trace["terminal"] == "RETURNED"
        request = trace["provider_requests"][0]
        assert request["input_tokens"] == 5 and request["output_tokens"] == 3
        assert request["status"] == "SUCCESS"
        answer = next(row for row in trace["host_events"] if row["event"] == "PROVIDER_ANSWER")
        assert answer["request_ref"] == request["request_ref"]
        assert answer["provider_payload_sha256"] == request["payload_sha256"]
        assert answer["host_attempt_trace_id"] == request["host_attempt_trace_id"]
        assert answer["context_in_prompt"] is (mode == "query-first")
        if mode == "query-first":
            # The second actual call takes the Runtime-validated cached path.
            assert baseline.complete(incoming, _metadata("op-2")) == observed.complete(
                incoming, _metadata("op-2"),
            )
            assert plain_transport.requests == observed_transport.requests
            assert observed.owner_traces()[1]["mcp_invocations"][0]["receipt_reused"]
        assert "Keep this system message" not in json.dumps(trace)
        assert "Earlier answer" not in json.dumps(trace)
        assert "session-1" not in json.dumps(trace)
        assert "operation-1" not in json.dumps(trace)
        trace["provider_requests"].clear()
        assert len(observed.owner_traces()[0]["provider_requests"]) == 1
    finally:
        baseline.close()
        observed.close()


def test_identical_payload_retry_gets_fresh_attempt_and_request_ids(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    adapter.transport = _Transport()
    incoming = _incoming()
    try:
        adapter.complete(incoming, _metadata())
        first = adapter.owner_traces()[0]
        adapter.complete(incoming, _metadata(), retry_of=first["host_attempt_trace_id"])
        first, second = adapter.owner_traces()
        assert first["host_attempt_trace_id"] != second["host_attempt_trace_id"]
        assert first["task_identity_digest"] == second["task_identity_digest"]
        assert second["retry_of"] == first["host_attempt_trace_id"]
        assert first["provider_requests"][0]["request_ref"] != (
            second["provider_requests"][0]["request_ref"]
        )
    finally:
        adapter.close()


@pytest.mark.parametrize("started", [False, True])
def test_transport_failure_preserves_unknown_usage_and_original_failure(
    tmp_path: Path, started: bool,
) -> None:
    adapter = _adapter(tmp_path / "host")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    transport = _Transport(ProviderTransportError("PRIVATE_ERROR_TEXT", request_started=started))
    adapter.transport = transport
    try:
        with pytest.raises(ProviderCallError):
            adapter.complete(_incoming(), _metadata())
        trace = adapter.owner_traces()[0]
        assert trace["terminal"] == "FAILURE"
        row = trace["provider_requests"][0]
        assert row["status"] == "FAILURE" and row["request_started"] is started
        assert row["input_tokens"] is None and row["output_tokens"] is None
        assert row["native_request_ref"] is None
        assert "PRIVATE_ERROR_TEXT" not in json.dumps(trace)
        assert adapter.transport is transport
    finally:
        adapter.close()


def test_unexpected_transport_exception_is_preserved_with_unknown_terminal(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    original = RuntimeError("PRIVATE_ERROR_TEXT")
    adapter.transport = _Transport(original)
    try:
        with pytest.raises(ProviderCallError, match="TRANSPORT_ADAPTER_EXCEPTION") as caught:
            adapter.complete(_incoming(), _metadata())
        assert caught.value.__cause__ is original
        trace = adapter.owner_traces()[0]
        assert trace["provider_requests"][0]["status"] == "UNKNOWN"
        assert trace["provider_requests"][0]["input_tokens"] is None
        assert "PRIVATE_ERROR_TEXT" not in json.dumps(trace)
    finally:
        adapter.close()


def test_stream_and_unbound_retry_are_rejected_before_provider(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    transport = _Transport()
    adapter.transport = transport
    try:
        incoming = _incoming(stream=True, stream_options={"include_usage": True})
        with pytest.raises(ValueError, match="HOST_OWNER_TRACE_STREAM_NOT_SUPPORTED"):
            adapter.complete(incoming, _metadata())
        with pytest.raises(ValueError, match="HOST_OWNER_TRACE_UNBOUND_RETRY"):
            adapter.complete(_incoming(), _metadata(), retry_of="missing")
        assert adapter.owner_traces() == []
        assert transport.requests == []
    finally:
        adapter.close()


class _QueryFirstMcp:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.calls: list[str | None] = []

    def resolve_memory(
        self, query: str, *, previous_context_id: str | None = None,
    ) -> dict[str, object]:
        del query
        self.calls.append(previous_context_id)
        outcome: dict[str, object] = {
            "schema_version": "access-outcome-v0.1",
            "status": "ABSTAINED" if self.blocked else "PARTIAL",
            "availability": "AVAILABLE", "items": [], "degraded_components": [],
            "open_issue_ids": ["issue-1"] if self.blocked else [],
            "abstention_reason": "OPEN_ISSUE" if self.blocked else "SUFFICIENCY_UNSATISFIED",
            "canonical_position": 20, "trace_id": "trace-1",
            "request_id": f"runtime-request-{len(self.calls)}",
            "receipt_reused": previous_context_id is not None,
            "context_receipt": {"context_capsule_id": "11111111-1111-4111-8111-111111111111"},
            "access_trace": {"planned_stage": "SEARCH", "terminal_stage": "SUFFICIENCY",
                             "spans": {"mcp_handler_ms": 2.0, "runtime_client_ms": 1.0}},
            "host_transport": {"uds_roundtrip_ms": 3.0},
        }
        if not self.blocked:
            outcome["reader_evidence_boundary"] = "GOVERNANCE_ADMITTED_SOFT_RANKED"
            outcome["memory_context"] = {
                "text": "MEMORY_CONTEXT_V0_2\nMEMORY_STATUS=PARTIAL\nprivate memory observation",
                "selected_evidence_ids": ["evidence-1"], "claim_versions": ["claim-version-1"],
            }
        return outcome

    def close(self) -> None:
        pass


def test_query_first_owner_binding_keeps_fresh_attempts_and_runtime_validated_cache(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path / "host", mode="query-first")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    mcp = _QueryFirstMcp()
    adapter.host_mcp = mcp  # type: ignore[assignment]
    transport = _Transport()
    adapter.transport = transport
    try:
        incoming = _incoming()
        assert adapter.complete(incoming, _metadata())[1] == "PROVIDER_AVAILABLE"
        assert adapter.complete(incoming, _metadata("operation-2"))[1] == "PROVIDER_AVAILABLE"
        first, second = adapter.owner_traces()
        prepares = [next(row for row in attempt["host_events"]
                         if row["event"] == "HOST_MCP_PREPARE_CONTEXT")
                    for attempt in (first, second)]
        assert prepares[0]["legacy_attempt_ref"] == prepares[1]["legacy_attempt_ref"]
        assert first["host_attempt_trace_id"] != second["host_attempt_trace_id"]
        assert mcp.calls == [None, "11111111-1111-4111-8111-111111111111"]
        assert prepares[0]["fresh_resolve"] is True
        assert prepares[1]["fresh_resolve"] is False
        assert prepares[1]["cache_reused"] is True
        assert prepares[0]["retrieval_trace_ref"] == prepares[1]["retrieval_trace_ref"]
        first_mcp, second_mcp = first["mcp_invocations"][0], second["mcp_invocations"][0]
        assert first_mcp["runtime_request_ref"] != second_mcp["runtime_request_ref"]
        assert first_mcp["previous_context_ref"] is None
        assert second_mcp["previous_context_ref"] == first_mcp["context_capsule_ref"]
        for attempt in (first, second):
            answer = next(
                row for row in attempt["host_events"] if row["event"] == "PROVIDER_ANSWER"
            )
            assert answer["context_in_prompt"] is True
            assert answer["request_ref"] == attempt["provider_requests"][0]["request_ref"]
            invocation, = attempt["mcp_invocations"]
            provider, = attempt["provider_requests"]
            binding, = provider["context_bindings"]
            assert invocation["host_attempt_trace_id"] == attempt["host_attempt_trace_id"]
            assert binding["mcp_invocation_id"] == invocation["invocation_id"]
            assert binding["retrieval_trace_ref"] == invocation["retrieval_trace_ref"]
            assert binding["runtime_request_ref"] == invocation["runtime_request_ref"]
            assert len(binding["selected_claim_version_refs"]) == 1
            assert binding["reader_context_sha256"] == answer["context_sha256"]
            assert len(binding["selected_evidence_refs"]) == 1
            assert provider["exposure_status"] == "DISPATCHED"
        assert first["mcp_invocations"][0]["invocation_id"] != (
            second["mcp_invocations"][0]["invocation_id"]
        )
        assert "private memory observation" not in json.dumps([first, second])
        assert "private memory observation" in json.dumps(transport.requests[0].payload)
    finally:
        adapter.close()


@pytest.mark.parametrize("started", [False, True, None])
def test_prepared_context_is_not_exposure_without_known_dispatch(
    tmp_path: Path, started: bool | None,
) -> None:
    adapter = _adapter(tmp_path / "host", mode="query-first")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    mcp = _QueryFirstMcp()
    adapter.host_mcp = mcp  # type: ignore[assignment]
    error = RuntimeError("PRIVATE_ERROR") if started is None else ProviderTransportError(
        "PRIVATE_ERROR", request_started=started,
    )
    adapter.transport = _Transport(error)
    try:
        with pytest.raises(ProviderCallError):
            adapter.complete(_incoming(), _metadata())
        row, = adapter.owner_traces()[0]["provider_requests"]
        assert len(row["prepared_context_bindings"]) == 1
        assert len(row["context_bindings"]) == (1 if started is True else 0)
        assert row["exposure_status"] == {
            True: "DISPATCHED", False: "NOT_STARTED", None: "UNKNOWN",
        }[started]
        assert row["input_tokens"] is None
        assert adapter.host_mcp is mcp
    finally:
        adapter.close()


def test_abstain_observation_does_not_invent_a_provider_request(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host", mode="query-first")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = _QueryFirstMcp(blocked=True)  # type: ignore[assignment]
    transport = _Transport()
    adapter.transport = transport
    try:
        _, route = adapter.complete(_incoming(), _metadata())
        assert route == "HOST_MEMORY_INSUFFICIENT"
        assert transport.requests == []
        trace = adapter.owner_traces()[0]
        assert trace["provider_requests"] == []
        assert any(row["event"] == "HOST_MCP_MEMORY_INSUFFICIENT" for row in trace["host_events"])
    finally:
        adapter.close()


def test_active_observation_rejects_nested_calls_and_partial_snapshot(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "host")
    assert isinstance(adapter, ObservedOpenWorkerProviderAdapter)

    class NestedTransport(_Transport):
        def invoke(
            self, request: ProviderRequest, capability: DevRunCapability,
        ) -> NativeProviderResponse:
            with pytest.raises(RuntimeError, match="HOST_OWNER_TRACE_ATTEMPT_ACTIVE"):
                adapter.owner_traces()
            with pytest.raises(RuntimeError, match="HOST_OWNER_TRACE_CONCURRENT_ATTEMPT"):
                adapter.complete(_incoming(), _metadata("other"))
            return super().invoke(request, capability)

    adapter.transport = NestedTransport()
    try:
        adapter.complete(_incoming(), _metadata())
        assert len(adapter.owner_traces()) == 1
        assert len(adapter.owner_traces()[0]["provider_requests"]) == 1
    finally:
        adapter.close()
