from __future__ import annotations

import copy
import dataclasses
import hashlib
import json

import pytest

from scripts import dg13u_u1_lifecycle_scenarios as lifecycle


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _steps(case_id: str) -> list[dict[str, object]]:
    return [
        {
            "step_id": step.step_id,
            "status": "COMPLETED",
            "attempts": 1,
            "receipt_sha256": _hash(f"receipt:{case_id}:{step.step_id}"),
        }
        for step in lifecycle.scenario_for_case(case_id).steps
    ]


def _broker_identity() -> dict[str, object]:
    return {
        "old_policy_sha256": _hash("policy:same"),
        "replacement_policy_sha256": _hash("policy:same"),
        "old_broker_process_sha256": _hash("broker:old"),
        "replacement_broker_process_sha256": _hash("broker:new"),
        "old_socket_identity_sha256": _hash("socket:old"),
        "old_worker_bind_identity_sha256": _hash("socket:old"),
        "replacement_socket_identity_sha256": _hash("socket:new"),
        "recreated_worker_bind_identity_sha256": _hash("socket:new"),
        "old_broker_stopped": True,
        "old_worker_bind_unavailable_after_stop": True,
        "old_worker_followed_replacement": False,
        "worker_recreated_and_remounted": True,
        "mcp_catalog_readiness_restored": True,
    }


def _adapter_identity() -> dict[str, object]:
    return {
        "warm_openworker_process_sha256": _hash("openworker:a"),
        "continuation_openworker_process_sha256": _hash("openworker:a"),
        "old_host_endpoint_sha256": _hash("host:endpoint"),
        "replacement_host_endpoint_sha256": _hash("host:endpoint"),
        "old_host_process_sha256": _hash("host:old"),
        "replacement_host_process_sha256": _hash("host:new"),
        "old_generation_sha256": _hash("generation:old"),
        "replacement_generation_sha256": _hash("generation:new"),
        "old_slot_sha256": _hash("slot:old"),
        "replacement_slot_sha256": _hash("slot:new"),
        "warm_task_session_sha256": _hash("session:a"),
        "continuation_task_session_sha256": _hash("session:a"),
        "warm_task_id_sha256": _hash("task:a"),
        "continuation_task_id_sha256": _hash("task:a"),
        "warm_context_sha256": _hash("context:warm"),
        "continuation_context_sha256": _hash("context:continuation"),
        "replacement_initial_registry_entry_count": 0,
        "old_host_stopped": True,
        "replacement_health_ready": True,
        "openworker_reconnected": True,
        "warm_task_relation": "TASK_START",
        "warm_prepare_status": "READY",
        "warm_route": "EXACT",
        "continuation_task_relation": "TASK_START",
        "continuation_prepare_status": "READY",
        "continuation_route": "EXACT",
        "old_cache_slot_reused": False,
    }


def _measurement(case_id: str) -> dict[str, object]:
    scenario = lifecycle.scenario_for_case(case_id)
    return {
        "schema": lifecycle.MEASUREMENT_SCHEMA,
        "case_id": case_id,
        "execution_class": scenario.execution_class,
        "steps": _steps(case_id),
        "mcp_calls": scenario.expected_mcp_calls,
        "provider_calls": scenario.expected_provider_calls,
        "automatic_retries": 0,
        "readiness_calls": {
            "host_health": scenario.expected_host_health_calls,
            "mcp_catalog": scenario.expected_mcp_catalog_calls,
        },
        "vllm": {
            "identity_before_sha256": _hash("external-vllm"),
            "identity_after_sha256": _hash("external-vllm"),
            "lifecycle_attempts": 0,
            "preserved": True,
        },
        "cleanup": {
            "status": "PASS",
            "attempts": 1,
            "run_owned_resources_absent": True,
            "receipt_sha256": _hash(f"cleanup:{case_id}"),
        },
        "identity": (
            _broker_identity()
            if case_id == "U1-BROKER-INODE-RECREATE"
            else _adapter_identity()
        ),
    }


def _assert_error(case_id: str, measurement: dict[str, object], expected: str) -> None:
    with pytest.raises(lifecycle.LifecycleScenarioError, match=f"^{expected}$"):
        lifecycle.reduce_lifecycle_measurement(case_id, measurement)


