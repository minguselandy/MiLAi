"""Execute and receipt the DG-21 quality, PostgreSQL, and security gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"
for _path in (ROOT, RUNTIME_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from milai.config import load_settings
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database

PYTEST = RUNTIME_ROOT / ".venv/bin/pytest"
RUFF = RUNTIME_ROOT / ".venv/bin/ruff"
MYPY = RUNTIME_ROOT / ".venv/bin/mypy"
S7_DIR = ROOT / "var/dg21/s7/dg21-s7-matched-20260828-008"
S7_EVIDENCE = (
    S7_DIR / "plan.json",
    S7_DIR / "sealed-context-trace.json",
    S7_DIR / "reader-progress-trace.json",
    S7_DIR / "reader-failure.json",
    S7_DIR / "failure-ledger.json",
    S7_DIR / "failure-analysis.json",
)
OUTPUT_ROOT = ROOT / "var/dg21/s8"


class DG21S8Error(RuntimeError):
    """The quality gate cannot produce trustworthy fresh evidence."""


@dataclass(frozen=True, slots=True)
class GateSpec:
    gate_id: str
    command: tuple[str, ...]
    cwd: Path
    test_gate: bool = False
    require_database: bool = False
    timeout_seconds: int = 600


def summarize_test_output(output: str) -> dict[str, int]:
    summary = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for key in summary:
        matches = re.findall(rf"(\d+) {key}", output)
        if matches:
            summary[key] = int(matches[-1])
    return summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(ROOT)),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_gate(
    spec: GateSpec,
    *,
    log_dir: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    print(json.dumps({"gate": spec.gate_id, "status": "STARTED"}), flush=True)
    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - argv is a frozen GateSpec
            list(spec.command),
            cwd=spec.cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=spec.timeout_seconds,
        )
        exit_code = completed.returncode
        output = completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = (
            exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        )
        output = stdout + stderr + "\nDG21_GATE_TIMEOUT\n"
    log_path = log_dir / f"{spec.gate_id}.log"
    log_path.write_text(output, encoding="utf-8")
    summary = summarize_test_output(output) if spec.test_gate else None
    database_configured = "is not configured" not in output
    passed = exit_code == 0 and not timed_out
    if spec.require_database:
        passed = passed and database_configured and bool(summary and summary["passed"])
    result = {
        "gate_id": spec.gate_id,
        "argv": list(spec.command),
        "cwd": str(spec.cwd.resolve()),
        "exit_code": exit_code,
        "passed": passed,
        "timed_out": timed_out,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "log": _identity(log_path),
        "summary": summary,
        "database_configured": database_configured if spec.require_database else None,
    }
    print(
        json.dumps(
            {
                "gate": spec.gate_id,
                "status": "PASSED" if passed else "FAILED",
                "exit_code": exit_code,
                "summary": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return result


def _gate_specs() -> tuple[GateSpec, ...]:
    dg21_tests = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "tests").glob("test_dg21*.py"))
    )
    dg21_evals = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "evals/dg21").glob("*.py"))
    )
    dg21_scripts = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "scripts").glob("*dg21*.py"))
    )
    return (
        GateSpec(
            "runtime-unit",
            (str(PYTEST), "-q", "tests/unit"),
            RUNTIME_ROOT,
            test_gate=True,
        ),
        GateSpec(
            "runtime-contract",
            (str(PYTEST), "-q", "tests/contract"),
            RUNTIME_ROOT,
            test_gate=True,
        ),
        GateSpec(
            "dg21-evaluation",
            (str(PYTEST), "-q", *dg21_tests),
            ROOT,
            test_gate=True,
        ),
        GateSpec("runtime-mypy-strict", (str(MYPY),), RUNTIME_ROOT),
        GateSpec(
            "dg21-mypy-strict",
            (str(MYPY), "--strict", *dg21_evals, *dg21_scripts),
            ROOT,
        ),
        GateSpec(
            "runtime-ruff",
            (str(RUFF), "check", "src", "tests", "migrations"),
            RUNTIME_ROOT,
        ),
        GateSpec(
            "dg21-ruff",
            (
                str(RUFF),
                "check",
                "--ignore",
                "E402",
                "--config",
                "runtime/pyproject.toml",
                *dg21_evals,
                *dg21_scripts,
                *dg21_tests,
            ),
            ROOT,
        ),
        GateSpec(
            "runtime-postgresql-integration-security",
            (str(PYTEST), "-q", "tests/integration", "tests/security"),
            RUNTIME_ROOT,
            test_gate=True,
            require_database=True,
            timeout_seconds=900,
        ),
    )


def run(*, run_id: str, output: Path, env_file: Path) -> dict[str, Any]:
    if output.exists():
        raise DG21S8Error("output exists; choose a fresh S8 run ID")
    missing = [path for path in S7_EVIDENCE if not path.is_file()]
    if missing:
        raise DG21S8Error("S7 failure evidence is incomplete")
    log_dir = output / "logs"
    log_dir.mkdir(parents=True)
    specs = _gate_specs()
    plan = {
        "schema": "milai.dg21.s8-quality-plan.v0.1",
        "run_id": run_id,
        "entry_s7_evidence": [_identity(path) for path in S7_EVIDENCE],
        "gates": [
            {
                "gate_id": spec.gate_id,
                "argv": list(spec.command),
                "cwd": str(spec.cwd.resolve()),
                "timeout_seconds": spec.timeout_seconds,
            }
            for spec in specs
        ],
        "real_postgresql": True,
        "separate_roles": ["owner", "api", "steward", "worker", "audit"],
        "schema_lane": "WP06_NOT_ENTERED_EXISTING_REPOSITORY_HEAD_ONLY",
        "latency_repeats": "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED",
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }
    plan_path = output / "plan.json"
    _write(plan_path, plan)

    environment = dict(os.environ)
    environment["PYTHONPATH"] = ":".join((str(RUNTIME_SRC), str(ROOT)))
    environment["MYPYPATH"] = str(RUNTIME_SRC)
    results = [
        _run_gate(spec, log_dir=log_dir, environment=environment)
        for spec in specs
        if not spec.require_database
    ]

    load_runtime_environment(env_file)
    settings = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise DG21S8Error("separate owner/worker/audit database URLs are required")
    database = f"milai_smoke_dg21_s8_{secrets.token_hex(8)}"
    cleanup: dict[str, object] = {"status": "NOT_CREATED"}
    created = False
    try:
        _create_database(owner_source, database)
        created = True
        urls = {
            "owner": _database_url(owner_source, database),
            "api": _database_url(settings.database_dsn, database),
            "steward": _database_url(settings.steward_database_dsn, database),
            "worker": _database_url(worker_source, database),
            "audit": _database_url(audit_source, database),
        }
        pg_environment = {
            **environment,
            **os.environ,
            "PYTHONPATH": environment["PYTHONPATH"],
            "MYPYPATH": environment["MYPYPATH"],
            "MILAI_MIGRATION_DATABASE_URL": urls["owner"],
            "MILAI_TEST_DATABASE_URL": urls["owner"],
            "MILAI_TEST_API_DATABASE_URL": urls["api"],
            "MILAI_TEST_STEWARD_DATABASE_URL": urls["steward"],
            "MILAI_TEST_WORKER_DATABASE_URL": urls["worker"],
            "MILAI_TEST_AUDIT_DATABASE_URL": urls["audit"],
            "MILAI_WORKER_DATABASE_URL": urls["worker"],
            "MILAI_AUDIT_DATABASE_URL": urls["audit"],
        }
        integration = next(spec for spec in specs if spec.require_database)
        results.append(
            _run_gate(integration, log_dir=log_dir, environment=pg_environment)
        )
    finally:
        cleanup = (
            dict(_drop_database(owner_source, database))
            if created
            else {"status": "NOT_CREATED"}
        )

    all_gates_passed = all(bool(result["passed"]) for result in results)
    cleanup_passed = cleanup.get("status") == "PASS"
    quality_passed = all_gates_passed and cleanup_passed
    receipt = {
        "schema": "milai.dg21.s8-quality-receipt.v0.1",
        "run_id": run_id,
        "status": (
            "PASS_DG21_QUALITY_POSTGRESQL_SECURITY_WITH_S7_BLOCKED"
            if quality_passed
            else "FAIL_DG21_QUALITY_POSTGRESQL_SECURITY"
        ),
        "passed": quality_passed,
        "gate_count": len(results),
        "passed_gate_count": sum(bool(result["passed"]) for result in results),
        "gates": results,
        "postgresql": {
            "executed": True,
            "fresh_ephemeral_database": True,
            "database_name": database,
            "database_name_sha256": hashlib.sha256(database.encode()).hexdigest(),
            "roles": ["owner", "api", "steward", "worker", "audit"],
            "credentials_recorded": False,
            "cleanup": cleanup,
            "coverage": {
                "source_range_scope_rls": "FULL_INTEGRATION_AND_SECURITY_SUITE",
                "adjacency_cross_tenant_scope_denial": "DG18_GOVERNED_ADJACENCY_PLUS_RLS_SUITE",
                "revoked_evidence_rejection": "RETRIEVAL_GATE_AND_CONTEXT_REVOCATION_TESTS",
                "statement_timeout_typed_failure": "RETRIEVAL_DEADLINE_INTEGRATION_TEST",
                "connection_context_reset": "SECURITY_TENANT_ROLE_POOL_RESET_TEST",
                "wp06_event_projection_checks": "NOT_APPLICABLE_WP06_NOT_ENTERED",
            },
        },
        "s7_correctness_sealed": False,
        "latency_repeats": "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED",
        "openworker_composition_executed": False,
        "openworker_composition_disposition": "OPTIONAL_OUT_OF_SCOPE_FOR_DG21_CORE",
        "candidate_default": False,
        "public_mcp_schema_changed_by_dg21": False,
        "reader_provider_contract_changed": False,
        "formal_holdout_consumed": False,
        "plan": _identity(plan_path),
        "runner": _identity(Path(__file__)),
        "entry_s7_evidence": [_identity(path) for path in S7_EVIDENCE],
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg21-s8-quality-20260828-002")
    parser.add_argument("--env-file", type=Path, default=RUNTIME_ROOT / ".env")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    try:
        receipt = run(run_id=args.run_id, output=output, env_file=args.env_file)
    except BaseException as exc:
        if output.exists() and not (output / "failure-ledger.json").exists():
            _write(
                output / "failure-ledger.json",
                {
                    "schema": "milai.dg21.failure-ledger.v0.1",
                    "run_id": args.run_id,
                    "status": "FAILED_PRESERVED_FOR_DIAGNOSIS",
                    "failure_type": type(exc).__name__,
                    "reason": str(exc),
                    "automatic_retry_attempted": False,
                    "formal_holdout_consumed": False,
                },
            )
        raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "passed": receipt["passed"],
                "receipt": str((output / "receipt.json").relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
