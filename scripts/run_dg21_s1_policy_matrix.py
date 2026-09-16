from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _value in (_ROOT, _ROOT / "runtime/src"):
    if str(_value) not in sys.path:
        sys.path.insert(0, str(_value))

from evals.dg21.synthetic_matrix import run_synthetic_matrix
from milai.application.acquisition_execution_policy import (
    default_acquisition_execution_policy,
)

_S0_RECEIPT = _ROOT / ("var/dg21/s0/dg21-s0-baseline-freeze-20260828-001/receipt.json")
_SOURCE_PATHS = (
    "runtime/src/milai/domain/acquisition_execution_policy.py",
    "runtime/src/milai/domain/acquisition_observation.py",
    "runtime/src/milai/application/acquisition_execution_policy.py",
    "runtime/src/milai/application/deterministic_recovery.py",
    "runtime/src/milai/domain/semantic_query.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/config/settings.py",
    "runtime/tests/unit/test_dg21_execution_policy_and_semantics.py",
    "evals/dg21/synthetic_matrix.py",
    "scripts/run_dg21_s1_policy_matrix.py",
    "tests/test_dg21_s1_synthetic_matrix.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg21-s1-policy-synthetic-20260828-004")
    args = parser.parse_args()
    output = _ROOT / "var/dg21/s1" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg21.s1-plan.v0.1",
        "run_id": args.run_id,
        "mode": "CONTENT_FREE_POLICY_SELECTOR_MATRIX",
        "entry_s0_receipt": _identity(_S0_RECEIPT),
        "minimum_synthetic_cells": 36,
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "automatic_retries_authorized": 0,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    policy = default_acquisition_execution_policy()
    policy_path = output / "acquisition-execution-policy-v0.2.json"
    _write_json(policy_path, policy.model_dump(mode="json"))

    matrix = run_synthetic_matrix()
    matrix["run_id"] = args.run_id
    matrix_path = output / "synthetic-selector-matrix.json"
    _write_json(matrix_path, matrix)

    source_manifest = {
        path: {
            "path": path,
            "sha256": _sha256(_ROOT / path),
            "size": (_ROOT / path).stat().st_size,
        }
        for path in _SOURCE_PATHS
    }
    receipt = {
        "schema": "milai.dg21.s1-policy-synthetic-receipt.v0.1",
        "status": matrix["status"],
        "run_id": args.run_id,
        "hard_gate": matrix["hard_gate"],
        "coverage": matrix["coverage"],
        "safety": matrix["safety"],
        "plan": _identity(plan_path),
        "entry_s0_receipt": _identity(_S0_RECEIPT),
        "policy": _identity(policy_path),
        "policy_digest": policy.policy_digest,
        "synthetic_selector_matrix": _identity(matrix_path),
        "source_identity_manifest": source_manifest,
    }
    receipt_path = output / "receipt.json"
    _write_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(_ROOT)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
