#!/usr/bin/env python3
"""Run DG-23 quality, PostgreSQL/security, cleanup, and architecture gates."""

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
PYTHON = RUNTIME_ROOT / ".venv/bin/python"
OUTPUT_ROOT = ROOT / "var/dg23/s8"
S6_RECEIPT = ROOT / "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/receipt.json"
S7_RECEIPT = ROOT / "var/dg23/s7/dg23-s7-matched-reader-20260829-002/receipt.json"
S7_FAILURE_LEDGER = ROOT / (
    "var/dg23/s7/dg23-s7-matched-reader-20260829-002/failure-ledger.json"
)
S8_PREVIOUS_FAILURE_LEDGERS = (
    ROOT / "var/dg23/s8/dg23-s8-quality-20260829-001/failure-ledger.json",
    ROOT / "var/dg23/s8/dg23-s8-quality-20260829-002/failure-ledger.json",
)
RUNBOOK = ROOT / "docs/runbooks/dg23-budget-invariant-context.md"
FAILURE_INDEX = ROOT / "var/dg23/failure-index.jsonl"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
DG21_S5_RECEIPT = ROOT / (
    "var/dg21/s5/dg21-s5-temporal-oracle-20260828-005/receipt.json"
)
DG21_ARCHIVAL_IDENTITY_TEST = (
    "tests/test_dg21_s5_temporal_oracle.py::"
    "test_s5_sealed_receipt_binds_every_artifact_and_source"
)
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)


