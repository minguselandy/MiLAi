#!/usr/bin/env python3
"""Execute DG-23 S3 atomic Context compiler contract proof."""

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
from evals.dg23.context_compiler_contract import (
    build_context_compiler_contract_report,
)

SOURCE_PATHS = (
    "runtime/src/milai/domain/reader_evidence_plan.py",
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/application/memory_resolve.py",
    "runtime/src/milai/application/retrieval.py",
    "evals/dg23/context_compiler_contract.py",
    "scripts/run_dg23_s3_context_compiler.py",
    "tests/test_dg23_s3_context_compiler.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s3-context-compiler-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s3" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s3-plan.v0.1",
            "run_id": args.run_id,
            "mode": "BUDGET_FREE_PLAN_ATOMIC_LOCAL_RENDER",
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "repository_calls_authorized": 0,
            "candidate_default": False,
        },
    )
    report = build_context_compiler_contract_report(ROOT)
    report["run_id"] = args.run_id
    report_path = output / "context-compiler-contract-report.json"
    _write(report_path, report)
    renderer_path = output / "renderer-matrix.json"
    _write(
        renderer_path,
        {
            "schema": "milai.dg23.s3-renderer-matrix.v0.1",
            "run_id": args.run_id,
            "records": report["render_records"],
            "short_optional_unit": report["short_optional_unit"],
            "oversized_optional_unit": report["oversized_optional_unit"],
            "conflict": report["conflict"],
        },
    )
    sealed_plan_path = output / "reader-evidence-plan.json"
    _write(
        sealed_plan_path,
        {
            "schema": "milai.dg23.s3-sealed-reader-evidence-plan.v0.1",
            "run_id": args.run_id,
            "plan": report["plan"],
        },
    )
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    receipt = {
        "schema": "milai.dg23.s3-context-compiler-receipt.v0.1",
        "run_id": args.run_id,
        "status": report["status"],
        "hard_gate": report["hard_gate"],
        "plan": _identity(plan_path),
        "contract_report": _identity(report_path),
        "renderer_matrix": _identity(renderer_path),
        "reader_evidence_plan": _identity(sealed_plan_path),
        "source_manifest": _identity(manifest_path),
        "execution_counts": report["execution_counts"],
        "safety": report["safety"],
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
