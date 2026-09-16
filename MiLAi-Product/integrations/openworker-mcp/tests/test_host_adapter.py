from __future__ import annotations

import hashlib
import http.client
import inspect
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from milai_client import AccessOutcome, TaskPreparedContext
from milai_client.context_policy import PrefetchContext

from milai_openworker_mcp.host_adapter import (
    _MEMORY_READING_POLICY,
    _ORDINARY_READ_PATH,
    _VLLM_JSON_SCHEMA_NAMED_TOOL,
    EXACT_MODEL_ID,
    Handler,
    OpenAIChatRequest,
    OpenWorkerAdapterError,
    OpenWorkerProviderAdapter,
    OrdinaryToolCompatibilityError,
    StreamingCompletion,
    _apply_single_ordinary_tool_required_once,
    _apply_vllm_json_schema_named_tool_compatibility,
    _authenticate_ingress,
    _last_user_content,
    _load_startup_task_policy,
    _memory_insufficient_outcome,
    _memory_terminal_completion,
    _native_request_observation,
    _prepared_prefetch,
    _question,
    _shadow_route_trace,
    _task_metadata_from_values,
    _transport_unavailable_outcome,
    _vllm_json_schema_named_tool_chunks,
)
from milai_openworker_mcp.memory_facade import (
    OpenWorkerMemoryFacade,
    decode_memory_support_lineage,
)
from milai_openworker_mcp.provider_execution import (
    BudgetError,
    NativeProviderResponse,
    ProviderCallError,
)

FIXTURE = Path(__file__).resolve().parents[3] / "contracts/agent/v1/dg13u-u1-candidate-fixture.json"
SOCKET_ROOT = Path("/dev") / "shm" / "milai" / "synthetic"


def _synthetic_run_token() -> str:
    return "-".join(("synthetic", "run", "token"))


def _request(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "model": EXACT_MODEL_ID,
        "messages": [
            {
                "role": "system",
                "content": "Keep this system message.",
                "name": "openworker",
            },
            {"role": "assistant", "content": "Earlier answer."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-weather",
                        "type": "function",
                        "function": {"name": "weather", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-weather", "content": "sunny"},
            {"role": "user", "content": "What is current?"},
        ],
        "stream": False,
        "tools": [
            {"type": "function", "function": {"name": "milai_milai_recall"}},
            {"type": "function", "function": {"name": "weather"}},
        ],
        "tool_choice": "auto",
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 64,
        "seed": 7,
        "response_format": {"type": "json_object"},
    }
    value.update(updates)
    return value


def _provider_manifest(path: Path, *, run_id: str = "host-adapter-test-run") -> Path:
    now = datetime.now(UTC)
    path.write_text(
        json.dumps(
            {
                "schema": "milai.provider.dev-run.v1",
                "run_id": run_id,
                "phase": "functional_f1",
                "provider": "local_vllm",
                "endpoint_identity": "http://127.0.0.1:7860",
                "model_id": EXACT_MODEL_ID,
                "dataset_manifest_sha256": "a" * 64,
                "prompt_template_sha256": "b" * 64,
                "max_native_requests": 8,
                "max_prompt_tokens": 800,
                "max_completion_tokens": 768,
                "deadline": (now + timedelta(minutes=5)).isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "synthetic_or_deidentified_only": True,
                "closed_test_access": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _reader_lite_policy(tmp_path: Path) -> Path:
    executable = tmp_path / "milai-mcp"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o500)
    policy = {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": "reader-lite",
        "socket_path": str(SOCKET_ROOT / "reader-lite.sock"),
        "socket_mode": "0600",
        "allowed_peer_uids": [os.geteuid()],
        "mcp_executable": str(executable),
        "mcp_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "base_url": "http://127.0.0.1:18080",
        "scope": {"project_ids": ["orchid-release"]},
        "required_authority": "INFORMATIONAL",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 3,
        "max_connections": 2,
        "child_shutdown_seconds": 2,
        "mcp_max_retries": 0,
    }
    path = tmp_path / "broker-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    path.chmod(0o600)
    return path


def _test_tokenizer_json(tmp_path: Path) -> Path:
    """Create a minimal exact tokenizer without relying on private model artifacts."""
    path = tmp_path / "tokenizer.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "truncation": None,
                "padding": None,
                "added_tokens": [],
                "normalizer": None,
                "pre_tokenizer": {"type": "Whitespace"},
                "post_processor": None,
                "decoder": None,
                "model": {
                    "type": "WordLevel",
                    "vocab": {"[UNK]": 0, "hello": 1, "world": 2},
                    "unk_token": "[UNK]",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_ingress_bearer_and_native_headers_are_exact_single_values() -> None:
    _authenticate_ingress(["Bearer synthetic-run-token"], "synthetic-run-token")
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_synthetic-1"],
            "X-MiLAi-Task-Operation": ["msg_synthetic-1"],
        }
    )

    assert metadata.task_session == "ses_synthetic-1"
    settlement_metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_synthetic-1"],
            "X-MiLAi-Task-Operation": ["msg_synthetic-1"],
            "X-MiLAi-Assistant-Message": ["msg_synthetic-assistant-1"],
            "X-MiLAi-User-Observed-At": ["2026-09-02T14:00:00.000Z"],
            "X-MiLAi-Assistant-Observed-At": ["2026-09-02T14:00:00.010Z"],
        },
        require_settlement=True,
    )
    assert settlement_metadata.assistant_message == "msg_synthetic-assistant-1"
    assert settlement_metadata.user_observed_at == "2026-09-02T14:00:00.000Z"
    with pytest.raises(OpenWorkerAdapterError, match="TASK_METADATA_INVALID"):
        _task_metadata_from_values(
            {
                "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
                "X-MiLAi-Task-Session": ["ses_synthetic-1"],
                "X-MiLAi-Task-Operation": ["msg_synthetic-1"],
            },
            require_settlement=True,
        )
    with pytest.raises(OpenWorkerAdapterError, match="AUTHENTICATION_REQUIRED"):
        _authenticate_ingress([], "synthetic-run-token")
    with pytest.raises(OpenWorkerAdapterError, match="AUTHENTICATION_REQUIRED"):
        _authenticate_ingress(["Bearer wrong"], "synthetic-run-token")
    with pytest.raises(OpenWorkerAdapterError, match="TASK_METADATA_INVALID"):
        _task_metadata_from_values(
            {
                "X-MiLAi-Host-Instance": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "123e4567-e89b-12d3-a456-426614174001",
                ],
                "X-MiLAi-Task-Session": ["ses_synthetic-1"],
                "X-MiLAi-Task-Operation": ["msg_synthetic-1"],
            }
        )


def test_provider_request_rejects_unknown_model_and_stream_contract() -> None:
    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_REQUEST_UNSUPPORTED"):
        OpenAIChatRequest.parse(_request(user="body-cannot-select-task"))
    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_MODEL_UNSUPPORTED"):
        OpenAIChatRequest.parse(_request(model="AUTO"))
    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_REQUEST_INVALID"):
        OpenAIChatRequest.parse(_request(stream=True, stream_options={"include_usage": False}))
    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_REQUEST_INVALID"):
        OpenAIChatRequest.parse(_request(stream=False, stream_options={"include_usage": True}))


def test_multi_request_capability_is_partitioned_into_per_request_reservations() -> None:
    from milai_openworker_mcp import host_adapter

    partition = host_adapter._per_request_token_budget

    assert partition(65_536, 2) == 32_768
    assert partition(768, 3) == 256
    with pytest.raises(OpenWorkerAdapterError, match="smaller than native request budget"):
        partition(1, 2)


def test_provider_timeout_is_explicit_and_bounded_for_failure_injection() -> None:
    from milai_openworker_mcp import host_adapter

    validate = host_adapter._bounded_provider_timeout

    assert validate(0.25) == 0.25
    assert validate(60) == 60.0
    for invalid in (0, -1, 601, True, "1"):
        with pytest.raises(ValueError, match="provider timeout"):
            validate(invalid)


def test_single_ordinary_tool_compatibility_is_default_off() -> None:
    parameter = inspect.signature(OpenWorkerProviderAdapter).parameters[
        "single_ordinary_tool_required_once"
    ]

    assert parameter.default is None

    with pytest.raises(ValueError, match="single ordinary tool compatibility only supports read"):
        OpenWorkerProviderAdapter(
            Path("/does/not/reach/provider-manifest.json"),
            Path("/does/not/reach/provider-ledger.jsonl"),
            Path("/does/not/reach/host-trace.jsonl"),
            single_ordinary_tool_required_once="bash",
        )

    with pytest.raises(ValueError, match="requires the read policy"):
        OpenWorkerProviderAdapter(
            Path("/does/not/reach/provider-manifest.json"),
            Path("/does/not/reach/provider-ledger.jsonl"),
            Path("/does/not/reach/host-trace.jsonl"),
            ordinary_tool_provider_compatibility=_VLLM_JSON_SCHEMA_NAMED_TOOL,
        )


def test_context_insertion_preserves_declared_fields_and_excludes_only_memory_tool() -> None:
    parsed = OpenAIChatRequest.parse(_request())

    payload, excluded = parsed.provider_payload("MEMORY_STATUS=AVAILABLE\nCURRENT=synthetic")

    assert excluded == ("milai_milai_recall",)
    assert payload["messages"][0] == {
        "role": "system",
        "name": "openworker",
        "content": (
            f"Keep this system message.\n\n{_MEMORY_READING_POLICY}\n\n"
            "MILAI_CONTEXT_BEGIN\nMEMORY_STATUS=AVAILABLE\nCURRENT=synthetic\nMILAI_CONTEXT_END"
        ),
    }
    assert payload["messages"][1:] == _request()["messages"][1:]
    assert [message["role"] for message in payload["messages"]].count("system") == 1
    assert payload["tools"] == [{"type": "function", "function": {"name": "weather"}}]
    for name in (
        "model",
        "stream",
        "tool_choice",
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "response_format",
    ):
        assert payload[name] == _request()[name]


