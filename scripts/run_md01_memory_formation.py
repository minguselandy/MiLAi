#!/usr/bin/env python3
"""Run and validate the sealed MD-01 Memory Formation bundle effect."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.md01.formation_bundle_effect import execute_md01_effect

RUN_ID = "md01-memory-formation-bundle-20260830-001"
OUTPUT_DIR = ROOT / "var/md01" / RUN_ID
RUN_LOCK = OUTPUT_DIR / "run-lock.json"
RESULTS = OUTPUT_DIR / "results.json"
TERMINAL = OUTPUT_DIR / "terminal.json"
RECEIPT = OUTPUT_DIR / "receipt.json"

REGRESSION_TARGETS = (
    "runtime/tests/unit/test_memory_formation_bundle.py",
    "runtime/tests/unit/test_mf03_formation_extraction.py",
    "runtime/tests/unit/test_mf04_state_change_formation.py",
    "tests/test_mf03_formation_effect.py",
    "tests/test_mf04_state_change_effect.py",
)
IMPLEMENTATION_PATHS = (
    "runtime/src/milai/domain/memory_formation.py",
    "runtime/src/milai/application/memory_formation.py",
    "evals/md01/formation_bundle_effect.py",
    "evals/md01/fixtures/contrasting-episodes.v0.1.json",
)


def run() -> dict[str, Any]:
    if any(path.exists() for path in (RESULTS, TERMINAL, RECEIPT)):
        raise RuntimeError("MD01_OUTPUT_ALREADY_EXISTS")
    results = execute_md01_effect(ROOT)
    regression = _run_regression()
    if (
        results["status"] == "PASS_MD01_MEMORY_FORMATION_CORE_PENDING_REGRESSION"
        and regression["passed"]
    ):
        status = "PASS_MD01_MEMORY_FORMATION_CORE"
    else:
        status = str(results["status"])
    terminal: dict[str, Any] = {
        "schema": "milai.md01.terminal.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "execution_authority": "USER_EXPLICIT_20260830_MD01_EXECUTE",
        "run_lock": _identity(RUN_LOCK),
        "results_digest": results["results_digest"],
        "implementation_identity": [
            _identity(ROOT / relative_path) for relative_path in IMPLEMENTATION_PATHS
        ],
        "hypotheses": {
            "MD01-H1": (
                "SUPPORTED_ON_SEALED_NON_HOLDOUT_VALIDATION"
                if all(
                    results["checks"][name]
                    for name in (
                        "raw_span_coverage_one",
                        "user_semantic_source_precision_one",
                        "artifact_lineage_closure_one",
                        "deterministic_replay_one",
                        "external_calls_zero",
                        "canonical_mutations_zero",
                    )
                )
                else "NOT_SUPPORTED"
            ),
            "MD01-H2": (
                "SUPPORTED_ON_SEALED_NON_HOLDOUT_VALIDATION"
                if all(
                    results["checks"][name]
                    for name in (
                        "episode_boundary_precision_threshold",
                        "episode_boundary_recall_threshold",
                        "episode_pairwise_f1_threshold",
                    )
                )
                else "NOT_SUPPORTED"
            ),
        },
        "metrics": results["metrics"],
        "checks": {
            **results["checks"],
            "mf03_mf04_regression_zero": regression["passed"],
        },
        "regression": regression,
        "safety": results["safety"],
        "scope": {
            "formal_holdout_used": False,
            "product_feature_flag_changed": False,
            "schema_changed": False,
            "public_mcp_changed": False,
            "database_accessed": False,
            "canonical_state_changed": False,
            "generalization_claim": "SEALED_NON_HOLDOUT_VALIDATION_ONLY",
        },
        "next_route": "EXPANDED_FORMATION_VALIDATION_BEFORE_PRODUCT_INTEGRATION",
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_exclusive(RESULTS, results)
    _write_exclusive(TERMINAL, terminal)
    receipt: dict[str, Any] = {
        "schema": "milai.md01.sidecar-receipt.v0.1",
        "run_id": RUN_ID,
        "status": status,
        "run_lock": _identity(RUN_LOCK),
        "results": _identity(RESULTS),
        "terminal": _identity(TERMINAL),
        "metrics": results["metrics"],
        "safety": results["safety"],
        "formal_holdout_used": False,
        "experimental_feature_flags": "OFF",
        "canonical": False,
        "canonical_mutation": False,
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    _write_exclusive(RECEIPT, receipt)
    return receipt


def validate() -> dict[str, Any]:
    run_lock = _object(RUN_LOCK)
    results = _object(RESULTS)
    terminal = _object(TERMINAL)
    receipt = _object(RECEIPT)
    _verify_embedded_digest(run_lock, "run_lock_digest")
    _verify_embedded_digest(results, "results_digest")
    _verify_embedded_digest(terminal, "terminal_digest")
    _verify_embedded_digest(receipt, "receipt_digest")
    if receipt["run_lock"] != _identity(RUN_LOCK):
        raise RuntimeError("MD01_RECEIPT_RUN_LOCK_LINK_INVALID")
    if receipt["results"] != _identity(RESULTS):
        raise RuntimeError("MD01_RECEIPT_RESULTS_LINK_INVALID")
    if receipt["terminal"] != _identity(TERMINAL):
        raise RuntimeError("MD01_RECEIPT_TERMINAL_LINK_INVALID")
    if (
        receipt["status"] != terminal["status"]
        or terminal["results_digest"] != results["results_digest"]
        or terminal["run_lock"] != _identity(RUN_LOCK)
        or not all(bool(value) for value in terminal["checks"].values())
    ):
        raise RuntimeError("MD01_TERMINAL_LINKAGE_INVALID")
    return {
        "valid": True,
        "status": receipt["status"],
        "receipt_digest": receipt["receipt_digest"],
        "metrics": receipt["metrics"],
    }


def _run_regression() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", *REGRESSION_TARGETS]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(RUNTIME_SRC)))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return {
        "command": command,
        "targets": list(REGRESSION_TARGETS),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _verify_embedded_digest(value: Mapping[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"MD01_DIGEST_INVALID:{field}")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    command_name = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command_name not in {"run", "validate"}:
        raise SystemExit("usage: run_md01_memory_formation.py [run|validate]")
    output = run() if command_name == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