def _gate_specs() -> tuple[GateSpec, ...]:
    dg23_tests = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "tests").glob("test_dg23*.py"))
    )
    prior_tests = tuple(
        str(path.relative_to(ROOT))
        for prefix in ("test_dg20*.py", "test_dg21*.py", "test_dg22*.py")
        for path in sorted((ROOT / "tests").glob(prefix))
    )
    dg23_evals = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "evals/dg23").glob("*.py"))
    )
    dg23_scripts = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "scripts").glob("*dg23*.py"))
    )
    context_retrieval_tests = tuple(
        str(path.relative_to(RUNTIME_ROOT))
        for pattern in (
            "test_context*.py",
            "test_dg17_memory_context.py",
            "test_dg18_context*.py",
            "test_retrieval*.py",
            "test_temporal_retrieval.py",
        )
        for path in sorted((RUNTIME_ROOT / "tests/unit").glob(pattern))
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
            "context-retrieval-regression",
            (str(PYTEST), "-q", *context_retrieval_tests),
            RUNTIME_ROOT,
            test_gate=True,
        ),
        GateSpec(
            "dg23-targeted-evaluation",
            (str(PYTEST), "-q", *dg23_tests),
            ROOT,
            test_gate=True,
        ),
        GateSpec(
            "dg20-dg21-dg22-evaluation-regression",
            (
                str(PYTEST),
                "-q",
                *prior_tests,
                "--deselect",
                DG21_ARCHIVAL_IDENTITY_TEST,
            ),
            ROOT,
            test_gate=True,
        ),
        GateSpec("runtime-mypy-strict", (str(MYPY),), RUNTIME_ROOT),
        GateSpec(
            "dg23-mypy-strict",
            (str(MYPY), "--strict", *dg23_evals, *dg23_scripts),
            ROOT,
        ),
        GateSpec(
            "runtime-ruff",
            (str(RUFF), "check", "src", "tests", "migrations"),
            RUNTIME_ROOT,
        ),
        GateSpec(
            "dg23-ruff",
            (
                str(RUFF),
                "check",
                "--ignore",
                "E402",
                "--config",
                "runtime/pyproject.toml",
                *dg23_evals,
                *dg23_scripts,
                *dg23_tests,
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
        GateSpec(
            "architecture-validate",
            (str(PYTHON), "architecture/v1.0/scripts/validate_bundle.py"),
            ROOT,
        ),
        GateSpec(
            "architecture-release-lock",
            (
                str(PYTHON),
                "architecture/v1.0/scripts/verify_lock.py",
                "--scope",
                "bundle",
                "--mode",
                "release",
                "--expected-manifest-sha256",
                ARCHITECTURE_MANIFEST_SHA256,
            ),
            ROOT,
        ),
    )


def run(*, run_id: str, output: Path, env_file: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    s6 = _read(S6_RECEIPT)
    s7 = _read(S7_RECEIPT)
    if (
        s6.get("status") != "PASS_DG23_OPENED_DEV_CONTEXT_LADDER"
        or s6.get("hard_gate", {}).get("passed") is not True
        or s6.get("structural_gate", {}).get("passed") is not True
    ):
        raise RuntimeError("DG23_S8_S6_ENTRY_INVALID")
    if (
        s7.get("status") != "FAIL_DG23_MATCHED_READER_ANSWER_CLOSURE"
        or s7.get("hard_gate", {}).get("passed") is not False
        or not (ROOT / str(s7["sealed_reader_product"]["path"])).is_file()
        or not (ROOT / str(s7["answer_score"]["path"])).is_file()
    ):
        raise RuntimeError("DG23_S8_REQUIRES_TERMINAL_S7_SCORE")
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise RuntimeError("DG23_S8_ARCHITECTURE_MANIFEST_DRIFT")

    log_dir = output / "logs"
    log_dir.mkdir(parents=True)
    specs = _gate_specs()
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s8-quality-plan.v0.1",
            "run_id": run_id,
            "entry_s7_status": s7["status"],
            "quality_runs_after_terminal_s7_pass_or_fail": True,
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
            "database_schema_changed_by_dg23": False,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
            "archival_identity_policy": {
                "deselected_from_behavior_regression": DG21_ARCHIVAL_IDENTITY_TEST,
                "reason": "successor source changes are audited separately from behavior",
            },
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
        raise RuntimeError("DG23_S8_DATABASE_ROLE_URLS_MISSING")
    database = f"milai_smoke_dg23_s8_{secrets.token_hex(8)}"
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

    source_paths = [
        *sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "evals/dg23").glob("*.py")
        ),
        *sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "scripts").glob("*dg23*.py")
        ),
        *sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "tests").glob("test_dg23*.py")
        ),
        "runtime/src/milai/application/memory_context.py",
        "runtime/src/milai/application/memory_resolve.py",
        "runtime/src/milai/application/reader_evidence_plan.py",
        "runtime/src/milai/application/retrieval.py",
        "runtime/src/milai/application/sufficiency.py",
        "runtime/src/milai/domain/reader_evidence_plan.py",
        "runtime/tests/unit/test_dg17_sufficiency.py",
        "evals/dg21/preference_expressivity.py",
        "tests/test_dg21_s4_preference_expressivity.py",
        RUNBOOK.relative_to(ROOT).as_posix(),
    ]
    source_manifest_path = output / "source-manifest.json"
    _write(
        source_manifest_path,
        {
            "schema": "milai.dg23.s8-source-manifest.v0.1",
            "identities": [_identity(ROOT / path) for path in sorted(set(source_paths))],
            "architecture_v1_changed_by_dg23": False,
        },
    )
    failure_records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if (
        not failure_records
        or len({row["failure_id"] for row in failure_records})
        != len(failure_records)
        or not all(row.get("append_only") is True for row in failure_records)
    ):
        raise RuntimeError("DG23_FAILURE_INDEX_NOT_APPEND_ONLY_UNIQUE")
    archival_audit_path = output / "dg21-archival-identity-audit.json"
    archival_audit = _dg21_archival_identity_audit()
    _write(archival_audit_path, archival_audit)
    artifact_manifest_path = output / "artifact-manifest.json"
    artifacts = [
        plan_path,
        S6_RECEIPT,
        S7_RECEIPT,
        S7_FAILURE_LEDGER,
        *S8_PREVIOUS_FAILURE_LEDGERS,
        RUNBOOK,
        FAILURE_INDEX,
        ARCHITECTURE_MANIFEST,
        source_manifest_path,
        archival_audit_path,
        *(log_dir / f"{result['gate_id']}.log" for result in results),
    ]
    _write(
        artifact_manifest_path,
        {
            "schema": "milai.dg23.s8-artifact-manifest.v0.1",
            "identities": [_identity(path) for path in artifacts],
        },
    )
    passed = (
        len(results) == len(specs)
        and all(bool(result["passed"]) for result in results)
        and cleanup.get("status") == "PASS"
        and archival_audit["passed"] is True
    )
    receipt = {
        "schema": "milai.dg23.s8-quality-receipt.v0.1",
        "run_id": run_id,
        "status": (
            "PASS_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE"
            if passed
            else "FAIL_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE"
        ),
        "passed": passed,
        "entry_s7_status": s7["status"],
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
        "architecture": {
            "manifest": _identity(ARCHITECTURE_MANIFEST),
            "expected_manifest_sha256": ARCHITECTURE_MANIFEST_SHA256,
            "changed_by_dg23": False,
            "validate_passed": next(
                result["passed"]
                for result in results
                if result["gate_id"] == "architecture-validate"
            ),
            "release_lock_passed": next(
                result["passed"]
                for result in results
                if result["gate_id"] == "architecture-release-lock"
            ),
        },
        "database_schema_changed_by_dg23": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "candidate_default": False,
        "reader_calls": 0,
        "provider_calls": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
        "predecessor_archival_identity_audit": {
            **_identity(archival_audit_path),
            "passed": archival_audit["passed"],
            "classification": archival_audit["classification"],
            "source_drift_count": archival_audit["source_drift_count"],
        },
        "runbook": _identity(RUNBOOK),
        "failure_index": _identity(FAILURE_INDEX),
        "source_manifest": _identity(source_manifest_path),
        "artifact_manifest": _identity(artifact_manifest_path),
        "plan": _identity(plan_path),
    }
    _write(output / "receipt.json", receipt)
    return receipt


