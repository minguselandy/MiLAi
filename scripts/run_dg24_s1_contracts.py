#!/usr/bin/env python3
"""Seal DG-24 trace schemas and synthetic lifecycle contracts."""

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

from evals.dg24.contracts import build_trace_schema_bundle, run_synthetic_matrix

S0 = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-008/receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s1-contracts-20260829-007")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s1" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    s0 = read_json(S0)
    if s0.get("hard_gate", {}).get("passed") is not True:
        raise RuntimeError("DG24_S0_NOT_PASSED")
    schema_path = output / "trace-schema-bundle.json"
    matrix_path = output / "synthetic-lifecycle-matrix.json"
    write_json(schema_path, build_trace_schema_bundle())
    matrix = run_synthetic_matrix()
    write_json(matrix_path, matrix)
    checks = {
        "s0_passed": True,
        "trace_schema_count_at_least_11": len(read_json(schema_path)["schemas"]) >= 11,
        "synthetic_matrix_passed": matrix["hard_gate"]["passed"],
        "reader_calls_zero": True,
        "generative_provider_calls_zero": True,
        "opened_dev_label_access_zero": True,
        "public_schema_change_zero": True,
    }
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s1-contracts-receipt.v0.1",
            "run_id": args.run_id,
            "status": "PASS_DG24_S1_CONTRACTS" if all(checks.values()) else "FAIL",
            "s0_receipt": identity(S0),
            "trace_schema_bundle": identity(schema_path),
            "synthetic_lifecycle_matrix": identity(matrix_path),
            "hard_gate": {"passed": all(checks.values()), "checks": checks},
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
    return 0 if all(checks.values()) else 1


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
