"""Exact authority contract for the MVP-01 U0 24-case context-only canary."""

from __future__ import annotations

from pathlib import Path

from evals.gdpm.b0_canary_contract import (
    CanaryAuthorityReceipt,
    assert_canary_authorized,
)

AUTHORIZED_RUN_ID = "mvp01-u0-20260901-017"
AUTHORIZED_RUN_LOCK = f"var/mvp01/{AUTHORIZED_RUN_ID}/run-lock.json"
SCOPE_IDENTITY = "MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY"
EVIDENCE_TOKEN_BUDGET = 8192

_COMMON_AUTHORITY = {
    "execution_authorized": "true",
    "execution_scope": "U0_24_CASE_CONTEXT_ONLY_CANARY",
    "active_case_scope": SCOPE_IDENTITY,
    "active_run_scope": SCOPE_IDENTITY,
    "active_run_lock": AUTHORIZED_RUN_LOCK,
    "authorized_benchmark_case_count": "24",
    "selection_metadata_access_authorized": "true",
    "benchmark_case_execution_authorized": "true",
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
}
_GOAL_AUTHORITY = {
    "document_id": "MILA-MVP-01",
    "version": "0.1",
    "status": "ACTIVE_U0_24_CASE_CONTEXT_ONLY_CANARY",
    "authority_snapshot": "MILA-ML-MASTER@2.1",
    "active_stage": "U0",
    **_COMMON_AUTHORITY,
    "product_default_enable_authorized": "false",
    "canonical_schema_change_authorized": "false",
    "public_mcp_change_authorized": "false",
}


def assert_mvp01_u0_canary_authorized(
    *, master_path: Path, goal_path: Path
) -> CanaryAuthorityReceipt:
    """Fail closed unless Master and MVP Goal authorize exactly this U0 run."""

    return assert_canary_authorized(
        master_path=master_path,
        goal_path=goal_path,
        master_authority=_MASTER_AUTHORITY,
        goal_authority=_GOAL_AUTHORITY,
        scope=SCOPE_IDENTITY,
    )


def required_authority_delta() -> dict[str, dict[str, str]]:
    """Return the exact scalar authority profile required by this canary."""

    return {
        "master": dict(_MASTER_AUTHORITY),
        "goal": dict(_GOAL_AUTHORITY),
    }


__all__ = [
    "AUTHORIZED_RUN_ID",
    "AUTHORIZED_RUN_LOCK",
    "EVIDENCE_TOKEN_BUDGET",
    "SCOPE_IDENTITY",
    "assert_mvp01_u0_canary_authorized",
    "required_authority_delta",
]
