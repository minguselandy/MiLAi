#!/usr/bin/env python3
"""Case-total launch and evidence-reduction contract for DG13-U1 faults."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from scripts.dg13u_u1_fault_scenarios import FAULT_SCENARIOS, TerminalExpectation

OverrideTarget = Literal[
    "BROKER_SOCKET",
    "RUNTIME_BASE_URL",
    "MCP_EXECUTABLE",
    "PROVIDER_ENDPOINT",
]
FixtureAction = Literal["START", "BUILD_FOR_BROKER", "KEEP_CLOSED", "ENSURE_ABSENT"]

_SCHEMA = "milai.dg13u.u1-fault-execution.v1"
_RUNTIME_SCRIPT = Path(__file__).with_name("dg13u_u1_runtime_fault.py").resolve()
_MCP_SCRIPT = Path(__file__).with_name("dg13u_u1_mcp_fault.py").resolve()
_MCP_CHILD_SCRIPT = Path(__file__).with_name("dg13u_u1_mcp_child_fault.py").resolve()
_PROVIDER_SCRIPT = Path(__file__).with_name("dg13u_u1_provider_fault.py").resolve()
_FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "authorization",
        "body",
        "credential",
        "credentials",
        "prompt",
        "raw_body",
        "token",
    }
)
_SECRET_PATH_PARTS = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "prompt",
        "secret",
        "secrets",
        "token",
        "tokens",
    }
)
_PROVIDER_TERMINAL_FIELDS = frozenset(
    {
        "event_sequence",
        "logical_request_id_sha256",
        "logical_reservations",
        "terminal_status",
        "reason_code",
        "request_started",
        "native_request_observed",
        "native_request_id_sha256",
        "prompt_tokens",
        "completion_tokens",
        "post_terminal_count",
        "automatic_retries",
    }
)
_PROVIDER_REQUEST_STARTED = MappingProxyType(
    {"DOWN": False, "MALFORMED": True, "TIMEOUT": False}
)


class FaultExecutionError(ValueError):
    """A launch contract or observed execution violates the frozen fault policy."""


def _is_exact_int(value: object, expected: int) -> bool:
    """Reject bool while matching one frozen integer observation."""

    return type(value) is int and value == expected


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class OverrideSpec:
    target: OverrideTarget
    value_ref: str


@dataclass(frozen=True, slots=True)
class ReceiptSpec:
    name: str
    path: Path
    schema: str


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    kind: str
    action: FixtureAction
    mode: str
    command: tuple[str, ...]
    delay_seconds: float | None
    resource_path: Path | None


@dataclass(frozen=True, slots=True)
class FaultExecutionPlan:
    schema: Literal["milai.dg13u.u1-fault-execution.v1"]
    case_id: str
    override: OverrideSpec
    fixture: FixtureSpec
    expected_terminal: TerminalExpectation
    expected_mcp_calls: int
    expected_provider_calls: int
    automatic_retries: Literal[0]
    provider_barrier: str
    receipts: tuple[ReceiptSpec, ...]


def _private_root(value: Path) -> Path:
    if not value.is_absolute() or value == Path("/"):
        raise FaultExecutionError("RUN_ROOT_MUST_BE_PRIVATE_ABSOLUTE")
    if any(part.casefold() in _SECRET_PATH_PARTS for part in value.parts):
        raise FaultExecutionError("RUN_ROOT_SECRET_LIKE")
    try:
        current = value.lstat()
    except OSError as exc:
        raise FaultExecutionError("RUN_ROOT_UNAVAILABLE") from exc
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or current.st_uid != os.geteuid()
        or stat.S_IMODE(current.st_mode) & 0o077
    ):
        raise FaultExecutionError("RUN_ROOT_UNSAFE")
    return value


def _python(value: Path) -> Path:
    if not value.is_absolute() or not value.is_file() or not os.access(value, os.X_OK):
        raise FaultExecutionError("PYTHON_EXECUTABLE_INVALID")
    return value


def _receipt(root: Path, name: str, schema: str) -> ReceiptSpec:
    return ReceiptSpec(name=name, path=root / name, schema=schema)


def build_fault_execution_plan(
    case_id: str,
    *,
    run_owned_root: Path,
    python_executable: Path,
) -> FaultExecutionPlan:
    """Build one side-effect-free, shell-free plan over an existing private run root."""

    scenario = FAULT_SCENARIOS.get(case_id)
    if scenario is None:
        raise FaultExecutionError("UNSUPPORTED_FAULT_CASE")
    if scenario.wireability != "DIRECT" or scenario.missing_injection_point is not None:
        raise FaultExecutionError("FAULT_CASE_NOT_DIRECT")
    root = _private_root(run_owned_root)
    python = _python(python_executable)
    slug = case_id.casefold()
    delay: float | None = None
    receipts: tuple[ReceiptSpec, ...] = ()

    if case_id.startswith("U1-RUNTIME-"):
        mode = case_id.removeprefix("U1-RUNTIME-")
        if mode == "DOWN":
            fixture = FixtureSpec(
                "RUNTIME_CLOSED_LOOPBACK", "KEEP_CLOSED", mode, (), None, None
            )
        else:
            delay = 5.0 if mode == "TIMEOUT" else 0.1
            runtime_receipt = _receipt(
                root,
                f"{slug}-runtime-receipt.json",
                "milai.dg13u.u1-runtime-fault-receipt.v1",
            )
            receipts = (runtime_receipt,)
            fixture = FixtureSpec(
                "RUNTIME_HTTP",
                "START",
                mode,
                (
                    str(python),
                    str(_RUNTIME_SCRIPT),
                    "--artifact",
                    str(runtime_receipt.path),
                    "--run-id",
                    f"dg13u-fault-{slug}",
                    "--mode",
                    mode,
                    "--delay-seconds",
                    str(delay),
                ),
                delay,
                None,
            )
        override = OverrideSpec("RUNTIME_BASE_URL", "fixture.base_url")
    elif case_id.startswith("U1-MCP-CHILD-"):
        mode = case_id.removeprefix("U1-MCP-CHILD-")
        delay = 5.0 if mode == "TIMEOUT" else 0.1
        executable = root / f"{slug}-mcp-child"
        ledger = _receipt(
            root,
            f"{slug}-ledger.json",
            "milai.dg13u.u1-mcp-child-fault-ledger.v1",
        )
        cleanup = _receipt(
            root,
            f"{slug}-cleanup.json",
            "milai.dg13u.u1-mcp-child-fault-cleanup.v1",
        )
        builder = _receipt(
            root,
            f"{slug}-builder.json",
            "milai.dg13u.u1-mcp-child-fault-builder.v1",
        )
        receipts = (builder, ledger, cleanup)
        fixture = FixtureSpec(
            "MCP_CHILD_STDIO",
            "BUILD_FOR_BROKER",
            mode,
            (
                str(python),
                str(_MCP_CHILD_SCRIPT),
                "build",
                "--mode",
                mode,
                "--executable",
                str(executable),
                "--ledger",
                str(ledger.path),
                "--cleanup-receipt",
                str(cleanup.path),
                "--manifest",
                str(builder.path),
                "--timeout-delay-seconds",
                str(delay),
            ),
            delay,
            executable,
        )
        override = OverrideSpec("MCP_EXECUTABLE", "fixture.mcp_executable")
    elif case_id.startswith("U1-BROKER-"):
        mode = case_id.removeprefix("U1-BROKER-")
        socket_path = root / f"{slug}.sock"
        if mode == "DOWN":
            fixture = FixtureSpec(
                "BROKER_SOCKET", "ENSURE_ABSENT", mode, (), None, socket_path
            )
        else:
            delay = 5.0 if mode == "TIMEOUT" else 0.1
            ledger = _receipt(
                root,
                f"{slug}-ledger.json",
                "milai.dg13u.u1-mcp-fault-ledger.v1",
            )
            receipts = (ledger,)
            fixture = FixtureSpec(
                "MCP_UDS",
                "START",
                mode,
                (
                    str(python),
                    str(_MCP_SCRIPT),
                    "--mode",
                    mode,
                    "--socket",
                    str(socket_path),
                    "--ledger",
                    str(ledger.path),
                    "--timeout-delay-seconds",
                    str(delay),
                ),
                delay,
                socket_path,
            )
        override = OverrideSpec("BROKER_SOCKET", "fixture.socket_path")
    elif case_id.startswith("U1-PROVIDER-"):
        mode = case_id.removeprefix("U1-PROVIDER-")
        if mode == "DOWN":
            fixture = FixtureSpec(
                "PROVIDER_CLOSED_LOOPBACK", "KEEP_CLOSED", mode, (), None, None
            )
        else:
            delay = 5.0 if mode == "TIMEOUT" else 0.1
            ledger = _receipt(
                root,
                f"{slug}-ledger.json",
                "milai.dg13u.u1-provider-fault-ledger.v1",
            )
            receipts = (ledger,)
            fixture = FixtureSpec(
                "PROVIDER_HTTP",
                "START",
                mode,
                (
                    str(python),
                    str(_PROVIDER_SCRIPT),
                    "--mode",
                    mode,
                    "--ledger",
                    str(ledger.path),
                    "--timeout-delay-seconds",
                    str(delay),
                ),
                delay,
                None,
            )
        override = OverrideSpec("PROVIDER_ENDPOINT", "fixture.endpoint")
    else:  # pragma: no cover - the scenario catalog is prefix-total
        raise FaultExecutionError("UNSUPPORTED_FAULT_CASE")

    return FaultExecutionPlan(
        schema=_SCHEMA,
        case_id=case_id,
        override=override,
        fixture=fixture,
        expected_terminal=scenario.expected_terminal,
        expected_mcp_calls=scenario.expected_mcp_calls,
        expected_provider_calls=scenario.expected_provider_calls,
        automatic_retries=0,
        provider_barrier=scenario.expected_provider_barrier,
        receipts=receipts,
    )


def _json_receipt(spec: ReceiptSpec) -> tuple[dict[str, Any], str]:
    try:
        current = spec.path.lstat()
        raw = spec.path.read_bytes()
    except OSError as exc:
        raise FaultExecutionError("FIXTURE_RECEIPT_UNAVAILABLE") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or stat.S_IMODE(current.st_mode) != 0o600
        or len(raw) > 1_048_576
    ):
        raise FaultExecutionError("FIXTURE_RECEIPT_UNSAFE")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaultExecutionError("FIXTURE_RECEIPT_INVALID") from exc
    if not isinstance(value, dict) or value.get("schema") != spec.schema:
        raise FaultExecutionError("FIXTURE_RECEIPT_SCHEMA_MISMATCH")
    _reject_raw_sensitive_content(value)
    return value, hashlib.sha256(raw).hexdigest()


def _reject_raw_sensitive_content(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold() in _FORBIDDEN_CONTENT_KEYS:
                raise FaultExecutionError("RAW_SENSITIVE_CONTENT_FORBIDDEN")
            _reject_raw_sensitive_content(item)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_sensitive_content(item)
    elif isinstance(value, str) and "bearer " in value.casefold():
        raise FaultExecutionError("RAW_SENSITIVE_CONTENT_FORBIDDEN")


def _validate_fixture_receipts(
    plan: FaultExecutionPlan,
    receipts: Mapping[str, Mapping[str, Any]],
    fixture_observation: Mapping[str, Any],
) -> None:
    mode = plan.fixture.mode
    kind = plan.fixture.kind
    if not receipts:
        if (
            set(fixture_observation) != {"state", "attempts", "cleanup_complete"}
            or fixture_observation.get("state") != "HELD_CLOSED"
            or not _is_exact_int(fixture_observation.get("attempts"), 0)
            or fixture_observation.get("cleanup_complete") is not True
        ):
            raise FaultExecutionError("CLOSED_FIXTURE_RECONCILIATION_FAILED")
        return
    if kind == "RUNTIME_HTTP":
        value = receipts[plan.receipts[0].name]
        cleanup = value.get("cleanup")
        if (
            value.get("mode") != mode
            or not _is_exact_int(value.get("request_count"), 1)
            or not _is_exact_int(value.get("capability_request_count"), 1)
            or not _is_exact_int(value.get("faults_injected"), 1)
            or not _is_exact_int(value.get("automatic_retries"), 0)
            or not isinstance(cleanup, Mapping)
            or not all(
                cleanup.get(key) is True
                for key in (
                    "attempted",
                    "listener_closed",
                    "server_stopped",
                    "worker_threads_stopped",
                )
            )
        ):
            raise FaultExecutionError("RUNTIME_FIXTURE_RECONCILIATION_FAILED")
    elif kind == "MCP_UDS":
        value = receipts[plan.receipts[0].name]
        cleanup = value.get("cleanup")
        if (
            value.get("mode") != mode
            or not _is_exact_int(value.get("native_attempts"), 1)
            or not _is_exact_int(value.get("automatic_retries"), 0)
            or value.get("active") is not False
            or not isinstance(cleanup, Mapping)
            or cleanup.get("path_absent") is not True
            or cleanup.get("owned_inode_removed") is not True
        ):
            raise FaultExecutionError("MCP_UDS_FIXTURE_RECONCILIATION_FAILED")
    elif kind == "PROVIDER_HTTP":
        value = receipts[plan.receipts[0].name]
        if (
            value.get("mode") != mode
            or not _is_exact_int(value.get("native_attempts"), 1)
            or not _is_exact_int(value.get("automatic_retries"), 0)
            or value.get("active") is not False
            or value.get("raw_request_persisted") is not False
            or value.get("request_credentials_persisted") is not False
        ):
            raise FaultExecutionError("PROVIDER_FIXTURE_RECONCILIATION_FAILED")
    elif kind == "MCP_CHILD_STDIO":
        builder, ledger, cleanup = (receipts[spec.name] for spec in plan.receipts)
        logical_requests = 0 if mode == "DOWN" else 1
        if (
            builder.get("mode") != mode
            or not _is_exact_int(builder.get("logical_request_maximum"), 1)
            or not _is_exact_int(builder.get("automatic_retries"), 0)
            or ledger.get("mode") != mode
            or not _is_exact_int(ledger.get("logical_requests"), logical_requests)
            or not _is_exact_int(ledger.get("automatic_retries"), 0)
            or ledger.get("active") is not False
            or cleanup.get("status") != "PASS"
            or not _is_exact_int(cleanup.get("logical_requests"), logical_requests)
            or not _is_exact_int(cleanup.get("automatic_retries"), 0)
        ):
            raise FaultExecutionError("MCP_CHILD_FIXTURE_RECONCILIATION_FAILED")
    else:  # pragma: no cover - plan builder is kind-total
        raise FaultExecutionError("UNKNOWN_FIXTURE_KIND")


def _validate_provider_terminal_observation(
    plan: FaultExecutionPlan, raw: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    provider_case = plan.case_id.startswith("U1-PROVIDER-")
    if not provider_case:
        if raw is not None:
            raise FaultExecutionError("UNEXPECTED_PROVIDER_TERMINAL_OBSERVATION")
        return None
    if raw is None:
        raise FaultExecutionError("PROVIDER_TERMINAL_OBSERVATION_REQUIRED")
    if set(raw) != _PROVIDER_TERMINAL_FIELDS:
        raise FaultExecutionError("PROVIDER_TERMINAL_FIELDS_INVALID")
    logical_request_id_sha256 = raw.get("logical_request_id_sha256")
    if not _is_lower_sha256(logical_request_id_sha256):
        raise FaultExecutionError("PROVIDER_TERMINAL_OBSERVATION_MISMATCH")
    expected = {
        "event_sequence": ["RESERVED", "PROVIDER_TERMINAL"],
        "logical_request_id_sha256": logical_request_id_sha256,
        "logical_reservations": 1,
        "terminal_status": "FAILED",
        "reason_code": plan.expected_terminal.reason_code,
        "request_started": _PROVIDER_REQUEST_STARTED[plan.fixture.mode],
        "native_request_observed": False,
        "native_request_id_sha256": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "post_terminal_count": 0,
        "automatic_retries": 0,
    }
    integer_fields = {
        "logical_reservations": 1,
        "post_terminal_count": 0,
        "automatic_retries": 0,
    }
    if (
        any(
            not _is_exact_int(raw.get(name), expected_value)
            for name, expected_value in integer_fields.items()
        )
        or dict(raw) != expected
    ):
        raise FaultExecutionError("PROVIDER_TERMINAL_OBSERVATION_MISMATCH")
    return expected


def reduce_fault_execution(
    plan: FaultExecutionPlan,
    *,
    host_terminal: Mapping[str, Any],
    ledger_calls: Mapping[str, Any],
    automatic_retries: int,
    provider_barrier: str,
    external_vllm: Mapping[str, Any],
    provider_terminal_observation: Mapping[str, Any] | None,
    fixture_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one completed case and emit only bounded identities and outcomes."""

    scenario = FAULT_SCENARIOS.get(plan.case_id)
    if (
        scenario is None
        or scenario.wireability != "DIRECT"
        or plan.expected_terminal != scenario.expected_terminal
        or not _is_exact_int(plan.expected_mcp_calls, scenario.expected_mcp_calls)
        or not _is_exact_int(
            plan.expected_provider_calls, scenario.expected_provider_calls
        )
        or plan.provider_barrier != scenario.expected_provider_barrier
        or not _is_exact_int(plan.automatic_retries, 0)
    ):
        raise FaultExecutionError("PLAN_CASE_INVALID")
    if dict(host_terminal) != asdict(plan.expected_terminal):
        raise FaultExecutionError("HOST_TERMINAL_MISMATCH")
    if set(ledger_calls) != {"mcp", "provider"} or not all(
        _is_exact_int(ledger_calls.get(name), expected)
        for name, expected in (
            ("mcp", plan.expected_mcp_calls),
            ("provider", plan.expected_provider_calls),
        )
    ):
        raise FaultExecutionError("LEDGER_CALL_COUNT_MISMATCH")
    safe_provider_terminal = _validate_provider_terminal_observation(
        plan, provider_terminal_observation
    )
    if not _is_exact_int(automatic_retries, 0):
        raise FaultExecutionError("AUTOMATIC_RETRY_OBSERVED")
    if provider_barrier != plan.provider_barrier:
        raise FaultExecutionError("PROVIDER_BARRIER_MISMATCH")
    if set(external_vllm) != {"attempts", "lifecycle_mutations"} or not all(
        _is_exact_int(external_vllm.get(name), 0)
        for name in ("attempts", "lifecycle_mutations")
    ):
        raise FaultExecutionError("EXTERNAL_VLLM_MUTATED")

    values: dict[str, Mapping[str, Any]] = {}
    identities: list[dict[str, str]] = []
    for spec in plan.receipts:
        value, digest = _json_receipt(spec)
        values[spec.name] = value
        identities.append(
            {
                "name": spec.name,
                "path": str(spec.path),
                "schema": spec.schema,
                "sha256": digest,
            }
        )
    _validate_fixture_receipts(plan, values, fixture_observation or {})
    result = {
        "schema": _SCHEMA,
        "status": "PASS",
        "case_id": plan.case_id,
        "replacement": asdict(plan.override),
        "fixture": {
            "kind": plan.fixture.kind,
            "action": plan.fixture.action,
            "mode": plan.fixture.mode,
            "delay_seconds": plan.fixture.delay_seconds,
        },
        "host_terminal": asdict(plan.expected_terminal),
        "exact_calls": dict(ledger_calls),
        "automatic_retries": 0,
        "provider_barrier": plan.provider_barrier,
        "provider_terminal": safe_provider_terminal,
        "external_vllm": {"attempts": 0, "lifecycle_mutations": 0},
        "receipt_identities": identities,
    }
    _reject_raw_sensitive_content(result)
    return result
