from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Literal, cast
from uuid import UUID

from milai_client import (
    ExecutionBindingToken,
    TaskBindingConstraints,
    TaskBindingContext,
    TaskBindingTransition,
    TaskMemoryBinding,
    TaskMemoryState,
    TaskRelationDecision,
)
from milai_client.task_state import CacheReuseConstraint, TaskRelation


class TaskBindingError(RuntimeError):
    pass


class TaskBindingConflict(TaskBindingError):
    pass


_NATIVE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


@dataclass(frozen=True, slots=True)
class NativeTaskMetadata:
    """The only model-external task identity emitted by the OpenWorker plugin."""

    host_instance: str
    task_session: str
    task_operation: str

    def __post_init__(self) -> None:
        try:
            parsed_host = UUID(self.host_instance)
        except (ValueError, AttributeError) as exc:
            raise TaskBindingError("host instance is not a UUID") from exc
        if str(parsed_host) != self.host_instance.lower():
            raise TaskBindingError("host instance UUID is not canonical")
        for value, label in (
            (self.task_session, "task session"),
            (self.task_operation, "task operation"),
        ):
            if not value.isascii() or _NATIVE_IDENTIFIER.fullmatch(value) is None:
                raise TaskBindingError(f"{label} is invalid")


NativeTaskRelation = Literal["TASK_START", "CONTINUE"]


@dataclass(frozen=True, slots=True)
class NativeTaskBinding:
    task_id: str
    task_generation: int
    relation: NativeTaskRelation
    operation_id: str
    invalidated_task_count: int


@dataclass(frozen=True, slots=True)
class SameProcessTaskSnapshot:
    process_generation: int
    host_instance_sha256: str | None
    session_task_ids: tuple[tuple[str, str], ...]
    seen_operations: tuple[tuple[str, str], ...]


