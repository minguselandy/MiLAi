#!/usr/bin/env python3
"""Execute DG-23 S4 exact Reader boundary contract proof."""

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
from evals.dg23.reader_boundary_contract import (
    build_reader_boundary_contract_report,
)

SOURCE_PATHS = (
    "evals/dg14/provider.py",
    "evals/dg23/reader_boundary.py",
    "evals/dg23/reader_boundary_contract.py",
    "evals/dg23/reader_token_accounting.py",
    "scripts/run_dg23_s4_reader_boundary.py",
    "tests/test_dg23_s4_reader_boundary.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s4-reader-boundary-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s4" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s4-plan.v0.1",
            "run_id": args.run_id,
            "mode": "ZERO_NETWORK_EXACT_READER_BOUNDARY_CONTRACT",
            "opened_dev_reader_calls_authorized": 0,
            "external_provider_calls_authorized": 0,
            "automatic_retries_authorized": 0,
            "response_salvage_authorized": False,
        },
    )
    report = build_reader_boundary_contract_report(ROOT)
    report["run_id"] = args.run_id
    report_path = output / "reader-boundary-contract-report.json"
    _write(report_path, report)
    seed_path = output / "seed-identity-matrix.json"
    _write(
        seed_path,
        {
            "schema": "milai.dg23.s4-seed-identity-matrix.v0.1",
            "run_id": args.run_id,
            "records": report["seed_matrix"],
            "exact_identity": report["exact_identity"],
        },
    )
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    receipt = {
        "schema": "milai.dg23.s4-reader-boundary-receipt.v0.1",
        "run_id": args.run_id,
        "status": report["status"],
        "hard_gate": report["hard_gate"],
        "plan": _identity(plan_path),
        "contract_report": _identity(report_path),
        "seed_identity_matrix": _identity(seed_path),
        "source_manifest": _identity(manifest_path),
        "reader_contract_digest": report["reader_contract_digest"],
        "reader_tokenizer": report["reader_tokenizer"],
        "execution_counts": report["execution_counts"],
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
