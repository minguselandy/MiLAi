from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from scripts import dg13u_u1_aggregate as aggregate
from scripts import dg13u_u1_fault_scenarios as faults
from scripts import dg13u_u1_openworker as runner
from scripts.dg13u_u1_mcp_fault import McpFaultEndpoint
from scripts.dg13u_u1_provider_fault import ProviderFaultInjector
from scripts.dg13u_u1_runtime_fault import (
    RuntimeFaultInjector,
    closed_loopback_endpoint_identity,
)

EXPECTED_CASE_IDS = {
    "U1-RUNTIME-UNAVAILABLE",
    "U1-RUNTIME-DOWN",
    "U1-RUNTIME-MALFORMED",
    "U1-RUNTIME-TIMEOUT",
    "U1-MCP-CHILD-DOWN",
    "U1-MCP-CHILD-MALFORMED",
    "U1-MCP-CHILD-TIMEOUT",
    "U1-BROKER-DOWN",
    "U1-BROKER-MALFORMED",
    "U1-BROKER-TIMEOUT",
    "U1-PROVIDER-DOWN",
    "U1-PROVIDER-MALFORMED",
    "U1-PROVIDER-TIMEOUT",
}


def test_exact_fault_case_set_matches_current_runner_cases() -> None:
    runner_faults = {
        case_id
        for case_id in runner.CASES
        if case_id.startswith(
            ("U1-RUNTIME-", "U1-MCP-CHILD-", "U1-BROKER-", "U1-PROVIDER-")
        )
        and case_id != "U1-BROKER-INODE-RECREATE"
    }

    assert runner_faults == EXPECTED_CASE_IDS
    assert set(faults.FAULT_SCENARIOS) == EXPECTED_CASE_IDS
    assert len(faults.FAULT_SCENARIOS) == 13


