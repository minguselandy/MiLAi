from __future__ import annotations

import pytest
from milai_client import TaskMemoryState

from milai_openworker_mcp.task_binding import (
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
    HostTaskRegistry,
    HostTaskRelationEvent,
    NativeTaskMetadata,
    OpaqueExecutionBindingCodec,
    SameProcessTaskRegistry,
    TaskBindingConflict,
    TaskBindingError,
    bind_host_task,
)


def _state(
    task_id: str,
    *,
    lane: str = "lane-main",
    parent: str | None = None,
    generation: int = 1,
    binding_generation: int = 1,
    goal: str | None = None,
    scope: str = "orchid",
    profile: str = "reader-lite",
    unresolved: tuple[str, ...] = (),
    slot_id: str | None = None,
) -> TaskMemoryState:
    return TaskMemoryState.from_host_payload(
        {
            "task_id": task_id,
            "parent_task_id": parent,
            "status": "ACTIVE",
            "task_generation": generation,
            "binding_generation": binding_generation,
            "project_scope": {"project_ids": [scope]},
            "profile_identity": profile,
            "active_goal_id": goal or f"goal-{task_id}",
            "active_goal_version": binding_generation,
            "active_goal_summary": f"Execute {goal or task_id}.",
            "execution_lane_id": lane,
            "plan_node_id": None,
            "unresolved_operation_ids": list(unresolved),
            "workspace_ref": f"workspace://{scope}",
            "artifact_refs": [],
            "created_epoch": 1,
            "last_active_epoch": binding_generation,
            "known_claim_ids": [],
            "known_state_keys": [],
            "relevant_open_issue_ids": [],
            "slot_id": slot_id,
            "slot_validation_handle": None,
            "slot_coverage": None,
        },
        fallback_task_id="unused",
        fallback_scope={},
        fallback_profile_id="reader-lite",
    )


def _components() -> tuple[
    HostTaskRegistry,
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
]:
    return (
        HostTaskRegistry(),
        DeterministicTaskRelationResolver(),
        DeterministicTaskTransitionValidator(),
    )


def _bind(
    registry: HostTaskRegistry,
    resolver: DeterministicTaskRelationResolver,
    validator: DeterministicTaskTransitionValidator,
    state: TaskMemoryState,
    relation: str | None,
):
    event = HostTaskRelationEvent(normalized_relation=relation)  # type: ignore[arg-type]
    return bind_host_task(registry, resolver, validator, state, event)


def test_five_relations_and_non_lifo_return_form_a_registry_graph() -> None:
    registry, resolver, validator = _components()

    start, start_resolution = _bind(registry, resolver, validator, _state("task-a"), None)
    continued, continue_resolution = _bind(
        registry, resolver, validator, _state("task-a"), "CONTINUE"
    )
    child, child_resolution = _bind(
        registry,
        resolver,
        validator,
        _state("task-b", parent="task-a"),
        "SUBTASK",
    )
    switched, switch_resolution = _bind(registry, resolver, validator, _state("task-c"), "SWITCH")
    returned, return_resolution = _bind(registry, resolver, validator, _state("task-a"), "RETURN")
    tentative, ambiguous_resolution = _bind(registry, resolver, validator, _state("task-d"), None)

    assert [
        start_resolution.decision.relation,
        continue_resolution.decision.relation,
        child_resolution.decision.relation,
        switch_resolution.decision.relation,
        return_resolution.decision.relation,
        ambiguous_resolution.decision.relation,
    ] == ["SWITCH", "CONTINUE", "SUBTASK", "SWITCH", "RETURN", "AMBIGUOUS"]
    assert start.transition.operation == "CREATE_AND_ACTIVATE"
    assert continued.cache_reuse_constraint == "ELIGIBLE_FOR_VALIDATION"
    assert child.transition.operation == "CREATE_CHILD"
    assert switched.transition.operation == "SUSPEND_AND_SWITCH"
    assert returned.transition.operation == "REACTIVATE"
    assert tentative.transition.operation == "TENTATIVE"
    assert tentative.tentative is True
    assert tentative.memory_binding.known_claim_ids == ()
    snapshot = registry.snapshot()
    assert snapshot.active_by_execution_lane == {"lane-main": "task-a"}
    assert set(snapshot.suspended_task_ids) == {"task-b", "task-c"}
    assert snapshot.parent_child_edges == (("task-a", "task-b"),)
    assert "task-d" not in snapshot.tasks


def test_parallel_lanes_have_independent_active_tasks() -> None:
    registry, resolver, validator = _components()

    _bind(registry, resolver, validator, _state("task-a", lane="lane-a"), None)
    _bind(registry, resolver, validator, _state("task-b", lane="lane-b"), None)

    assert registry.snapshot().active_by_execution_lane == {
        "lane-a": "task-a",
        "lane-b": "task-b",
    }


def test_decision_is_pure_and_registry_mutation_requires_revision_cas() -> None:
    registry, resolver, validator = _components()
    _bind(registry, resolver, validator, _state("task-a"), None)
    before = registry.snapshot()
    changed = _state("task-a", binding_generation=2, goal="audit")

    first = resolver.resolve(before, changed, HostTaskRelationEvent("CONTINUE"))
    second = resolver.resolve(before, changed, HostTaskRelationEvent("CONTINUE"))
    first_transition = validator.plan(before, changed, first.decision)
    second_transition = validator.plan(before, changed, second.decision)

    assert registry.snapshot() == before
    registry.apply(changed, first.decision, first_transition)
    with pytest.raises(TaskBindingConflict, match="registry revision CAS"):
        registry.apply(changed, second.decision, second_transition)