def test_exact_lifecycle_cases_execution_classes_and_call_contracts_are_frozen() -> None:
    assert set(lifecycle.LIFECYCLE_SCENARIOS) == {
        "U1-BROKER-INODE-RECREATE",
        "U1-ADAPTER-RESTART",
    }
    broker = lifecycle.scenario_for_case("U1-BROKER-INODE-RECREATE")
    assert broker.execution_class == "BROKER_WORKER_BIND_RECREATE"
    assert (
        broker.expected_mcp_calls,
        broker.expected_provider_calls,
        broker.expected_host_health_calls,
        broker.expected_mcp_catalog_calls,
    ) == (0, 0, 0, 1)
    adapter = lifecycle.scenario_for_case("U1-ADAPTER-RESTART")
    assert adapter.execution_class == "OPENWORKER_HOST_GENERATION_RESTART"
    assert (
        adapter.expected_mcp_calls,
        adapter.expected_provider_calls,
        adapter.expected_host_health_calls,
        adapter.expected_mcp_catalog_calls,
    ) == (2, 2, 1, 0)
    for scenario in lifecycle.LIFECYCLE_SCENARIOS.values():
        assert scenario.automatic_retries == 0
        assert scenario.maximum_attempts_per_step == 1
        assert scenario.vllm_policy == "EXTERNAL_PRESERVE_ZERO_LIFECYCLE"
        with pytest.raises(dataclasses.FrozenInstanceError):
            scenario.case_id = "U1-NONE-EN"  # type: ignore[misc]


def test_broker_step_order_is_real_inode_recreate_then_catalog_readiness() -> None:
    scenario = lifecycle.scenario_for_case("U1-BROKER-INODE-RECREATE")
    assert [step.step_id for step in scenario.steps] == [
        "CAPTURE_OLD_SOCKET_AND_WORKER_BIND",
        "STOP_OLD_RUN_OWNED_BROKER",
        "CONFIRM_OLD_WORKER_BIND_UNAVAILABLE",
        "START_REPLACEMENT_BROKER_SAME_POLICY",
        "VERIFY_NEW_INODE_AND_NO_SILENT_FOLLOW",
        "RECREATE_WORKER_WITH_NEW_BIND",
        "VERIFY_RECREATED_WORKER_READINESS",
        "CLEANUP_RUN_OWNED_REPLACEMENTS",
    ]
    assert scenario.steps[6].action == (
        "MCP_LIST_CATALOG_READINESS_WITHOUT_PREPARE_OR_PROVIDER_CALL"
    )


def test_adapter_step_order_warms_restarts_reconnects_and_continues() -> None:
    scenario = lifecycle.scenario_for_case("U1-ADAPTER-RESTART")
    assert [step.step_id for step in scenario.steps] == [
        "WARM_OPENWORKER_A_EXACT_TURN",
        "CAPTURE_WARM_BINDING_AND_OLD_HOST_GENERATION",
        "STOP_OLD_RUN_OWNED_HOST",
        "START_REPLACEMENT_HOST_NEW_GENERATION",
        "VERIFY_OPENWORKER_RECONNECT_AND_HOST_HEALTH",
        "CONTINUE_OPENWORKER_A_THROUGH_REPLACEMENT_HOST",
        "VERIFY_RESTART_TASK_START_READY_EXACT",
        "CLEANUP_RUN_OWNED_REPLACEMENT_HOST",
    ]
    assert scenario.steps[0].ownership == "RUN_OWNED"
    assert scenario.steps[5].ownership == "RUN_OWNED"


def test_identity_helpers_return_only_hashes_and_reject_invalid_input() -> None:
    socket_hash = lifecycle.socket_identity_sha256(12345, 987654)
    process_hash = lifecycle.process_identity_sha256(
        23456, "private command marker", "private generation"
    )

    assert len(socket_hash) == len(process_hash) == 64
    assert "12345" not in socket_hash
    assert "private" not in process_hash
    with pytest.raises(lifecycle.LifecycleScenarioError, match="SOCKET_IDENTITY_INVALID"):
        lifecycle.socket_identity_sha256(True, 1)
    with pytest.raises(lifecycle.LifecycleScenarioError, match="PROCESS_IDENTITY_INVALID"):
        lifecycle.process_identity_sha256(1, "", "generation")


