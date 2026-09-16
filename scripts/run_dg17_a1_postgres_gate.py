#!/usr/bin/env python3
"""Run the DG-17 A1 focused PostgreSQL gate in one fresh database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.config import SettingsError, load_settings
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database

TESTS = (
    "tests/unit/test_migration_resources.py",
    "tests/unit/test_dg17_turn_first_acquisition.py",
    (
        "tests/integration/test_projection_worker.py::"
        "test_dg17_a1_evidence_search_ranks_matching_turns_without_session_backfill"
    ),
)


def run(
    *, env_file: Path, output: Path, tests: tuple[str, ...] = TESTS
) -> dict[str, object]:
    load_runtime_environment(env_file)
    settings = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SettingsError("owner, worker and audit URLs are required")
    run_id = secrets.token_hex(12)
    database = f"milai_smoke_dg17_a1_{run_id[:16]}"
    urls = {
        "owner": _database_url(owner_source, database),
        "api": _database_url(settings.database_dsn, database),
        "steward": _database_url(settings.steward_database_dsn, database),
        "worker": _database_url(worker_source, database),
        "audit": _database_url(audit_source, database),
    }
    started = time.perf_counter()
    receipt: dict[str, object] = {
        "schema": "milai.dg17.a1-focused-postgresql-gate.v0.1",
        "status": "BLOCKED",
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "tests": list(tests),
        "automatic_retries": 0,
        "model_calls": 0,
    }
    created = False
    try:
        _create_database(owner_source, database)
        created = True
        environment = {
            **os.environ,
            "MILAI_MIGRATION_DATABASE_URL": urls["owner"],
            "MILAI_TEST_DATABASE_URL": urls["owner"],
            "MILAI_TEST_API_DATABASE_URL": urls["api"],
            "MILAI_TEST_STEWARD_DATABASE_URL": urls["steward"],
            "MILAI_TEST_WORKER_DATABASE_URL": urls["worker"],
            "MILAI_TEST_AUDIT_DATABASE_URL": urls["audit"],
            "MILAI_WORKER_DATABASE_URL": urls["worker"],
            "MILAI_AUDIT_DATABASE_URL": urls["audit"],
        }
        completed = subprocess.run(
            [str(RUNTIME_ROOT / ".venv/bin/pytest"), "-q", *tests],
            cwd=RUNTIME_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        receipt.update(
            {
                "pytest_exit_code": completed.returncode,
                "pytest_stdout": completed.stdout[-30_000:],
                "pytest_stderr": completed.stderr[-30_000:],
                "status": "PASS" if completed.returncode == 0 else "FAIL",
            }
        )
    except subprocess.TimeoutExpired as exc:
        receipt.update(
            {
                "status": "FAIL",
                "failure_code": "PYTEST_TIMEOUT",
                "pytest_stdout": str(exc.stdout or "")[-30_000:],
                "pytest_stderr": str(exc.stderr or "")[-30_000:],
            }
        )
    finally:
        cleanup = (
            _drop_database(owner_source, database)
            if created
            else {"status": "NOT_CREATED"}
        )
        receipt["cleanup"] = cleanup
        if cleanup.get("status") != "PASS":
            receipt["status"] = "BLOCKED"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        receipt["wall_ms"] = round((time.perf_counter() - started) * 1_000, 6)
        _write_json(output, receipt)
    return receipt


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=RUNTIME_ROOT / ".env")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test", action="append", dest="tests")
    args = parser.parse_args()
    tests = tuple(args.tests) if args.tests else TESTS
    receipt = run(env_file=args.env_file, output=args.output, tests=tests)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(args.output),
                "receipt_sha256": _sha256(args.output),
                "pytest_exit_code": receipt.get("pytest_exit_code"),
                "cleanup": receipt["cleanup"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
