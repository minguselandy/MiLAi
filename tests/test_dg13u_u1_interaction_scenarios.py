from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from collections.abc import MutableMapping
from typing import Any

import pytest

from scripts import dg13u_u1_interaction_scenarios as scenarios

READ_SHA256 = hashlib.sha256(b"read").hexdigest()
CALL_ID_SHA256 = hashlib.sha256(b"call-read-1").hexdigest()
NATIVE_ID_SHA256 = hashlib.sha256(b"chatcmpl-native-stream-1").hexdigest()
PRIVATE_ARGUMENTS = '{"path":"private/source.py"}'
PRIVATE_RESULT = "private synthetic tool result"
PRIVATE_SESSION = "ses_private_interaction_123"
MODEL = "openworker/Qwen3.6-35B-A3B-FP8"


def _event_bytes(events: list[dict[str, Any]]) -> bytes:
    return "\n".join(json.dumps(event) for event in events).encode()


def _event(
    event_type: str,
    part: dict[str, Any],
    *,
    session_id: str = PRIVATE_SESSION,
) -> dict[str, Any]:
    return {"type": event_type, "sessionID": session_id, "part": part}


def _stream_observation() -> dict[str, Any]:
    return {
        "request": {
            "stream": True,
            "include_usage": True,
            "provider_memory_tool_count": 0,
            "excluded_memory_tool_count": 1,
        },
        "gateway": {
            "terminal_event_count": 1,
            "done_observed": True,
            "usage_observed": True,
            "native_id_count": 1,
            "native_request_id_sha256": NATIVE_ID_SHA256,
            "finish_reason": "stop",
            "terminal_status": "SUCCEEDED",
        },
        "opencode": {
            "exit_code": 0,
            "json_event_count": 4,
            "terminal_success_event_count": 1,
            "json_parse_error_count": 0,
            "typed_error_count": 0,
        },
        "provider": {
            "attempts": 1,
            "automatic_retries": 0,
            "ledger_events": [
                "RESERVED",
                "PROVIDER_TERMINAL",
                "POST_PROVIDER_TERMINAL",
            ],
        },
        "mcp": {"calls": 1, "automatic_retries": 0},
        "host": {"terminal_status": "SUCCEEDED"},
        "persistence": {
            "raw_sse_frames": False,
            "opencode_event_body": False,
            "prompt": False,
            "credentials": False,
            "response_content": False,
        },
    }


def _ordinary_observation() -> dict[str, Any]:
    return {
        "rounds": [
            {
                "round": "CALL",
                "requested_tool_choice": "AUTO",
                "effective_tool_choice": "NAMED",
                "ordinary_tool_count": 1,
                "ordinary_tool_name_sha256": READ_SHA256,
                "provider_memory_tool_count": 0,
                "excluded_memory_tool_count": 1,
                "assistant_tool_call_count": 0,
                "tool_result_count": 0,
                "matching_tool_result_count": 0,
                "tool_call_id_sha256": None,
                "provider_finish_reason": "stop",
                "provider_payload_ordinary_tool_count": 0,
                "tool_call_delivery": "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER",
                "delivered_tool_call_count": 1,
                "delivered_tool_name_sha256": READ_SHA256,
                "delivered_tool_call_id_sha256": CALL_ID_SHA256,
            },
            {
                "round": "FINAL",
                "requested_tool_choice": "AUTO",
                "effective_tool_choice": "NONE",
                "ordinary_tool_count": 1,
                "ordinary_tool_name_sha256": READ_SHA256,
                "provider_memory_tool_count": 0,
                "excluded_memory_tool_count": 1,
                "assistant_tool_call_count": 1,
                "tool_result_count": 1,
                "matching_tool_result_count": 1,
                "tool_call_id_sha256": CALL_ID_SHA256,
                "provider_finish_reason": "stop",
                "provider_payload_ordinary_tool_count": 1,
                "tool_call_delivery": "NATIVE_NONE",
                "delivered_tool_call_count": 0,
                "delivered_tool_name_sha256": None,
                "delivered_tool_call_id_sha256": None,
            },
        ],
        "provider": {
            "attempts": 2,
            "automatic_retries": 0,
            "terminal_count": 2,
            "post_terminal_count": 2,
            "logical_request_ids_unique": True,
            "third_round_observed": False,
        },
        "mcp": {"calls": 0, "automatic_retries": 0},
        "host": {
            "tool_execution_count": 1,
            "tool_name_sha256": READ_SHA256,
            "tool_call_id_sha256": CALL_ID_SHA256,
            "tool_result_call_id_sha256": CALL_ID_SHA256,
            "third_round_observed": False,
        },
        "delivery": {
            "incoming_tool_choice": "AUTO",
            "provider_tool_choice": "ABSENT",
            "provider_tool_count": 0,
            "native_finish_reason": "stop",
            "native_tool_call_count": 0,
            "delivery_owner": "HOST_ADAPTER",
            "client_finish_reason": "tool_calls",
            "delivered_read_count": 1,
        },
        "persistence": {
            "tool_arguments": False,
            "tool_result": False,
            "prompt": False,
            "credentials": False,
        },
    }


