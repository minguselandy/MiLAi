"""Fail-closed authority for the bounded MVP-01 U0 warm-002 repair probe."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

AUTHORIZED_RUN_ID = "mvp01-u0-warm-repair-probe-20260901-002"
AUTHORIZED_RUN_LOCK = f"var/mvp01/{AUTHORIZED_RUN_ID}/run-lock.json"
SCOPE_IDENTITY = "MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE"
QUERY_CLASS_COUNT = 10
FIXTURE_EVENT_COUNT = 20
EVIDENCE_TOKEN_BUDGET = 8_192

FAILED_WARM_RUN_ID = "mvp01-u0-warm-20260901-002"
FAILED_WARM_STATUS = (
    "FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED"
)
FAILED_WARM_TERMINAL = Path(f"var/mvp01/{FAILED_WARM_RUN_ID}/terminal.json")
FAILED_WARM_TERMINAL_SHA256 = (
    "51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0"
)
FAILED_WARM_RESULTS = Path(f"var/mvp01/{FAILED_WARM_RUN_ID}/results.json")
FAILED_WARM_RESULTS_SHA256 = (
    "fb8958447c681d1cd80cd8f35085a831d4488804cca99e6b7b47196b077afc1d"
)
FAILED_WARM_CHECKPOINT = Path(
    f"var/mvp01/{FAILED_WARM_RUN_ID}/checkpoint/state.json"
)
FAILED_WARM_CHECKPOINT_SHA256 = (
    "31b37c8980932f822673c1b4672efccbc01bffe137a93b89b42cba23f0e38c18"
)
FAILED_WARM_RUN_LOCK = Path(f"var/mvp01/{FAILED_WARM_RUN_ID}/run-lock.json")
FAILED_WARM_RUN_LOCK_SHA256 = (
    "de720a2f713e944fdb64a5c73a155ff63bd1353ad7d53fa3369415fdb75cd301"
)

_COMMON_AUTHORITY = {
    "execution_authorized": "true",
    "execution_scope": "U0_WARM_002_FAILURE_REPAIR_PROBE",
    "active_case_scope": SCOPE_IDENTITY,
    "active_run_scope": SCOPE_IDENTITY,
    "active_run_lock": AUTHORIZED_RUN_LOCK,
    "authorized_synthetic_query_class_count": str(QUERY_CLASS_COUNT),
    "formal_warm_successor_authorized": "false",
    "authorized_benchmark_case_count": "0",
    "selection_metadata_access_authorized": "false",
    "benchmark_case_execution_authorized": "false",
    "reader_answer_judge_calls_authorized": "false",
    "formal_holdout_authorized": "false",
}
_MASTER_AUTHORITY = {
    "document_id": "MILA-ML-MASTER",
    "version": "2.1",
    "status": "ACTIVE_EXECUTION_MASTER",
    "development_control": "MVP01_U0_WARM_002_FAILURE_REPAIR",
    "active_goal": "MILA-MVP-01@0.1",
    "active_block": "MILA-MVP-U0",
    **_COMMON_AUTHORITY,
    "latest_block_artifact": str(FAILED_WARM_TERMINAL),
    "latest_block_artifact_sha256": FAILED_WARM_TERMINAL_SHA256,
    "latest_block_status": FAILED_WARM_STATUS,
    "latest_block_results_sha256": FAILED_WARM_RESULTS_SHA256,
    "latest_block_checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
    "latest_block_run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
    "latest_block_audit_status": "NO_GO_SUCCESSOR_REPAIR_REQUIRED",
    "next_authority_required": "INDEPENDENT_AUDITOR_GO_AFTER_10_CLASS_REPAIR_PROBE",
}
_GOAL_AUTHORITY = {
    "document_id": "MILA-MVP-01",
    "version": "0.1",
    "status": "ACTIVE_U0_WARM_002_FAILURE_REPAIR",
    "authority_snapshot": "MILA-ML-MASTER@2.1",
    "active_stage": "U0",
    **_COMMON_AUTHORITY,
    "latest_u0_warm_terminal": str(FAILED_WARM_TERMINAL),
    "latest_u0_warm_terminal_sha256": FAILED_WARM_TERMINAL_SHA256,
    "latest_u0_warm_status": FAILED_WARM_STATUS,
    "latest_u0_warm_results_sha256": FAILED_WARM_RESULTS_SHA256,
    "latest_u0_warm_checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
    "latest_u0_warm_run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
    "latest_u0_warm_audit_status": "NO_GO_SUCCESSOR_REPAIR_REQUIRED",
    "product_default_enable_authorized": "false",
    "canonical_schema_change_authorized": "false",
    "public_mcp_change_authorized": "false",
}


class U0WarmRepairContractError(RuntimeError):
    """The exact repair-probe authority or failed predecessor drifted."""


@dataclass(frozen=True, slots=True)
class RepairProbeAuthorityReceipt:
    master_sha256: str
    goal_sha256: str
    scope: str = SCOPE_IDENTITY
    query_class_count: int = QUERY_CLASS_COUNT
    benchmark_case_count: int = 0
    reader_answer_judge_calls: int = 0
    formal_holdout_consumed: bool = False
    formal_warm_successor_authorized: bool = False


def assert_repair_probe_authorized(
    *, master_path: Path, goal_path: Path
) -> RepairProbeAuthorityReceipt:
    master = _frontmatter(master_path)
    goal = _frontmatter(goal_path)
    _require_authority(master, _MASTER_AUTHORITY, "Master")
    _require_authority(goal, _GOAL_AUTHORITY, "Goal")
    return RepairProbeAuthorityReceipt(
        master_sha256=_sha256(master_path),
        goal_sha256=_sha256(goal_path),
    )


def assert_failed_warm_002(project_root: Path) -> dict[str, object]:
    run_lock = _sealed_json(
        project_root, FAILED_WARM_RUN_LOCK, FAILED_WARM_RUN_LOCK_SHA256, "002 run lock"
    )
    _require_facts(
        run_lock,
        {
            "schema_version": "mila-mvp01-u0-warm-run-lock-v0.3",
            "run_id": FAILED_WARM_RUN_ID,
        },
        "002 run lock",
    )
    checkpoint = _sealed_json(
        project_root,
        FAILED_WARM_CHECKPOINT,
        FAILED_WARM_CHECKPOINT_SHA256,
        "002 checkpoint",
    )
    _require_facts(
        checkpoint,
        {
            "schema_version": "mila-mvp01-u0-warm-checkpoint-v0.3",
            "run_id": FAILED_WARM_RUN_ID,
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "phase": "LIFECYCLE_TERMINAL",
            "runtime_attempt_count": 1,
            "interruption_count": 0,
        },
        "002 checkpoint",
    )
    results = _sealed_json(
        project_root, FAILED_WARM_RESULTS, FAILED_WARM_RESULTS_SHA256, "002 results"
    )
    _require_facts(
        results,
        {
            "schema_version": "mila-mvp01-u0-warm-results-v0.3",
            "run_id": FAILED_WARM_RUN_ID,
            "status": "FAIL",
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
            "request_count": 100,
            "logical_attempt_count": 100,
            "runtime_attempt_count": 1,
            "interruption_count": 0,
            "evidence_archive_count": 90,
            "benchmark_case_count": 0,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
            "formal_holdout_consumed": False,
        },
        "002 results",
    )
    terminal = _sealed_json(
        project_root,
        FAILED_WARM_TERMINAL,
        FAILED_WARM_TERMINAL_SHA256,
        "002 terminal",
    )
    _require_facts(
        terminal,
        {
            "schema_version": "mila-mvp01-u0-warm-terminal-v0.3",
            "run_id": FAILED_WARM_RUN_ID,
            "status": FAILED_WARM_STATUS,
            "block_complete": False,
            "goal_complete": False,
            "request_count": 100,
            "logical_attempt_count": 100,
            "runtime_attempt_count": 1,
            "interruption_count": 0,
            "context_terminal_count": 0,
            "evidence_archive_count": 90,
            "reader_answer_judge_calls": 0,
            "formal_holdout_consumed": False,
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
            "results_sha256": FAILED_WARM_RESULTS_SHA256,
        },
        "002 terminal",
    )
    return {
        "run_id": FAILED_WARM_RUN_ID,
        "status": terminal["status"],
        "terminal": {
            "path": str(FAILED_WARM_TERMINAL),
            "sha256": FAILED_WARM_TERMINAL_SHA256,
        },
        "results": {
            "path": str(FAILED_WARM_RESULTS),
            "sha256": FAILED_WARM_RESULTS_SHA256,
        },
        "checkpoint": {
            "path": str(FAILED_WARM_CHECKPOINT),
            "sha256": FAILED_WARM_CHECKPOINT_SHA256,
        },
        "run_lock": {
            "path": str(FAILED_WARM_RUN_LOCK),
            "sha256": FAILED_WARM_RUN_LOCK_SHA256,
        },
    }


def _sealed_json(
    project_root: Path,
    relative_path: Path,
    expected_sha256: str,
    label: str,
) -> dict[str, object]:
    path = project_root / relative_path
    if not path.is_file() or _sha256(path) != expected_sha256:
        raise U0WarmRepairContractError(f"{label} is absent or its digest drifted")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise U0WarmRepairContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise U0WarmRepairContractError(f"{label} is not an object")
    return value


def _require_facts(
    value: Mapping[str, object], expected: Mapping[str, object], label: str
) -> None:
    drift = {
        key: {"expected": expected_value, "actual": value.get(key)}
        for key, expected_value in expected.items()
        if value.get(key) != expected_value
    }
    if drift:
        raise U0WarmRepairContractError(f"{label} facts drifted: {drift}")


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise U0WarmRepairContractError(
            f"cannot read authority document: {path}"
        ) from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise U0WarmRepairContractError(f"authority frontmatter is missing: {path}")
    body = text[4:].split("\n---\n", 1)[0]
    values: dict[str, str] = {}
    for line in body.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().strip('"').strip("'")
        if value:
            values[key] = value
    return values


def _require_authority(
    actual: Mapping[str, str], expected: Mapping[str, str], label: str
) -> None:
    drift = {
        key: {"expected": expected_value, "actual": actual.get(key)}
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    }
    if drift:
        raise U0WarmRepairContractError(
            f"{label} does not authorize {SCOPE_IDENTITY}: {drift}"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "AUTHORIZED_RUN_ID",
    "AUTHORIZED_RUN_LOCK",
    "EVIDENCE_TOKEN_BUDGET",
    "FIXTURE_EVENT_COUNT",
    "QUERY_CLASS_COUNT",
    "SCOPE_IDENTITY",
    "RepairProbeAuthorityReceipt",
    "U0WarmRepairContractError",
    "assert_failed_warm_002",
    "assert_repair_probe_authorized",
]
