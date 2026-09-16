from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from uuid import UUID

TaskStatus = Literal["ACTIVE", "SUSPENDED", "COMPLETED"]
TaskRelation = Literal["CONTINUE", "SUBTASK", "SWITCH", "RETURN", "AMBIGUOUS"]
TaskConfidenceTier = Literal["HARD", "STRUCTURED", "AMBIGUOUS"]
CacheReuseConstraint = Literal["PROHIBITED", "ELIGIBLE_FOR_VALIDATION"]
TaskTransitionOperation = Literal[
    "KEEP",
    "CREATE_AND_ACTIVATE",
    "CREATE_CHILD",
    "SUSPEND_AND_SWITCH",
    "REACTIVATE",
    "TENTATIVE",
]


@dataclass(frozen=True, slots=True)
class CanonicalStateKey:
    subject: str
    predicate: str
    claim_type: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.subject, self.predicate, self.claim_type)):
            raise ValueError("canonical state key fields are required")

    @classmethod
    def from_host_payload(cls, value: object) -> CanonicalStateKey:
        if not isinstance(value, Mapping) or set(value) != {
            "subject",
            "predicate",
            "claim_type",
        }:
            raise ValueError("canonical state key payload is invalid")
        return cls(
            subject=_bounded_string(value["subject"], "state key subject", 512),
            predicate=_bounded_string(value["predicate"], "state key predicate", 256),
            claim_type=_bounded_string(value["claim_type"], "state key claim_type", 128),
        )

    def canonical(self) -> dict[str, str]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "claim_type": self.claim_type,
        }


@dataclass(frozen=True, slots=True)
class TaskIdentityState:
    task_id: str
    parent_task_id: str | None
    status: TaskStatus
    task_generation: int
    binding_generation: int
    project_scope: dict[str, Any]
    profile_identity: str
    active_goal_id: str
    active_goal_version: int
    active_goal_summary: str
    execution_lane_id: str
    plan_node_id: str | None
    unresolved_operation_ids: tuple[str, ...]
    workspace_ref: str | None
    artifact_refs: tuple[str, ...]
    created_epoch: int
    last_active_epoch: int

    def __post_init__(self) -> None:
        for value, label, limit in (
            (self.task_id, "task_id", 256),
            (self.profile_identity, "profile_identity", 128),
            (self.active_goal_id, "active_goal_id", 256),
            (self.active_goal_summary, "active_goal_summary", 2_000),
            (self.execution_lane_id, "execution_lane_id", 256),
        ):
            _bounded_string(value, label, limit)
        _optional_string(self.parent_task_id, "parent_task_id", 256)
        _optional_string(self.plan_node_id, "plan_node_id", 256)
        _optional_string(self.workspace_ref, "workspace_ref", 2_048)
        if self.status not in {"ACTIVE", "SUSPENDED", "COMPLETED"}:
            raise ValueError("task status is invalid")
        if self.task_generation < 1 or self.binding_generation < 1:
            raise ValueError("task and binding generations must be positive")
        if self.active_goal_version < 1:
            raise ValueError("active_goal_version must be positive")
        if self.created_epoch < 0 or self.last_active_epoch < self.created_epoch:
            raise ValueError("task epochs are invalid")
        _bounded_unique_strings(self.unresolved_operation_ids, "unresolved_operation_ids", 256, 128)
        _bounded_unique_strings(self.artifact_refs, "artifact_refs", 2_048, 128)

    @property
    def scope_digest(self) -> str:
        return _digest(self.project_scope)

    @property
    def profile_digest(self) -> str:
        return _digest(self.profile_identity)

    @property
    def binding_digest(self) -> str:
        return _digest(self.canonical())

    def canonical(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "status": self.status,
            "task_generation": self.task_generation,
            "binding_generation": self.binding_generation,
            "project_scope": self.project_scope,
            "profile_identity": self.profile_identity,
            "active_goal_id": self.active_goal_id,
            "active_goal_version": self.active_goal_version,
            "active_goal_summary": self.active_goal_summary,
            "execution_lane_id": self.execution_lane_id,
            "plan_node_id": self.plan_node_id,
            "unresolved_operation_ids": list(self.unresolved_operation_ids),
            "workspace_ref": self.workspace_ref,
            "artifact_refs": list(self.artifact_refs),
            "created_epoch": self.created_epoch,
            "last_active_epoch": self.last_active_epoch,
        }