def test_context_insertion_creates_system_only_when_request_has_none() -> None:
    original_messages = [
        {"role": "assistant", "content": "Earlier answer."},
        {"role": "user", "content": "What is current?"},
    ]
    parsed = OpenAIChatRequest.parse(_request(messages=original_messages))

    payload, _ = parsed.provider_payload("MEMORY_STATUS=AVAILABLE\nCURRENT=synthetic")

    assert payload["messages"] == [
        {
            "role": "system",
            "content": (
                f"{_MEMORY_READING_POLICY}\n\n"
                "MILAI_CONTEXT_BEGIN\nMEMORY_STATUS=AVAILABLE\nCURRENT=synthetic\nMILAI_CONTEXT_END"
            ),
        },
        *original_messages,
    ]


def test_memory_reading_policy_is_absent_without_context_and_precedes_untrusted_context() -> None:
    parsed = OpenAIChatRequest.parse(_request())

    plain_payload, _ = parsed.provider_payload(None)
    contextual_payload, _ = parsed.provider_payload(
        "MEMORY_STATUS=AVAILABLE\nCURRENT=untrusted synthetic evidence"
    )

    plain_system = plain_payload["messages"][0]["content"]
    contextual_system = contextual_payload["messages"][0]["content"]
    assert isinstance(plain_system, str)
    assert isinstance(contextual_system, str)
    assert _MEMORY_READING_POLICY not in plain_system
    assert contextual_system.count(_MEMORY_READING_POLICY) == 1
    assert contextual_system.index(_MEMORY_READING_POLICY) < contextual_system.index(
        "MILAI_CONTEXT_BEGIN"
    )
    assert contextual_system.index("MILAI_CONTEXT_BEGIN") < contextual_system.index(
        "CURRENT=untrusted synthetic evidence"
    )


def test_native_multiline_json_string_transport_is_unwrapped_for_memory_query() -> None:
    semantic_question = "Reference time: now\nWhich facts are relevant?"

    assert _question(
        [{"role": "user", "content": json.dumps(semantic_question)}]
    ) == semantic_question
    assert _question(
        [{"role": "user", "content": f'"{semantic_question}"'}]
    ) == semantic_question
    assert _last_user_content(
        [{"role": "user", "content": json.dumps(semantic_question) + "\n"}]
    ) == semantic_question
    assert _last_user_content(
        [{"role": "user", "content": f'"{semantic_question}"'}]
    ) == semantic_question


def _ordinary_tool_request(*, messages: list[dict[str, object]]) -> OpenAIChatRequest:
    return OpenAIChatRequest.parse(
        _request(
            messages=messages,
            tools=[
                {"type": "function", "function": {"name": "milai_milai_recall"}},
                {
                    "type": "function",
                    "function": {
                        "name": "read",
                        "description": "Read one synthetic workspace file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"filePath": {"type": "string"}},
                            "required": ["filePath"],
                            "additionalProperties": False,
                        },
                    },
                },
            ],
            tool_choice="auto",
            response_format=None,
        )
    )


def test_target_memory_resolve_is_never_forwarded_to_answer_provider() -> None:
    parsed = OpenAIChatRequest.parse(
        _request(
            tools=[
                {"type": "function", "function": {"name": "milai_memory_resolve"}},
                {"type": "function", "function": {"name": "weather"}},
            ]
        )
    )

    payload, excluded = parsed.provider_payload("MEMORY_STATUS=AVAILABLE")

    assert excluded == ("milai_memory_resolve",)
    assert payload["tools"] == [{"type": "function", "function": {"name": "weather"}}]


def test_single_ordinary_tool_policy_uses_named_then_none_without_exposing_memory() -> None:
    first = _ordinary_tool_request(
        messages=[{"role": "user", "content": "Read the synthetic marker once."}]
    )
    first_payload, first_excluded = first.provider_payload(None)

    first_truth = _apply_single_ordinary_tool_required_once(first_payload, "read")

    assert first_excluded == ("milai_milai_recall",)
    assert [tool["function"]["name"] for tool in first_payload["tools"]] == ["read"]
    assert first_payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "read"},
    }
    assert first_truth == {
        "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
        "round": "CALL",
        "requested_tool_choice": "AUTO",
        "effective_tool_choice": "NAMED",
        "ordinary_tool_count": 1,
        "ordinary_tool_name_sha256": hashlib.sha256(b"read").hexdigest(),
        "assistant_tool_call_count": 0,
        "tool_result_count": 0,
        "matching_tool_result_count": 0,
        "tool_call_id_sha256": None,
    }

    call_id = "call_synthetic_read_1"
    second_messages: list[dict[str, object]] = [
        {"role": "user", "content": "Read the synthetic marker once."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": '{"filePath":"/synthetic/marker"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": "synthetic marker result",
        },
    ]
    second = _ordinary_tool_request(messages=second_messages)
    second_payload, second_excluded = second.provider_payload(None)

    second_truth = _apply_single_ordinary_tool_required_once(second_payload, "read")

    assert second_excluded == ("milai_milai_recall",)
    assert second_payload["messages"] == second_messages
    assert second_payload["tool_choice"] == "none"
    assert second_truth == {
        "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
        "round": "FINAL",
        "requested_tool_choice": "AUTO",
        "effective_tool_choice": "NONE",
        "ordinary_tool_count": 1,
        "ordinary_tool_name_sha256": hashlib.sha256(b"read").hexdigest(),
        "assistant_tool_call_count": 1,
        "tool_result_count": 1,
        "matching_tool_result_count": 1,
        "tool_call_id_sha256": hashlib.sha256(call_id.encode()).hexdigest(),
    }
    assert "synthetic marker result" not in json.dumps(second_truth, sort_keys=True)
    assert "/synthetic/marker" not in json.dumps(second_truth, sort_keys=True)


def test_vllm_json_schema_named_tool_compatibility_is_narrow_and_explicit() -> None:
    first = _ordinary_tool_request(
        messages=[{"role": "user", "content": "Read the synthetic marker once."}]
    )
    first_payload, _ = first.provider_payload(None)
    first_policy = _apply_single_ordinary_tool_required_once(first_payload, "read")

    assert _apply_vllm_json_schema_named_tool_compatibility(first_payload, first_policy)
    assert "tools" not in first_payload
    assert "tool_choice" not in first_payload
    schema = first_payload["response_format"]["json_schema"]["schema"]
    assert schema == {
        "type": "object",
        "properties": {"filePath": {"type": "string", "enum": [_ORDINARY_READ_PATH]}},
        "required": ["filePath"],
        "additionalProperties": False,
    }

    conflicting = _ordinary_tool_request(messages=[{"role": "user", "content": "Read once."}])
    conflicting_payload, _ = conflicting.provider_payload(None)
    conflicting_payload["response_format"] = {"type": "json_object"}
    conflicting_policy = _apply_single_ordinary_tool_required_once(conflicting_payload, "read")
    with pytest.raises(OpenWorkerAdapterError, match="COMPATIBILITY_CONFLICT"):
        _apply_vllm_json_schema_named_tool_compatibility(conflicting_payload, conflicting_policy)


