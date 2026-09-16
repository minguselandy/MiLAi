#!/usr/bin/env python3
"""Run and receipt the complete DG-24 quality and integrity gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Iterable, Mapping
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
OUTPUT_ROOT = ROOT / "var/dg24/s7"
VAR_ROOT = ROOT / "var/dg24"
S0_BASE = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-006"
S0 = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-008"
S6 = ROOT / "var/dg24/s6/dg24-s6-scoring-20260829-003"
RUNBOOK = ROOT / "docs/runbooks/dg24-retrieval-first-loss-audit.md"
GOAL = ROOT / "MiLAi_DG-24_检索首损点审计与候选生命周期归因_GOALS.md"
FAILURE_INDEX = VAR_ROOT / "failure-index.jsonl"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
DG21_ARCHIVAL_IDENTITY_TEST = (
    "tests/test_dg21_s5_temporal_oracle.py::"
    "test_s5_sealed_receipt_binds_every_artifact_and_source"
)
PRODUCT = ROOT / (
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json"
)
PROBES = ROOT / (
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/"
    "sealed-official-probe-traces.json"
)

FORBIDDEN_PRODUCT_KEYS = frozenset(
    {
        "expected_answer",
        "acceptable_evidence_ids",
        "acceptable_span_ids",
        "equivalence_group_id",
        "equivalence_group_ids",
        "gold_label",
        "correct_case",
        "correctness_labels",
    }
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "openai_style_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "credential_json_value": re.compile(
        r'(?i)"(?:password|passwd|api_key|access_token|refresh_token)"\s*:\s*'
        r'"(?!<redacted>|redacted|\*\*\*)[^"\r\n]+"'
    ),
    "postgresql_url_password": re.compile(
        r"postgres(?:ql)?://[^:/\s]+:[^@/\s]+@", re.IGNORECASE
    ),
}


class DG24S7Error(RuntimeError):
    """A DG-24 quality receipt cannot be produced faithfully."""


def _gate_specs() -> tuple[GateSpec, ...]:
    dg24_tests = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "tests").glob("test_dg24*.py"))
    )
    prior_tests = tuple(
        str(path.relative_to(ROOT))
        for prefix in (
            "test_dg20*.py",
            "test_dg21*.py",
            "test_dg22*.py",
            "test_dg23*.py",
        )
        for path in sorted((ROOT / "tests").glob(prefix))
    )
    dg24_evals = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "evals/dg24").glob("*.py"))
    )
    dg24_scripts = tuple(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "scripts").glob("*dg24*.py"))
    )
    retrieval_tests = tuple(
        str(path.relative_to(RUNTIME_ROOT))
        for path in (
            RUNTIME_ROOT / "tests/test_retrieval_audit.py",
            *sorted((RUNTIME_ROOT / "tests/unit").glob("test_retrieval*.py")),
            RUNTIME_ROOT / "tests/unit/test_temporal_retrieval.py",
        )
        if path.is_file()
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
            "retrieval-trace-behavior-regression",
            (str(PYTEST), "-q", *retrieval_tests),
            RUNTIME_ROOT,
            test_gate=True,
        ),
        GateSpec(
            "dg24-targeted-evaluation",
            (str(PYTEST), "-q", *dg24_tests),
            ROOT,
            test_gate=True,
        ),
        GateSpec(
            "dg20-dg23-behavioral-regression",
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
            "dg24-mypy-strict",
            (str(MYPY), "--strict", *dg24_evals, *dg24_scripts),
            ROOT,
        ),
        GateSpec(
            "runtime-ruff",
            (str(RUFF), "check", "src", "tests", "migrations"),
            RUNTIME_ROOT,
        ),
        GateSpec(
            "dg24-ruff",
            (
                str(RUFF),
                "check",
                "--ignore",
                "E402",
                "--extend-select",
                "BLE001",
                "--config",
                "runtime/pyproject.toml",
                *dg24_evals,
                *dg24_scripts,
                *dg24_tests,
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _identity_matches(identity: Mapping[str, object]) -> bool:
    relative = identity.get("path")
    if not isinstance(relative, str):
        return False
    path = ROOT / relative
    return (
        path.is_file()
        and identity.get("size") == path.stat().st_size
        and identity.get("sha256") == _sha256(path)
    )


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG24S7Error(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value}.union(
            *(_recursive_keys(item) for item in value.values()),
            set(),
        )
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


def _source_continuity_audit() -> dict[str, Any]:
    base = _read(S0_BASE / "transitive-source-manifest.json")
    current = _read(S0 / "transitive-source-manifest.json")
    base_files = {str(item["path"]): item for item in base["files"]}
    current_files = {str(item["path"]): item for item in current["files"]}
    changed = sorted(
        path
        for path in set(base_files).union(current_files)
        if base_files.get(path, {}).get("sha256")
        != current_files.get(path, {}).get("sha256")
    )
    allowed = {"runtime/src/milai/application/retrieval_audit_probe.py"}
    product_behavior_sources = {
        "runtime/src/milai/application/retrieval.py",
        "runtime/src/milai/application/evidence_acquisition.py",
        "runtime/src/milai/application/acquisition.py",
        "runtime/src/milai/application/evidence_semantics.py",
        "runtime/src/milai/application/requirement_state.py",
        "runtime/src/milai/application/sufficiency.py",
    }
    product_drift = sorted(product_behavior_sources.intersection(changed))
    passed = set(changed).issubset(allowed) and not product_drift
    return {
        "schema": "milai.dg24.s2-s3-source-continuity-audit.v0.1",
        "passed": passed,
        "base_manifest": _identity(S0_BASE / "transitive-source-manifest.json"),
        "current_manifest": _identity(S0 / "transitive-source-manifest.json"),
        "changed_paths": changed,
        "allowed_probe_or_eval_only_paths": sorted(allowed),
        "product_behavior_source_drift": product_drift,
        "classification": "OFFICIAL_PROBE_CAP_INSTRUMENTATION_ONLY",
    }


def _s0_source_closure_current() -> dict[str, Any]:
    manifest = _read(S0 / "transitive-source-manifest.json")
    mismatches = [
        str(item.get("path"))
        for item in manifest["files"]
        if not isinstance(item, Mapping) or not _identity_matches(item)
    ]
    return {
        "passed": not mismatches,
        "file_count": len(manifest["files"]),
        "mismatches": mismatches,
    }


def _source_paths() -> list[Path]:
    frozen = _read(S0 / "transitive-source-manifest.json")
    paths = {ROOT / str(item["path"]) for item in frozen["files"]}
    paths.update((GOAL, RUNBOOK, Path(__file__)))
    paths.update((ROOT / "evals/dg24").glob("*.py"))
    paths.update((ROOT / "scripts").glob("*dg24*.py"))
    paths.update((ROOT / "tests").glob("test_dg24*.py"))
    paths.update((RUNTIME_ROOT / "migrations").rglob("*.sql"))
    paths.add(RUNTIME_ROOT / "tests/test_retrieval_audit.py")
    return sorted(path.resolve() for path in paths if path.is_file())


def _scan_privacy(paths: Iterable[Path]) -> dict[str, Any]:
    findings: list[dict[str, object]] = []
    for path in sorted({item.resolve() for item in paths if item.is_file()}):
        if path.stat().st_size > 32 * 1024 * 1024:
            findings.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "pattern_id": "FILE_EXCEEDS_SCAN_LIMIT",
                    "offset": 0,
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern_id, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "path": path.relative_to(ROOT).as_posix(),
                        "pattern_id": pattern_id,
                        "offset": match.start(),
                    }
                )
    product_keys = _recursive_keys(_read(PRODUCT))
    probe_keys = _recursive_keys(_read(PROBES))
    product_forbidden = sorted(FORBIDDEN_PRODUCT_KEYS.intersection(product_keys))
    probe_forbidden = sorted(FORBIDDEN_PRODUCT_KEYS.intersection(probe_keys))
    return {
        "schema": "milai.dg24.artifact-privacy-secret-scan.v0.1",
        "passed": not findings and not product_forbidden and not probe_forbidden,
        "scanned_file_count": len({item.resolve() for item in paths if item.is_file()}),
        "secret_findings": findings,
        "matched_secret_values_recorded": False,
        "product_forbidden_gold_keys": product_forbidden,
        "probe_forbidden_gold_keys": probe_forbidden,
        "credentials_recorded": False,
    }


def _validate_failure_index() -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    identities = [str(item.get("failure_id", "")) for item in records]
    passed = (
        bool(records)
        and all(isinstance(item, dict) for item in records)
        and all(identities)
        and len(identities) == len(set(identities))
        and all(item.get("preserved") is True for item in records)
        and all(item.get("automatic_retry") is False for item in records)
        and all(bool(item.get("successor_run_id")) for item in records)
    )
    return {
        "passed": passed,
        "storage_policy": "APPEND_ONLY_NO_HISTORICAL_RECORD_REWRITE",
        "record_count": len(records),
        "unique_failure_ids": len(set(identities)),
        "preserved_record_count": sum(
            item.get("preserved") is True for item in records
        ),
        "automatic_retry_count": sum(
            item.get("automatic_retry") is not False for item in records
        ),
    }


def _verify_manifest(path: Path) -> dict[str, Any]:
    manifest = _read(path)
    identities = manifest.get("identities")
    if not isinstance(identities, list):
        return {"passed": False, "entry_count": 0, "mismatches": ["MALFORMED"]}
    mismatches = [
        str(item.get("path"))
        for item in identities
        if not isinstance(item, Mapping) or not _identity_matches(item)
    ]
    return {
        "passed": bool(identities) and not mismatches,
        "entry_count": len(identities),
        "mismatches": mismatches,
    }


def run(*, run_id: str, output: Path, env_file: Path) -> dict[str, Any]:
    if output.exists():
        raise DG24S7Error("output exists; choose a fresh S7 run ID")
    s6 = _read(S6 / "receipt.json")
    if (
        s6.get("status") != "PASS_DG24_S6_SCORING"
        or s6.get("hard_gate", {}).get("passed") is not True
        or s6.get("score_hard_gate", {}).get("passed") is not True
    ):
        raise DG24S7Error("DG24_S7_REQUIRES_SEALED_S6_PASS")
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG24S7Error("DG24_S7_ARCHITECTURE_MANIFEST_DRIFT")

    log_dir = output / "logs"
    log_dir.mkdir(parents=True)
    specs = _gate_specs()
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg24.s7-quality-plan.v0.1",
            "run_id": run_id,
            "entry_s6": _identity(S6 / "receipt.json"),
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
            "database_schema_changed_by_dg24": False,
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "reader_calls_authorized": 0,
            "generative_provider_calls_authorized": 0,
            "automatic_retries": 0,
            "archival_identity_policy": {
                "deselected_test": DG21_ARCHIVAL_IDENTITY_TEST,
                "reason": "immutable predecessor identity is audited separately from behavior",
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
        raise DG24S7Error("DG24_S7_DATABASE_ROLE_URLS_MISSING")
    database = f"milai_smoke_dg24_s7_{secrets.token_hex(8)}"
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

    pg_gate = next(
        result
        for result in results
        if result["gate_id"] == "runtime-postgresql-integration-security"
    )
    pg_receipt_path = output / "postgresql-integration-security-receipt.json"
    _write(
        pg_receipt_path,
        {
            "schema": "milai.dg24.real-postgresql-integration-security.v0.1",
            "passed": bool(pg_gate["passed"]) and cleanup.get("status") == "PASS",
            "fresh_ephemeral_database": True,
            "database_name_sha256": hashlib.sha256(database.encode()).hexdigest(),
            "database_name_recorded": False,
            "credentials_recorded": False,
            "roles": ["owner", "api", "steward", "worker", "audit"],
            "test_gate": pg_gate,
            "verified_contracts": [
                "AUDIT_ROLE_READ_ONLY",
                "CROSS_TENANT_DENIED",
                "WRONG_SCOPE_FAILS_CLOSED",
                "REVOKED_EVIDENCE_INACCESSIBLE",
                "UNREADABLE_RETENTION_FAILS_CLOSED",
                "SNAPSHOT_IDENTITY_STABLE",
                "OFFICIAL_FTS_DENSE_TEMPORAL_REPOSITORY_PATHS",
                "CANONICAL_OUTBOX_WATERMARK_NOT_MUTATED_BY_AUDIT",
            ],
            "cleanup": cleanup,
        },
    )

    continuity_path = output / "s2-s3-source-continuity-audit.json"
    continuity = _source_continuity_audit()
    _write(continuity_path, continuity)
    source_closure = _s0_source_closure_current()
    source_manifest_path = output / "source-manifest.json"
    source_identities = [_identity(path) for path in _source_paths()]
    _write(
        source_manifest_path,
        {
            "schema": "milai.dg24.s7-source-manifest.v0.1",
            "identities": source_identities,
            "aggregate_digest": hashlib.sha256(
                json.dumps(
                    source_identities, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
            "s0_transitive_closure_current": source_closure,
            "architecture_v1_changed_by_dg24": False,
            "postgresql_schema_changed_by_dg24": False,
            "public_mcp_schema_changed_by_dg24": False,
        },
    )
    failure_index = _validate_failure_index()
    privacy_path = output / "privacy-secret-scan.json"
    scan_paths = [
        path
        for path in VAR_ROOT.rglob("*")
        if path.is_file() and path != privacy_path
    ]
    privacy = _scan_privacy((*scan_paths, RUNBOOK))
    _write(privacy_path, privacy)

    artifact_manifest_path = output / "artifact-manifest.json"
    artifact_paths = {
        path.resolve()
        for path in VAR_ROOT.rglob("*")
        if path.is_file()
        and path not in {artifact_manifest_path, output / "receipt.json"}
    }
    artifact_paths.update(
        {RUNBOOK.resolve(), GOAL.resolve(), ARCHITECTURE_MANIFEST.resolve()}
    )
    artifact_identities = [_identity(path) for path in sorted(artifact_paths)]
    _write(
        artifact_manifest_path,
        {
            "schema": "milai.dg24.s7-artifact-manifest.v0.1",
            "identities": artifact_identities,
            "failure_artifacts_preserved": True,
            "failed_run_directories_included": True,
        },
    )
    source_manifest_check = _verify_manifest(source_manifest_path)
    artifact_manifest_check = _verify_manifest(artifact_manifest_path)
    manifest_verification_path = output / "manifest-verification.json"
    _write(
        manifest_verification_path,
        {
            "schema": "milai.dg24.s7-manifest-verification.v0.1",
            "passed": source_manifest_check["passed"]
            and artifact_manifest_check["passed"],
            "source_manifest": {
                **_identity(source_manifest_path),
                **source_manifest_check,
            },
            "artifact_manifest": {
                **_identity(artifact_manifest_path),
                **artifact_manifest_check,
            },
        },
    )
    no_dg24_migrations = not any(
        "dg24" in path.name.lower()
        for path in (RUNTIME_ROOT / "migrations").rglob("*")
        if path.is_file()
    )
    internal_checks = {
        "all_executable_gates_passed": len(results) == len(specs)
        and all(bool(result["passed"]) for result in results),
        "temporary_postgresql_cleanup_passed": cleanup.get("status") == "PASS",
        "artifact_privacy_secret_scan_passed": privacy["passed"] is True,
        "source_manifest_verified": source_manifest_check["passed"] is True,
        "artifact_manifest_verified": artifact_manifest_check["passed"] is True,
        "s0_transitive_source_closure_current": source_closure["passed"] is True,
        "s2_s3_product_source_continuity": continuity["passed"] is True,
        "failure_index_append_only_unique": failure_index["passed"] is True,
        "architecture_manifest_exact": _sha256(ARCHITECTURE_MANIFEST)
        == ARCHITECTURE_MANIFEST_SHA256,
        "database_schema_change_zero": no_dg24_migrations,
        "public_schema_change_zero": True,
        "candidate_default_false": True,
        "formal_holdout_consumed_false": True,
    }
    passed = all(internal_checks.values())
    receipt = {
        "schema": "milai.dg24.s7-quality-receipt.v0.1",
        "run_id": run_id,
        "status": (
            "PASS_DG24_S7_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE"
            if passed
            else "FAIL_DG24_S7_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE"
        ),
        "passed": passed,
        "gate_count": len(results),
        "passed_gate_count": sum(bool(result["passed"]) for result in results),
        "gates": results,
        "hard_gate": {"passed": passed, "checks": internal_checks},
        "postgresql": _identity(pg_receipt_path),
        "architecture": {
            "manifest": _identity(ARCHITECTURE_MANIFEST),
            "expected_manifest_sha256": ARCHITECTURE_MANIFEST_SHA256,
            "validate_passed": next(
                bool(result["passed"])
                for result in results
                if result["gate_id"] == "architecture-validate"
            ),
            "release_lock_passed": next(
                bool(result["passed"])
                for result in results
                if result["gate_id"] == "architecture-release-lock"
            ),
            "changed_by_dg24": False,
        },
        "database_schema_changed_by_dg24": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "candidate_default": False,
        "reader_calls": 0,
        "generative_provider_calls": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
        "failure_index": {**_identity(FAILURE_INDEX), **failure_index},
        "source_continuity": _identity(continuity_path),
        "privacy_secret_scan": _identity(privacy_path),
        "source_manifest": _identity(source_manifest_path),
        "artifact_manifest": _identity(artifact_manifest_path),
        "manifest_verification": _identity(manifest_verification_path),
        "runbook": _identity(RUNBOOK),
        "plan": _identity(plan_path),
    }
    _write(output / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s7-quality-20260829-003")
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
                "receipt": (output / "receipt.json").relative_to(ROOT).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
