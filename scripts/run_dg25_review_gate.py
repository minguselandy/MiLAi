#!/usr/bin/env python3
"""Accept the independent DG-25 review and freeze exact pre-treatment controls."""

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
from evals.dg25.baseline_freeze import build_source_config_index_snapshot_manifest
from evals.dg25.review_gate import (
    REVIEW_PATH,
    REVIEW_SHA256,
    S1_RECEIPT_PATH,
    S1_RECEIPT_SHA256,
    S1_SOURCE_MANIFEST_PATH,
    S1_SOURCE_MANIFEST_SHA256,
    build_executor_feasibility,
    build_pre_treatment_arm_manifest,
    build_stop_rule_registry,
    load_and_validate_independent_review,
)

S0_MANIFEST = Path(
    "var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/"
    "source-config-index-snapshot-manifest.json"
)
SOURCE_PATHS = (
    "MiLAi_DG-25_Requirement定向检索与时间答案正确性闭环_GOALS.md",
    "evals/dg25/artifacts.py",
    "evals/dg25/baseline_freeze.py",
    "evals/dg25/review_gate.py",
    "scripts/run_dg25_review_gate.py",
    "tests/test_dg25_review_gate.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg25-review-gate-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg25/reviews" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan_path = output / "plan.json"
    write_json_new(
        plan_path,
        {
            "schema": "milai.dg25.review-gate-plan.v0.1",
            "run_id": args.run_id,
            "review_sha256": REVIEW_SHA256,
            "s1_receipt_sha256": S1_RECEIPT_SHA256,
            "s1_source_manifest_sha256": S1_SOURCE_MANIFEST_SHA256,
            "treatment_executed": False,
            "effect_scoring_authorized": False,
            "reader_calls_authorized": 0,
            "model_provider_controller_calls_authorized": 0,
            "automatic_retries": 0,
            "formal_holdout_authorized": False,
            "candidate_default": False,
        },
    )
    review = load_and_validate_independent_review(ROOT)
    arm_manifest = build_pre_treatment_arm_manifest(ROOT, review)
    arm_path = output / "pre-treatment-arm-manifest.json"
    write_json_new(arm_path, arm_manifest)
    stop_rules = build_stop_rule_registry(review)
    stop_path = output / "stop-rule-registry.json"
    write_json_new(stop_path, stop_rules)
    feasibility = build_executor_feasibility(review)
    feasibility_path = output / "executor-feasibility-review.json"
    write_json_new(feasibility_path, feasibility)
    edit_disposition = {
        "schema": "milai.dg25.required-edit-disposition.v0.1",
        "run_id": args.run_id,
        "edits": {
            "RE-01": "SATISFIED_FOR_S2_BY_PRE_TREATMENT_ARM_MANIFEST",
            "RE-02": "PREREGISTERED_BLOCKING_BEFORE_E1",
            "RE-03": "PREREGISTERED_BLOCKING_BEFORE_E2_DISPOSITION",
            "RE-04": "INCORPORATED_IN_GOAL_AND_ARM_CLAIM_BOUNDARY",
            "RE-05": "COST_LEDGER_SCHEMA_FROZEN_BLOCKING_BEFORE_FINAL_POLICY",
            "RE-06": "PREREGISTERED_READER_CALLS_REMAIN_ZERO",
            "RE-07": "SATISFIED_FOR_S2_BY_MACHINE_STOP_RULE_REGISTRY",
            "RE-08": "SATISFIED_FOR_S2_BY_EXACT_S1_002_BINDING",
        },
        "s2_preconditions_satisfied": True,
        "effect_scoring_authorized": False,
        "reader_calls_authorized": 0,
    }
    edit_path = output / "required-edit-disposition.json"
    write_json_new(edit_path, edit_disposition)

    current_boundaries = build_source_config_index_snapshot_manifest(ROOT)[
        "boundary_tree_identities"
    ]
    s0_boundaries = json.loads((ROOT / S0_MANIFEST).read_text(encoding="utf-8"))[
        "boundary_tree_identities"
    ]
    checks = {
        "independent_review_identity_exact": file_identity(ROOT, ROOT / REVIEW_PATH)[
            "sha256"
        ]
        == REVIEW_SHA256,
        "review_authorizes_s2": review["s2_authorized"] is True,
        "s1_receipt_identity_exact": file_identity(ROOT, ROOT / S1_RECEIPT_PATH)[
            "sha256"
        ]
        == S1_RECEIPT_SHA256,
        "s1_source_manifest_identity_exact": file_identity(
            ROOT, ROOT / S1_SOURCE_MANIFEST_PATH
        )["sha256"]
        == S1_SOURCE_MANIFEST_SHA256,
        "exact_query_count_75": len(arm_manifest["exact_channel_query_identities"]) == 75,
        "final_k_exact_8": arm_manifest["selection_and_budget"]["final_k"] == 8,
        "dense_ceiling_exact_30": arm_manifest["selection_and_budget"][
            "verified_dense_ceiling"
        ]
        == 30,
        "s2_arm_order_exact": arm_manifest["arm_order"]["S2"] == ["R0", "R0P"],
        "machine_stop_rules_present": len(stop_rules["machine_rules"]) == 10,
        "effect_scoring_not_authorized": arm_manifest["authorization"][
            "E1_E2_effect_scoring"
        ]
        is False,
        "reader_calls_zero": arm_manifest["authorization"]["E4_reader_calls"] is False,
        "formal_holdout_untouched": arm_manifest["label_boundary"][
            "formal_holdout_consumed"
        ]
        is False,
        "public_mcp_tree_unchanged": current_boundaries["public_mcp_contracts"]
        == s0_boundaries["public_mcp_contracts"],
        "postgresql_migration_tree_unchanged": current_boundaries["postgresql_migrations"]
        == s0_boundaries["postgresql_migrations"],
        "architecture_v1_tree_unchanged": current_boundaries["architecture_v1"]
        == s0_boundaries["architecture_v1"],
    }
    source_path = output / "source-manifest.json"
    write_json_new(
        source_path,
        {
            "schema": "milai.dg25.review-gate-source-manifest.v0.1",
            "run_id": args.run_id,
            "files": [file_identity(ROOT, ROOT / path) for path in SOURCE_PATHS],
        },
    )
    receipt = {
        "schema": "milai.dg25.review-gate-receipt.v0.1",
        "run_id": args.run_id,
        "status": "PASS_DG25_INDEPENDENT_REVIEW_GATE_S2_AUTHORIZED"
        if all(checks.values())
        else "FAIL_DG25_INDEPENDENT_REVIEW_GATE",
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "plan": file_identity(ROOT, plan_path),
        "independent_review": file_identity(ROOT, ROOT / REVIEW_PATH),
        "pre_treatment_arm_manifest": file_identity(ROOT, arm_path),
        "stop_rule_registry": file_identity(ROOT, stop_path),
        "executor_feasibility_review": file_identity(ROOT, feasibility_path),
        "required_edit_disposition": file_identity(ROOT, edit_path),
        "source_manifest": file_identity(ROOT, source_path),
        "s2_authorized": all(checks.values()),
        "effect_scoring_authorized": False,
        "reader_calls_authorized": 0,
        "provider_model_controller_calls_authorized": 0,
        "automatic_retries": 0,
        "candidate_default": False,
        "formal_holdout_consumed": False,
    }
    receipt_path = output / "receipt.json"
    write_json_new(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "exact_channel_queries": len(arm_manifest["exact_channel_query_identities"]),
                "s2_authorized": receipt["s2_authorized"],
                "effect_scoring_authorized": False,
                "receipt": receipt_path.relative_to(ROOT).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
