"""Hash-only plans and reducers for DG-13U U1 lifecycle cases.

This module never invokes Docker, signals a process, or opens a socket.  It
freezes runner-owned steps and validates measured receipts without retaining
raw process, socket, container, task, or provider identities.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

Ownership = Literal["RUN_OWNED", "OBSERVATION_ONLY"]
ExecutionClass = Literal[
    "BROKER_WORKER_BIND_RECREATE", "OPENWORKER_HOST_GENERATION_RESTART"
]

MEASUREMENT_SCHEMA = "milai.dg13u.u1-lifecycle-measurement.v1"
EVIDENCE_SCHEMA = "milai.dg13u.u1-lifecycle-evidence.v1"
_HASH = re.compile(r"[0-9a-f]{64}")


class LifecycleScenarioError(ValueError):
    """A lifecycle plan or measured receipt violated the frozen contract."""


@dataclass(frozen=True, slots=True)
class LifecycleStep:
    step_id: str
    action: str
    target_kind: str
    ownership: Ownership


@dataclass(frozen=True, slots=True)
class LifecycleScenario:
    case_id: str
    execution_class: ExecutionClass
    steps: tuple[LifecycleStep, ...]
    expected_mcp_calls: Literal[0, 2]
    expected_provider_calls: Literal[0, 2]
    expected_host_health_calls: Literal[0, 1]
    expected_mcp_catalog_calls: Literal[0, 1]
    automatic_retries: Literal[0]
    maximum_attempts_per_step: Literal[1]
    vllm_policy: Literal["EXTERNAL_PRESERVE_ZERO_LIFECYCLE"]


def _step(
    step_id: str, action: str, target_kind: str, ownership: Ownership
) -> LifecycleStep:
    return LifecycleStep(step_id, action, target_kind, ownership)


LIFECYCLE_SCENARIOS: Mapping[str, LifecycleScenario] = MappingProxyType(
    {
        "U1-BROKER-INODE-RECREATE": LifecycleScenario(
            case_id="U1-BROKER-INODE-RECREATE",
            execution_class="BROKER_WORKER_BIND_RECREATE",
            steps=(
                _step(
                    "CAPTURE_OLD_SOCKET_AND_WORKER_BIND",
                    "HASH_OLD_SOCKET_DEV_INODE_AND_BOUND_WORKER_MOUNT",
                    "BROKER_SOCKET_AND_WORKER",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "STOP_OLD_RUN_OWNED_BROKER",
                    "NORMAL_STOP_EXACT_STABLE_PROCESS_IDENTITY",
                    "BROKER_PROCESS",
                    "RUN_OWNED",
                ),
                _step(
                    "CONFIRM_OLD_WORKER_BIND_UNAVAILABLE",
                    "PROBE_BOUND_TRANSPORT_WITHOUT_MCP_TOOL_CALL",
                    "WORKER_SOCKET_BIND",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "START_REPLACEMENT_BROKER_SAME_POLICY",
                    "START_ONE_BROKER_WITH_EXACT_POLICY_HASH",
                    "BROKER_PROCESS_AND_SOCKET",
                    "RUN_OWNED",
                ),
                _step(
                    "VERIFY_NEW_INODE_AND_NO_SILENT_FOLLOW",
                    "HASH_NEW_SOCKET_AND_REPROBE_OLD_WORKER_BIND",
                    "BROKER_SOCKET_AND_WORKER_BIND",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "RECREATE_WORKER_WITH_NEW_BIND",
                    "REMOVE_OLD_WORKER_THEN_CREATE_ONE_EXACT_REMOUNT",
                    "OPENWORKER_CONTAINER",
                    "RUN_OWNED",
                ),
                _step(
                    "VERIFY_RECREATED_WORKER_READINESS",
                    "MCP_LIST_CATALOG_READINESS_WITHOUT_PREPARE_OR_PROVIDER_CALL",
                    "OPENWORKER_CONTAINER",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "CLEANUP_RUN_OWNED_REPLACEMENTS",
                    "NORMAL_REVERSE_ORDER_CLEANUP",
                    "BROKER_PROCESS_SOCKET_AND_WORKER",
                    "RUN_OWNED",
                ),
            ),
            expected_mcp_calls=0,
            expected_provider_calls=0,
            expected_host_health_calls=0,
            expected_mcp_catalog_calls=1,
            automatic_retries=0,
            maximum_attempts_per_step=1,
            vllm_policy="EXTERNAL_PRESERVE_ZERO_LIFECYCLE",
        ),
        "U1-ADAPTER-RESTART": LifecycleScenario(
            case_id="U1-ADAPTER-RESTART",
            execution_class="OPENWORKER_HOST_GENERATION_RESTART",
            steps=(
                _step(
                    "WARM_OPENWORKER_A_EXACT_TURN",
                    "RUN_ONE_REAL_EXACT_TURN_THROUGH_OLD_HOST",
                    "OPENWORKER_A_AND_OLD_HOST",
                    "RUN_OWNED",
                ),
                _step(
                    "CAPTURE_WARM_BINDING_AND_OLD_HOST_GENERATION",
                    "HASH_PROCESS_SESSION_TASK_SLOT_AND_CONTEXT",
                    "OPENWORKER_A_AND_HOST_TASK_BINDING",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "STOP_OLD_RUN_OWNED_HOST",
                    "NORMAL_STOP_EXACT_STABLE_PROCESS_IDENTITY",
                    "HOST_PROCESS",
                    "RUN_OWNED",
                ),
                _step(
                    "START_REPLACEMENT_HOST_NEW_GENERATION",
                    "START_ONE_HOST_AT_SAME_ENDPOINT_WITH_EMPTY_TASK_REGISTRY",
                    "HOST_PROCESS_AND_TASK_REGISTRY",
                    "RUN_OWNED",
                ),
                _step(
                    "VERIFY_OPENWORKER_RECONNECT_AND_HOST_HEALTH",
                    "HEALTH_REPLACEMENT_HOST_AND_REQUIRE_NEW_CONNECTION_GENERATION",
                    "OPENWORKER_A_AND_REPLACEMENT_HOST",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "CONTINUE_OPENWORKER_A_THROUGH_REPLACEMENT_HOST",
                    "RUN_REAL_CONTINUATION_FOR_SAME_SESSION_AND_TASK",
                    "OPENWORKER_A_AND_REPLACEMENT_HOST",
                    "RUN_OWNED",
                ),
                _step(
                    "VERIFY_RESTART_TASK_START_READY_EXACT",
                    "REQUIRE_TASK_START_READY_EXACT_AND_NO_OLD_CACHE_SLOT",
                    "REPLACEMENT_HOST_TASK_BINDING",
                    "OBSERVATION_ONLY",
                ),
                _step(
                    "CLEANUP_RUN_OWNED_REPLACEMENT_HOST",
                    "NORMAL_REVERSE_ORDER_CLEANUP",
                    "HOST_PROCESS",
                    "RUN_OWNED",
                ),
            ),
            expected_mcp_calls=2,
            expected_provider_calls=2,
            expected_host_health_calls=1,
            expected_mcp_catalog_calls=0,
            automatic_retries=0,
            maximum_attempts_per_step=1,
            vllm_policy="EXTERNAL_PRESERVE_ZERO_LIFECYCLE",
        ),
    }
)


def scenario_for_case(case_id: str) -> LifecycleScenario:
    if not isinstance(case_id, str) or case_id not in LIFECYCLE_SCENARIOS:
        raise LifecycleScenarioError("UNSUPPORTED_CASE")
    return LIFECYCLE_SCENARIOS[case_id]


def socket_identity_sha256(device: int, inode: int) -> str:
    """Hash a live socket identity without returning either raw integer."""

    if (
        not isinstance(device, int)
        or isinstance(device, bool)
        or device < 1
        or not isinstance(inode, int)
        or isinstance(inode, bool)
        or inode < 1
    ):
        raise LifecycleScenarioError("SOCKET_IDENTITY_INVALID")
    return hashlib.sha256(f"socket:{device}:{inode}".encode()).hexdigest()


def process_identity_sha256(pid: int, stable_marker: str, generation: str) -> str:
    """Hash a process identity tuple without returning PID or marker text."""

    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid < 1
        or not isinstance(stable_marker, str)
        or not stable_marker
        or len(stable_marker) > 512
        or not isinstance(generation, str)
        or not generation
        or len(generation) > 256
    ):
        raise LifecycleScenarioError("PROCESS_IDENTITY_INVALID")
    encoded = json.dumps(
        ["process", pid, stable_marker, generation],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


_TOP_FIELDS = frozenset(
    {
        "schema",
        "case_id",
        "steps",
        "mcp_calls",
        "provider_calls",
        "automatic_retries",
        "execution_class",
        "readiness_calls",
        "vllm",
        "cleanup",
        "identity",
    }
)
_STEP_FIELDS = frozenset({"step_id", "status", "attempts", "receipt_sha256"})
_VLLM_FIELDS = frozenset(
    {
        "identity_before_sha256",
        "identity_after_sha256",
        "lifecycle_attempts",
        "preserved",
    }
)
_CLEANUP_FIELDS = frozenset(
    {"status", "attempts", "run_owned_resources_absent", "receipt_sha256"}
)
_READINESS_CALL_FIELDS = frozenset({"host_health", "mcp_catalog"})
_BROKER_IDENTITY_FIELDS = frozenset(
    {
        "old_policy_sha256",
        "replacement_policy_sha256",
        "old_broker_process_sha256",
        "replacement_broker_process_sha256",
        "old_socket_identity_sha256",
        "old_worker_bind_identity_sha256",
        "replacement_socket_identity_sha256",
        "recreated_worker_bind_identity_sha256",
        "old_broker_stopped",
        "old_worker_bind_unavailable_after_stop",
        "old_worker_followed_replacement",
        "worker_recreated_and_remounted",
        "mcp_catalog_readiness_restored",
    }
)
_ADAPTER_IDENTITY_FIELDS = frozenset(
    {
        "warm_openworker_process_sha256",
        "continuation_openworker_process_sha256",
        "old_host_endpoint_sha256",
        "replacement_host_endpoint_sha256",
        "old_host_process_sha256",
        "replacement_host_process_sha256",
        "old_generation_sha256",
        "replacement_generation_sha256",
        "old_slot_sha256",
        "replacement_slot_sha256",
        "warm_task_session_sha256",
        "continuation_task_session_sha256",
        "warm_task_id_sha256",
        "continuation_task_id_sha256",
        "warm_context_sha256",
        "continuation_context_sha256",
        "replacement_initial_registry_entry_count",
        "old_host_stopped",
        "replacement_health_ready",
        "openworker_reconnected",
        "warm_task_relation",
        "warm_prepare_status",
        "warm_route",
        "continuation_task_relation",
        "continuation_prepare_status",
        "continuation_route",
        "old_cache_slot_reused",
    }
)


def reduce_lifecycle_measurement(
    case_id: str, measurement: Mapping[str, object]
) -> dict[str, object]:
    """Validate one measured lifecycle receipt and return hash-only evidence."""

    scenario = scenario_for_case(case_id)
    if not isinstance(measurement, Mapping) or set(measurement) != _TOP_FIELDS:
        raise LifecycleScenarioError("MEASUREMENT_FIELDS_INVALID")
    if (
        measurement.get("schema") != MEASUREMENT_SCHEMA
        or measurement.get("case_id") != case_id
        or measurement.get("execution_class") != scenario.execution_class
    ):
        raise LifecycleScenarioError("MEASUREMENT_IDENTITY_INVALID")
    if any(
        not _is_exact_int(measurement.get(name), expected)
        for name, expected in (
            ("mcp_calls", scenario.expected_mcp_calls),
            ("provider_calls", scenario.expected_provider_calls),
            ("automatic_retries", 0),
        )
    ):
        raise LifecycleScenarioError("CALL_ACCOUNTING_INVALID")
    safe_readiness_calls = _validate_readiness_calls(
        scenario, measurement.get("readiness_calls")
    )
    safe_steps = _validate_steps(scenario, measurement.get("steps"))
    safe_vllm = _validate_vllm(measurement.get("vllm"))
    safe_cleanup = _validate_cleanup(measurement.get("cleanup"))
    identity = measurement.get("identity")
    if not isinstance(identity, Mapping):
        raise LifecycleScenarioError("IDENTITY_RECEIPT_INVALID")
    safe_identity = (
        _validate_broker_identity(identity)
        if case_id == "U1-BROKER-INODE-RECREATE"
        else _validate_adapter_identity(identity)
    )
    return {
        "schema": EVIDENCE_SCHEMA,
        "case_id": case_id,
        "status": "PASS",
        "execution_class": scenario.execution_class,
        "steps": safe_steps,
        "observed_mcp_calls": scenario.expected_mcp_calls,
        "observed_provider_calls": scenario.expected_provider_calls,
        "readiness_calls": safe_readiness_calls,
        "automatic_retries": 0,
        "vllm": safe_vllm,
        "cleanup": safe_cleanup,
        "identity": safe_identity,
    }


def _validate_readiness_calls(
    scenario: LifecycleScenario, raw: object
) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _READINESS_CALL_FIELDS:
        raise LifecycleScenarioError("READINESS_CALL_FIELDS_INVALID")
    if not _is_exact_int(
        raw.get("host_health"), scenario.expected_host_health_calls
    ) or not _is_exact_int(raw.get("mcp_catalog"), scenario.expected_mcp_catalog_calls):
        raise LifecycleScenarioError("READINESS_CALL_ACCOUNTING_INVALID")
    return dict(raw)


def _validate_steps(
    scenario: LifecycleScenario, raw_steps: object
) -> list[dict[str, object]]:
    if (
        not isinstance(raw_steps, Sequence)
        or isinstance(raw_steps, (str, bytes))
        or len(raw_steps) != len(scenario.steps)
    ):
        raise LifecycleScenarioError("STEP_RECEIPT_COUNT_INVALID")
    safe: list[dict[str, object]] = []
    for expected, raw in zip(scenario.steps, raw_steps, strict=True):
        if not isinstance(raw, Mapping) or set(raw) != _STEP_FIELDS:
            raise LifecycleScenarioError("STEP_RECEIPT_FIELDS_INVALID")
        if (
            raw.get("step_id") != expected.step_id
            or raw.get("status") != "COMPLETED"
            or not _is_exact_int(raw.get("attempts"), 1)
            or not _is_sha256(raw.get("receipt_sha256"))
        ):
            raise LifecycleScenarioError("STEP_RECEIPT_INVALID")
        safe.append(dict(raw))
    return safe


def _validate_vllm(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _VLLM_FIELDS:
        raise LifecycleScenarioError("VLLM_RECEIPT_FIELDS_INVALID")
    before = raw.get("identity_before_sha256")
    after = raw.get("identity_after_sha256")
    if (
        not _is_sha256(before)
        or after != before
        or not _is_exact_int(raw.get("lifecycle_attempts"), 0)
        or raw.get("preserved") is not True
    ):
        raise LifecycleScenarioError("VLLM_PRESERVATION_INVALID")
    return dict(raw)


def _validate_cleanup(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _CLEANUP_FIELDS:
        raise LifecycleScenarioError("CLEANUP_RECEIPT_FIELDS_INVALID")
    if (
        raw.get("status") != "PASS"
        or not _is_exact_int(raw.get("attempts"), 1)
        or raw.get("run_owned_resources_absent") is not True
        or not _is_sha256(raw.get("receipt_sha256"))
    ):
        raise LifecycleScenarioError("CLEANUP_INCOMPLETE")
    return dict(raw)


def _validate_broker_identity(raw: Mapping[str, object]) -> dict[str, object]:
    if set(raw) != _BROKER_IDENTITY_FIELDS:
        raise LifecycleScenarioError("BROKER_IDENTITY_FIELDS_INVALID")
    for name in _BROKER_IDENTITY_FIELDS - {
        "old_broker_stopped",
        "old_worker_bind_unavailable_after_stop",
        "old_worker_followed_replacement",
        "worker_recreated_and_remounted",
        "mcp_catalog_readiness_restored",
    }:
        if not _is_sha256(raw.get(name)):
            raise LifecycleScenarioError("BROKER_IDENTITY_HASH_INVALID")
    old_socket = raw["old_socket_identity_sha256"]
    replacement_socket = raw["replacement_socket_identity_sha256"]
    if (
        raw["old_worker_bind_identity_sha256"] != old_socket
        or raw["recreated_worker_bind_identity_sha256"] != replacement_socket
        or old_socket == replacement_socket
        or raw["old_policy_sha256"] != raw["replacement_policy_sha256"]
        or raw["old_broker_process_sha256"] == raw["replacement_broker_process_sha256"]
        or raw["old_broker_stopped"] is not True
        or raw["old_worker_bind_unavailable_after_stop"] is not True
        or raw["old_worker_followed_replacement"] is not False
        or raw["worker_recreated_and_remounted"] is not True
        or raw["mcp_catalog_readiness_restored"] is not True
    ):
        raise LifecycleScenarioError("BROKER_RECREATE_INVARIANT_FAILED")
    return dict(raw)


def _validate_adapter_identity(raw: Mapping[str, object]) -> dict[str, object]:
    if set(raw) != _ADAPTER_IDENTITY_FIELDS:
        raise LifecycleScenarioError("ADAPTER_IDENTITY_FIELDS_INVALID")
    for name in _ADAPTER_IDENTITY_FIELDS - {
        "replacement_initial_registry_entry_count",
        "old_host_stopped",
        "replacement_health_ready",
        "openworker_reconnected",
        "warm_task_relation",
        "warm_prepare_status",
        "warm_route",
        "continuation_task_relation",
        "continuation_prepare_status",
        "continuation_route",
        "old_cache_slot_reused",
    }:
        if not _is_sha256(raw.get(name)):
            raise LifecycleScenarioError("ADAPTER_IDENTITY_HASH_INVALID")
    if (
        not _is_exact_int(raw["replacement_initial_registry_entry_count"], 0)
        or raw["warm_openworker_process_sha256"]
        != raw["continuation_openworker_process_sha256"]
        or raw["old_host_endpoint_sha256"] != raw["replacement_host_endpoint_sha256"]
        or raw["warm_task_session_sha256"] != raw["continuation_task_session_sha256"]
        or raw["warm_task_id_sha256"] != raw["continuation_task_id_sha256"]
        or raw["old_host_process_sha256"] == raw["replacement_host_process_sha256"]
        or raw["old_generation_sha256"] == raw["replacement_generation_sha256"]
        or raw["old_slot_sha256"] == raw["replacement_slot_sha256"]
        or raw["old_host_stopped"] is not True
        or raw["replacement_health_ready"] is not True
        or raw["openworker_reconnected"] is not True
        or raw["warm_task_relation"] != "TASK_START"
        or raw["warm_prepare_status"] != "READY"
        or raw["warm_route"] != "EXACT"
        or raw["continuation_task_relation"] != "TASK_START"
        or raw["continuation_prepare_status"] != "READY"
        or raw["continuation_route"] != "EXACT"
        or raw["old_cache_slot_reused"] is not False
    ):
        raise LifecycleScenarioError("ADAPTER_RESTART_INVARIANT_FAILED")
    return dict(raw)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _is_exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected
