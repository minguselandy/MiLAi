#!/usr/bin/env python3
"""Run matched trace-OFF/ON behavior-neutrality checks for all DG-24 cases."""

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

from evals.dg24.product import run_behavior_equivalence

S0 = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-006"
S1 = ROOT / "var/dg24/s1/dg24-s1-contracts-20260829-005/receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s2-behavior-equivalence-20260829-005")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    if read_json(S1).get("hard_gate", {}).get("passed") is not True:
        raise RuntimeError("DG24_S1_NOT_PASSED")
    plan_path = output / "plan.json"
    write_json(
        plan_path,
        {
            "schema": "milai.dg24.s2-plan.v0.1",
            "run_id": args.run_id,
            "mode": "MATCHED_TRACE_OFF_ON_SAME_SNAPSHOT",
            "case_count": 10,
            "reader_calls_authorized": 0,
            "generative_provider_calls_authorized": 0,
            "automatic_retry_authorized": False,
            "labels_authorized": False,
        },
    )
    report = run_behavior_equivalence(
        ROOT,
        run_id=args.run_id,
        output=output,
        input_manifest_path=S0 / "input-only-case-manifest-v0.1.json",
    )
    report_path = output / "trace-off-on-behavior-equivalence.json"
    write_json(report_path, report)
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s2-behavior-equivalence-receipt.v0.1",
            "run_id": args.run_id,
            "status": (
                "PASS_DG24_S2_BEHAVIOR_EQUIVALENCE"
                if report["hard_gate"]["passed"]
                else "PARKED_BEHAVIOR_CHANGED"
            ),
            "plan": identity(plan_path),
            "s1_receipt": identity(S1),
            "behavior_equivalence_report": identity(report_path),
            "hard_gate": report["hard_gate"],
            "safety": report["safety"],
        },
    )
    print(
        json.dumps(
            {
                "status": read_json(receipt_path)["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if report["hard_gate"]["passed"] else 1


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