def _changed(
    source: dict[str, Any], path: tuple[str | int, ...], value: Any
) -> dict[str, Any]:
    changed = copy.deepcopy(source)
    target: MutableMapping[str, Any] | list[Any] = changed
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    return changed


def test_interaction_prompts_are_exact_safe_and_case_specific() -> None:
    assert scenarios.interaction_prompt("U1-STREAM") == (
        "What is the current release target for orchid-release?"
    )
    ordinary = scenarios.interaction_prompt("U1-ORDINARY-SYNC-TOOL")
    assert ordinary == (
        "For this synthetic local tool check, call read exactly once on "
        "/openworker/runtime/opencode.json, then give one short confirmation. "
        "Do not call any other tool."
    )
    assert ordinary.count("read") == 1
    assert ordinary.count("/openworker/runtime/opencode.json") == 1


def test_stream_command_is_shell_free_attached_json_without_ordinary_agent() -> None:
    prompt = scenarios.interaction_prompt("U1-STREAM")

    command = scenarios.build_opencode_interaction_command(
        "U1-STREAM",
        container_name="milai-dg13u-u1-worker-1234abcd",
        prompt=prompt,
        model=MODEL,
        session_id=PRIVATE_SESSION,
    )

    assert command == (
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        "milai-dg13u-u1-worker-1234abcd",
        "opencode",
        "run",
        "--attach",
        "http://127.0.0.1:4096",
        "--password",
        "openworker-local",
        "--format",
        "json",
        "--model",
        MODEL,
        "--session",
        PRIVATE_SESSION,
        "--dir",
        "/openworker/runtime",
        prompt,
    )
    assert "--agent" not in command
    assert not any(part in command for part in ("sh", "bash", "-c"))


def test_ordinary_command_selects_only_frozen_sync_agent_and_prompt() -> None:
    prompt = scenarios.interaction_prompt("U1-ORDINARY-SYNC-TOOL")

    command = scenarios.build_opencode_interaction_command(
        "U1-ORDINARY-SYNC-TOOL",
        container_name="milai-dg13u-u1-worker-abcd1234",
        prompt=prompt,
        model=MODEL,
        session_id=PRIVATE_SESSION,
    )

    assert command[command.index("--session") + 1] == PRIVATE_SESSION
    assert command[command.index("--dir") + 1] == "/openworker/runtime"
    assert command.count("--agent") == 1
    assert command.count("dg13u-ordinary-sync") == 1
    assert command[-1] == prompt


@pytest.mark.parametrize(
    ("case_id", "container_name", "prompt", "model", "reason"),
    [
        (
            "U1-UNKNOWN",
            "milai-worker",
            "anything",
            MODEL,
            "UNSUPPORTED_INTERACTION_CASE",
        ),
        (
            "U1-STREAM",
            "bad/container",
            "What is the current release target for orchid-release?",
            MODEL,
            "CONTAINER_NAME_INVALID",
        ),
        (
            "U1-STREAM",
            "milai-worker",
            "What is another target?",
            MODEL,
            "INTERACTION_PROMPT_INVALID",
        ),
        (
            "U1-STREAM",
            "milai-worker",
            "What is the current release target for orchid-release?",
            "openworker/other-model",
            "MODEL_INVALID",
        ),
    ],
)
def test_interaction_command_rejects_selector_container_prompt_or_model_drift(
    case_id: str,
    container_name: str,
    prompt: str,
    model: str,
    reason: str,
) -> None:
    with pytest.raises(scenarios.InteractionScenarioError, match=reason):
        scenarios.build_opencode_interaction_command(
            case_id,
            container_name=container_name,
            prompt=prompt,
            model=model,
            session_id=PRIVATE_SESSION,
        )


