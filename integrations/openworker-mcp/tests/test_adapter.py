from __future__ import annotations

import threading

from milai_client import AgentRecallPolicy, DeterministicMemoryNeedResolver, PrefetchContext

from milai_openworker_mcp.host_adapter import (
    OpenWorkerProviderAdapter,
    _host_access_trace_link,
    _query_only_intent_shadow_trace,
    _requested_memory_route,
    _shadow_route_trace,
)
from milai_openworker_mcp.task_binding import (
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
    HostTaskRegistry,
)


def _adapter() -> OpenWorkerProviderAdapter:
    adapter = object.__new__(OpenWorkerProviderAdapter)
    adapter.task_session_id = "host-task-session"
    adapter.run_id = "host-task-state-test"
    adapter.task_policy = AgentRecallPolicy(
        scope={"host_policy": "reader-lite"},
        authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=3,
    )
    adapter._task_lock = threading.Lock()
    adapter._task_sequence = 0
    adapter.task_registry = HostTaskRegistry()
    adapter.task_relation_resolver = DeterministicTaskRelationResolver()
    adapter.task_transition_validator = DeterministicTaskTransitionValidator()
    adapter._active_task_key_by_task = {}
    adapter._task_contexts = {}
    return adapter


def _state(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "host-task-session",
        "active_goal_id": "goal-release",
        "active_goal_version": 1,
        "active_goal_summary": "Prepare the governed release.",
        "project_scope": {"project_ids": ["orchid"]},
        "profile_id": "reader-lite",
        "execution_lane_id": "lane-main",
        "task_generation": 1,
        "binding_generation": 1,
    }
    value.update(updates)
    return value


def test_host_owned_session_stays_stable_without_host_generation_change() -> None:
    adapter = _adapter()

    identities = [
        adapter._bind_task_state({}, declared_event="EXPLICIT_MEMORY_REQUEST").identity
        for _ in range(101)
    ]

    assert {identity.session_id for identity in identities} == {"host-task-session"}
    assert len({identity.task_epoch for identity in identities}) == 1


def test_host_owned_active_goal_is_stable_across_current_questions() -> None:
    adapter = _adapter()

    first = adapter._bind_task_state({}, declared_event="EXPLICIT_MEMORY_REQUEST")
    followup = adapter._bind_task_state({}, declared_event="EXPLICIT_MEMORY_REQUEST")

    assert first.active_goal == "Continue the host-owned task."
    assert followup.active_goal == first.active_goal
    assert followup.task_key == first.task_key
    assert followup.transition == "KEEP"


def test_goal_scope_and_profile_switches_rebind_and_invalidate_task_key() -> None:
    adapter = _adapter()
    incoming = {"user": "host-task-session", "milai_task_state": _state()}

    initial = adapter._bind_task_state(incoming, declared_event="TASK_START")
    goal = adapter._bind_task_state(
        {
            **incoming,
            "milai_task_state": _state(
                active_goal_id="goal-audit",
                active_goal_summary="Audit the governed release.",
                active_goal_version=2,
                binding_generation=2,
            ),
        },
        declared_event="GOAL_CHANGED",
    )
    scope = adapter._bind_task_state(
        {
            **incoming,
            "milai_task_state": _state(
                active_goal_id="goal-audit",
                active_goal_summary="Audit the governed release.",
                active_goal_version=3,
                task_generation=2,
                binding_generation=3,
                project_scope={"project_ids": ["cedar"]},
            ),
            "milai_task_relation": "SWITCH",
        },
        declared_event="GOAL_CHANGED",
    )
    profile = adapter._bind_task_state(
        {
            **incoming,
            "milai_task_state": _state(
                active_goal_id="goal-audit",
                active_goal_summary="Audit the governed release.",
                active_goal_version=4,
                task_generation=3,
                binding_generation=4,
                project_scope={"project_ids": ["cedar"]},
                profile_id="submitter",
            ),
            "milai_task_relation": "SWITCH",
        },
        declared_event="GOAL_CHANGED",
    )

    assert [goal.transition, scope.transition, profile.transition] == [
        "KEEP",
        "CREATE_AND_ACTIVATE",
        "CREATE_AND_ACTIVATE",
    ]
    assert len({initial.task_key, goal.task_key, scope.task_key, profile.task_key}) == 4


def test_shadow_route_trace_does_not_invent_runtime_validation() -> None:
    none_trace = _shadow_route_trace(
        requested_route="NONE", actual_route="NONE", host_terminal=True
    )
    composite_trace = _shadow_route_trace(
        requested_route="L0", actual_route="L1", host_terminal=False
    )

    assert none_trace["route_trace_complete"] is True
    assert none_trace["validated_route"] == "NONE"
    assert composite_trace["requested_route"] == "L0"
    assert composite_trace["validated_route"] is None
    assert composite_trace["attempted_routes"] == ["L1"]
    assert composite_trace["trace_gap_reason"] == "VALIDATED_ROUTE_NOT_EXPOSED_PRECHANGE"