@dataclass(frozen=True, slots=True)
class TaskMemoryBinding:
    task_id: str
    known_claim_ids: tuple[str, ...] = ()
    known_state_keys: tuple[CanonicalStateKey, ...] = ()
    relevant_open_issue_ids: tuple[str, ...] = ()
    canonical_position_seen: int | None = None
    slot_id: str | None = None
    slot_validation_handle: str | None = field(default=None, repr=False)
    slot_coverage: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        _bounded_string(self.task_id, "task_id", 256)
        if self.canonical_position_seen is not None and self.canonical_position_seen < 0:
            raise ValueError("canonical_position_seen must be non-negative")
        _optional_string(self.slot_id, "slot_id", 256)
        _optional_string(self.slot_validation_handle, "slot_validation_handle", 8_192)

    def canonical(self, *, include_validation_handle: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "known_claim_ids": list(self.known_claim_ids),
            "known_state_keys": [key.canonical() for key in self.known_state_keys],
            "relevant_open_issue_ids": list(self.relevant_open_issue_ids),
            "canonical_position_seen": self.canonical_position_seen,
            "slot_id": self.slot_id,
            "slot_coverage": self.slot_coverage,
        }
        if include_validation_handle:
            result["slot_validation_handle"] = self.slot_validation_handle
        return result