def test_interaction_command_rejects_missing_or_invalid_explicit_session() -> None:
    prompt = scenarios.interaction_prompt("U1-STREAM")
    for session_id in ("", "bad session"):
        with pytest.raises(
            scenarios.InteractionScenarioError, match="SESSION_ID_INVALID"
        ):
            scenarios.build_opencode_interaction_command(
                "U1-STREAM",
                container_name="milai-worker",
                prompt=prompt,
                model=MODEL,
                session_id=session_id,
            )


def test_parse_stream_events_returns_only_hashes_and_structural_counts() -> None:
    raw = _event_bytes(
        [
            _event("step_start", {"type": "step-start"}),
            _event("text", {"type": "text", "text": "private streamed answer"}),
            _event(
                "step_finish",
                {
                    "type": "step-finish",
                    "tokens": {"input": 7, "output": 2},
                },
            ),
        ]
    )

    evidence = scenarios.parse_opencode_interaction_events(raw)

    assert evidence == {
        "schema": scenarios.OPENCODE_EVENT_SCHEMA,
        "event_stream_sha256": hashlib.sha256(raw).hexdigest(),
        "json_event_count": 3,
        "json_parse_error_count": 0,
        "typed_error_count": 0,
        "terminal_success_event_count": 1,
        "completed_ordinary_tool_event_count": 0,
        "completed_ordinary_tool_name_sha256": None,
        "session_id_sha256": hashlib.sha256(PRIVATE_SESSION.encode()).hexdigest(),
    }
    encoded = json.dumps(evidence, sort_keys=True)
    assert PRIVATE_SESSION not in encoded
    assert "private streamed answer" not in encoded
    assert "tokens" not in encoded


def test_parse_ordinary_read_event_counts_only_completed_tool_structure() -> None:
    raw = _event_bytes(
        [
            _event("step_start", {"type": "step-start"}),
            _event(
                "tool_use",
                {
                    "type": "tool",
                    "tool": "read",
                    "state": {
                        "status": "completed",
                        "input": PRIVATE_ARGUMENTS,
                        "output": PRIVATE_RESULT,
                    },
                },
            ),
            _event("text", {"type": "text", "text": "private final answer"}),
            _event("step_finish", {"type": "step-finish"}),
        ]
    )

    evidence = scenarios.parse_opencode_interaction_events(raw)

    assert evidence["json_event_count"] == 4
    assert evidence["terminal_success_event_count"] == 1
    assert evidence["completed_ordinary_tool_event_count"] == 1
    assert evidence["completed_ordinary_tool_name_sha256"] == READ_SHA256
    encoded = json.dumps(evidence, sort_keys=True)
    for private in (
        PRIVATE_SESSION,
        PRIVATE_ARGUMENTS,
        PRIVATE_RESULT,
        "private final answer",
        "read",
    ):
        assert private not in encoded


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"", "OPENCODE_EVENTS_EMPTY"),
        (b"\xff", "OPENCODE_EVENTS_INVALID_UTF8"),
        (b"{not-json}", "OPENCODE_EVENT_INVALID_JSON"),
        (b"[]", "OPENCODE_EVENT_INVALID"),
        (
            _event_bytes(
                [
                    _event("text", {"type": "text"}, session_id="ses_a"),
                    _event("text", {"type": "text"}, session_id="ses_b"),
                ]
            ),
            "OPENCODE_SESSION_NOT_UNIQUE",
        ),
        (
            _event_bytes([{"type": "text", "part": {"type": "text"}}]),
            "OPENCODE_SESSION_INVALID",
        ),
    ],
)
def test_parse_events_rejects_invalid_encoding_json_object_or_session(
    raw: bytes, reason: str
) -> None:
    with pytest.raises(scenarios.InteractionScenarioError, match=reason):
        scenarios.parse_opencode_interaction_events(raw)


def test_parse_events_counts_typed_error_without_retaining_error_body() -> None:
    raw = _event_bytes(
        [
            _event(
                "error",
                {
                    "type": "error",
                    "message": "private typed failure",
                    "reason_code": "PRIVATE_REASON",
                },
            )
        ]
    )

    evidence = scenarios.parse_opencode_interaction_events(raw)

    assert evidence["typed_error_count"] == 1
    assert evidence["terminal_success_event_count"] == 0
    encoded = json.dumps(evidence, sort_keys=True)
    assert "private typed failure" not in encoded
    assert "PRIVATE_REASON" not in encoded


