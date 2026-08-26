from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts import dg13u_u1_fault_execution as execution
from scripts import dg13u_u1_fault_scenarios as scenarios

PRIVATE_PROMPT = "private synthetic prompt must not persist"
PRIVATE_TOKEN = "Bearer private synthetic credential must not persist"


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "run-owned"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _plan(tmp_path: Path, case_id: str) -> execution.FaultExecutionPlan:
    return execution.build_fault_execution_plan(
        case_id,
        run_owned_root=_root(tmp_path),
        python_executable=Path(os.sys.executable),
    )


def _provider_terminal(plan: execution.FaultExecutionPlan) -> dict[str, Any] | None:
    if not plan.case_id.startswith("U1-PROVIDER-"):
        return None
    return {
        "event_sequence": ["RESERVED", "PROVIDER_TERMINAL"],
        "logical_request_id_sha256": "b" * 64,
        "logical_reservations": 1,
        "terminal_status": "FAILED",
        "reason_code": plan.expected_terminal.reason_code,
        "request_started": plan.fixture.mode == "MALFORMED",
        "native_request_observed": False,
        "native_request_id_sha256": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "post_terminal_count": 0,
        "automatic_retries": 0,
    }


def _receipt_value(plan: execution.FaultExecutionPlan, schema: str) -> dict[str, Any]:
    mode = plan.fixture.mode
    if schema == "milai.dg13u.u1-runtime-fault-receipt.v1":
        return {
            "schema": schema,
            "mode": mode,
            "request_count": 1,
            "capability_request_count": 1,
            "faults_injected": 1,
            "automatic_retries": 0,
            "raw_request_persisted": False,
            "credential_material_persisted": False,
            "prompt_material_persisted": False,
            "cleanup": {
                "attempted": True,
                "listener_closed": True,
                "server_stopped": True,
                "worker_threads_stopped": True,
            },
        }
    if schema == "milai.dg13u.u1-mcp-fault-ledger.v1":
        return {
            "schema": schema,
            "mode": mode,
            "native_attempts": 1,
            "automatic_retries": 0,
            "active": False,
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
            "cleanup": {
                "path_absent": True,
                "owned_inode_removed": True,
            },
        }
    if schema == "milai.dg13u.u1-provider-fault-ledger.v1":
        return {
            "schema": schema,
            "mode": mode,
            "native_attempts": 1,
            "automatic_retries": 0,
            "active": False,
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
            "events": [{"request": {"body_sha256": "a" * 64}}],
        }
    logical_requests = 0 if mode == "DOWN" else 1
    if schema == "milai.dg13u.u1-mcp-child-fault-builder.v1":
        return {
            "schema": schema,
            "mode": mode,
            "logical_request_maximum": 1,
            "automatic_retries": 0,
        }
    if schema == "milai.dg13u.u1-mcp-child-fault-ledger.v1":
        return {
            "schema": schema,
            "mode": mode,
            "logical_requests": logical_requests,
            "automatic_retries": 0,
            "active": False,
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
        }
    if schema == "milai.dg13u.u1-mcp-child-fault-cleanup.v1":
        return {
            "schema": schema,
            "mode": mode,
            "status": "PASS",
            "logical_requests": logical_requests,
            "automatic_retries": 0,
            "raw_request_persisted": False,
            "request_credentials_persisted": False,
        }
    raise AssertionError(schema)


