from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from milai_openworker_mcp.provider_execution import (
    BudgetError,
    CapabilityError,
    NativeProviderResponse,
    ProviderCallError,
    ProviderExecutionError,
    ProviderExecutionGateway,
    ProviderRequest,
    ProviderTransportError,
)

MODEL = "Qwen3.6-35B-A3B-FP8"


def _manifest(path: Path, **overrides: Any) -> Path:
    now = datetime.now(UTC)
    value = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": "f1-functional-test-0001",
        "phase": "functional_f1",
        "provider": "local_vllm",
        "endpoint_identity": "http://127.0.0.1:7860",
        "model_id": MODEL,
        "dataset_manifest_sha256": "a" * 64,
        "prompt_template_sha256": "b" * 64,
        "max_native_requests": 5,
        "max_prompt_tokens": 500,
        "max_completion_tokens": 100,
        "deadline": (now + timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
        **overrides,
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _request(identifier: str, transport: str = "json") -> ProviderRequest:
    return ProviderRequest(
        logical_request_id=identifier,
        transport=transport,
        payload={
            "model": MODEL,
            "messages": [{"role": "user", "content": "synthetic"}],
            "temperature": 0,
            "max_tokens": 10,
            "stream": transport == "stream",
        },
        prompt_token_budget=50,
        completion_token_budget=10,
        timeout_seconds=2,
    )


def _closed_loopback_endpoint() -> str:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    return f"http://127.0.0.1:{port}"


class _Transport:
    name = "json"

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, request, capability) -> NativeProviderResponse:  # type: ignore[no-untyped-def]
        self.calls += 1
        return NativeProviderResponse(
            native_request_id=f"native-{request.logical_request_id}",
            prompt_tokens=7,
            completion_tokens=3,
            finish_reason="stop",
            payload={"answer": "OK"},
        )


def test_missing_or_expired_capability_performs_no_transport_call(tmp_path: Path) -> None:
    transport = _Transport()
    gateway = ProviderExecutionGateway(tmp_path / "missing.json", tmp_path / "ledger.jsonl")
    with pytest.raises(CapabilityError):
        gateway.execute(_request("logical-request-0001"), transport, dict)
    assert transport.calls == 0
    assert not (tmp_path / "ledger.jsonl").exists()

    expired = _manifest(
        tmp_path / "expired.json",
        deadline=(datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    gateway = ProviderExecutionGateway(expired, tmp_path / "expired-ledger.jsonl")
    with pytest.raises(CapabilityError):
        gateway.execute(_request("logical-request-0002"), transport, dict)
    assert transport.calls == 0


def test_closed_test_capability_requires_confirmation_schema_and_phase(
    tmp_path: Path,
) -> None:
    closed = _manifest(
        tmp_path / "closed.json",
        schema="milai.provider.closed-test-run.v1",
        phase="confirmation",
        closed_test_access=True,
    )
    gateway = ProviderExecutionGateway(closed, tmp_path / "closed-ledger.jsonl")
    transport = _Transport()

    result = gateway.execute(_request("confirmation-request-0001"), transport, dict)

    assert result.value == {"answer": "OK"}
    assert transport.calls == 1

    mismatched = _manifest(
        tmp_path / "mismatched.json",
        schema="milai.provider.closed-test-run.v1",
        phase="dev",
        closed_test_access=True,
    )
    rejected = ProviderExecutionGateway(
        mismatched,
        tmp_path / "mismatched-ledger.jsonl",
    )
    with pytest.raises(CapabilityError, match="phase"):
        rejected.execute(_request("confirmation-request-0002"), transport, dict)
    assert transport.calls == 1


def test_success_records_provider_terminal_before_answer_parser(tmp_path: Path) -> None:
    gateway = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    )
    transport = _Transport()

    def parser(payload: Any) -> str:
        events = gateway.read_ledger()
        assert [event["event"] for event in events] == ["RESERVED", "PROVIDER_TERMINAL"]
        assert events[-1]["status"] == "SUCCEEDED"
        return str(payload["answer"])

    result = gateway.execute(_request("logical-request-0003"), transport, parser)
    assert result.value == "OK"
    assert result.native_request_id == "native-logical-request-0003"
    assert [event["event"] for event in gateway.read_ledger()] == [
        "RESERVED",
        "PROVIDER_TERMINAL",
        "POST_PROVIDER_TERMINAL",
    ]


def test_restart_sequence_recovers_next_id_from_completed_hash_chain(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    ledger = tmp_path / "ledger.jsonl"
    warm = ProviderExecutionGateway(manifest, ledger)

    assert warm.next_logical_request_sequence() == 1
    warm.execute(_request("f1-functional-test-0001-ow-01"), _Transport(), dict)

    replacement = ProviderExecutionGateway(manifest, ledger)
    assert replacement.next_logical_request_sequence() == 2


@pytest.mark.parametrize(
    "logical_request_id",
    [
        "f1-functional-test-0001-ow-02",
        "f1-functional-test-0001-ow-001",
        "foreign-run-ow-01",
    ],
)
def test_restart_sequence_rejects_gap_illegal_suffix_and_foreign_run(
    tmp_path: Path, logical_request_id: str
) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    ledger = tmp_path / "ledger.jsonl"
    gateway = ProviderExecutionGateway(manifest, ledger)
    gateway.execute(_request(logical_request_id), _Transport(), dict)

    with pytest.raises(ProviderExecutionError, match="logical request sequence"):
        ProviderExecutionGateway(manifest, ledger).next_logical_request_sequence()


def test_restart_sequence_rejects_manifest_drift_and_hash_chain_tamper(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path / "manifest.json")
    ledger = tmp_path / "ledger.jsonl"
    gateway = ProviderExecutionGateway(manifest, ledger)
    gateway.execute(_request("f1-functional-test-0001-ow-01"), _Transport(), dict)

    drifted = _manifest(
        tmp_path / "drifted.json",
        dataset_manifest_sha256="c" * 64,
    )
    with pytest.raises(ProviderExecutionError, match="logical request sequence"):
        ProviderExecutionGateway(drifted, ledger).next_logical_request_sequence()

    rows = ledger.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["logical_request_id"] = "f1-functional-test-0001-ow-02"
    rows[0] = json.dumps(first, sort_keys=True)
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ProviderExecutionError, match="hash chain"):
        ProviderExecutionGateway(manifest, ledger).next_logical_request_sequence()


def test_budget_is_reserved_atomically_before_transport(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path / "manifest.json",
        max_native_requests=1,
        max_prompt_tokens=50,
        max_completion_tokens=10,
    )
    gateway = ProviderExecutionGateway(manifest, tmp_path / "ledger.jsonl")
    transport = _Transport()
    gateway.execute(_request("logical-request-0004"), transport, dict)
    with pytest.raises(BudgetError, match="native request budget"):
        gateway.execute(_request("logical-request-0005"), transport, dict)
    assert transport.calls == 1


def test_transport_failure_keeps_started_request_and_native_identity(tmp_path: Path) -> None:
    class FailedTransport:
        name = "json"

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            raise ProviderTransportError(
                "TIMEOUT_AFTER_HEADERS",
                request_started=True,
                native_request_id="native-timeout-0001",
            )

    gateway = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    )
    with pytest.raises(ProviderCallError, match="TIMEOUT_AFTER_HEADERS"):
        gateway.execute(_request("logical-request-0006"), FailedTransport(), dict)
    terminal = gateway.read_ledger()[-1]
    assert terminal["event"] == "PROVIDER_TERMINAL"
    assert terminal["request_started"] is True
    assert terminal["native_request_id"] == "native-timeout-0001"
    assert terminal["status"] == "FAILED"


