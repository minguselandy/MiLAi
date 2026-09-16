#!/usr/bin/env python3
"""Execute DG-23 S2 decision/presentation separation proof."""

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
from evals.dg23.decision_separation import build_decision_separation_report

SOURCE_PATHS = (
    "runtime/src/milai/domain/reader_evidence_plan.py",
    "runtime/src/milai/application/reader_evidence_plan.py",
    "runtime/src/milai/application/memory_access.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/src/milai/application/memory_resolve.py",
    "evals/dg23/decision_separation.py",
    "scripts/run_dg23_s2_decision_separation.py",
    "tests/test_dg23_s2_decision_separation.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s2-decision-separation-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg23/s2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s2-plan.v0.1",
            "run_id": args.run_id,
            "mode": "ONE_DECISION_SEVEN_PRESENTATION_PROJECTIONS",
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "database_calls_authorized": 0,
            "public_schema_change_authorized": False,
            "database_migration_authorized": False,
        },
    )
    report = build_decision_separation_report(ROOT)
    report["run_id"] = args.run_id
    report_path = output / "decision-invariance-report.json"
    _write(report_path, report)
    snapshot_path = output / "decision-snapshot.json"
    _write(
        snapshot_path,
        {
            "schema": "milai.dg23.s2-sealed-decision-snapshot.v0.1",
            "run_id": args.run_id,
            "snapshot_digest": report["decision_snapshot_digest"],
            "snapshot": report["decision_snapshot"],
        },
    )
    manifest = source_manifest(ROOT, SOURCE_PATHS)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-manifest.json"
    _write(manifest_path, manifest)
    receipt = {
        "schema": "milai.dg23.s2-decision-separation-receipt.v0.1",
        "run_id": args.run_id,
        "status": report["status"],
        "hard_gate": report["hard_gate"],
        "plan": _identity(plan_path),
        "decision_invariance_report": _identity(report_path),
        "decision_snapshot": _identity(snapshot_path),
        "source_manifest": _identity(manifest_path),
        "execution_counts": report["execution_counts"],
        "public_boundary": report["public_boundary"],
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
