#!/usr/bin/env python3
"""Validate sealed DG-23 evidence and write its honest terminal disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOAL = ROOT / "MiLAi_DG-23_预算稳定上下文编译与答案回归闭环_GOALS.md"
RUNBOOK = ROOT / "docs/runbooks/dg23-budget-invariant-context.md"
FAILURE_INDEX = ROOT / "var/dg23/failure-index.jsonl"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
OUTPUT_ROOT = ROOT / "var/dg23/s9"
STAGE_RECEIPTS = {
    "s0": ROOT / "var/dg23/s0/dg23-s0-baseline-freeze-20260829-001/receipt.json",
    "s1": ROOT / "var/dg23/s1/dg23-s1-budget-causality-20260829-001/receipt.json",
    "s2": ROOT / "var/dg23/s2/dg23-s2-decision-separation-20260829-001/receipt.json",
    "s3": ROOT / "var/dg23/s3/dg23-s3-context-compiler-20260829-001/receipt.json",
    "s4": ROOT / "var/dg23/s4/dg23-s4-reader-boundary-20260829-002/receipt.json",
    "s5": ROOT / "var/dg23/s5/dg23-s5-synthetic-matrix-20260829-001/receipt.json",
    "s6": ROOT / "var/dg23/s6/dg23-s6-opened-dev-context-20260829-020/receipt.json",
    "s7": ROOT / "var/dg23/s7/dg23-s7-matched-reader-20260829-002/receipt.json",
    "s8": ROOT / "var/dg23/s8/dg23-s8-quality-20260829-004/receipt.json",
}
EXPECTED_STATUS = {
    "s0": "PASS_DG23_BASELINE_DENOMINATOR_FREEZE",
    "s1": "PASS_DG22_BUDGET_CAUSALITY_AUDIT",
    "s2": "PASS_BUDGET_INVARIANT_DECISION_SNAPSHOT",
    "s3": "PASS_ATOMIC_NESTED_CONTEXT_COMPILER",
    "s4": "PASS_EXACT_READER_IDENTITY_BOUNDARY",
    "s5": "PASS_DG23_SYNTHETIC_CONTRACT_MATRIX",
    "s6": "PASS_DG23_OPENED_DEV_CONTEXT_LADDER",
    "s7": "FAIL_DG23_MATCHED_READER_ANSWER_CLOSURE",
    "s8": "PASS_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE",
}
FAILURE_INDEX_RELATIVE = FAILURE_INDEX.relative_to(ROOT).as_posix()


class DG23S9Error(RuntimeError):
    """Terminal evidence is missing, inconsistent, or overstated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(ROOT)),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG23S9Error(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DG23S9Error(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    if path.exists():
        raise DG23S9Error(f"refusing to overwrite terminal artifact: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _contains_true_key(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            (name == key and item is True) or _contains_true_key(item, key)
            for name, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_true_key(item, key) for item in value)
    return False


def _referenced_identities(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, Mapping):
        if {"path", "sha256", "size"} <= set(value):
            yield value
        for item in value.values():
            yield from _referenced_identities(item)
    elif isinstance(value, list):
        for item in value:
            yield from _referenced_identities(item)


def _verify_identity(reference: Mapping[str, object]) -> None:
    relative = reference.get("path")
    if not isinstance(relative, str):
        raise DG23S9Error("artifact identity path is missing")
    path = ROOT / relative
    if (
        not path.is_file()
        or reference.get("sha256") != _sha256(path)
        or reference.get("size") != path.stat().st_size
    ):
        raise DG23S9Error(f"artifact identity drifted: {relative}")


def derive_dispositions(statuses: Mapping[str, str]) -> dict[str, str]:
    """Map independent sealed lanes to the predeclared DG-23 vocabulary."""

    if set(statuses) != set(EXPECTED_STATUS):
        raise DG23S9Error("stage status denominator is incomplete")
    if any(statuses[stage] != expected for stage, expected in EXPECTED_STATUS.items()):
        raise DG23S9Error("stage status is not authoritative")
    return {
        "context_decision": "PASS_BUDGET_INVARIANT_DECISION_AND_CONTEXT",
        "recall_binding": "PASS_DG22_RECALL_BINDING_NON_REGRESSION",
        "answer": "FAIL_CORRECT_CASE_REGRESSION",
        "reader_semantics": "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
        "safety": "PASS_DG23_SAFETY",
        "quality": "PASS_DG23_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE",
        "overall": "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
    }


def _validate_failure_index() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not all(isinstance(row, dict) for row in records):
        raise DG23S9Error("failure index requires JSON objects")
    identities = [str(row.get("failure_id", "")) for row in records]
    if (
        not identities
        or any(not value for value in identities)
        or len(identities) != len(set(identities))
        or any(row.get("append_only") is not True for row in records)
    ):
        raise DG23S9Error("failure index append-only identity gate failed")
    by_id = {str(row["failure_id"]): row for row in records}
    required = {
        "dg23-s7-002-structural-pass-answer-regression",
        "dg23-s8-001-quality-contract-and-legacy-decision-boundary-resolved",
        "dg23-s8-002-queryir-sufficiency-slot-identity-resolved",
    }
    if not required.issubset(by_id):
        raise DG23S9Error("terminal failure/resolution evidence is incomplete")
    if (
        by_id["dg23-s7-002-structural-pass-answer-regression"].get("status")
        != "PARKED_READER_SEMANTIC_NON_MONOTONICITY"
    ):
        raise DG23S9Error("S7 answer failure was reclassified")
    return records


def _verify_manifest(identity: Mapping[str, object]) -> None:
    _verify_identity(identity)
    manifest = _read(ROOT / str(identity["path"]))
    entries = manifest.get("identities")
    if not isinstance(entries, list) or not entries:
        raise DG23S9Error("final manifest has no identities")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise DG23S9Error("manifest identity is malformed")
        _verify_identity(entry)


def _validate_stage_receipts() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for stage, path in STAGE_RECEIPTS.items():
        receipt = _read(path)
        if receipt.get("status") != EXPECTED_STATUS[stage]:
            raise DG23S9Error(f"{stage} status is not authoritative")
        if _contains_true_key(receipt, "formal_holdout_consumed"):
            raise DG23S9Error(f"{stage} consumed formal holdout")
        for identity in _referenced_identities(receipt):
            if identity.get("path") == FAILURE_INDEX_RELATIVE and stage != "s8":
                continue
            _verify_identity(identity)
        receipts[stage] = receipt

    for stage in ("s0", "s1", "s2", "s3", "s4", "s5", "s6"):
        gate = receipts[stage].get("hard_gate")
        if not isinstance(gate, Mapping) or gate.get("passed") is not True:
            raise DG23S9Error(f"{stage} structural/safety gate did not pass")
    s6 = receipts["s6"]
    if (
        not isinstance(s6.get("structural_gate"), Mapping)
        or s6["structural_gate"].get("passed") is not True
        or s6.get("labels_loaded_only_after_product_seal") is not True
        or s6.get("metrics", {}).get("wrong_complete") != 0
        or s6.get("metrics", {}).get("accepted_binding_precision") != 1
    ):
        raise DG23S9Error("S6 context/recall/Binding evidence is incomplete")

    s7 = receipts["s7"]
    s7_gate = s7.get("hard_gate")
    if not isinstance(s7_gate, Mapping):
        raise DG23S9Error("S7 hard gate is missing")
    checks = s7_gate.get("checks")
    if (
        not isinstance(checks, Mapping)
        or s7_gate.get("passed") is not False
        or checks.get("correct_case_regression_zero_primary") is not False
        or checks.get("wrong_complete_zero") is not True
        or checks.get("retrieval_frozen") is not True
        or checks.get("reader_contract_drift_zero") is not True
        or s7.get("labels_loaded_only_after_reader_product_seal") is not True
        or s7.get("automatic_retries") != 0
        or s7.get("invalid_json_count") != 0
        or s7.get("infeasible_reader_calls") != 0
    ):
        raise DG23S9Error("S7 answer failure or Reader integrity drifted")

    s8 = receipts["s8"]
    postgresql = s8.get("postgresql")
    architecture = s8.get("architecture")
    if (
        s8.get("passed") is not True
        or s8.get("gate_count") != 12
        or s8.get("passed_gate_count") != 12
        or not isinstance(postgresql, Mapping)
        or postgresql.get("executed") is not True
        or postgresql.get("cleanup", {}).get("status") != "PASS"
        or not isinstance(architecture, Mapping)
        or architecture.get("validate_passed") is not True
        or architecture.get("release_lock_passed") is not True
        or s8.get("candidate_default") is not False
        or s8.get("database_schema_changed_by_dg23") is not False
        or s8.get("schema_lane") != "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    ):
        raise DG23S9Error("S8 quality/PostgreSQL/schema evidence is incomplete")
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG23S9Error("frozen architecture manifest drifted")
    _verify_manifest(s8["source_manifest"])
    _verify_manifest(s8["artifact_manifest"])
    return receipts


def _deliverable_index(
    receipts: Mapping[str, Mapping[str, Any]], terminal_receipt: Path
) -> dict[str, Any]:
    stage = {name: _identity(path) for name, path in STAGE_RECEIPTS.items()}
    items = [
        ("baseline_freeze_receipt", [stage["s0"]]),
        ("budget_causality_audit", [receipts["s1"]["sealed_product"]]),
        ("affected_case_first_divergence", [receipts["s1"]["first_divergence_trace"]]),
        ("decision_snapshot_contract", [receipts["s2"]["decision_invariance_report"]]),
        ("reader_evidence_plan_contract", [receipts["s3"]["reader_evidence_plan"]]),
        ("context_budget_envelope_contract", [receipts["s3"]["contract_report"]]),
        ("atomic_saturation_nested_renderer", [receipts["s3"]["renderer_matrix"]]),
        ("seed_identity_contract", [receipts["s4"]["seed_identity_matrix"]]),
        ("exact_tokenizer_accounting", [receipts["s4"]["contract_report"]]),
        ("synthetic_mutation_matrix", [receipts["s5"]["sealed_product"]]),
        ("property_test_report", [receipts["s5"]["property_report"]]),
        ("opened_dev_context_ladder", [receipts["s6"]["sealed_context_product"]]),
        ("b_safe_b_ref_report", [stage["s6"]]),
        ("product_path_fidelity", [receipts["s6"]["preseal_structural_gate"]]),
        ("mediator_score", [receipts["s6"]["context_score"]]),
        ("sealed_matched_reader_product", [receipts["s7"]["sealed_reader_product"]]),
        ("answer_score", [receipts["s7"]["answer_score"]]),
        ("correct_case_regression_report", [stage["s7"]]),
        ("efficiency_token_report", [stage["s6"], stage["s7"]]),
        ("quality_receipt", [stage["s8"]]),
        ("postgresql_integration_security", [stage["s8"]]),
        ("append_only_failure_index", [_identity(FAILURE_INDEX)]),
        ("source_manifest", [receipts["s8"]["source_manifest"]]),
        ("artifact_manifest", [receipts["s8"]["artifact_manifest"]]),
        ("rollback_runbook", [_identity(RUNBOOK)]),
    ]
    indexed = [
        {"id": index, "name": name, "evidence": evidence}
        for index, (name, evidence) in enumerate(items, start=1)
    ]
    indexed.append(
        {
            "id": 26,
            "name": "s9_terminal_receipt",
            "path": str(terminal_receipt.relative_to(ROOT)),
            "sealed_by_parent_receipt": True,
        }
    )
    return {
        "schema": "milai.dg23.s9-deliverable-index.v0.1",
        "deliverable_count": 26,
        "items": indexed,
    }


def _artifact_manifest(
    receipts: Mapping[str, Mapping[str, Any]],
    failure_records: list[dict[str, Any]],
    terminal_paths: list[Path],
) -> dict[str, Any]:
    paths = {
        GOAL,
        RUNBOOK,
        FAILURE_INDEX,
        ARCHITECTURE_MANIFEST,
        Path(__file__),
        *STAGE_RECEIPTS.values(),
        *terminal_paths,
    }
    for receipt in receipts.values():
        for identity in _referenced_identities(receipt):
            relative = identity.get("path")
            if isinstance(relative, str) and (ROOT / relative).is_file():
                paths.add(ROOT / relative)
    for record in failure_records:
        for key in ("ledger", "receipt", "proof"):
            relative = record.get(key)
            if isinstance(relative, str) and (ROOT / relative).is_file():
                paths.add(ROOT / relative)
    return {
        "schema": "milai.dg23.s9-artifact-manifest.v0.1",
        "identities": [_identity(path) for path in sorted(paths)],
    }


def run(*, run_id: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s9-terminal-plan.v0.1",
            "run_id": run_id,
            "mode": "REFERENCE_AND_VALIDATE_SEALED_S0_S8_NO_EXPERIMENT_RECOMPUTE",
            "stage_receipts": {
                stage: str(path.relative_to(ROOT))
                for stage, path in STAGE_RECEIPTS.items()
            },
            "expected_status": EXPECTED_STATUS,
            "reader_calls_authorized": 0,
            "provider_calls_authorized": 0,
            "formal_holdout_consumed": False,
            "candidate_default": False,
            "production_release_authorized": False,
        },
    )
    receipts = _validate_stage_receipts()
    dispositions = derive_dispositions(
        {stage: str(receipt["status"]) for stage, receipt in receipts.items()}
    )
    failure_records = _validate_failure_index()

    deliverable_path = output / "deliverable-index.json"
    receipt_path = output / "receipt.json"
    _write(deliverable_path, _deliverable_index(receipts, receipt_path))
    artifact_manifest_path = output / "artifact-manifest.json"
    _write(
        artifact_manifest_path,
        _artifact_manifest(
            receipts,
            failure_records,
            [plan_path, deliverable_path],
        ),
    )

    s6_metrics = receipts["s6"]["metrics"]
    s7 = receipts["s7"]
    terminal_checks = {
        "authoritative_s0_s8_statuses_exact": True,
        "all_referenced_artifact_identities_verified": True,
        "context_decision_lane_pass_preserved": dispositions["context_decision"]
        == "PASS_BUDGET_INVARIANT_DECISION_AND_CONTEXT",
        "recall_binding_lane_pass_preserved": dispositions["recall_binding"]
        == "PASS_DG22_RECALL_BINDING_NON_REGRESSION",
        "answer_failure_not_overstated": dispositions["answer"]
        == "FAIL_CORRECT_CASE_REGRESSION",
        "reader_semantic_park_not_overstated": dispositions["reader_semantics"]
        == "PARKED_READER_SEMANTIC_NON_MONOTONICITY",
        "wrong_complete_zero": receipts["s7"]["hard_gate"]["checks"][
            "wrong_complete_zero"
        ]
        is True,
        "temporal_partial_not_hidden": set(
            _read(ROOT / str(receipts["s7"]["answer_score"]["path"]))[
                "primary_correct_case_regressions"
            ][index]["case_id"]
            for index in range(
                len(
                    _read(ROOT / str(receipts["s7"]["answer_score"]["path"]))[
                        "primary_correct_case_regressions"
                    ]
                )
            )
        )
        == {"2e6d26dc", "88432d0a"},
        "candidate_default_false": all(
            receipts[stage].get("candidate_default") is False
            for stage in ("s6", "s7", "s8")
        ),
        "formal_holdout_untouched": True,
        "schema_lane_not_entered": receipts["s8"]["schema_lane"]
        == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "architecture_unchanged": _sha256(ARCHITECTURE_MANIFEST)
        == ARCHITECTURE_MANIFEST_SHA256,
        "quality_postgresql_security_passed": receipts["s8"]["passed"] is True,
        "failure_index_append_only_unique": len(failure_records)
        == len({row["failure_id"] for row in failure_records}),
        "deliverable_count_26": True,
    }
    full_success_checks = {
        "context_decision_lane": True,
        "recall_binding_lane": True,
        "answer_regression_closure": False,
        "safety_lane": True,
        "quality_postgresql_security": True,
        "candidate_default_false": True,
        "formal_holdout_untouched": True,
        "architecture_unchanged": True,
    }
    receipt = {
        "schema": "milai.dg23.s9-terminal-receipt.v0.1",
        "run_id": run_id,
        "status": "TERMINAL_DISPOSITION_SEALED",
        "overall_disposition": dispositions["overall"],
        "context_decision_disposition": dispositions["context_decision"],
        "recall_binding_disposition": dispositions["recall_binding"],
        "answer_disposition": dispositions["answer"],
        "reader_semantic_disposition": dispositions["reader_semantics"],
        "safety_disposition": dispositions["safety"],
        "quality_disposition": dispositions["quality"],
        "full_success": False,
        "full_success_gate": {"passed": False, "checks": full_success_checks},
        "terminal_seal_gate": {
            "passed": all(terminal_checks.values()),
            "checks": terminal_checks,
        },
        "opened_development_metrics": {
            **s6_metrics,
            "candidate_b_ref_exact_match_by_replicate": [4, 4, 4],
            "primary_correct_case_regression_count": 12,
            "primary_regression_case_ids": ["2e6d26dc", "88432d0a"],
            "historical_regression_2048_correct_all_replicates": s7["hard_gate"][
                "checks"
            ]["historical_regression_2048_correct_all_replicates"],
        },
        "observed_safety": {
            "wrong_complete": 0,
            "canonical_mutations": 0,
            "automatic_retries": s7["automatic_retries"],
            "invalid_reader_json": s7["invalid_json_count"],
            "infeasible_reader_calls": s7["infeasible_reader_calls"],
            "formal_holdout_consumed": False,
        },
        "candidate_default": False,
        "formal_holdout_consumed": False,
        "production_release_authorized": False,
        "database_schema_changed_by_dg23": False,
        "public_mcp_schema_changed_by_dg23": False,
        "architecture_v1_changed_by_dg23": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "stage_receipts": {
            stage: _identity(path) for stage, path in STAGE_RECEIPTS.items()
        },
        "plan": _identity(plan_path),
        "source_manifest": receipts["s8"]["source_manifest"],
        "quality_artifact_manifest": receipts["s8"]["artifact_manifest"],
        "terminal_artifact_manifest": _identity(artifact_manifest_path),
        "deliverable_index": _identity(deliverable_path),
        "failure_index": _identity(FAILURE_INDEX),
        "runbook": _identity(RUNBOOK),
        "goal": _identity(GOAL),
        "architecture_manifest": _identity(ARCHITECTURE_MANIFEST),
        "runner": _identity(Path(__file__)),
        "claim_boundary": (
            "On the sealed synthetic and public deidentified opened-development protocol, "
            "DG-23 separated presentation budget from acquisition, Binding, RequirementState, "
            "Sufficiency, and operator decisions; atomic protected Context, nested rendering, "
            "semantic saturation, exact Reader-envelope accounting, recall/Binding floors, "
            "safety, and quality/PostgreSQL/security gates passed. The fixed Reader nevertheless "
            "regressed two previously correct temporal-count cases across both primary modes and "
            "all three preregistered replicates, so answer closure did not pass and DG-23 is "
            "parked for a separate evidence-consumption/completeness study. This does not "
            "establish "
            "formal LongMemEval improvement, universal memory correctness, production readiness, "
            "schema readiness, or architecture-freeze update readiness."
        ),
    }
    if receipt["terminal_seal_gate"]["passed"] is not True:
        raise DG23S9Error("terminal seal checks failed")
    _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s9-terminal-20260829-001")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    try:
        receipt = run(run_id=args.run_id, output=output)
    except Exception as exc:
        if output.exists() and not (output / "failure-ledger.json").exists():
            _write(
                output / "failure-ledger.json",
                {
                    "schema": "milai.dg23.s9-failure-ledger.v0.1",
                    "run_id": args.run_id,
                    "status": "FAILED_PRESERVED_FOR_DIAGNOSIS",
                    "failure_type": type(exc).__name__,
                    "reason": str(exc),
                    "automatic_retry_attempted": False,
                    "reader_calls": 0,
                    "provider_calls": 0,
                    "formal_holdout_consumed": False,
                },
            )
        raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "overall_disposition": receipt["overall_disposition"],
                "receipt": str((output / "receipt.json").relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
