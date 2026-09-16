#!/usr/bin/env python3
"""Execute DG-25 S0 technical freeze without treatment or label exposure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg25.artifacts import file_identity, write_json_new
from evals.dg25.baseline_freeze import (
    PRE_DG25_WORKTREE,
    build_baseline_freeze,
    build_source_config_index_snapshot_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg25-s0-baseline-freeze-20260829-001")
    parser.add_argument("--review-receipt", type=Path)
    parser.add_argument("--owner-waiver", type=Path)
    args = parser.parse_args()

    output = ROOT / "var/dg25/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    write_json_new(
        plan_path,
        {
            "schema": "milai.dg25.s0-plan.v0.1",
            "run_id": args.run_id,
            "mode": "IDENTITY_DENOMINATOR_SOURCE_REVIEW_FREEZE",
            "treatment_authorized": False,
            "labels_authorized_for_product": False,
            "formal_holdout_authorized": False,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "canonical_mutation_authorized": False,
            "public_mcp_schema_change_authorized": False,
            "postgresql_schema_change_authorized": False,
            "architecture_v1_change_authorized": False,
            "automatic_retry_authorized": False,
            "candidate_default": False,
        },
    )
    baseline = build_baseline_freeze(
        ROOT,
        review_receipt=args.review_receipt,
        owner_waiver=args.owner_waiver,
    )
    baseline["run_id"] = args.run_id
    baseline_path = output / "baseline-freeze.json"
    write_json_new(baseline_path, baseline)
    denominator_path = output / "denominator-freeze.json"
    write_json_new(
        denominator_path,
        {
            "schema": "milai.dg25.s0-denominator-freeze.v0.1",
            "run_id": args.run_id,
            **baseline["denominators"],
        },
    )
    manifest = build_source_config_index_snapshot_manifest(ROOT)
    manifest["run_id"] = args.run_id
    manifest_path = output / "source-config-index-snapshot-manifest.json"
    write_json_new(manifest_path, manifest)
    worktree_path = output / "preexisting-worktree-receipt.json"
    write_json_new(
        worktree_path,
        {
            "schema": "milai.dg25.s0-preexisting-worktree-receipt.v0.1",
            "run_id": args.run_id,
            **PRE_DG25_WORKTREE,
            "protected_diff_checks": baseline["preexisting_worktree"][
                "protected_diff_checks"
            ],
            "preservation_required": True,
        },
    )
    review_status_path = output / "ablation-review-status.json"
    write_json_new(
        review_status_path,
        {
            "schema": "milai.dg25.s0-ablation-review-status.v0.1",
            "run_id": args.run_id,
            **baseline["review_gate"],
            "s2_execution_authorized": baseline["review_gate"]["passed"],
        },
    )
    failure_index = ROOT / "var/dg25/failure-index.jsonl"
    failure_index.parent.mkdir(parents=True, exist_ok=True)
    failure_index.touch(exist_ok=True)
    receipt = {
        "schema": "milai.dg25.s0-baseline-freeze-receipt.v0.1",
        "run_id": args.run_id,
        "status": baseline["status"],
        "hard_gate": baseline["hard_gate"],
        "plan": file_identity(ROOT, plan_path),
        "baseline_freeze": file_identity(ROOT, baseline_path),
        "denominator_freeze": file_identity(ROOT, denominator_path),
        "source_config_index_snapshot_manifest": file_identity(ROOT, manifest_path),
        "preexisting_worktree_receipt": file_identity(ROOT, worktree_path),
        "ablation_review_status": file_identity(ROOT, review_status_path),
        "failure_index": file_identity(ROOT, failure_index),
        "label_boundary": baseline["label_boundary"],
        "safety": baseline["safety"],
        "s1_contract_work_may_proceed": baseline["hard_gate"]["technical_passed"],
        "s2_execution_authorized": baseline["hard_gate"]["passed"],
    }
    receipt_path = output / "receipt.json"
    write_json_new(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "technical_gate_passed": receipt["hard_gate"]["technical_passed"],
                "stage_gate_passed": receipt["hard_gate"]["passed"],
                "s2_execution_authorized": receipt["s2_execution_authorized"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["technical_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