def test_vllm_json_schema_stream_is_validated_then_delivered_as_one_read() -> None:
    native_id = "chatcmpl-native-json-schema-1"
    source = iter(
        [
            (
                b"data: "
                + json.dumps(
                    {
                        "id": native_id,
                        "choices": [
                            {
                                "delta": {"content": '{"filePath":'},
                                "finish_reason": None,
                            }
                        ],
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n\n"
            ),
            (
                b"data: "
                + json.dumps(
                    {
                        "id": native_id,
                        "choices": [
                            {
                                "delta": {"content": '"/openworker/runtime/opencode.json"}'},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 11, "completion_tokens": 4},
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n\n"
            ),
            b"data: [DONE]\n\n",
        ]
    )

    delivered = b"".join(_vllm_json_schema_named_tool_chunks(source))

    events = [
        json.loads(line[5:])
        for line in delivered.decode().splitlines()
        if line.startswith("data: {")
    ]
    call = events[0]["choices"][0]["delta"]["tool_calls"][0]
    assert call["function"] == {
        "name": "read",
        "arguments": '{"filePath":"/openworker/runtime/opencode.json"}',
    }
    assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert events[-1]["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 4,
        "total_tokens": 15,
    }
    assert delivered.endswith(b"data: [DONE]\n\n")


def test_vllm_json_schema_stream_rejects_wrong_arguments_after_native_terminal() -> None:
    native_id = "chatcmpl-native-json-schema-invalid"
    source = iter(
        [
            (
                b"data: "
                + json.dumps(
                    {
                        "id": native_id,
                        "choices": [
                            {
                                "delta": {"content": '{"filePath":"/wrong"}'},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                    },
                    separators=(",", ":"),
                ).encode()
                + b"\n\n"
            ),
            b"data: [DONE]\n\n",
        ]
    )

    with pytest.raises(
        OrdinaryToolCompatibilityError,
        match="PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID",
    ):
        b"".join(_vllm_json_schema_named_tool_chunks(source))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_calls", []),
        ("function_call", {"name": "read", "arguments": "{}"}),
    ],
)
def test_vllm_json_schema_stream_rejects_native_tool_fields(field: str, value: object) -> None:
    delta: dict[str, object] = {
        "content": '{"filePath":"/openworker/runtime/opencode.json"}',
        field: value,
    }
    source = iter(
        [
            b"data: "
            + json.dumps(
                {
                    "id": "chatcmpl-native-tool-field",
                    "choices": [{"delta": delta, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                },
                separators=(",", ":"),
            ).encode()
            + b"\n\n",
            b"data: [DONE]\n\n",
        ]
    )

    with pytest.raises(
        OrdinaryToolCompatibilityError,
        match="PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID",
    ):
        b"".join(_vllm_json_schema_named_tool_chunks(source))


@pytest.mark.parametrize(
    "choices",
    [
        [
            {"delta": {"content": "{}"}, "finish_reason": None},
            {"delta": {"content": "{}"}, "finish_reason": "stop"},
        ],
        [{"delta": {"content": 7}, "finish_reason": "stop"}],
        [{"delta": {"unexpected": "value"}, "finish_reason": "stop"}],
    ],
)
def test_vllm_json_schema_stream_rejects_non_single_or_abnormal_delta(
    choices: list[object],
) -> None:
    source = iter(
        [
            b"data: "
            + json.dumps(
                {
                    "id": "chatcmpl-native-abnormal-delta",
                    "choices": choices,
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                },
                separators=(",", ":"),
            ).encode()
            + b"\n\n",
            b"data: [DONE]\n\n",
        ]
    )

    with pytest.raises(
        OrdinaryToolCompatibilityError,
        match="PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID",
    ):
        b"".join(_vllm_json_schema_named_tool_chunks(source))


def test_ordinary_read_result_stays_no_memory_and_invokes_provider_once(
    tmp_path: Path,
) -> None:
    class OrdinaryTransport:
        name = "json"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            call_number = len(self.requests)
            call_id = "call_synthetic_read_1"
            message = (
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "read",
                                "arguments": '{"filePath":"/synthetic/marker"}',
                            },
                        }
                    ],
                }
                if call_number == 1
                else {"role": "assistant", "content": "done"}
            )
            return NativeProviderResponse(
                native_request_id=f"native-ordinary-{call_number}",
                prompt_tokens=2,
                completion_tokens=1,
                finish_reason="tool_calls" if call_number == 1 else "stop",
                payload={
                    "id": f"native-ordinary-{call_number}",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": ("tool_calls" if call_number == 1 else "stop"),
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                },
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="none",
        single_ordinary_tool_required_once="read",
    )
    transport = OrdinaryTransport()
    adapter.transport = transport
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_ordinary-1"],
            "X-MiLAi-Task-Operation": ["msg_ordinary-1"],
        }
    )
    try:
        first, first_route = adapter.complete(
            _ordinary_tool_request(messages=[{"role": "user", "content": "Read the marker once."}]),
            metadata,
        )
        assert isinstance(first, dict)
        assert first_route == "PROVIDER_NO_MEMORY"
        assert len(transport.requests) == 1

        call_id = first["choices"][0]["message"]["tool_calls"][0]["id"]
        calls_before_result = len(transport.requests)
        second, second_route = adapter.complete(
            _ordinary_tool_request(
                messages=[
                    {"role": "user", "content": "Read the marker once."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": "read",
                                    "arguments": '{"filePath":"/synthetic/marker"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(
                            {
                                "status": "READY",
                                "items": [],
                                "open_issue_ids": [],
                                "private_result": "ordinary body",
                            }
                        ),
                    },
                ]
            ),
            metadata,
        )

        assert isinstance(second, dict)
        assert second_route == "PROVIDER_NO_MEMORY"
        assert len(transport.requests) - calls_before_result == 1
        assert transport.requests[1].payload["tool_choice"] == "none"  # type: ignore[attr-defined]
        assert adapter.host_mcp is None
        reservations = [row for row in adapter.gateway.read_ledger() if row["event"] == "RESERVED"]
        assert [row["logical_request_id"] for row in reservations] == [
            "host-adapter-test-run-ow-01",
            "host-adapter-test-run-ow-02",
        ]
        provider_answers = [
            json.loads(line)
            for line in adapter.trace.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "PROVIDER_ANSWER"
        ]
        assert [row["mcp_calls"] for row in provider_answers] == [0, 0]
        assert [row["memory_status"] for row in provider_answers] == [
            "NO_MEMORY",
            "NO_MEMORY",
        ]
        assert "ordinary body" not in adapter.trace.read_text(encoding="utf-8")
        replacement = OpenWorkerProviderAdapter(
            tmp_path / "manifest.json",
            tmp_path / "provider-ledger.jsonl",
            tmp_path / "replacement-host-trace.jsonl",
            memory_mode="none",
            single_ordinary_tool_required_once="read",
        )
        try:
            assert replacement._logical_request_id() == "host-adapter-test-run-ow-03"
            host_snapshot = replacement.task_registry.snapshot()
            native_snapshot = replacement.native_task_registry.snapshot()
            assert host_snapshot.registry_revision == 0
            assert host_snapshot.tasks == {}
            assert native_snapshot.process_generation == 0
            assert native_snapshot.session_task_ids == ()
            assert native_snapshot.seen_operations == ()
        finally:
            replacement.close()
    finally:
        adapter.close()


