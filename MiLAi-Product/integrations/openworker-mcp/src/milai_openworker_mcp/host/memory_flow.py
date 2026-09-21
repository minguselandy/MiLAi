"""Memory preparation, recall decoding and fail-closed terminal rendering."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from milai_client import AccessOutcome, TaskPreparedContext
from milai_client.context_policy import MemoryStatus, PrefetchContext, prepare_prefetch

from milai_openworker_mcp.host.request_contract import (
    MODEL_ID,
    OpenWorkerAdapterError,
    _is_memory_tool,
)
from milai_openworker_mcp.host.tool_compat import _canonical

_HOST_PREFETCH_MODES = frozenset({"prefetch", "query-first"})


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
            value = _native_user_content(message.get("content")).strip()
            if value:
                return value[:2000]
    return "What governed memory is available?"


def _native_user_content(value: object) -> str:
    """Remove only OpenCode CLI's JSON-string transport envelope."""

    text = _text(value)
    stripped = text.strip()
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, str) and decoded.strip():
        return decoded
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"' and "\n" in stripped:
        # The attached native CLI can retain literal newlines inside the
        # quotes, making the envelope itself invalid JSON.
        return stripped[1:-1]
    return text


def _last_user_content(messages: Sequence[Mapping[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            value = _native_user_content(message.get("content"))
            if value.strip():
                return value
    raise OpenWorkerAdapterError("PROVIDER_USER_MESSAGE_ABSENT")


def _memory_answer_eligible(
    *,
    memory_mode: str,
    rendered_context: str | None,
    payload: Mapping[str, Any],
    ordinary_tool_policy: Mapping[str, Any] | None,
) -> bool:
    return (
        memory_mode == "query-first"
        and rendered_context is not None
        and ordinary_tool_policy is None
        and not payload.get("tools")
        and payload.get("response_format") is None
    )


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
        status: MemoryStatus = "UNCERTAIN" if issue_ids else "AVAILABLE"
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


def _memory_insufficient_outcome(
    payload: Mapping[str, Any],
    resolved: Mapping[str, Any],
    context: PrefetchContext,
) -> AccessOutcome:
    """Map a completed but non-answer-bearing resolve to the frozen barrier."""

    raw_position = resolved.get("canonical_position")
    canonical_position = (
        raw_position
        if isinstance(raw_position, int) and not isinstance(raw_position, bool)
        else None
    )
    raw_trace_id = resolved.get("trace_id")
    trace_id = (
        raw_trace_id
        if isinstance(raw_trace_id, str) and raw_trace_id.strip()
        else "host-mcp-insufficient:" + hashlib.sha256(_canonical(payload)).hexdigest()
    )
    raw_status = resolved.get("status")
    reason_code = context.abstention_reason or (
        str(raw_status) if isinstance(raw_status, str) and raw_status else context.status
    )
    return AccessOutcome(
        status="MEMORY_INSUFFICIENT",
        execution_action="ASK_USER",
        provider_execution="PROHIBITED",
        terminal_stage="SUFFICIENCY",
        context_digest=None,
        canonical_position=canonical_position,
        reason_code=reason_code,
        trace_id=trace_id,
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