def _write_receipts(plan: execution.FaultExecutionPlan) -> None:
    for spec in plan.receipts:
        spec.path.write_bytes(
            json.dumps(
                _receipt_value(plan, spec.schema),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        spec.path.chmod(0o600)


def _reduce(
    plan: execution.FaultExecutionPlan,
    **updates: Any,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "host_terminal": dataclasses.asdict(plan.expected_terminal),
        "ledger_calls": {
            "mcp": plan.expected_mcp_calls,
            "provider": plan.expected_provider_calls,
        },
        "automatic_retries": 0,
        "provider_barrier": plan.provider_barrier,
        "provider_terminal_observation": _provider_terminal(plan),
        "external_vllm": {"attempts": 0, "lifecycle_mutations": 0},
        "fixture_observation": (
            {
                "state": "HELD_CLOSED",
                "attempts": 0,
                "cleanup_complete": True,
            }
            if not plan.receipts
            else {}
        ),
    }
    values.update(updates)
    return execution.reduce_fault_execution(plan, **values)


def test_all_thirteen_scenarios_have_one_direct_case_specific_plan(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    plans = {
        case_id: execution.build_fault_execution_plan(
            case_id,
            run_owned_root=root,
            python_executable=Path(os.sys.executable),
        )
        for case_id in scenarios.FAULT_SCENARIOS
    }

    assert len(plans) == 13
    assert all(
        scenario.wireability == "DIRECT" and scenario.missing_injection_point is None
        for scenario in scenarios.FAULT_SCENARIOS.values()
    )
    assert {plan.override.target for plan in plans.values()} == {
        "BROKER_SOCKET",
        "RUNTIME_BASE_URL",
        "MCP_EXECUTABLE",
        "PROVIDER_ENDPOINT",
    }
    assert sum(case_id.startswith("U1-RUNTIME-") for case_id in plans) == 4
    assert sum(case_id.startswith("U1-MCP-CHILD-") for case_id in plans) == 3
    assert sum(case_id.startswith("U1-BROKER-") for case_id in plans) == 3
    assert sum(case_id.startswith("U1-PROVIDER-") for case_id in plans) == 3
    assert all(plan.automatic_retries == 0 for plan in plans.values())
    assert all(
        plan.fixture.action
        in {"START", "BUILD_FOR_BROKER", "KEEP_CLOSED", "ENSURE_ABSENT"}
        for plan in plans.values()
    )
    for plan in plans.values():
        assert (
            plan.expected_terminal
            == scenarios.FAULT_SCENARIOS[plan.case_id].expected_terminal
        )
        if plan.fixture.command:
            assert plan.fixture.command[0] == os.sys.executable
            assert Path(plan.fixture.command[1]).is_file()
        assert all(spec.path.parent == root for spec in plan.receipts)
    assert plans["U1-BROKER-DOWN"].fixture.resource_path == root / "u1-broker-down.sock"
    assert plans["U1-MCP-CHILD-DOWN"].fixture.resource_path == (
        root / "u1-mcp-child-down-mcp-child"
    )


@pytest.mark.parametrize("case_id", sorted(scenarios.FAULT_SCENARIOS))
def test_reducer_accepts_exact_fixture_host_ledger_barrier_and_vllm_contract(
    tmp_path: Path,
    case_id: str,
) -> None:
    plan = _plan(tmp_path, case_id)
    _write_receipts(plan)

    result = _reduce(plan)

    assert result["status"] == "PASS"
    assert result["case_id"] == case_id
    assert result["automatic_retries"] == 0
    assert result["provider_terminal"] == _provider_terminal(plan)
    assert result["external_vllm"] == {"attempts": 0, "lifecycle_mutations": 0}
    assert result["receipt_identities"] == [
        {
            "name": spec.name,
            "path": str(spec.path),
            "schema": spec.schema,
            "sha256": hashlib.sha256(spec.path.read_bytes()).hexdigest(),
        }
        for spec in plan.receipts
    ]
    encoded = json.dumps(result, sort_keys=True)
    assert PRIVATE_PROMPT not in encoded
    assert PRIVATE_TOKEN not in encoded
    assert "command" not in result["fixture"]


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"host_terminal": {}}, "HOST_TERMINAL_MISMATCH"),
        ({"ledger_calls": {"mcp": 9, "provider": 9}}, "LEDGER_CALL_COUNT_MISMATCH"),
        ({"automatic_retries": 1}, "AUTOMATIC_RETRY_OBSERVED"),
        ({"provider_barrier": "BYPASSED"}, "PROVIDER_BARRIER_MISMATCH"),
        (
            {"external_vllm": {"attempts": 0, "lifecycle_mutations": 1}},
            "EXTERNAL_VLLM_MUTATED",
        ),
    ],
)
def test_reducer_negative_twins_fail_closed(
    tmp_path: Path,
    updates: dict[str, Any],
    reason: str,
) -> None:
    plan = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(plan)

    with pytest.raises(execution.FaultExecutionError, match=reason):
        _reduce(plan, **updates)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        (
            {"ledger_calls": {"mcp": False, "provider": True}},
            "LEDGER_CALL_COUNT_MISMATCH",
        ),
        ({"automatic_retries": False}, "AUTOMATIC_RETRY_OBSERVED"),
        (
            {"external_vllm": {"attempts": False, "lifecycle_mutations": False}},
            "EXTERNAL_VLLM_MUTATED",
        ),
    ],
)
def test_reducer_rejects_bool_for_integer_observations(
    tmp_path: Path,
    updates: dict[str, Any],
    reason: str,
) -> None:
    plan = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(plan)

    with pytest.raises(execution.FaultExecutionError, match=reason):
        _reduce(plan, **updates)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("logical_reservations", True),
        ("post_terminal_count", False),
        ("automatic_retries", False),
    ],
)
def test_provider_terminal_rejects_bool_for_integer_observations(
    tmp_path: Path,
    field: str,
    replacement: bool,
) -> None:
    plan = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(plan)
    observation = _provider_terminal(plan)
    assert observation is not None
    observation[field] = replacement

    with pytest.raises(
        execution.FaultExecutionError,
        match="PROVIDER_TERMINAL_OBSERVATION_MISMATCH",
    ):
        _reduce(plan, provider_terminal_observation=observation)


