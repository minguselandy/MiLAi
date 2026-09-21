"""Host task identity, transition and cache-reuse state machine."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from milai_client import (
    AgentRecallPolicy,
    MemoryNeedResolution,
    TaskBindingContext,
    TaskMemoryIdentity,
    TaskMemoryState,
)
from milai_client.context_policy import PrefetchContext
from milai_client.models import PrepareContextEvent

from milai_openworker_mcp.host.ingress import StartupTaskPolicy
from milai_openworker_mcp.host.request_contract import OpenWorkerAdapterError
from milai_openworker_mcp.host.tool_compat import _canonical
from milai_openworker_mcp.task_binding import (
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
    HostTaskRegistry,
    HostTaskRelationEvent,
    NativeTaskMetadata,
    SameProcessTaskRegistry,
    TaskBindingConflict,
    TaskResolution,
    bind_host_task,
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


@dataclass(frozen=True, slots=True)
class _BoundTaskState:
    state: TaskMemoryState
    binding_context: TaskBindingContext
    resolution: TaskResolution
    identity: TaskMemoryIdentity
    active_goal: str
    task_key: str
    event: PrepareContextEvent
    declared_event: str
    transition: str
    event_adjustment: str | None
    retained: PrefetchContext | None



class HostTaskState:
    """Internal base owning deterministic native and host task binding."""

    task_session_id: str | None
    run_id: str
    task_policy: AgentRecallPolicy
    startup_task_policy: StartupTaskPolicy | None
    task_registry: HostTaskRegistry
    native_task_registry: SameProcessTaskRegistry
    task_relation_resolver: DeterministicTaskRelationResolver
    task_transition_validator: DeterministicTaskTransitionValidator
    _task_lock: Any
    _native_bind_lock: Any
    _task_sequence: int
    _task_contexts: dict[str, PrefetchContext]
    _active_task_key_by_task: dict[str, str]
    _last_need_by_task_key: dict[str, MemoryNeedResolution]

    def _record(self, event: Mapping[str, Any]) -> None:
        raise NotImplementedError

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
        event: PrepareContextEvent
        if binding_context.registry_revision_before == 0:
            event = "TASK_START"
        elif binding_context.cache_reuse_constraint == "PROHIBITED":
            event = "GOAL_CHANGED"
        else:
            event = cast(PrepareContextEvent, declared_event or "EXPLICIT_MEMORY_REQUEST")
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