def test_parse_events_does_not_count_structurally_valid_unfinished_tool() -> None:
    raw = _event_bytes(
        [
            _event(
                "tool_use",
                {
                    "type": "tool",
                    "tool": "read",
                    "state": {"status": "running", "input": PRIVATE_ARGUMENTS},
                },
            )
        ]
    )

    evidence = scenarios.parse_opencode_interaction_events(raw)

    assert evidence["completed_ordinary_tool_event_count"] == 0
    assert evidence["completed_ordinary_tool_name_sha256"] is None


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (
            _event("step_finish", {"type": "text"}),
            "OPENCODE_STEP_FINISH_INVALID",
        ),
        (
            _event("text", {"type": "step-finish"}),
            "OPENCODE_STEP_FINISH_INVALID",
        ),
        (
            _event("tool_use", {"type": "text", "state": {"status": "completed"}}),
            "OPENCODE_TOOL_EVENT_INVALID",
        ),
        (
            _event("text", {"type": "tool", "state": {"status": "completed"}}),
            "OPENCODE_TOOL_EVENT_INVALID",
        ),
        (
            _event("tool_use", {"type": "tool", "state": {"status": "completed"}}),
            "OPENCODE_TOOL_EVENT_INVALID",
        ),
    ],
)
def test_parse_events_fails_closed_on_recognized_structure_drift(
    event: dict[str, Any], reason: str
) -> None:
    with pytest.raises(scenarios.InteractionScenarioError, match=reason):
        scenarios.parse_opencode_interaction_events(_event_bytes([event]))


def test_parse_events_rejects_multiple_distinct_completed_tool_names() -> None:
    raw = _event_bytes(
        [
            _event(
                "tool_use",
                {"type": "tool", "tool": name, "state": {"status": "completed"}},
            )
            for name in ("read", "bash")
        ]
    )

    with pytest.raises(
        scenarios.InteractionScenarioError, match="OPENCODE_TOOL_NAME_NOT_UNIQUE"
    ):
        scenarios.parse_opencode_interaction_events(raw)


def test_plans_freeze_real_product_counts_and_stream_case_spec_revision() -> None:
    assert set(scenarios.PLANS) == {"U1-STREAM", "U1-ORDINARY-SYNC-TOOL"}

    stream = scenarios.interaction_plan("U1-STREAM")
    assert (stream.memory_need, stream.provider_rounds, stream.mcp_calls) == (
        "EXACT",
        1,
        1,
    )
    assert dict(stream.case_spec_revision or {}) == {
        "current_description": "Streaming NONE provider semantics",
        "required_description": "Streaming EXACT memory semantics",
        "current_memory_need": "NONE",
        "required_memory_need": "EXACT",
        "current_expected_mcp_calls": 0,
        "required_expected_mcp_calls": 1,
    }
    ordinary = scenarios.interaction_plan("U1-ORDINARY-SYNC-TOOL")
    assert (ordinary.memory_need, ordinary.provider_rounds, ordinary.mcp_calls) == (
        "NONE",
        2,
        0,
    )
    assert stream.request_stream is stream.stream_include_usage is True
    assert ordinary.request_stream is ordinary.stream_include_usage is True
    assert ordinary.case_spec_revision is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        ordinary.mcp_calls = 2  # type: ignore[misc]
    with pytest.raises(scenarios.InteractionScenarioError, match="UNSUPPORTED"):
        scenarios.interaction_plan("U1-UNKNOWN")


def test_stream_reducer_accepts_native_sse_identity_usage_and_single_attempts() -> None:
    result = scenarios.reduce_interaction("U1-STREAM", _stream_observation())

    assert result["status"] == "PASS"
    assert result["memory_need"] == "EXACT"
    assert result["provider_rounds"] == result["mcp_calls"] == 1
    assert result["automatic_retries"] == 0
    assert result["visible_milai_tool_count"] == 0
    assert result["sse"] == {
        "gateway_terminal_event_count": 1,
        "native_request_id_sha256": NATIVE_ID_SHA256,
        "include_usage": True,
        "finish_reason": "stop",
        "done": True,
        "opencode_json_event_count": 4,
        "opencode_terminal_success_event_count": 1,
        "opencode_typed_error_count": 0,
    }
    encoded = json.dumps(result, sort_keys=True)
    assert "data:" not in encoded
    assert "response_content" not in encoded


