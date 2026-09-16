from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from milai_client import (
    AccessOutcome,
    AgentRecallPolicy,
    CanonicalStateKey,
    ContextBudgetInfeasibleError,
    ContextIntegrityError,
    DeterministicMemoryNeedResolver,
    DeterministicQueryOnlyIntentShadow,
    MemoryNeedResolution,
    TaskBindingContext,
    TaskMemoryBudget,
    TaskMemoryIdentity,
    TaskMemoryState,
    TaskPreparedContext,
    TokenBudget,
)
from milai_client.context_policy import PrefetchContext, prepare_prefetch

from milai_openworker_mcp import TargetTokenizerCounter, build_task_memory_controller
from milai_openworker_mcp.broker import BrokerError, Policy
from milai_openworker_mcp.provider_execution import (
    BudgetError,
    CapabilityError,
    DevRunCapability,
    JsonCompletionTransport,
    ProviderCallError,
    ProviderExecutionGateway,
    ProviderRequest,
    ProviderTransportError,
    StreamCompletionTransport,
    _SseObserver,
)
from milai_openworker_mcp.task_binding import (
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
    HostTaskRegistry,
    HostTaskRelationEvent,
    NativeTaskMetadata,
    SameProcessTaskRegistry,
    TaskBindingConflict,
    TaskBindingError,
    TaskResolution,
    bind_host_task,
)
from milai_openworker_mcp.transport import McpUnixClient, McpUnixClientError

MAX_BODY_BYTES = 2 * 1024 * 1024
EXACT_MODEL_ID = "Qwen3.6-35B-A3B-FP8"
MODEL_ID = EXACT_MODEL_ID
_FIXTURE_SHA256 = "47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555"
_PROVIDER_FIELDS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "stream_options",
        "tools",
        "tool_choice",
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "response_format",
    }
)
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
_ORDINARY_READ_PATH = "/openworker/runtime/opencode.json"
_VLLM_JSON_SCHEMA_NAMED_TOOL = "VLLM_JSON_SCHEMA_NAMED_TOOL_ADAPTER"
_IDENTIFIER_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_HEADER_NAMES = (
    "X-MiLAi-Host-Instance",
    "X-MiLAi-Task-Session",
    "X-MiLAi-Task-Operation",
)
_TASK_EVENTS = frozenset(
    {
        "TASK_START",
        "GOAL_CHANGED",
        "EXPLICIT_MEMORY_REQUEST",
        "KNOWN_OBJECT",
        "TOOL_RESULT",
        "MEMORY_AFFECTING_TOOL_RESULT",
        "MODEL_RETRY",
        "CANONICAL_POSITION_CHANGED",
        "ACTION_PROPOSED",
    }
)
_HOST_PREFETCH_MODES = frozenset({"prefetch", "query-first"})


class OpenWorkerAdapterError(RuntimeError):
    pass


class OrdinaryToolCompatibilityError(OpenWorkerAdapterError):
    """A deterministic structured-output-to-tool-call conversion failure."""


@dataclass(frozen=True, slots=True)
class StartupTaskPolicy:
    profile: str
    scope: dict[str, Any]
    required_authority: str
    consistency_floor: str
    max_limit: int
    state_keys: tuple[CanonicalStateKey, ...]
    broker_policy_sha256: str
    task_fixture_sha256: str


@dataclass(frozen=True, slots=True)
class StreamingCompletion:
    chunks: Iterator[bytes]


@dataclass(frozen=True, slots=True)
class OpenAIChatRequest:
    payload: dict[str, Any]
    messages: tuple[dict[str, Any], ...]
    stream: bool
    max_tokens: int | None

    @classmethod
    def parse(cls, value: object) -> OpenAIChatRequest:
        if not isinstance(value, Mapping):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        unsupported = set(value) - _PROVIDER_FIELDS
        if unsupported:
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_UNSUPPORTED")
        if value.get("model") != EXACT_MODEL_ID:
            raise OpenWorkerAdapterError("PROVIDER_MODEL_UNSUPPORTED")
        if "messages" not in value or "stream" not in value:
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        stream = value.get("stream")
        if not isinstance(stream, bool):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        stream_options = value.get("stream_options")
        if stream:
            if stream_options != {"include_usage": True}:
                raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        elif "stream_options" in value:
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")

        raw_messages = value.get("messages")
        if (
            not isinstance(raw_messages, Sequence)
            or isinstance(raw_messages, (str, bytes))
            or not raw_messages
        ):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        messages: list[dict[str, Any]] = []
        for message in raw_messages:
            if not isinstance(message, Mapping) or message.get("role") not in _MESSAGE_ROLES:
                raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
            if message.get("role") == "tool" and (
                not isinstance(message.get("tool_call_id"), str)
                or not message["tool_call_id"].strip()
            ):
                raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
            messages.append(dict(message))

        tools = value.get("tools")
        if tools is not None and (
            not isinstance(tools, Sequence)
            or isinstance(tools, (str, bytes))
            or any(not isinstance(tool, Mapping) for tool in tools)
        ):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        tool_choice = value.get("tool_choice")
        if tool_choice is not None and not isinstance(tool_choice, (str, Mapping)):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        for name in ("temperature", "top_p"):
            setting = value.get(name)
            if setting is not None and (
                not isinstance(setting, (int, float)) or isinstance(setting, bool)
            ):
                raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        max_tokens = value.get("max_tokens")
        if max_tokens is not None and (
            not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1
        ):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        seed = value.get("seed")
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        response_format = value.get("response_format")
        if response_format is not None and not isinstance(response_format, Mapping):
            raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
        return cls(dict(value), tuple(messages), stream, max_tokens)

    def provider_payload(
        self,
        rendered_context: str | None,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        direct_choice = _tool_choice_name(self.payload.get("tool_choice"))
        if direct_choice is not None and _is_memory_tool(direct_choice):
            raise OpenWorkerAdapterError("PROVIDER_MEMORY_TOOL_VISIBLE")
        payload = dict(self.payload)
        messages = [dict(message) for message in self.messages]
        if rendered_context is not None:
            context_block = "MILAI_CONTEXT_BEGIN\n" + rendered_context + "\nMILAI_CONTEXT_END"
            system_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.get("role") == "system"
                ),
                None,
            )
            if system_index is None:
                messages.insert(0, {"role": "system", "content": context_block})
            else:
                system_message = messages[system_index]
                original_content = system_message.get("content")
                if not isinstance(original_content, str):
                    raise OpenWorkerAdapterError("PROVIDER_REQUEST_INVALID")
                separator = "\n\n" if original_content else ""
                system_message["content"] = original_content + separator + context_block
        payload["messages"] = messages
        excluded: list[str] = []
        raw_tools = self.payload.get("tools")
        if isinstance(raw_tools, Sequence) and not isinstance(raw_tools, (str, bytes)):
            ordinary_tools: list[object] = []
            for tool in raw_tools:
                name = _tool_definition_name(tool)
                if name is not None and _is_memory_tool(name):
                    excluded.append(name)
                else:
                    ordinary_tools.append(tool)
            if ordinary_tools:
                payload["tools"] = ordinary_tools
            else:
                payload.pop("tools", None)
                if payload.get("tool_choice") == "auto":
                    payload.pop("tool_choice")
        return payload, tuple(excluded)


def _tool_definition_name(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    function = value.get("function")
    name = function.get("name") if isinstance(function, Mapping) else None
    return name if isinstance(name, str) else None


def _tool_choice_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    function = value.get("function")
    name = function.get("name") if isinstance(function, Mapping) else None
    return name if isinstance(name, str) else None


def _is_memory_tool(name: str) -> bool:
    return name in {"milai_recall", "milai_memory_resolve"} or name.endswith(
        ("_milai_recall", "_milai_memory_resolve")
    )


def _apply_single_ordinary_tool_required_once(
    payload: dict[str, Any], tool_name: str
) -> dict[str, Any]:
    """Adapt one explicit ordinary tool turn to vLLM's named/none capability.

    This is deliberately not general ``auto`` tool choice emulation.  It is a
    fail-closed compatibility contract for one synchronous ``read`` call:
    named function calling on the first provider round and ``none`` only after
    the matching OpenCode tool result is present on the second round.
    """

    if tool_name != "read":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes)):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    ordinary_names = [_tool_definition_name(tool) for tool in raw_tools]
    if ordinary_names != [tool_name]:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    if payload.get("tool_choice") != "auto":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_CHOICE_INVALID")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    messages = list(raw_messages)
    last_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], Mapping) and messages[index].get("role") == "user"
        ),
        None,
    )
    if last_user is None:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    suffix = messages[last_user + 1 :]
    tool_name_sha256 = hashlib.sha256(tool_name.encode()).hexdigest()
    if not suffix:
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_name},
        }
        return {
            "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
            "round": "CALL",
            "requested_tool_choice": "AUTO",
            "effective_tool_choice": "NAMED",
            "ordinary_tool_count": 1,
            "ordinary_tool_name_sha256": tool_name_sha256,
            "assistant_tool_call_count": 0,
            "tool_result_count": 0,
            "matching_tool_result_count": 0,
            "tool_call_id_sha256": None,
        }

    if (
        len(suffix) != 2
        or not isinstance(suffix[0], Mapping)
        or suffix[0].get("role") != "assistant"
        or not isinstance(suffix[1], Mapping)
        or suffix[1].get("role") != "tool"
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    raw_calls = suffix[0].get("tool_calls")
    if (
        not isinstance(raw_calls, Sequence)
        or isinstance(raw_calls, (str, bytes))
        or len(raw_calls) != 1
        or not isinstance(raw_calls[0], Mapping)
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    call = raw_calls[0]
    function = call.get("function")
    call_id = call.get("id")
    arguments = function.get("arguments") if isinstance(function, Mapping) else None
    if (
        call.get("type") != "function"
        or not isinstance(call_id, str)
        or not call_id.strip()
        or not isinstance(function, Mapping)
        or function.get("name") != tool_name
        or not isinstance(arguments, str)
        or suffix[1].get("tool_call_id") != call_id
    ):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    try:
        decoded_arguments = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID") from exc
    if not isinstance(decoded_arguments, Mapping):
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_STATE_INVALID")
    payload["tool_choice"] = "none"
    return {
        "policy": "SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE",
        "round": "FINAL",
        "requested_tool_choice": "AUTO",
        "effective_tool_choice": "NONE",
        "ordinary_tool_count": 1,
        "ordinary_tool_name_sha256": tool_name_sha256,
        "assistant_tool_call_count": 1,
        "tool_result_count": 1,
        "matching_tool_result_count": 1,
        "tool_call_id_sha256": hashlib.sha256(call_id.encode()).hexdigest(),
    }


def _apply_vllm_json_schema_named_tool_compatibility(
    payload: dict[str, Any], policy: Mapping[str, Any]
) -> bool:
    """Use vLLM structured output when its server has no tool parser.

    Only the forced first ``read`` round is adapted.  The upstream response is
    later validated in memory and rendered back to the OpenAI tool-call shape;
    the final round keeps the paired tool result and ``tool_choice=none``.
    """

    if policy.get("round") != "CALL":
        return False
    if payload.get("response_format") is not None:
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_CONFLICT")
    if [_tool_definition_name(tool) for tool in payload.get("tools", [])] != [
        "read"
    ] or _tool_choice_name(payload.get("tool_choice")) != "read":
        raise OpenWorkerAdapterError("PROVIDER_SINGLE_ORDINARY_TOOL_INVALID")
    payload.pop("tools")
    payload.pop("tool_choice")
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "dg13u_read_arguments",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"filePath": {"type": "string", "enum": [_ORDINARY_READ_PATH]}},
                "required": ["filePath"],
                "additionalProperties": False,
            },
        },
    }
    return True


