#!/usr/bin/env python3
"""Offline, fail-closed aggregation for the exact DG-13U U1 case matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from scripts import dg13u_u1_fault_scenarios as fault_scenarios
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import dg13u_u1_fault_scenarios as fault_scenarios

REPORT_SCHEMA = "milai.dg13u.u1-run-report.v1"
MANIFEST_SCHEMA = "milai.dg13u.u1-run-manifest.v1"
AGGREGATE_SCHEMA = "milai.dg13u.u1-aggregate-report.v1"
RECOVERY_PLAN_SCHEMA = "milai.dg13u.u1-recovery-resource-plan.v1"
FAULT_EXECUTION_SCHEMA = "milai.dg13u.u1-fault-execution.v1"
RELEASE_LABEL = "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
GATE_NAMES = tuple(f"U1-G{index}" for index in range(6))
VALID_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "NOT_RUN"})
SAFETY_COUNTERS = (
    "WrongTaskAcceptance",
    "WrongScopeAcceptance",
    "StaleCurrentAcceptance",
    "RevokedEvidenceReentry",
    "UnauthorizedAuthorityEscalation",
    "SilentMemoryNeedNone",
    "TerminalCacheMiss",
    "ModelVisibleMemoryToolUse",
    "UnaccountedProviderOrMcpCall",
)
REQUIRED_STAGES = ("start", "readiness", "smoke", "reconciliation")
REQUIRED_BINDINGS = (
    "interface_freeze",
    "execution_override",
    "candidate_fixture",
    "task_metadata_headers",
)
REQUIRED_ARTIFACT_SCHEMAS = {
    "manifest.json": MANIFEST_SCHEMA,
    "exact-product-manifest.json": "milai.dg13u.u1-exact-product-manifest.v1",
    "identity-preflight.json": "milai.dg13u.u1-identity-preflight.v1",
    "readiness.json": "milai.dg13u.u1-readiness.v1",
    "smoke-evidence.json": "milai.dg13u.u1-smoke-evidence.v1",
    "reconciliation.json": "milai.dg13u.u1-reconciliation.v1",
    "cleanup-receipt.json": "milai.dg13u.u1-cleanup-receipt.v1",
    "recovery-resource-plan.json": RECOVERY_PLAN_SCHEMA,
}
CURRENT_SCOPE = {
    "deployment": "LOCAL",
    "profile": "reader-lite",
    "consistency": "STRICT_CURRENT",
    "task_continuity": "SAME_ADAPTER_PROCESS_ONLY",
    "data": "SYNTHETIC_OR_INDEPENDENTLY_DEIDENTIFIED",
    "delayed_or_asynchronous_tool_result": "UNSUPPORTED",
}
CURRENT_COMPOSITION = {
    "openworker_image": "milai-openworker:dg13u-u1-current-local",
    "provider_origin": "http://127.0.0.1:7860",
    "provider_model": MODEL_ID,
    "provider_lifecycle": "PRESERVE_EXISTING_READ_ONLY_IDENTITY",
    "runtime": "FRESH_RUN_OWNED_DATABASE_API_WORKER",
    "memory_transport": "READER_LITE_UDS_BROKER_MCP_ONLY",
    "provider_topology": "DIRECT_DEDICATED_DOCKER_BRIDGE_TO_RUN_OWNED_HOST",
}
CALL_POLICY = {
    "provider_automatic_retries": 0,
    "mcp_automatic_retries": 0,
    "provider_calls_per_turn_maximum": 1,
}


class AggregateError(RuntimeError):
    """An input cannot participate in a bounded U1 aggregate."""


@dataclass(frozen=True, slots=True)
class CaseContract:
    expected_mcp_calls: int
    expected_provider_calls: int
    safety_counters: tuple[str, ...]


def _case(
    mcp: int,
    provider: int,
    *safety: str,
) -> CaseContract:
    return CaseContract(mcp, provider, tuple(safety))


_UNACCOUNTED = "UnaccountedProviderOrMcpCall"
_VISIBLE = "ModelVisibleMemoryToolUse"
_SILENT_NONE = "SilentMemoryNeedNone"
_WRONG_TASK = "WrongTaskAcceptance"

CASE_CONTRACTS: dict[str, CaseContract] = {
    "U1-NONE-EN": _case(0, 1, _SILENT_NONE, _UNACCOUNTED),
    "U1-NONE-CN": _case(0, 1, _SILENT_NONE, _UNACCOUNTED),
    "U1-EXACT-TARGET-EN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-EXACT-TARGET-CN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-EXACT-DATABASE-EN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-EXACT-DATABASE-CN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-EXACT-DECISION-EN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-EXACT-DECISION-CN": _case(1, 1, _SILENT_NONE, _VISIBLE),
    "U1-CACHE-FALLBACK": _case(2, 2, "TerminalCacheMiss", _UNACCOUNTED),
    "U1-WRONG-TASK": _case(2, 2, _WRONG_TASK, _UNACCOUNTED),
    "U1-WRONG-SCOPE": _case(1, 1, "WrongScopeAcceptance", _UNACCOUNTED),
    "U1-STALE-CURRENT": _case(2, 2, "StaleCurrentAcceptance", _UNACCOUNTED),
    "U1-REVOKE-REENTRY": _case(1, 0, "RevokedEvidenceReentry"),
    "U1-AUTHORITY-ESCALATION": _case(0, 0, "UnauthorizedAuthorityEscalation"),
    "U1-RUNTIME-UNAVAILABLE": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-ALIAS-COLLISION": _case(0, 0, "WrongScopeAcceptance", _UNACCOUNTED),
    "U1-OPEN-ISSUE": _case(
        1,
        0,
        "StaleCurrentAcceptance",
        "UnauthorizedAuthorityEscalation",
        _UNACCOUNTED,
    ),
    "U1-BROKER-DOWN": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-BROKER-MALFORMED": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-BROKER-TIMEOUT": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-PROVIDER-DOWN": _case(0, 1, _UNACCOUNTED),
    "U1-PROVIDER-MALFORMED": _case(0, 1, _UNACCOUNTED),
    "U1-PROVIDER-TIMEOUT": _case(0, 1, _UNACCOUNTED),
    "U1-BROKER-INODE-RECREATE": _case(0, 0, _UNACCOUNTED),
    "U1-ADAPTER-RESTART": _case(2, 2, _WRONG_TASK, _UNACCOUNTED),
    "U1-STREAM": _case(1, 1, _UNACCOUNTED),
    "U1-ORDINARY-SYNC-TOOL": _case(0, 2, _VISIBLE, _UNACCOUNTED),
    "U1-TASK-CONTINUE": _case(2, 2, _WRONG_TASK, _UNACCOUNTED),
    "U1-TASK-SWITCH": _case(2, 2, _WRONG_TASK, _UNACCOUNTED),
    "U1-TASK-RETURN": _case(3, 3, _WRONG_TASK, "StaleCurrentAcceptance"),
    "U1-TASK-CONCURRENT": _case(2, 2, _WRONG_TASK, _UNACCOUNTED),
    "U1-RUNTIME-DOWN": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-RUNTIME-MALFORMED": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-RUNTIME-TIMEOUT": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-MCP-CHILD-DOWN": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-MCP-CHILD-MALFORMED": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
    "U1-MCP-CHILD-TIMEOUT": _case(1, 0, _SILENT_NONE, _UNACCOUNTED),
}
REQUIRED_CASE_IDS = tuple(CASE_CONTRACTS)
FAULT_CASE_IDS = frozenset(fault_scenarios.FAULT_SCENARIOS)
if not FAULT_CASE_IDS <= set(CASE_CONTRACTS):  # pragma: no cover - import invariant
    raise RuntimeError("frozen fault cases are not a subset of the U1 matrix")
PROVIDER_FAILURE_CASE_IDS = frozenset(
    {
        "U1-PROVIDER-DOWN",
        "U1-PROVIDER-MALFORMED",
        "U1-PROVIDER-TIMEOUT",
    }
)
PROVIDER_NATIVE_JOIN_CASE_IDS = frozenset(
    case_id
    for case_id, contract in CASE_CONTRACTS.items()
    if contract.expected_provider_calls > 0 and case_id not in PROVIDER_FAILURE_CASE_IDS
)
MEMORY_CONTEXT_CASE_IDS = frozenset(
    case_id
    for case_id in REQUIRED_CASE_IDS
    if case_id.startswith(("U1-EXACT-", "U1-TASK-"))
    or case_id
    in {
        "U1-CACHE-FALLBACK",
        "U1-WRONG-TASK",
        "U1-WRONG-SCOPE",
        "U1-STALE-CURRENT",
        "U1-ADAPTER-RESTART",
        "U1-STREAM",
    }
)
EXACT_SUCCESS_CASE_IDS = MEMORY_CONTEXT_CASE_IDS


@dataclass(frozen=True, slots=True)
class _LoadedRun:
    path: Path
    report: dict[str, Any]
    manifest: dict[str, Any]
    manifest_current: bool
    manifest_reasons: tuple[str, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AggregateError(f"{label} must be an object")
    return value


def _status(value: object, label: str) -> str:
    if value not in VALID_STATUSES:
        raise AggregateError(f"{label} status is invalid")
    return str(value)


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AggregateError(f"{label} must be a nonnegative integer")
    return value


def _nonnegative_number(value: object) -> int | float | None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        return None
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise AggregateError(f"{label} must be an explicit regular file")
    try:
        return _object(json.loads(path.read_bytes()), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregateError(f"{label} is unreadable") from exc


def _manifest_artifact_matches(report: Mapping[str, Any], manifest_path: Path) -> bool:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    matches = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and item.get("path") == "manifest.json"
    ]
    return (
        len(matches) == 1
        and matches[0].get("sha256") == _sha256(manifest_path)
        and matches[0].get("bytes") == manifest_path.stat().st_size
    )


def _manifest_reasons(
    report: Mapping[str, Any], manifest: Mapping[str, Any], manifest_path: Path
) -> tuple[str, ...]:
    reasons: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        reasons.append("MANIFEST_SCHEMA_INVALID")
    for name in ("run_id", "case_id"):
        if manifest.get(name) != report.get(name):
            reasons.append(f"MANIFEST_{name.upper()}_MISMATCH")
    if manifest.get("status") != report.get("status"):
        reasons.append("MANIFEST_STATUS_MISMATCH")
    if manifest.get("release_label") != RELEASE_LABEL:
        reasons.append("RELEASE_LABEL_DRIFT")
    if manifest.get("release_label_earned") is not False:
        reasons.append("CASE_RELEASE_LABEL_PREMATURE")
    if manifest.get("scope") != CURRENT_SCOPE:
        reasons.append("CURRENT_SCOPE_DRIFT")
    if manifest.get("requested_composition") != CURRENT_COMPOSITION:
        reasons.append("CURRENT_COMPOSITION_DRIFT")
    case_id = report.get("case_id")
    contract = CASE_CONTRACTS.get(str(case_id))
    expected_call_policy = (
        {
            **CALL_POLICY,
            "provider_calls_case_maximum": contract.expected_provider_calls,
        }
        if contract is not None
        else None
    )
    if manifest.get("call_policy") != expected_call_policy:
        reasons.append("CALL_POLICY_DRIFT")
    if manifest.get("formal_evaluation_input") is not False:
        reasons.append("FORMAL_INPUT_BOUNDARY_INVALID")
    bindings = manifest.get("bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != set(REQUIRED_BINDINGS):
        reasons.append("MANIFEST_BINDINGS_INVALID")
    else:
        for name in REQUIRED_BINDINGS:
            identity = bindings[name]
            if (
                not isinstance(identity, Mapping)
                or not isinstance(identity.get("path"), str)
                or not isinstance(identity.get("sha256"), str)
                or len(identity["sha256"]) != 64
            ):
                reasons.append(f"MANIFEST_BINDING_{name.upper()}_INVALID")
    if not _manifest_artifact_matches(report, manifest_path):
        reasons.append("REPORT_MANIFEST_ARTIFACT_MISMATCH")
    return tuple(reasons)


def _load_runs(report_paths: Sequence[Path]) -> list[_LoadedRun]:
    if not report_paths:
        raise AggregateError("at least one explicit --report is required")
    resolved = [path.resolve(strict=False) for path in report_paths]
    if len(resolved) != len(set(resolved)):
        raise AggregateError("duplicate report path")
    loaded: list[_LoadedRun] = []
    seen_cases: set[str] = set()
    seen_runs: set[str] = set()
    for path in report_paths:
        report = _read_json(path, "run report")
        if report.get("schema") != REPORT_SCHEMA:
            raise AggregateError("run report schema is invalid")
        run_id = report.get("run_id")
        case_id = report.get("case_id")
        if not isinstance(run_id, str) or not run_id:
            raise AggregateError("run report run_id is invalid")
        if case_id not in CASE_CONTRACTS:
            raise AggregateError(f"unexpected case_id: {case_id}")
        if run_id in seen_runs:
            raise AggregateError(f"duplicate run_id: {run_id}")
        if case_id in seen_cases:
            raise AggregateError(f"duplicate case_id: {case_id}")
        _status(report.get("status"), f"{case_id} report")
        seen_runs.add(run_id)
        seen_cases.add(case_id)
        manifest_path = path.with_name("manifest.json")
        manifest = _read_json(manifest_path, f"{case_id} manifest")
        reasons = _manifest_reasons(report, manifest, manifest_path)
        loaded.append(
            _LoadedRun(
                path=path,
                report=report,
                manifest=manifest,
                manifest_current=not reasons,
                manifest_reasons=reasons,
            )
        )
    return loaded


def _artifact_token(name: str) -> str:
    return name.removesuffix(".json").replace("-", "_").upper()


def _required_artifact_schemas(case_id: str) -> dict[str, str]:
    required = dict(REQUIRED_ARTIFACT_SCHEMAS)
    if case_id in FAULT_CASE_IDS:
        required["fault-execution.json"] = FAULT_EXECUTION_SCHEMA
    return required


def _expected_artifact_status(name: str, report: Mapping[str, Any]) -> object:
    if name in {
        "exact-product-manifest.json",
        "fault-execution.json",
        "identity-preflight.json",
    }:
        return "PASS"
    if name == "cleanup-receipt.json":
        cleanup = report.get("cleanup")
        return cleanup.get("status") if isinstance(cleanup, Mapping) else None
    return report.get("status")


def _exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _validate_fault_execution(
    document: Mapping[str, Any] | None,
    *,
    case_id: str,
    run_id: str,
) -> list[str]:
    if case_id not in FAULT_CASE_IDS:
        return []
    if document is None:
        return ["FAULT_EXECUTION_ARTIFACT_MISSING"]

    reasons: list[str] = []
    scenario = fault_scenarios.FAULT_SCENARIOS[case_id]
    if document.get("schema") != FAULT_EXECUTION_SCHEMA:
        reasons.append("FAULT_EXECUTION_SCHEMA_INVALID")
    if document.get("status") != "PASS":
        reasons.append("FAULT_EXECUTION_STATUS_NOT_PASS")
    if document.get("run_id") != run_id:
        reasons.append("FAULT_EXECUTION_RUN_ID_MISMATCH")
    if document.get("case_id") != case_id:
        reasons.append("FAULT_EXECUTION_CASE_ID_MISMATCH")
    if document.get("host_terminal") != asdict(scenario.expected_terminal):
        reasons.append("FAULT_EXECUTION_HOST_TERMINAL_MISMATCH")

    exact_calls = document.get("exact_calls")
    if not (
        isinstance(exact_calls, Mapping)
        and set(exact_calls) == {"mcp", "provider"}
        and _exact_int(exact_calls.get("mcp"), scenario.expected_mcp_calls)
        and _exact_int(exact_calls.get("provider"), scenario.expected_provider_calls)
    ):
        reasons.append("FAULT_EXECUTION_EXACT_CALLS_MISMATCH")
    if not _exact_int(document.get("automatic_retries"), 0):
        reasons.append("FAULT_EXECUTION_AUTOMATIC_RETRIES_NOT_ZERO")
    if document.get("provider_barrier") != scenario.expected_provider_barrier:
        reasons.append("FAULT_EXECUTION_PROVIDER_BARRIER_MISMATCH")
    if not _exact_int(document.get("external_attempts"), 0):
        reasons.append("FAULT_EXECUTION_EXTERNAL_ATTEMPTS_NOT_ZERO")
    if not _exact_int(document.get("external_lifecycle_mutations"), 0):
        reasons.append("FAULT_EXECUTION_EXTERNAL_LIFECYCLE_MUTATIONS_NOT_ZERO")

    external_vllm = document.get("external_vllm")
    if not (
        isinstance(external_vllm, Mapping)
        and set(external_vllm) == {"attempts", "lifecycle_mutations"}
        and _exact_int(external_vllm.get("attempts"), 0)
        and _exact_int(external_vllm.get("lifecycle_mutations"), 0)
    ):
        reasons.append("FAULT_EXECUTION_EXTERNAL_VLLM_INVALID")
    return reasons


def _validate_run_evidence(run: _LoadedRun) -> dict[str, Any]:
    report = run.report
    case_id = str(report["case_id"])
    run_id = str(report["run_id"])
    reasons: dict[str, list[str]] = {
        "artifacts": [],
        "fault_execution": [],
        "feature_support": [],
        "context_tokens": [],
        "joined_identities": [],
        "readiness_security": [],
        "reconciliation": [],
    }

    feature_support = report.get("feature_support")
    if (
        not isinstance(feature_support, Mapping)
        or feature_support.get("delayed_or_asynchronous_tool_result") != "UNSUPPORTED"
    ):
        reasons["feature_support"].append(
            "DELAYED_OR_ASYNC_TOOL_RESULT_NOT_UNSUPPORTED"
        )

    context_tokens = report.get("context_tokens")
    if not isinstance(context_tokens, int) or isinstance(context_tokens, bool):
        reasons["context_tokens"].append("CONTEXT_TOKENS_NOT_INTEGER")
    elif case_id in MEMORY_CONTEXT_CASE_IDS and context_tokens <= 0:
        reasons["context_tokens"].append("MEMORY_CONTEXT_TOKENS_NOT_POSITIVE")
    elif case_id not in MEMORY_CONTEXT_CASE_IDS and context_tokens != 0:
        reasons["context_tokens"].append(
            "NON_MEMORY_OR_TERMINAL_CONTEXT_TOKENS_NOT_ZERO"
        )

    identities = report.get("joined_identities")
    if not isinstance(identities, Mapping):
        identities = {}
        reasons["joined_identities"].append("JOINED_IDENTITIES_MISSING")
    if case_id in PROVIDER_NATIVE_JOIN_CASE_IDS and not _is_sha256(
        identities.get("provider_native_request_id_sha256")
    ):
        reasons["joined_identities"].append("PROVIDER_NATIVE_REQUEST_ID_HASH_MISSING")
    if case_id in EXACT_SUCCESS_CASE_IDS:
        for field in (
            "access_id_sha256",
            "mcp_receipt_sha256",
            "runtime_trace_sha256",
        ):
            if not _is_sha256(identities.get(field)):
                reasons["joined_identities"].append(f"{field.upper()}_MISSING")

    artifacts = report.get("artifacts")
    rows_by_path: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(artifacts, list):
        for row in artifacts:
            if isinstance(row, Mapping) and isinstance(row.get("path"), str):
                rows_by_path.setdefault(str(row["path"]), []).append(row)
    else:
        reasons["artifacts"].append("ARTIFACT_INDEX_MISSING")
    documents: dict[str, dict[str, Any]] = {}
    for name, schema in _required_artifact_schemas(case_id).items():
        token = _artifact_token(name)
        rows = rows_by_path.get(name, [])
        if len(rows) != 1:
            reasons["artifacts"].append(
                f"ARTIFACT_{token}_{'MISSING' if not rows else 'DUPLICATE'}"
            )
            continue
        artifact_path = run.path.parent / name
        if not artifact_path.is_file() or artifact_path.is_symlink():
            reasons["artifacts"].append(f"ARTIFACT_{token}_NOT_REGULAR")
            continue
        row = rows[0]
        if row.get("bytes") != artifact_path.stat().st_size:
            reasons["artifacts"].append(f"ARTIFACT_{token}_BYTES_MISMATCH")
        if row.get("sha256") != _sha256(artifact_path):
            reasons["artifacts"].append(f"ARTIFACT_{token}_SHA256_MISMATCH")
        try:
            document = _object(json.loads(artifact_path.read_bytes()), name)
        except (AggregateError, OSError, json.JSONDecodeError):
            reasons["artifacts"].append(f"ARTIFACT_{token}_JSON_INVALID")
            continue
        documents[name] = document
        if document.get("schema") != schema:
            reasons["artifacts"].append(f"ARTIFACT_{token}_SCHEMA_INVALID")
        if document.get("run_id") != run_id:
            reasons["artifacts"].append(f"ARTIFACT_{token}_RUN_ID_MISMATCH")
        if name != "recovery-resource-plan.json":
            if document.get("status") != _expected_artifact_status(name, report):
                reasons["artifacts"].append(f"ARTIFACT_{token}_STATUS_MISMATCH")
            if document.get("case_id") != case_id:
                reasons["artifacts"].append(f"ARTIFACT_{token}_CASE_ID_MISMATCH")

    reasons["fault_execution"].extend(
        _validate_fault_execution(
            documents.get("fault-execution.json"),
            case_id=case_id,
            run_id=run_id,
        )
    )

    readiness = documents.get("readiness.json", {})
    for component in ("runtime", "broker", "host", "openworker"):
        if readiness.get(component) != "PASS":
            reasons["readiness_security"].append(
                f"READINESS_{component.upper()}_NOT_PASS"
            )
    if readiness.get("provider") != "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS":
        reasons["readiness_security"].append("READINESS_PROVIDER_IDENTITY_NOT_PASS")
    security = readiness.get("security")
    if not isinstance(security, Mapping):
        reasons["readiness_security"].append("READINESS_SECURITY_MISSING")
    else:
        expected_security = {
            "status": "PASS",
            "network_internal": True,
            "reader_lite_socket_read_only": True,
            "docker_socket_mounted": False,
            "forbidden_environment_names": [],
        }
        for field, expected in expected_security.items():
            if security.get(field) != expected:
                reasons["readiness_security"].append(
                    f"READINESS_SECURITY_{field.upper()}_INVALID"
                )

    reconciliation = documents.get("reconciliation.json", {})
    if reconciliation.get("unaccounted_calls") != 0:
        reasons["reconciliation"].append("RECONCILIATION_UNACCOUNTED_CALLS_NOT_ZERO")
    if reconciliation.get("durable_credentials_found") != 0:
        reasons["reconciliation"].append("RECONCILIATION_CREDENTIALS_NOT_ZERO")
    cleanup = documents.get("cleanup-receipt.json", {})
    plan = documents.get("recovery-resource-plan.json", {})
    plan_path = run.path.with_name("recovery-resource-plan.json")
    plan_sha256 = _sha256(plan_path) if plan_path.is_file() else None
    report_cleanup = report.get("cleanup")
    report_plan_sha256 = (
        report_cleanup.get("recovery_plan_sha256")
        if isinstance(report_cleanup, Mapping)
        and report_cleanup.get("status") == "PASS"
        else None
    )
    if not _is_sha256(report_plan_sha256):
        reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_SHA256_INVALID")
    elif report_plan_sha256 != plan_sha256:
        reasons["reconciliation"].append("REPORT_RECOVERY_PLAN_SHA256_MISMATCH")
    if plan.get("schema") != RECOVERY_PLAN_SCHEMA:
        reasons["reconciliation"].append("RECOVERY_PLAN_SCHEMA_INVALID")
    if plan.get("run_id") != run_id:
        reasons["reconciliation"].append("RECOVERY_PLAN_RUN_ID_MISMATCH")
    plan_external = [
        item
        for item in plan.get("resources", [])
        if isinstance(item, Mapping) and item.get("kind") == "external_vllm"
    ]
    if (
        len(plan_external) != 1
        or plan_external[0].get("ownership") != "PRESERVED_EXTERNAL"
    ):
        reasons["reconciliation"].append("RECOVERY_PLAN_EXTERNAL_VLLM_INVALID")
    recovery_binding = cleanup.get("recovery_plan")
    if not isinstance(recovery_binding, Mapping):
        reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_BINDING_MISSING")
    else:
        if recovery_binding.get("schema") != RECOVERY_PLAN_SCHEMA:
            reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_SCHEMA_MISMATCH")
        if recovery_binding.get("status") != "PASS":
            reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_NOT_PASS")
        if recovery_binding.get("path") != str(plan_path.resolve(strict=False)):
            reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_PATH_MISMATCH")
        binding_sha256 = recovery_binding.get("sha256")
        if not _is_sha256(binding_sha256) or binding_sha256 != plan_sha256:
            reasons["reconciliation"].append("CLEANUP_RECOVERY_PLAN_SHA256_MISMATCH")
        if _is_sha256(report_plan_sha256) and binding_sha256 != report_plan_sha256:
            reasons["reconciliation"].append(
                "REPORT_CLEANUP_RECOVERY_PLAN_BINDING_MISMATCH"
            )
    if cleanup.get("existing_vllm_preserved") is not True:
        reasons["reconciliation"].append("CLEANUP_EXTERNAL_VLLM_NOT_PRESERVED")
    if cleanup.get("external_lifecycle_mutations") != 0:
        reasons["reconciliation"].append("CLEANUP_EXTERNAL_VLLM_MUTATED")
    cleanup_items = cleanup.get("items")
    external_cleanup_items = (
        [
            item
            for item in cleanup_items
            if isinstance(item, Mapping) and item.get("kind") == "external_vllm"
        ]
        if isinstance(cleanup_items, list)
        else []
    )
    if len(external_cleanup_items) != 1 or not (
        external_cleanup_items[0].get("ownership") == "PRESERVED_EXTERNAL"
        and external_cleanup_items[0].get("state") == "preserved_external"
        and external_cleanup_items[0].get("attempts") == 0
    ):
        reasons["reconciliation"].append("CLEANUP_EXTERNAL_VLLM_RECEIPT_MISSING")
    if not isinstance(cleanup_items, list) or any(
        isinstance(item, Mapping)
        and item.get("kind") == "external_vllm"
        and item.get("attempts") != 0
        for item in cleanup_items
    ):
        reasons["reconciliation"].append("CLEANUP_EXTERNAL_VLLM_ATTEMPTS_NOT_ZERO")

    categories = {
        name: {
            "status": "PASS" if not category_reasons else "FAIL",
            "reason_codes": category_reasons,
        }
        for name, category_reasons in reasons.items()
    }
    return {
        "case_id": case_id,
        "run_id": run_id,
        "status": (
            "PASS"
            if all(value["status"] == "PASS" for value in categories.values())
            else "FAIL"
        ),
        "categories": categories,
    }


def _aggregate_evidence(runs: Sequence[_LoadedRun]) -> dict[str, Any]:
    cases = [_validate_run_evidence(run) for run in runs]
    category_names = (
        "artifacts",
        "fault_execution",
        "feature_support",
        "context_tokens",
        "joined_identities",
        "readiness_security",
        "reconciliation",
    )
    categories = {
        name: {
            "status": (
                "PASS"
                if cases
                and all(case["categories"][name]["status"] == "PASS" for case in cases)
                else "FAIL"
            ),
            "failed_case_ids": sorted(
                case["case_id"]
                for case in cases
                if case["categories"][name]["status"] != "PASS"
            ),
        }
        for name in category_names
    }
    return {
        "status": (
            "PASS"
            if cases and all(case["status"] == "PASS" for case in cases)
            else "FAIL"
        ),
        "categories": categories,
        "cases": sorted(cases, key=lambda item: item["case_id"]),
    }


def _worst_status(values: Sequence[str]) -> str:
    for status in ("FAIL", "BLOCKED", "NOT_RUN"):
        if status in values:
            return status
    return "PASS"


def _aggregate_safety(runs: Sequence[_LoadedRun]) -> dict[str, dict[str, Any]]:
    totals = {
        name: {"failures": 0, "denominator": 0, "status": "NOT_RUN"}
        for name in SAFETY_COUNTERS
    }
    for run in runs:
        case_id = str(run.report["case_id"])
        counters = _object(run.report.get("safety_counters"), f"{case_id} safety")
        if set(counters) != set(SAFETY_COUNTERS):
            raise AggregateError(f"{case_id} safety counter set is invalid")
        expected_names = set(CASE_CONTRACTS[case_id].safety_counters)
        report_passed = run.report.get("status") == "PASS"
        for name in SAFETY_COUNTERS:
            counter = _object(counters[name], f"{case_id} {name}")
            failures = _nonnegative_int(
                counter.get("failures"), f"{case_id} {name} failures"
            )
            denominator = _nonnegative_int(
                counter.get("denominator"), f"{case_id} {name} denominator"
            )
            observed_status = _status(counter.get("status"), f"{case_id} {name}")
            expected_denominator = 1 if name in expected_names else 0
            permitted_denominators = (
                {expected_denominator} if report_passed else {0, expected_denominator}
            )
            if denominator not in permitted_denominators:
                raise AggregateError(f"{case_id} {name} denominator drift")
            correct_status = (
                "PASS"
                if denominator > 0 and failures == 0
                else "FAIL"
                if denominator > 0
                else "NOT_RUN"
            )
            if observed_status != correct_status:
                raise AggregateError(f"{case_id} {name} status is inconsistent")
            totals[name]["failures"] += failures
            totals[name]["denominator"] += denominator
    for total in totals.values():
        total["status"] = (
            "PASS" if total["failures"] == 0 and total["denominator"] > 0 else "FAIL"
        )
    return totals


def _aggregate_calls(runs: Sequence[_LoadedRun]) -> dict[str, Any]:
    totals = {
        "mcp": {"expected": 0, "observed": 0, "unaccounted": 0, "automatic_retries": 0},
        "provider": {
            "expected": 0,
            "observed": 0,
            "unaccounted": 0,
            "automatic_retries": 0,
            "per_turn_maximum": 1,
        },
    }
    input_statuses: list[str] = []
    evidence_complete = True
    for run in runs:
        case_id = str(run.report["case_id"])
        contract = CASE_CONTRACTS[case_id]
        calls = _object(run.report.get("calls"), f"{case_id} calls")
        for kind, expected in (
            ("mcp", contract.expected_mcp_calls),
            ("provider", contract.expected_provider_calls),
        ):
            record = _object(calls.get(kind), f"{case_id} {kind} calls")
            values = {
                name: _nonnegative_int(record.get(name), f"{case_id} {kind} {name}")
                for name in ("expected", "observed", "unaccounted")
            }
            if values["expected"] != expected:
                raise AggregateError(f"{case_id} {kind} expected-call drift")
            retry = record.get("automatic_retries")
            if retry is None and kind == "mcp":
                retry_value = 0
                totals[kind]["retry_evidence_source"] = "MANIFEST_CALL_POLICY"
            elif retry is None:
                evidence_complete = False
                retry_value = 0
            else:
                retry_value = _nonnegative_int(retry, f"{case_id} {kind} retries")
                totals[kind]["retry_evidence_source"] = "RUN_REPORT_COUNTER"
            totals[kind]["expected"] += values["expected"]
            totals[kind]["observed"] += values["observed"]
            totals[kind]["unaccounted"] += values["unaccounted"]
            totals[kind]["automatic_retries"] += retry_value
            input_statuses.append(
                _status(record.get("status"), f"{case_id} {kind} calls")
            )
        provider = _object(calls.get("provider"), f"{case_id} provider calls")
        if (
            provider.get("maximum_per_model_round") != 1
            or provider.get("model_rounds") != contract.expected_provider_calls
            or provider.get("calls_per_task_operation")
            != contract.expected_provider_calls
            or provider.get("case_maximum") != contract.expected_provider_calls
        ):
            evidence_complete = False
    clean = all(
        record["observed"] == record["expected"]
        and record["unaccounted"] == 0
        and record["automatic_retries"] == 0
        for record in totals.values()
    )
    totals["status"] = (
        "PASS"
        if evidence_complete and clean and _worst_status(input_statuses) == "PASS"
        else "FAIL"
    )
    totals["evidence_complete"] = evidence_complete
    return totals


def _nearest_rank(
    values: Sequence[int | float], percentile: float
) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _metric(
    values: Sequence[int | float],
    missing: Sequence[str],
    expected_count: int,
    unit: str,
) -> dict[str, Any]:
    return {
        "unit": unit,
        "sample_count": len(values),
        "expected_sample_count": expected_count,
        "missing_case_ids": sorted(missing),
        "p50": _nearest_rank(values, 0.50),
        "p95": _nearest_rank(values, 0.95),
        "p99": _nearest_rank(values, 0.99),
        "status": (
            "PASS"
            if not missing and len(values) == expected_count and expected_count > 0
            else "FAIL"
        ),
    }


def _aggregate_metrics(runs: Sequence[_LoadedRun]) -> dict[str, Any]:
    expected_count = len(REQUIRED_CASE_IDS)
    absent_cases = sorted(
        set(REQUIRED_CASE_IDS) - {str(run.report["case_id"]) for run in runs}
    )
    wall: list[int | float] = []
    context: list[int | float] = []
    missing_wall: list[str] = list(absent_cases)
    missing_context: list[str] = list(absent_cases)
    stage_values: dict[str, list[int | float]] = {name: [] for name in REQUIRED_STAGES}
    missing_stages: dict[str, list[str]] = {
        name: list(absent_cases) for name in REQUIRED_STAGES
    }
    for run in runs:
        case_id = str(run.report["case_id"])
        wall_value = _nonnegative_number(run.report.get("wall_latency_ms"))
        if wall_value is None:
            missing_wall.append(case_id)
        else:
            wall.append(wall_value)
        context_value = run.report.get("context_tokens")
        if (
            not isinstance(context_value, int)
            or isinstance(context_value, bool)
            or context_value < 0
        ):
            missing_context.append(case_id)
        else:
            context.append(context_value)
        stages = run.report.get("stage_latency_ms")
        if not isinstance(stages, Mapping):
            stages = {}
        for name in REQUIRED_STAGES:
            stage_value = _nonnegative_number(stages.get(name))
            if stage_value is None:
                missing_stages[name].append(case_id)
            else:
                stage_values[name].append(stage_value)
    return {
        "method": "DETERMINISTIC_NEAREST_RANK_CEIL_P_TIMES_N",
        "wall_latency_ms": _metric(wall, missing_wall, expected_count, "ms"),
        "context_tokens": _metric(context, missing_context, expected_count, "tokens"),
        "stage_latency_ms": {
            name: _metric(
                stage_values[name], missing_stages[name], expected_count, "ms"
            )
            for name in REQUIRED_STAGES
        },
    }


def _named_stages_pass(runs: Sequence[_LoadedRun], names: Sequence[str]) -> bool:
    for run in runs:
        case_id = str(run.report["case_id"])
        rows = run.report.get("stages")
        if not isinstance(rows, list):
            return False
        by_name = {
            row.get("stage"): row
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("stage"), str)
        }
        if any(
            name not in by_name or by_name[name].get("status") != "PASS"
            for name in names
        ):
            return False
        if any(
            _nonnegative_number(by_name[name].get("duration_ms")) is None
            for name in names
        ):
            raise AggregateError(f"{case_id} stage duration is invalid")
    return True


def _condition_status(*, fail: bool = False, missing: bool = False) -> str:
    if fail:
        return "FAIL"
    if missing:
        return "NOT_RUN"
    return "PASS"


def aggregate_reports(report_paths: Sequence[Path]) -> dict[str, Any]:
    runs = _load_runs(tuple(Path(path) for path in report_paths))
    observed = {str(run.report["case_id"]) for run in runs}
    required = set(REQUIRED_CASE_IDS)
    missing = sorted(required - observed)
    unexpected = sorted(observed - required)
    matrix_pass = not missing and not unexpected and len(runs) == len(REQUIRED_CASE_IDS)
    matrix = {
        "required": len(REQUIRED_CASE_IDS),
        "observed": len(runs),
        "missing_case_ids": missing,
        "unexpected_case_ids": unexpected,
        "status": "PASS" if matrix_pass else "NOT_RUN",
    }

    binding_reasons = sorted(
        {reason for run in runs for reason in run.manifest_reasons}
    )
    binding_digests = {
        hashlib.sha256(_canonical(run.manifest.get("bindings"))).hexdigest()
        for run in runs
        if isinstance(run.manifest.get("bindings"), Mapping)
    }
    if len(binding_digests) > 1:
        binding_reasons.append("CROSS_RUN_BINDING_DRIFT")
    manifest_binding = {
        "status": "PASS" if not binding_reasons else "FAIL",
        "case_count": len(runs),
        "binding_set_sha256": next(iter(binding_digests))
        if len(binding_digests) == 1
        else None,
        "reason_codes": binding_reasons,
    }

    safety = _aggregate_safety(runs)
    safety_pass = all(value["status"] == "PASS" for value in safety.values())
    calls = _aggregate_calls(runs)
    metrics = _aggregate_metrics(runs)
    evidence = _aggregate_evidence(runs)
    evidence_categories = evidence["categories"]
    metrics_pass = (
        metrics["wall_latency_ms"]["status"] == "PASS"
        and metrics["context_tokens"]["status"] == "PASS"
        and all(
            value["status"] == "PASS" for value in metrics["stage_latency_ms"].values()
        )
    )
    reports_pass = all(run.report["status"] == "PASS" for run in runs)
    readiness_stages_pass = _named_stages_pass(runs, ("start", "readiness"))
    stages_pass = _named_stages_pass(runs, REQUIRED_STAGES)
    cleanup_all_pass = (
        all(
            isinstance(run.report.get("cleanup"), Mapping)
            and run.report["cleanup"].get("status") == "PASS"
            and run.report["cleanup"].get("existing_vllm_preserved") is True
            and _is_sha256(run.report["cleanup"].get("recovery_plan_sha256"))
            for run in runs
        )
        and matrix_pass
    )
    retries_zero = all(
        calls[kind]["automatic_retries"] == 0 for kind in ("mcp", "provider")
    )

    intrinsic = {
        "U1-G0": _condition_status(
            fail=(
                manifest_binding["status"] != "PASS"
                or not reports_pass
                or (matrix_pass and not readiness_stages_pass)
                or evidence_categories["artifacts"]["status"] != "PASS"
                or evidence_categories["readiness_security"]["status"] != "PASS"
            ),
            missing=not matrix_pass,
        ),
        "U1-G1": _condition_status(
            fail=(
                not safety_pass
                or evidence_categories["readiness_security"]["status"] != "PASS"
            ),
        ),
        "U1-G2": _condition_status(
            fail=matrix_pass
            and (
                not reports_pass
                or not stages_pass
                or evidence_categories["artifacts"]["status"] != "PASS"
                or evidence_categories["context_tokens"]["status"] != "PASS"
            ),
            missing=not matrix_pass,
        ),
        "U1-G3": _condition_status(
            fail=matrix_pass
            and (
                not reports_pass
                or not stages_pass
                or evidence_categories["feature_support"]["status"] != "PASS"
                or evidence_categories["joined_identities"]["status"] != "PASS"
            ),
            missing=not matrix_pass,
        ),
        "U1-G4": _condition_status(
            fail=matrix_pass
            and (
                not cleanup_all_pass
                or not retries_zero
                or evidence_categories["fault_execution"]["status"] != "PASS"
                or evidence_categories["reconciliation"]["status"] != "PASS"
            ),
            missing=not matrix_pass,
        ),
        "U1-G5": _condition_status(
            fail=(
                calls["status"] != "PASS"
                or not metrics_pass
                or evidence_categories["joined_identities"]["status"] != "PASS"
                or evidence_categories["reconciliation"]["status"] != "PASS"
            ),
            missing=not matrix_pass,
        ),
    }
    gate_reasons = {
        "U1-G0": "CURRENT_EXACT_MANIFEST_AND_READINESS",
        "U1-G1": "CANONICAL_SECURITY_COUNTERS_0_OVER_N",
        "U1-G2": "FULL_REAL_VERTICAL_MATRIX",
        "U1-G3": "PROVIDER_AND_TASK_CONTRACT",
        "U1-G4": "FAILURE_LIFECYCLE_OPERATIONS_AND_CLEANUP",
        "U1-G5": "RECONCILIATION_COST_AND_PERCENTILES",
    }
    gates: dict[str, dict[str, Any]] = {}
    predecessors_pass = True
    for name in GATE_NAMES:
        effective = intrinsic[name] if predecessors_pass else "BLOCKED"
        gates[name] = {
            "status": effective,
            "intrinsic_status": intrinsic[name],
            "reason_code": (
                gate_reasons[name] if predecessors_pass else "PREDECESSOR_GATE_NOT_PASS"
            ),
        }
        predecessors_pass = predecessors_pass and effective == "PASS"

    all_gates_pass = all(gates[name]["status"] == "PASS" for name in GATE_NAMES)
    earned = all_gates_pass and cleanup_all_pass
    first_nonpass = next(
        (
            gates[name]["status"]
            for name in GATE_NAMES
            if gates[name]["status"] != "PASS"
        ),
        "PASS",
    )
    return {
        "schema": AGGREGATE_SCHEMA,
        "status": "PASS" if earned else first_nonpass,
        "product_usable": earned,
        "release_label": RELEASE_LABEL,
        "release_label_earned": earned,
        "input_mode": "EXPLICIT_REPORT_PATHS_ONLY",
        "inputs": [
            {
                "case_id": run.report["case_id"],
                "run_id": run.report["run_id"],
                "report_path": str(run.path),
                "report_sha256": _sha256(run.path),
            }
            for run in sorted(runs, key=lambda item: str(item.report["case_id"]))
        ],
        "matrix": matrix,
        "manifest_binding": manifest_binding,
        "evidence_validation": evidence,
        "safety_counters": safety,
        "calls": calls,
        "metrics": metrics,
        "cleanup": {
            "all_pass": cleanup_all_pass,
            "passed": sum(
                1
                for run in runs
                if isinstance(run.report.get("cleanup"), Mapping)
                and run.report["cleanup"].get("status") == "PASS"
                and run.report["cleanup"].get("existing_vllm_preserved") is True
                and _is_sha256(run.report["cleanup"].get("recovery_plan_sha256"))
            ),
            "denominator": len(REQUIRED_CASE_IDS),
            "status": "PASS" if cleanup_all_pass else "FAIL",
        },
        "gates": gates,
    }


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise AggregateError("output must be a regular file path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate explicit DG-13U U1 run reports"
    )
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = aggregate_reports(args.report)
    _atomic_write(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
