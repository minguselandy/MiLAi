"""Exact authority contract for the MVP-01 U0 100-request warm soak."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

AUTHORIZED_RUN_ID = "mvp01-u0-warm-20260901-002"
AUTHORIZED_RUN_LOCK = f"var/mvp01/{AUTHORIZED_RUN_ID}/run-lock.json"
SCOPE_IDENTITY = "MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK"
REQUEST_COUNT = 100
EVIDENCE_TOKEN_BUDGET = 8192
PREVIOUS_GATE = Path("var/mvp01/mvp01-u0-20260901-017/terminal.json")
PREVIOUS_GATE_SHA256 = (
    "ba9fedb8ce69c82a927bc57620302391d52dfaaa1f4dd8c54383f610cf79f38a"
)
PREVIOUS_GATE_STATUS = "PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY"
FAILED_WARM_GATE = Path("var/mvp01/mvp01-u0-warm-20260901-001/terminal.json")
FAILED_WARM_GATE_SHA256 = (
    "babf44c832e77c36940293dc4e80f8360adf862db331eb531c36925952893fef"
)
FAILED_WARM_GATE_STATUS = (
    "FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED"
)
FAILED_WARM_RESULTS = Path("var/mvp01/mvp01-u0-warm-20260901-001/results.json")
FAILED_WARM_RESULTS_SHA256 = (
    "90f8bbb4091af371a9940fd4fbb5bd814ffff44a7e8b092259e7293b9820740e"
)
FAILED_WARM_CHECKPOINT = Path(
    "var/mvp01/mvp01-u0-warm-20260901-001/checkpoint/state.json"
)
FAILED_WARM_CHECKPOINT_SHA256 = (
    "b4dcb90829c83a25fd26fcdae301ef2571ddc1908e9bd761dada2b71173bf089"
)
FAILED_WARM_RUN_LOCK = Path("var/mvp01/mvp01-u0-warm-20260901-001/run-lock.json")
FAILED_WARM_RUN_LOCK_SHA256 = (
    "5a60715910008bd7445d3f7d43c61c61c92fffde0aefb074627f3d584819cc72"
)
REPAIR_PROBE_GATE = Path(
    "var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/terminal.json"
)
REPAIR_PROBE_GATE_SHA256 = (
    "a4b8331d0666824407693a44de9349e69750c5628691169e6e0022505266f775"
)
REPAIR_PROBE_GATE_STATUS = "PASS_MVP01_U0_WARM_REPAIR_PRODUCTION_PATH_PROBE"
REPAIR_PROBE_RESULTS = Path(
    "var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/results.json"
)
REPAIR_PROBE_RESULTS_SHA256 = (
    "c52bf2496e5492132a49d128f4a3597f83bbff87bae67fb9db7f0fccc3f02c0c"
)

_COMMON_AUTHORITY = {
    "execution_authorized": "true",
    "execution_scope": "U0_100_REQUEST_WARM_RELIABILITY_SOAK",
    "active_case_scope": SCOPE_IDENTITY,
    "active_run_scope": SCOPE_IDENTITY,
    "active_run_lock": AUTHORIZED_RUN_LOCK,
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
    "active_goal": "MILA-MVP-01@0.1",
    "active_block": "MILA-MVP-U0",
    **_COMMON_AUTHORITY,
    "latest_block_artifact": str(FAILED_WARM_GATE),
    "latest_block_artifact_sha256": FAILED_WARM_GATE_SHA256,
    "latest_block_status": FAILED_WARM_GATE_STATUS,
    "latest_passed_block_artifact": str(PREVIOUS_GATE),
    "latest_passed_block_artifact_sha256": PREVIOUS_GATE_SHA256,
    "latest_passed_block_status": PREVIOUS_GATE_STATUS,
    "latest_repair_probe_artifact": str(REPAIR_PROBE_GATE),
    "latest_repair_probe_artifact_sha256": REPAIR_PROBE_GATE_SHA256,
    "latest_repair_probe_status": REPAIR_PROBE_GATE_STATUS,
}
_GOAL_AUTHORITY = {
    "document_id": "MILA-MVP-01",
    "version": "0.1",
    "status": "ACTIVE_U0_100_REQUEST_WARM_RELIABILITY_SOAK",
    "authority_snapshot": "MILA-ML-MASTER@2.1",
    "active_stage": "U0",
    **_COMMON_AUTHORITY,
    "latest_u0_canary_terminal": str(PREVIOUS_GATE),
    "latest_u0_canary_terminal_sha256": PREVIOUS_GATE_SHA256,
    "latest_u0_canary_status": PREVIOUS_GATE_STATUS,
    "latest_u0_warm_terminal": str(FAILED_WARM_GATE),
    "latest_u0_warm_terminal_sha256": FAILED_WARM_GATE_SHA256,
    "latest_u0_warm_status": FAILED_WARM_GATE_STATUS,
    "latest_u0_warm_repair_probe_terminal": str(REPAIR_PROBE_GATE),
    "latest_u0_warm_repair_probe_terminal_sha256": REPAIR_PROBE_GATE_SHA256,
    "latest_u0_warm_repair_probe_status": REPAIR_PROBE_GATE_STATUS,
    "product_default_enable_authorized": "false",
    "canonical_schema_change_authorized": "false",
    "public_mcp_change_authorized": "false",
}


class U0WarmContractError(RuntimeError):
    """The exact warm-soak authority or predecessor gate failed closed."""


@dataclass(frozen=True, slots=True)
class WarmAuthorityReceipt:
    master_sha256: str
    goal_sha256: str
    scope: str = SCOPE_IDENTITY
    request_count: int = REQUEST_COUNT
    benchmark_case_count: int = 0
    reader_answer_judge_calls: int = 0
    formal_holdout_consumed: bool = False


def assert_mvp01_u0_warm_authorized(
    *, master_path: Path, goal_path: Path
) -> WarmAuthorityReceipt:
    """Fail closed unless Master and Goal authorize exactly this warm run."""

    master = _frontmatter(master_path)
    goal = _frontmatter(goal_path)
    _require_authority(master, _MASTER_AUTHORITY, "Master")
    _require_authority(goal, _GOAL_AUTHORITY, "Goal")
    return WarmAuthorityReceipt(
        master_sha256=_sha256(master_path),
        goal_sha256=_sha256(goal_path),
    )


def assert_previous_u0_gate(project_root: Path) -> dict[str, object]:
    """Verify PASS, immediate FAIL, and repair-probe predecessor lineage."""

    passed = _sealed_json(
        project_root=project_root,
        relative_path=PREVIOUS_GATE,
        expected_sha256=PREVIOUS_GATE_SHA256,
        label="previous passed U0 terminal",
    )
    _require_facts(
        passed,
        {
            "status": PREVIOUS_GATE_STATUS,
            "case_count": 24,
            "reader_answer_judge_calls": 0,
            "formal_holdout_consumed": False,
        },
        "previous passed U0 terminal",
    )

    failed_run_lock = _sealed_json(
        project_root=project_root,
        relative_path=FAILED_WARM_RUN_LOCK,
        expected_sha256=FAILED_WARM_RUN_LOCK_SHA256,
        label="failed warm run lock",
    )
    _require_facts(
        failed_run_lock,
        {
            "schema_version": "mila-mvp01-u0-warm-run-lock-v0.1",
            "run_id": "mvp01-u0-warm-20260901-001",
        },
        "failed warm run lock",
    )
    failed_checkpoint = _sealed_json(
        project_root=project_root,
        relative_path=FAILED_WARM_CHECKPOINT,
        expected_sha256=FAILED_WARM_CHECKPOINT_SHA256,
        label="failed warm checkpoint",
    )
    _require_facts(
        failed_checkpoint,
        {
            "schema_version": "mila-mvp01-u0-warm-checkpoint-v0.2",
            "run_id": "mvp01-u0-warm-20260901-001",
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "phase": "LIFECYCLE_TERMINAL",
            "runtime_attempt_count": 1,
            "interruption_count": 0,
        },
        "failed warm checkpoint",
    )
    failed_results = _sealed_json(
        project_root=project_root,
        relative_path=FAILED_WARM_RESULTS,
        expected_sha256=FAILED_WARM_RESULTS_SHA256,
        label="failed warm results",
    )
    _require_facts(
        failed_results,
        {
            "schema_version": "mila-mvp01-u0-warm-results-v0.2",
            "run_id": "mvp01-u0-warm-20260901-001",
            "status": "FAIL",
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
            "request_count": 100,
            "logical_attempt_count": 0,
            "runtime_attempt_count": 1,
            "interruption_count": 0,
            "evidence_archive_count": 0,
            "benchmark_case_count": 0,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
            "formal_holdout_consumed": False,
        },
        "failed warm results",
    )
    failed = _sealed_json(
        project_root=project_root,
        relative_path=FAILED_WARM_GATE,
        expected_sha256=FAILED_WARM_GATE_SHA256,
        label="immediate failed warm terminal",
    )
    _require_facts(
        failed,
        {
            "schema_version": "mila-mvp01-u0-warm-terminal-v0.2",
            "run_id": "mvp01-u0-warm-20260901-001",
            "status": FAILED_WARM_GATE_STATUS,
            "block_complete": False,
            "goal_complete": False,
            "next_active_scope": "U0_100_REQUEST_WARM_RELIABILITY_REPAIR",
            "request_count": 100,
            "logical_attempt_count": 0,
            "runtime_attempt_count": 1,
            "interruption_count": 0,
            "context_terminal_count": 0,
            "context_terminal_rate": 0,
            "evidence_archive_count": 0,
            "reader_answer_judge_calls": 0,
            "formal_holdout_consumed": False,
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
            "results_sha256": FAILED_WARM_RESULTS_SHA256,
        },
        "immediate failed warm terminal",
    )

    probe_results = _sealed_json(
        project_root=project_root,
        relative_path=REPAIR_PROBE_RESULTS,
        expected_sha256=REPAIR_PROBE_RESULTS_SHA256,
        label="warm repair probe results",
    )
    _require_facts(
        probe_results,
        {
            "schema_version": "mila-mvp01-u0-warm-repair-probe-v0.1",
            "run_id": "mvp01-u0-warm-repair-probe-20260901-001",
            "status": "PASS",
            "benchmark_case_count": 0,
            "formal_holdout_consumed": False,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
        },
        "warm repair probe results",
    )
    probe = _sealed_json(
        project_root=project_root,
        relative_path=REPAIR_PROBE_GATE,
        expected_sha256=REPAIR_PROBE_GATE_SHA256,
        label="warm repair probe terminal",
    )
    _require_facts(
        probe,
        {
            "schema_version": ("mila-mvp01-u0-warm-repair-probe-terminal-v0.1"),
            "run_id": "mvp01-u0-warm-repair-probe-20260901-001",
            "status": REPAIR_PROBE_GATE_STATUS,
            "formal_holdout_consumed": False,
            "reader_answer_judge_calls": 0,
            "results_sha256": REPAIR_PROBE_RESULTS_SHA256,
        },
        "warm repair probe terminal",
    )
    return {
        "passed_canary": {
            "path": str(PREVIOUS_GATE),
            "sha256": PREVIOUS_GATE_SHA256,
            "status": passed["status"],
            "case_count": passed["case_count"],
        },
        "immediate_failed_warm": {
            "path": str(FAILED_WARM_GATE),
            "sha256": FAILED_WARM_GATE_SHA256,
            "status": failed["status"],
            "request_count": failed["request_count"],
            "logical_attempt_count": failed["logical_attempt_count"],
            "runtime_attempt_count": failed["runtime_attempt_count"],
            "reader_answer_judge_calls": failed["reader_answer_judge_calls"],
            "formal_holdout_consumed": failed["formal_holdout_consumed"],
            "run_lock_sha256": FAILED_WARM_RUN_LOCK_SHA256,
            "checkpoint_sha256": FAILED_WARM_CHECKPOINT_SHA256,
            "results_sha256": FAILED_WARM_RESULTS_SHA256,
        },
        "repair_probe": {
            "path": str(REPAIR_PROBE_GATE),
            "sha256": REPAIR_PROBE_GATE_SHA256,
            "status": probe["status"],
            "results_sha256": REPAIR_PROBE_RESULTS_SHA256,
        },
    }


def _sealed_json(
    *,
    project_root: Path,
    relative_path: Path,
    expected_sha256: str,
    label: str,
) -> dict[str, object]:
    path = project_root / relative_path
    if not path.is_file():
        raise U0WarmContractError(f"{label} is absent: {path}")
    if _sha256(path) != expected_sha256:
        raise U0WarmContractError(f"{label} digest drifted")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise U0WarmContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise U0WarmContractError(f"{label} is not an object")
    return value


def _require_facts(
    value: Mapping[str, object],
    expected: Mapping[str, object],
    label: str,
) -> None:
    drift = {
        key: {"expected": expected_value, "actual": value.get(key)}
        for key, expected_value in expected.items()
        if value.get(key) != expected_value
    }
    if drift:
        raise U0WarmContractError(f"{label} facts drifted: {drift}")


def required_authority_delta() -> dict[str, dict[str, str]]:
    """Return the exact scalar authority profile required by this warm run."""

    return {
        "master": dict(_MASTER_AUTHORITY),
        "goal": dict(_GOAL_AUTHORITY),
    }


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise U0WarmContractError(f"cannot read authority document: {path}") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise U0WarmContractError(f"authority frontmatter is missing: {path}")
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
    actual: dict[str, str], expected: dict[str, str], label: str
) -> None:
    drift = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if drift:
        raise U0WarmContractError(
            f"{label} does not authorize {SCOPE_IDENTITY}: {drift}"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "AUTHORIZED_RUN_ID",
    "AUTHORIZED_RUN_LOCK",
    "EVIDENCE_TOKEN_BUDGET",
    "FAILED_WARM_CHECKPOINT",
    "FAILED_WARM_CHECKPOINT_SHA256",
    "FAILED_WARM_GATE",
    "FAILED_WARM_GATE_SHA256",
    "FAILED_WARM_GATE_STATUS",
    "FAILED_WARM_RESULTS",
    "FAILED_WARM_RESULTS_SHA256",
    "FAILED_WARM_RUN_LOCK",
    "FAILED_WARM_RUN_LOCK_SHA256",
    "PREVIOUS_GATE",
    "PREVIOUS_GATE_SHA256",
    "PREVIOUS_GATE_STATUS",
    "REPAIR_PROBE_GATE",
    "REPAIR_PROBE_GATE_SHA256",
    "REPAIR_PROBE_GATE_STATUS",
    "REPAIR_PROBE_RESULTS",
    "REPAIR_PROBE_RESULTS_SHA256",
    "REQUEST_COUNT",
    "SCOPE_IDENTITY",
    "U0WarmContractError",
    "WarmAuthorityReceipt",
    "assert_mvp01_u0_warm_authorized",
    "assert_previous_u0_gate",
    "required_authority_delta",
]