@pytest.mark.parametrize("replacement", [None, "A" * 64, "a" * 63, "g" * 64])
def test_provider_terminal_requires_lowercase_logical_request_sha256(
    tmp_path: Path,
    replacement: object,
) -> None:
    plan = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(plan)
    observation = _provider_terminal(plan)
    assert observation is not None
    observation["logical_request_id_sha256"] = replacement

    with pytest.raises(
        execution.FaultExecutionError,
        match="PROVIDER_TERMINAL_OBSERVATION_MISMATCH",
    ):
        _reduce(plan, provider_terminal_observation=observation)


def test_reducer_rejects_fixture_count_cleanup_and_raw_body_twins(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, "U1-RUNTIME-UNAVAILABLE")
    spec = plan.receipts[0]
    value = _receipt_value(plan, spec.schema)
    value["request_count"] = 2
    spec.path.write_text(json.dumps(value), encoding="utf-8")
    spec.path.chmod(0o600)
    with pytest.raises(
        execution.FaultExecutionError, match="RUNTIME_FIXTURE_RECONCILIATION_FAILED"
    ):
        _reduce(plan)

    spec.path.unlink()
    value["request_count"] = 1
    value["body"] = PRIVATE_PROMPT
    spec.path.write_text(json.dumps(value), encoding="utf-8")
    spec.path.chmod(0o600)
    with pytest.raises(
        execution.FaultExecutionError, match="RAW_SENSITIVE_CONTENT_FORBIDDEN"
    ):
        _reduce(plan)


@pytest.mark.parametrize(
    ("case_id", "schema", "field", "replacement", "reason"),
    [
        (
            "U1-RUNTIME-UNAVAILABLE",
            "milai.dg13u.u1-runtime-fault-receipt.v1",
            "request_count",
            True,
            "RUNTIME_FIXTURE_RECONCILIATION_FAILED",
        ),
        (
            "U1-BROKER-MALFORMED",
            "milai.dg13u.u1-mcp-fault-ledger.v1",
            "native_attempts",
            True,
            "MCP_UDS_FIXTURE_RECONCILIATION_FAILED",
        ),
        (
            "U1-PROVIDER-MALFORMED",
            "milai.dg13u.u1-provider-fault-ledger.v1",
            "automatic_retries",
            False,
            "PROVIDER_FIXTURE_RECONCILIATION_FAILED",
        ),
        (
            "U1-MCP-CHILD-MALFORMED",
            "milai.dg13u.u1-mcp-child-fault-ledger.v1",
            "logical_requests",
            True,
            "MCP_CHILD_FIXTURE_RECONCILIATION_FAILED",
        ),
    ],
)
def test_fixture_receipts_reject_bool_for_integer_observations(
    tmp_path: Path,
    case_id: str,
    schema: str,
    field: str,
    replacement: bool,
    reason: str,
) -> None:
    plan = _plan(tmp_path, case_id)
    _write_receipts(plan)
    spec = next(item for item in plan.receipts if item.schema == schema)
    value = _receipt_value(plan, spec.schema)
    value[field] = replacement
    spec.path.write_text(json.dumps(value), encoding="utf-8")
    spec.path.chmod(0o600)

    with pytest.raises(execution.FaultExecutionError, match=reason):
        _reduce(plan)


def test_closed_fixture_rejects_bool_attempt_count(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "U1-BROKER-DOWN")

    with pytest.raises(
        execution.FaultExecutionError,
        match="CLOSED_FIXTURE_RECONCILIATION_FAILED",
    ):
        _reduce(
            plan,
            fixture_observation={
                "state": "HELD_CLOSED",
                "attempts": False,
                "cleanup_complete": True,
            },
        )


