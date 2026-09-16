#!/usr/bin/env python3
"""Run DG-23 S6 one-decision opened-dev Context ladder and post-seal scorer."""

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

from evals.dg14.benchmark import DEFAULT_ENV_FILE
from evals.dg23.baseline_freeze import source_manifest
from evals.dg23.opened_dev_context import (
    build_opened_dev_context_product,
    score_opened_dev_context_product,
    seal_opened_dev_context_product,
)

SOURCE_PATHS = (
    "runtime/src/milai/config/settings.py",
    "runtime/src/milai/api/app.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/src/milai/application/accuracy_acquisition.py",
    "runtime/src/milai/application/deterministic_recovery.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/memory_resolve.py",
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/application/reader_evidence_plan.py",
    "runtime/src/milai/domain/reader_evidence_plan.py",
    "evals/dg15/contracts.py",
    "evals/dg15/runtime_session.py",
    "evals/dg15/milai_mcp_adapter.py",
    "evals/dg23/opened_dev_context.py",
    "evals/dg23/reader_token_accounting.py",
    "scripts/run_dg23_s6_opened_dev_context.py",
    "runtime/tests/unit/test_deterministic_recovery.py",
    "runtime/tests/unit/test_dg22_accuracy_acquisition.py",
    "tests/test_dg23_s3_context_compiler.py",
    "tests/test_dg23_s6_opened_dev_context.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s6-opened-dev-context-20260829-001")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--score-only-product",
        type=Path,
        help="score an already sealed label-free S6 product without reacquisition",
    )
    args = parser.parse_args()
    output = ROOT / "var/dg23/s6" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s6-plan.v0.1",
            "run_id": args.run_id,
            "case_count": 10,
            "official_acquisition_decision_executions_per_case": 1,
            "diagnostic_budgets": [128, 256, 512, 1024, 2048, 4096, 8000],
            "diagnostic_local_renders_per_case": 7,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "source_labels_authorized_before_product_seal": False,
            "formal_holdout_authorized": False,
            "candidate_feature": "budget_invariant_context_v0_1",
            "candidate_default": False,
            "execution_phase": (
                "SEALED_PRODUCT_SCORER_ONLY"
                if args.score_only_product is not None
                else "PRODUCT_THEN_SCORER"
            ),
        },
    )
    if args.score_only_product is not None:
        product_path = args.score_only_product
        if not product_path.is_absolute():
            product_path = ROOT / product_path
        return _score_sealed_product(
            run_id=args.run_id,
            output=output,
            plan_path=plan_path,
            product_path=product_path.resolve(),
        )
    product = build_opened_dev_context_product(
        ROOT,
        run_id=args.run_id,
        output=output,
        env_file=args.env_file,
    )
    quarantine_path = output / "unsealed-context-product-quarantine.json"
    _write(quarantine_path, product)
    gate_report_path = output / "preseal-structural-gate.json"
    _write(gate_report_path, product["structural_gate"])
    if not product["structural_gate"]["passed"]:
        failure_receipt = {
            "schema": "milai.dg23.s6-preseal-failure-receipt.v0.1",
            "run_id": args.run_id,
            "status": "FAIL_DG23_CONTEXT_STRUCTURAL_GATE",
            "first_loss": "READER_PLAN",
            "structural_gate": product["structural_gate"],
            "quarantine_product": _identity(quarantine_path),
            "gate_report": _identity(gate_report_path),
            "reader_calls": 0,
            "provider_calls": 0,
            "labels_loaded": False,
            "formal_holdout_consumed": False,
        }
        failure_receipt_path = output / "receipt.json"
        _write(failure_receipt_path, failure_receipt)
        print(
            json.dumps(
                {
                    "status": failure_receipt["status"],
                    "failed_checks": [
                        key
                        for key, value in product["structural_gate"]["checks"].items()
                        if not value
                    ],
                    "receipt": str(failure_receipt_path.relative_to(ROOT)),
                },
                sort_keys=True,
            )
        )
        return 2
    product_path = output / "sealed-opened-dev-context-product.json"
    seal_opened_dev_context_product(product, product_path)
    score = score_opened_dev_context_product(ROOT, product_path)
    score_path = output / "context-score.json"
    _write(score_path, score)
    first_loss_path = output / "first-loss-ledger.json"
    _write(
        first_loss_path,
        {
            "schema": "milai.dg23.s6-first-loss-ledger.v0.1",
            "records": score["first_loss_ledger"],
        },
    )
    source = source_manifest(ROOT, SOURCE_PATHS)
    source["run_id"] = args.run_id
    source_path = output / "source-manifest.json"
    _write(source_path, source)
    receipt = {
        "schema": "milai.dg23.s6-opened-dev-context-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "structural_gate": product["structural_gate"],
        "metrics": score["metrics"],
        "execution_counts": product["execution_counts"],
        "labels_loaded_only_after_product_seal": True,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "plan": _identity(plan_path),
        "sealed_context_product": _identity(product_path),
        "preseal_quarantine_product": _identity(quarantine_path),
        "preseal_structural_gate": _identity(gate_report_path),
        "context_score": _identity(score_path),
        "first_loss_ledger": _identity(first_loss_path),
        "source_manifest": _identity(source_path),
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "structural_gate_passed": receipt["structural_gate"]["passed"],
                "metrics": receipt["metrics"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 2


def _score_sealed_product(
    *,
    run_id: str,
    output: Path,
    plan_path: Path,
    product_path: Path,
) -> int:
    if not product_path.is_file() or ROOT not in product_path.parents:
        raise ValueError("score-only product must be an existing workspace artifact")
    product = json.loads(product_path.read_text(encoding="utf-8"))
    if (
        not isinstance(product, dict)
        or product.get("status") != "SEALED_CONTEXT_PRODUCT_PENDING_SOURCE_SCORER"
        or not isinstance(product.get("structural_gate"), dict)
        or product["structural_gate"].get("passed") is not True
    ):
        raise ValueError("score-only input is not a structurally sealed S6 product")
    score = score_opened_dev_context_product(ROOT, product_path)
    score_path = output / "context-score.json"
    _write(score_path, score)
    first_loss_path = output / "first-loss-ledger.json"
    _write(
        first_loss_path,
        {
            "schema": "milai.dg23.s6-first-loss-ledger.v0.1",
            "records": score["first_loss_ledger"],
        },
    )
    source = source_manifest(ROOT, SOURCE_PATHS)
    source["run_id"] = run_id
    source_path = output / "source-manifest.json"
    _write(source_path, source)
    gate_path = product_path.parent / "preseal-structural-gate.json"
    receipt = {
        "schema": "milai.dg23.s6-opened-dev-context-receipt.v0.1",
        "run_id": run_id,
        "product_run_id": product.get("run_id"),
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "structural_gate": product["structural_gate"],
        "metrics": score["metrics"],
        "execution_counts": product["execution_counts"],
        "execution_phase": "SEALED_PRODUCT_SCORER_ONLY",
        "reacquisition_executions": 0,
        "labels_loaded_only_after_product_seal": True,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "plan": _identity(plan_path),
        "sealed_context_product": _identity(product_path),
        "preseal_structural_gate": _identity(gate_path),
        "context_score": _identity(score_path),
        "first_loss_ledger": _identity(first_loss_path),
        "source_manifest": _identity(source_path),
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "structural_gate_passed": receipt["structural_gate"]["passed"],
                "metrics": receipt["metrics"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 2


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
