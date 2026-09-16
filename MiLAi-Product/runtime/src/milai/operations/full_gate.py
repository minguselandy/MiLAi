from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai.config import SettingsError, load_settings
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database


def _write_report(path: Path, value: dict[str, Any]) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_runtime_full_gate(env_file: Path, report_path: Path) -> dict[str, Any]:
    """Run the Runtime test suite against one fresh exact-role database."""
    load_runtime_environment(env_file)
    settings = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise SettingsError("owner, worker and audit URLs are required")

    run_id = secrets.token_hex(12)
    database = f"milai_smoke_{run_id[:20]}"
    urls = {
        "owner": _database_url(owner_source, database),
        "api": _database_url(settings.database_dsn, database),
        "steward": _database_url(settings.steward_database_dsn, database),
        "worker": _database_url(worker_source, database),
        "audit": _database_url(audit_source, database),
    }
    report: dict[str, Any] = {
        "schema": "milai.runtime-fresh-database-full-gate.v1",
        "run_id": run_id,
        "database": database,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "BLOCKED",
    }
    created = False
    runtime_root = env_file.resolve().parent
    python_paths = [str(runtime_root.parent), str(runtime_root / "src")]
    inherited_pythonpath = os.environ.get("PYTHONPATH")
    if inherited_pythonpath:
        python_paths.append(inherited_pythonpath)
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
            "PYTHONPATH": os.pathsep.join(python_paths),
        }
        completed = subprocess.run(  # noqa: S603 -- fixed repository pytest executable
            [str(runtime_root / ".venv/bin/pytest"), "-q"],
            cwd=runtime_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        report["pytest_exit_code"] = completed.returncode
        report["pytest_stdout_tail"] = completed.stdout[-2_000:]
        report["pytest_stderr_tail"] = completed.stderr[-2_000:]
        summary = re.search(r"(\d+) passed(?:, \d+ skipped)? in ([0-9.]+)s", completed.stdout)
        if summary is not None:
            report["pytest_passed"] = int(summary.group(1))
            report["pytest_elapsed_seconds"] = float(summary.group(2))
        report["status"] = "PASS" if completed.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        report["failure_code"] = "PYTEST_TIMEOUT"
    finally:
        report["cleanup"] = (
            _drop_database(owner_source, database) if created else {"status": "NOT_CREATED"}
        )
        if report["cleanup"].get("status") != "PASS":
            report["status"] = "BLOCKED"
        report["finished_at"] = datetime.now(UTC).isoformat()
        _write_report(report_path, report)
    return report
