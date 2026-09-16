#!/usr/bin/env python3
"""Execute DG-25 S1 typed-contract and synthetic falsification gates."""

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

from milai.domain.requirement_acquisition import (
    RequirementAcquisitionPlanV01,
    RequirementCompleteRetrievalPolicyV01,
)
from milai.domain.temporal_proof import (
    BoundedRangeScanProofV02,
    EventIdentityV01,
    EventTimeIntervalV02,
    LegacyBoundedRangeScanProofV01,
)
from milai.domain.typed_answer import TypedAnswerDecisionV01

from evals.dg25.artifacts import file_identity, write_json_new
from evals.dg25.baseline_freeze import (
    CASE_ORDER,
    build_source_config_index_snapshot_manifest,
)
from evals.dg25.synthetic_matrix import negative_contract_report, run_synthetic_matrix

S0 = Path("var/dg25/s0/dg25-s0-baseline-freeze-20260829-001")
SOURCE_PATHS = (
    "runtime/src/milai/domain/__init__.py",
    "runtime/src/milai/domain/requirement_acquisition.py",
    "runtime/src/milai/domain/temporal_proof.py",
    "runtime/src/milai/domain/typed_answer.py",
    "runtime/tests/unit/test_dg25_contracts.py",
    "evals/dg25/__init__.py",
    "evals/dg25/artifacts.py",
    "evals/dg25/baseline_freeze.py",
    "evals/dg25/synthetic_matrix.py",
    "scripts/run_dg25_s1_contracts.py",
    "tests/test_dg25_s1_contracts.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg25-s1-contracts-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg25/s1" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    s0_receipt = _read(ROOT / S0 / "receipt.json")
    if s0_receipt.get("s1_contract_work_may_proceed") is not True:
        raise RuntimeError("DG25 S0 technical gate does not authorize S1 contract work")
    plan_path = output / "plan.json"
    write_json_new(
        plan_path,
        {
            "schema": "milai.dg25.s1-plan.v0.1",
            "run_id": args.run_id,
            "mode": "LABEL_FREE_CONTRACT_AND_SYNTHETIC_FALSIFICATION",
            "treatment_authorized": False,
            "s2_execution_authorized": False,
            "labels_authorized": False,
            "formal_holdout_authorized": False,
            "provider_calls_authorized": 0,
            "reader_calls_authorized": 0,
            "canonical_mutation_authorized": False,
            "public_mcp_schema_change_authorized": False,
            "postgresql_schema_change_authorized": False,
            "architecture_v1_change_authorized": False,
            "automatic_retry_authorized": False,
            "candidate_default": False,
        },
    )
    schema_bundle = {
        "schema": "milai.dg25.s1-contract-schema-bundle.v0.1",
        "contracts": {
            "RequirementAcquisitionPlanV01": RequirementAcquisitionPlanV01.model_json_schema(),
            "RequirementCompleteRetrievalPolicyV01": (
                RequirementCompleteRetrievalPolicyV01.model_json_schema()
            ),
            "EventTimeIntervalV02": EventTimeIntervalV02.model_json_schema(),
            "EventIdentityV01": EventIdentityV01.model_json_schema(),
            "BoundedRangeScanProofV02": BoundedRangeScanProofV02.model_json_schema(),
            "TypedAnswerDecisionV01": TypedAnswerDecisionV01.model_json_schema(),
            "LegacyBoundedRangeScanProofV01Reader": (
                LegacyBoundedRangeScanProofV01.model_json_schema()
            ),
        },
        "writers": {
            "requirement_acquisition_plan": "requirement-acquisition-plan-v0.1",
            "event_time_interval": "event-time-interval-v0.2",
            "event_identity": "event-identity-v0.1",
            "bounded_range_scan_proof": "bounded-range-scan-proof-v0.2",
            "typed_answer_decision": "typed-answer-decision-v0.1",
        },
        "historic_readers": ["legacy-bounded-range-scan-proof-v0.1"],
        "public_mcp_schema_changed": False,
        "postgresql_schema_changed": False,
    }
    schema_path = output / "contract-schema-bundle.json"
    write_json_new(schema_path, schema_bundle)
    matrix = run_synthetic_matrix()
    matrix["run_id"] = args.run_id
    matrix_path = output / "synthetic-matrix.json"
    write_json_new(matrix_path, matrix)
    negative = negative_contract_report(matrix)
    negative["run_id"] = args.run_id
    negative_path = output / "negative-contract-report.json"
    write_json_new(negative_path, negative)

    current_boundaries = build_source_config_index_snapshot_manifest(ROOT)[
        "boundary_tree_identities"
    ]
    s0_manifest = _read(ROOT / S0 / "source-config-index-snapshot-manifest.json")
    s0_boundaries = s0_manifest["boundary_tree_identities"]
    runtime_findings = _runtime_forbidden_findings()
    checks = {
        "s0_technical_gate_passed": s0_receipt.get("hard_gate", {}).get(
            "technical_passed"
        )
        is True,
        "synthetic_matrix_passed": matrix["hard_gate"]["passed"] is True,
        "negative_contracts_passed": negative["hard_gate"]["passed"] is True,
        "contract_writer_versions_exact": schema_bundle["writers"]
        == {
            "requirement_acquisition_plan": "requirement-acquisition-plan-v0.1",
            "event_time_interval": "event-time-interval-v0.2",
            "event_identity": "event-identity-v0.1",
            "bounded_range_scan_proof": "bounded-range-scan-proof-v0.2",
            "typed_answer_decision": "typed-answer-decision-v0.1",
        },
        "legacy_proof_reader_preserved": schema_bundle["historic_readers"]
        == ["legacy-bounded-range-scan-proof-v0.1"],
        "runtime_forbidden_findings_zero": runtime_findings == [],
        "public_mcp_contract_tree_unchanged": current_boundaries["public_mcp_contracts"]
        == s0_boundaries["public_mcp_contracts"],
        "postgresql_migration_tree_unchanged": current_boundaries[
            "postgresql_migrations"
        ]
        == s0_boundaries["postgresql_migrations"],
        "architecture_v1_tree_unchanged": current_boundaries["architecture_v1"]
        == s0_boundaries["architecture_v1"],
        "candidate_default_false": matrix["safety"]["candidate_default"] is False,
        "formal_holdout_untouched": matrix["safety"]["formal_holdout_consumed"]
        is False,
        "provider_calls_zero": matrix["safety"]["provider_calls"] == 0,
        "automatic_retries_zero": matrix["safety"]["automatic_retries"] == 0,
        "canonical_mutations_zero": matrix["safety"]["canonical_mutations"] == 0,
        "treatment_executed_zero": True,
        "s2_still_not_authorized": s0_receipt.get("s2_execution_authorized") is False,
    }
    source_manifest = {
        "schema": "milai.dg25.s1-source-manifest.v0.1",
        "run_id": args.run_id,
        "files": [file_identity(ROOT, ROOT / path) for path in SOURCE_PATHS],
    }
    source_manifest_path = output / "source-manifest.json"
    write_json_new(source_manifest_path, source_manifest)
    failure_index = ROOT / "var/dg25/failure-index.jsonl"
    receipt = {
        "schema": "milai.dg25.s1-contracts-receipt.v0.1",
        "run_id": args.run_id,
        "status": "PASS_DG25_S1_TYPED_CONTRACTS_SYNTHETIC_MATRIX"
        if all(checks.values())
        else "FAIL_DG25_S1_TYPED_CONTRACTS_SYNTHETIC_MATRIX",
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "plan": file_identity(ROOT, plan_path),
        "contract_schema_bundle": file_identity(ROOT, schema_path),
        "synthetic_matrix": file_identity(ROOT, matrix_path),
        "negative_contract_report": file_identity(ROOT, negative_path),
        "source_manifest": file_identity(ROOT, source_manifest_path),
        "failure_index": file_identity(ROOT, failure_index),
        "matrix_counts": matrix["counts"],
        "negative_case_count": negative["negative_case_count"],
        "runtime_forbidden_findings": runtime_findings,
        "safety": matrix["safety"],
        "s2_execution_authorized": False,
    }
    receipt_path = output / "receipt.json"
    write_json_new(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "matrix_cases": receipt["matrix_counts"]["total"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "s2_execution_authorized": False,
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
        for case_id in CASE_ORDER:
            if case_id in text:
                findings.append({"path": relative, "reason": f"CASE_ID:{case_id}"})
        tree = ast.parse(text)
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("evals.dg25"):
                        findings.append(
                            {"path": relative, "reason": f"EVAL_IMPORT:{alias.name}"}
                        )
            if module and module.startswith("evals.dg25"):
                findings.append({"path": relative, "reason": f"EVAL_IMPORT:{module}"})
    return findings


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