@dataclass(frozen=True, slots=True)
class TaskMemoryState:
    """Host-owned envelope with identity and memory locator state kept separate."""

    identity: TaskIdentityState
    memory_binding: TaskMemoryBinding

    def __post_init__(self) -> None:
        if self.identity.task_id != self.memory_binding.task_id:
            raise ValueError("identity and memory binding task_id differ")

    @classmethod
    def from_host_payload(
        cls,
        value: object,
        *,
        fallback_task_id: str,
        fallback_scope: Mapping[str, Any],
        fallback_profile_id: str,
        fallback_execution_lane_id: str = "primary",
    ) -> TaskMemoryState:
        if value is None:
            goal_digest = hashlib.sha256(fallback_task_id.encode()).hexdigest()[:24]
            identity = TaskIdentityState(
                task_id=fallback_task_id,
                parent_task_id=None,
                status="ACTIVE",
                task_generation=1,
                binding_generation=1,
                project_scope=dict(fallback_scope),
                profile_identity=fallback_profile_id,
                active_goal_id=f"host-default-goal-{goal_digest}",
                active_goal_version=1,
                active_goal_summary="Continue the host-owned task.",
                execution_lane_id=fallback_execution_lane_id,
                plan_node_id=None,
                unresolved_operation_ids=(),
                workspace_ref=None,
                artifact_refs=(),
                created_epoch=0,
                last_active_epoch=0,
            )
            return cls(identity, TaskMemoryBinding(task_id=fallback_task_id))
        if not isinstance(value, Mapping):
            raise ValueError("milai_task_state must be a Host-owned object")
        required = {
            "task_id",
            "active_goal_id",
            "active_goal_version",
            "active_goal_summary",
            "project_scope",
        }
        identity_fields = {
            "parent_task_id",
            "status",
            "task_generation",
            "binding_generation",
            "profile_id",
            "profile_identity",
            "execution_lane_id",
            "plan_node_id",
            "unresolved_operation_ids",
            "workspace_ref",
            "artifact_refs",
            "created_epoch",
            "last_active_epoch",
        }
        memory_fields = {
            "known_claim_ids",
            "known_state_keys",
            "relevant_open_issue_ids",
            "canonical_position_seen",
            "slot_id",
            "slot_validation_handle",
            "slot_coverage",
        }
        if (
            not required.issubset(value)
            or not set(value).issubset(required | identity_fields | memory_fields)
            or ("profile_id" in value and "profile_identity" in value)
        ):
            raise ValueError("milai_task_state field set is invalid")
        scope = value["project_scope"]
        if not isinstance(scope, Mapping):
            raise ValueError("project_scope must be an object")
        version = _integer(value["active_goal_version"], "active_goal_version", minimum=1)
        task_generation = _integer(value.get("task_generation", 1), "task_generation", minimum=1)
        binding_generation = _integer(
            value.get("binding_generation", 1), "binding_generation", minimum=1
        )
        created_epoch = _integer(value.get("created_epoch", 0), "created_epoch", minimum=0)
        last_active_epoch = _integer(
            value.get("last_active_epoch", created_epoch), "last_active_epoch", minimum=0
        )
        canonical_position = value.get("canonical_position_seen")
        if canonical_position is not None:
            canonical_position = _integer(canonical_position, "canonical_position_seen", minimum=0)
        task_id = _bounded_string(value["task_id"], "task_id", 256)
        identity = TaskIdentityState(
            task_id=task_id,
            parent_task_id=_optional_string(value.get("parent_task_id"), "parent_task_id", 256),
            status=_task_status(value.get("status", "ACTIVE")),
            task_generation=task_generation,
            binding_generation=binding_generation,
            project_scope=dict(scope),
            profile_identity=_bounded_string(
                value.get("profile_identity", value.get("profile_id", fallback_profile_id)),
                "profile_identity",
                128,
            ),
            active_goal_id=_bounded_string(value["active_goal_id"], "active_goal_id", 256),
            active_goal_version=version,
            active_goal_summary=_bounded_string(
                value["active_goal_summary"], "active_goal_summary", 2_000
            ),
            execution_lane_id=_bounded_string(
                value.get("execution_lane_id", fallback_execution_lane_id),
                "execution_lane_id",
                256,
            ),
            plan_node_id=_optional_string(value.get("plan_node_id"), "plan_node_id", 256),
            unresolved_operation_ids=_string_tuple(
                value.get("unresolved_operation_ids", ()),
                "unresolved_operation_ids",
                item_limit=256,
            ),
            workspace_ref=_optional_string(value.get("workspace_ref"), "workspace_ref", 2_048),
            artifact_refs=_string_tuple(
                value.get("artifact_refs", ()), "artifact_refs", item_limit=2_048
            ),
            created_epoch=created_epoch,
            last_active_epoch=last_active_epoch,
        )
        binding = TaskMemoryBinding(
            task_id=task_id,
            known_claim_ids=_uuid_tuple(value.get("known_claim_ids", ()), "known_claim_ids"),
            known_state_keys=tuple(
                CanonicalStateKey.from_host_payload(item)
                for item in _sequence(value.get("known_state_keys", ()), "known_state_keys")
            ),
            relevant_open_issue_ids=_uuid_tuple(
                value.get("relevant_open_issue_ids", ()), "relevant_open_issue_ids"
            ),
            canonical_position_seen=canonical_position,
            slot_id=_optional_string(value.get("slot_id"), "slot_id", 256),
            slot_validation_handle=_optional_string(
                value.get("slot_validation_handle"), "slot_validation_handle", 8_192
            ),
            slot_coverage=_optional_mapping(value.get("slot_coverage"), "slot_coverage"),
        )
        return cls(identity, binding)

    @property
    def task_id(self) -> str:
        return self.identity.task_id

    @property
    def active_goal_id(self) -> str:
        return self.identity.active_goal_id

    @property
    def active_goal_version(self) -> int:
        return self.identity.active_goal_version

    @property
    def active_goal_summary(self) -> str:
        return self.identity.active_goal_summary

    @property
    def project_scope(self) -> dict[str, Any]:
        return self.identity.project_scope

    @property
    def profile_id(self) -> str:
        return self.identity.profile_identity

    @property
    def known_claim_ids(self) -> tuple[str, ...]:
        return self.memory_binding.known_claim_ids

    @property
    def known_state_keys(self) -> tuple[CanonicalStateKey, ...]:
        return self.memory_binding.known_state_keys

    @property
    def relevant_open_issue_ids(self) -> tuple[str, ...]:
        return self.memory_binding.relevant_open_issue_ids

    @property
    def canonical_position_seen(self) -> int | None:
        return self.memory_binding.canonical_position_seen

    @property
    def binding_digest(self) -> str:
        return self.identity.binding_digest


@dataclass(frozen=True, slots=True)
class TaskBindingConstraints:
    cache_reuse: CacheReuseConstraint

    def __post_init__(self) -> None:
        if self.cache_reuse not in {"PROHIBITED", "ELIGIBLE_FOR_VALIDATION"}:
            raise ValueError("cache reuse constraint is invalid")