class SameProcessTaskRegistry:
    """Derive task continuity only from one live OpenWorker plugin process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._host_instance: str | None = None
        self._process_generation = 0
        self._session_task_ids: dict[str, str] = {}
        self._seen_operations: set[tuple[str, str]] = set()

    def snapshot(self) -> SameProcessTaskSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def bind(
        self,
        metadata: NativeTaskMetadata,
        *,
        allow_operation_continuation: bool = False,
    ) -> NativeTaskBinding:
        with self._lock:
            invalidated = 0
            if metadata.host_instance != self._host_instance:
                invalidated = len(self._session_task_ids)
                self._host_instance = metadata.host_instance
                self._process_generation += 1
                self._session_task_ids.clear()
                self._seen_operations.clear()

            operation_key = (metadata.task_session, metadata.task_operation)
            if operation_key in self._seen_operations:
                if allow_operation_continuation:
                    task_id = self._session_task_ids[metadata.task_session]
                    return NativeTaskBinding(
                        task_id=task_id,
                        task_generation=self._process_generation,
                        relation="CONTINUE",
                        operation_id=metadata.task_operation,
                        invalidated_task_count=0,
                    )
                raise TaskBindingConflict("native task operation replay")

            task_id = self._session_task_ids.get(metadata.task_session)
            relation: NativeTaskRelation
            if task_id is None:
                task_id = (
                    "ow-task-"
                    + hashlib.sha256(
                        _canonical(
                            {
                                "host_instance": metadata.host_instance,
                                "task_session": metadata.task_session,
                            }
                        )
                    ).hexdigest()[:48]
                )
                self._session_task_ids[metadata.task_session] = task_id
                relation = "TASK_START"
            else:
                relation = "CONTINUE"
            self._seen_operations.add(operation_key)
            return NativeTaskBinding(
                task_id=task_id,
                task_generation=self._process_generation,
                relation=relation,
                operation_id=metadata.task_operation,
                invalidated_task_count=invalidated,
            )

    def _snapshot_locked(self) -> SameProcessTaskSnapshot:
        return SameProcessTaskSnapshot(
            process_generation=self._process_generation,
            host_instance_sha256=(
                hashlib.sha256(self._host_instance.encode()).hexdigest()
                if self._host_instance is not None
                else None
            ),
            session_task_ids=tuple(sorted(self._session_task_ids.items())),
            seen_operations=tuple(sorted(self._seen_operations)),
        )


@dataclass(frozen=True, slots=True)
class TaskRegistrySnapshot:
    registry_revision: int
    tasks: dict[str, TaskMemoryState]
    active_by_execution_lane: dict[str, str]
    parent_child_edges: tuple[tuple[str, str], ...]
    suspended_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HostTaskRelationEvent:
    """Normalized Host execution evidence; user text and retrieval are deliberately absent."""

    normalized_relation: TaskRelation | None = None
    operation_id: str | None = None
    strong_suspended_task_id: str | None = None
    completed_unrelated_lineage: bool = False


@dataclass(frozen=True, slots=True)
class TaskResolution:
    decision: TaskRelationDecision
    resolver_ms: float
    task_transition_ms: float = 0.0
    task_state_rebind_ms: float = 0.0
    llm_calls: int = 0
    embedding_calls: int = 0
    retrieval_calls: int = 0
    training_calls: int = 0
    hidden_provider_calls: int = 0


DelayedResultStatus = Literal[
    "BOUND_TO_ORIGIN",
    "RETAINED_FOR_SUSPENDED_TASK",
    "ORPHAN_TASK_MISSING",
    "ORPHAN_GENERATION_MISMATCH",
    "ORPHAN_BINDING_MISMATCH",
    "ORPHAN_OPERATION_RESOLVED",
]


@dataclass(frozen=True, slots=True)
class DelayedResultBinding:
    status: DelayedResultStatus
    origin_task_id: str
    completion_active_task_id: str | None
    bound_task_id: str | None
    registry_revision_before: int
    registry_revision_after: int

    @property
    def wrong_task_binding(self) -> bool:
        return self.bound_task_id is not None and self.bound_task_id != self.origin_task_id


class DeterministicTaskRelationResolver:
    """Pure lexicographic resolver with no model or memory-query dependency."""

    def resolve(
        self,
        snapshot: TaskRegistrySnapshot,
        incoming: TaskMemoryState,
        event: HostTaskRelationEvent,
    ) -> TaskResolution:
        started = perf_counter()
        identity = incoming.identity
        lane_id = identity.execution_lane_id
        source_task_id = snapshot.active_by_execution_lane.get(lane_id)
        source = snapshot.tasks.get(source_task_id) if source_task_id is not None else None
        candidate = snapshot.tasks.get(identity.task_id)
        compatibility_reference = (
            candidate
            if candidate is not None
            and (
                event.normalized_relation == "RETURN"
                or event.strong_suspended_task_id == identity.task_id
            )
            else source
        )
        scope_compatible = _scope_compatible(compatibility_reference, incoming)
        profile_compatible = _profile_compatible(compatibility_reference, incoming)

        relation: TaskRelation
        confidence: Literal["HARD", "STRUCTURED", "AMBIGUOUS"]
        reasons: tuple[str, ...]

        if source is None:
            if candidate is not None and candidate.identity.status == "SUSPENDED":
                relation = "RETURN"
                confidence = "STRUCTURED"
                reasons = ("LANE_EMPTY_SUSPENDED_TARGET",)
            else:
                relation = "SWITCH"
                confidence = "HARD"
                reasons = ("REGISTRY_LANE_TASK_START",)
            scope_compatible = True
            profile_compatible = True
        elif (not scope_compatible or not profile_compatible) and (
            event.normalized_relation != "SWITCH"
        ):
            relation = "AMBIGUOUS"
            confidence = "AMBIGUOUS"
            reasons = tuple(
                reason
                for incompatible, reason in (
                    (not scope_compatible, "SCOPE_INCOMPATIBLE_NO_HOST_REBIND"),
                    (not profile_compatible, "PROFILE_INCOMPATIBLE_NO_HOST_REBIND"),
                )
                if incompatible
            )
        elif event.normalized_relation == "SWITCH" or event.completed_unrelated_lineage:
            relation = "SWITCH"
            confidence = "HARD"
            reasons = (
                (
                    "HOST_NORMALIZED_EXPLICIT_SWITCH"
                    if event.normalized_relation == "SWITCH"
                    else "COMPLETED_UNRELATED_LINEAGE"
                ),
            )
        elif (
            identity.task_id == source.identity.task_id
            and event.operation_id is not None
            and event.operation_id in source.identity.unresolved_operation_ids
        ):
            relation = "CONTINUE"
            confidence = "HARD"
            reasons = ("SAME_UNRESOLVED_HOST_OPERATION",)
        elif identity.task_id == source.identity.task_id:
            relation = "CONTINUE"
            confidence = "HARD"
            reasons = (
                (
                    "HOST_NORMALIZED_EXPLICIT_CONTINUE"
                    if event.normalized_relation == "CONTINUE"
                    else "SAME_HOST_TASK_ID_COMPATIBLE"
                ),
            )
        elif (
            event.normalized_relation == "SUBTASK"
            and identity.parent_task_id == source.identity.task_id
        ):
            relation = "SUBTASK"
            confidence = "STRUCTURED"
            reasons = ("COMPATIBLE_HOST_CHILD_OPERATION",)
        elif (
            candidate is not None
            and candidate.identity.status == "SUSPENDED"
            and (
                event.normalized_relation == "RETURN"
                or event.strong_suspended_task_id == identity.task_id
            )
            and _scope_compatible(candidate, incoming)
            and _profile_compatible(candidate, incoming)
        ):
            relation = "RETURN"
            confidence = "STRUCTURED"
            reasons = ("STRONG_SUSPENDED_TASK_MATCH",)
        else:
            relation = "AMBIGUOUS"
            confidence = "AMBIGUOUS"
            reasons = ("INSUFFICIENT_HOST_EXECUTION_EVIDENCE",)

        cache_reuse: CacheReuseConstraint = (
            "ELIGIBLE_FOR_VALIDATION"
            if relation == "CONTINUE"
            and source is not None
            and incoming.identity == source.identity
            else "PROHIBITED"
        )
        decision = TaskRelationDecision(
            source_task_id=source_task_id,
            candidate_target_task_id=(
                identity.task_id if relation != "AMBIGUOUS" or candidate is not None else None
            ),
            relation=relation,
            confidence_tier=confidence,
            reason_codes=reasons,
            scope_compatible=scope_compatible,
            profile_compatible=profile_compatible,
            binding_constraints=TaskBindingConstraints(cache_reuse),
        )
        return TaskResolution(
            decision=decision,
            resolver_ms=round((perf_counter() - started) * 1_000, 6),
        )


class DeterministicTaskTransitionValidator:
    """Builds a proposed transition without mutating Registry state."""

    def plan(
        self,
        snapshot: TaskRegistrySnapshot,
        incoming: TaskMemoryState,
        decision: TaskRelationDecision,
    ) -> TaskBindingTransition:
        source = (
            snapshot.tasks.get(decision.source_task_id)
            if decision.source_task_id is not None
            else None
        )
        expected_generation = source.identity.task_generation if source is not None else 0
        operation = {
            "CONTINUE": "KEEP",
            "SUBTASK": "CREATE_CHILD",
            "RETURN": "REACTIVATE",
            "AMBIGUOUS": "TENTATIVE",
            "SWITCH": (
                "CREATE_AND_ACTIVATE"
                if source is None or source.identity.task_id == incoming.identity.task_id
                else "SUSPEND_AND_SWITCH"
            ),
        }[decision.relation]
        return TaskBindingTransition(
            operation=cast(Any, operation),
            source_task_id=decision.source_task_id,
            target_task_id=(
                incoming.identity.task_id if decision.relation != "AMBIGUOUS" else None
            ),
            expected_registry_revision=snapshot.registry_revision,
            expected_task_generation=expected_generation,
        )


class HostTaskRegistry:
    """Host-owned per-lane task graph with revision/generation CAS mutation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revision = 0
        self._tasks: dict[str, TaskMemoryState] = {}
        self._active_by_lane: dict[str, str] = {}
        self._parent_child_edges: set[tuple[str, str]] = set()
        self._suspended_task_ids: set[str] = set()

    def snapshot(self) -> TaskRegistrySnapshot:
        with self._lock:
            return self._snapshot_locked()

    def apply(
        self,
        incoming: TaskMemoryState,
        decision: TaskRelationDecision,
        transition: TaskBindingTransition,
    ) -> TaskBindingContext:
        with self._lock:
            revision_before = self._revision
            self._verify_cas_locked(transition)
            if transition.operation == "TENTATIVE":
                safe_binding = TaskMemoryBinding(task_id=incoming.task_id)
                return TaskBindingContext(
                    incoming.identity,
                    safe_binding,
                    decision,
                    transition,
                    revision_before,
                    self._revision,
                    True,
                )
            if transition.operation == "KEEP":
                state = self._keep_locked(incoming, transition)
            elif transition.operation == "CREATE_AND_ACTIVATE":
                state = self._create_or_rebind_locked(incoming, transition)
            elif transition.operation == "CREATE_CHILD":
                state = self._create_child_locked(incoming, transition)
            elif transition.operation == "SUSPEND_AND_SWITCH":
                state = self._switch_locked(incoming, transition)
            elif transition.operation == "REACTIVATE":
                state = self._reactivate_locked(incoming, transition)
            else:  # pragma: no cover - Literal exhaustiveness
                raise TaskBindingConflict("unknown task transition operation")
            self._assert_invariants_locked()
            return TaskBindingContext(
                state.identity,
                state.memory_binding,
                decision,
                transition,
                revision_before,
                self._revision,
                False,
            )

    def begin_operation(
        self,
        context: TaskBindingContext,
        operation_id: str,
    ) -> ExecutionBindingToken:
        if not operation_id.strip() or len(operation_id) > 256:
            raise TaskBindingError("operation_id is invalid")
        with self._lock:
            if self._revision != context.registry_revision_after:
                raise TaskBindingConflict("operation invocation registry revision changed")
            state = self._tasks.get(context.identity_state.task_id)
            if (
                state is None
                or state.identity.task_generation != context.identity_state.task_generation
            ):
                raise TaskBindingConflict("operation invocation task generation changed")
            if self._active_by_lane.get(state.identity.execution_lane_id) != state.task_id:
                raise TaskBindingConflict("operation invocation task is not lane-active")
            if operation_id in state.identity.unresolved_operation_ids:
                raise TaskBindingConflict("operation_id is already unresolved")
            identity = replace(
                state.identity,
                unresolved_operation_ids=(
                    *state.identity.unresolved_operation_ids,
                    operation_id,
                ),
            )
            self._tasks[state.task_id] = TaskMemoryState(identity, state.memory_binding)
            self._revision += 1
            return ExecutionBindingToken(
                task_id=state.task_id,
                task_generation=identity.task_generation,
                lane_id=identity.execution_lane_id,
                operation_id=operation_id,
                registry_revision_at_invocation=self._revision,
                scope_digest=identity.scope_digest,
                profile_digest=identity.profile_digest,
            )

    def bind_tool_result(self, token: ExecutionBindingToken) -> DelayedResultBinding:
        with self._lock:
            revision_before = self._revision
            completion_active_task_id = self._active_by_lane.get(token.lane_id)
            state = self._tasks.get(token.task_id)
            if state is None:
                return DelayedResultBinding(
                    "ORPHAN_TASK_MISSING",
                    token.task_id,
                    completion_active_task_id,
                    None,
                    revision_before,
                    self._revision,
                )
            identity = state.identity
            if identity.task_generation != token.task_generation:
                return DelayedResultBinding(
                    "ORPHAN_GENERATION_MISMATCH",
                    token.task_id,
                    completion_active_task_id,
                    None,
                    revision_before,
                    self._revision,
                )
            if (
                identity.scope_digest != token.scope_digest
                or identity.profile_digest != token.profile_digest
            ):
                return DelayedResultBinding(
                    "ORPHAN_BINDING_MISMATCH",
                    token.task_id,
                    completion_active_task_id,
                    None,
                    revision_before,
                    self._revision,
                )
            if token.operation_id not in identity.unresolved_operation_ids:
                return DelayedResultBinding(
                    "ORPHAN_OPERATION_RESOLVED",
                    token.task_id,
                    completion_active_task_id,
                    None,
                    revision_before,
                    self._revision,
                )
            unresolved = tuple(
                value for value in identity.unresolved_operation_ids if value != token.operation_id
            )
            self._tasks[token.task_id] = TaskMemoryState(
                replace(identity, unresolved_operation_ids=unresolved),
                state.memory_binding,
            )
            self._revision += 1
            status: DelayedResultStatus = (
                "RETAINED_FOR_SUSPENDED_TASK"
                if identity.status == "SUSPENDED"
                else "BOUND_TO_ORIGIN"
            )
            return DelayedResultBinding(
                status,
                token.task_id,
                completion_active_task_id,
                token.task_id,
                revision_before,
                self._revision,
            )

    def _verify_cas_locked(self, transition: TaskBindingTransition) -> None:
        if transition.expected_registry_revision != self._revision:
            raise TaskBindingConflict("registry revision CAS failed")
        if transition.source_task_id is None:
            if transition.expected_task_generation != 0:
                raise TaskBindingConflict("initial transition generation must be zero")
            return
        source = self._tasks.get(transition.source_task_id)
        if source is None:
            raise TaskBindingConflict("source task is absent")
        if source.identity.task_generation != transition.expected_task_generation:
            raise TaskBindingConflict("task generation CAS failed")

    def _keep_locked(
        self, incoming: TaskMemoryState, transition: TaskBindingTransition
    ) -> TaskMemoryState:
        source = self._source_locked(transition)
        if incoming.task_id != source.task_id:
            raise TaskBindingConflict("KEEP target differs from source")
        if not _scope_compatible(source, incoming) or not _profile_compatible(source, incoming):
            raise TaskBindingConflict("KEEP compatibility failed")
        if incoming.identity.task_generation != source.identity.task_generation:
            raise TaskBindingConflict("KEEP task generation changed")
        if incoming.identity.binding_generation < source.identity.binding_generation:
            raise TaskBindingConflict("binding generation moved backwards")
        identity_changed = incoming.identity != replace(source.identity, status="ACTIVE")
        if identity_changed and (
            incoming.identity.binding_generation == source.identity.binding_generation
        ):
            raise TaskBindingConflict("binding generation did not advance")
        state = TaskMemoryState(
            replace(incoming.identity, status="ACTIVE"), incoming.memory_binding
        )
        if state != source:
            self._tasks[state.task_id] = state
            self._revision += 1
        return state

    def _create_or_rebind_locked(
        self, incoming: TaskMemoryState, transition: TaskBindingTransition
    ) -> TaskMemoryState:
        existing = self._tasks.get(incoming.task_id)
        if existing is not None:
            source = self._source_locked(transition)
            if source.task_id != incoming.task_id:
                raise TaskBindingConflict("cannot overwrite an existing target task")
            if incoming.identity.task_generation != source.identity.task_generation + 1:
                raise TaskBindingConflict("task rebind generation did not advance exactly once")
        state = TaskMemoryState(
            replace(incoming.identity, status="ACTIVE"), incoming.memory_binding
        )
        self._tasks[state.task_id] = state
        self._active_by_lane[state.identity.execution_lane_id] = state.task_id
        self._suspended_task_ids.discard(state.task_id)
        self._revision += 1
        return state

    def _create_child_locked(
        self, incoming: TaskMemoryState, transition: TaskBindingTransition
    ) -> TaskMemoryState:
        parent = self._source_locked(transition)
        if incoming.identity.parent_task_id != parent.task_id:
            raise TaskBindingConflict("child parent does not match active source")
        if incoming.task_id in self._tasks:
            raise TaskBindingConflict("child task already exists")
        if not _scope_compatible(parent, incoming) or not _profile_compatible(parent, incoming):
            raise TaskBindingConflict("child compatibility failed")
        self._suspend_locked(parent.task_id)
        state = TaskMemoryState(
            replace(incoming.identity, status="ACTIVE"), incoming.memory_binding
        )
        self._tasks[state.task_id] = state
        self._active_by_lane[state.identity.execution_lane_id] = state.task_id
        self._parent_child_edges.add((parent.task_id, state.task_id))
        self._revision += 1
        return state

    def _switch_locked(
        self, incoming: TaskMemoryState, transition: TaskBindingTransition
    ) -> TaskMemoryState:
        source = self._source_locked(transition)
        if incoming.task_id in self._tasks:
            raise TaskBindingConflict("SWITCH target already exists; use RETURN")
        self._suspend_locked(source.task_id)
        state = TaskMemoryState(
            replace(incoming.identity, status="ACTIVE"), incoming.memory_binding
        )
        self._tasks[state.task_id] = state
        self._active_by_lane[state.identity.execution_lane_id] = state.task_id
        self._revision += 1
        return state

    def _reactivate_locked(
        self, incoming: TaskMemoryState, transition: TaskBindingTransition
    ) -> TaskMemoryState:
        target = self._tasks.get(incoming.task_id)
        if target is None or target.identity.status != "SUSPENDED":
            raise TaskBindingConflict("RETURN target is not suspended")
        if incoming.identity.task_generation != target.identity.task_generation:
            raise TaskBindingConflict("RETURN target generation changed")
        if not _scope_compatible(target, incoming) or not _profile_compatible(target, incoming):
            raise TaskBindingConflict("RETURN compatibility failed")
        source = self._source_locked(transition)
        if source.task_id != target.task_id:
            self._suspend_locked(source.task_id)
        state = TaskMemoryState(
            replace(incoming.identity, status="ACTIVE"), incoming.memory_binding
        )
        self._tasks[state.task_id] = state
        self._active_by_lane[state.identity.execution_lane_id] = state.task_id
        self._suspended_task_ids.discard(state.task_id)
        self._revision += 1
        return state

    def _source_locked(self, transition: TaskBindingTransition) -> TaskMemoryState:
        if transition.source_task_id is None:
            raise TaskBindingConflict("transition source is absent")
        source = self._tasks.get(transition.source_task_id)
        if source is None:
            raise TaskBindingConflict("transition source is missing")
        return source

    def _suspend_locked(self, task_id: str) -> None:
        state = self._tasks[task_id]
        self._tasks[task_id] = TaskMemoryState(
            replace(state.identity, status="SUSPENDED"), state.memory_binding
        )
        self._suspended_task_ids.add(task_id)
        lane_id = state.identity.execution_lane_id
        if self._active_by_lane.get(lane_id) == task_id:
            del self._active_by_lane[lane_id]

    def _assert_invariants_locked(self) -> None:
        active_ids = list(self._active_by_lane.values())
        if len(active_ids) != len(set(active_ids)):
            raise TaskBindingConflict("one task is active in multiple lanes")
        for lane_id, task_id in self._active_by_lane.items():
            state = self._tasks.get(task_id)
            if (
                state is None
                or state.identity.status != "ACTIVE"
                or state.identity.execution_lane_id != lane_id
            ):
                raise TaskBindingConflict("active lane registry invariant failed")
        for task_id in self._suspended_task_ids:
            if self._tasks[task_id].identity.status != "SUSPENDED":
                raise TaskBindingConflict("suspended registry invariant failed")

    def _snapshot_locked(self) -> TaskRegistrySnapshot:
        return TaskRegistrySnapshot(
            self._revision,
            dict(self._tasks),
            dict(self._active_by_lane),
            tuple(sorted(self._parent_child_edges)),
            tuple(sorted(self._suspended_task_ids)),
        )