def test_parse_failure_occurs_after_provider_terminal_and_is_bounded(tmp_path: Path) -> None:
    gateway = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    )

    def malformed(_payload: Any) -> str:
        raise ValueError("malformed answer")

    with pytest.raises(ProviderCallError, match="ANSWER_PARSE_FAILED"):
        gateway.execute(_request("logical-request-0007"), _Transport(), malformed)
    events = gateway.read_ledger()
    assert events[-2]["event"] == "PROVIDER_TERMINAL"
    assert events[-2]["status"] == "SUCCEEDED"
    assert events[-1]["event"] == "POST_PROVIDER_TERMINAL"
    assert events[-1]["reason_code"] == "ANSWER_PARSE_FAILED"


def test_provider_request_allows_provider_default_when_max_tokens_is_absent(
    tmp_path: Path,
) -> None:
    request = _request("logical-request-default-max")
    payload = dict(request.payload)
    del payload["max_tokens"]
    request = ProviderRequest(
        logical_request_id=request.logical_request_id,
        transport=request.transport,
        payload=payload,
        prompt_token_budget=request.prompt_token_budget,
        completion_token_budget=request.completion_token_budget,
        timeout_seconds=request.timeout_seconds,
    )

    result = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    ).execute(request, _Transport(), dict)

    assert result.value == {"answer": "OK"}


def test_stream_is_forwarded_byte_for_byte_and_opened_once(tmp_path: Path) -> None:
    class StreamTransport:
        name = "stream"

        def __init__(self) -> None:
            self.opens = 0

        def open_stream(self, request, capability):  # type: ignore[no-untyped-def]
            self.opens += 1
            return iter(
                [
                    (
                        b'data: {"id":"native-stream-0001","choices":'
                        b'[{"delta":{"content":"A"},"finish_reason":null}]}\n\n'
                    ),
                    (
                        b'data: {"id":"native-stream-0001","choices":'
                        b'[{"delta":{},"finish_reason":"stop"}],'
                        b'"usage":{"prompt_tokens":2,"completion_tokens":1}}\n\n'
                    ),
                    b"data: [DONE]\n\n",
                ]
            )

    gateway = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    )
    transport = StreamTransport()
    expected = b"".join(transport.open_stream(None, None))
    transport.opens = 0

    observed = b"".join(
        gateway.execute_stream(_request("logical-stream-0001", "stream"), transport)
    )

    assert observed == expected
    assert transport.opens == 1
    assert [event["event"] for event in gateway.read_ledger()] == [
        "RESERVED",
        "PROVIDER_TERMINAL",
        "POST_PROVIDER_TERMINAL",
    ]


def test_stream_failure_is_terminal_and_never_retried(tmp_path: Path) -> None:
    class FailedStreamTransport:
        name = "stream"

        def __init__(self) -> None:
            self.opens = 0

        def open_stream(self, request, capability):  # type: ignore[no-untyped-def]
            self.opens += 1
            raise ProviderTransportError("PROVIDER_UNAVAILABLE", request_started=False)

    gateway = ProviderExecutionGateway(
        _manifest(tmp_path / "manifest.json"), tmp_path / "ledger.jsonl"
    )
    transport = FailedStreamTransport()

    with pytest.raises(ProviderCallError, match="PROVIDER_UNAVAILABLE"):
        gateway.execute_stream(_request("logical-stream-0002", "stream"), transport)

    assert transport.opens == 1
    assert gateway.read_ledger()[-1]["status"] == "FAILED"
