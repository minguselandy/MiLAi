#!/usr/bin/env python3
"""Run DG-22 quality, PostgreSQL/RLS, security, and evidence-manifest gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.config import load_settings
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database

from scripts.run_dg21_s8_quality import GateSpec, _run_gate

PYTEST = RUNTIME_ROOT / ".venv/bin/pytest"
MYPY = RUNTIME_ROOT / ".venv/bin/mypy"
RUFF = RUNTIME_ROOT / ".venv/bin/ruff"
OUTPUT_ROOT = ROOT / "var/dg22/s9"
S7_RECEIPT = ROOT / "var/dg22/s7/dg22-s7-mediator-20260829-001/receipt.json"
S8_RECEIPT = ROOT / "var/dg22/s8/dg22-s8-answer-correctness-20260829-003/receipt.json"
RUNBOOK = ROOT / "docs/runbooks/dg22-accuracy-answer-closure.md"
FAILURE_INDEX = ROOT / "var/dg22/failure-index.jsonl"


def _gate_specs() -> tuple[GateSpec, ...]:
    tests = tuple(
        str(path.relative_to(ROOT)) for path in sorted((ROOT / "tests").glob("test_dg22*.py"))
    )
    evaluations = tuple(
        str(path.relative_to(ROOT)) for path in sorted((ROOT / "evals/dg22").glob("*.py"))
    )
    scripts = tuple(
        str(path.relative_to(ROOT)) for path in sorted((ROOT / "scripts").glob("*dg22*.py"))
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
            "dg22-evaluation",
            (str(PYTEST), "-q", *tests),
            ROOT,
            test_gate=True,
        ),
        GateSpec("runtime-mypy-strict", (str(MYPY),), RUNTIME_ROOT),
        GateSpec(
            "dg22-mypy-strict",
            (str(MYPY), "--strict", *evaluations, *scripts),
            ROOT,
        ),
        GateSpec(
            "runtime-ruff",
            (str(RUFF), "check", "src", "tests", "migrations"),
            RUNTIME_ROOT,
        ),
        GateSpec(
            "dg22-ruff",
            (
                str(RUFF),
                "check",
                "--ignore",
                "E402",
                "--config",
                "runtime/pyproject.toml",
                *evaluations,
                *scripts,
                *tests,
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
        raise FileExistsError(output)
    s7 = _read(S7_RECEIPT)
    s8 = _read(S8_RECEIPT)
    if s7.get("status") != "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION":
        raise RuntimeError("DG22_S9_S7_ENTRY_INVALID")
    if s8.get("status") != "FAIL_CORRECT_CASE_REGRESSION":
        raise RuntimeError("DG22_S9_S8_ENTRY_INVALID")
    log_dir = output / "logs"
    log_dir.mkdir(parents=True)
    specs = _gate_specs()
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s9-quality-plan.v0.1",
            "run_id": run_id,
            "gates": [
                {
                    "gate_id": spec.gate_id,
                    "argv": list(spec.command),
                    "cwd": str(spec.cwd),
                    "timeout_seconds": spec.timeout_seconds,
                }
                for spec in specs
            ],
            "real_postgresql": True,
            "database_schema_changed_by_dg22": False,
            "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "formal_holdout_consumed": False,
        },
    )
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
        raise RuntimeError("DG22_S9_DATABASE_ROLE_URLS_MISSING")
    database = f"milai_smoke_dg22_s9_{secrets.token_hex(8)}"
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
        results.append(_run_gate(integration, log_dir=log_dir, environment=pg_environment))
    finally:
        cleanup = (
            dict(_drop_database(owner_source, database)) if created else {"status": "NOT_CREATED"}
        )

    source_paths = [
        *sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "evals/dg22").glob("*.py")),
        *sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "scripts").glob("*dg22*.py")),
        *sorted(
            path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("test_dg22*.py")
        ),
        "runtime/src/milai/application/acquisition.py",
        "runtime/src/milai/application/accuracy_acquisition.py",
        "runtime/src/milai/application/appointment_composition.py",
        "runtime/src/milai/application/evidence_semantics.py",
        "runtime/src/milai/application/memory_query.py",
        "runtime/src/milai/application/query_ir_compat.py",
        "runtime/src/milai/domain/__init__.py",
        "runtime/src/milai/domain/semantic_query.py",
        RUNBOOK.relative_to(ROOT).as_posix(),
    ]
    source_manifest_path = output / "source-manifest.json"
    _write(
        source_manifest_path,
        {
            "schema": "milai.dg22.s9-source-manifest.v0.1",
            "identities": [_identity(ROOT / path) for path in sorted(set(source_paths))],
            "architecture_v1_changed_by_dg22": False,
        },
    )
    failure_records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({row["failure_id"] for row in failure_records}) != len(failure_records):
        raise RuntimeError("DG22_FAILURE_INDEX_NOT_APPEND_ONLY_UNIQUE")
    artifact_manifest_path = output / "artifact-manifest.json"
    artifacts = [
        plan_path,
        S7_RECEIPT,
        S8_RECEIPT,
        RUNBOOK,
        FAILURE_INDEX,
        source_manifest_path,
        *(log_dir / f"{result['gate_id']}.log" for result in results),
    ]
    _write(
        artifact_manifest_path,
        {
            "schema": "milai.dg22.s9-artifact-manifest.v0.1",
            "identities": [_identity(path) for path in artifacts],
        },
    )
    passed = all(bool(result["passed"]) for result in results) and cleanup.get("status") == "PASS"
    receipt = {
        "schema": "milai.dg22.s9-quality-receipt.v0.1",
        "run_id": run_id,
        "status": "PASS_DG22_QUALITY_POSTGRESQL_SECURITY"
        if passed
        else "FAIL_DG22_QUALITY_POSTGRESQL_SECURITY",
        "passed": passed,
        "gate_count": len(results),
        "passed_gate_count": sum(bool(result["passed"]) for result in results),
        "gates": results,
        "postgresql": {
            "executed": True,
            "fresh_ephemeral_database": True,
            "roles": ["owner", "api", "steward", "worker", "audit"],
            "credentials_recorded": False,
            "database_name_sha256": hashlib.sha256(database.encode()).hexdigest(),
            "cleanup": cleanup,
        },
        "database_schema_changed_by_dg22": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "candidate_default": False,
        "reader_calls": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
        "runbook": _identity(RUNBOOK),
        "failure_index": _identity(FAILURE_INDEX),
        "source_manifest": _identity(source_manifest_path),
        "artifact_manifest": _identity(artifact_manifest_path),
        "plan": _identity(plan_path),
    }
    _write(output / "receipt.json", receipt)
    return receipt


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s9-quality-20260829-001")
    parser.add_argument("--env-file", type=Path, default=RUNTIME_ROOT / ".env")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    receipt = run(run_id=args.run_id, output=output, env_file=args.env_file)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "passed_gate_count": receipt["passed_gate_count"],
                "gate_count": receipt["gate_count"],
                "receipt": str((output / "receipt.json").relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