class OpaqueExecutionBindingCodec:
    """Integrity- and audience-bound correlation handle; it grants no memory authority."""

    def __init__(self, key: bytes, *, audience: str) -> None:
        if len(key) < 32 or not audience.strip():
            raise ValueError("opaque execution binding key/audience is invalid")
        self._key = bytes(key)
        self._audience = audience.strip()

    def encode(self, token: ExecutionBindingToken) -> str:
        payload = _canonical({"audience": self._audience, "binding": token.canonical()})
        signature = hmac.new(self._key, payload, hashlib.sha256).digest()
        return _b64(payload) + "." + _b64(signature)

    def decode(self, handle: str) -> ExecutionBindingToken:
        try:
            payload_part, signature_part = handle.split(".", 1)
            payload = _unb64(payload_part)
            signature = _unb64(signature_part)
        except (ValueError, UnicodeError) as exc:
            raise TaskBindingError("execution binding handle is malformed") from exc
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise TaskBindingError("execution binding handle integrity failed")
        value = json.loads(payload)
        if not isinstance(value, Mapping) or value.get("audience") != self._audience:
            raise TaskBindingError("execution binding handle audience failed")
        binding = value.get("binding")
        if not isinstance(binding, Mapping):
            raise TaskBindingError("execution binding handle payload failed")
        try:
            return ExecutionBindingToken(
                task_id=str(binding["task_id"]),
                task_generation=int(binding["task_generation"]),
                lane_id=str(binding["lane_id"]),
                operation_id=str(binding["operation_id"]),
                registry_revision_at_invocation=int(binding["registry_revision_at_invocation"]),
                scope_digest=str(binding["scope_digest"]),
                profile_digest=str(binding["profile_digest"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskBindingError("execution binding handle fields failed") from exc


def bind_host_task(
    registry: HostTaskRegistry,
    resolver: DeterministicTaskRelationResolver,
    validator: DeterministicTaskTransitionValidator,
    incoming: TaskMemoryState,
    event: HostTaskRelationEvent,
) -> tuple[TaskBindingContext, TaskResolution]:
    snapshot = registry.snapshot()
    resolution = resolver.resolve(snapshot, incoming, event)
    transition_started = perf_counter()
    transition = validator.plan(snapshot, incoming, resolution.decision)
    transition_ms = round((perf_counter() - transition_started) * 1_000, 6)
    rebind_started = perf_counter()
    context = registry.apply(incoming, resolution.decision, transition)
    rebind_ms = round((perf_counter() - rebind_started) * 1_000, 6)
    return context, replace(
        resolution,
        task_transition_ms=transition_ms,
        task_state_rebind_ms=rebind_ms,
    )


def _scope_compatible(left: TaskMemoryState | None, right: TaskMemoryState) -> bool:
    return left is None or left.identity.project_scope == right.identity.project_scope


def _profile_compatible(left: TaskMemoryState | None, right: TaskMemoryState) -> bool:
    return left is None or left.identity.profile_identity == right.identity.profile_identity


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
