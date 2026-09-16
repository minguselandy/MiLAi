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

from evals.dg22.temporal_correctness import (
    build_temporal_product,
    score_temporal_product,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s6-temporal-correctness-20260829-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s6" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s6-plan.v0.1",
            "run_id": args.run_id,
            "product_first_then_scorer": True,
            "runtime_case_id_selector": False,
            "event_projection_schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
            "provider_calls_authorized": 0,
            "reader_calls_authorized": 0,
            "formal_holdout_consumed": False,
        },
    )
    product_path = output / "sealed-temporal-product.json"
    _write(product_path, build_temporal_product(_ROOT))
    score = score_temporal_product(product_path)
    score_path = output / "temporal-score.json"
    _write(score_path, score)
    receipt = {
        "schema": "milai.dg22.s6-temporal-correctness-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "metrics": score["metrics"],
        "full_temporal_pass": score["full_temporal_pass"],
        "plan": _identity(plan_path),
        "sealed_temporal_product": _identity(product_path),
        "score": _identity(score_path),
        "database_schema_changed_by_dg22": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "formal_holdout_consumed": False,
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
