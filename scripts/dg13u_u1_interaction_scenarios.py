#!/usr/bin/env python3
"""Structural plans and reducers for DG13-U1 stream and ordinary-tool cases."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

InteractionCase = Literal["U1-STREAM", "U1-ORDINARY-SYNC-TOOL"]
_SCHEMA = "milai.dg13u.u1-interaction-scenario.v1"
OPENCODE_EVENT_SCHEMA = "milai.dg13u.u1-opencode-interaction-events.v1"
_SHA256 = frozenset("0123456789abcdef")
_READ_SHA256 = hashlib.sha256(b"read").hexdigest()
_OPENCODE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_MODEL = "openworker/Qwen3.6-35B-A3B-FP8"
_OPENWORKER_ORIGIN = "http://127.0.0.1:4096"
_OPENWORKER_DIRECTORY = "/openworker/runtime"
_OPENWORKER_PASSWORD = "openworker-local"
_INTERACTION_PROMPTS: Mapping[str, str] = MappingProxyType(
    {
        "U1-STREAM": "What is the current release target for orchid-release?",
        "U1-ORDINARY-SYNC-TOOL": (
            "For this synthetic local tool check, call read exactly once on "
            "/openworker/runtime/opencode.json, then give one short confirmation. "
            "Do not call any other tool."
        ),
    }
)


class InteractionScenarioError(ValueError):
    """A structural observation violates the selected interaction contract."""


@dataclass(frozen=True, slots=True)
class InteractionPlan:
    schema: Literal["milai.dg13u.u1-interaction-scenario.v1"]
    case_id: InteractionCase
    memory_need: Literal["NONE", "EXACT"]
    provider_rounds: int
    mcp_calls: int
    automatic_retries: Literal[0]
    visible_milai_tool_count: Literal[0]
    request_stream: bool
    stream_include_usage: bool
    ordinary_tool_policy: str | None
    case_spec_revision: Mapping[str, object] | None


PLANS: Mapping[str, InteractionPlan] = MappingProxyType(
    {
        "U1-STREAM": InteractionPlan(
            schema=_SCHEMA,
            case_id="U1-STREAM",
            memory_need="EXACT",
            provider_rounds=1,
            mcp_calls=1,
            automatic_retries=0,
            visible_milai_tool_count=0,
            request_stream=True,
            stream_include_usage=True,
            ordinary_tool_policy=None,
            case_spec_revision=MappingProxyType(
                {
                    "current_description": "Streaming NONE provider semantics",
                    "required_description": "Streaming EXACT memory semantics",
                    "current_memory_need": "NONE",
                    "required_memory_need": "EXACT",
                    "current_expected_mcp_calls": 0,
                    "required_expected_mcp_calls": 1,
                }
            ),
        ),
        "U1-ORDINARY-SYNC-TOOL": InteractionPlan(
            schema=_SCHEMA,
            case_id="U1-ORDINARY-SYNC-TOOL",
            memory_need="NONE",
            provider_rounds=2,
            mcp_calls=0,
            automatic_retries=0,
            visible_milai_tool_count=0,
            request_stream=True,
            stream_include_usage=True,
            ordinary_tool_policy="SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
            case_spec_revision=None,
        ),
    }
)


def interaction_plan(case_id: str) -> InteractionPlan:
    try:
        return PLANS[case_id]
    except (KeyError, TypeError) as exc:
        raise InteractionScenarioError("UNSUPPORTED_INTERACTION_CASE") from exc


def interaction_prompt(case_id: str) -> str:
    """Return the one frozen, synthetic prompt for an interaction case."""

    try:
        return _INTERACTION_PROMPTS[case_id]
    except (KeyError, TypeError) as exc:
        raise InteractionScenarioError("UNSUPPORTED_INTERACTION_CASE") from exc


def build_opencode_interaction_command(
    case_id: str,
    *,
    container_name: str,
    prompt: str,
    model: str,
    session_id: str,
) -> tuple[str, ...]:
    """Build the shell-free attached OpenCode command for one interaction case."""

    expected_prompt = interaction_prompt(case_id)
    if (
        not isinstance(container_name, str)
        or _OPENCODE_IDENTIFIER.fullmatch(container_name) is None
    ):
        raise InteractionScenarioError("CONTAINER_NAME_INVALID")
    if not isinstance(prompt, str) or prompt != expected_prompt:
        raise InteractionScenarioError("INTERACTION_PROMPT_INVALID")
    if model != _MODEL:
        raise InteractionScenarioError("MODEL_INVALID")
    if (
        not isinstance(session_id, str)
        or _OPENCODE_IDENTIFIER.fullmatch(session_id) is None
    ):
        raise InteractionScenarioError("SESSION_ID_INVALID")

    command = [
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        container_name,
        "opencode",
        "run",
        "--attach",
        _OPENWORKER_ORIGIN,
        "--password",
        _OPENWORKER_PASSWORD,
        "--format",
        "json",
    ]
    if case_id == "U1-ORDINARY-SYNC-TOOL":
        command.extend(("--agent", "dg13u-ordinary-sync"))
    command.extend(
        (
            "--model",
            model,
            "--session",
            session_id,
            "--dir",
            _OPENWORKER_DIRECTORY,
            prompt,
        )
    )
    return tuple(command)


def parse_opencode_interaction_events(raw: bytes) -> dict[str, object]:
    """Reduce OpenCode JSONL to content-free interaction evidence.

    Recognized terminal and tool events are fail-closed: their outer and
    ``part`` types must agree.  A structurally valid, non-completed tool event
    is retained only in the total JSON event count.  Completed tool events are
    counted and may name exactly one distinct ordinary tool.
    """

    if not isinstance(raw, bytes) or not raw.strip():
        raise InteractionScenarioError("OPENCODE_EVENTS_EMPTY")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise InteractionScenarioError("OPENCODE_EVENTS_INVALID_UTF8") from exc

    event_count = 0
    typed_error_count = 0
    terminal_success_event_count = 0
    completed_tool_count = 0
    completed_tool_names: set[str] = set()
    session_ids: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InteractionScenarioError("OPENCODE_EVENT_INVALID_JSON") from exc
        if not isinstance(event, Mapping):
            raise InteractionScenarioError("OPENCODE_EVENT_INVALID")
        event_count += 1

        session_id = event.get("sessionID")
        if (
            not isinstance(session_id, str)
            or _OPENCODE_IDENTIFIER.fullmatch(session_id) is None
        ):
            raise InteractionScenarioError("OPENCODE_SESSION_INVALID")
        session_ids.add(session_id)

        event_type = event.get("type")
        if event_type == "error":
            typed_error_count += 1
        part = event.get("part")
        part_type = part.get("type") if isinstance(part, Mapping) else None

        if event_type == "step_finish" or part_type == "step-finish":
            if event_type != "step_finish" or part_type != "step-finish":
                raise InteractionScenarioError("OPENCODE_STEP_FINISH_INVALID")
            terminal_success_event_count += 1

        if event_type == "tool_use" or part_type == "tool":
            if (
                event_type != "tool_use"
                or not isinstance(part, Mapping)
                or part_type != "tool"
                or not isinstance(part.get("state"), Mapping)
                or not isinstance(part["state"].get("status"), str)
            ):
                raise InteractionScenarioError("OPENCODE_TOOL_EVENT_INVALID")
            if part["state"]["status"] != "completed":
                continue
            tool_name = part.get("tool")
            if (
                not isinstance(tool_name, str)
                or _OPENCODE_IDENTIFIER.fullmatch(tool_name) is None
            ):
                raise InteractionScenarioError("OPENCODE_TOOL_EVENT_INVALID")
            completed_tool_count += 1
            completed_tool_names.add(tool_name)

    if event_count == 0:
        raise InteractionScenarioError("OPENCODE_EVENTS_EMPTY")
    if len(session_ids) != 1:
        raise InteractionScenarioError("OPENCODE_SESSION_NOT_UNIQUE")
    if len(completed_tool_names) > 1:
        raise InteractionScenarioError("OPENCODE_TOOL_NAME_NOT_UNIQUE")

    session_id = next(iter(session_ids))
    completed_tool_name = next(iter(completed_tool_names), None)
    return {
        "schema": OPENCODE_EVENT_SCHEMA,
        "event_stream_sha256": hashlib.sha256(raw).hexdigest(),
        "json_event_count": event_count,
        "json_parse_error_count": 0,
        "typed_error_count": typed_error_count,
        "terminal_success_event_count": terminal_success_event_count,
        "completed_ordinary_tool_event_count": completed_tool_count,
        "completed_ordinary_tool_name_sha256": (
            hashlib.sha256(completed_tool_name.encode()).hexdigest()
            if completed_tool_name is not None
            else None
        ),
        "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
    }


def _exact_mapping(value: object, keys: set[str], reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise InteractionScenarioError(reason)
    return value


def _sha(value: object, reason: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256 for character in value)
    ):
        raise InteractionScenarioError(reason)
    return value


def _persistence(value: object, keys: set[str]) -> None:
    observed = _exact_mapping(value, keys, "PERSISTENCE_TRUTH_INVALID")
    if any(item is not False for item in observed.values()):
        raise InteractionScenarioError("RAW_INTERACTION_CONTENT_PERSISTED")


def _reduce_stream(
    plan: InteractionPlan, observation: Mapping[str, Any]
) -> dict[str, Any]:
    value = _exact_mapping(
        observation,
        {
            "request",
            "gateway",
            "opencode",
            "provider",
            "mcp",
            "host",
            "persistence",
        },
        "STREAM_OBSERVATION_INVALID",
    )
    request = _exact_mapping(
        value["request"],
        {
            "stream",
            "include_usage",
            "provider_memory_tool_count",
            "excluded_memory_tool_count",
        },
        "STREAM_REQUEST_INVALID",
    )
    if request != {
        "stream": True,
        "include_usage": True,
        "provider_memory_tool_count": 0,
        "excluded_memory_tool_count": 1,
    }:
        raise InteractionScenarioError("STREAM_REQUEST_INVALID")
    gateway = _exact_mapping(
        value["gateway"],
        {
            "terminal_event_count",
            "done_observed",
            "usage_observed",
            "native_id_count",
            "native_request_id_sha256",
            "finish_reason",
            "terminal_status",
        },
        "STREAM_GATEWAY_INVALID",
    )
    if (
        gateway["terminal_event_count"] != 1
        or gateway["done_observed"] is not True
        or gateway["usage_observed"] is not True
        or gateway["native_id_count"] != 1
        or gateway["finish_reason"] != "stop"
        or gateway["terminal_status"] != "SUCCEEDED"
    ):
        raise InteractionScenarioError("STREAM_GATEWAY_INVALID")
    native_request_id = _sha(
        gateway["native_request_id_sha256"], "STREAM_GATEWAY_INVALID"
    )
    opencode = _exact_mapping(
        value["opencode"],
        {
            "exit_code",
            "json_event_count",
            "terminal_success_event_count",
            "json_parse_error_count",
            "typed_error_count",
        },
        "STREAM_OPENCODE_INVALID",
    )
    if (
        opencode["exit_code"] != 0
        or not isinstance(opencode["json_event_count"], int)
        or isinstance(opencode["json_event_count"], bool)
        or opencode["json_event_count"] < 1
        or not isinstance(opencode["terminal_success_event_count"], int)
        or isinstance(opencode["terminal_success_event_count"], bool)
        or opencode["terminal_success_event_count"] not in {0, 1}
        or opencode["json_parse_error_count"] != 0
        or opencode["typed_error_count"] != 0
    ):
        raise InteractionScenarioError("STREAM_OPENCODE_INVALID")
    provider = _exact_mapping(
        value["provider"],
        {"attempts", "automatic_retries", "ledger_events"},
        "STREAM_PROVIDER_INVALID",
    )
    if provider != {
        "attempts": 1,
        "automatic_retries": 0,
        "ledger_events": ["RESERVED", "PROVIDER_TERMINAL", "POST_PROVIDER_TERMINAL"],
    }:
        raise InteractionScenarioError("STREAM_PROVIDER_INVALID")
    mcp = _exact_mapping(
        value["mcp"], {"calls", "automatic_retries"}, "STREAM_MCP_INVALID"
    )
    if mcp != {"calls": 1, "automatic_retries": 0}:
        raise InteractionScenarioError("STREAM_MCP_INVALID")
    host = _exact_mapping(value["host"], {"terminal_status"}, "STREAM_HOST_INVALID")
    if host["terminal_status"] != "SUCCEEDED":
        raise InteractionScenarioError("STREAM_HOST_INVALID")
    _persistence(
        value["persistence"],
        {
            "raw_sse_frames",
            "opencode_event_body",
            "prompt",
            "credentials",
            "response_content",
        },
    )
    return {
        "schema": _SCHEMA,
        "status": "PASS",
        "case_id": plan.case_id,
        "memory_need": plan.memory_need,
        "provider_rounds": 1,
        "mcp_calls": 1,
        "automatic_retries": 0,
        "visible_milai_tool_count": 0,
        "sse": {
            "gateway_terminal_event_count": 1,
            "native_request_id_sha256": native_request_id,
            "include_usage": True,
            "finish_reason": "stop",
            "done": True,
            "opencode_json_event_count": opencode["json_event_count"],
            "opencode_terminal_success_event_count": opencode[
                "terminal_success_event_count"
            ],
            "opencode_typed_error_count": 0,
        },
    }


def _ordinary_round(value: object, *, final: bool) -> Mapping[str, Any]:
    observed = _exact_mapping(
        value,
        {
            "round",
            "requested_tool_choice",
            "effective_tool_choice",
            "ordinary_tool_count",
            "ordinary_tool_name_sha256",
            "provider_memory_tool_count",
            "excluded_memory_tool_count",
            "assistant_tool_call_count",
            "tool_result_count",
            "matching_tool_result_count",
            "tool_call_id_sha256",
            "provider_finish_reason",
            "provider_payload_ordinary_tool_count",
            "tool_call_delivery",
            "delivered_tool_call_count",
            "delivered_tool_name_sha256",
            "delivered_tool_call_id_sha256",
        },
        "ORDINARY_ROUND_INVALID",
    )
    expected = {
        "round": "FINAL" if final else "CALL",
        "requested_tool_choice": "AUTO",
        "effective_tool_choice": "NONE" if final else "NAMED",
        "ordinary_tool_count": 1,
        "ordinary_tool_name_sha256": _READ_SHA256,
        "provider_memory_tool_count": 0,
        "excluded_memory_tool_count": 1,
        "assistant_tool_call_count": 1 if final else 0,
        "tool_result_count": 1 if final else 0,
        "matching_tool_result_count": 1 if final else 0,
        "tool_call_id_sha256": observed["tool_call_id_sha256"] if final else None,
        "provider_finish_reason": "stop",
        "provider_payload_ordinary_tool_count": 1 if final else 0,
        "tool_call_delivery": (
            "NATIVE_NONE" if final else "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER"
        ),
        "delivered_tool_call_count": 0 if final else 1,
        "delivered_tool_name_sha256": None if final else _READ_SHA256,
        "delivered_tool_call_id_sha256": None
        if final
        else observed["delivered_tool_call_id_sha256"],
    }
    if dict(observed) != expected:
        raise InteractionScenarioError("ORDINARY_ROUND_INVALID")
    if final:
        _sha(observed["tool_call_id_sha256"], "ORDINARY_TOOL_PAIR_INVALID")
    else:
        _sha(observed["delivered_tool_call_id_sha256"], "ORDINARY_TOOL_PAIR_INVALID")
    return observed


def _reduce_ordinary(
    plan: InteractionPlan, observation: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(observation, Mapping) or "delivery" not in observation:
        raise InteractionScenarioError("ORDINARY_DELIVERY_INVALID")
    value = _exact_mapping(
        observation,
        {"rounds", "provider", "mcp", "host", "delivery", "persistence"},
        "ORDINARY_OBSERVATION_INVALID",
    )
    rounds = value["rounds"]
    if (
        not isinstance(rounds, Sequence)
        or isinstance(rounds, (str, bytes))
        or len(rounds) != 2
    ):
        raise InteractionScenarioError("ORDINARY_ROUND_COUNT_INVALID")
    first = _ordinary_round(rounds[0], final=False)
    second = _ordinary_round(rounds[1], final=True)
    host = _exact_mapping(
        value["host"],
        {
            "tool_execution_count",
            "tool_name_sha256",
            "tool_call_id_sha256",
            "tool_result_call_id_sha256",
            "third_round_observed",
        },
        "ORDINARY_HOST_INVALID",
    )
    call_id = _sha(first["delivered_tool_call_id_sha256"], "ORDINARY_TOOL_PAIR_INVALID")
    if (
        host["tool_execution_count"] != 1
        or host["tool_name_sha256"] != _READ_SHA256
        or host["tool_call_id_sha256"] != call_id
        or host["tool_result_call_id_sha256"] != call_id
        or second["tool_call_id_sha256"] != call_id
        or host["third_round_observed"] is not False
    ):
        raise InteractionScenarioError("ORDINARY_TOOL_PAIR_INVALID")
    provider = _exact_mapping(
        value["provider"],
        {
            "attempts",
            "automatic_retries",
            "terminal_count",
            "post_terminal_count",
            "logical_request_ids_unique",
            "third_round_observed",
        },
        "ORDINARY_PROVIDER_INVALID",
    )
    if provider != {
        "attempts": 2,
        "automatic_retries": 0,
        "terminal_count": 2,
        "post_terminal_count": 2,
        "logical_request_ids_unique": True,
        "third_round_observed": False,
    }:
        raise InteractionScenarioError("ORDINARY_PROVIDER_INVALID")
    mcp = _exact_mapping(
        value["mcp"], {"calls", "automatic_retries"}, "ORDINARY_MCP_INVALID"
    )
    if mcp != {"calls": 0, "automatic_retries": 0}:
        raise InteractionScenarioError("ORDINARY_MCP_INVALID")
    delivery = _exact_mapping(
        value["delivery"],
        {
            "incoming_tool_choice",
            "provider_tool_choice",
            "provider_tool_count",
            "native_finish_reason",
            "native_tool_call_count",
            "delivery_owner",
            "client_finish_reason",
            "delivered_read_count",
        },
        "ORDINARY_DELIVERY_INVALID",
    )
    expected_delivery = {
        "incoming_tool_choice": "AUTO",
        "provider_tool_choice": "ABSENT",
        "provider_tool_count": 0,
        "native_finish_reason": "stop",
        "native_tool_call_count": 0,
        "delivery_owner": "HOST_ADAPTER",
        "client_finish_reason": "tool_calls",
        "delivered_read_count": 1,
    }
    if (
        any(
            not isinstance(delivery[field], int) or isinstance(delivery[field], bool)
            for field in (
                "provider_tool_count",
                "native_tool_call_count",
                "delivered_read_count",
            )
        )
        or dict(delivery) != expected_delivery
        or delivery["incoming_tool_choice"] != first["requested_tool_choice"]
        or delivery["provider_tool_count"]
        != first["provider_payload_ordinary_tool_count"]
        or delivery["native_finish_reason"] != first["provider_finish_reason"]
        or delivery["delivered_read_count"] != first["delivered_tool_call_count"]
        or delivery["delivered_read_count"] != host["tool_execution_count"]
    ):
        raise InteractionScenarioError("ORDINARY_DELIVERY_INVALID")
    _persistence(
        value["persistence"],
        {"tool_arguments", "tool_result", "prompt", "credentials"},
    )
    return {
        "schema": _SCHEMA,
        "status": "PASS",
        "case_id": plan.case_id,
        "memory_need": plan.memory_need,
        "provider_rounds": 2,
        "mcp_calls": 0,
        "automatic_retries": 0,
        "visible_milai_tool_count": 0,
        "provider_call_policy": {
            "provider_calls_per_model_round_maximum": 1,
            "model_rounds": plan.provider_rounds,
            "calls_per_task_operation": plan.provider_rounds,
            "case_maximum": plan.provider_rounds,
        },
        "ordinary_tool": {
            "policy": plan.ordinary_tool_policy,
            "tool_name_sha256": _READ_SHA256,
            "tool_call_id_sha256": call_id,
            "execution_count": 1,
            "final_tool_choice": "NONE",
            "tool_call_delivery": first["tool_call_delivery"],
            "native_provider_finish_reasons": [
                first["provider_finish_reason"],
                second["provider_finish_reason"],
            ],
            "third_round_observed": False,
            **dict(delivery),
        },
    }


def reduce_interaction(case_id: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce one content-free structural observation into a bounded PASS receipt."""

    plan = interaction_plan(case_id)
    if not isinstance(observation, Mapping):
        raise InteractionScenarioError("INTERACTION_OBSERVATION_INVALID")
    return (
        _reduce_stream(plan, observation)
        if case_id == "U1-STREAM"
        else _reduce_ordinary(plan, observation)
    )
