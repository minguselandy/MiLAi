#!/usr/bin/env python3
"""Execute DG-23 S5 generic synthetic and property matrix."""

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
from evals.dg23.synthetic_matrix import build_synthetic_matrix_report

SOURCE_PATHS = (
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/domain/reader_evidence_plan.py",
    "evals/dg23/synthetic_matrix.py",
    "scripts/run_dg23_s5_synthetic_matrix.py",
    "tests/test_dg23_s5_synthetic_matrix.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s5-synthetic-matrix-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s5" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s5-plan.v0.1",
            "run_id": args.run_id,
            "mode": "GENERIC_SYNTHETIC_FULL_LADDER_AND_PROPERTY_MATRIX",
            "source_labels_authorized": False,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "repository_calls_authorized": 0,
            "formal_holdout_authorized": False,
        },
    )
    report = build_synthetic_matrix_report(ROOT)
    report["run_id"] = args.run_id
    report_path = output / "synthetic-contract-report.json"
    _write(report_path, report)
    product_path = output / "sealed-synthetic-context-product.json"
    _write(
        product_path,
        {
            "schema": "milai.dg23.s5-sealed-synthetic-context-product.v0.1",
            "run_id": args.run_id,
            "diagnostic_budgets": report["diagnostic_budgets"],
            "records": report["records"],
            "case_summaries": report["case_summaries"],
        },
    )
    property_path = output / "property-report.json"
    _write(property_path, report["property_report"])
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    receipt = {
        "schema": "milai.dg23.s5-synthetic-matrix-receipt.v0.1",
        "run_id": args.run_id,
        "status": report["status"],
        "hard_gate": report["hard_gate"],
        "plan": _identity(plan_path),
        "contract_report": _identity(report_path),
        "sealed_product": _identity(product_path),
        "property_report": _identity(property_path),
        "source_manifest": _identity(manifest_path),
        "execution_counts": report["execution_counts"],
        "label_boundary": report["label_boundary"],
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