@pytest.mark.parametrize("case_id", sorted(EXPECTED_CASE_IDS))
def test_scenario_is_immutable_strict_and_matches_call_contract(case_id: str) -> None:
    scenario = faults.fault_scenario_for_case(case_id)
    runner_case = runner.CASES[case_id]
    aggregate_case = aggregate.CASE_CONTRACTS[case_id]

    assert scenario.case_id == case_id
    assert scenario.expected_mcp_calls == runner_case.expected_mcp_calls
    assert scenario.expected_provider_calls == runner_case.expected_provider_calls
    assert scenario.expected_mcp_calls == aggregate_case.expected_mcp_calls
    assert scenario.expected_provider_calls == aggregate_case.expected_provider_calls
    assert scenario.automatic_retries == 0
    assert scenario.max_fault_attempts == 1
    assert scenario.injector_contract_identity.startswith("milai.dg13u.u1.fault/")
    assert scenario.expected_terminal.reason_code
    assert scenario.expected_provider_barrier in {"BLOCKED", "ALLOWED_ONCE"}
    assert set(dataclasses.asdict(scenario)) == {
        "case_id",
        "fault_phase",
        "endpoint_strategy",
        "expected_terminal",
        "expected_provider_barrier",
        "expected_mcp_calls",
        "expected_provider_calls",
        "automatic_retries",
        "max_fault_attempts",
        "injector_contract_identity",
        "implementation_binding",
        "wireability",
        "missing_injection_point",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        scenario.case_id = "U1-NONE-EN"  # type: ignore[misc]


def test_all_contract_identities_are_unique() -> None:
    identities = [
        scenario.injector_contract_identity
        for scenario in faults.FAULT_SCENARIOS.values()
    ]
    assert len(identities) == len(set(identities))


def test_direct_plans_bind_existing_helpers_instead_of_copying_them() -> None:
    assert McpFaultEndpoint.__module__ == "scripts.dg13u_u1_mcp_fault"
    assert ProviderFaultInjector.__module__ == "scripts.dg13u_u1_provider_fault"
    assert RuntimeFaultInjector.__module__ == "scripts.dg13u_u1_runtime_fault"
    assert (
        closed_loopback_endpoint_identity.__module__ == "scripts.dg13u_u1_runtime_fault"
    )
    assert runner.FreshRuntimeLifecycle.__module__ == "scripts.dg13u_u1_openworker"
    assert (
        faults.FAULT_SCENARIOS["U1-BROKER-MALFORMED"].implementation_binding
        == "scripts.dg13u_u1_mcp_fault:McpFaultEndpoint"
    )
    assert (
        faults.FAULT_SCENARIOS["U1-PROVIDER-TIMEOUT"].implementation_binding
        == "scripts.dg13u_u1_provider_fault:ProviderFaultInjector"
    )
    assert (
        faults.FAULT_SCENARIOS["U1-RUNTIME-UNAVAILABLE"].implementation_binding
        == "scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=UNAVAILABLE)"
    )
    assert (
        faults.FAULT_SCENARIOS["U1-RUNTIME-DOWN"].implementation_binding
        == "scripts.dg13u_u1_runtime_fault:closed_loopback_endpoint_identity"
    )
    assert (
        faults.FAULT_SCENARIOS["U1-RUNTIME-MALFORMED"].implementation_binding
        == "scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=MALFORMED)"
    )
    assert (
        faults.FAULT_SCENARIOS["U1-RUNTIME-TIMEOUT"].implementation_binding
        == "scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=TIMEOUT)"
    )


@pytest.mark.parametrize(
    ("case_id", "reason_code"),
    [
        ("U1-RUNTIME-UNAVAILABLE", "CANONICAL_UNAVAILABLE"),
        ("U1-RUNTIME-DOWN", "MCP_TOOL_ERROR"),
        ("U1-RUNTIME-MALFORMED", "MCP_TOOL_ERROR"),
        ("U1-RUNTIME-TIMEOUT", "MCP_TOOL_ERROR"),
        ("U1-MCP-CHILD-DOWN", "MCP_SESSION_CLOSED"),
        ("U1-MCP-CHILD-MALFORMED", "MCP_RESPONSE_JSON_REJECTED"),
        ("U1-MCP-CHILD-TIMEOUT", "MCP_DEADLINE_EXCEEDED"),
        ("U1-BROKER-DOWN", "MCP_SOCKET_UNAVAILABLE"),
        ("U1-BROKER-MALFORMED", "MCP_RESPONSE_JSON_REJECTED"),
        ("U1-BROKER-TIMEOUT", "MCP_DEADLINE_EXCEEDED"),
        ("U1-PROVIDER-DOWN", "PROVIDER_UNAVAILABLE"),
        ("U1-PROVIDER-MALFORMED", "PROVIDER_STREAM_FAILED"),
        ("U1-PROVIDER-TIMEOUT", "PROVIDER_UNAVAILABLE"),
    ],
)
def test_exact_terminal_reason_and_access_barrier(
    case_id: str, reason_code: str
) -> None:
    scenario = faults.fault_scenario_for_case(case_id)

    assert scenario.expected_terminal.reason_code == reason_code
    if case_id.startswith("U1-PROVIDER-"):
        assert scenario.expected_terminal.access_status == "NO_MEMORY_NEEDED"
        assert scenario.expected_terminal.execution_action == "CONTINUE"
        assert scenario.expected_terminal.provider_execution == "ALLOWED"
        assert scenario.expected_terminal.terminal_stage == "NONE"
        assert scenario.expected_terminal.http_status == 502
        assert scenario.expected_provider_barrier == "ALLOWED_ONCE"
    else:
        assert (
            scenario.expected_terminal.access_status
            == "MEMORY_REQUIRED_BUT_UNAVAILABLE"
        )
        assert scenario.expected_terminal.execution_action == "RETRY"
        assert scenario.expected_terminal.provider_execution == "PROHIBITED"
        assert scenario.expected_terminal.terminal_stage == "TRANSPORT"
        assert scenario.expected_terminal.http_status == 200
        assert scenario.expected_provider_barrier == "BLOCKED"


def test_wireability_does_not_claim_missing_injection_points_are_direct() -> None:
    direct = {
        case_id
        for case_id, scenario in faults.FAULT_SCENARIOS.items()
        if scenario.wireability == "DIRECT"
    }
    missing = {
        case_id
        for case_id, scenario in faults.FAULT_SCENARIOS.items()
        if scenario.wireability == "MISSING_INJECTION_POINT"
    }

    assert direct == {
        "U1-RUNTIME-UNAVAILABLE",
        "U1-RUNTIME-DOWN",
        "U1-RUNTIME-MALFORMED",
        "U1-RUNTIME-TIMEOUT",
        "U1-MCP-CHILD-DOWN",
        "U1-MCP-CHILD-MALFORMED",
        "U1-MCP-CHILD-TIMEOUT",
        "U1-BROKER-DOWN",
        "U1-BROKER-MALFORMED",
        "U1-BROKER-TIMEOUT",
        "U1-PROVIDER-DOWN",
        "U1-PROVIDER-MALFORMED",
        "U1-PROVIDER-TIMEOUT",
    }
    assert missing == EXPECTED_CASE_IDS - direct
    assert all(
        faults.FAULT_SCENARIOS[case_id].missing_injection_point for case_id in missing
    )
    assert all(
        faults.FAULT_SCENARIOS[case_id].missing_injection_point is None
        for case_id in direct
    )


def test_serialized_plans_contain_no_pass_secret_or_native_identity() -> None:
    encoded = json.dumps(
        {
            case_id: dataclasses.asdict(scenario)
            for case_id, scenario in faults.FAULT_SCENARIOS.items()
        },
        sort_keys=True,
    )
    assert "PASS" not in encoded
    assert "Bearer" not in encoded
    assert "token" not in encoded.lower()
    assert "native_request_id" not in encoded
    assert "claim_id" not in encoded
    assert "evidence_id" not in encoded


@pytest.mark.parametrize(
    ("case_id", "mode", "delay"),
    [
        ("U1-BROKER-DOWN", None, None),
        ("U1-BROKER-MALFORMED", "MALFORMED", None),
        ("U1-BROKER-TIMEOUT", "TIMEOUT", "5.0"),
    ],
)
def test_broker_launch_plan_is_bounded_and_reuses_mcp_fault_helper(
    tmp_path: Path,
    case_id: str,
    mode: str | None,
    delay: str | None,
) -> None:
    root = tmp_path / "run-owned"
    root.mkdir(mode=0o700)
    launch = faults.build_broker_fault_launch(
        case_id,
        run_owned_root=root,
        python_executable=Path(os.sys.executable),
    )

    assert launch.case_id == case_id
    assert launch.socket_path == root / "uds/reader-lite.sock"
    assert launch.max_connections == 1
    assert launch.automatic_retries == 0
    if mode is None:
        assert launch.action == "ENSURE_ENDPOINT_ABSENT"
        assert launch.command == ()
        assert launch.ledger_path is None
        assert launch.ready_path is None
    else:
        assert launch.action == "START_MCP_FAULT_ENDPOINT"
        assert "scripts/dg13u_u1_mcp_fault.py" in " ".join(launch.command)
        assert launch.command[launch.command.index("--mode") + 1] == mode
        assert launch.command[launch.command.index("--socket") + 1] == str(
            launch.socket_path
        )
        assert launch.command[launch.command.index("--max-frame-bytes") + 1] == "65536"
        if delay is not None:
            assert (
                launch.command[launch.command.index("--timeout-delay-seconds") + 1]
                == delay
            )


def test_broker_launch_rejects_wrong_case_unsafe_root_and_executable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run-owned"
    root.mkdir(mode=0o700)
    executable = Path(os.sys.executable)
    with pytest.raises(faults.FaultScenarioError, match="NOT_A_BROKER_FAULT"):
        faults.build_broker_fault_launch(
            "U1-PROVIDER-DOWN",
            run_owned_root=root,
            python_executable=executable,
        )
    with pytest.raises(faults.FaultScenarioError, match="RUN_ROOT_MUST_BE_ABSOLUTE"):
        faults.build_broker_fault_launch(
            "U1-BROKER-DOWN",
            run_owned_root=Path("relative"),
            python_executable=executable,
        )
    with pytest.raises(faults.FaultScenarioError, match="RUN_ROOT_UNSAFE"):
        faults.build_broker_fault_launch(
            "U1-BROKER-DOWN",
            run_owned_root=Path("/"),
            python_executable=executable,
        )
    with pytest.raises(faults.FaultScenarioError, match="PYTHON_EXECUTABLE_INVALID"):
        faults.build_broker_fault_launch(
            "U1-BROKER-DOWN",
            run_owned_root=root,
            python_executable=root / "missing-python",
        )


def test_broker_launch_rejects_symlink_and_group_writable_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    executable = Path(os.sys.executable)
    with pytest.raises(faults.FaultScenarioError, match="RUN_ROOT_UNSAFE"):
        faults.build_broker_fault_launch(
            "U1-BROKER-MALFORMED",
            run_owned_root=linked,
            python_executable=executable,
        )

    real.chmod(0o770)
    with pytest.raises(faults.FaultScenarioError, match="RUN_ROOT_MODE_UNSAFE"):
        faults.build_broker_fault_launch(
            "U1-BROKER-TIMEOUT",
            run_owned_root=real,
            python_executable=executable,
        )


def test_unknown_case_is_rejected() -> None:
    with pytest.raises(faults.FaultScenarioError, match="UNSUPPORTED_FAULT_CASE"):
        faults.fault_scenario_for_case("U1-NONE-EN")
