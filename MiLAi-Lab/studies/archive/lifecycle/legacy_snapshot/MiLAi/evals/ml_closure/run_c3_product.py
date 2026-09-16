"""Run the frozen C3 product acquisition in one fresh ephemeral database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
RUNTIME_SRC = RUNTIME / "src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.config import load_settings
from milai.domain.requirement_state import canonical_sha256
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database

OUTPUT = (
    ROOT / "var/ml_closure/ml-closure-20260830-001/checkpoints/c3-product-unscored.json"
)
RAW = ROOT / "evals/datasets/ml_closure/sealed-validation.raw.json"
BASELINE = (
    ROOT
    / "var/ml_closure/ml-closure-20260830-001/checkpoints/c0-candidate-r-unscored.json"
)
ENV_FILE = RUNTIME / ".env"
MARKER = "ML_CLOSURE_C3_PRODUCT_RESULT="


def execute(
    *,
    raw_path: Path = RAW,
    baseline_path: Path | None = BASELINE,
    output_path: Path = OUTPUT,
) -> dict[str, Any]:
    if output_path.exists():
        raise RuntimeError("C3_PRODUCT_OUTPUT_ALREADY_EXISTS")
    load_runtime_environment(ENV_FILE)
    settings = load_settings()
    owner = _required("MILAI_MIGRATION_DATABASE_URL")
    worker = _required("MILAI_WORKER_DATABASE_URL")
    audit = _required("MILAI_AUDIT_DATABASE_URL")
    database = f"milai_smoke_mlc3_{secrets.token_hex(8)}"
    created = False
    completed: subprocess.CompletedProcess[str] | None = None
    cleanup: dict[str, object] = {"status": "NOT_CREATED"}
    try:
        _create_database(owner, database)
        created = True
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": f"{RUNTIME_SRC}:{ROOT}",
                "MILAI_MIGRATION_DATABASE_URL": _database_url(owner, database),
                "MILAI_TEST_API_DATABASE_URL": _database_url(
                    settings.database_dsn, database
                ),
                "MILAI_TEST_STEWARD_DATABASE_URL": _database_url(
                    settings.steward_database_dsn, database
                ),
                "MILAI_TEST_WORKER_DATABASE_URL": _database_url(worker, database),
                "MILAI_TEST_AUDIT_DATABASE_URL": _database_url(audit, database),
            }
        )
        child_command = [
            str(RUNTIME / ".venv/bin/python"),
            str(Path(__file__).with_name("c3_product_acquisition.py")),
            "--raw",
            str(raw_path.resolve()),
        ]
        if baseline_path is None:
            child_command.append("--no-baseline")
        else:
            child_command.extend(("--baseline", str(baseline_path.resolve())))
        completed = subprocess.run(
            child_command,
            cwd=RUNTIME,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
        )
    finally:
        cleanup = (
            dict(_drop_database(owner, database))
            if created
            else {"status": "NOT_CREATED"}
        )
    if completed is None:
        raise RuntimeError("C3_PRODUCT_NOT_EXECUTED")
    result = _parse(completed.stdout)
    result["process_exit_code"] = completed.returncode
    result["fresh_ephemeral_database"] = True
    result["database_name_sha256"] = hashlib.sha256(database.encode()).hexdigest()
    result["cleanup"] = cleanup
    result["credentials_recorded"] = False
    result["stderr_empty"] = not completed.stderr.strip()
    checks = result.get("checks")
    result["status"] = (
        "PASS_C3_PRODUCT_ACQUISITION"
        if completed.returncode == 0
        and isinstance(checks, dict)
        and all(value is True for value in checks.values())
        and cleanup.get("status") == "PASS"
        else "NEEDS_REPAIR"
    )
    result["result_digest"] = canonical_sha256(result)
    _write_exclusive(output_path, result)
    return result


def _parse(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(MARKER):
            value = json.loads(line.removeprefix(MARKER))
            if isinstance(value, dict):
                return value
    raise RuntimeError("C3_PRODUCT_RESULT_MARKER_MISSING")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name}_MISSING")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    print(
        json.dumps(
            execute(
                raw_path=arguments.raw.resolve(),
                baseline_path=(
                    None if arguments.no_baseline else arguments.baseline.resolve()
                ),
                output_path=arguments.output.resolve(),
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