@pytest.mark.parametrize(
    "case_id", ["U1-BROKER-INODE-RECREATE", "U1-ADAPTER-RESTART"]
)
def test_valid_measurement_reduces_to_hash_only_pass_without_mutation(
    case_id: str,
) -> None:
    measurement = _measurement(case_id)
    original = copy.deepcopy(measurement)
    scenario = lifecycle.scenario_for_case(case_id)

    evidence = lifecycle.reduce_lifecycle_measurement(case_id, measurement)

    assert evidence["schema"] == lifecycle.EVIDENCE_SCHEMA
    assert evidence["status"] == "PASS"
    assert evidence["execution_class"] == scenario.execution_class
    assert evidence["observed_mcp_calls"] == scenario.expected_mcp_calls
    assert evidence["observed_provider_calls"] == scenario.expected_provider_calls
    assert evidence["automatic_retries"] == 0
    assert measurement == original
    encoded = json.dumps(evidence, sort_keys=True)
    for forbidden in (
        "private command marker",
        "private generation",
        '"pid"',
        '"inode"',
        '"device"',
        '"session_id"',
        '"task_id"',
        '"context"',
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("replacement_socket_identity_sha256", _hash("socket:old")),
        ("replacement_broker_process_sha256", _hash("broker:old")),
        ("replacement_policy_sha256", _hash("policy:different")),
        ("old_worker_bind_unavailable_after_stop", False),
        ("old_worker_followed_replacement", True),
        ("worker_recreated_and_remounted", False),
        ("mcp_catalog_readiness_restored", False),
    ],
)
def test_broker_recreate_negative_twins_fail(field: str, replacement: object) -> None:
    measurement = _measurement("U1-BROKER-INODE-RECREATE")
    identity = measurement["identity"]
    assert isinstance(identity, dict)
    identity[field] = replacement
    _assert_error(
        "U1-BROKER-INODE-RECREATE",
        measurement,
        "BROKER_RECREATE_INVARIANT_FAILED",
    )


def test_broker_worker_must_be_explicitly_remounted_to_new_inode() -> None:
    measurement = _measurement("U1-BROKER-INODE-RECREATE")
    identity = measurement["identity"]
    assert isinstance(identity, dict)
    identity["recreated_worker_bind_identity_sha256"] = identity[
        "old_socket_identity_sha256"
    ]
    _assert_error(
        "U1-BROKER-INODE-RECREATE",
        measurement,
        "BROKER_RECREATE_INVARIANT_FAILED",
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("continuation_openworker_process_sha256", _hash("openworker:b")),
        ("replacement_host_endpoint_sha256", _hash("host:other-endpoint")),
        ("replacement_host_process_sha256", _hash("host:old")),
        ("replacement_generation_sha256", _hash("generation:old")),
        ("replacement_slot_sha256", _hash("slot:old")),
        ("continuation_task_session_sha256", _hash("session:b")),
        ("continuation_task_id_sha256", _hash("task:b")),
        ("replacement_initial_registry_entry_count", 1),
        ("old_host_stopped", False),
        ("replacement_health_ready", False),
        ("openworker_reconnected", False),
        ("continuation_task_relation", "CONTINUE"),
        ("continuation_prepare_status", "CACHE"),
        ("continuation_route", "CACHE"),
        ("old_cache_slot_reused", True),
    ],
)
def test_adapter_restart_negative_twins_fail(field: str, replacement: object) -> None:
    measurement = _measurement("U1-ADAPTER-RESTART")
    identity = measurement["identity"]
    assert isinstance(identity, dict)
    identity[field] = replacement
    _assert_error(
        "U1-ADAPTER-RESTART",
        measurement,
        "ADAPTER_RESTART_INVARIANT_FAILED",
    )


@pytest.mark.parametrize(
    ("case_id", "field", "replacement"),
    [
        ("U1-BROKER-INODE-RECREATE", "mcp_catalog", 0),
        ("U1-BROKER-INODE-RECREATE", "mcp_catalog", 2),
        ("U1-ADAPTER-RESTART", "host_health", 0),
        ("U1-ADAPTER-RESTART", "host_health", 2),
    ],
)
def test_readiness_calls_are_separate_and_exact(
    case_id: str, field: str, replacement: int
) -> None:
    measurement = _measurement(case_id)
    readiness = measurement["readiness_calls"]
    assert isinstance(readiness, dict)
    readiness[field] = replacement
    _assert_error(case_id, measurement, "READINESS_CALL_ACCOUNTING_INVALID")


def test_broker_catalog_readiness_does_not_increment_prepare_context_calls() -> None:
    measurement = _measurement("U1-BROKER-INODE-RECREATE")
    evidence = lifecycle.reduce_lifecycle_measurement(
        "U1-BROKER-INODE-RECREATE", measurement
    )

    assert evidence["observed_mcp_calls"] == 0
    assert evidence["observed_provider_calls"] == 0
    assert evidence["readiness_calls"] == {"host_health": 0, "mcp_catalog": 1}


