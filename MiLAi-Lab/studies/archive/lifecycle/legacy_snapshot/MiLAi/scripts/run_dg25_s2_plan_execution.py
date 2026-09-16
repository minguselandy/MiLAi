#!/usr/bin/env python3
"""Execute DG-25 S2 label-free plan and official-executor gates."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg25.artifacts import file_identity, sha256_file, write_json_new
from evals.dg25.baseline_freeze import (
    CASE_ORDER,
    build_source_config_index_snapshot_manifest,
)
from evals.dg25.plan_execution import build_s2_reports
from evals.dg25.review_gate import (
    LIVE_ACTION_CAPS,
    S1_RECEIPT_PATH,
    S1_RECEIPT_SHA256,
    S1_SOURCE_MANIFEST_PATH,
    S1_SOURCE_MANIFEST_SHA256,
)

REVIEW_GATE_RECEIPT = Path(
    "var/dg25/reviews/dg25-review-gate-20260829-001/receipt.json"
)
REVIEW_GATE_RECEIPT_SHA256 = (
    "8c71eca956518f52d2a19ca8cbd698895476d25fbfe89a8ff33f1ee592739f21"
)
ARM_MANIFEST = Path(
    "var/dg25/reviews/dg25-review-gate-20260829-001/"
    "pre-treatment-arm-manifest.json"
)
ARM_MANIFEST_SHA256 = (
    "d6565873e1e188b186c20d53d9151c5c3d1dabc542d886a9eee1a714a0944f24"
)
S0_BOUNDARY_MANIFEST = Path(
    "var/dg25/s0/dg25-s0-baseline-freeze-20260829-001/"
    "source-config-index-snapshot-manifest.json"
)
SOURCE_PATHS = (
    "runtime/src/milai/application/__init__.py",
    "runtime/src/milai/application/acquisition_capability.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/requirement_acquisition.py",
    "runtime/src/milai/domain/requirement_acquisition.py",
    "runtime/tests/unit/test_dg25_contracts.py",
    "runtime/tests/unit/test_dg25_requirement_acquisition.py",
    "evals/dg25/artifacts.py",
    "evals/dg25/baseline_freeze.py",
    "evals/dg25/plan_execution.py",
    "evals/dg25/review_gate.py",
    "scripts/run_dg25_s2_plan_execution.py",
    "tests/test_dg25_s2_plan_execution.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg25-s2-plan-execution-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg25/s2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    review_receipt = _read(ROOT / REVIEW_GATE_RECEIPT)
    arm_manifest = _read(ROOT / ARM_MANIFEST)
    if review_receipt.get("s2_authorized") is not True:
        raise RuntimeError("DG25 independent review gate does not authorize S2")
    plan_path = output / "plan.json"
    write_json_new(
        plan_path,
        {
            "schema": "milai.dg25.s2-execution-plan.v0.1",
            "run_id": args.run_id,
            "mode": "SYNTHETIC_LABEL_FREE_R0_R0P_AND_PLAN_EXECUTION",
            "arm_order": ["R0", "R0P"],
            "final_k": 8,
            "live_action_caps": LIVE_ACTION_CAPS,
            "max_actions_per_plan": 2,
            "max_repository_calls_per_plan": 2,
            "max_hydrated_candidates_per_plan": 120,
            "effect_scoring_authorized": False,
            "opened_development_labels_authorized": False,
            "formal_holdout_authorized": False,
            "reader_calls_authorized": 0,
            "model_provider_controller_calls_authorized": 0,
            "automatic_retries": 0,
            "candidate_default": False,
        },
    )

    traces, validation, equivalence = build_s2_reports()
    traces["run_id"] = args.run_id
    validation["run_id"] = args.run_id
    equivalence["run_id"] = args.run_id
    traces_path = output / "requirement-acquisition-plan-traces.json"
    validation_path = output / "plan-validation-report.json"
    equivalence_path = output / "official-execution-equivalence-report.json"
    write_json_new(traces_path, traces)
    write_json_new(validation_path, validation)
    write_json_new(equivalence_path, equivalence)

    current_boundaries = build_source_config_index_snapshot_manifest(ROOT)[
        "boundary_tree_identities"
    ]
    frozen_boundaries = _read(ROOT / S0_BOUNDARY_MANIFEST)[
        "boundary_tree_identities"
    ]
    runtime_forbidden_findings = _runtime_forbidden_findings()
    composition = traces["proof_discovery_composition"]
    cost = traces["cost_ledger"]
    checks = {
        "review_gate_receipt_identity_exact": (
            sha256_file(ROOT / REVIEW_GATE_RECEIPT)
            == REVIEW_GATE_RECEIPT_SHA256
        ),
        "review_gate_authorizes_s2": review_receipt.get("s2_authorized") is True,
        "arm_manifest_identity_exact": (
            sha256_file(ROOT / ARM_MANIFEST) == ARM_MANIFEST_SHA256
        ),
        "s1_receipt_identity_exact": (
            sha256_file(ROOT / S1_RECEIPT_PATH) == S1_RECEIPT_SHA256
        ),
        "s1_source_manifest_identity_exact": (
            sha256_file(ROOT / S1_SOURCE_MANIFEST_PATH)
            == S1_SOURCE_MANIFEST_SHA256
        ),
        "s2_arm_order_exact": arm_manifest["arm_order"]["S2"]
        == ["R0", "R0P"],
        "final_k_exact_8": arm_manifest["selection_and_budget"]["final_k"] == 8,
        "live_action_caps_exact": arm_manifest["selection_and_budget"][
            "live_action_candidate_caps"
        ]
        == LIVE_ACTION_CAPS,
        "r0_r0p_semantics_exact": equivalence["exact_semantic_equivalence"]
        is True,
        "r0p_action_digest_preserved": equivalence[
            "r0p_baseline_action_digest_preserved"
        ]
        is True,
        "r0p_candidate_cap_preserved": equivalence[
            "r0p_baseline_candidate_cap_preserved"
        ]
        is True,
        "proof_and_discovery_compose": [
            item["action_role"]
            for item in composition["compilation"]["plan"]["actions"]
        ]
        == ["EVIDENCE_DISCOVERY", "PROOF_CLOSURE"],
        "official_executor_only": composition["official_executor_identity"]
        == "milai-evidence-acquisition-executor-v0.1",
        "one_full_recompute": cost["proof_discovery"]["extra_state_passes"]
        == 1,
        "aggregate_repository_budget_respected": cost["proof_discovery"][
            "repository_calls"
        ]
        == 2,
        "aggregate_hydration_budget_respected": cost["proof_discovery"][
            "planned_candidate_cap_sum"
        ]
        == 16,
        "fixed_channel_lineage_retained": composition["channels_retained"]
        == ["FTS_RAW", "TEMPORAL_EVENT"],
        "negative_plans_rejected_pre_repository": validation["hard_gate"][
            "passed"
        ]
        is True,
        "runtime_forbidden_findings_zero": runtime_forbidden_findings == [],
        "provider_model_controller_calls_zero": equivalence[
            "provider_model_controller_calls"
        ]
        == 0,
        "reader_calls_zero": cost["reader_calls"] == 0,
        "automatic_retries_zero": equivalence["automatic_retries"] == 0,
        "effect_scoring_not_executed": equivalence["effect_scoring_executed"]
        is False,
        "formal_holdout_untouched": traces["safety"]["formal_holdout_consumed"]
        is False,
        "candidate_default_false": traces["safety"]["candidate_default"]
        is False,
        "canonical_mutations_zero": traces["safety"]["canonical_mutations"]
        == 0,
        "public_mcp_tree_unchanged": current_boundaries["public_mcp_contracts"]
        == frozen_boundaries["public_mcp_contracts"],
        "postgresql_migration_tree_unchanged": current_boundaries[
            "postgresql_migrations"
        ]
        == frozen_boundaries["postgresql_migrations"],
        "architecture_v1_tree_unchanged": current_boundaries["architecture_v1"]
        == frozen_boundaries["architecture_v1"],
    }

    source_path = output / "source-manifest.json"
    write_json_new(
        source_path,
        {
            "schema": "milai.dg25.s2-source-manifest.v0.1",
            "run_id": args.run_id,
            "files": [file_identity(ROOT, ROOT / path) for path in SOURCE_PATHS],
        },
    )
    failure_index = ROOT / "var/dg25/failure-index.jsonl"
    receipt = {
        "schema": "milai.dg25.s2-plan-execution-receipt.v0.1",
        "run_id": args.run_id,
        "status": "PASS_DG25_S2_UNIFIED_PLAN_OFFICIAL_BATCH_EXECUTION"
        if all(checks.values())
        else "FAIL_DG25_S2_UNIFIED_PLAN_OFFICIAL_BATCH_EXECUTION",
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "plan": file_identity(ROOT, plan_path),
        "requirement_acquisition_plan_traces": file_identity(ROOT, traces_path),
        "plan_validation_report": file_identity(ROOT, validation_path),
        "official_execution_equivalence_report": file_identity(
            ROOT, equivalence_path
        ),
        "source_manifest": file_identity(ROOT, source_path),
        "failure_index": file_identity(ROOT, failure_index),
        "bound_s1": {
            "receipt": file_identity(ROOT, ROOT / S1_RECEIPT_PATH),
            "source_manifest": file_identity(
                ROOT, ROOT / S1_SOURCE_MANIFEST_PATH
            ),
        },
        "bound_independent_review_gate": {
            "receipt": file_identity(ROOT, ROOT / REVIEW_GATE_RECEIPT),
            "arm_manifest": file_identity(ROOT, ROOT / ARM_MANIFEST),
        },
        "metrics": {
            "r0_r0p_exact_semantic_equivalence": equivalence[
                "exact_semantic_equivalence"
            ],
            "fresh_plans_accepted": validation["counts"]["fresh_accepted"],
            "invalid_plans_rejected_pre_repository": validation["counts"][
                "negative_rejected_before_repository_call"
            ],
            "proof_discovery_actions": 2,
            "proof_discovery_repository_calls": cost["proof_discovery"][
                "repository_calls"
            ],
            "proof_discovery_state_passes": cost["proof_discovery"][
                "extra_state_passes"
            ],
        },
        "runtime_forbidden_findings": runtime_forbidden_findings,
        "safety": {
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "labels_loaded": False,
            "effect_scoring_executed": False,
            "reader_calls": 0,
            "provider_model_controller_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
        "s3_effect_execution_authorized": False,
        "s3_requires_post_s2_independent_authorization": True,
    }
    receipt_path = output / "receipt.json"
    write_json_new(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "r0_r0p_equivalent": equivalence["exact_semantic_equivalence"],
                "negative_pre_repository_rejections": validation["counts"][
                    "negative_rejected_before_repository_call"
                ],
                "receipt": receipt_path.relative_to(ROOT).as_posix(),
                "s3_effect_execution_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


def _runtime_forbidden_findings() -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sorted((ROOT / "runtime/src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        for frozen_case_id in CASE_ORDER:
            if frozen_case_id in text:
                findings.append(
                    {"path": relative, "reason": f"CASE_ID:{frozen_case_id}"}
                )
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("evals.dg25"):
                    findings.append(
                        {"path": relative, "reason": f"EVAL_IMPORT:{node.module}"}
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("evals.dg25"):
                        findings.append(
                            {"path": relative, "reason": f"EVAL_IMPORT:{alias.name}"}
                        )
    return findings


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