@dataclass(frozen=True, slots=True)
class TaskRelationDecision:
    source_task_id: str | None
    candidate_target_task_id: str | None
    relation: TaskRelation
    confidence_tier: TaskConfidenceTier
    reason_codes: tuple[str, ...]
    scope_compatible: bool
    profile_compatible: bool
    binding_constraints: TaskBindingConstraints

    def __post_init__(self) -> None:
        _optional_string(self.source_task_id, "source_task_id", 256)
        _optional_string(self.candidate_target_task_id, "candidate_target_task_id", 256)
        if self.relation not in {"CONTINUE", "SUBTASK", "SWITCH", "RETURN", "AMBIGUOUS"}:
            raise ValueError("task relation is invalid")
        if self.confidence_tier not in {"HARD", "STRUCTURED", "AMBIGUOUS"}:
            raise ValueError("task confidence tier is invalid")
        _bounded_unique_strings(self.reason_codes, "reason_codes", 256, 32)


@dataclass(frozen=True, slots=True)
class TaskBindingTransition:
    operation: TaskTransitionOperation
    source_task_id: str | None
    target_task_id: str | None
    expected_registry_revision: int
    expected_task_generation: int

    def __post_init__(self) -> None:
        _optional_string(self.source_task_id, "source_task_id", 256)
        _optional_string(self.target_task_id, "target_task_id", 256)
        if self.expected_registry_revision < 0 or self.expected_task_generation < 0:
            raise ValueError("transition CAS values must be non-negative")


@dataclass(frozen=True, slots=True)
class ExecutionBindingToken:
    task_id: str
    task_generation: int
    lane_id: str
    operation_id: str
    registry_revision_at_invocation: int
    scope_digest: str
    profile_digest: str

    def __post_init__(self) -> None:
        _bounded_string(self.task_id, "task_id", 256)
        _bounded_string(self.lane_id, "lane_id", 256)
        _bounded_string(self.operation_id, "operation_id", 256)
        _bounded_string(self.scope_digest, "scope_digest", 128)
        _bounded_string(self.profile_digest, "profile_digest", 128)
        if self.task_generation < 1 or self.registry_revision_at_invocation < 0:
            raise ValueError("execution binding token generations are invalid")

    def canonical(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_generation": self.task_generation,
            "lane_id": self.lane_id,
            "operation_id": self.operation_id,
            "registry_revision_at_invocation": self.registry_revision_at_invocation,
            "scope_digest": self.scope_digest,
            "profile_digest": self.profile_digest,
        }


@dataclass(frozen=True, slots=True)
class TaskBindingContext:
    identity_state: TaskIdentityState
    memory_binding: TaskMemoryBinding
    relation_decision: TaskRelationDecision
    transition: TaskBindingTransition
    registry_revision_before: int
    registry_revision_after: int
    tentative: bool

    def __post_init__(self) -> None:
        if self.identity_state.task_id != self.memory_binding.task_id:
            raise ValueError("binding context task_id differs")
        if self.registry_revision_after < self.registry_revision_before:
            raise ValueError("registry revision moved backwards")

    @property
    def cache_reuse_constraint(self) -> CacheReuseConstraint:
        return self.relation_decision.binding_constraints.cache_reuse


def _bounded_string(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{label} must contain 1-{limit} characters")
    return value.strip()


def _optional_string(value: object, label: str, limit: int) -> str | None:
    return None if value is None else _bounded_string(value, label, limit)


def _sequence(value: object, label: str, *, limit: int = 128) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        raise ValueError(f"{label} must be a bounded array")
    return tuple(value)


def _bounded_unique_strings(
    values: tuple[str, ...], label: str, item_limit: int, count_limit: int
) -> None:
    if len(values) > count_limit or len(set(values)) != len(values):
        raise ValueError(f"{label} must contain unique bounded values")
    for value in values:
        _bounded_string(value, label, item_limit)


def _string_tuple(value: object, label: str, *, item_limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for item in _sequence(value, label):
        parsed = _bounded_string(item, label, item_limit)
        if parsed not in result:
            result.append(parsed)
    return tuple(result)


def _uuid_tuple(value: object, label: str) -> tuple[str, ...]:
    result: list[str] = []
    for item in _sequence(value, label, limit=64):
        try:
            parsed = str(UUID(str(item)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{label} must contain UUIDs") from exc
        if parsed not in result:
            result.append(parsed)
    return tuple(result)


def _optional_mapping(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object or null")
    return dict(value)


def _integer(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _task_status(value: object) -> TaskStatus:
    if value not in {"ACTIVE", "SUSPENDED", "COMPLETED"}:
        raise ValueError("task status is invalid")
    return cast(TaskStatus, value)


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
