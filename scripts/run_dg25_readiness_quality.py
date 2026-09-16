#!/usr/bin/env python3
"""Run and hash-bind the DG-25 readiness quality gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
PYTHON = RUNTIME / ".venv/bin/python"
PYTEST = RUNTIME / ".venv/bin/pytest"
MYPY = RUNTIME / ".venv/bin/mypy"
RUFF = RUNTIME / ".venv/bin/ruff"
ARCHITECTURE_SHA256 = "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg25.s3_readiness import READINESS_SOURCE_PATHS


class Gate(NamedTuple):
    gate_id: str
    argv: tuple[str, ...]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    output = ROOT / "var/dg25/quality" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    source_files = [_identity(ROOT / path) for path in READINESS_SOURCE_PATHS]
    gates = _gates()
    results = []
    environment = os.environ.copy()
    environment["PYTHONPATH"] = f"{ROOT / 'runtime/src'}:{ROOT}"
    for gate in gates:
        completed = subprocess.run(
            gate.argv,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
        )
        stdout_path = output / f"{gate.gate_id}.stdout.txt"
        stderr_path = output / f"{gate.gate_id}.stderr.txt"
        stdout_path.write_bytes(completed.stdout)
        stderr_path.write_bytes(completed.stderr)
        results.append(
            {
                "gate_id": gate.gate_id,
                "argv": list(gate.argv),
                "cwd": str(ROOT),
                "exit_code": completed.returncode,
                "stdout": _identity(stdout_path),
                "stderr": _identity(stderr_path),
            }
        )

    current_sources = all(
        _sha256(ROOT / str(item["path"])) == item["sha256"]
        and (ROOT / str(item["path"])).stat().st_size == item["size"]
        for item in source_files
    )
    passed = all(item["exit_code"] == 0 for item in results) and current_sources
    receipt = {
        "schema": "milai.dg25.readiness-quality-receipt.v0.1",
        "run_id": args.run_id,
        "status": (
            "PASS_DG25_READINESS_QUALITY" if passed else "FAIL_DG25_READINESS_QUALITY"
        ),
        "gates": results,
        "source_files": source_files,
        "source_set_digest": _canonical_sha256(source_files),
        "source_files_current_after_gates": current_sources,
        "architecture_manifest_sha256": ARCHITECTURE_SHA256,
        "automatic_retries": 0,
    }
    receipt_path = output / "receipt.json"
    _write_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _gates() -> list[Gate]:
    dg25_sources = (
        "evals/dg25/arm_sealing.py",
        "evals/dg25/effect_scorer.py",
        "evals/dg25/routing_ablation.py",
        "evals/dg25/s3_readiness.py",
        "evals/dg25/s3a_generator.py",
        "evals/dg25/stop_gate.py",
        "scripts/run_dg25_readiness_quality.py",
        "scripts/run_dg25_s3_readiness.py",
        "scripts/run_dg25_s3a.py",
        "tests/test_dg25_s3_readiness.py",
    )
    return [
        Gate(
            "expanded-pytest",
            (
                str(PYTEST),
                "-q",
                "runtime/tests/unit",
                "runtime/tests/contract",
                "tests/test_dg25_s0_baseline_freeze.py",
                "tests/test_dg25_s1_contracts.py",
                "tests/test_dg25_review_gate.py",
                "tests/test_dg25_s2_plan_execution.py",
                "tests/test_dg25_s3_readiness.py",
            ),
        ),
        Gate(
            "strict-mypy",
            (str(MYPY), "--strict", "runtime/src/milai", *dg25_sources),
        ),
        Gate(
            "ruff",
            (str(RUFF), "check", "runtime/src/milai", *dg25_sources),
        ),
        Gate(
            "compileall",
            (
                str(PYTHON),
                "-m",
                "compileall",
                "-q",
                "runtime/src/milai",
                "evals/dg25",
                "scripts/run_dg25_readiness_quality.py",
                "scripts/run_dg25_s3_readiness.py",
                "scripts/run_dg25_s3a.py",
            ),
        ),
        Gate(
            "architecture-validate",
            (str(PYTHON), "architecture/v1.0/scripts/validate_bundle.py"),
        ),
        Gate(
            "architecture-release-lock",
            (
                str(PYTHON),
                "architecture/v1.0/scripts/verify_lock.py",
                "--scope",
                "bundle",
                "--mode",
                "release",
                "--expected-manifest-sha256",
                ARCHITECTURE_SHA256,
            ),
        ),
    ]


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