def test_stream_reducer_accepts_missing_cli_terminal_only_with_gateway_terminal() -> (
    None
):
    observation = _stream_observation()
    observation["opencode"]["terminal_success_event_count"] = 0

    result = scenarios.reduce_interaction("U1-STREAM", observation)

    assert result["sse"]["gateway_terminal_event_count"] == 1
    assert result["sse"]["done"] is True
    assert result["sse"]["opencode_terminal_success_event_count"] == 0


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("request", "include_usage"), False, "STREAM_REQUEST_INVALID"),
        (("request", "provider_memory_tool_count"), 1, "STREAM_REQUEST_INVALID"),
        (("gateway", "terminal_event_count"), 0, "STREAM_GATEWAY_INVALID"),
        (("gateway", "done_observed"), False, "STREAM_GATEWAY_INVALID"),
        (("gateway", "usage_observed"), False, "STREAM_GATEWAY_INVALID"),
        (("gateway", "native_id_count"), 2, "STREAM_GATEWAY_INVALID"),
        (("gateway", "finish_reason"), "tool_calls", "STREAM_GATEWAY_INVALID"),
        (("opencode", "json_event_count"), 0, "STREAM_OPENCODE_INVALID"),
        (("opencode", "json_parse_error_count"), 1, "STREAM_OPENCODE_INVALID"),
        (("opencode", "typed_error_count"), 1, "STREAM_OPENCODE_INVALID"),
        (("opencode", "terminal_success_event_count"), 2, "STREAM_OPENCODE_INVALID"),
        (("provider", "attempts"), 2, "STREAM_PROVIDER_INVALID"),
        (("provider", "automatic_retries"), 1, "STREAM_PROVIDER_INVALID"),
        (("mcp", "calls"), 0, "STREAM_MCP_INVALID"),
        (("persistence", "raw_sse_frames"), True, "RAW_INTERACTION_CONTENT_PERSISTED"),
        (
            ("persistence", "opencode_event_body"),
            True,
            "RAW_INTERACTION_CONTENT_PERSISTED",
        ),
    ],
)
def test_stream_negative_twins_reject_drift(
    path: tuple[str | int, ...], value: Any, reason: str
) -> None:
    with pytest.raises(scenarios.InteractionScenarioError, match=reason):
        scenarios.reduce_interaction(
            "U1-STREAM", _changed(_stream_observation(), path, value)
        )


def test_stream_rejects_transport_chunk_observation_as_non_semantic_evidence() -> None:
    observation = _stream_observation()
    observation["gateway"]["raw_transport_chunk_sha256"] = "a" * 64

    with pytest.raises(
        scenarios.InteractionScenarioError, match="STREAM_GATEWAY_INVALID"
    ):
        scenarios.reduce_interaction("U1-STREAM", observation)


