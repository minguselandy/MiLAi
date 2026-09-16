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

from evals.dg22.accuracy_oracle import (
    build_label_free_product,
    score_sealed_product,
    seal_product,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s1-accuracy-oracle-20260829-001")
    args = parser.parse_args()
    output = _ROOT / "var/dg22/s1" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s1-plan.v0.1",
            "run_id": args.run_id,
            "product_label_access_authorized": 0,
            "scorer_label_access_authorized": 1,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "eval_owned_retrieval_authorized": False,
            "official_channels_only": True,
            "formal_holdout_consumed": False,
        },
    )
    product = build_label_free_product(_ROOT, run_id=args.run_id)
    sealed_path = output / "sealed-product-oracle.json"
    seal_product(product, sealed_path)
    score = score_sealed_product(sealed_path)
    score_path = output / "safe-oracle-requirement-ledger.json"
    _write(score_path, score)
    first_loss_path = output / "first-loss-ledger.json"
    _write(
        first_loss_path,
        {
            "schema": "milai.dg22.s1-first-loss-ledger.v0.1",
            "run_id": args.run_id,
            "record_count": len(score["records"]),
            "records": [
                {
                    "case_id": row["case_id"],
                    "requirement_id": row["requirement_id"],
                    "first_loss": row["current_first_loss"],
                    "secondary_losses": row["secondary_losses"],
                }
                for row in score["records"]
            ],
            "one_first_loss_per_requirement": score["hard_gate"]["checks"][
                "one_first_loss_per_requirement"
            ],
        },
    )
    reachability_path = output / "channel-reachability-report.json"
    _write(
        reachability_path,
        {
            "schema": "milai.dg22.s1-channel-reachability.v0.1",
            "run_id": args.run_id,
            "official_channel": product["official_channel"],
            "metrics": score["metrics"],
            "formal_holdout_consumed": False,
        },
    )
    baseline_path = output / "accuracy-baseline.json"
    _write(
        baseline_path,
        {
            "schema": "milai.dg22.s1-accuracy-baseline.v0.1",
            "run_id": args.run_id,
            "dg20_floors": {
                "2048": {"coverage": 8 / 23, "exact_match": 2, "f1": 0.234848485},
                "512": {"coverage": 7 / 23, "exact_match": 1, "f1": 0.219896104},
            },
            "safe_oracle": score["metrics"],
        },
    )
    receipt = {
        "schema": "milai.dg22.s1-accuracy-oracle-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "plan": _identity(plan_path),
        "sealed_product_oracle": _identity(sealed_path),
        "safe_oracle_requirement_ledger": _identity(score_path),
        "first_loss_ledger": _identity(first_loss_path),
        "channel_reachability_report": _identity(reachability_path),
        "accuracy_baseline": _identity(baseline_path),
        "label_boundary": score["label_boundary"],
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "provider_calls": 0,
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


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
