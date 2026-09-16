#!/usr/bin/env python3
"""Seal the DG-20 S3 conditional non-entry disposition.

S3 is conditional.  This runner never calls a Provider: it verifies the S2
core threshold and records the exact DISABLED_NOT_NEEDED residual disposition
in the same five-file layout used by executed stages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_S1_RECEIPT = ROOT / "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003/receipt.json"
DEFAULT_S2_RECEIPT = ROOT / "var/dg20/s2/dg20-s2-deterministic-policy-20260828-002/receipt.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg20/s3"


class DG20S3DispositionError(RuntimeError):
    """The conditional S3 disposition cannot be proven from its entry receipts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DG20S3DispositionError(f"expected JSON object: {path}")
    return payload


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise DG20S3DispositionError(f"refusing to overwrite artifact: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(
    *,
    run_id: str,
    output_root: Path,
    s1_receipt_path: Path,
    s2_receipt_path: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG20S3DispositionError("output exists; choose a fresh S3 run ID")
    s1 = _read_object(s1_receipt_path)
    s2 = _read_object(s2_receipt_path)
    if s1.get("status") != "PASS_S1_OFFICIAL_CHANNEL_ORACLE":
        raise DG20S3DispositionError("S1 official-channel entry receipt did not pass")
    if s2.get("status") != "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY":
        raise DG20S3DispositionError("S2 deterministic policy entry receipt did not pass")
    hard_gate = s2.get("hard_gate")
    metrics = s2.get("metrics")
    if not isinstance(hard_gate, dict) or hard_gate.get("passed") is not True:
        raise DG20S3DispositionError("S2 hard gate is not proven")
    if (
        not isinstance(metrics, dict)
        or metrics.get("missing_requirement_improved_case_count", 0) < 2
    ):
        raise DG20S3DispositionError("S2 did not reach the predeclared core threshold")
    if s2.get("residual_assist") != "DISABLED_NOT_NEEDED":
        raise DG20S3DispositionError("S2 did not authorize the disabled-not-needed lane")

    output_root.mkdir(parents=True)
    plan_path = output_root / "plan.json"
    sealed_path = output_root / "sealed-product-trace.json"
    score_path = output_root / "score.json"
    ledger_path = output_root / "acquisition-loss-ledger.json"
    receipt_path = output_root / "receipt.json"

    plan = {
        "schema": "milai.dg20.s3-plan.v0.1",
        "run_id": run_id,
        "conditional_stage": True,
        "entry_s1_receipt": _identity(s1_receipt_path),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "entry_rule": "S2_THRESHOLD_REACHED_RESIDUAL_NOT_REQUIRED",
        "provider_calls_authorized": 0,
        "additional_acquisition_passes_authorized": 0,
        "automatic_retries_authorized": 0,
        "formal_holdout_consumed": False,
    }
    _write_new_json(plan_path, plan)
    sealed = {
        "schema": "milai.dg20.s3-sealed-product-trace.v0.1",
        "run_id": run_id,
        "status": "CONDITIONAL_STAGE_NOT_ENTERED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV / PRODUCT_PLANE",
        "labels_loaded": False,
        "label_fields_available": False,
        "provider_calls": 0,
        "automatic_retries": 0,
        "additional_acquisition_passes": 0,
        "exact_cue_created": False,
        "restricted_cue_artifact_created": False,
        "public_cue_digest_receipts": [],
        "product_output_mutation": False,
        "canonical_mutation": False,
        "formal_holdout_consumed": False,
        "reason_code": "CORE_THRESHOLD_REACHED_RESIDUAL_NOT_REQUIRED",
    }
    _write_new_json(sealed_path, sealed)
    ledger: dict[str, Any] = {
        "schema": "milai.dg20.s3-acquisition-loss-ledger.v0.1",
        "run_id": run_id,
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "eligible_requirement_count": 0,
        "record_count": 0,
        "records": [],
        "all_eligible_requirements_have_exactly_one_first_loss": True,
        "reason_code": "NO_S3_ELIGIBLE_EXECUTION_RESIDUAL_DISABLED_NOT_NEEDED",
        "upstream_s2_loss_ledger": s2.get("acquisition_loss_ledger"),
        "scorer_truth_loaded_after_seal": True,
    }
    _write_new_json(ledger_path, ledger)
    score = {
        "schema": "milai.dg20.s3-score.v0.1",
        "run_id": run_id,
        "sealed_product_trace": _identity(sealed_path),
        "entry_gate_entered": False,
        "entry_gate_reason": "CORE_THRESHOLD_REACHED_RESIDUAL_NOT_REQUIRED",
        "residual_assist": "DISABLED_NOT_NEEDED",
        "delivery_gate": "NOT_APPLICABLE",
        "semantic_manipulation_gate": "NOT_APPLICABLE",
        "effect_gate": "NOT_APPLICABLE",
        "provider_calls": 0,
        "automatic_retries": 0,
        "additional_acquisition_passes": 0,
        "exact_cue_publicly_persisted": False,
        "formal_holdout_consumed": False,
        "passed": True,
    }
    _write_new_json(score_path, score)
    receipt = {
        "schema": "milai.dg20.s3-disposition-receipt.v0.1",
        "run_id": run_id,
        "status": "PASS_S3_CONDITIONAL_DISPOSITION",
        "core_lane": "PASS_REQUIREMENT_STATE_ALIGNED_ACQUISITION",
        "residual_assist": "DISABLED_NOT_NEEDED",
        "entry_gate_entered": False,
        "reason_code": "CORE_THRESHOLD_REACHED_RESIDUAL_NOT_REQUIRED",
        "provider_calls": 0,
        "automatic_retries": 0,
        "additional_acquisition_passes": 0,
        "formal_holdout_consumed": False,
        "plan": _identity(plan_path),
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(ledger_path),
        "entry_s1_receipt": _identity(s1_receipt_path),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "runner": _identity(Path(__file__)),
    }
    _write_new_json(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--s1-receipt", type=Path, default=DEFAULT_S1_RECEIPT)
    parser.add_argument("--s2-receipt", type=Path, default=DEFAULT_S2_RECEIPT)
    args = parser.parse_args()
    receipt = run(
        run_id=args.run_id,
        output_root=args.output_root / args.run_id,
        s1_receipt_path=args.s1_receipt,
        s2_receipt_path=args.s2_receipt,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