def test_invalid_ordinary_result_never_consumes_provider_sequence_or_calls_provider(
    tmp_path: Path,
) -> None:
    class RejectTransport:
        name = "json"
        calls = 0

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del request, capability
            self.calls += 1
            raise AssertionError("invalid ordinary state reached provider")

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="none",
        single_ordinary_tool_required_once="read",
    )
    transport = RejectTransport()
    adapter.transport = transport
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_ordinary-invalid"],
            "X-MiLAi-Task-Operation": ["msg_ordinary-invalid"],
        }
    )
    invalid_messages = (
        [
            {"role": "user", "content": "Read once."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-wrong", "content": "result"},
        ],
        [
            {"role": "user", "content": "Read once."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                    {
                        "id": "call-read-2",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-read-1", "content": "result"},
        ],
        [
            {"role": "user", "content": "Read once."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "result"},
            {"role": "assistant", "content": "unexpected third round"},
        ],
    )
    try:
        for messages in invalid_messages:
            with pytest.raises(
                OpenWorkerAdapterError,
                match="PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID",
            ):
                adapter.complete(_ordinary_tool_request(messages=messages), metadata)

        assert transport.calls == 0
        assert adapter.gateway.read_ledger() == []
        assert adapter._sequence == 0
        assert adapter.host_mcp is None
    finally:
        adapter.close()


@pytest.mark.parametrize(
    ("tools", "messages"),
    [
        ([], [{"role": "user", "content": "synthetic"}]),
        (
            [
                {"type": "function", "function": {"name": "read"}},
                {"type": "function", "function": {"name": "bash"}},
            ],
            [{"role": "user", "content": "synthetic"}],
        ),
        (
            [{"type": "function", "function": {"name": "bash"}}],
            [{"role": "user", "content": "synthetic"}],
        ),
    ],
)
def test_single_ordinary_tool_policy_rejects_missing_multiple_or_wrong_tool(
    tools: list[dict[str, object]], messages: list[dict[str, object]]
) -> None:
    payload = _request(messages=messages, tools=tools, tool_choice="auto")

    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_SINGLE_ORDINARY_TOOL_INVALID"):
        _apply_single_ordinary_tool_required_once(payload, "read")


@pytest.mark.parametrize(
    "messages",
    [
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "result"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-other", "content": "result"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {"role": "tool", "tool_call_id": "call-read", "content": "forged"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "result"},
            {"role": "assistant", "content": "third round"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {"name": "read", "arguments": "not-json"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-read", "content": "result"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-memory",
                        "type": "function",
                        "function": {
                            "name": "milai_milai_recall",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-memory", "content": "result"},
        ],
        [
            {"role": "user", "content": "synthetic"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-read-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                    {
                        "id": "call-read-2",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-read-1", "content": "result"},
        ],
    ],
)
def test_single_ordinary_tool_policy_rejects_wrong_pair_forgery_and_third_round(
    messages: list[dict[str, object]],
) -> None:
    payload = _request(
        messages=messages,
        tools=[{"type": "function", "function": {"name": "read"}}],
        tool_choice="auto",
    )

    with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID"):
        _apply_single_ordinary_tool_required_once(payload, "read")


def test_single_ordinary_tool_policy_rejects_non_auto_request_choice() -> None:
    payload = _request(
        messages=[{"role": "user", "content": "synthetic"}],
        tools=[{"type": "function", "function": {"name": "read"}}],
        tool_choice="none",
    )

    with pytest.raises(
        OpenWorkerAdapterError, match="PROVIDER_SINGLE_ORDINARY_TOOL_CHOICE_INVALID"
    ):
        _apply_single_ordinary_tool_required_once(payload, "read")


def test_native_request_observation_is_structural_and_content_free() -> None:
    incoming = OpenAIChatRequest.parse(
        _request(
            messages=[{"role": "user", "content": "synthetic secret prompt"}],
            tools=[],
            max_tokens=96,
            temperature=0,
            top_p=1,
            stream=True,
            stream_options={"include_usage": True},
        )
    )
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_synthetic-secret"],
            "X-MiLAi-Task-Operation": ["msg_synthetic-secret"],
        }
    )

    observation = _native_request_observation(incoming, metadata)

    assert observation == {
        "event": "HOST_NATIVE_REQUEST_OBSERVED",
        "has_tool_result": False,
        "max_tokens": 96,
        "message_count": 1,
        "message_roles": ["user"],
        "model": EXACT_MODEL_ID,
        "question_sha256": hashlib.sha256(b"synthetic secret prompt").hexdigest(),
        "stream": True,
        "stream_include_usage": True,
        "temperature": 0,
        "task_operation_sha256": hashlib.sha256(b"msg_synthetic-secret").hexdigest(),
        "task_session_sha256": hashlib.sha256(b"ses_synthetic-secret").hexdigest(),
        "top_p": 1,
        "tool_count": 0,
    }
    durable = json.dumps(observation, sort_keys=True)
    assert "synthetic secret prompt" not in durable
    assert "ses_synthetic-secret" not in durable
    assert "msg_synthetic-secret" not in durable


def test_native_request_observation_reports_nonstream_without_usage() -> None:
    incoming = OpenAIChatRequest.parse(
        _request(messages=[{"role": "user", "content": "synthetic"}], tools=[])
    )
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses_synthetic-2"],
            "X-MiLAi-Task-Operation": ["msg_synthetic-2"],
        }
    )

    observation = _native_request_observation(incoming, metadata)

    assert observation["stream"] is False
    assert observation["stream_include_usage"] is False


def test_direct_memory_tool_choice_is_rejected_before_provider() -> None:
    for tool_choice in (
        {"type": "function", "function": {"name": "milai_recall"}},
        "milai_recall",
        "openworker_milai_recall",
        {"type": "function", "function": {"name": "milai_memory_resolve"}},
        "milai_memory_resolve",
        "openworker_milai_memory_resolve",
    ):
        parsed = OpenAIChatRequest.parse(_request(tool_choice=tool_choice))

        with pytest.raises(OpenWorkerAdapterError, match="PROVIDER_MEMORY_TOOL_VISIBLE"):
            parsed.provider_payload(None)


def test_access_outcome_provider_barrier_blocks_governance_before_provider() -> None:
    prepared = TaskPreparedContext(
        route="L0",
        outcome=AccessOutcome(
            status="GOVERNANCE_BLOCKED",
            execution_action="ABSTAIN",
            provider_execution="PROHIBITED",
            terminal_stage="GATE",
            context_digest=None,
            canonical_position=7,
            reason_code="OPEN_ISSUE",
            trace_id="trace-governance-blocked",
        ),
        delta=None,
        validation_token=None,
        trace_pointer="trace-governance-blocked",
        usage={"prepare_context_calls": 1},
    )

    blocked = _prepared_prefetch(prepared)

    assert blocked.status == "UNAVAILABLE"
    assert blocked.abstention_reason == "OPEN_ISSUE"


def test_transport_failure_renders_frozen_typed_terminal_without_provider_usage() -> None:
    payload = {
        "model": EXACT_MODEL_ID,
        "messages": [{"role": "user", "content": "synthetic private prompt"}],
    }

    outcome = _transport_unavailable_outcome(payload, "MCP_DEADLINE_EXCEEDED")
    completion = _memory_terminal_completion(payload, outcome)
    answer = json.loads(completion["choices"][0]["message"]["content"])

    assert outcome.to_api() == {
        "status": "MEMORY_REQUIRED_BUT_UNAVAILABLE",
        "execution_action": "RETRY",
        "provider_execution": "PROHIBITED",
        "terminal_stage": "TRANSPORT",
        "context_digest": None,
        "canonical_position": None,
        "reason_code": "MCP_DEADLINE_EXCEEDED",
        "trace_id": "host-mcp-transport:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    assert answer == {
        "answer": "UNKNOWN",
        "status": "MEMORY_REQUIRED_BUT_UNAVAILABLE",
        "memory_used": False,
        "memory_outcome": "MEMORY_REQUIRED_BUT_UNAVAILABLE",
        "execution_action": "RETRY",
        "provider_execution": "PROHIBITED",
        "terminal_stage": "TRANSPORT",
        "reason_code": "MCP_DEADLINE_EXCEEDED",
        "trace_id": outcome.trace_id,
    }
    assert completion["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert "synthetic private prompt" not in json.dumps(outcome.to_api(), sort_keys=True)


@pytest.mark.parametrize(
    ("runtime_status", "availability", "open_issue_ids", "abstention_reason"),
    [
        ("DENIED", "UNAVAILABLE", [], "ACCESS_DENIED"),
        ("ABSTAINED", "AVAILABLE", ["issue-query-first-contested"], "OPEN_ISSUE"),
    ],
)
def test_query_first_denial_or_open_issue_prohibits_provider_execution(
    tmp_path: Path,
    runtime_status: str,
    availability: str,
    open_issue_ids: list[str],
    abstention_reason: str,
) -> None:
    class QueryFirstMcp:
        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            del query, previous_context_id
            return {
                "schema_version": "access-outcome-v0.1",
                "status": runtime_status,
                "availability": availability,
                "items": [],
                "open_issue_ids": open_issue_ids,
                "degraded_components": [],
                "abstention_reason": abstention_reason,
                "canonical_position": 19,
                "trace_id": "trace-query-first-insufficient",
                "access_trace": {
                    "planned_stage": "SEARCH",
                    "terminal_stage": "SUFFICIENCY",
                    "spans": {"mcp_handler_ms": 2.0, "runtime_client_ms": 1.0},
                },
                "host_transport": {"uds_roundtrip_ms": 3.0},
            }

        def close(self) -> None:
            return None

    class ProviderMustNotRun:
        name = "json"

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del request, capability
            self.calls += 1
            raise AssertionError("provider must not run for insufficient memory")

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
    )
    fake_mcp = QueryFirstMcp()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = fake_mcp  # type: ignore[assignment]
    transport = ProviderMustNotRun()
    adapter.transport = transport
    incoming = OpenAIChatRequest.parse(_request())
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses-query-first-insufficient"],
            "X-MiLAi-Task-Operation": ["msg-query-first-insufficient"],
        }
    )
    try:
        completion, route = adapter.complete(incoming, metadata)
        answer = json.loads(completion["choices"][0]["message"]["content"])

        assert route == f"HOST_{answer['status']}"
        assert answer["status"] in {
            "MEMORY_INSUFFICIENT",
            "MEMORY_REQUIRED_BUT_UNAVAILABLE",
        }
        assert answer["provider_execution"] == "PROHIBITED"
        assert answer["reason_code"] == abstention_reason
        assert transport.calls == 0
    finally:
        adapter.close()


@pytest.mark.parametrize(
    ("question", "provider_expected"),
    [
        ("Please note that my marker is cedar.", True),
        ("Recall my marker from memory.", False),
    ],
)
def test_query_first_empty_store_bootstraps_and_settles_exact_exchange(
    tmp_path: Path,
    question: str,
    provider_expected: bool,
) -> None:
    class EmptyReader:
        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            del query, previous_context_id
            return {
                "schema_version": "access-outcome-v0.1",
                "status": "ABSENT",
                "availability": "AVAILABLE",
                "items": [],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": "NO_MEMORY_CONTROL",
                "canonical_position": 0,
                "trace_id": "trace-empty-bootstrap",
                "access_trace": {
                    "planned_stage": "SEARCH",
                    "terminal_stage": "SUFFICIENCY",
                    "spans": {"mcp_handler_ms": 2.0, "runtime_client_ms": 1.0},
                },
                "host_transport": {"uds_roundtrip_ms": 3.0},
            }

        def close(self) -> None:
            return None

    class Submitter:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def capture_evidence(self, payload):  # type: ignore[no-untyped-def]
            self.calls.append(dict(payload))
            sequence = len(self.calls)
            return {
                "evidence_id": f"evidence-bootstrap-{sequence}",
                "outbox_id": f"outbox-bootstrap-{sequence}",
                "replayed": False,
            }

        def create_proposal(self, payload):  # type: ignore[no-untyped-def]
            raise AssertionError(f"settlement cannot create canonical proposal: {payload}")

    class ProviderTransport:
        name = "json"

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del request, capability
            self.calls += 1
            return NativeProviderResponse(
                native_request_id="native-bootstrap-answer",
                prompt_tokens=5,
                completion_tokens=2,
                finish_reason="stop",
                payload={
                    "id": "native-bootstrap-answer",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Noted."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                        "total_tokens": 7,
                    },
                },
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        submitter_socket=SOCKET_ROOT / "submitter.sock",
        memory_subject_id="synthetic-user",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
    )
    reader = EmptyReader()
    submitter = Submitter()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = reader  # type: ignore[assignment]
    adapter.memory_facade = OpenWorkerMemoryFacade(
        reader,
        submitter=submitter,
        subject_id="synthetic-user",
        permission_snapshot={"readable": True, "project_ids": ["orchid-release"]},
    )
    transport = ProviderTransport()
    adapter.transport = transport
    incoming = OpenAIChatRequest.parse(
        _request(messages=[{"role": "user", "content": question}], tools=[], response_format=None)
    )
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses-empty-bootstrap"],
            "X-MiLAi-Task-Operation": ["msg-bootstrap-user"],
            "X-MiLAi-Assistant-Message": ["msg-bootstrap-assistant"],
            "X-MiLAi-User-Observed-At": ["2026-09-03T01:00:00.000Z"],
            "X-MiLAi-Assistant-Observed-At": ["2026-09-03T01:00:00.010Z"],
        },
        require_settlement=True,
    )
    try:
        completion, route = adapter.complete(incoming, metadata)

        assert isinstance(completion, dict)
        assert transport.calls == int(provider_expected)
        assert route == ("PROVIDER_NO_MEMORY" if provider_expected else "HOST_MEMORY_INSUFFICIENT")
        assert [call["speaker"] for call in submitter.calls] == ["user", "assistant"]
        assert submitter.calls[0]["content"] == question
        assert submitter.calls[1]["source_ref"].endswith(
            "/message/msg-bootstrap-assistant"
        )
        assert decode_memory_support_lineage(str(submitter.calls[1]["source_ref"])) is None
    finally:
        adapter.close()


