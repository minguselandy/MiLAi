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

from evals.dg22.mediator import (
    build_mediator_product,
    score_mediator_product,
    seal_mediator_product,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s7-mediator-20260829-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s7" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s7-plan.v0.1",
            "run_id": args.run_id,
            "arms": [
                "A_DG20_TERMINAL_BASELINE",
                "B_DG21_FINAL_POLICY_CONTEXT",
                "C_DG22_QUERY_BINDING_CORRECTNESS",
                "D_REQUIREMENT_COMPLETE_ACQUISITION_FUSION",
                "E_SAFE_TEMPORAL_APPLICABILITY_COUNT",
            ],
            "budgets": [512, 2048],
            "product_first_then_scorer": True,
            "reader_calls_authorized": 0,
            "candidate_default": False,
            "formal_holdout_consumed": False,
        },
    )
    product_path = output / "sealed-mediator-product.json"
    seal_mediator_product(build_mediator_product(_ROOT), product_path)
    score = score_mediator_product(product_path)
    score_path = output / "mediator-score.json"
    _write(score_path, score)
    first_loss_path = output / "first-loss-ledger.json"
    _write(
        first_loss_path,
        {
            "schema": "milai.dg22.s7-first-loss-ledger.v0.1",
            "records": score["first_loss_ledger"],
        },
    )
    receipt = {
        "schema": "milai.dg22.s7-mediator-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "metrics": score["metrics"],
        "plan": _identity(plan_path),
        "sealed_mediator_product": _identity(product_path),
        "mediator_score": _identity(score_path),
        "first_loss_ledger": _identity(first_loss_path),
        "reader_calls": 0,
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