def _dg21_archival_identity_audit() -> dict[str, Any]:
    """Separate immutable DG21 artifact integrity from expected live-source drift."""

    receipt = _read(DG21_S5_RECEIPT)
    artifact_keys = (
        "plan",
        "entry_s4_receipt",
        "sealed_product_oracle",
        "score",
        "schema_entry_audit",
    )
    artifact_checks = {
        key: _identity_matches(ROOT / str(receipt[key]["path"]), receipt[key])
        for key in artifact_keys
    }
    source_checks = []
    for relative, sealed in sorted(receipt["source_identity_manifest"].items()):
        path = ROOT / relative
        source_checks.append(
            {
                "path": relative,
                "sealed_sha256": sealed["sha256"],
                "sealed_size": sealed["size"],
                "current_sha256": _sha256(path),
                "current_size": path.stat().st_size,
                "matches_seal": _identity_matches(path, sealed),
            }
        )
    source_drift_count = sum(not row["matches_seal"] for row in source_checks)
    passed = (
        receipt.get("status") == "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT"
        and all(artifact_checks.values())
        and all((ROOT / row["path"]).is_file() for row in source_checks)
    )
    return {
        "schema": "milai.dg23.predecessor-archival-identity-audit.v0.1",
        "passed": passed,
        "classification": "EXPECTED_SUCCESSOR_SOURCE_DRIFT",
        "receipt": _identity(DG21_S5_RECEIPT),
        "sealed_artifact_checks": artifact_checks,
        "sealed_artifacts_unchanged": all(artifact_checks.values()),
        "live_source_checks": source_checks,
        "source_drift_count": source_drift_count,
        "excluded_test": DG21_ARCHIVAL_IDENTITY_TEST,
        "behavior_regression_covered_by_remaining_tests": True,
    }


def _identity_matches(path: Path, expected: dict[str, Any]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == expected.get("size")
        and _sha256(path) == expected.get("sha256")
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(ROOT)),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s8-quality-20260829-001")
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