@pytest.mark.parametrize("runtime_status", ["ABSTAINED", "PARTIAL"])
def test_query_first_soft_partial_context_reaches_provider_with_typed_status(
    tmp_path: Path,
    runtime_status: str,
) -> None:
    partial_context = (
        "MEMORY_CONTEXT_V0_2\n"
        "MEMORY_STATUS=PARTIAL\n"
        "SUFFICIENCY_STATUS=UNSATISFIED\n"
        "SUPPORTED_EVIDENCE=one grounded member\n"
        "COMPLETENESS=NOT_ESTABLISHED"
    )

    class QueryFirstMcp:
        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            del query, previous_context_id
            return {
                "schema_version": "access-outcome-v0.1",
                "status": runtime_status,
                "availability": "AVAILABLE",
                "items": [],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": "SUFFICIENCY_UNSATISFIED",
                "canonical_position": 20,
                "trace_id": "trace-query-first-soft-partial",
                "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
                "memory_context": {
                    "text": partial_context,
                    "selected_evidence_ids": ["evidence-soft-partial"],
                    "claim_versions": [],
                },
                "access_trace": {
                    "planned_stage": "SEARCH",
                    "terminal_stage": "SUFFICIENCY",
                    "spans": {"mcp_handler_ms": 2.0, "runtime_client_ms": 1.0},
                },
                "host_transport": {"uds_roundtrip_ms": 3.0},
            }

        def close(self) -> None:
            return None

    class ProviderTransport:
        name = "json"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            return NativeProviderResponse(
                native_request_id="native-soft-partial",
                prompt_tokens=5,
                completion_tokens=3,
                finish_reason="stop",
                payload={
                    "id": "native-soft-partial",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "One member is supported; completeness is unknown.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 3,
                        "total_tokens": 8,
                    },
                },
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
    )
    fake_mcp = QueryFirstMcp()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = fake_mcp  # type: ignore[assignment]
    transport = ProviderTransport()
    adapter.transport = transport
    incoming = OpenAIChatRequest.parse(_request())
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses-query-first-soft-partial"],
            "X-MiLAi-Task-Operation": ["msg-query-first-soft-partial"],
        }
    )
    try:
        completion, route = adapter.complete(incoming, metadata)

        assert route == "PROVIDER_AVAILABLE"
        assert completion["choices"][0]["message"]["content"] == (
            "One member is supported; completeness is unknown."
        )
        assert len(transport.requests) == 1
        provider_request = transport.requests[0]
        system_content = provider_request.payload["messages"][0]["content"]  # type: ignore[attr-defined]
        assert isinstance(system_content, str)
        assert system_content.count(_MEMORY_READING_POLICY) == 1
        assert partial_context in system_content
        assert system_content.index(_MEMORY_READING_POLICY) < system_content.index(
            "MILAI_CONTEXT_BEGIN"
        ) < system_content.index(partial_context)

        rows = [
            json.loads(line)
            for line in adapter.trace.read_text(encoding="utf-8").splitlines()
        ]
        prepare = next(
            row for row in rows if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        )
        assert prepare["memory_status"] == "AVAILABLE"
        assert prepare["current_state_status"] == runtime_status
        assert any(row.get("event") == "PROVIDER_ANSWER" for row in rows)
    finally:
        adapter.close()


def test_memory_insufficient_outcome_uses_frozen_access_contract() -> None:
    context = PrefetchContext.no_memory()
    outcome = _memory_insufficient_outcome(
        {"model": EXACT_MODEL_ID},
        {
            "status": "ABSENT",
            "canonical_position": 23,
            "trace_id": "trace-absent",
        },
        context,
    )

    assert outcome.to_api() == {
        "status": "MEMORY_INSUFFICIENT",
        "execution_action": "ASK_USER",
        "provider_execution": "PROHIBITED",
        "terminal_stage": "SUFFICIENCY",
        "context_digest": None,
        "canonical_position": 23,
        "reason_code": "NO_MEMORY_CONTROL",
        "trace_id": "trace-absent",
    }


def test_unchanged_context_without_retained_host_slot_fails_closed() -> None:
    from milai_openworker_mcp import host_adapter

    retained = PrefetchContext.no_memory()
    prepared = TaskPreparedContext(
        route="CACHE",
        outcome=AccessOutcome(
            status="CONTEXT_READY_CURRENT",
            execution_action="CONTINUE",
            provider_execution="ALLOWED",
            terminal_stage="CACHE",
            context_digest=retained.context_sha256,
            canonical_position=8,
            reason_code=None,
            trace_id="trace-cache-hit",
        ),
        delta=None,
        validation_token=_synthetic_run_token(),
        trace_pointer="trace-cache-hit",
        usage={"prepare_context_calls": 1},
    )
    resolve = host_adapter._resolve_prepared_context

    with pytest.raises(OpenWorkerAdapterError, match="retained host slot is absent"):
        resolve(prepared, None)
    assert resolve(prepared, retained) is retained
    mismatched = TaskPreparedContext(
        route=prepared.route,
        outcome=AccessOutcome(
            status="CONTEXT_READY_CURRENT",
            execution_action="CONTINUE",
            provider_execution="ALLOWED",
            terminal_stage="CACHE",
            context_digest="a" * 64,
            canonical_position=8,
            reason_code=None,
            trace_id="trace-cache-hit-mismatch",
        ),
        delta=None,
        validation_token=prepared.validation_token,
        trace_pointer="trace-cache-hit-mismatch",
        usage=prepared.usage,
    )
    with pytest.raises(OpenWorkerAdapterError, match="digest mismatch"):
        resolve(mismatched, retained)


def test_query_first_passes_only_receipt_locator_on_native_continuation_turn(
    tmp_path: Path,
) -> None:
    class QueryFirstMcp:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            self.calls.append((query, previous_context_id))
            return {
                "schema_version": "access-outcome-v0.1",
                "status": "HIT",
                "availability": "AVAILABLE",
                "items": [
                    {
                        "claim_id": "claim-query-first",
                        "subject_id": "orchid-release",
                        "predicate": "release.target",
                        "claim_type": "PROJECT_STATE",
                        "payload": {"target": "synthetic-candidate"},
                        "authority": "INFORMATIONAL",
                        "epistemic_status": "ACCEPTED",
                    }
                ],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": None,
                "trace_id": "trace-query-first-1",
                "receipt_reused": previous_context_id is not None,
                "context_receipt": {
                    "context_capsule_id": "11111111-1111-4111-8111-111111111111"
                },
                "access_trace": {
                    "planned_stage": "SEARCH",
                    "terminal_stage": (
                        "REUSE" if previous_context_id is not None else "FTS"
                    ),
                    "spans": {"mcp_handler_ms": 2.0, "runtime_client_ms": 1.0},
                },
                "host_transport": {"uds_roundtrip_ms": 3.0},
            }

        def close(self) -> None:
            return None

    class ProviderTransport:
        name = "json"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            sequence = len(self.requests)
            return NativeProviderResponse(
                native_request_id=f"native-query-first-{sequence}",
                prompt_tokens=2,
                completion_tokens=1,
                finish_reason="stop",
                payload={
                    "id": f"native-query-first-{sequence}",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "done"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                },
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
    )
    fake_mcp = QueryFirstMcp()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = fake_mcp  # type: ignore[assignment]
    transport = ProviderTransport()
    adapter.transport = transport
    incoming = OpenAIChatRequest.parse(
        _request(
            tools=[
                {"type": "function", "function": {"name": "milai_memory_resolve"}},
                {"type": "function", "function": {"name": "milai_milai_recall"}},
            ]
        )
    )
    try:
        for operation in ("msg-query-first-1", "msg-query-first-2"):
            metadata = _task_metadata_from_values(
                {
                    "X-MiLAi-Host-Instance": [
                        "123e4567-e89b-12d3-a456-426614174000"
                    ],
                    "X-MiLAi-Task-Session": ["ses-query-first"],
                    "X-MiLAi-Task-Operation": [operation],
                }
            )
            _completion, route = adapter.complete(incoming, metadata)
            assert route == "PROVIDER_AVAILABLE"

        assert fake_mcp.calls == [
            ("What is current?", None),
            (
                "What is current?",
                "11111111-1111-4111-8111-111111111111",
            ),
        ]
        assert len(transport.requests) == 2
        assert all(not request.payload.get("tools") for request in transport.requests)  # type: ignore[attr-defined]
        rows = [
            json.loads(line)
            for line in adapter.trace.read_text(encoding="utf-8").splitlines()
        ]
        prepares = [
            row for row in rows if row.get("event") == "HOST_MCP_PREPARE_CONTEXT"
        ]
        assert len(prepares) == 2
        assert [row["fresh_resolve"] for row in prepares] == [True, False]
        assert all(row["mcp_tool"] == "milai_memory_resolve" for row in prepares)
        assert all(row["route"] == "SEARCH" for row in prepares)
        assert all(row["prepare_status"] == "READY" for row in prepares)
        assert all(row["current_state_status"] == "HIT" for row in prepares)
        assert [row["cache_validation_outcome"] for row in prepares] == [
            None,
            "REUSED",
        ]
        answers = [row for row in rows if row.get("event") == "PROVIDER_ANSWER"]
        assert [row["mcp_calls"] for row in answers] == [1, 1]
        assert all(row["ordinary_tool_count"] == 0 for row in answers)
    finally:
        adapter.close()


