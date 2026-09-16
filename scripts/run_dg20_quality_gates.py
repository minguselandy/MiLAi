#!/usr/bin/env python3
"""Execute and receipt DG-20 Runtime, evaluation, static, and integration gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime/.venv/bin/python"
PYTEST = ROOT / "runtime/.venv/bin/pytest"
RUFF = ROOT / "runtime/.venv/bin/ruff"
MYPY = ROOT / "runtime/.venv/bin/mypy"


class DG20QualityGateError(RuntimeError):
    """The quality gate could not be executed without overwriting evidence."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def summarize_test_output(output: str) -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for key in summary:
        matches = re.findall(rf"(\d+) {key}", output)
        if matches:
            summary[key] = int(matches[-1])
    return summary


def _run_gate(
    *,
    gate_id: str,
    command: list[str],
    cwd: Path,
    log_dir: Path,
    environment: dict[str, str],
    test_gate: bool = False,
    require_configured_database: bool = False,
) -> dict[str, Any]:
    print(json.dumps({"gate": gate_id, "status": "STARTED"}), flush=True)
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - commands are fixed repository tools
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    log_path = log_dir / f"{gate_id}.log"
    log_path.write_text(output, encoding="utf-8")
    summary = summarize_test_output(output) if test_gate else None
    database_configured = "is not configured" not in output
    passed = completed.returncode == 0
    if require_configured_database:
        passed = passed and database_configured and bool(summary and summary["passed"])
    result = {
        "gate_id": gate_id,
        "command": command,
        "cwd": str(cwd.resolve()),
        "exit_code": completed.returncode,
        "passed": passed,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "log": _identity(log_path),
        "test_summary": summary,
        "database_configured": database_configured if require_configured_database else None,
    }
    print(
        json.dumps(
            {
                "gate": gate_id,
                "status": "PASSED" if passed else "FAILED",
                "exit_code": completed.returncode,
                "test_summary": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def run(*, run_id: str, output: Path, include_integration: bool) -> dict[str, Any]:
    if output.exists():
        raise DG20QualityGateError("output exists; choose a fresh quality run ID")
    log_dir = output / "logs"
    log_dir.mkdir(parents=True)
    environment = dict(os.environ)
    # DG-20 owns the Runtime/evaluator lane.  The Goal explicitly keeps the
    # primary OpenWorker composition gate outside this work package, so do not
    # make optional integration packages importable just for this receipt.
    environment["PYTHONPATH"] = ":".join(
        str(path) for path in (ROOT / "runtime/src", ROOT)
    )
    environment["MYPYPATH"] = str(ROOT / "runtime/src")
    dg20_tests = sorted(
        str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_dg20*.py")
    )
    dg20_scripts = sorted(
        str(path.relative_to(ROOT)) for path in (ROOT / "scripts").glob("*dg20*.py")
    )
    dg20_evals = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "evals/dg20").glob("*.py"))
    gates = [
        (
            "runtime-unit",
            [str(PYTEST), "-q", "tests/unit"],
            ROOT / "runtime",
            True,
            False,
        ),
        (
            "runtime-contract",
            [str(PYTEST), "-q", "tests/contract"],
            ROOT / "runtime",
            True,
            False,
        ),
        (
            "dg20-evaluation",
            [str(PYTEST), "-q", *dg20_tests],
            ROOT,
            True,
            False,
        ),
        (
            "runtime-mypy-strict",
            [str(MYPY)],
            ROOT / "runtime",
            False,
            False,
        ),
        (
            "dg20-mypy-strict",
            [str(MYPY), "--strict", *dg20_evals, *dg20_scripts],
            ROOT,
            False,
            False,
        ),
        (
            "runtime-ruff",
            [str(RUFF), "check", "src", "tests", "migrations"],
            ROOT / "runtime",
            False,
            False,
        ),
        (
            "dg20-ruff",
            [
                str(RUFF),
                "check",
                "--ignore",
                "E402",
                "--config",
                "runtime/pyproject.toml",
                *dg20_evals,
                *dg20_scripts,
                *dg20_tests,
            ],
            ROOT,
            False,
            False,
        ),
    ]
    if include_integration:
        required = (
            "MILAI_MIGRATION_DATABASE_URL",
            "MILAI_TEST_DATABASE_URL",
            "MILAI_TEST_API_DATABASE_URL",
            "MILAI_TEST_STEWARD_DATABASE_URL",
            "MILAI_TEST_WORKER_DATABASE_URL",
            "MILAI_TEST_AUDIT_DATABASE_URL",
        )
        missing = [name for name in required if not environment.get(name)]
        if missing:
            raise DG20QualityGateError(
                "integration database variables are missing: " + ", ".join(missing)
            )
        gates.append(
            (
                "runtime-integration-security",
                [str(PYTEST), "-q", "tests/integration", "tests/security"],
                ROOT / "runtime",
                True,
                True,
            )
        )
    results = [
        _run_gate(
            gate_id=gate_id,
            command=command,
            cwd=cwd,
            log_dir=log_dir,
            environment=environment,
            test_gate=test_gate,
            require_configured_database=require_database,
        )
        for gate_id, command, cwd, test_gate, require_database in gates
    ]
    passed = all(bool(item["passed"]) for item in results)
    receipt = {
        "schema": "milai.dg20.quality-gate-receipt.v0.1",
        "run_id": run_id,
        "status": "PASS_DG20_QUALITY_GATES" if passed else "FAILED_DG20_QUALITY_GATES",
        "passed": passed,
        "gate_count": len(results),
        "passed_gate_count": sum(bool(item["passed"]) for item in results),
        "integration_executed": include_integration,
        "openworker_composition_executed": False,
        "openworker_composition_disposition": (
            "OUT_OF_SCOPE_OPTIONAL_GATE_PER_DG20_SECTION_3_10"
        ),
        "formal_holdout_consumed": False,
        "gates": results,
        "runner": _identity(Path(__file__)),
    }
    receipt_path = output / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/dg20/quality")
    parser.add_argument("--include-integration", action="store_true")
    args = parser.parse_args()
    receipt = run(
        run_id=args.run_id,
        output=args.output_root / args.run_id,
        include_integration=args.include_integration,
    )
    print(json.dumps({"status": receipt["status"], "passed": receipt["passed"]}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
