#!/usr/bin/env python3
"""Run and validate the sole sealed MF-02 four-arm representation effect."""

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

from evals.mf02.four_arm_effect import execute_mf02_effect

RUN_ID = "mf02-semantic-episode-four-arm-20260830-001"
OUTPUT_DIR = ROOT / "var/mf02" / RUN_ID
RUN_LOCK = OUTPUT_DIR / "run-lock.json"
RESULTS = OUTPUT_DIR / "results.json"
TERMINAL = OUTPUT_DIR / "terminal.json"
RECEIPT = OUTPUT_DIR / "receipt.json"

LEGAL_STATUSES = {
    "PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION",
    "PASS_MF02_REPRESENTATION_ONLY_NO_READ_GAIN",
    "PARKED_MF02_SIMPLE_SEGMENTATION_SUFFICIENT",
    "PARKED_MF02_DATA_OR_REPRESENTATION_UNRESOLVED",
    "FAIL_MF02_RAW_OR_AUTHORITY_BOUNDARY",
}
REGRESSION_TARGETS = (
    "runtime/tests/unit/test_memory_formation_bundle.py",
    "runtime/tests/unit/test_mf03_formation_extraction.py",
    "runtime/tests/unit/test_mf04_state_change_formation.py",
    "tests/test_md01_formation_bundle_effect.py",
    "tests/test_md01_artifacts.py",
    "tests/test_mf02_four_arm_effect.py",
    "tests/test_mf03_formation_effect.py",
    "tests/test_mf04_state_change_effect.py",
)
IMPLEMENTATION_PATHS = (
    "runtime/src/milai/domain/memory_formation.py",
    "runtime/src/milai/application/memory_formation.py",
    "evals/mf02/four_arm_effect.py",
    "evals/mf02/fixtures/repair-dev.v0.1.json",
    "evals/mf02/fixtures/sealed-validation.v0.1.json",
    "scripts/seal_mf02_labels.py",
    "scripts/run_mf02_semantic_episode.py",
)