def test_ordinary_reducer_accepts_exact_read_pair_second_none_and_no_third_round() -> (
    None
):
    result = scenarios.reduce_interaction(
        "U1-ORDINARY-SYNC-TOOL", _ordinary_observation()
    )

    assert result["status"] == "PASS"
    assert result["memory_need"] == "NONE"
    assert result["provider_rounds"] == 2
    assert result["mcp_calls"] == 0
    assert result["automatic_retries"] == 0
    assert result["visible_milai_tool_count"] == 0
    assert result["provider_call_policy"] == {
        "provider_calls_per_model_round_maximum": 1,
        "model_rounds": 2,
        "calls_per_task_operation": 2,
        "case_maximum": 2,
    }
    assert result["ordinary_tool"] == {
        "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
        "tool_name_sha256": READ_SHA256,
        "tool_call_id_sha256": CALL_ID_SHA256,
        "execution_count": 1,
        "final_tool_choice": "NONE",
        "tool_call_delivery": "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER",
        "native_provider_finish_reasons": ["stop", "stop"],
        "third_round_observed": False,
        "incoming_tool_choice": "AUTO",
        "provider_tool_choice": "ABSENT",
        "provider_tool_count": 0,
        "native_finish_reason": "stop",
        "native_tool_call_count": 0,
        "delivery_owner": "HOST_ADAPTER",
        "client_finish_reason": "tool_calls",
        "delivered_read_count": 1,
    }
    encoded = json.dumps(result, sort_keys=True)
    assert PRIVATE_ARGUMENTS not in encoded
    assert PRIVATE_RESULT not in encoded


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("rounds", 0, "delivered_tool_call_count"), 2, "ORDINARY_ROUND_INVALID"),
        (
            ("rounds", 0, "delivered_tool_name_sha256"),
            "a" * 64,
            "ORDINARY_ROUND_INVALID",
        ),
        (("rounds", 1, "effective_tool_choice"), "NAMED", "ORDINARY_ROUND_INVALID"),
        (("rounds", 1, "matching_tool_result_count"), 0, "ORDINARY_ROUND_INVALID"),
        (
            ("host", "tool_result_call_id_sha256"),
            "b" * 64,
            "ORDINARY_TOOL_PAIR_INVALID",
        ),
        (("host", "tool_execution_count"), 2, "ORDINARY_TOOL_PAIR_INVALID"),
        (("provider", "attempts"), 3, "ORDINARY_PROVIDER_INVALID"),
        (("provider", "third_round_observed"), True, "ORDINARY_PROVIDER_INVALID"),
        (("mcp", "calls"), 2, "ORDINARY_MCP_INVALID"),
        (("delivery", "incoming_tool_choice"), "NONE", "ORDINARY_DELIVERY_INVALID"),
        (
            ("delivery", "provider_tool_choice"),
            "AUTO",
            "ORDINARY_DELIVERY_INVALID",
        ),
        (("delivery", "provider_tool_count"), 1, "ORDINARY_DELIVERY_INVALID"),
        (("delivery", "provider_tool_count"), False, "ORDINARY_DELIVERY_INVALID"),
        (
            ("delivery", "native_finish_reason"),
            "tool_calls",
            "ORDINARY_DELIVERY_INVALID",
        ),
        (("delivery", "native_tool_call_count"), 1, "ORDINARY_DELIVERY_INVALID"),
        (
            ("delivery", "native_tool_call_count"),
            False,
            "ORDINARY_DELIVERY_INVALID",
        ),
        (
            ("delivery", "delivery_owner"),
            "PROVIDER",
            "ORDINARY_DELIVERY_INVALID",
        ),
        (
            ("delivery", "client_finish_reason"),
            "stop",
            "ORDINARY_DELIVERY_INVALID",
        ),
        (("delivery", "delivered_read_count"), 0, "ORDINARY_DELIVERY_INVALID"),
        (("delivery", "delivered_read_count"), True, "ORDINARY_DELIVERY_INVALID"),
        (("persistence", "tool_arguments"), True, "RAW_INTERACTION_CONTENT_PERSISTED"),
    ],
)
def test_ordinary_negative_twins_reject_drift(
    path: tuple[str | int, ...], value: Any, reason: str
) -> None:
    with pytest.raises(scenarios.InteractionScenarioError, match=reason):
        scenarios.reduce_interaction(
            "U1-ORDINARY-SYNC-TOOL",
            _changed(_ordinary_observation(), path, value),
        )


@pytest.mark.parametrize("field", ["tool_arguments", "tool_result"])
def test_ordinary_rejects_raw_tool_body_fields(field: str) -> None:
    observation = _ordinary_observation()
    observation["host"][field] = (
        PRIVATE_ARGUMENTS if field == "tool_arguments" else PRIVATE_RESULT
    )

    with pytest.raises(
        scenarios.InteractionScenarioError, match="ORDINARY_HOST_INVALID"
    ):
        scenarios.reduce_interaction("U1-ORDINARY-SYNC-TOOL", observation)


def test_ordinary_rejects_missing_delivery_trace_instead_of_inferring_it() -> None:
    observation = _ordinary_observation()
    observation.pop("delivery")

    with pytest.raises(
        scenarios.InteractionScenarioError, match="ORDINARY_DELIVERY_INVALID"
    ):
        scenarios.reduce_interaction("U1-ORDINARY-SYNC-TOOL", observation)


@pytest.mark.parametrize(
    "field",
    (
        "incoming_tool_choice",
        "provider_tool_choice",
        "provider_tool_count",
        "native_finish_reason",
        "native_tool_call_count",
        "delivery_owner",
        "client_finish_reason",
        "delivered_read_count",
    ),
)
def test_ordinary_rejects_each_missing_delivery_fact(field: str) -> None:
    observation = _ordinary_observation()
    observation["delivery"].pop(field)

    with pytest.raises(
        scenarios.InteractionScenarioError, match="ORDINARY_DELIVERY_INVALID"
    ):
        scenarios.reduce_interaction("U1-ORDINARY-SYNC-TOOL", observation)


def test_reducer_rejects_non_mapping_observation() -> None:
    with pytest.raises(
        scenarios.InteractionScenarioError, match="INTERACTION_OBSERVATION_INVALID"
    ):
        scenarios.reduce_interaction("U1-STREAM", [])  # type: ignore[arg-type]
