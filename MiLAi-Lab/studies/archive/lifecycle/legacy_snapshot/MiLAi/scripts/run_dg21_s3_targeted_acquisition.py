from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_SRC = _ROOT / "runtime/src"
for _path in (_ROOT, _RUNTIME_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evals.dg21.targeted_acquisition import run_targeted_acquisition_matrix

_S2_RECEIPT = _ROOT / (
    "var/dg21/s2/dg21-s2-type-directed-replay-20260828-004/receipt.json"
)
_SOURCE_PATHS = (
    "runtime/src/milai/domain/acquisition_observation.py",
    "runtime/src/milai/domain/deterministic_recovery.py",
    "runtime/src/milai/domain/semantic_query.py",
    "runtime/src/milai/application/source_time.py",
    "runtime/src/milai/application/query_ir_compat.py",
    "runtime/src/milai/application/acquisition.py",
    "runtime/src/milai/application/acquisition_capability.py",
    "runtime/src/milai/application/acquisition_execution_policy.py",
    "runtime/src/milai/application/deterministic_recovery.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/tests/unit/test_dg21_targeted_acquisition.py",
    "evals/dg21/targeted_acquisition.py",
    "scripts/run_dg21_s3_targeted_acquisition.py",
    "tests/test_dg21_s3_targeted_acquisition.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default="dg21-s3-targeted-source-adjacency-20260828-005",
    )
    args = parser.parse_args()
    output = _ROOT / "var/dg21/s3" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg21.s3-plan.v0.1",
        "run_id": args.run_id,
        "work_packages": ["DG21-WP03", "DG21-WP04_NON_PREFERENCE"],
        "mode": "OFFICIAL_EXECUTOR_SYNTHETIC_PLUS_OPENED_DEV_DIAGNOSIS",
        "entry_s2_receipt": _identity(_S2_RECEIPT),
        "candidate_budget_sweep": [8, 12, 16],
        "preference_ir_changes_authorized": False,
        "temporal_projection_changes_authorized": False,
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "automatic_retries_authorized": 0,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    matrix = run_targeted_acquisition_matrix(_ROOT)
    matrix["run_id"] = args.run_id
    matrix_path = output / "targeted-acquisition-matrix.json"
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
        "schema": "milai.dg21.s3-targeted-acquisition-receipt.v0.1",
        "status": matrix["status"],
        "run_id": args.run_id,
        "policy_digest": matrix["policy_digest"],
        "selected_candidate_policy": matrix["selected_candidate_policy"],
        "metrics": matrix["metrics"],
        "opened_9a_diagnosis": matrix["opened_9a_diagnosis"],
        "hard_gate": matrix["hard_gate"],
        "safety": matrix["safety"],
        "plan": _identity(plan_path),
        "entry_s2_receipt": _identity(_S2_RECEIPT),
        "targeted_acquisition_matrix": _identity(matrix_path),
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
