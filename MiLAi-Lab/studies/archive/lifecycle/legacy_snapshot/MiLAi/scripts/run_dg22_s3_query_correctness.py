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

from evals.dg22.query_correctness import run_query_correctness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s3-query-correctness-20260829-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s3" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s3-plan.v0.1",
            "run_id": args.run_id,
            "minimum_cells": 60,
            "annotation_predeclared": True,
            "runtime_case_id_or_gold_inputs": False,
            "provider_calls_authorized": 0,
            "reader_calls_authorized": 0,
            "formal_holdout_consumed": False,
        },
    )
    result = run_query_correctness()
    result["run_id"] = args.run_id
    matrix_path = output / "query-requirement-matrix.json"
    _write(matrix_path, result)
    receipt = {
        "schema": "milai.dg22.s3-query-correctness-receipt.v0.1",
        "run_id": args.run_id,
        "status": result["status"],
        "hard_gate": result["hard_gate"],
        "metrics": result["metrics"],
        "plan": _identity(plan_path),
        "query_requirement_matrix": _identity(matrix_path),
        "safety": result["safety"],
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "metrics": receipt["metrics"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 2


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