def test_scope_profile_ambiguity_never_unions_or_reuses_memory_binding() -> None:
    registry, resolver, validator = _components()
    _bind(
        registry,
        resolver,
        validator,
        _state("task-a", slot_id="slot-parent"),
        None,
    )

    context, resolution = _bind(
        registry,
        resolver,
        validator,
        _state("task-b", scope="cedar", profile="submitter", slot_id="slot-other"),
        None,
    )

    assert resolution.decision.relation == "AMBIGUOUS"
    assert resolution.decision.scope_compatible is False
    assert resolution.decision.profile_compatible is False
    assert context.cache_reuse_constraint == "PROHIBITED"
    assert context.memory_binding.slot_id is None
    assert registry.snapshot().active_by_execution_lane == {"lane-main": "task-a"}


def test_child_does_not_inherit_parent_slot_or_authority_hints() -> None:
    registry, resolver, validator = _components()
    _bind(
        registry,
        resolver,
        validator,
        _state("task-a", slot_id="slot-parent"),
        None,
    )

    child, _ = _bind(
        registry,
        resolver,
        validator,
        _state("task-b", parent="task-a"),
        "SUBTASK",
    )

    assert child.memory_binding.slot_id is None
    assert child.cache_reuse_constraint == "PROHIBITED"


def test_delayed_result_binds_to_invocation_task_after_lane_switch() -> None:
    registry, resolver, validator = _components()
    origin, _ = _bind(registry, resolver, validator, _state("task-a"), None)
    token = registry.begin_operation(origin, "operation-a")
    _bind(registry, resolver, validator, _state("task-b"), "SWITCH")

    result = registry.bind_tool_result(token)

    assert result.status == "RETAINED_FOR_SUSPENDED_TASK"
    assert result.origin_task_id == "task-a"
    assert result.completion_active_task_id == "task-b"
    assert result.bound_task_id == "task-a"
    assert result.wrong_task_binding is False


def test_old_execution_token_is_orphaned_after_same_id_aba_rebind() -> None:
    registry, resolver, validator = _components()
    origin, _ = _bind(registry, resolver, validator, _state("task-a"), None)
    token = registry.begin_operation(origin, "operation-a")
    _bind(registry, resolver, validator, _state("task-b"), "SWITCH")
    _bind(
        registry,
        resolver,
        validator,
        _state("task-a", unresolved=("operation-a",)),
        "RETURN",
    )
    _bind(
        registry,
        resolver,
        validator,
        _state("task-a", generation=2, binding_generation=2, goal="replacement"),
        "SWITCH",
    )

    result = registry.bind_tool_result(token)

    assert result.status == "ORPHAN_GENERATION_MISMATCH"
    assert result.bound_task_id is None
    assert result.wrong_task_binding is False


def test_opaque_execution_handle_is_integrity_and_audience_bound() -> None:
    registry, resolver, validator = _components()
    origin, _ = _bind(registry, resolver, validator, _state("task-a"), None)
    token = registry.begin_operation(origin, "operation-a")
    codec = OpaqueExecutionBindingCodec(b"k" * 32, audience="openworker-tool")
    handle = codec.encode(token)

    assert codec.decode(handle) == token
    with pytest.raises(TaskBindingError, match="integrity"):
        codec.decode(handle[:-1] + ("A" if handle[-1] != "A" else "B"))
    with pytest.raises(TaskBindingError, match="audience"):
        OpaqueExecutionBindingCodec(b"k" * 32, audience="different-worker").decode(handle)


def test_resolver_has_zero_model_embedding_retrieval_and_training_calls() -> None:
    registry, resolver, validator = _components()
    _, resolution = _bind(registry, resolver, validator, _state("task-a"), None)

    assert {
        resolution.llm_calls,
        resolution.embedding_calls,
        resolution.retrieval_calls,
        resolution.training_calls,
        resolution.hidden_provider_calls,
    } == {0}


def test_native_session_registry_continues_only_within_one_plugin_process() -> None:
    registry = SameProcessTaskRegistry()
    host_a = "123e4567-e89b-12d3-a456-426614174000"
    host_b = "123e4567-e89b-12d3-a456-426614174001"

    started = registry.bind(NativeTaskMetadata(host_a, "session-a", "message-a"))
    continued = registry.bind(NativeTaskMetadata(host_a, "session-a", "message-b"))
    restarted = registry.bind(NativeTaskMetadata(host_b, "session-a", "message-c"))

    assert started.relation == "TASK_START"
    assert continued.relation == "CONTINUE"
    assert continued.task_id == started.task_id
    assert continued.task_generation == started.task_generation
    assert restarted.relation == "TASK_START"
    assert restarted.task_id != started.task_id
    assert restarted.task_generation > started.task_generation
    assert restarted.invalidated_task_count == 1


def test_native_session_registry_rejects_operation_replay_without_advancing_state() -> None:
    registry = SameProcessTaskRegistry()
    metadata = NativeTaskMetadata(
        "123e4567-e89b-12d3-a456-426614174000",
        "session-a",
        "message-a",
    )
    registry.bind(metadata)
    before = registry.snapshot()

    with pytest.raises(TaskBindingConflict, match="operation replay"):
        registry.bind(metadata)

    assert registry.snapshot() == before


def test_native_session_registry_allows_synchronous_tool_continuation_without_advancing() -> None:
    registry = SameProcessTaskRegistry()
    metadata = NativeTaskMetadata(
        "123e4567-e89b-12d3-a456-426614174000",
        "session-a",
        "message-a",
    )
    started = registry.bind(metadata)
    before = registry.snapshot()

    continued = registry.bind(metadata, allow_operation_continuation=True)

    assert continued.relation == "CONTINUE"
    assert continued.task_id == started.task_id
    assert continued.task_generation == started.task_generation
    assert registry.snapshot() == before
