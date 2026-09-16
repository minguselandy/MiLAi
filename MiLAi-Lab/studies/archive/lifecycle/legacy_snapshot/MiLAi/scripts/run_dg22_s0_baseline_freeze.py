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

from evals.dg22.baseline_freeze import run_baseline_freeze, source_manifest

_SOURCE_PATHS = (
    "MiLAi_DG-22_证据召回准确性与答案正确性闭环_GOALS.md",
    "MiLAi_Lean_V1_实施合同.md",
    "evals/dg22/__init__.py",
    "evals/dg22/baseline_freeze.py",
    "scripts/run_dg22_s0_baseline_freeze.py",
    "tests/test_dg22_s0_baseline_freeze.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s0-baseline-freeze-20260829-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg22.s0-plan.v0.1",
        "run_id": args.run_id,
        "mode": "BASELINE_IDENTITY_DENOMINATOR_FREEZE",
        "classification": "PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE",
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "runtime_behavior_change_authorized": False,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
        "formal_holdout_case_ids_loaded": [],
        "quarantined_identity_reissue_authorized": False,
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    baseline = run_baseline_freeze(_ROOT)
    baseline["run_id"] = args.run_id
    baseline_path = output / "baseline.json"
    _write_json(baseline_path, baseline)

    denominator_path = output / "denominator-freeze.json"
    _write_json(
        denominator_path,
        {
            "schema": "milai.dg22.s0-denominator-freeze.v0.1",
            "run_id": args.run_id,
            **baseline["denominator_freeze"],
        },
    )
    quarantine_path = output / "reader-quarantine.json"
    _write_json(
        quarantine_path,
        {
            "schema": "milai.dg22.s0-reader-quarantine.v0.1",
            "run_id": args.run_id,
            **baseline["reader_quarantine"],
            "reissue_count": 0,
        },
    )
    manifest = source_manifest(_ROOT, _SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "current-source-manifest.json"
    _write_json(manifest_path, manifest)

    receipt = {
        "schema": "milai.dg22.s0-baseline-freeze-receipt.v0.1",
        "run_id": args.run_id,
        "status": baseline["status"],
        "hard_gate": baseline["hard_gate"],
        "plan": _identity(plan_path),
        "baseline": _identity(baseline_path),
        "denominator_freeze": _identity(denominator_path),
        "reader_quarantine": _identity(quarantine_path),
        "current_source_manifest": _identity(manifest_path),
        "predecessor_identity_validation": baseline["predecessor_identity_validation"],
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


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
