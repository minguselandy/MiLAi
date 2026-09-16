from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from evals.dg20.fresh_state_audit import run_fresh_state_audit

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ARCHIVE = _ROOT / (
    "var/dg19/s4/dg19-s4-opened-dev-residual-20260828-003/sealed-product-shadow.json"
)
_IDENTITY_PATHS = (
    "runtime/src/milai/domain/requirement_state.py",
    "runtime/src/milai/application/requirement_state.py",
    "runtime/src/milai/domain/acquisition_capability.py",
    "runtime/src/milai/application/acquisition_capability.py",
    "runtime/src/milai/domain/acquisition.py",
    "runtime/src/milai/application/acquisition_state.py",
    "runtime/src/milai/application/acquisition.py",
    "runtime/src/milai/application/sufficiency.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "evals/dg20/fresh_state_audit.py",
    "scripts/run_dg20_s0_fresh_state_audit.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg20-s0-fresh-state-20260828-001")
    parser.add_argument("--archive", type=Path, default=_DEFAULT_ARCHIVE)
    args = parser.parse_args()
    output = _ROOT / "var/dg20/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "milai.dg20.s0-plan.v0.1",
        "run_id": args.run_id,
        "mode": "LABEL_FREE_FRESH_STATE_AUDIT",
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
        "bound_archive": {
            "path": str(args.archive.resolve().relative_to(_ROOT)),
            "sha256": _sha256(args.archive.resolve()),
        },
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)
    audit = run_fresh_state_audit(args.archive.resolve())
    audit["run_id"] = args.run_id
    audit["source_identities"] = {
        path: {"path": path, "sha256": _sha256(_ROOT / path)} for path in _IDENTITY_PATHS
    }
    audit["bound_archive"] = {
        "path": str(args.archive.resolve().relative_to(_ROOT)),
        "sha256": _sha256(args.archive.resolve()),
    }
    sealed = {
        "schema": "milai.dg20.s0-fresh-state-sealed-product.v0.1",
        "status": "SEALED_LABEL_FREE_STATE_AUDIT",
        "run_id": args.run_id,
        "labels_loaded": False,
        "label_fields_available": False,
        "formal_holdout_consumed": False,
        "audit": audit,
    }
    sealed_path = output / "sealed-product-trace.json"
    _write_json(sealed_path, sealed)
    loss_records = [
        {
            **record,
            "scorer_truth_loaded_after_seal": True,
            "truth_source": "NONE_LABEL_FREE_CONTRACT_FIXTURE",
        }
        for record in audit["unresolved_fixture_loss_inputs"]
    ]
    ledger = {
        "schema": "milai.dg20.s0-acquisition-loss-ledger.v0.1",
        "run_id": args.run_id,
        "classification": "LABEL_FREE_CONTRACT_FIXTURES / EVALUATION_PLANE",
        "record_count": len(loss_records),
        "records": loss_records,
        "all_records_have_exactly_one_first_loss": all(
            bool(record["first_loss_stage"]) for record in loss_records
        ),
        "scoring_started_after_product_seal": True,
    }
    ledger_path = output / "acquisition-loss-ledger.json"
    _write_json(ledger_path, ledger)
    score = {
        "schema": "milai.dg20.s0-fresh-state-score.v0.1",
        "status": audit["status"],
        "run_id": args.run_id,
        "sealed_product_trace": _identity(sealed_path),
        "hard_gate": audit["hard_gate"],
        "metrics": audit["metrics"],
        "archived_current_migration": audit["archived_current_migration"],
        "formal_holdout_consumed": False,
    }
    score_path = output / "score.json"
    _write_json(score_path, score)
    receipt = {
        "schema": "milai.dg20.s0-fresh-state-receipt.v0.2",
        "status": audit["status"],
        "run_id": args.run_id,
        "hard_gate": audit["hard_gate"],
        "metrics": audit["metrics"],
        "invariants": audit["invariants"],
        "plan": _identity(plan_path),
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(ledger_path),
        "source_identities": audit["source_identities"],
        "bound_archive": audit["bound_archive"],
    }
    receipt_path = output / "receipt.json"
    _write_json(receipt_path, receipt)
    print(json.dumps(_summary(receipt, receipt_path), sort_keys=True))
    return 0 if receipt["hard_gate"]["passed"] else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _summary(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "status": receipt["status"],
        "hard_gate_passed": receipt["hard_gate"]["passed"],
        "receipt": str(path.relative_to(_ROOT)),
    }


if __name__ == "__main__":
    raise SystemExit(main())