@pytest.mark.parametrize(
    ("case_id", "field", "replacement"),
    [
        ("U1-PROVIDER-DOWN", "event_sequence", ["PROVIDER_TERMINAL"]),
        ("U1-PROVIDER-DOWN", "logical_reservations", 2),
        ("U1-PROVIDER-MALFORMED", "terminal_status", "SUCCEEDED"),
        ("U1-PROVIDER-MALFORMED", "reason_code", "NATIVE_REQUEST_ID_MISSING"),
        ("U1-PROVIDER-MALFORMED", "request_started", False),
        ("U1-PROVIDER-TIMEOUT", "request_started", True),
        ("U1-PROVIDER-DOWN", "native_request_observed", True),
        ("U1-PROVIDER-DOWN", "native_request_id_sha256", "a" * 64),
        ("U1-PROVIDER-DOWN", "prompt_tokens", 1),
        ("U1-PROVIDER-DOWN", "completion_tokens", 1),
        ("U1-PROVIDER-DOWN", "post_terminal_count", 1),
        ("U1-PROVIDER-DOWN", "automatic_retries", 1),
    ],
)
def test_provider_terminal_observation_negative_twins_fail_closed(
    tmp_path: Path, case_id: str, field: str, replacement: object
) -> None:
    plan = _plan(tmp_path, case_id)
    _write_receipts(plan)
    observation = _provider_terminal(plan)
    assert observation is not None
    observation[field] = replacement

    with pytest.raises(
        execution.FaultExecutionError,
        match="PROVIDER_TERMINAL_OBSERVATION_MISMATCH",
    ):
        _reduce(plan, provider_terminal_observation=observation)


def test_provider_terminal_observation_is_required_exact_and_provider_only(
    tmp_path: Path,
) -> None:
    provider = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(provider)
    with pytest.raises(
        execution.FaultExecutionError,
        match="PROVIDER_TERMINAL_OBSERVATION_REQUIRED",
    ):
        _reduce(provider, provider_terminal_observation=None)

    extra = _provider_terminal(provider)
    assert extra is not None
    extra["prompt"] = PRIVATE_PROMPT
    with pytest.raises(
        execution.FaultExecutionError, match="PROVIDER_TERMINAL_FIELDS_INVALID"
    ):
        _reduce(provider, provider_terminal_observation=extra)

    missing_logical_join = _provider_terminal(provider)
    assert missing_logical_join is not None
    missing_logical_join.pop("logical_request_id_sha256")
    with pytest.raises(
        execution.FaultExecutionError, match="PROVIDER_TERMINAL_FIELDS_INVALID"
    ):
        _reduce(provider, provider_terminal_observation=missing_logical_join)

    non_provider_root = tmp_path / "non-provider"
    non_provider_root.mkdir()
    non_provider = _plan(non_provider_root, "U1-BROKER-DOWN")
    with pytest.raises(
        execution.FaultExecutionError,
        match="UNEXPECTED_PROVIDER_TERMINAL_OBSERVATION",
    ):
        _reduce(
            non_provider,
            provider_terminal_observation=_provider_terminal(provider),
        )


def test_plan_rejects_unknown_case_and_unsafe_roots(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(execution.FaultExecutionError, match="UNSUPPORTED_FAULT_CASE"):
        execution.build_fault_execution_plan(
            "U1-NONE-EN",
            run_owned_root=root,
            python_executable=Path(os.sys.executable),
        )
    root.chmod(0o770)
    with pytest.raises(execution.FaultExecutionError, match="RUN_ROOT_UNSAFE"):
        execution.build_fault_execution_plan(
            "U1-RUNTIME-DOWN",
            run_owned_root=root,
            python_executable=Path(os.sys.executable),
        )

    secret_root = tmp_path / "secrets"
    secret_root.mkdir(mode=0o700)
    with pytest.raises(execution.FaultExecutionError, match="RUN_ROOT_SECRET_LIKE"):
        execution.build_fault_execution_plan(
            "U1-RUNTIME-DOWN",
            run_owned_root=secret_root,
            python_executable=Path(os.sys.executable),
        )


def test_receipts_must_be_private_regular_files(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "U1-PROVIDER-MALFORMED")
    _write_receipts(plan)
    plan.receipts[0].path.chmod(0o644)

    with pytest.raises(execution.FaultExecutionError, match="FIXTURE_RECEIPT_UNSAFE"):
        _reduce(plan)


def test_reducer_rejects_tampered_plan_expectations(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "U1-BROKER-DOWN")
    tampered = dataclasses.replace(plan, expected_mcp_calls=9)

    with pytest.raises(execution.FaultExecutionError, match="PLAN_CASE_INVALID"):
        _reduce(
            tampered,
            ledger_calls={"mcp": 9, "provider": tampered.expected_provider_calls},
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"expected_mcp_calls": True},
        {"expected_provider_calls": False},
        {"automatic_retries": False},
    ],
)
def test_reducer_rejects_bool_plan_integer_contracts(
    tmp_path: Path,
    updates: dict[str, bool],
) -> None:
    plan = _plan(tmp_path, "U1-BROKER-DOWN")
    tampered = dataclasses.replace(plan, **updates)

    with pytest.raises(execution.FaultExecutionError, match="PLAN_CASE_INVALID"):
        _reduce(tampered)
