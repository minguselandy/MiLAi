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

from evals.dg21.baseline_freeze import run_baseline_freeze, source_manifest

_SOURCE_PATHS = (
    "MiLAi_DG-21_类型定向证据获取效率与时间完备性修复_GOALS.md",
    "MiLAi_Lean_V1_实施合同.md",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/deterministic_recovery.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/memory_query.py",
    "runtime/src/milai/domain/deterministic_recovery.py",
    "runtime/src/milai/domain/requirement_state.py",
    "runtime/src/milai/domain/evidence.py",
    "runtime/src/milai/persistence/retrieval_repository.py",
    "evals/dg21/baseline_freeze.py",
    "scripts/run_dg21_s0_baseline_freeze.py",
    "tests/test_dg21_s0_baseline_freeze.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg21-s0-baseline-freeze-20260828-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg21/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg21.s0-plan.v0.1",
        "run_id": args.run_id,
        "mode": "BASELINE_CONTRACT_FREEZE",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE",
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "runtime_behavior_change_authorized": False,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
        "formal_holdout_case_ids_loaded": [],
        "token_budget": 2048,
        "policy_sweep_candidate_caps": [8, 12, 16],
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    baseline = run_baseline_freeze(_ROOT)
    baseline["run_id"] = args.run_id
    baseline["source_identity_manifest"] = source_manifest(_ROOT, _SOURCE_PATHS)
    baseline_path = output / "baseline.json"
    _write_json(baseline_path, baseline)

    first_loss = {
        "schema": "milai.dg21.s0-first-loss-ledger.v0.1",
        "run_id": args.run_id,
        "classification": baseline["classification"],
        "record_count": len(baseline["first_loss_records"]),
        "records": baseline["first_loss_records"],
        "distribution": baseline["first_loss_distribution"],
        "assignment_rate": 1.0,
        "one_first_loss_per_unresolved_requirement": baseline["hard_gate"]["checks"][
            "first_loss_unique_per_requirement"
        ],
        "formal_holdout_consumed": False,
    }
    first_loss_path = output / "first-loss-ledger.json"
    _write_json(first_loss_path, first_loss)

    receipt = {
        "schema": "milai.dg21.s0-baseline-freeze-receipt.v0.1",
        "status": baseline["status"],
        "run_id": args.run_id,
        "hard_gate": baseline["hard_gate"],
        "plan": _identity(plan_path),
        "baseline": _identity(baseline_path),
        "first_loss_ledger": _identity(first_loss_path),
        "artifact_identities": baseline["artifact_identities"],
        "upstream_stage_receipts": baseline["upstream_stage_receipts"],
        "source_identity_manifest": baseline["source_identity_manifest"],
        "safety": baseline["safety"],
        "formal_holdout": baseline["formal_holdout"],
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