def _ordinary_read_completion(
    native_request_id: str, *, prompt_tokens: int, completion_tokens: int
) -> dict[str, Any]:
    arguments = {"filePath": _ORDINARY_READ_PATH}
    call_id = (
        "call_"
        + hashlib.sha256(native_request_id.encode() + b":" + _canonical(arguments)).hexdigest()[:24]
    )
    return {
        "id": native_request_id,
        "object": "chat.completion",
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "read",
                                "arguments": _canonical(arguments).decode(),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _vllm_json_schema_named_tool_chunks(source: Iterator[bytes]) -> Iterator[bytes]:
    """Validate a native structured-output stream, then deliver one read call."""

    observer = _SseObserver()
    content: list[str] = []
    try:
        for raw_chunk in source:
            observer.observe(raw_chunk)
            for line in raw_chunk.decode("utf-8", errors="strict").splitlines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                if not isinstance(event, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                choices = event.get("choices")
                if not isinstance(choices, list) or len(choices) > 1:
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if not choices:
                    if not isinstance(event.get("usage"), Mapping):
                        raise OrdinaryToolCompatibilityError(
                            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                        )
                    continue
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                delta = choice.get("delta")
                if not isinstance(delta, Mapping):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if "tool_calls" in delta or "function_call" in delta:
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if not set(delta).issubset({"content", "role", "reasoning", "reasoning_content"}):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                role = delta.get("role")
                if role is not None and role != "assistant":
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                for reasoning_field in ("reasoning", "reasoning_content"):
                    reasoning = delta.get(reasoning_field)
                    if reasoning not in {None, ""}:
                        raise OrdinaryToolCompatibilityError(
                            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                        )
                part = delta.get("content")
                if part is not None and not isinstance(part, str):
                    raise OrdinaryToolCompatibilityError(
                        "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
                    )
                if isinstance(part, str):
                    content.append(part)
    except OrdinaryToolCompatibilityError:
        raise
    except (UnicodeError, json.JSONDecodeError, ProviderTransportError) as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
    try:
        response = observer.response()
    except ProviderTransportError as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    try:
        arguments = json.loads("".join(content))
    except json.JSONDecodeError as exc:
        raise OrdinaryToolCompatibilityError(
            "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID"
        ) from exc
    if response.finish_reason != "stop" or arguments != {"filePath": _ORDINARY_READ_PATH}:
        raise OrdinaryToolCompatibilityError("PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_INVALID")
    completion = _ordinary_read_completion(
        response.native_request_id,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
    )
    yield _sse(completion)


def _authenticate_ingress(values: Sequence[str], expected_token: str) -> None:
    if len(values) != 1:
        raise OpenWorkerAdapterError("AUTHENTICATION_REQUIRED")
    supplied = values[0]
    prefix = "Bearer "
    if not supplied.startswith(prefix) or not hmac.compare_digest(
        supplied[len(prefix) :].encode(), expected_token.encode()
    ):
        raise OpenWorkerAdapterError("AUTHENTICATION_REQUIRED")


def _task_metadata_from_values(values: Mapping[str, Sequence[str]]) -> NativeTaskMetadata:
    try:
        selected = {name: tuple(values.get(name, ())) for name in _HEADER_NAMES}
        if any(len(items) != 1 for items in selected.values()):
            raise TaskBindingError("metadata header cardinality is invalid")
        return NativeTaskMetadata(
            host_instance=selected["X-MiLAi-Host-Instance"][0],
            task_session=selected["X-MiLAi-Task-Session"][0],
            task_operation=selected["X-MiLAi-Task-Operation"][0],
        )
    except (TaskBindingError, IndexError, TypeError) as exc:
        raise OpenWorkerAdapterError("TASK_METADATA_INVALID") from exc


def _load_ingress_token(path: Path) -> str:
    if not path.is_absolute():
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    try:
        current = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or stat.S_IMODE(current.st_mode) not in {0o400, 0o600}
        or current.st_uid not in {0, os.geteuid()}
    ):
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID") from exc
    if not 16 <= len(token) <= 256 or _IDENTIFIER_SAFE.fullmatch(token) is None:
        raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
    return token


def _load_startup_task_policy(
    broker_policy_path: Path,
    task_fixture_path: Path,
) -> StartupTaskPolicy:
    try:
        policy = Policy.load(broker_policy_path)
        fixture_raw = task_fixture_path.read_bytes()
        fixture = json.loads(fixture_raw)
    except (BrokerError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID") from exc
    if policy.profile != "reader-lite":
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    fixture_sha256 = hashlib.sha256(fixture_raw).hexdigest()
    if fixture_sha256 != _FIXTURE_SHA256 or not isinstance(fixture, Mapping):
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    if set(fixture) != {
        "schema",
        "status",
        "data_boundary",
        "formal_evaluation_input",
        "families",
    } or (
        fixture.get("schema") != "milai.dg13u.u1-candidate-fixture.v1"
        or fixture.get("data_boundary") != "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED"
        or fixture.get("formal_evaluation_input") is not False
    ):
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    families = fixture.get("families")
    if not isinstance(families, list) or len(families) != 3:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
    try:
        scope = json.loads(policy.scope_json)
        project_ids = scope.get("project_ids") if isinstance(scope, Mapping) else None
        if (
            not isinstance(project_ids, list)
            or not project_ids
            or any(not isinstance(project, str) or not project for project in project_ids)
        ):
            raise ValueError("scope project_ids are invalid")
        state_keys: list[CanonicalStateKey] = []
        fixture_projects: set[str] = set()
        for family in families:
            if not isinstance(family, Mapping) or set(family) != {
                "project",
                "state_key",
                "claim_type",
                "aliases",
            }:
                raise ValueError("fixture family is invalid")
            aliases = family.get("aliases")
            if (
                not isinstance(aliases, list)
                or not aliases
                or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
            ):
                raise ValueError("fixture aliases are invalid")
            project = family.get("project")
            if not isinstance(project, str):
                raise ValueError("fixture project is invalid")
            fixture_projects.add(project)
            state_keys.append(
                CanonicalStateKey(
                    subject=project,
                    predicate=str(family["state_key"]),
                    claim_type=str(family["claim_type"]),
                )
            )
        if (
            scope != {"project_ids": sorted(fixture_projects)}
            or policy.required_authority != "INFORMATIONAL"
            or policy.consistency_floor != "CANONICAL_REQUIRED"
            or policy.max_limit != 3
            or len(set(state_keys)) != 3
        ):
            raise ValueError("fixture scope or state keys are invalid")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID") from exc
    return StartupTaskPolicy(
        profile=policy.profile,
        scope=dict(scope),
        required_authority=policy.required_authority,
        consistency_floor=policy.consistency_floor,
        max_limit=policy.max_limit,
        state_keys=tuple(state_keys),
        broker_policy_sha256=policy.digest,
        task_fixture_sha256=fixture_sha256,
    )


@dataclass(frozen=True, slots=True)
class _BoundTaskState:
    state: TaskMemoryState
    binding_context: TaskBindingContext
    resolution: TaskResolution
    identity: TaskMemoryIdentity
    active_goal: str
    task_key: str
    event: str
    declared_event: str
    transition: str
    event_adjustment: str | None
    retained: PrefetchContext | None


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _nonnegative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(max(0.0, left - right), 3)


def _per_request_token_budget(total_tokens: int, max_native_requests: int) -> int:
    """Partition a run-level capability budget without over-reserving its first call."""

    per_request = total_tokens // max_native_requests
    if per_request < 1:
        raise OpenWorkerAdapterError("provider token budget is smaller than native request budget")
    return per_request


def _bounded_provider_timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 < float(value) <= 600
    ):
        raise ValueError("provider timeout must be between 0 and 600 seconds")
    return float(value)


def _requested_memory_route(
    bound: _BoundTaskState | None,
    resolution: MemoryNeedResolution | None,
    previous: MemoryNeedResolution | None,
) -> str:
    if resolution is None:
        return "L1"
    resolver_route = resolution.requested_route
    if (
        resolver_route != "NONE"
        and previous is not None
        and resolution.signature.need_signature_id == previous.signature.need_signature_id
        and bound is not None
        and bound.retained is not None
        and bound.binding_context.cache_reuse_constraint == "ELIGIBLE_FOR_VALIDATION"
        and bound.event
        not in {
            "GOAL_CHANGED",
            "MEMORY_AFFECTING_TOOL_RESULT",
            "CANONICAL_POSITION_CHANGED",
            "ACTION_PROPOSED",
        }
    ):
        return "CACHE"
    return resolver_route


def _shadow_route_trace(
    *,
    requested_route: str,
    actual_route: str,
    host_terminal: bool,
    runtime_trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Join the Host decision to payload-free Runtime execution observations."""
    if host_terminal:
        return {
            "need_signature_id": None,
            "requested_route": requested_route,
            "planned_route": actual_route,
            "validated_route": actual_route,
            "attempted_routes": [actual_route],
            "terminal_route": actual_route,
            "result": "HIT",
            "policy_override_reason": None,
            "fallback_reason": None,
            "next_route_recommended": None,
            "route_trace_complete": True,
            "trace_gap_reason": None,
            "query_embedding_calls": 0,
            "vector_calls": 0,
            "reranker_calls": 0,
            "exact_calls": 0,
            "fts_calls": 0,
            "l0_calls": 0,
        }
    if runtime_trace is not None and runtime_trace.get("route_trace_complete") is True:
        propagated_requested_route = runtime_trace.get("requested_route")
        planned_route = runtime_trace.get("planned_route")
        validated_route = runtime_trace.get("validated_route")
        attempted_routes = runtime_trace.get("attempted_routes")
        terminal_route = runtime_trace.get("terminal_route")
        counters = {
            name: runtime_trace.get(name)
            for name in (
                "query_embedding_calls",
                "vector_calls",
                "reranker_calls",
                "exact_calls",
                "fts_calls",
                "l0_calls",
            )
        }
        complete = (
            propagated_requested_route == requested_route
            and isinstance(planned_route, str)
            and validated_route == planned_route
            and isinstance(terminal_route, str)
            and isinstance(attempted_routes, list)
            and all(isinstance(value, str) for value in attempted_routes)
            and all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in counters.values()
            )
            and runtime_trace.get("result") in {"HIT", "MISS", "BLOCKED", "ABSTAINED", "ERROR"}
        )
        return {
            "need_signature_id": runtime_trace.get("need_signature_id"),
            "requested_route": propagated_requested_route,
            "planned_route": planned_route,
            "validated_route": validated_route,
            "attempted_routes": attempted_routes,
            "terminal_route": terminal_route,
            "result": runtime_trace.get("result"),
            "policy_override_reason": runtime_trace.get("policy_override_reason"),
            "fallback_reason": runtime_trace.get("fallback_reason"),
            "next_route_recommended": runtime_trace.get("next_route_recommended"),
            "route_trace_complete": complete,
            "trace_gap_reason": (
                None
                if complete
                else (
                    "REQUESTED_ROUTE_PROPAGATION_MISMATCH"
                    if propagated_requested_route != requested_route
                    else "RUNTIME_ROUTE_TRACE_INVALID"
                )
            ),
            **counters,
            **(
                {"progressive_l1": dict(runtime_trace["progressive_l1"])}
                if isinstance(runtime_trace.get("progressive_l1"), Mapping)
                else {}
            ),
        }
    return {
        "need_signature_id": None,
        "requested_route": requested_route,
        "planned_route": None,
        "validated_route": None,
        "attempted_routes": [actual_route],
        "terminal_route": actual_route,
        "result": "ERROR",
        "policy_override_reason": None,
        "fallback_reason": None,
        "next_route_recommended": None,
        "route_trace_complete": False,
        "trace_gap_reason": "VALIDATED_ROUTE_NOT_EXPOSED_PRECHANGE",
        "query_embedding_calls": None,
        "vector_calls": None,
        "reranker_calls": None,
        "exact_calls": None,
        "fts_calls": None,
        "l0_calls": None,
    }


def _query_only_intent_shadow_trace(
    query: str,
    *,
    current_resolution: MemoryNeedResolution | None,
    current_effective_route: str,
) -> dict[str, object]:
    """Compare query-only reachability with the current Host-gated route.

    The returned event is payload-free and observational.  It cannot alter the
    current route, capability, scope, provider decision, or Runtime request.
    """
    shadow = DeterministicQueryOnlyIntentShadow().interpret(
        query, invocation_mode="PREFETCH_AUTO"
    )
    current_intent = (
        current_resolution.signature.intent_class
        if current_resolution is not None and current_effective_route != "NONE"
        else "NONE"
    )
    current_reason = (
        current_resolution.reason_code if current_resolution is not None else "TASK_UNAVAILABLE"
    )
    return {
        "interpreter_version": shadow.interpreter_version,
        "query_fingerprint": hashlib.sha256(
            (shadow.interpreter_version + "\0" + query).encode()
        ).hexdigest(),
        "query_only_intent": shadow.intent,
        "query_only_requirement": shadow.requirement,
        "query_only_reason": shadow.reason_code,
        "current_task_gated_intent": current_intent,
        "current_task_gated_route": current_effective_route,
        "current_task_gated_reason": current_reason,
        "intent_route_disagreement": (
            shadow.intent in {"POSSIBLE", "REQUIRED"} and current_effective_route == "NONE"
        ),
        "shadow_changed_production_result": False,
    }


def _host_access_trace_link(
    *,
    attempt_trace_id: str,
    retrieval_trace_id: str | None,
    timing: Mapping[str, float],
    host_total_ms: float,
) -> dict[str, object]:
    uds_roundtrip_ms = timing.get("uds_roundtrip_ms")
    mcp_handler_ms = timing.get("mcp_handler_ms")
    runtime_total_ms = timing.get("runtime_total_ms")
    return {
        "schema_version": "access-trace-link-v0.1",
        "host_attempt_trace_id": attempt_trace_id,
        "retrieval_trace_id": retrieval_trace_id,
        "spans": {
            "host_total_ms": round(host_total_ms, 3),
            "broker_ipc_ms": _nonnegative_difference(uds_roundtrip_ms, mcp_handler_ms),
            "uds_roundtrip_ms": uds_roundtrip_ms,
            "mcp_handler_ms": mcp_handler_ms,
            "runtime_total_ms": runtime_total_ms,
            "context_compile_ms": timing.get("context_compile_ms", 0.0),
        },
    }


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
        if isinstance(name, str) and _is_memory_tool(name):
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


def _native_request_observation(
    incoming: OpenAIChatRequest, metadata: NativeTaskMetadata
) -> dict[str, Any]:
    tools = incoming.payload.get("tools")
    tool_count = (
        len(tools) if isinstance(tools, Sequence) and not isinstance(tools, (str, bytes)) else 0
    )
    question = _question(incoming.messages)
    return {
        "event": "HOST_NATIVE_REQUEST_OBSERVED",
        "model": incoming.payload["model"],
        "stream": incoming.stream,
        "stream_include_usage": incoming.payload.get("stream_options") == {"include_usage": True},
        "max_tokens": incoming.max_tokens,
        "message_count": len(incoming.messages),
        "message_roles": [str(message["role"]) for message in incoming.messages],
        "tool_count": tool_count,
        "has_tool_result": any(message.get("role") == "tool" for message in incoming.messages),
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "task_session_sha256": hashlib.sha256(metadata.task_session.encode()).hexdigest(),
        "task_operation_sha256": hashlib.sha256(metadata.task_operation.encode()).hexdigest(),
    }


def _recall_query(question: str) -> str:
    return question[:2000]


def _should_recall(memory_mode: str) -> bool:
    if memory_mode == "none":
        return False
    if memory_mode in _HOST_PREFETCH_MODES:
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
    memory_call_ids: set[str] = set()
    for message in messages:
        if message.get("role") != "assistant":
            continue
        raw_calls = message.get("tool_calls")
        if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
            continue
        for call in raw_calls:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            name = function.get("name") if isinstance(function, Mapping) else None
            call_id = call.get("id")
            if (
                isinstance(name, str)
                and _is_memory_tool(name)
                and isinstance(call_id, str)
                and call_id.strip()
            ):
                memory_call_ids.add(call_id)
    for message in reversed(messages):
        if message.get("role") != "tool" or message.get("tool_call_id") not in memory_call_ids:
            continue
        found = _recall_object(message.get("content"))
        if found is not None:
            return found
    return None


def _prepared_prefetch(prepared: TaskPreparedContext) -> PrefetchContext:
    if prepared.outcome.provider_execution == "PROHIBITED":
        return PrefetchContext.unavailable(prepared.outcome.reason_code or prepared.outcome.status)
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


def _resolve_prepared_context(
    prepared: TaskPreparedContext, retained: PrefetchContext | None
) -> PrefetchContext:
    if prepared.status != "UNCHANGED":
        return _prepared_prefetch(prepared)
    if retained is None:
        raise OpenWorkerAdapterError("UNCHANGED task context retained host slot is absent")
    if retained.context_sha256 != prepared.outcome.context_digest:
        raise OpenWorkerAdapterError("UNCHANGED task context retained host slot digest mismatch")
    return retained


def _transport_unavailable_outcome(payload: Mapping[str, Any], reason_code: str) -> AccessOutcome:
    """Create the frozen fail-closed outcome for a Host-to-MCP transport failure."""

    return AccessOutcome(
        status="MEMORY_REQUIRED_BUT_UNAVAILABLE",
        execution_action="RETRY",
        provider_execution="PROHIBITED",
        terminal_stage="TRANSPORT",
        context_digest=None,
        canonical_position=None,
        reason_code=reason_code,
        trace_id="host-mcp-transport:" + hashlib.sha256(_canonical(payload)).hexdigest(),
    )


def _memory_terminal_completion(
    payload: Mapping[str, Any], outcome: AccessOutcome
) -> dict[str, Any]:
    """Render a typed terminal without invoking the answer provider."""

    request_id = "chatcmpl-unavailable-" + hashlib.sha256(_canonical(payload)).hexdigest()[:18]
    answer = {
        "answer": "UNKNOWN",
        "status": outcome.status,
        "memory_used": False,
        "memory_outcome": outcome.status,
        "execution_action": outcome.execution_action,
        "provider_execution": outcome.provider_execution,
        "terminal_stage": outcome.terminal_stage,
        "reason_code": outcome.reason_code,
        "trace_id": outcome.trace_id,
    }
    return _completion(
        request_id=request_id,
        content=_canonical(answer).decode(),
        finish_reason="stop",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )


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
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
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
        b"".join(b"data: " + _canonical(event) + b"\n\n" for event in events) + b"data: [DONE]\n\n"
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
        broker_policy: Path | None = None,
        task_fixture: Path | None = None,
        task_session_id: str | None = None,
        provider_timeout_seconds: float = 60,
        single_ordinary_tool_required_once: str | None = None,
        ordinary_tool_provider_compatibility: str | None = None,
    ) -> None:
        if memory_mode not in {"auto", "none", *_HOST_PREFETCH_MODES}:
            raise ValueError("unknown memory mode")
        host_prefetch = memory_mode in _HOST_PREFETCH_MODES
        if host_prefetch and prefetch_socket is None:
            raise ValueError("prefetch mode requires a host MCP socket")
        if not host_prefetch and prefetch_socket is not None:
            raise ValueError("host MCP socket is only valid in prefetch mode")
        if host_prefetch and tokenizer_json is None:
            raise ValueError("prefetch mode requires the target tokenizer.json")
        if not host_prefetch and tokenizer_json is not None:
            raise ValueError("target tokenizer is only valid in prefetch mode")
        if host_prefetch and (broker_policy is None or task_fixture is None):
            raise ValueError("prefetch mode requires broker policy and task fixture")
        if not host_prefetch and (broker_policy is not None or task_fixture is not None):
            raise ValueError("startup task policy is only valid in prefetch mode")
        if host_prefetch and task_session_id is not None:
            raise ValueError("prefetch task identity must come from native headers")
        if task_session_id is not None and (
            not task_session_id.strip() or len(task_session_id) > 256
        ):
            raise ValueError("task_session_id must contain 1-256 characters")
        if single_ordinary_tool_required_once not in {None, "read"}:
            raise ValueError("single ordinary tool compatibility only supports read")
        if ordinary_tool_provider_compatibility not in {
            None,
            _VLLM_JSON_SCHEMA_NAMED_TOOL,
        }:
            raise ValueError("unknown ordinary tool provider compatibility")
        if (
            ordinary_tool_provider_compatibility is not None
            and single_ordinary_tool_required_once != "read"
        ):
            raise ValueError("ordinary provider compatibility requires the read policy")
        self.gateway = ProviderExecutionGateway(manifest, ledger)
        self.transport = JsonCompletionTransport()
        self.stream_transport = StreamCompletionTransport()
        capability = DevRunCapability.load(manifest)
        next_logical_request_sequence = self.gateway.next_logical_request_sequence()
        if capability.model_id != EXACT_MODEL_ID:
            raise ValueError("provider capability model is not the frozen U1 model")
        self.provider_capability = capability
        self.provider_timeout_seconds = _bounded_provider_timeout(provider_timeout_seconds)
        self.single_ordinary_tool_required_once = single_ordinary_tool_required_once
        self.ordinary_tool_provider_compatibility = ordinary_tool_provider_compatibility
        self.run_id = capability.run_id
        self.trace = trace
        self.memory_mode = memory_mode
        self.task_session_id = task_session_id.strip() if task_session_id is not None else None
        self.task_free_context_locators: dict[str, str] = {}
        self.host_mcp = McpUnixClient(prefetch_socket) if prefetch_socket is not None else None
        self.target_counter = (
            TargetTokenizerCounter(tokenizer_json) if tokenizer_json is not None else None
        )
        digest_input = {
            "integration": "milai-openworker-mcp-v1",
            "profile": "reader-lite",
            "model_id": capability.model_id,
            "representation": "grouped-compact/v3",
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
        self.startup_task_policy = (
            _load_startup_task_policy(broker_policy, task_fixture)
            if broker_policy is not None and task_fixture is not None
            else None
        )
        self.task_policy = AgentRecallPolicy(
            scope=(
                self.startup_task_policy.scope
                if self.startup_task_policy is not None
                else {"host_policy": "reader-lite"}
            ),
            authority=(
                self.startup_task_policy.required_authority
                if self.startup_task_policy is not None
                else "INFORMATIONAL"
            ),
            consistency_floor=(
                self.startup_task_policy.consistency_floor
                if self.startup_task_policy is not None
                else "CANONICAL_REQUIRED"
            ),
            max_limit=(
                self.startup_task_policy.max_limit if self.startup_task_policy is not None else 3
            ),
        )
        self.need_resolver = DeterministicMemoryNeedResolver()
        self.task_budget = TaskMemoryBudget(
            max_prepare_context_calls=64,
            max_full_recall_calls=20,
            max_delta_refreshes=8,
            max_memory_tokens_injected=10_240,
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
        self._native_bind_lock = threading.Lock()
        self._task_sequence = 0
        self.task_registry = HostTaskRegistry()
        self.native_task_registry = SameProcessTaskRegistry()
        self.task_relation_resolver = DeterministicTaskRelationResolver()
        self.task_transition_validator = DeterministicTaskTransitionValidator()
        self._active_task_key_by_task: dict[str, str] = {}
        self._last_need_by_task_key: dict[str, MemoryNeedResolution] = {}
        self._lock = threading.Lock()
        self._sequence = next_logical_request_sequence - 1
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

    def _record_ingress_terminal(self, http_status: int, exc: Exception) -> None:
        if isinstance(
            exc,
            (OpenWorkerAdapterError, ProviderCallError, BudgetError, CapabilityError),
        ):
            reason_code = str(exc)
        elif isinstance(exc, json.JSONDecodeError):
            reason_code = "JSON_DECODE_ERROR"
        else:
            reason_code = "VALUE_ERROR"
        self._record(
            {
                "event": "HOST_INGRESS_TERMINAL",
                "exception_type": type(exc).__name__,
                "http_status": http_status,
                "reason_code": reason_code,
            }
        )

    def _record_stream_terminal(self, exc: Exception) -> None:
        reason_code = (
            str(exc)
            if isinstance(exc, (ProviderCallError, BudgetError))
            else "STREAM_CONNECTION_CLOSED"
        )
        self._record(
            {
                "event": "HOST_STREAM_TERMINAL",
                "exception_type": type(exc).__name__,
                "http_status": 200,
                "reason_code": reason_code,
                "response_headers_committed": True,
                "status": "FAILED",
            }
        )

    def _logical_request_id(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"{self.run_id}-ow-{self._sequence:02d}"

    def _bind_task_state(
        self,
        incoming: Mapping[str, Any],
        *,
        declared_event: str | None,
    ) -> _BoundTaskState:
        raw_user = incoming.get("user")
        if isinstance(raw_user, str) and raw_user.strip():
            fallback_task_id = raw_user.strip()[:256]
        elif self.task_session_id is not None:
            fallback_task_id = self.task_session_id
        else:
            with self._task_lock:
                self._task_sequence += 1
                task_sequence = self._task_sequence
            fallback_task_id = (
                "openworker-request-"
                + hashlib.sha256(
                    _canonical({"run_id": self.run_id, "sequence": task_sequence})
                ).hexdigest()[:32]
            )
        try:
            state = TaskMemoryState.from_host_payload(
                incoming.get("milai_task_state"),
                fallback_task_id=fallback_task_id,
                fallback_scope=self.task_policy.scope,
                fallback_profile_id="reader-lite",
            )
        except ValueError as exc:
            raise OpenWorkerAdapterError("Host task-memory state was rejected") from exc
        if declared_event is not None and declared_event not in _TASK_EVENTS:
            raise OpenWorkerAdapterError("Host task-memory event is invalid")
        raw_relation = incoming.get("milai_task_relation")
        if raw_relation is not None and raw_relation not in {
            "CONTINUE",
            "SUBTASK",
            "SWITCH",
            "RETURN",
            "AMBIGUOUS",
        }:
            raise OpenWorkerAdapterError("Host task relation is invalid")
        raw_operation_id = incoming.get("milai_operation_id")
        if raw_operation_id is not None and (
            not isinstance(raw_operation_id, str)
            or not raw_operation_id.strip()
            or len(raw_operation_id) > 256
        ):
            raise OpenWorkerAdapterError("Host operation identity is invalid")
        try:
            binding_context, resolution = bind_host_task(
                self.task_registry,
                self.task_relation_resolver,
                self.task_transition_validator,
                state,
                HostTaskRelationEvent(
                    normalized_relation=raw_relation,
                    operation_id=raw_operation_id,
                    strong_suspended_task_id=(state.task_id if raw_relation == "RETURN" else None),
                ),
            )
        except TaskBindingConflict as exc:
            raise OpenWorkerAdapterError("Host task binding transition was rejected") from exc
        bound_identity = binding_context.identity_state
        state = TaskMemoryState(bound_identity, binding_context.memory_binding)
        transition = binding_context.transition.operation
        task_epoch = (
            "task-"
            + hashlib.sha256(
                f"{state.task_id}:{bound_identity.task_generation}".encode()
            ).hexdigest()[:32]
        )
        identity = TaskMemoryIdentity(
            tenant_id="mcp-socket-capability",
            session_id=state.task_id,
            agent_id="openworker",
            profile_id=state.profile_id,
            task_epoch=task_epoch,
        )
        task_key = hashlib.sha256(
            _canonical(
                {
                    "task_binding": state.binding_digest,
                    "task_epoch": task_epoch,
                }
            )
        ).hexdigest()
        event_adjustment: str | None = None
        if binding_context.registry_revision_before == 0:
            event = "TASK_START"
        elif binding_context.cache_reuse_constraint == "PROHIBITED":
            event = "GOAL_CHANGED"
        else:
            event = declared_event or "EXPLICIT_MEMORY_REQUEST"
        if event == "KNOWN_OBJECT" and not state.known_claim_ids and not state.known_state_keys:
            event = "EXPLICIT_MEMORY_REQUEST"
            event_adjustment = "KNOWN_OBJECT_WITHOUT_HOST_CLAIM_ID"
        with self._task_lock:
            previous_key = self._active_task_key_by_task.get(state.task_id)
            if previous_key is not None and (
                previous_key != task_key or binding_context.cache_reuse_constraint == "PROHIBITED"
            ):
                self._task_contexts.pop(previous_key, None)
            retained = (
                self._task_contexts.get(task_key)
                if binding_context.cache_reuse_constraint == "ELIGIBLE_FOR_VALIDATION"
                else None
            )
            if not binding_context.tentative:
                self._active_task_key_by_task[state.task_id] = task_key
        return _BoundTaskState(
            state=state,
            binding_context=binding_context,
            resolution=resolution,
            identity=identity,
            active_goal=state.active_goal_summary,
            task_key=task_key,
            event=event,
            declared_event=declared_event or "HOST_EVENT_ABSENT",
            transition=transition,
            event_adjustment=event_adjustment,
            retained=retained,
        )

    def _bind_native_task_state(
        self,
        metadata: NativeTaskMetadata,
        *,
        allow_operation_continuation: bool = False,
    ) -> _BoundTaskState:
        if self.startup_task_policy is None:
            raise OpenWorkerAdapterError("HOST_STARTUP_POLICY_INVALID")
        with self._native_bind_lock:
            try:
                native = self.native_task_registry.bind(
                    metadata,
                    allow_operation_continuation=allow_operation_continuation,
                )
            except TaskBindingConflict as exc:
                raise OpenWorkerAdapterError("TASK_OPERATION_REPLAY") from exc
            if native.invalidated_task_count:
                self.task_registry = HostTaskRegistry()
                with self._task_lock:
                    self._task_contexts.clear()
                    self._active_task_key_by_task.clear()
                    self._last_need_by_task_key.clear()
            state_payload = {
                "task_id": native.task_id,
                "active_goal_id": (
                    "openworker-session-"
                    + hashlib.sha256(metadata.task_session.encode()).hexdigest()[:24]
                ),
                "active_goal_version": 1,
                "active_goal_summary": "Continue the trusted OpenWorker session.",
                "project_scope": self.startup_task_policy.scope,
                "profile_id": self.startup_task_policy.profile,
                "execution_lane_id": native.task_id,
                "task_generation": native.task_generation,
                "binding_generation": native.task_generation,
                "known_state_keys": [
                    key.canonical() for key in self.startup_task_policy.state_keys
                ],
            }
            bound = self._bind_task_state(
                {
                    "milai_task_state": state_payload,
                    "milai_task_relation": ("CONTINUE" if native.relation == "CONTINUE" else None),
                    "milai_operation_id": native.operation_id,
                },
                declared_event=(
                    "TASK_START" if native.relation == "TASK_START" else "EXPLICIT_MEMORY_REQUEST"
                ),
            )
        self._record(
            {
                "event": "HOST_NATIVE_TASK_BOUND",
                "provider_call": False,
                "host_instance_sha256": hashlib.sha256(metadata.host_instance.encode()).hexdigest(),
                "task_session_sha256": hashlib.sha256(metadata.task_session.encode()).hexdigest(),
                "task_operation_sha256": hashlib.sha256(
                    metadata.task_operation.encode()
                ).hexdigest(),
                "task_id_sha256": hashlib.sha256(native.task_id.encode()).hexdigest(),
                "task_generation": native.task_generation,
                "task_relation": native.relation,
                "invalidated_task_count": native.invalidated_task_count,
                "profile": self.startup_task_policy.profile,
                "scope_sha256": hashlib.sha256(
                    _canonical(self.startup_task_policy.scope)
                ).hexdigest(),
                "broker_policy_sha256": self.startup_task_policy.broker_policy_sha256,
                "task_fixture_sha256": self.startup_task_policy.task_fixture_sha256,
            }
        )
        return bound

    def complete(
        self,
        incoming: OpenAIChatRequest,
        metadata: NativeTaskMetadata,
        *,
        request_parse_ms: float | None = None,
    ) -> tuple[dict[str, Any] | StreamingCompletion, str]:
        adapter_started = time.perf_counter()
        payload_input = incoming.payload
        messages = list(incoming.messages)
        incoming.provider_payload(None)  # validates direct memory-tool selection pre-MCP
        recall_name = _tool_name(payload_input.get("tools"))
        recall = (
            None
            if self.memory_mode in _HOST_PREFETCH_MODES
            else _recall_from_messages(messages)
        )
        question = _question(messages)
        question_sha256 = hashlib.sha256(question.encode()).hexdigest()
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        self._record(_native_request_observation(incoming, metadata))
        memory_control_ms: float | None = None
        memory_source = "NO_MEMORY"
        mcp_calls = 0
        context: PrefetchContext | None = None
        prepared: TaskPreparedContext | None = None
        bound = (
            self._bind_native_task_state(
                metadata,
                allow_operation_continuation=has_tool_result,
            )
            if self.memory_mode in _HOST_PREFETCH_MODES and recall is None
            else None
        )
        turn_authority = self.task_policy.authority
        turn_policy = (
            AgentRecallPolicy(
                scope=bound.state.project_scope,
                authority=turn_authority,
                consistency_floor=self.task_policy.consistency_floor,
                max_limit=self.task_policy.max_limit,
            )
            if bound is not None
            else self.task_policy
        )
        previous_need_resolution = (
            self._last_need_by_task_key.get(bound.task_key) if bound is not None else None
        )
        need_resolution = (
            self.need_resolver.resolve(
                question,
                scope=bound.state.project_scope,
                required_authority=turn_policy.authority,
                consistency_floor=turn_policy.consistency_floor,
                known_state_keys=bound.state.known_state_keys,
                known_claim_ids=bound.state.known_claim_ids,
                open_issue_ids=bound.state.relevant_open_issue_ids,
                canonical_position_seen=bound.state.canonical_position_seen,
                previous=previous_need_resolution,
            )
            if self.memory_mode == "prefetch" and recall is None and bound is not None
            else None
        )
        requested_memory_route = _requested_memory_route(
            bound,
            need_resolution,
            previous_need_resolution,
        )
        if self.memory_mode in _HOST_PREFETCH_MODES and recall is None:
            current_effective_route = (
                "NONE"
                if bound is None or bound.binding_context.tentative
                else requested_memory_route
            )
            self._record(
                {
                    "event": "HOST_QUERY_ONLY_INTENT_SHADOW",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **_query_only_intent_shadow_trace(
                        question,
                        current_resolution=need_resolution,
                        current_effective_route=current_effective_route,
                    ),
                }
            )
        if need_resolution is not None:
            if need_resolution.signature.intent_class != "NONE":
                self._last_need_by_task_key[bound.task_key] = need_resolution
            self._record(
                {
                    "event": "HOST_MEMORY_NEED_RESOLVED",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "need_signature_id": need_resolution.signature.need_signature_id,
                    "intent_class": need_resolution.signature.intent_class,
                    "temporal_need": need_resolution.signature.temporal_need,
                    "evidence_need": need_resolution.signature.evidence_need,
                    "resolver_route": need_resolution.requested_route,
                    "requested_route": requested_memory_route,
                    "state_key_ref_present": need_resolution.state_key_ref is not None,
                    "state_key_ref_sha256": (
                        hashlib.sha256(
                            _canonical(need_resolution.state_key_ref.to_api())
                        ).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_subject_sha256": (
                        hashlib.sha256(need_resolution.state_key_ref.subject.encode()).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_predicate_sha256": (
                        hashlib.sha256(need_resolution.state_key_ref.predicate.encode()).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_claim_type_sha256": (
                        hashlib.sha256(
                            need_resolution.state_key_ref.claim_type.encode()
                        ).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "resolver_model_calls": need_resolution.resolver_model_calls,
                    "resolver_embedding_calls": need_resolution.resolver_embedding_calls,
                    "resolver_retrieval_calls": need_resolution.resolver_retrieval_calls,
                }
            )
        if bound is not None:
            self._record(
                {
                    "event": "HOST_TASK_STATE_SHADOW",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "task_id_sha256": hashlib.sha256(bound.state.task_id.encode()).hexdigest(),
                    "task_epoch": bound.identity.task_epoch,
                    "active_goal_id_sha256": hashlib.sha256(
                        bound.state.active_goal_id.encode()
                    ).hexdigest(),
                    "active_goal_version": bound.state.active_goal_version,
                    "active_goal_sha256": hashlib.sha256(bound.active_goal.encode()).hexdigest(),
                    "active_goal_equals_current_question": bound.active_goal == question,
                    "project_scope_sha256": hashlib.sha256(
                        _canonical(bound.state.project_scope)
                    ).hexdigest(),
                    "profile_id": bound.state.profile_id,
                    "task_key": bound.task_key,
                    "declared_host_event": bound.declared_event,
                    "host_event": bound.event,
                    "event_adjustment": bound.event_adjustment,
                    "binding_transition": bound.transition,
                    "task_relation": bound.binding_context.relation_decision.relation,
                    "confidence_tier": (bound.binding_context.relation_decision.confidence_tier),
                    "reason_codes": list(bound.binding_context.relation_decision.reason_codes),
                    "transition_operation": bound.binding_context.transition.operation,
                    "source_task_id_sha256": (
                        hashlib.sha256(
                            bound.binding_context.transition.source_task_id.encode()
                        ).hexdigest()
                        if bound.binding_context.transition.source_task_id is not None
                        else None
                    ),
                    "target_task_id_sha256": (
                        hashlib.sha256(
                            bound.binding_context.transition.target_task_id.encode()
                        ).hexdigest()
                        if bound.binding_context.transition.target_task_id is not None
                        else None
                    ),
                    "registry_revision_before": (bound.binding_context.registry_revision_before),
                    "registry_revision_after": bound.binding_context.registry_revision_after,
                    "expected_registry_revision": (
                        bound.binding_context.transition.expected_registry_revision
                    ),
                    "task_generation": bound.state.identity.task_generation,
                    "binding_generation": bound.state.identity.binding_generation,
                    "expected_task_generation": (
                        bound.binding_context.transition.expected_task_generation
                    ),
                    "execution_lane_id_sha256": hashlib.sha256(
                        bound.state.identity.execution_lane_id.encode()
                    ).hexdigest(),
                    "cache_reuse_constraint": (bound.binding_context.cache_reuse_constraint),
                    "tentative_binding": bound.binding_context.tentative,
                    "scope_compatible": (bound.binding_context.relation_decision.scope_compatible),
                    "profile_compatible": (
                        bound.binding_context.relation_decision.profile_compatible
                    ),
                    "resolver_ms": bound.resolution.resolver_ms,
                    "task_relation_ms": bound.resolution.resolver_ms,
                    "task_transition_ms": bound.resolution.task_transition_ms,
                    "task_state_rebind_ms": bound.resolution.task_state_rebind_ms,
                    "task_resolver_llm_calls": bound.resolution.llm_calls,
                    "task_resolver_embedding_calls": bound.resolution.embedding_calls,
                    "task_resolver_retrieval_calls": bound.resolution.retrieval_calls,
                    "task_resolver_training_calls": bound.resolution.training_calls,
                    "task_resolver_hidden_provider_calls": (bound.resolution.hidden_provider_calls),
                    "relation_transition_trace_complete": True,
                    "retained_slot_present": bound.retained is not None,
                }
            )
        if self.memory_mode == "query-first" and recall is None:
            if self.host_mcp is None or self.target_counter is None:
                raise OpenWorkerAdapterError("query-first MCP client is absent")
            recalled_at = time.perf_counter()
            attempt_trace_id = (
                "host-mcp-attempt:" + hashlib.sha256(_canonical(payload_input)).hexdigest()
            )
            native_trace_identity = {
                "task_session_sha256": hashlib.sha256(
                    metadata.task_session.encode()
                ).hexdigest(),
                "task_operation_sha256": hashlib.sha256(
                    metadata.task_operation.encode()
                ).hexdigest(),
            }
            previous_context_id = self.task_free_context_locators.get(
                metadata.task_session
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_ATTEMPT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **native_trace_identity,
                    "memory_mode": self.memory_mode,
                    "mcp_tool": "milai_memory_resolve",
                    "requested_route": "L1",
                    "fresh_resolve": previous_context_id is None,
                    "receipt_locator_present": previous_context_id is not None,
                    "logical_mcp_calls": 1,
                    "attempt_trace_id": attempt_trace_id,
                }
            )
            try:
                query = _recall_query(question)
                resolved = (
                    self.host_mcp.resolve_memory(
                        query,
                        previous_context_id=previous_context_id,
                    )
                    if previous_context_id is not None
                    else self.host_mcp.resolve_memory(query)
                )
            except McpUnixClientError as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1_000
                outcome = _transport_unavailable_outcome(payload_input, exc.code)
                completion = _memory_terminal_completion(payload_input, outcome)
                self._record(
                    {
                        "event": "HOST_MCP_PREFETCH_FAILED",
                        "provider_call": False,
                        "request_id": completion["id"],
                        "question_sha256": question_sha256,
                        **native_trace_identity,
                        "memory_mode": self.memory_mode,
                        "mcp_tool": "milai_memory_resolve",
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_code": exc.code,
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": outcome.to_api(),
                    }
                )
                return completion, "HOST_" + outcome.status

            compile_started = time.perf_counter()
            context = prepare_prefetch(resolved)
            raw_receipt = resolved.get("context_receipt")
            next_context_id = (
                raw_receipt.get("context_capsule_id")
                if isinstance(raw_receipt, Mapping)
                else None
            )
            if isinstance(next_context_id, str) and next_context_id:
                self.task_free_context_locators[metadata.task_session] = next_context_id
                if len(self.task_free_context_locators) > 256:
                    oldest = next(iter(self.task_free_context_locators))
                    if oldest != metadata.task_session:
                        self.task_free_context_locators.pop(oldest, None)
            context_compile_ms = (time.perf_counter() - compile_started) * 1_000
            memory_control_ms = (time.perf_counter() - recalled_at) * 1_000
            memory_source = "HOST_MCP_QUERY_FIRST"
            mcp_calls = 1
            raw_trace = resolved.get("access_trace")
            access_trace = dict(raw_trace) if isinstance(raw_trace, Mapping) else {}
            raw_spans = access_trace.get("spans")
            spans = dict(raw_spans) if isinstance(raw_spans, Mapping) else {}
            raw_transport = resolved.get("host_transport")
            host_transport = (
                dict(raw_transport) if isinstance(raw_transport, Mapping) else {}
            )

            def measured(value: object) -> float | None:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
                return None

            timing = {
                "uds_roundtrip_ms": measured(host_transport.get("uds_roundtrip_ms")),
                "mcp_handler_ms": measured(spans.get("mcp_handler_ms")),
                "runtime_total_ms": measured(spans.get("runtime_client_ms")),
                "context_compile_ms": round(context_compile_ms, 3),
            }
            items = resolved.get("items")
            issue_ids = resolved.get("open_issue_ids")
            target_status = str(resolved.get("status"))
            terminal_stage = access_trace.get("terminal_stage")
            trace_id = resolved.get("trace_id")
            compiled = context.status in {"AVAILABLE", "UNCERTAIN"}
            prepare_status = (
                "READY"
                if compiled
                else "ABSTAIN"
                if context.status == "NO_MEMORY"
                else "DEGRADED"
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_CONTEXT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **native_trace_identity,
                    "attempt_trace_id": attempt_trace_id,
                    "memory_mode": self.memory_mode,
                    "mcp_tool": "milai_memory_resolve",
                    "fresh_resolve": previous_context_id is None,
                    "memory_control_ms": round(memory_control_ms, 3),
                    "memory_status": context.status,
                    "route": access_trace.get("planned_stage") or "SEARCH",
                    "prepare_status": prepare_status,
                    "prepare_reason": context.abstention_reason,
                    "access_outcome": {
                        "schema_version": resolved.get("schema_version"),
                        "status": target_status,
                        "availability": resolved.get("availability"),
                        "terminal_stage": terminal_stage,
                        "trace_id": trace_id,
                    },
                    "trace_id": trace_id,
                    "current_state_status": target_status,
                    "current_state_claim_count": (
                        len(items) if isinstance(items, list) else 0
                    ),
                    "current_state_open_issue_count": (
                        len(issue_ids) if isinstance(issue_ids, list) else 0
                    ),
                    "cache_validation_outcome": (
                        "REUSED"
                        if resolved.get("receipt_reused") is True
                        else resolved.get("receipt_fallback_reason")
                    ),
                    "timing": timing,
                    "access_trace_link": _host_access_trace_link(
                        attempt_trace_id=attempt_trace_id,
                        retrieval_trace_id=(trace_id if isinstance(trace_id, str) else None),
                        timing={
                            key: value
                            for key, value in timing.items()
                            if isinstance(value, float)
                        },
                        host_total_ms=memory_control_ms,
                    ),
                    "compiled_memory_tokens": (
                        self.target_counter.count_text(context.rendered) if compiled else None
                    ),
                    "compiled_memory_bytes": (
                        len(context.rendered.encode("utf-8")) if compiled else None
                    ),
                    "recall_execution_trace": access_trace,
                }
            )
            if context.status == "UNAVAILABLE":
                outcome = _transport_unavailable_outcome(
                    payload_input,
                    context.abstention_reason or target_status,
                )
                return _memory_terminal_completion(payload_input, outcome), "HOST_" + outcome.status
        elif bound is not None and bound.binding_context.tentative:
            context = PrefetchContext.no_memory()
            memory_source = "HOST_TASK_BINDING_AMBIGUOUS"
            self._record(
                {
                    "event": "HOST_MEMORY_ROUTE_NONE",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "route": "NONE",
                    "reason": "TASK_BINDING_AMBIGUOUS",
                    "mcp_calls": 0,
                    "compiled_memory_tokens": 0,
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route="NONE",
                        actual_route="NONE",
                        host_terminal=True,
                    ),
                }
            )
        elif need_resolution is not None and need_resolution.requested_route == "NONE":
            context = PrefetchContext.no_memory()
            memory_source = "HOST_ROUTER_NONE"
            self._record(
                {
                    "event": "HOST_MEMORY_ROUTE_NONE",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "route": "NONE",
                    "reason": need_resolution.reason_code,
                    "mcp_calls": 0,
                    "compiled_memory_tokens": 0,
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route="NONE",
                        actual_route="NONE",
                        host_terminal=True,
                    ),
                }
            )
        elif self.memory_mode == "prefetch" and recall is None:
            if (
                self.task_memory is None or self.target_counter is None or self.token_budget is None
            ):  # pragma: no cover - constructor invariant
                raise OpenWorkerAdapterError("host task-memory controller is absent")
            if bound is None:  # pragma: no cover - constructor and branch invariant
                raise OpenWorkerAdapterError("Host task-memory state is absent")
            identity = bound.identity
            active_goal = bound.active_goal
            task_key = bound.task_key
            event = bound.event
            retained = bound.retained
            recalled_at = time.perf_counter()
            attempt_trace_id = (
                "host-mcp-attempt:" + hashlib.sha256(_canonical(payload_input)).hexdigest()
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_ATTEMPT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "task_session_sha256": hashlib.sha256(
                        metadata.task_session.encode()
                    ).hexdigest(),
                    "task_operation_sha256": hashlib.sha256(
                        metadata.task_operation.encode()
                    ).hexdigest(),
                    "memory_mode": self.memory_mode,
                    "requested_route": requested_memory_route,
                    "logical_mcp_calls": 1,
                    "attempt_trace_id": attempt_trace_id,
                }
            )
            try:
                prepared = self.task_memory.prepare_context(
                    _recall_query(question),
                    identity=identity,
                    event=event,
                    active_goal=active_goal,
                    recall_policy=turn_policy,
                    token_counter=self.target_counter,
                    token_budget=self.token_budget,
                    task_budget=self.task_budget,
                    requested_route=(requested_memory_route),
                    need_signature_id=(
                        need_resolution.signature.need_signature_id
                        if need_resolution is not None
                        else None
                    ),
                    memory_need_signature=(
                        need_resolution.signature if need_resolution is not None else None
                    ),
                    state_key_ref=(
                        need_resolution.state_key_ref if need_resolution is not None else None
                    ),
                    known_claim_id=(
                        bound.state.known_claim_ids[0]
                        if event == "KNOWN_OBJECT" and bound.state.known_claim_ids
                        else None
                    ),
                )
            except McpUnixClientError as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
                outcome = _transport_unavailable_outcome(payload_input, exc.code)
                completion = _memory_terminal_completion(payload_input, outcome)
                self._record(
                    {
                        "event": "HOST_MCP_PREFETCH_FAILED",
                        "provider_call": False,
                        "request_id": completion["id"],
                        "question_sha256": question_sha256,
                        "memory_mode": self.memory_mode,
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_code": exc.code,
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": outcome.to_api(),
                    }
                )
                return (
                    completion,
                    "HOST_" + outcome.status,
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
            context = _resolve_prepared_context(prepared, retained)
            if prepared.status != "UNCHANGED":
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
                    "task_session_sha256": hashlib.sha256(
                        metadata.task_session.encode()
                    ).hexdigest(),
                    "task_operation_sha256": hashlib.sha256(
                        metadata.task_operation.encode()
                    ).hexdigest(),
                    "attempt_trace_id": attempt_trace_id,
                    "memory_mode": self.memory_mode,
                    "memory_control_ms": round(memory_control_ms, 3),
                    "memory_status": context.status,
                    "route": prepared.route,
                    "prepare_status": prepared.status,
                    "prepare_reason": prepared.reason,
                    "access_outcome": prepared.outcome.to_api(),
                    "usage": prepared.usage,
                    "trace_id": prepared.trace_pointer,
                    "current_state_status": (
                        prepared.current_state_envelope.status
                        if prepared.current_state_envelope is not None
                        else None
                    ),
                    "current_state_claim_count": (
                        len(prepared.current_state_envelope.claims)
                        if prepared.current_state_envelope is not None
                        else 0
                    ),
                    "current_state_open_issue_count": (
                        len(prepared.current_state_envelope.open_issues)
                        if prepared.current_state_envelope is not None
                        else 0
                    ),
                    "current_state_validation_handle_present": (
                        prepared.current_state_envelope.slot_validation_handle is not None
                        if prepared.current_state_envelope is not None
                        else False
                    ),
                    "memory_slot_coverage_present": (prepared.memory_slot_coverage is not None),
                    "memory_slot_coverage_counts": (
                        {
                            "claims": len(
                                prepared.memory_slot_coverage.claim_ids_and_head_versions
                            ),
                            "state_keys": len(
                                prepared.memory_slot_coverage.state_keys_and_head_versions
                            ),
                            "open_issues": len(
                                prepared.memory_slot_coverage.open_issue_ids_and_revisions
                            ),
                        }
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "memory_slot_policy_identity": (
                        prepared.memory_slot_coverage.policy_identity
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "memory_slot_evidence_depth": (
                        prepared.memory_slot_coverage.evidence_depth
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "dependency_frontier_position": (
                        prepared.memory_slot_coverage.dependency_frontier.get("canonical_position")
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "cache_validation_outcome": (
                        (
                            "HIT"
                            if prepared.status == "UNCHANGED"
                            and prepared.validation_token is not None
                            else (prepared.reason or "MISS")
                        )
                        if requested_memory_route == "CACHE"
                        else None
                    ),
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
                    "access_trace_link": _host_access_trace_link(
                        attempt_trace_id=attempt_trace_id,
                        retrieval_trace_id=prepared.trace_pointer,
                        timing=timing,
                        host_total_ms=memory_control_ms,
                    ),
                    "compiled_memory_tokens": (
                        prepared.delta.metrics.actual_tokens if prepared.delta is not None else None
                    ),
                    "compiled_memory_bytes": (
                        len(prepared.delta.delta.rendered_context.encode("utf-8"))
                        if prepared.delta is not None
                        and prepared.delta.delta.rendered_context is not None
                        else None
                    ),
                    "representation_tiers": (
                        [list(value) for value in prepared.delta.metrics.representation_tiers]
                        if prepared.delta is not None
                        else []
                    ),
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route=(requested_memory_route),
                        actual_route=prepared.route,
                        host_terminal=False,
                        runtime_trace=prepared.recall_execution_trace,
                    ),
                }
            )
            if context.status == "UNAVAILABLE":
                return (
                    _memory_terminal_completion(payload_input, prepared.outcome),
                    "HOST_" + prepared.outcome.status,
                )
        if (
            recall_name is not None
            and recall is None
            and context is None
            and not has_tool_result
            and _should_recall(self.memory_mode)
        ):
            request_id = (
                "chatcmpl-route-" + hashlib.sha256(_canonical(payload_input)).hexdigest()[:24]
            )
            with self._pending_lock:
                self._pending_recall[question_sha256].append(time.perf_counter())
            self._record(
                {
                    "event": "MCP_ROUTE",
                    "provider_call": False,
                    "request_id": request_id,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "adapter_route_ms": round((time.perf_counter() - adapter_started) * 1000, 3),
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

        ordinary_tool_continuation = (
            self.single_ordinary_tool_required_once is not None and has_tool_result
        )
        if (
            context is None
            and recall is None
            and (recall_name is None or has_tool_result)
            and not ordinary_tool_continuation
        ):
            answer = {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
            request_id = (
                "chatcmpl-unavailable-" + hashlib.sha256(_canonical(payload_input)).hexdigest()[:18]
            )
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
                prepare_prefetch(recall) if recall is not None else PrefetchContext.no_memory()
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
        rendered_context = context.rendered if context.status != "NO_MEMORY" else None
        payload, excluded_memory_tools = incoming.provider_payload(rendered_context)
        ordinary_tool_policy = (
            _apply_single_ordinary_tool_required_once(
                payload, self.single_ordinary_tool_required_once
            )
            if self.single_ordinary_tool_required_once is not None
            else None
        )
        ordinary_tool_compatibility_applied = False
        ordinary_tool_delivery = "NATIVE"
        ordinary_tool_delivery_evidence: dict[str, Any] | None = None
        if self.ordinary_tool_provider_compatibility is not None:
            if not incoming.stream:
                raise OpenWorkerAdapterError(
                    "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_REQUIRES_STREAM"
                )
            assert ordinary_tool_policy is not None
            ordinary_tool_compatibility_applied = _apply_vllm_json_schema_named_tool_compatibility(
                payload, ordinary_tool_policy
            )
            ordinary_tool_delivery = (
                self.ordinary_tool_provider_compatibility
                if ordinary_tool_compatibility_applied
                else "NATIVE_NONE"
            )
            if ordinary_tool_compatibility_applied:
                ordinary_tool_delivery_evidence = {
                    "incoming_tool_choice": ordinary_tool_policy.get("requested_tool_choice"),
                    "provider_tool_choice": (
                        "ABSENT" if "tool_choice" not in payload else "PRESENT"
                    ),
                    "provider_tool_count": len(payload.get("tools", [])),
                    "native_tool_call_count": 0,
                    "delivery_owner": "HOST_ADAPTER",
                    "client_finish_reason": "tool_calls",
                    "delivered_read_count": 1,
                }
        logical_request_id = self._logical_request_id()
        prompt_budget = _per_request_token_budget(
            self.provider_capability.max_prompt_tokens,
            self.provider_capability.max_native_requests,
        )
        per_request_completion_budget = _per_request_token_budget(
            self.provider_capability.max_completion_tokens,
            self.provider_capability.max_native_requests,
        )
        completion_budget = min(
            incoming.max_tokens or per_request_completion_budget,
            per_request_completion_budget,
        )
        transport_name = "stream" if incoming.stream else "json"
        provider_request = ProviderRequest(
            logical_request_id=logical_request_id,
            transport=transport_name,
            payload=payload,
            prompt_token_budget=prompt_budget,
            completion_token_budget=completion_budget,
            timeout_seconds=self.provider_timeout_seconds,
        )
        provider_started = time.perf_counter()
        trace_base = {
            "event": "PROVIDER_ANSWER",
            "provider_call": True,
            "logical_request_id": logical_request_id,
            "memory_status": context.status,
            "memory_mode": self.memory_mode,
            "memory_source": memory_source,
            "mcp_calls": mcp_calls,
            "memory_control_ms": (
                round(memory_control_ms, 3) if memory_control_ms is not None else None
            ),
            "request_parse_ms": (
                round(request_parse_ms, 3) if request_parse_ms is not None else None
            ),
            "context_sha256": context.context_sha256,
            "context_in_prompt": rendered_context is not None,
            "trace_id": context.trace_id,
            "claim_refs": list(context.claim_refs),
            "open_issue_ids": list(context.open_issue_ids),
            "provider_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            "excluded_memory_tools": list(excluded_memory_tools),
            "ordinary_tool_count": len(payload.get("tools", [])),
            "ordinary_tool_policy": ordinary_tool_policy,
            "ordinary_tool_delivery": ordinary_tool_delivery,
            "provider_transport": transport_name,
        }
        if incoming.stream:
            chunks = self.gateway.execute_stream(provider_request, self.stream_transport)
            if ordinary_tool_compatibility_applied:
                chunks = _vllm_json_schema_named_tool_chunks(chunks)

            def traced_chunks() -> Iterator[bytes]:
                yield from chunks
                ledger = self.gateway.read_ledger()
                terminal = next(
                    event
                    for event in reversed(ledger)
                    if event.get("event") == "PROVIDER_TERMINAL"
                    and event.get("logical_request_id") == logical_request_id
                )
                self._record(
                    {
                        **trace_base,
                        "native_request_id": terminal.get("native_request_id"),
                        "finish_reason": terminal.get("finish_reason"),
                        "ordinary_tool_delivery_evidence": (
                            {
                                **ordinary_tool_delivery_evidence,
                                "native_finish_reason": terminal.get("finish_reason"),
                            }
                            if ordinary_tool_delivery_evidence is not None
                            else None
                        ),
                        "prompt_tokens": terminal.get("prompt_tokens"),
                        "completion_tokens": terminal.get("completion_tokens"),
                        "provider_prefill_answer_ms": round(
                            (time.perf_counter() - provider_started) * 1000, 3
                        ),
                        "adapter_total_ms": round(
                            (time.perf_counter() - adapter_started) * 1000, 3
                        ),
                    }
                )

            return StreamingCompletion(traced_chunks()), f"PROVIDER_{context.status}"

        result = self.gateway.execute(
            provider_request,
            self.transport,
            lambda response: dict(response),
        )
        provider_prefill_answer_ms = (time.perf_counter() - provider_started) * 1000
        self._record(
            {
                **trace_base,
                "native_request_id": result.native_request_id,
                "finish_reason": result.finish_reason,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "provider_prefill_answer_ms": round(provider_prefill_answer_ms, 3),
                "adapter_total_ms": round((time.perf_counter() - adapter_started) * 1000, 3),
                "response_sha256": hashlib.sha256(_canonical(result.value)).hexdigest(),
            }
        )
        return dict(result.value), f"PROVIDER_{context.status}"


class Handler(BaseHTTPRequestHandler):
    server_version = "MiLAiOpenWorkerU1Adapter/1"
    protocol_version = "HTTP/1.1"

    @property
    def adapter(self) -> OpenWorkerProviderAdapter:
        value = getattr(self.server, "adapter", None)
        if not isinstance(value, OpenWorkerProviderAdapter):
            raise OpenWorkerAdapterError("adapter is unavailable")
        return value

    @property
    def ingress_token(self) -> str:
        value = getattr(self.server, "ingress_token", None)
        if not isinstance(value, str):
            raise OpenWorkerAdapterError("INGRESS_TOKEN_INVALID")
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

    def _write_error(self, status: int, reason_code: str) -> None:
        self._write(
            status,
            _canonical(
                {
                    "error": {
                        "message": "OpenWorker Host request failed",
                        "type": "local_adapter_error",
                        "reason_code": reason_code,
                    }
                }
            ),
            "application/json",
        )

    def _authenticate(self) -> bool:
        try:
            _authenticate_ingress(self.headers.get_all("Authorization", []), self.ingress_token)
        except OpenWorkerAdapterError:
            self._write_error(401, "AUTHENTICATION_REQUIRED")
            return False
        return True

    def _metadata(self) -> NativeTaskMetadata:
        return _task_metadata_from_values(
            {name: self.headers.get_all(name, []) for name in _HEADER_NAMES}
        )

    def _write_stream(self, chunks: Iterator[bytes]) -> None:
        try:
            first_chunk = next(chunks)
        except StopIteration as exc:
            raise ProviderCallError("PROVIDER_STREAM_DONE_MISSING") from exc
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(first_chunk)
            self.wfile.flush()
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (ProviderCallError, BudgetError, OSError) as exc:
            self.adapter._record_stream_terminal(exc)
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()
            self.close_connection = True

    def do_GET(self) -> None:
        if not self._authenticate():
            return
        if self.path != "/v1/models":
            self._write(404, b"{}", "application/json")
            return
        payload = {
            "object": "list",
            "data": [{"id": MODEL_ID, "object": "model", "owned_by": "milai-local"}],
        }
        self._write(200, _canonical(payload), "application/json")

    def do_POST(self) -> None:
        parse_started = time.perf_counter()
        if not self._authenticate():
            return
        try:
            if self.path != "/v1/chat/completions":
                raise OpenWorkerAdapterError("path is not allowlisted")
            metadata = self._metadata()
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise OpenWorkerAdapterError("request body boundary failed")
            incoming = OpenAIChatRequest.parse(json.loads(self.rfile.read(length)))
            request_parse_ms = (time.perf_counter() - parse_started) * 1000
            completion, route = self.adapter.complete(
                incoming,
                metadata,
                request_parse_ms=request_parse_ms,
            )
            print(
                json.dumps({"event": "OPENWORKER_U1_ROUTE", "route": route}, sort_keys=True),
                flush=True,
            )
            if isinstance(completion, StreamingCompletion):
                self._write_stream(completion.chunks)
                return
            payload = _sse(completion) if incoming.stream else _canonical(completion)
            content_type = "text/event-stream" if incoming.stream else "application/json"
            self._write(200, payload, content_type)
        except (OpenWorkerAdapterError, ValueError, json.JSONDecodeError) as exc:
            status = 422 if isinstance(exc, OrdinaryToolCompatibilityError) else 400
            self.adapter._record_ingress_terminal(status, exc)
            self._write_error(status, str(exc))
        except ProviderCallError as exc:
            match = re.fullmatch(r"PROVIDER_HTTP_(\d{3})", str(exc))
            status = 422 if match is not None and 400 <= int(match.group(1)) < 500 else 502
            self.adapter._record_ingress_terminal(status, exc)
            self._write_error(status, str(exc))
        except (BudgetError, CapabilityError) as exc:
            self.adapter._record_ingress_terminal(502, exc)
            self._write_error(502, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve OpenWorker through the U1 Host adapter")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument(
        "--memory-mode",
        choices=("auto", "none", "prefetch", "query-first"),
        default="auto",
    )
    parser.add_argument("--prefetch-socket", type=Path)
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--broker-policy", type=Path)
    parser.add_argument("--task-fixture", type=Path)
    parser.add_argument("--ingress-token-file", type=Path, required=True)
    parser.add_argument("--task-session-id")
    parser.add_argument("--provider-timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--single-ordinary-tool-required-once",
        choices=("read",),
        help=(
            "Enable the explicit SINGLE_ORDINARY_SYNC_TOOL_REQUIRED_ONCE "
            "compatibility contract for one OpenCode read call"
        ),
    )
    parser.add_argument(
        "--ordinary-tool-provider-compatibility",
        choices=(_VLLM_JSON_SCHEMA_NAMED_TOOL,),
        help=(
            "Adapt the forced read round through vLLM JSON Schema when the "
            "protected server has no tool parser"
        ),
    )
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
        broker_policy=args.broker_policy,
        task_fixture=args.task_fixture,
        task_session_id=args.task_session_id,
        provider_timeout_seconds=args.provider_timeout_seconds,
        single_ordinary_tool_required_once=args.single_ordinary_tool_required_once,
        ordinary_tool_provider_compatibility=(args.ordinary_tool_provider_compatibility),
    )
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.adapter = adapter  # type: ignore[attr-defined]
    server.ingress_token = _load_ingress_token(args.ingress_token_file)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        adapter.close()
        server.server_close()


if __name__ == "__main__":
    main()
