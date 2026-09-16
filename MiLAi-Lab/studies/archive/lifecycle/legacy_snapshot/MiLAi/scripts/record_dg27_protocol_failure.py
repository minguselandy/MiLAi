#!/usr/bin/env python3
"""Seal the non-retryable DG-27 V02 model-contract failure and quality evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.dg27.decision_boundary import load_run_lock

RUN_LOCK = ROOT / "var/dg27/v02/run-lock.json"
RESULTS = ROOT / "var/dg27/v02/results.json"
TERMINAL = ROOT / "var/dg27/v02/terminal.json"


class DG27FailureSealError(RuntimeError):
    """The observed failure cannot be represented without changing its facts."""


def seal() -> dict[str, Any]:
    if RESULTS.exists() or TERMINAL.exists():
        raise DG27FailureSealError("DG27_FAILURE_ARTIFACT_ALREADY_EXISTS")
    lock = load_run_lock(ROOT, RUN_LOCK)
    results: dict[str, Any] = {
        "schema": "milai.dg27.v02.failed-results.v0.2",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": "FAIL",
        "reason_code": "MODEL_OUTPUT_RUNTIME_VALIDATION_FAILED",
        "run_lock_digest": lock["lock_digest"],
        "execution": {
            "effect_attempts": 1,
            "completed_arms": [],
            "failure_phase": "D2_MODEL_INTERPRETATION_BEFORE_UNSCORED_OUTPUT_SEAL",
            "failure_case_id": "gpt4_8279ba03",
            "failure_requirement_id": "TARGET_EVENT",
            "submitted_candidate_occurrences": 8,
            "model_calls": 1,
            "automatic_retries": 0,
            "rerun_performed": False,
        },
        "failure": {
            "boundary": "SemanticHypothesisV02_RUNTIME_VALIDATION",
            "exception_code": "DG27_MODEL_HYPOTHESIS_SCHEMA_INVALID",
            "validation_reason_codes": [
                "GROUNDED_SPAN_WIDTH_MISMATCH",
                "EVENT_TIME_TIMEZONE_MISSING",
            ],
            "fail_closed": True,
            "model_output_persisted": False,
        },
        "label_boundary": {
            "unscored_output_sealed": False,
            "gold_registry_opened": False,
            "scorer_executed": False,
        },
        "scores": None,
        "safety": {
            "authority_violations": 0,
            "canonical_mutations": 0,
            "candidate_feature_flag": "OFF",
            "formal_holdout_used": False,
            "acquisition_calls": 0,
            "reader_calls": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
    }
    results["results_digest"] = canonical_sha256(results)
    _write_exclusive(RESULTS, results)

    quality = {
        "targeted_tests": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "runtime/tests/unit/test_dg27_decision_boundary.py",
                "tests/test_dg27_v02_effect.py",
                "runtime/tests/unit/test_requirement_state.py",
            ]
        ),
        "lint": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/ruff"),
                "check",
                "runtime/src/milai/domain/decision_boundary.py",
                "runtime/src/milai/application/decision_boundary.py",
                "runtime/src/milai/adapters/grounded_interpretation.py",
                "evals/dg27/decision_boundary.py",
                "scripts/run_dg27.py",
                "runtime/tests/unit/test_dg27_decision_boundary.py",
                "tests/test_dg27_v02_effect.py",
            ]
        ),
        "typecheck": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/mypy"),
                "--config-file",
                "runtime/pyproject.toml",
                "runtime/src/milai/domain/decision_boundary.py",
                "runtime/src/milai/application/decision_boundary.py",
                "runtime/src/milai/adapters/grounded_interpretation.py",
                "evals/dg27/decision_boundary.py",
                "scripts/run_dg27.py",
            ]
        ),
    }
    terminal: dict[str, Any] = {
        "schema": "milai.dg27.v02.terminal.v0.2",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": "FAIL",
        "reason_code": "SAFETY_OR_PROTOCOL",
        "detail_reason_code": "MODEL_OUTPUT_RUNTIME_VALIDATION_FAILED",
        "claims": {
            "DG27_H1_DECISION_BOUNDARY_REPAIR": "NOT_ESTABLISHED_BY_MATCHED_EFFECT",
            "DG27_H2_PROVISIONAL_INTERPRETATION_GAIN": "NOT_ESTABLISHED",
            "FAIL_CLOSED_MODEL_VALIDATION": "SUPPORTED",
        },
        "quality_gates": quality,
        "run_lock_digest": lock["lock_digest"],
        "results_digest": results["results_digest"],
        "safety": results["safety"],
        "rerun_authorized": False,
        "rollback": {
            "model_interpretation_feature_flag": "OFF",
            "decision_boundary_v02_retained": True,
            "v01_lock_retained": True,
            "provisional_state_persisted": False,
        },
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    _write_exclusive(TERMINAL, terminal)
    return terminal


def _run_quality(command: list[str]) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_SRC), str(ROOT), environment.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-4_000:],
    }


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    print(json.dumps(seal(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