def run() -> dict[str, Any]:
    if not RUN_LOCK.is_file():
        raise RuntimeError("MF02_RUN_LOCK_MISSING")
    if any(path.exists() for path in (RESULTS, TERMINAL, RECEIPT)):
        raise RuntimeError("MF02_OFFICIAL_OUTPUT_ALREADY_EXISTS")
    regression = _run_regression()
    if not regression["passed"]:
        raise RuntimeError("MF02_PRE_EFFECT_REGRESSION_FAILED")

    results = execute_mf02_effect(ROOT)
    status = str(results["status"])
    if status not in LEGAL_STATUSES:
        raise RuntimeError("MF02_ILLEGAL_TERMINAL_STATUS")
    terminal: dict[str, Any] = {
        "schema": "milai.mf02.terminal.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "execution_authority": "USER_EXPLICIT_20260830_MF02_EXECUTE",
        "effect_attempt": 1,
        "run_lock": _identity(RUN_LOCK),
        "results_digest": results["results_digest"],
        "prediction_digest_before_scoring": results["prediction_digest_before_scoring"],
        "implementation_identity": [
            _identity(ROOT / relative_path) for relative_path in IMPLEMENTATION_PATHS
        ],
        "hypotheses": results["hypotheses"],
        "direct": results["metrics"]["direct"],
        "simple_read": results["metrics"]["simple_read"],
        "failure_distribution": results["metrics"]["failure_distribution"],
        "checks": results["checks"],
        "md01_scorer_sanity": results["md01_scorer_sanity"],
        "regression": regression,
        "safety": results["safety"],
        "scope": {
            "claim": "SEALED_NON_HOLDOUT_REPRESENTATION_GENERALIZATION_ONLY",
            "product_retrieval_recall_claimed": False,
            "formal_holdout_used": False,
            "schema_changed": False,
            "public_mcp_changed": False,
            "database_accessed": False,
            "canonical_state_changed": False,
            "product_feature_flag_changed": False,
            "durable_episode_created": False,
        },
        "next_route": _next_route(status),
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_exclusive(RESULTS, results)
    _write_exclusive(TERMINAL, terminal)
    receipt: dict[str, Any] = {
        "schema": "milai.mf02.sidecar-receipt.v0.1",
        "run_id": RUN_ID,
        "status": status,
        "effect_attempt": 1,
        "run_lock": _identity(RUN_LOCK),
        "results": _identity(RESULTS),
        "terminal": _identity(TERMINAL),
        "hypotheses": results["hypotheses"],
        "direct_summary": {
            "semantic_episode_pairwise_f1": results["metrics"]["direct"][
                "semantic_pairwise_f1"
            ],
            "strongest_simple_baseline": results["metrics"]["direct"][
                "strongest_simple_baseline"
            ],
            "paired_macro_delta": results["metrics"]["direct"][
                "paired_macro_delta_vs_strongest_simple"
            ],
        },
        "simple_read_summary": {
            "semantic_support_closure_auc": results["metrics"]["simple_read"][
                "semantic_support_closure_auc"
            ],
            "strongest_simple_baseline": results["metrics"]["simple_read"][
                "strongest_simple_baseline"
            ],
            "paired_macro_delta": results["metrics"]["simple_read"][
                "paired_macro_delta_vs_strongest_simple"
            ],
            "distractor_turn_rate_delta": results["metrics"]["simple_read"][
                "semantic_distractor_turn_rate_delta_vs_strongest_simple"
            ],
        },
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
    status = str(receipt["status"])
    if status not in LEGAL_STATUSES or status != terminal["status"]:
        raise RuntimeError("MF02_TERMINAL_STATUS_INVALID")
    if receipt["run_lock"] != _identity(RUN_LOCK):
        raise RuntimeError("MF02_RECEIPT_RUN_LOCK_LINK_INVALID")
    if receipt["results"] != _identity(RESULTS):
        raise RuntimeError("MF02_RECEIPT_RESULTS_LINK_INVALID")
    if receipt["terminal"] != _identity(TERMINAL):
        raise RuntimeError("MF02_RECEIPT_TERMINAL_LINK_INVALID")
    if (
        terminal["results_digest"] != results["results_digest"]
        or terminal["run_lock"] != _identity(RUN_LOCK)
        or terminal["prediction_digest_before_scoring"]
        != results["prediction_digest_before_scoring"]
        or terminal["effect_attempt"] != 1
        or receipt["effect_attempt"] != 1
    ):
        raise RuntimeError("MF02_TERMINAL_LINKAGE_INVALID")
    if terminal["implementation_identity"] != [
        _identity(ROOT / relative_path) for relative_path in IMPLEMENTATION_PATHS
    ]:
        raise RuntimeError("MF02_IMPLEMENTATION_DRIFT_AFTER_EFFECT")
    if {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()} != {
        "run-lock.json",
        "results.json",
        "terminal.json",
        "receipt.json",
    }:
        raise RuntimeError("MF02_MAJOR_ARTIFACT_SET_INVALID")
    if status == "PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION" and not all(
        bool(value) for value in terminal["checks"].values()
    ):
        raise RuntimeError("MF02_PASS_CHECKS_INCOMPLETE")
    if (
        not terminal["regression"]["passed"]
        or not terminal["md01_scorer_sanity"]["passed"]
    ):
        raise RuntimeError("MF02_REGRESSION_OR_SANITY_FAILED")
    return {
        "valid": True,
        "status": status,
        "receipt_digest": receipt["receipt_digest"],
        "direct_summary": receipt["direct_summary"],
        "simple_read_summary": receipt["simple_read_summary"],
        "safety": receipt["safety"],
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
        timeout=240,
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


def _next_route(status: str) -> str:
    if status == "PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION":
        return "ELIGIBLE_FOR_SEPARATELY_AUTHORIZED_PRODUCT_SHADOW_DESIGN"
    if status == "PASS_MF02_REPRESENTATION_ONLY_NO_READ_GAIN":
        return "KEEP_NONCANONICAL_SIDECAR_NO_PRODUCT_INTEGRATION"
    return "PARK_SEMANTIC_EPISODE_PRODUCT_ROUTE"


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
        raise RuntimeError(f"MF02_DIGEST_INVALID:{field}")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"MF02_JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    command_name = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command_name not in {"run", "validate"}:
        raise SystemExit("usage: run_mf02_semantic_episode.py [run|validate]")
    output = run() if command_name == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
