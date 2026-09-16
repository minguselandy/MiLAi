"""Build the additive DG-18 provider-RCA calibration and completion audit receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PYTHON = ROOT / "runtime/.venv/bin/python"
RUNTIME_RUFF = ROOT / "runtime/.venv/bin/ruff"
RUNTIME_MYPY = ROOT / "runtime/.venv/bin/mypy"
GOAL = ROOT / "MiLAi_DG-18_受限残差再查找与证据可达性优化_GOALS.md"
RUNBOOK = ROOT / "docs/dg18/runtime-architecture-and-operator-runbook.md"
CONFORMANCE_ROOT = (
    ROOT
    / "var/dg18/provider-conformance/dg18-provider-conformance-20260828-002"
)
HISTORICAL_IDENTITIES = {
    "terminal": (
        ROOT / "var/dg18/final/dg18-terminal-receipt-20260828-001.json",
        "fef64a133938089cb929008c7a4a22adfff858de8f7490a38d250d3e154afce0",
    ),
    "r3_001": (
        ROOT / "var/dg18/r3/dg18-r3-residual-shadow-20260828-001/receipt.json",
        "02ea27f0e821d0a34e092ef91ab55083c94f030387ae129514db9a14518d1922",
    ),
    "r3_002": (
        ROOT / "var/dg18/r3/dg18-r3-residual-shadow-20260828-002/receipt.json",
        "9527cd60817c1b57d2706ffe2207dd44a93f3b4edd4d36531342b8e768b3d1e7",
    ),
}
SOURCE_FILES = (
    ROOT / "runtime/src/milai/domain/residual_refinding.py",
    ROOT / "runtime/src/milai/application/residual_refinding.py",
    ROOT / "runtime/src/milai/application/semantic_hint.py",
    ROOT / "runtime/src/milai/adapters/semantic_hint.py",
    ROOT / "evals/dg18/residual_shadow.py",
    ROOT / "scripts/run_dg18_provider_conformance.py",
    ROOT / "scripts/run_dg18_r3_shadow.py",
)
TEST_FILES = (
    ROOT / "runtime/tests/unit/test_dg18_residual_refinding.py",
    ROOT / "runtime/tests/unit/test_dg18_provider_transport.py",
    ROOT / "tests/test_dg18_r0_baseline.py",
    ROOT / "tests/test_dg18_residual_shadow.py",
)


class CalibrationError(RuntimeError):
    """One provider-RCA calibration invariant was not proven."""


def build(*, output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError("calibration receipt exists; choose a fresh path")
    historical: dict[str, dict[str, str]] = {}
    for name, (path, expected_sha256) in HISTORICAL_IDENTITIES.items():
        identity = _identity(path)
        _require(
            identity["sha256"] == expected_sha256,
            f"historical DG-18 receipt changed: {name}",
        )
        historical[name] = identity
    terminal = _load_json(HISTORICAL_IDENTITIES["terminal"][0])
    _require(
        terminal.get("disposition") == "PARKED_NO_GENERALIZABLE_RESIDUAL_GAIN",
        "historical terminal disposition is not preserved",
    )

    conformance_path = CONFORMANCE_ROOT / "receipt.json"
    matrix_path = CONFORMANCE_ROOT / "matrix.json"
    sse_path = CONFORMANCE_ROOT / "typed-sse-error-receipt.json"
    conformance = _load_json(conformance_path)
    matrix = _load_json(matrix_path)
    sse = _load_json(sse_path)
    _require(
        conformance.get("status") == "PASS_PROVIDER_CONFORMANCE",
        "provider conformance did not pass",
    )
    _require(matrix.get("status") == "PASS", "provider matrix did not pass")
    _require(
        matrix.get("application_schema_forbidden_keywords_absent") is True,
        "application wire schema retains an unsupported keyword",
    )
    summary = matrix.get("summary")
    _require(isinstance(summary, dict), "provider matrix summary is missing")
    _require(summary.get("flat_cell_pass_count") == 6, "flat matrix is incomplete")
    _require(summary.get("pydantic_parse_count") == 4, "Pydantic parse count drifted")
    _require(summary.get("runtime_accepted_count") == 4, "Runtime acceptance drifted")
    _require(
        summary.get("negative_error_classification_pass_count") == 2,
        "negative transport classification did not pass",
    )
    diagnostic = sse.get("diagnostic")
    _require(isinstance(diagnostic, dict), "typed SSE diagnostic is missing")
    _require(
        sse.get("status") == "PASS_TYPED_SSE_ERROR_CLASSIFICATION"
        and diagnostic.get("ProviderSSEErrorObserved") is True
        and diagnostic.get("ProviderErrorClassificationCorrect") is True
        and diagnostic.get("validation_error_type")
        == "SEMANTIC_HINT_PROVIDER_SSE_ERROR",
        "top-level SSE error is not correctly classified",
    )

    failed_gate_path = ROOT / "var/dg18/final/dg18-runtime-full-gate-20260828-003.json"
    passed_gate_path = ROOT / "var/dg18/final/dg18-runtime-full-gate-20260828-004.json"
    failed_gate = _load_json(failed_gate_path)
    passed_gate = _load_json(passed_gate_path)
    _require(
        failed_gate.get("status") == "FAIL"
        and failed_gate.get("pytest_passed") == 515
        and _nested(failed_gate, "cleanup", "status") == "PASS",
        "failed gate attempt is not preserved with clean teardown",
    )
    _require(
        passed_gate.get("status") == "PASS"
        and passed_gate.get("pytest_passed") == 516
        and _nested(passed_gate, "cleanup", "status") == "PASS",
        "fresh PostgreSQL Runtime gate did not pass",
    )

    goal_text = GOAL.read_text(encoding="utf-8")
    runbook_text = RUNBOOK.read_text(encoding="utf-8")
    scorer_text = (ROOT / "evals/dg18/residual_shadow.py").read_text(encoding="utf-8")
    r3_runner_text = (ROOT / "scripts/run_dg18_r3_shadow.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "PARKED_PROVIDER_CONTRACT_INCOMPATIBLE",
        "RESIDUAL_EFFECT_NOT_EVALUATED",
        "TREATMENT_NOT_DELIVERED",
    ):
        _require(required in goal_text and required in runbook_text, f"missing {required}")
    _require(
        "MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT" in scorer_text,
        "scorer mediator-effect outcome is absent",
    )
    _require(
        "--provider-conformance-receipt" in r3_runner_text
        and "--treatment-delivery-receipt" in r3_runner_text,
        "full R3 LME entry gates are not executable",
    )

    verification = {
        "focused_pytest": _run_check(
            [
                str(RUNTIME_PYTHON),
                "-m",
                "pytest",
                "-q",
                "tests/test_dg18_r0_baseline.py",
                "tests/test_dg18_residual_shadow.py",
            ],
            passed_pattern=r"(\d+) passed",
        ),
        "ruff": _run_check(
            [
                str(RUNTIME_RUFF),
                "check",
                "runtime/src",
                "runtime/tests/unit",
                "evals/dg18",
                "scripts/run_dg18_provider_conformance.py",
                "scripts/run_dg18_r3_shadow.py",
                "scripts/build_dg18_provider_rca_calibration.py",
                "tests/test_dg18_r0_baseline.py",
                "tests/test_dg18_residual_shadow.py",
            ]
        ),
        "strict_mypy": _run_check(
            [str(RUNTIME_MYPY), "--strict", "runtime/src/milai"],
            passed_pattern=r"Success: no issues found in (\d+) source files",
        ),
    }
    receipt = {
        "schema": "milai.dg18.provider-rca-calibration-receipt.v0.1",
        "status": "PASS_PROVIDER_RCA_CALIBRATION",
        "created_at": datetime.now(UTC).isoformat(),
        "goal_identity": _identity(GOAL),
        "goal_version": "0.2.1 PROVIDER RCA",
        "formal_holdout_consumed": False,
        "lme_rerun": False,
        "provider_restarted_or_reconfigured": False,
        "automatic_retry_count": 0,
        "historical_receipts_preserved": historical,
        "historical_terminal_disposition_preserved": (
            "PARKED_NO_GENERALIZABLE_RESIDUAL_GAIN"
        ),
        "analytical_calibration": {
            "treatment_delivery_outcome": "TREATMENT_NOT_DELIVERED",
            "disposition": "PARKED_PROVIDER_CONTRACT_INCOMPATIBLE",
            "residual_effect_outcome": "RESIDUAL_EFFECT_NOT_EVALUATED",
            "r3_001_validation_field_path": "UNKNOWN",
            "r3_002_root_cause": "PROVIDER_STRUCTURED_SCHEMA_UNSUPPORTED_UNIQUE_ITEMS",
            "historical_streaming_misclassification": (
                "SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT"
            ),
            "corrected_streaming_classification": (
                "SEMANTIC_HINT_PROVIDER_SSE_ERROR"
            ),
        },
        "successor_contract": {
            "wire_schema": "ResidualCueProposal v0.1",
            "provider_conformance": _identity(conformance_path),
            "matrix": _identity(matrix_path),
            "typed_sse_error": _identity(sse_path),
            "flat_transport_cells_passed": 6,
            "runtime_accepted_conformance_cells": 4,
        },
        "verification": {
            **verification,
            "fresh_postgresql_gate_failed_attempt_preserved": _identity(
                failed_gate_path
            ),
            "fresh_postgresql_gate": _identity(passed_gate_path),
            "fresh_postgresql_tests_passed": 516,
        },
        "implementation_identities": {
            "sources": [_identity(path) for path in SOURCE_FILES],
            "tests": [_identity(path) for path in TEST_FILES],
            "runbook": _identity(RUNBOOK),
        },
        "phase_status": {
            "R0": "PASS_HISTORICAL_BASELINE_PRESERVED",
            "R1": "PASS_PACKING_LOSS_ZERO",
            "R2": "PASS_TYPED_ACQUISITION_STATE",
            "R3": "HISTORICAL_TREATMENT_NOT_DELIVERED_EFFECT_NOT_EVALUATED",
            "R4": "NOT_EXECUTED_NOT_AUTHORIZED",
            "R5": "NOT_EXECUTED_PARKED_NOT_NEEDED",
        },
        "release": {
            "residual_refinding_label_granted": False,
            "runtime": "CANDIDATE",
            "schema": "EXPERIMENTAL / NO-GO FOR FREEZE",
            "production_or_remote_mcp_authorized": False,
        },
        "next_gate": (
            "SYNTHETIC_TREATMENT_DELIVERY_SHADOW_REQUIRED_FULL_LME_DISABLED"
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_new(output_path, receipt)
    return receipt


def _run_check(
    command: list[str], *, passed_pattern: str | None = None
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    _require(completed.returncode == 0, f"verification failed: {command[0]}")
    combined = completed.stdout + completed.stderr
    result: dict[str, Any] = {
        "command": command,
        "exit_code": completed.returncode,
        "output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
    }
    if passed_pattern is not None:
        matched = re.search(passed_pattern, combined)
        _require(matched is not None, f"verification summary missing: {command[0]}")
        result["reported_count"] = int(matched.group(1))
    return result


def _nested(value: dict[str, Any], key: str, child: str) -> object:
    nested = value.get(key)
    return nested.get(child) if isinstance(nested, dict) else None


def _identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(payload)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CalibrationError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build(output_path=args.output)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": str(args.output),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "next_gate": receipt["next_gate"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
