#!/usr/bin/env python3
"""Execute the DG-23 S1 label-closed historical budget causality audit."""

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

from evals.dg23.baseline_freeze import source_manifest
from evals.dg23.budget_causality import build_budget_causality_audit

SOURCE_PATHS = (
    "evals/dg23/budget_causality.py",
    "scripts/run_dg23_s1_budget_causality.py",
    "tests/test_dg23_s1_budget_causality.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s1-budget-causality-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s1" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s1-plan.v0.1",
            "run_id": args.run_id,
            "mode": "RETROSPECTIVE_LABEL_CLOSED_FIRST_DIVERGENCE_AUDIT",
            "budgets": [512, 2048],
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "source_labels_authorized": False,
            "formal_holdout_authorized": False,
            "runtime_behavior_change_authorized": False,
        },
    )
    audit = build_budget_causality_audit(ROOT)
    audit["run_id"] = args.run_id
    product_path = output / "sealed-budget-causality-product.json"
    _write(product_path, audit)
    trace_path = output / "first-divergence-trace.json"
    _write(
        trace_path,
        {
            "schema": "milai.dg23.s1-first-divergence-trace.v0.1",
            "run_id": args.run_id,
            "order": audit["first_divergence_order"],
            "traces": audit["first_divergence_traces"],
            "affected_case": audit["affected_case"],
        },
    )
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    receipt = {
        "schema": "milai.dg23.s1-budget-causality-receipt.v0.1",
        "run_id": args.run_id,
        "status": audit["status"],
        "hard_gate": audit["hard_gate"],
        "plan": _identity(plan_path),
        "sealed_product": _identity(product_path),
        "first_divergence_trace": _identity(trace_path),
        "source_manifest": _identity(manifest_path),
        "label_boundary": audit["label_boundary"],
        "safety": audit["safety"],
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