@pytest.mark.parametrize(
    ("case_id", "field", "replacement"),
    [
        ("U1-BROKER-INODE-RECREATE", "mcp_calls", 1),
        ("U1-BROKER-INODE-RECREATE", "provider_calls", 1),
        ("U1-ADAPTER-RESTART", "mcp_calls", 0),
        ("U1-ADAPTER-RESTART", "mcp_calls", 3),
        ("U1-ADAPTER-RESTART", "provider_calls", 1),
        ("U1-ADAPTER-RESTART", "automatic_retries", 1),
    ],
)
def test_prepare_provider_and_retry_accounting_negative_twins(
    case_id: str, field: str, replacement: int
) -> None:
    measurement = _measurement(case_id)
    measurement[field] = replacement
    _assert_error(case_id, measurement, "CALL_ACCOUNTING_INVALID")


def test_wrong_execution_class_fails_before_receipt_reduction() -> None:
    measurement = _measurement("U1-ADAPTER-RESTART")
    measurement["execution_class"] = "BROKER_WORKER_BIND_RECREATE"
    _assert_error(
        "U1-ADAPTER-RESTART", measurement, "MEASUREMENT_IDENTITY_INVALID"
    )


@pytest.mark.parametrize("replacement", [2, True])
def test_extra_or_non_integer_step_attempt_fails(replacement: object) -> None:
    measurement = _measurement("U1-ADAPTER-RESTART")
    steps = measurement["steps"]
    assert isinstance(steps, list)
    steps[0]["attempts"] = replacement
    _assert_error("U1-ADAPTER-RESTART", measurement, "STEP_RECEIPT_INVALID")


def test_cleanup_and_vllm_fail_closed() -> None:
    incomplete = _measurement("U1-ADAPTER-RESTART")
    cleanup = incomplete["cleanup"]
    assert isinstance(cleanup, dict)
    cleanup["run_owned_resources_absent"] = False
    _assert_error("U1-ADAPTER-RESTART", incomplete, "CLEANUP_INCOMPLETE")

    mutated = _measurement("U1-BROKER-INODE-RECREATE")
    vllm = mutated["vllm"]
    assert isinstance(vllm, dict)
    vllm["identity_after_sha256"] = _hash("different-vllm")
    _assert_error(
        "U1-BROKER-INODE-RECREATE", mutated, "VLLM_PRESERVATION_INVALID"
    )


def test_missing_reordered_or_extra_step_fails_closed() -> None:
    missing = _measurement("U1-BROKER-INODE-RECREATE")
    steps = missing["steps"]
    assert isinstance(steps, list)
    steps.pop()
    _assert_error(
        "U1-BROKER-INODE-RECREATE", missing, "STEP_RECEIPT_COUNT_INVALID"
    )

    reordered = _measurement("U1-ADAPTER-RESTART")
    steps = reordered["steps"]
    assert isinstance(steps, list)
    steps[0], steps[1] = steps[1], steps[0]
    _assert_error("U1-ADAPTER-RESTART", reordered, "STEP_RECEIPT_INVALID")


@pytest.mark.parametrize(
    "case_id", ["U1-BROKER-INODE-RECREATE", "U1-ADAPTER-RESTART"]
)
def test_raw_identity_field_is_rejected(case_id: str) -> None:
    measurement = _measurement(case_id)
    identity = measurement["identity"]
    assert isinstance(identity, dict)
    identity["raw_pid"] = 12345
    expected = (
        "BROKER_IDENTITY_FIELDS_INVALID"
        if case_id == "U1-BROKER-INODE-RECREATE"
        else "ADAPTER_IDENTITY_FIELDS_INVALID"
    )
    _assert_error(case_id, measurement, expected)


def test_unknown_case_and_non_mapping_measurement_are_rejected() -> None:
    with pytest.raises(lifecycle.LifecycleScenarioError, match="^UNSUPPORTED_CASE$"):
        lifecycle.scenario_for_case("U1-NONE-EN")
    with pytest.raises(
        lifecycle.LifecycleScenarioError, match="^MEASUREMENT_FIELDS_INVALID$"
    ):
        lifecycle.reduce_lifecycle_measurement(  # type: ignore[arg-type]
            "U1-ADAPTER-RESTART", []
        )