def test_startup_policy_binds_reader_lite_scope_and_exact_three_state_keys(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "milai-mcp"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o500)
    policy = {
        "schema": "milai.openworker.mcp-broker-policy.v1",
        "profile": "reader-lite",
        "socket_path": str(SOCKET_ROOT / "reader-lite.sock"),
        "socket_mode": "0600",
        "allowed_peer_uids": [os.geteuid()],
        "mcp_executable": str(executable),
        "mcp_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "base_url": "http://127.0.0.1:18080",
        "scope": {"project_ids": ["orchid-release"]},
        "required_authority": "INFORMATIONAL",
        "consistency_floor": "CANONICAL_REQUIRED",
        "max_limit": 3,
        "max_connections": 2,
        "child_shutdown_seconds": 2,
    }
    policy_path = tmp_path / "broker-policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    policy_path.chmod(0o600)

    startup = _load_startup_task_policy(policy_path, FIXTURE)

    assert startup.profile == "reader-lite"
    assert startup.scope == {"project_ids": ["orchid-release"]}
    assert startup.required_authority == "INFORMATIONAL"
    assert startup.consistency_floor == "CANONICAL_REQUIRED"
    assert [key.predicate for key in startup.state_keys] == [
        "release.target",
        "release.database",
        "release.decision",
    ]

    policy["max_limit"] = 50
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    wide_startup = _load_startup_task_policy(policy_path, FIXTURE)
    assert wide_startup.max_limit == 50

    policy["profile"] = "submitter"
    policy["socket_path"] = str(SOCKET_ROOT / "submitter.sock")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(OpenWorkerAdapterError, match="HOST_STARTUP_POLICY_INVALID"):
        _load_startup_task_policy(policy_path, FIXTURE)

    policy["profile"] = "reader-lite"
    policy["socket_path"] = str(SOCKET_ROOT / "reader-lite.sock")
    policy["scope"] = {"project_ids": ["orchid-release", "foreign-project"]}
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(OpenWorkerAdapterError, match="HOST_STARTUP_POLICY_INVALID"):
        _load_startup_task_policy(policy_path, FIXTURE)

    policy["scope"] = {"project_ids": ["orchid-release"]}
    policy["required_authority"] = "ACTION_SAFE"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(OpenWorkerAdapterError, match="HOST_STARTUP_POLICY_INVALID"):
        _load_startup_task_policy(policy_path, FIXTURE)


def test_runtime_planned_route_is_preserved_in_host_trace() -> None:
    runtime_trace = {
        "need_signature_id": "need-synthetic",
        "requested_route": "CACHE",
        "planned_route": "CACHE",
        "validated_route": "CACHE",
        "attempted_routes": ["CACHE", "L0"],
        "terminal_route": "L0",
        "result": "HIT",
        "policy_override_reason": None,
        "fallback_reason": "CACHE_MISS",
        "next_route_recommended": None,
        "route_trace_complete": True,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "reranker_calls": 0,
        "exact_calls": 1,
        "fts_calls": 0,
        "l0_calls": 1,
    }
    trace = _shadow_route_trace(
        requested_route="CACHE",
        actual_route="L0",
        host_terminal=False,
        runtime_trace=runtime_trace,
    )

    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"

    missing = _shadow_route_trace(
        requested_route="CACHE",
        actual_route="L0",
        host_terminal=False,
        runtime_trace={
            key: value for key, value in runtime_trace.items() if key != "planned_route"
        },
    )
    conflicting = _shadow_route_trace(
        requested_route="CACHE",
        actual_route="L0",
        host_terminal=False,
        runtime_trace={**runtime_trace, "planned_route": "L0"},
    )
    assert missing["route_trace_complete"] is False
    assert conflicting["route_trace_complete"] is False


