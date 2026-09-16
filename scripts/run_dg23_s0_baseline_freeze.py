#!/usr/bin/env python3
"""Execute DG-23 S0 predecessor and denominator freeze without labels or calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg23.baseline_freeze import run_baseline_freeze, source_manifest

SOURCE_PATHS = (
    "MiLAi_DG-23_预算稳定上下文编译与答案回归闭环_GOALS.md",
    "MiLAi_Lean_V1_实施合同.md",
    "evals/dg23/__init__.py",
    "evals/dg23/baseline_freeze.py",
    "scripts/run_dg23_s0_baseline_freeze.py",
    "tests/test_dg23_s0_baseline_freeze.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s0-baseline-freeze-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s0-plan.v0.1",
            "run_id": args.run_id,
            "mode": "PREDECESSOR_IDENTITY_DENOMINATOR_CONTROL_FREEZE",
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "source_labels_authorized": False,
            "formal_holdout_authorized": False,
            "runtime_behavior_change_authorized": False,
            "public_schema_change_authorized": False,
            "database_migration_authorized": False,
            "candidate_default": False,
        },
    )
    baseline = run_baseline_freeze(ROOT)
    baseline["run_id"] = args.run_id
    baseline_path = output / "baseline.json"
    _write(baseline_path, baseline)
    denominator_path = output / "denominator-freeze.json"
    _write(
        denominator_path,
        {
            "schema": "milai.dg23.s0-denominator-freeze.v0.1",
            "run_id": args.run_id,
            **baseline["denominator"],
        },
    )
    controls_path = output / "frozen-controls.json"
    _write(
        controls_path,
        {
            "schema": "milai.dg23.s0-frozen-controls.v0.1",
            "run_id": args.run_id,
            **baseline["frozen_controls"],
        },
    )
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    failure_index = ROOT / "var/dg23/failure-index.jsonl"
    failure_index.parent.mkdir(parents=True, exist_ok=True)
    failure_index.write_text("", encoding="utf-8")

    receipt = {
        "schema": "milai.dg23.s0-baseline-freeze-receipt.v0.1",
        "run_id": args.run_id,
        "status": baseline["status"],
        "hard_gate": baseline["hard_gate"],
        "plan": _identity(plan_path),
        "baseline": _identity(baseline_path),
        "denominator_freeze": _identity(denominator_path),
        "frozen_controls": _identity(controls_path),
        "source_manifest": _identity(manifest_path),
        "failure_index": _identity(failure_index),
        "label_boundary": baseline["label_boundary"],
        "safety": baseline["safety"],
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
