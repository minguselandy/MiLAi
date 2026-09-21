"""Payload-free host routing, access and terminal trace projections."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from milai_client import DeterministicQueryOnlyIntentShadow, MemoryNeedResolution
from milai_client.models import RecallExecutionRoute

from milai_openworker_mcp.evidence_use import GroundedEvidenceUseV01
from milai_openworker_mcp.host.memory_flow import _question
from milai_openworker_mcp.host.request_contract import OpenAIChatRequest
from milai_openworker_mcp.host.task_state import _BoundTaskState
from milai_openworker_mcp.task_binding import NativeTaskMetadata


def _nonnegative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(max(0.0, left - right), 3)


def _requested_memory_route(
    bound: _BoundTaskState | None,
    resolution: MemoryNeedResolution | None,
    previous: MemoryNeedResolution | None,
) -> RecallExecutionRoute:
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
            **_progressive_l1_trace(runtime_trace.get("progressive_l1")),
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


def _progressive_l1_trace(value: object) -> dict[str, object]:
    return {"progressive_l1": dict(value)} if isinstance(value, Mapping) else {}


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
        "temperature": incoming.payload.get("temperature"),
        "top_p": incoming.payload.get("top_p"),
        "message_count": len(incoming.messages),
        "message_roles": [str(message["role"]) for message in incoming.messages],
        "tool_count": tool_count,
        "has_tool_result": any(message.get("role") == "tool" for message in incoming.messages),
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "task_session_sha256": hashlib.sha256(metadata.task_session.encode()).hexdigest(),
        "task_operation_sha256": hashlib.sha256(metadata.task_operation.encode()).hexdigest(),
    }


def _evidence_use_trace_result(
    grounded: GroundedEvidenceUseV01,
    *,
    pass_count: int = 1,
) -> dict[str, Any]:
    return {
        "disposition": grounded.disposition,
        "support_count": len(grounded.support),
        "member_count": len(grounded.members),
        "evidence_alias_count": len(grounded.evidence_aliases),
        "calculation_present": grounded.calculation.expression is not None,
        "host_validated": True,
        "truth_or_completeness_certified": False,
        "pass_count": pass_count,
    }

