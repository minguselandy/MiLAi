"""Immutable DG-13U U1 fault plans; this module executes no case or fault."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

AccessStatus = Literal["MEMORY_REQUIRED_BUT_UNAVAILABLE", "NO_MEMORY_NEEDED"]
ExecutionAction = Literal["RETRY", "CONTINUE"]
ProviderExecution = Literal["PROHIBITED", "ALLOWED"]
TerminalStage = Literal["TRANSPORT", "NONE"]
ProviderBarrier = Literal["BLOCKED", "ALLOWED_ONCE"]
Wireability = Literal["DIRECT", "MISSING_INJECTION_POINT"]
BrokerFaultAction = Literal["ENSURE_ENDPOINT_ABSENT", "START_MCP_FAULT_ENDPOINT"]

_MCP_FAULT_SCRIPT = Path(__file__).with_name("dg13u_u1_mcp_fault.py").resolve()


class FaultScenarioError(ValueError):
    """A fault selector or bounded launch request violates the frozen plan."""


@dataclass(frozen=True, slots=True)
class TerminalExpectation:
    """Typed AccessOutcome plus the externally observed Host terminal reason."""

    access_status: AccessStatus
    execution_action: ExecutionAction
    provider_execution: ProviderExecution
    terminal_stage: TerminalStage
    reason_code: str
    http_status: int


@dataclass(frozen=True, slots=True)
class FaultScenario:
    """A plan and expectation, never evidence that the case was executed."""

    case_id: str
    fault_phase: str
    endpoint_strategy: str
    expected_terminal: TerminalExpectation
    expected_provider_barrier: ProviderBarrier
    expected_mcp_calls: int
    expected_provider_calls: int
    automatic_retries: Literal[0]
    max_fault_attempts: Literal[1]
    injector_contract_identity: str
    implementation_binding: str
    wireability: Wireability
    missing_injection_point: str | None


@dataclass(frozen=True, slots=True)
class BrokerFaultLaunch:
    """A shell-free, run-owned broker endpoint action for a runner to execute."""

    case_id: str
    action: BrokerFaultAction
    socket_path: Path
    ledger_path: Path | None
    ready_path: Path | None
    command: tuple[str, ...]
    max_connections: Literal[1]
    automatic_retries: Literal[0]


def _memory_terminal(reason_code: str) -> TerminalExpectation:
    return TerminalExpectation(
        access_status="MEMORY_REQUIRED_BUT_UNAVAILABLE",
        execution_action="RETRY",
        provider_execution="PROHIBITED",
        terminal_stage="TRANSPORT",
        reason_code=reason_code,
        http_status=200,
    )


def _provider_terminal(reason_code: str) -> TerminalExpectation:
    return TerminalExpectation(
        access_status="NO_MEMORY_NEEDED",
        execution_action="CONTINUE",
        provider_execution="ALLOWED",
        terminal_stage="NONE",
        reason_code=reason_code,
        http_status=502,
    )


def _fault(
    case_id: str,
    *,
    phase: str,
    strategy: str,
    reason: str,
    mcp_calls: int,
    provider_calls: int,
    identity: str,
    binding: str,
    direct: bool,
    missing: str | None = None,
) -> FaultScenario:
    provider_fault = case_id.startswith("U1-PROVIDER-")
    if direct == (missing is not None):
        raise AssertionError("fault wireability invariant failed")
    return FaultScenario(
        case_id=case_id,
        fault_phase=phase,
        endpoint_strategy=strategy,
        expected_terminal=(
            _provider_terminal(reason) if provider_fault else _memory_terminal(reason)
        ),
        expected_provider_barrier="ALLOWED_ONCE" if provider_fault else "BLOCKED",
        expected_mcp_calls=mcp_calls,
        expected_provider_calls=provider_calls,
        automatic_retries=0,
        max_fault_attempts=1,
        injector_contract_identity=f"milai.dg13u.u1.fault/{identity}",
        implementation_binding=binding,
        wireability="DIRECT" if direct else "MISSING_INJECTION_POINT",
        missing_injection_point=missing,
    )


FAULT_SCENARIOS: Mapping[str, FaultScenario] = MappingProxyType(
    {
        "U1-RUNTIME-UNAVAILABLE": _fault(
            "U1-RUNTIME-UNAVAILABLE",
            phase="RUNTIME_CANONICAL_RESPONSE",
            strategy="CANONICAL_UNAVAILABLE_FIXTURE",
            reason="CANONICAL_UNAVAILABLE",
            mcp_calls=1,
            provider_calls=0,
            identity="runtime-unavailable/canonical-fixture-v1",
            binding="scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=UNAVAILABLE)",
            direct=True,
        ),
        "U1-RUNTIME-DOWN": _fault(
            "U1-RUNTIME-DOWN",
            phase="MCP_CHILD_TO_RUNTIME_HTTP",
            strategy="CLOSED_LOOPBACK_ENDPOINT_ZERO_RETRY",
            reason="MCP_TOOL_ERROR",
            mcp_calls=1,
            provider_calls=0,
            identity="runtime-down/closed-loopback-zero-retry-v1",
            binding="scripts.dg13u_u1_runtime_fault:closed_loopback_endpoint_identity",
            direct=True,
        ),
        "U1-RUNTIME-MALFORMED": _fault(
            "U1-RUNTIME-MALFORMED",
            phase="MCP_CHILD_TO_RUNTIME_HTTP",
            strategy="RUNTIME_HTTP_MALFORMED_RESPONSE",
            reason="MCP_TOOL_ERROR",
            mcp_calls=1,
            provider_calls=0,
            identity="runtime-malformed/http-fixture-v1",
            binding="scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=MALFORMED)",
            direct=True,
        ),
        "U1-RUNTIME-TIMEOUT": _fault(
            "U1-RUNTIME-TIMEOUT",
            phase="MCP_CHILD_TO_RUNTIME_HTTP",
            strategy="RUNTIME_HTTP_DELAY_BEYOND_CLIENT_TIMEOUT",
            reason="MCP_TOOL_ERROR",
            mcp_calls=1,
            provider_calls=0,
            identity="runtime-timeout/http-fixture-v1",
            binding="scripts.dg13u_u1_runtime_fault:RuntimeFaultInjector(mode=TIMEOUT)",
            direct=True,
        ),
        "U1-MCP-CHILD-DOWN": _fault(
            "U1-MCP-CHILD-DOWN",
            phase="BROKER_TO_MCP_CHILD_STDIO",
            strategy="DIGEST_BOUND_CHILD_EXIT_BEFORE_RESPONSE",
            reason="MCP_SESSION_CLOSED",
            mcp_calls=1,
            provider_calls=0,
            identity="mcp-child-down/stdio-fixture-v1",
            binding="scripts.dg13u_u1_mcp_child_fault:build_child_fixture(mode=DOWN)",
            direct=True,
        ),
        "U1-MCP-CHILD-MALFORMED": _fault(
            "U1-MCP-CHILD-MALFORMED",
            phase="BROKER_TO_MCP_CHILD_STDIO",
            strategy="DIGEST_BOUND_CHILD_MALFORMED_FRAME",
            reason="MCP_RESPONSE_JSON_REJECTED",
            mcp_calls=1,
            provider_calls=0,
            identity="mcp-child-malformed/stdio-fixture-v1",
            binding="scripts.dg13u_u1_mcp_child_fault:build_child_fixture(mode=MALFORMED)",
            direct=True,
        ),
        "U1-MCP-CHILD-TIMEOUT": _fault(
            "U1-MCP-CHILD-TIMEOUT",
            phase="BROKER_TO_MCP_CHILD_STDIO",
            strategy="DIGEST_BOUND_CHILD_DELAY_BEYOND_SHARED_DEADLINE",
            reason="MCP_DEADLINE_EXCEEDED",
            mcp_calls=1,
            provider_calls=0,
            identity="mcp-child-timeout/stdio-fixture-v1",
            binding="scripts.dg13u_u1_mcp_child_fault:build_child_fixture(mode=TIMEOUT)",
            direct=True,
        ),
        "U1-BROKER-DOWN": _fault(
            "U1-BROKER-DOWN",
            phase="HOST_TO_BROKER_UDS",
            strategy="RUN_OWNED_BROKER_SOCKET_ABSENT",
            reason="MCP_SOCKET_UNAVAILABLE",
            mcp_calls=1,
            provider_calls=0,
            identity="broker-down/absent-uds-v1",
            binding="scripts.dg13u_u1_fault_scenarios:BrokerFaultLaunch",
            direct=True,
        ),
        "U1-BROKER-MALFORMED": _fault(
            "U1-BROKER-MALFORMED",
            phase="HOST_TO_BROKER_UDS",
            strategy="MCP_FAULT_ENDPOINT_MALFORMED",
            reason="MCP_RESPONSE_JSON_REJECTED",
            mcp_calls=1,
            provider_calls=0,
            identity="broker-malformed/mcp-fault-malformed-v1",
            binding="scripts.dg13u_u1_mcp_fault:McpFaultEndpoint",
            direct=True,
        ),
        "U1-BROKER-TIMEOUT": _fault(
            "U1-BROKER-TIMEOUT",
            phase="HOST_TO_BROKER_UDS",
            strategy="MCP_FAULT_ENDPOINT_SHARED_DEADLINE",
            reason="MCP_DEADLINE_EXCEEDED",
            mcp_calls=1,
            provider_calls=0,
            identity="broker-timeout/mcp-fault-timeout-v1",
            binding="scripts.dg13u_u1_mcp_fault:McpFaultEndpoint",
            direct=True,
        ),
        "U1-PROVIDER-DOWN": _fault(
            "U1-PROVIDER-DOWN",
            phase="HOST_TO_PROVIDER_HTTP",
            strategy="START_STOP_FAULT_ENDPOINT_BEFORE_TURN",
            reason="PROVIDER_UNAVAILABLE",
            mcp_calls=0,
            provider_calls=1,
            identity="provider-down/stopped-loopback-v1",
            binding="scripts.dg13u_u1_provider_fault:ProviderFaultInjector",
            direct=True,
        ),
        "U1-PROVIDER-MALFORMED": _fault(
            "U1-PROVIDER-MALFORMED",
            phase="HOST_TO_PROVIDER_HTTP",
            strategy="PROVIDER_FAULT_ENDPOINT_MALFORMED",
            reason="PROVIDER_STREAM_FAILED",
            mcp_calls=0,
            provider_calls=1,
            identity="provider-malformed/provider-fault-malformed-v1",
            binding="scripts.dg13u_u1_provider_fault:ProviderFaultInjector",
            direct=True,
        ),
        "U1-PROVIDER-TIMEOUT": _fault(
            "U1-PROVIDER-TIMEOUT",
            phase="HOST_TO_PROVIDER_HTTP",
            strategy="HOST_TIMEOUT_SHORTER_THAN_FAULT_DELAY",
            reason="PROVIDER_UNAVAILABLE",
            mcp_calls=0,
            provider_calls=1,
            identity="provider-timeout/provider-fault-timeout-v1",
            binding="scripts.dg13u_u1_provider_fault:ProviderFaultInjector",
            direct=True,
        ),
    }
)


def fault_scenario_for_case(case_id: str) -> FaultScenario:
    """Return one immutable plan without claiming it has executed."""

    if not isinstance(case_id, str) or case_id not in FAULT_SCENARIOS:
        raise FaultScenarioError("UNSUPPORTED_FAULT_CASE")
    return FAULT_SCENARIOS[case_id]


def build_broker_fault_launch(
    case_id: str,
    *,
    run_owned_root: Path,
    python_executable: Path,
) -> BrokerFaultLaunch:
    """Build a shell-free broker fault action scoped to one private run root."""

    scenario = fault_scenario_for_case(case_id)
    if scenario.fault_phase != "HOST_TO_BROKER_UDS":
        raise FaultScenarioError("NOT_A_BROKER_FAULT")
    root = _private_run_root(run_owned_root)
    executable = _python_executable(python_executable)
    socket_path = root / "uds/reader-lite.sock"
    if case_id == "U1-BROKER-DOWN":
        return BrokerFaultLaunch(
            case_id=case_id,
            action="ENSURE_ENDPOINT_ABSENT",
            socket_path=socket_path,
            ledger_path=None,
            ready_path=None,
            command=(),
            max_connections=1,
            automatic_retries=0,
        )

    mode = "MALFORMED" if case_id == "U1-BROKER-MALFORMED" else "TIMEOUT"
    ledger_path = root / "evidence/broker-fault-ledger.json"
    ready_path = root / "temporary/broker-fault-ready.json"
    command = [
        str(executable),
        str(_MCP_FAULT_SCRIPT),
        "--mode",
        mode,
        "--socket",
        str(socket_path),
        "--ledger",
        str(ledger_path),
        "--ready-file",
        str(ready_path),
        "--max-frame-bytes",
        "65536",
    ]
    if mode == "TIMEOUT":
        command.extend(("--timeout-delay-seconds", "5.0"))
    return BrokerFaultLaunch(
        case_id=case_id,
        action="START_MCP_FAULT_ENDPOINT",
        socket_path=socket_path,
        ledger_path=ledger_path,
        ready_path=ready_path,
        command=tuple(command),
        max_connections=1,
        automatic_retries=0,
    )


def _private_run_root(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise FaultScenarioError("RUN_ROOT_MUST_BE_ABSOLUTE")
    if value == Path(value.anchor):
        raise FaultScenarioError("RUN_ROOT_UNSAFE")
    try:
        current = value.lstat()
    except OSError as exc:
        raise FaultScenarioError("RUN_ROOT_UNSAFE") from exc
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or current.st_uid != os.geteuid()
    ):
        raise FaultScenarioError("RUN_ROOT_UNSAFE")
    if stat.S_IMODE(current.st_mode) & 0o077:
        raise FaultScenarioError("RUN_ROOT_MODE_UNSAFE")
    if value.resolve() != value:
        raise FaultScenarioError("RUN_ROOT_UNSAFE")
    return value


def _python_executable(value: Path) -> Path:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or not value.is_file()
        or not os.access(value, os.X_OK)
    ):
        raise FaultScenarioError("PYTHON_EXECUTABLE_INVALID")
    return value


__all__ = [
    "FAULT_SCENARIOS",
    "BrokerFaultLaunch",
    "FaultScenario",
    "FaultScenarioError",
    "TerminalExpectation",
    "build_broker_fault_launch",
    "fault_scenario_for_case",
]