def test_http_boundary_authenticates_then_validates_metadata_then_parses_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def complete(self, request, metadata, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return (
            {
                "id": "native-synthetic-0001",
                "object": "chat.completion",
                "model": EXACT_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            "PROVIDER_NO_MEMORY",
        )

    monkeypatch.setattr(OpenWorkerProviderAdapter, "complete", complete)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _synthetic_run_token()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=b"not-json")
        response = connection.getresponse()
        assert response.status == 401
        assert json.loads(response.read())["error"]["reason_code"] == "AUTHENTICATION_REQUIRED"
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"not-json",
            headers={"Authorization": "Bearer synthetic-run-token"},
        )
        response = connection.getresponse()
        assert response.status == 400
        assert json.loads(response.read())["error"]["reason_code"] == "TASK_METADATA_INVALID"
        connection.close()

        body = json.dumps(_request()).encode()
        headers = {
            "Authorization": "Bearer synthetic-run-token",
            "Content-Type": "application/json",
            "X-MiLAi-Host-Instance": "123e4567-e89b-12d3-a456-426614174000",
            "X-MiLAi-Task-Session": "ses_synthetic-1",
            "X-MiLAi-Task-Operation": "msg_synthetic-1",
        }
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["id"] == "native-synthetic-0001"
        connection.close()
        assert calls == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_boundary_records_typed_terminal_before_a_replayed_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def complete(self, request, metadata, **kwargs):  # type: ignore[no-untyped-def]
        del self, request, metadata, kwargs
        raise BudgetError("request max_tokens exceeds its reservation")

    monkeypatch.setattr(OpenWorkerProviderAdapter, "complete", complete)
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _synthetic_run_token()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            _request(messages=[{"role": "user", "content": "secret prompt"}])
        ).encode()
        headers = {
            "Authorization": "Bearer synthetic-run-token",
            "Content-Type": "application/json",
            "X-MiLAi-Host-Instance": "123e4567-e89b-12d3-a456-426614174000",
            "X-MiLAi-Task-Session": "ses_synthetic-secret",
            "X-MiLAi-Task-Operation": "msg_synthetic-secret",
        }
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == 502
        response.read()
        connection.close()

        event = json.loads(adapter.trace.read_text(encoding="utf-8"))
        assert event == {
            "event": "HOST_INGRESS_TERMINAL",
            "exception_type": "BudgetError",
            "http_status": 502,
            "reason_code": "request max_tokens exceeds its reservation",
        }
        durable = adapter.trace.read_text(encoding="utf-8")
        assert "secret prompt" not in durable
        assert "synthetic-run-token" not in durable
        assert "ses_synthetic-secret" not in durable
        assert "msg_synthetic-secret" not in durable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (ProviderCallError("PROVIDER_HTTP_400"), 422),
        (
            OrdinaryToolCompatibilityError("PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"),
            422,
        ),
        (ProviderCallError("PROVIDER_HTTP_500"), 502),
        (ProviderCallError("PROVIDER_STREAM_FAILED"), 502),
    ],
)
def test_http_boundary_maps_only_deterministic_provider_failures_to_nonretryable_4xx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_status: int,
) -> None:
    def complete(self, request, metadata, **kwargs):  # type: ignore[no-untyped-def]
        del self, request, metadata, kwargs
        raise failure

    monkeypatch.setattr(OpenWorkerProviderAdapter, "complete", complete)
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _synthetic_run_token()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            _request(messages=[{"role": "user", "content": "private mapped failure"}])
        ).encode()
        headers = {
            "Authorization": "Bearer synthetic-run-token",
            "Content-Type": "application/json",
            "X-MiLAi-Host-Instance": "123e4567-e89b-12d3-a456-426614174000",
            "X-MiLAi-Task-Session": "ses_mapped-failure",
            "X-MiLAi-Task-Operation": "msg_mapped-failure",
        }
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == expected_status
        assert json.loads(response.read())["error"]["reason_code"] == str(failure)
        connection.close()

        event = json.loads(adapter.trace.read_text(encoding="utf-8"))
        assert event == {
            "event": "HOST_INGRESS_TERMINAL",
            "exception_type": type(failure).__name__,
            "http_status": expected_status,
            "reason_code": str(failure),
        }
        durable = adapter.trace.read_text(encoding="utf-8")
        assert "private mapped failure" not in durable
        assert "synthetic-run-token" not in durable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stream_first_chunk_failure_is_typed_502_before_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_chunks():  # type: ignore[no-untyped-def]
        raise ProviderCallError("PROVIDER_STREAM_FAILED")
        yield b"unreachable"  # pragma: no cover

    def complete(self, request, metadata, **kwargs):  # type: ignore[no-untyped-def]
        del self, request, metadata, kwargs
        return StreamingCompletion(failed_chunks()), "PROVIDER_NO_MEMORY"

    monkeypatch.setattr(OpenWorkerProviderAdapter, "complete", complete)
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _synthetic_run_token()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            _request(
                messages=[{"role": "user", "content": "private first frame prompt"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        ).encode()
        headers = {
            "Authorization": "Bearer synthetic-run-token",
            "Content-Type": "application/json",
            "X-MiLAi-Host-Instance": "123e4567-e89b-12d3-a456-426614174000",
            "X-MiLAi-Task-Session": "ses_stream-first-failure",
            "X-MiLAi-Task-Operation": "msg_stream-first-failure",
        }
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == 502
        assert json.loads(response.read())["error"]["reason_code"] == ("PROVIDER_STREAM_FAILED")
        connection.close()

        event = json.loads(adapter.trace.read_text(encoding="utf-8"))
        assert event == {
            "event": "HOST_INGRESS_TERMINAL",
            "exception_type": "ProviderCallError",
            "http_status": 502,
            "reason_code": "PROVIDER_STREAM_FAILED",
        }
        durable = adapter.trace.read_text(encoding="utf-8")
        assert "private first frame prompt" not in durable
        assert "synthetic-run-token" not in durable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stream_failure_after_headers_records_content_free_terminal_and_disconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_chunk = b"data: private-stream-content\n\n"

    def failed_chunks():  # type: ignore[no-untyped-def]
        yield private_chunk
        raise ProviderCallError("PROVIDER_STREAM_DONE_MISSING")

    def complete(self, request, metadata, **kwargs):  # type: ignore[no-untyped-def]
        del self, request, metadata, kwargs
        return StreamingCompletion(failed_chunks()), "PROVIDER_NO_MEMORY"

    monkeypatch.setattr(OpenWorkerProviderAdapter, "complete", complete)
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _synthetic_run_token()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            _request(
                messages=[{"role": "user", "content": "private midstream prompt"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        ).encode()
        headers = {
            "Authorization": "Bearer synthetic-run-token",
            "Content-Type": "application/json",
            "X-MiLAi-Host-Instance": "123e4567-e89b-12d3-a456-426614174000",
            "X-MiLAi-Task-Session": "ses_stream-mid-failure",
            "X-MiLAi-Task-Operation": "msg_stream-mid-failure",
        }
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == private_chunk
        connection.close()

        event = json.loads(adapter.trace.read_text(encoding="utf-8"))
        assert event == {
            "event": "HOST_STREAM_TERMINAL",
            "exception_type": "ProviderCallError",
            "http_status": 200,
            "reason_code": "PROVIDER_STREAM_DONE_MISSING",
            "response_headers_committed": True,
            "status": "FAILED",
        }
        durable = adapter.trace.read_text(encoding="utf-8")
        assert "private-stream-content" not in durable
        assert "private midstream prompt" not in durable
        assert "synthetic-run-token" not in durable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("evidence_use_mode", ["grounded", "ledger"])
def test_grounded_query_first_settles_exact_native_exchange_before_delivery(
    tmp_path: Path,
    stream: bool,
    evidence_use_mode: str,
) -> None:
    context_text = (
        "MEMORY_CONTEXT_V0_2\n"
        "MEMORY_STATUS=HIT\n"
        "[E1 source=prior-user] The user's marker is cedar."
    )

    class Reader:
        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            del query, previous_context_id
            return {
                "schema_version": "access-outcome-v0.1",
                "status": "HIT",
                "availability": "AVAILABLE",
                "items": [],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": None,
                "canonical_position": 30,
                "trace_id": "trace-grounded-settlement",
                "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
                "memory_context": {
                    "text": context_text,
                    "selected_evidence_ids": ["evidence-prior"],
                    "claim_versions": [],
                },
                "context_receipt": {
                    "context_capsule_id": "context-grounded-1",
                    "receipt_mapping": [
                        {
                            "alias": "E1",
                            "evidence_ids": ["evidence-prior"],
                            "source_turn_refs": ["prior-user"],
                            "claim_versions": [],
                        }
                    ],
                },
                "access_trace": {"planned_stage": "SEARCH", "spans": {}},
                "host_transport": {"uds_roundtrip_ms": 1.0},
            }

        def close(self) -> None:
            return None

    class Submitter:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def capture_evidence(self, payload):  # type: ignore[no-untyped-def]
            self.calls.append(dict(payload))
            sequence = len(self.calls)
            return {
                "evidence_id": f"evidence-new-{sequence}",
                "outbox_id": f"outbox-new-{sequence}",
                "replayed": False,
            }

        def create_proposal(self, payload):  # type: ignore[no-untyped-def]
            raise AssertionError(f"settlement cannot create canonical proposal: {payload}")

    grounded = {
        "disposition": "ANSWERED",
        "answer_text": "Your marker is cedar.",
        "support": [
            {"assertion": "The marker is cedar.", "evidence_aliases": ["E1"]}
        ],
        "members": [],
        "calculation": {"expression": None, "result": None},
        "uncertainties": [],
    }
    evidence_ledger = {
        name: grounded[name]
        for name in ("support", "members", "calculation", "uncertainties")
    }

    class ProviderTransport:
        name = "json"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            sequence = len(self.requests)
            content = (
                json.dumps(grounded)
                if evidence_use_mode == "grounded" or sequence == 2
                else json.dumps(evidence_ledger)
            )
            native_request_id = f"native-grounded-answer-{sequence}"
            return NativeProviderResponse(
                native_request_id=native_request_id,
                prompt_tokens=20,
                completion_tokens=10,
                finish_reason="stop",
                payload={
                    "id": native_request_id,
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": content,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                },
            )

    class ProviderStreamTransport:
        name = "stream"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def open_stream(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            sequence = len(self.requests)
            content = (
                json.dumps(grounded)
                if evidence_use_mode == "grounded" or sequence == 2
                else json.dumps(evidence_ledger)
            )
            native_request_id = f"native-grounded-answer-{sequence}"
            midpoint = len(content) // 2

            def event(delta: dict[str, object], finish_reason: str | None) -> bytes:
                return (
                    b"data: "
                    + json.dumps(
                        {
                            "id": native_request_id,
                            "object": "chat.completion.chunk",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": delta,
                                    "finish_reason": finish_reason,
                                }
                            ],
                            **(
                                {
                                    "usage": {
                                        "prompt_tokens": 20,
                                        "completion_tokens": 10,
                                        "total_tokens": 30,
                                    }
                                }
                                if finish_reason is not None
                                else {}
                            ),
                        },
                        separators=(",", ":"),
                    ).encode()
                    + b"\n\n"
                )

            return iter(
                [
                    event(
                        {"role": "assistant", "content": content[:midpoint]},
                        None,
                    ),
                    event({"content": content[midpoint:]}, "stop"),
                    b"data: [DONE]\n\n",
                ]
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        submitter_socket=SOCKET_ROOT / "submitter.sock",
        memory_subject_id="synthetic-user",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
        evidence_use_mode=evidence_use_mode,
    )
    reader = Reader()
    submitter = Submitter()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = reader  # type: ignore[assignment]
    adapter.memory_facade = OpenWorkerMemoryFacade(
        reader,
        submitter=submitter,
        subject_id="synthetic-user",
        permission_snapshot={"readable": True, "project_ids": ["orchid-release"]},
    )
    transport = ProviderTransport()
    stream_transport = ProviderStreamTransport()
    if stream:
        adapter.stream_transport = stream_transport
    else:
        adapter.transport = transport
    incoming = OpenAIChatRequest.parse(
        _request(
            messages=[{"role": "user", "content": "What is my marker?"}],
            stream=stream,
            tools=[],
            response_format=None,
            **({"stream_options": {"include_usage": True}} if stream else {}),
        )
    )
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": ["ses-grounded-1"],
            "X-MiLAi-Task-Operation": ["msg-user-1"],
            "X-MiLAi-Assistant-Message": ["msg-assistant-1"],
            "X-MiLAi-User-Observed-At": ["2026-09-03T00:00:00.000Z"],
            "X-MiLAi-Assistant-Observed-At": ["2026-09-03T00:00:00.010Z"],
        },
        require_settlement=True,
    )
    try:
        completion, route = adapter.complete(incoming, metadata)

        assert route == "PROVIDER_AVAILABLE"
        assert submitter.calls
        if stream:
            assert isinstance(completion, StreamingCompletion)
            delivered = b"".join(completion.chunks).decode()
            assert "Your marker is cedar." in delivered
            assert "GroundedEvidenceUseV01" not in delivered
            provider_payload = stream_transport.requests[0].payload  # type: ignore[attr-defined]
            provider_requests = stream_transport.requests
        else:
            assert isinstance(completion, dict)
            assert completion["choices"][0]["message"]["content"] == "Your marker is cedar."
            provider_payload = transport.requests[0].payload  # type: ignore[attr-defined]
            provider_requests = transport.requests
        assert provider_payload["response_format"]["json_schema"]["name"] == (
            "EvidenceLedgerV01"
            if evidence_use_mode == "ledger"
            else "GroundedEvidenceUseV01"
        )
        assert "tools" not in provider_payload
        assert len(provider_requests) == (2 if evidence_use_mode == "ledger" else 1)
        if evidence_use_mode == "ledger":
            final_payload = provider_requests[1].payload  # type: ignore[attr-defined]
            assert final_payload["response_format"]["json_schema"]["name"] == (
                "GroundedEvidenceUseV01"
            )
            assert "MILAI_PROVISIONAL_EVIDENCE_LEDGER_BEGIN" in json.dumps(
                final_payload["messages"]
            )
        assert [call["speaker"] for call in submitter.calls] == ["user", "assistant"]
        assert [call["content"] for call in submitter.calls] == [
            "What is my marker?",
            "Your marker is cedar.",
        ]
        assert submitter.calls[0]["source_context"]["turn_id"] == "msg-user-1"
        assert submitter.calls[1]["source_context"]["turn_id"] == "msg-assistant-1"
        assert submitter.calls[0]["source_ref"].endswith("/message/msg-user-1")
        lineage = decode_memory_support_lineage(str(submitter.calls[1]["source_ref"]))
        assert lineage is not None
        assert lineage.evidence_aliases == ("E1",)
        assert lineage.evidence_ids == ("evidence-prior",)
        captured = "\n".join(str(call["content"]) for call in submitter.calls)
        assert "MILAI_CONTEXT" not in captured
        assert "Reader-visible alias inventory" not in captured
        rows = [
            json.loads(line)
            for line in adapter.trace.read_text(encoding="utf-8").splitlines()
        ]
        settlement = next(row for row in rows if row["event"] == "HOST_MEMORY_SETTLED")
        assert settlement["memory_support_refs"] == ["evidence-prior"]
        assert settlement["canonical_changed"] is False
        answer_trace = next(row for row in rows if row["event"] == "PROVIDER_ANSWER")
        assert answer_trace["evidence_use_pass_count"] == (
            2 if evidence_use_mode == "ledger" else 1
        )
    finally:
        adapter.close()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reader_outcome", ["answer", "calculate", "invalid"])
def test_model_native_reader_delivers_one_terminal_and_contains_internal_tool_loop(
    tmp_path: Path,
    stream: bool,
    reader_outcome: str,
) -> None:
    context_text = (
        "MEMORY_CONTEXT_V0_2\n"
        "MEMORY_STATUS=HIT\n"
        "[E1 source=prior-user] The user has one hat.\n"
        "[E2 source=prior-user] The user has two shirts."
    )

    class Reader:
        def resolve_memory(
            self, query: str, *, previous_context_id: str | None = None
        ) -> dict[str, object]:
            del query, previous_context_id
            return {
                "schema_version": "access-outcome-v0.1",
                "status": "HIT",
                "availability": "AVAILABLE",
                "items": [],
                "open_issue_ids": [],
                "degraded_components": [],
                "abstention_reason": None,
                "canonical_position": 30,
                "trace_id": "trace-model-native-reader",
                "reader_evidence_boundary": "GOVERNANCE_ADMITTED_SOFT_RANKED",
                "memory_context": {
                    "text": context_text,
                    "selected_evidence_ids": ["evidence-one", "evidence-two"],
                    "claim_versions": [],
                },
                "context_receipt": {
                    "context_capsule_id": "context-model-native-1",
                    "receipt_mapping": [
                        {
                            "alias": "E1",
                            "evidence_ids": ["evidence-one"],
                            "source_turn_refs": ["prior-user-1"],
                            "claim_versions": [],
                        },
                        {
                            "alias": "E2",
                            "evidence_ids": ["evidence-two"],
                            "source_turn_refs": ["prior-user-2"],
                            "claim_versions": [],
                        },
                    ],
                },
                "access_trace": {"planned_stage": "SEARCH", "spans": {}},
                "host_transport": {"uds_roundtrip_ms": 1.0},
            }

        def close(self) -> None:
            return None

    class ProviderTransport:
        name = "json"

        def __init__(self) -> None:
            self.requests: list[object] = []

        def invoke(self, request, capability):  # type: ignore[no-untyped-def]
            del capability
            self.requests.append(request)
            ordinal = len(self.requests)
            if reader_outcome == "invalid":
                content = "not-json"
            elif reader_outcome == "calculate" and ordinal == 1:
                content = json.dumps(
                    {
                        "action": "CALCULATE",
                        "answer_text": "",
                        "evidence_aliases": ["E1", "E2"],
                        "expressions": ["1 + 2"],
                    }
                )
            elif reader_outcome == "calculate":
                content = json.dumps(
                    {
                        "answer_text": "You have three clothing items.",
                        "evidence_aliases": ["[E1]", "E2"],
                    }
                )
            else:
                content = json.dumps(
                    {
                        "action": "ANSWER",
                        "answer_text": "You have one hat and two shirts.",
                        "evidence_aliases": [],
                        "expressions": [],
                    }
                )
            native_request_id = f"native-model-native-{ordinal}"
            return NativeProviderResponse(
                native_request_id=native_request_id,
                prompt_tokens=20,
                completion_tokens=10,
                finish_reason="stop",
                payload={
                    "id": native_request_id,
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                },
            )

    adapter = OpenWorkerProviderAdapter(
        _provider_manifest(tmp_path / "manifest.json"),
        tmp_path / "provider-ledger.jsonl",
        tmp_path / "host-trace.jsonl",
        memory_mode="query-first",
        prefetch_socket=SOCKET_ROOT / "reader-lite.sock",
        tokenizer_json=_test_tokenizer_json(tmp_path),
        broker_policy=_reader_lite_policy(tmp_path),
        task_fixture=FIXTURE,
        evidence_use_mode="model-native",
    )
    reader = Reader()
    assert adapter.host_mcp is not None
    adapter.host_mcp.close()
    adapter.host_mcp = reader  # type: ignore[assignment]
    transport = ProviderTransport()
    adapter.transport = transport
    incoming = OpenAIChatRequest.parse(
        _request(
            messages=[{"role": "user", "content": "How many clothing items do I have?"}],
            stream=stream,
            tools=[],
            response_format=None,
            **({"stream_options": {"include_usage": True}} if stream else {}),
        )
    )
    metadata = _task_metadata_from_values(
        {
            "X-MiLAi-Host-Instance": ["123e4567-e89b-12d3-a456-426614174000"],
            "X-MiLAi-Task-Session": [f"ses-model-native-{reader_outcome}-{stream}"],
            "X-MiLAi-Task-Operation": [f"msg-model-native-{reader_outcome}-{stream}"],
        }
    )
    try:
        completion, route = adapter.complete(incoming, metadata)

        assert route == "PROVIDER_AVAILABLE"
        if stream:
            assert isinstance(completion, StreamingCompletion)
            delivered = b"".join(completion.chunks).decode()
        else:
            assert isinstance(completion, dict)
            delivered = str(completion["choices"][0]["message"]["content"])
        expected_answer = {
            "answer": "You have one hat and two shirts.",
            "calculate": "You have three clothing items.",
            "invalid": (
                "I couldn't reliably complete this memory answer from the available evidence."
            ),
        }[reader_outcome]
        assert expected_answer in delivered
        assert "ReaderActionV01" not in delivered
        assert len(transport.requests) == (2 if reader_outcome == "calculate" else 1)
        assert all(request.payload["stream"] is False for request in transport.requests)  # type: ignore[attr-defined]
        assert all("tools" not in request.payload for request in transport.requests)  # type: ignore[attr-defined]
        first_payload = transport.requests[0].payload  # type: ignore[attr-defined]
        assert first_payload["response_format"]["json_schema"]["name"] == (
            "ReaderActionV01"
        )
        if reader_outcome == "calculate":
            final_payload = transport.requests[1].payload  # type: ignore[attr-defined]
            assert final_payload["response_format"]["json_schema"]["name"] == (
                "ReaderFinalAnswerV01"
            )
            assert final_payload["messages"][-2]["role"] == "assistant"
            assert final_payload["messages"][-2]["tool_calls"][0]["function"][
                "name"
            ] == "calculator"
            assert final_payload["messages"][-1]["role"] == "tool"
            assert json.loads(final_payload["messages"][-1]["content"]) == {
                "value": "3"
            }
        trace = [
            json.loads(line)
            for line in adapter.trace.read_text(encoding="utf-8").splitlines()
        ]
        assert not any(row["event"] == "HOST_EVIDENCE_USE_REJECTED" for row in trace)
        fallbacks = [row for row in trace if row["event"] == "HOST_READER_SESSION_FALLBACK"]
        assert len(fallbacks) == int(reader_outcome == "invalid")
        answer = next(row for row in trace if row["event"] == "PROVIDER_ANSWER")
        assert answer["reader_session_result"]["fallback"] is (
            reader_outcome == "invalid"
        )
        assert answer["reader_session_result"]["provider_rounds"] == len(
            transport.requests
        )
        assert answer["evidence_use_pass_count"] == len(transport.requests)
    finally:
        adapter.close()


def test_ingress_terminal_trace_does_not_persist_untrusted_value_error_text(
    tmp_path: Path,
) -> None:
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.trace = tmp_path / "host-access-trace.jsonl"
    adapter._lock = threading.Lock()

    adapter._record_ingress_terminal(400, ValueError("synthetic-secret-token /private/host/path"))

    event = json.loads(adapter.trace.read_text(encoding="utf-8"))
    assert event == {
        "event": "HOST_INGRESS_TERMINAL",
        "exception_type": "ValueError",
        "http_status": 400,
        "reason_code": "VALUE_ERROR",
    }
    assert "synthetic-secret-token" not in adapter.trace.read_text(encoding="utf-8")
    assert "/private/host/path" not in adapter.trace.read_text(encoding="utf-8")


def test_openworker_image_bakes_real_header_plugin_and_exact_model() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "openworker/opencode.json").read_text(encoding="utf-8"))
    plugin = (root / "openworker/milai-task-metadata.js").read_text(encoding="utf-8")
    dockerfile = (root / "openworker/Dockerfile").read_text(encoding="utf-8")

    assert config["model"] == f"openworker/{EXACT_MODEL_ID}"
    assert set(config["provider"]["openworker"]["models"]) == {EXACT_MODEL_ID}
    assert config["provider"]["openworker"]["models"][EXACT_MODEL_ID]["temperature"] is True
    assert config["provider"]["openworker"]["models"][EXACT_MODEL_ID]["limit"] == {
        "context": 65_536,
        "output": 2_048,
    }
    assert config["agent"]["build"]["temperature"] == 0
    assert config["agent"]["build"]["top_p"] == 1
    assert {
        name: config["agent"][name].get("disabled") for name in ("title", "summary", "compaction")
    } == {
        "title": True,
        "summary": True,
        "compaction": True,
    }
    assert config["tools"] == {"*": False, "milai_*": True}
    assert {
        name: config["agent"][name].get("tools") for name in ("build", "general", "explore", "plan")
    } == {name: {"*": False, "milai_*": True} for name in ("build", "general", "explore", "plan")}
    assert {
        name: config["agent"][name]["permission"]
        for name in ("build", "general", "explore", "plan")
    } == {
        name: {"*": "deny", "milai_*": "allow"} for name in ("build", "general", "explore", "plan")
    }
    ordinary = config["agent"]["dg13u-ordinary-sync"]
    assert ordinary == {
        "description": ("DG13-U1 synthetic single synchronous read-tool compatibility case."),
        "mode": "primary",
        "steps": 4,
        "tools": {"*": False, "read": True, "milai_*": True},
        "permission": {"*": "deny", "read": "allow", "milai_*": "allow"},
    }
    assert "/openworker/image/plugins/milai-task-metadata.js" in config["plugin"]
    assert '"chat.headers"' in plugin
    assert "input.sessionID" in plugin
    assert "input.message?.id" in plugin
    assert 'event.type !== "message.updated"' in plugin
    assert 'output.headers["X-MiLAi-Assistant-Message"]' in plugin
    assert 'output.headers["X-MiLAi-User-Observed-At"]' in plugin
    assert "openworker/milai-task-metadata.js" in dockerfile
