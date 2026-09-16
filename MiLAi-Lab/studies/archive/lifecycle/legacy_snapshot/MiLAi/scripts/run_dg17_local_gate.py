#!/usr/bin/env python3
"""Run and receipt the DG-17 local deterministic test/static gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/local-gate"


@dataclass(frozen=True, slots=True)
class GateCommand:
    name: str
    cwd: Path
    argv: tuple[str, ...]
    env: dict[str, str]


def gate_commands() -> tuple[GateCommand, ...]:
    # Preserve the virtual-environment launcher path; resolving its symlink would
    # bypass the venv and lose the installed test/static-check packages.
    python = str(RUNTIME / ".venv/bin/python")
    uv = _executable("uv")
    root_test_paths = [
        *sorted((ROOT / "tests").glob("test_dg17_*.py")),
        ROOT / "tests/test_dg16_reader_stability.py",
    ]
    root_tests = tuple(
        str(path.relative_to(ROOT))
        for path in root_test_paths
    )
    root_sources = tuple(
        str(path.relative_to(ROOT))
        for pattern in (
            "evals/dg17/*.py",
            "scripts/run_dg17*.py",
            "tests/test_dg17_*.py",
            "scripts/run_dg16_reader_stability.py",
            "tests/test_dg16_reader_stability.py",
        )
        for path in sorted(ROOT.glob(pattern))
    )
    root_env = {
        "PYTHONPATH": str((RUNTIME / "src").resolve()),
        "MYPYPATH": str((RUNTIME / "src").resolve()),
    }
    return (
        GateCommand(
            "runtime-unit",
            RUNTIME,
            (uv, "run", "pytest", "-q", "tests/unit"),
            {},
        ),
        GateCommand(
            "runtime-contract",
            RUNTIME,
            (uv, "run", "pytest", "-q", "tests/contract"),
            {},
        ),
        GateCommand(
            "runtime-strict-mypy",
            RUNTIME,
            (uv, "run", "mypy", "--strict", "src/milai"),
            {},
        ),
        GateCommand(
            "runtime-ruff",
            RUNTIME,
            (uv, "run", "ruff", "check", "src/milai", "tests/unit"),
            {},
        ),
        GateCommand(
            "dg17-tests",
            ROOT,
            (python, "-m", "pytest", "-q", *root_tests),
            root_env,
        ),
        GateCommand(
            "dg17-ruff",
            ROOT,
            (python, "-m", "ruff", "check", *root_sources),
            root_env,
        ),
        GateCommand(
            "dg17-strict-mypy",
            ROOT,
            (python, "-m", "mypy", "--strict", *root_sources),
            root_env,
        ),
    )


def run_gate(*, run_id: str, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise RuntimeError("output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for command in gate_commands():
        command_started = time.perf_counter()
        environment = dict(os.environ)
        environment.update(command.env)
        completed = subprocess.run(
            command.argv,
            cwd=command.cwd,
            env=environment,
            capture_output=True,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - command_started) * 1_000
        output = completed.stdout + completed.stderr
        log_path = output_root / f"{command.name}.log"
        log_path.write_bytes(output)
        passed = sum(int(value) for value in re.findall(rb"(\d+) passed", output))
        results.append(
            {
                "name": command.name,
                "argv": list(command.argv),
                "cwd": str(command.cwd.relative_to(ROOT)),
                "exit_code": completed.returncode,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "elapsed_ms": round(elapsed_ms, 6),
                "reported_passed_tests": passed,
                "log": str(log_path.relative_to(ROOT)),
                "log_sha256": hashlib.sha256(output).hexdigest(),
            }
        )
        if completed.returncode != 0:
            break
    receipt = {
        "schema": "milai.dg17.local-deterministic-gate.v0.1",
        "status": "PASS"
        if len(results) == len(gate_commands())
        and all(result["status"] == "PASS" for result in results)
        else "FAIL",
        "classification": "LOCAL_DETERMINISTIC_DEVELOPMENT_GATE",
        "run_id": run_id,
        "external_model_calls": 0,
        "runtime_or_database_started": False,
        "formal_holdout_consumed": False,
        "automatic_retries": 0,
        "command_count": len(results),
        "reported_passed_tests": sum(
            int(result["reported_passed_tests"]) for result in results
        ),
        "commands": results,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    payload = (
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    (output_root / "receipt.json").write_bytes(payload)
    return receipt


def _executable(name: str) -> str:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise RuntimeError(f"required executable not found: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run_gate(run_id=args.run_id, output_root=output_root)
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "reported_passed_tests": receipt["reported_passed_tests"],
                "wall_ms": receipt["wall_ms"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