def test_shadow_route_trace_joins_complete_runtime_observation() -> None:
    trace = _shadow_route_trace(
        requested_route="L1",
        actual_route="NONE",
        host_terminal=False,
        runtime_trace={
            "need_signature_id": None,
            "requested_route": "L1",
            "planned_route": "L1",
            "validated_route": "L1",
            "attempted_routes": ["L1"],
            "terminal_route": "NONE",
            "result": "MISS",
            "policy_override_reason": None,
            "fallback_reason": "NO_TASK_SLOT",
            "next_route_recommended": "L1",
            "route_trace_complete": True,
            "trace_gap_reason": None,
            "query_embedding_calls": 0,
            "vector_calls": 0,
            "reranker_calls": 0,
            "exact_calls": 0,
            "fts_calls": 0,
            "l0_calls": 0,
        },
    )

    assert trace["route_trace_complete"] is True
    assert trace["planned_route"] == "L1"
    assert trace["validated_route"] == "L1"
    assert trace["terminal_route"] == "NONE"
    assert trace["policy_override_reason"] is None
    assert trace["fallback_reason"] == "NO_TASK_SLOT"


def test_query_only_shadow_records_task_gate_disagreement_without_query_text() -> None:
    current = DeterministicMemoryNeedResolver().resolve(
        "Could this affect the release?",
        scope={"project_ids": ["orchid"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
    )
    assert current.requested_route == "NONE"

    trace = _query_only_intent_shadow_trace(
        "Could this affect the release?",
        current_resolution=current,
        current_effective_route="NONE",
    )

    assert trace == {
        "interpreter_version": "query-only-shadow-v1",
        "query_fingerprint": trace["query_fingerprint"],
        "query_only_intent": "POSSIBLE",
        "query_only_requirement": "SEARCH",
        "query_only_reason": "QUERY_MEMORY_BOUNDED_PROBE",
        "current_task_gated_intent": "NONE",
        "current_task_gated_route": "NONE",
        "current_task_gated_reason": "NO_TYPED_MEMORY_INTENT",
        "intent_route_disagreement": True,
        "shadow_changed_production_result": False,
    }
    assert len(str(trace["query_fingerprint"])) == 64
    assert "affect" not in str(trace)


def test_query_only_shadow_agrees_on_explicit_current_query() -> None:
    current = DeterministicMemoryNeedResolver().resolve(
        "What is the current release status?",
        scope={"project_ids": ["orchid"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
    )

    trace = _query_only_intent_shadow_trace(
        "What is the current release status?",
        current_resolution=current,
        current_effective_route=current.requested_route,
    )

    assert trace["query_only_intent"] == "REQUIRED"
    assert trace["current_task_gated_intent"] == "CURRENT_STATE"
    assert trace["intent_route_disagreement"] is False


def test_host_access_trace_link_joins_broker_mcp_and_runtime_without_payload() -> None:
    link = _host_access_trace_link(
        attempt_trace_id="host-attempt-1",
        retrieval_trace_id="runtime-trace-1",
        timing={
            "uds_roundtrip_ms": 8.5,
            "mcp_handler_ms": 6.0,
            "runtime_total_ms": 4.0,
            "context_compile_ms": 0.5,
        },
        host_total_ms=10.0,
    )

    assert link == {
        "schema_version": "access-trace-link-v0.1",
        "host_attempt_trace_id": "host-attempt-1",
        "retrieval_trace_id": "runtime-trace-1",
        "spans": {
            "host_total_ms": 10.0,
            "broker_ipc_ms": 2.5,
            "uds_roundtrip_ms": 8.5,
            "mcp_handler_ms": 6.0,
            "runtime_total_ms": 4.0,
            "context_compile_ms": 0.5,
        },
    }


def test_retained_slot_only_requests_cache_as_a_runtime_validation_candidate() -> None:
    adapter = _adapter()
    incoming = {
        "user": "host-task-session",
        "milai_task_state": _state(
            known_state_keys=[
                {
                    "subject": "release",
                    "predicate": "release.target",
                    "claim_type": "PROJECT_STATE",
                }
            ]
        ),
    }
    first = adapter._bind_task_state(incoming, declared_event="TASK_START")
    adapter._task_contexts[first.task_key] = PrefetchContext.no_memory()
    retry = adapter._bind_task_state(incoming, declared_event="MODEL_RETRY")
    resolution = DeterministicMemoryNeedResolver().resolve(
        "repeat current release target",
        scope=retry.state.project_scope,
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        known_state_keys=retry.state.known_state_keys,
    )

    assert resolution.requested_route == "L0"
    assert retry.retained is not None
    assert _requested_memory_route(retry, resolution, resolution) == "CACHE"

    changed = adapter._bind_task_state(
        incoming,
        declared_event="MEMORY_AFFECTING_TOOL_RESULT",
    )
    assert _requested_memory_route(changed, resolution, resolution) == "L0"
