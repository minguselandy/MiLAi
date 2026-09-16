#!/usr/bin/env python3
"""Validate DG-22 sealed evidence and write its honest terminal disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime/.venv/bin/python"
GOAL = ROOT / "MiLAi_DG-22_证据召回准确性与答案正确性闭环_GOALS.md"
RUNBOOK = ROOT / "docs/runbooks/dg22-accuracy-answer-closure.md"
FAILURE_INDEX = ROOT / "var/dg22/failure-index.jsonl"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
OUTPUT_ROOT = ROOT / "var/dg22/s10"
STAGE_RECEIPTS = {
    "s0": ROOT / "var/dg22/s0/dg22-s0-baseline-freeze-20260829-001/receipt.json",
    "s1": ROOT / "var/dg22/s1/dg22-s1-accuracy-oracle-20260829-001/receipt.json",
    "s2": ROOT / "var/dg22/s2/dg22-s2-reader-conformance-20260829-001/receipt.json",
    "s3": ROOT / "var/dg22/s3/dg22-s3-query-correctness-20260829-001/receipt.json",
    "s4": ROOT / "var/dg22/s4/dg22-s4-binding-correctness-20260829-001/receipt.json",
    "s5": ROOT
    / "var/dg22/s5/dg22-s5-acquisition-correctness-20260829-001/receipt.json",
    "s6": ROOT / "var/dg22/s6/dg22-s6-temporal-correctness-20260829-001/receipt.json",
    "s7": ROOT / "var/dg22/s7/dg22-s7-mediator-20260829-001/receipt.json",
    "s8": ROOT / "var/dg22/s8/dg22-s8-answer-correctness-20260829-003/receipt.json",
    "s9": ROOT / "var/dg22/s9/dg22-s9-quality-20260829-003/receipt.json",
}
EXPECTED_STATUS = {
    "s0": "PASS_BASELINE_IDENTITY_FREEZE",
    "s1": "PASS_SAFE_ORACLE",
    "s2": "PASS_READER_CONFORMANCE",
    "s3": "PASS_QUERY_REQUIREMENT_CORRECTNESS",
    "s4": "PASS_APPLICABILITY_AND_BINDING_V02",
    "s5": "PASS_REQUIREMENT_COMPLETE_ACQUISITION_FUSION",
    "s6": "PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED",
    "s7": "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION",
    "s8": "FAIL_CORRECT_CASE_REGRESSION",
    "s9": "PASS_DG22_QUALITY_POSTGRESQL_SECURITY",
}
HISTORICAL_RECEIPTS = (
    ROOT / "var/dg22/s8/dg22-s8-answer-correctness-20260829-001/receipt.json",
    ROOT / "var/dg22/s8/dg22-s8-answer-correctness-20260829-002/receipt.json",
    ROOT / "var/dg22/s9/dg22-s9-quality-20260829-001/receipt.json",
    ROOT / "var/dg22/s9/dg22-s9-quality-20260829-002/receipt.json",
)


class DG22S10Error(RuntimeError):
    """The terminal evidence is missing, inconsistent, or overstated."""


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
        raise DG22S10Error(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DG22S10Error(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    if path.exists():
        raise DG22S10Error(f"refusing to overwrite terminal artifact: {path}")
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
        raise DG22S10Error("artifact identity path is missing")
    path = ROOT / relative
    if (
        not path.is_file()
        or reference.get("sha256") != _sha256(path)
        or reference.get("size") != path.stat().st_size
    ):
        raise DG22S10Error(f"artifact identity drifted: {relative}")


def derive_dispositions(statuses: Mapping[str, str]) -> dict[str, str]:
    """Map independent lane evidence to the predeclared terminal vocabulary."""
    required = set(EXPECTED_STATUS)
    if set(statuses) != required:
        raise DG22S10Error("stage status denominator is incomplete")
    if any(statuses[stage] != EXPECTED_STATUS[stage] for stage in required):
        raise DG22S10Error("stage status is not authoritative")
    return {
        "reader": "PASS_READER_CONFORMANCE",
        "recall_binding": "PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION",
        "temporal": "PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED",
        "answer": "FAIL_CORRECT_CASE_REGRESSION",
        "overall": "FAIL_SAFETY_OR_REGRESSION",
    }


def _validate_failure_index() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not all(isinstance(row, dict) for row in records):
        raise DG22S10Error("failure index requires JSON objects")
    identities = [str(row.get("failure_id", "")) for row in records]
    if (
        not identities
        or any(not value for value in identities)
        or len(identities) != len(set(identities))
        or any(row.get("append_only") is not True for row in records)
    ):
        raise DG22S10Error("failure index append-only identity gate failed")
    return records


def _validate_stage_receipts() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for stage, path in STAGE_RECEIPTS.items():
        receipt = _read(path)
        if receipt.get("status") != EXPECTED_STATUS[stage]:
            raise DG22S10Error(f"{stage} status is not authoritative")
        if _contains_true_key(receipt, "formal_holdout_consumed"):
            raise DG22S10Error(f"{stage} consumed formal holdout")
        for identity in _referenced_identities(receipt):
            _verify_identity(identity)
        receipts[stage] = receipt

    for stage in ("s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"):
        hard_gate = receipts[stage].get("hard_gate")
        if not isinstance(hard_gate, Mapping) or hard_gate.get("passed") is not True:
            raise DG22S10Error(f"{stage} hard safety/entry gate did not pass")

    s6 = receipts["s6"]
    if (
        s6.get("full_temporal_pass") is not False
        or s6.get("schema_lane") != "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
        or s6.get("database_schema_changed_by_dg22") is not False
    ):
        raise DG22S10Error("S6 partial/schema boundary drifted")

    s8_gate = receipts["s8"].get("hard_gate")
    if not isinstance(s8_gate, Mapping):
        raise DG22S10Error("S8 hard gate is missing")
    s8_checks = s8_gate.get("checks")
    if (
        not isinstance(s8_checks, Mapping)
        or s8_gate.get("passed") is not False
        or s8_checks.get("baseline_correct_regression_zero_both_budgets") is not False
        or s8_checks.get("wrong_complete_zero") is not True
        or not all(
            s8_checks.get(check) is True
            for check in (
                "2048_exact_match_at_least_3",
                "2048_normalized_f1_at_least_030",
                "512_exact_match_at_least_2",
                "512_normalized_f1_at_least_027",
                "retrieval_frozen",
            )
        )
    ):
        raise DG22S10Error("S8 regression or aggregate answer evidence drifted")

    s9 = receipts["s9"]
    postgresql = s9.get("postgresql")
    if (
        s9.get("passed") is not True
        or s9.get("gate_count") != 8
        or s9.get("passed_gate_count") != 8
        or not isinstance(postgresql, Mapping)
        or postgresql.get("executed") is not True
        or not isinstance(postgresql.get("cleanup"), Mapping)
        or postgresql["cleanup"].get("status") != "PASS"
        or s9.get("candidate_default") is not False
        or s9.get("database_schema_changed_by_dg22") is not False
        or s9.get("schema_lane") != "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    ):
        raise DG22S10Error("S9 quality/PostgreSQL/schema evidence is incomplete")
    return receipts


def _run_architecture_gates(output: Path) -> dict[str, Any]:
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG22S10Error("frozen architecture manifest drifted")
    commands: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "validate-bundle",
            (str(PYTHON), "architecture/v1.0/scripts/validate_bundle.py"),
        ),
        (
            "verify-release-lock",
            (
                str(PYTHON),
                "architecture/v1.0/scripts/verify_lock.py",
                "--scope",
                "bundle",
                "--mode",
                "release",
                "--expected-manifest-sha256",
                ARCHITECTURE_MANIFEST_SHA256,
            ),
        ),
    )
    gates = []
    for gate_id, command in commands:
        completed = subprocess.run(  # noqa: S603 -- fixed local executable and argv.
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        log_path = output / f"architecture-{gate_id}.log"
        _write(log_path, {"stdout": completed.stdout, "stderr": completed.stderr})
        gates.append(
            {
                "gate_id": gate_id,
                "argv": list(command),
                "exit_code": completed.returncode,
                "passed": completed.returncode == 0,
                "log": _identity(log_path),
            }
        )
    return {
        "passed": all(gate["passed"] for gate in gates),
        "changed_by_dg22": False,
        "manifest": _identity(ARCHITECTURE_MANIFEST),
        "gates": gates,
    }


def _deliverable_index(
    receipts: Mapping[str, Mapping[str, Any]], terminal_receipt_path: Path
) -> dict[str, Any]:
    stage = {name: _identity(STAGE_RECEIPTS[name]) for name in STAGE_RECEIPTS}
    source = {
        path.name: _identity(path)
        for path in (
            ROOT / "runtime/src/milai/application/accuracy_acquisition.py",
            ROOT / "runtime/src/milai/application/appointment_composition.py",
            ROOT / "runtime/src/milai/application/evidence_semantics.py",
            ROOT / "runtime/src/milai/domain/semantic_query.py",
        )
    }
    return {
        "schema": "milai.dg22.s10-deliverable-index.v0.1",
        "deliverable_count": 24,
        "items": [
            {"id": 1, "name": "baseline_identity_receipt", "evidence": [stage["s0"]]},
            {
                "id": 2,
                "name": "safe_oracle_requirement_ledger",
                "evidence": [receipts["s1"]["safe_oracle_requirement_ledger"]],
            },
            {
                "id": 3,
                "name": "first_loss_ledgers",
                "evidence": [
                    receipts["s1"]["first_loss_ledger"],
                    receipts["s7"]["first_loss_ledger"],
                ],
            },
            {
                "id": 4,
                "name": "reader_conformance_v02",
                "evidence": [
                    receipts["s2"]["selected_reader_contract"],
                    receipts["s2"]["conformance_matrix"],
                ],
            },
            {
                "id": 5,
                "name": "query_requirement_mutation_matrix",
                "evidence": [receipts["s3"]["query_requirement_matrix"]],
            },
            {
                "id": 6,
                "name": "non_temporal_applicability_binding_v02",
                "evidence": [
                    receipts["s4"]["applicability_binding_report"],
                    source["semantic_query.py"],
                ],
            },
            {
                "id": 7,
                "name": "temporal_unknown_fail_separation",
                "evidence": [stage["s4"], stage["s6"]],
            },
            {
                "id": 8,
                "name": "accuracy_acquisition_policy_v03",
                "evidence": [receipts["s5"]["policy"]],
            },
            {
                "id": 9,
                "name": "requirement_complete_action_bundle",
                "evidence": [
                    receipts["s5"]["acquisition_fusion_report"],
                    source["accuracy_acquisition.py"],
                ],
            },
            {
                "id": 10,
                "name": "channel_requirement_local_fusion",
                "evidence": [stage["s5"]],
            },
            {
                "id": 11,
                "name": "probe_binding_attribution_split",
                "evidence": [stage["s5"]],
            },
            {
                "id": 12,
                "name": "bounded_local_event_time_anchor",
                "evidence": [
                    receipts["s6"]["sealed_temporal_product"],
                    source["evidence_semantics.py"],
                ],
            },
            {
                "id": 13,
                "name": "relevant_unresolved_count_blocker",
                "evidence": [stage["s6"], source["appointment_composition.py"]],
            },
            {
                "id": 14,
                "name": "product_faithful_mediator",
                "evidence": [
                    receipts["s7"]["sealed_mediator_product"],
                    receipts["s7"]["mediator_score"],
                ],
            },
            {
                "id": 15,
                "name": "matched_512_2048_answer_report",
                "evidence": [
                    receipts["s8"]["sealed_answer_reader_product"],
                    receipts["s8"]["answer_score"],
                ],
            },
            {
                "id": 16,
                "name": "recall_precision_binding_completeness_metrics",
                "evidence": [stage["s6"], stage["s7"]],
            },
            {
                "id": 17,
                "name": "cost_latency_report",
                "evidence": [stage["s7"], stage["s9"]],
            },
            {
                "id": 18,
                "name": "runtime_unit_contract_evaluation",
                "evidence": [stage["s9"]],
            },
            {
                "id": 19,
                "name": "postgresql_integration_security",
                "evidence": [stage["s9"]],
            },
            {"id": 20, "name": "strict_mypy_ruff", "evidence": [stage["s9"]]},
            {"id": 21, "name": "runbook_rollback", "evidence": [_identity(RUNBOOK)]},
            {
                "id": 22,
                "name": "source_artifact_manifests",
                "evidence": [
                    receipts["s9"]["source_manifest"],
                    receipts["s9"]["artifact_manifest"],
                ],
            },
            {
                "id": 23,
                "name": "append_only_failure_index",
                "evidence": [_identity(FAILURE_INDEX)],
            },
            {
                "id": 24,
                "name": "s10_terminal_receipt",
                "path": str(terminal_receipt_path.relative_to(ROOT)),
                "sealed_by_parent_receipt": True,
            },
        ],
    }


def _artifact_manifest(
    receipts: Mapping[str, Mapping[str, Any]], terminal_paths: list[Path]
) -> dict[str, Any]:
    paths = {
        GOAL,
        RUNBOOK,
        FAILURE_INDEX,
        ARCHITECTURE_MANIFEST,
        Path(__file__),
        *terminal_paths,
    }
    paths.update(STAGE_RECEIPTS.values())
    paths.update(HISTORICAL_RECEIPTS)
    for receipt in receipts.values():
        for identity in _referenced_identities(receipt):
            relative = identity.get("path")
            if isinstance(relative, str):
                paths.add(ROOT / relative)
    return {
        "schema": "milai.dg22.s10-artifact-manifest.v0.1",
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
            "schema": "milai.dg22.s10-terminal-plan.v0.1",
            "run_id": run_id,
            "mode": "REFERENCE_AND_VALIDATE_SEALED_S0_S9_NO_EXPERIMENT_RECOMPUTE",
            "stage_receipts": {
                stage: str(path.relative_to(ROOT))
                for stage, path in STAGE_RECEIPTS.items()
            },
            "expected_status": EXPECTED_STATUS,
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
    architecture = _run_architecture_gates(output)
    if architecture["passed"] is not True:
        raise DG22S10Error("architecture validation failed")

    deliverable_path = output / "deliverable-index.json"
    receipt_path = output / "receipt.json"
    _write(deliverable_path, _deliverable_index(receipts, receipt_path))
    artifact_manifest_path = output / "artifact-manifest.json"
    architecture_logs = [
        output / "architecture-validate-bundle.log",
        output / "architecture-verify-release-lock.log",
    ]
    _write(
        artifact_manifest_path,
        _artifact_manifest(
            receipts,
            [plan_path, deliverable_path, *architecture_logs],
        ),
    )

    s6_metrics = receipts["s6"]["metrics"]
    s7_metrics = receipts["s7"]["metrics"]
    s8_checks = receipts["s8"]["hard_gate"]["checks"]
    terminal_checks = {
        "authoritative_s0_s9_statuses_exact": True,
        "all_referenced_artifact_identities_verified": True,
        "reader_lane_pass_preserved": dispositions["reader"] == EXPECTED_STATUS["s2"],
        "recall_binding_lane_pass_preserved": dispositions["recall_binding"]
        == EXPECTED_STATUS["s7"],
        "temporal_partial_not_overstated": dispositions["temporal"]
        == EXPECTED_STATUS["s6"],
        "answer_regression_failure_not_overstated": dispositions["answer"]
        == EXPECTED_STATUS["s8"],
        "overall_failure_matches_predeclared_rule": dispositions["overall"]
        == "FAIL_SAFETY_OR_REGRESSION",
        "wrong_complete_zero": s6_metrics["opened_count_wrong_complete"] == 0
        and s7_metrics["wrong_complete"] == 0
        and s8_checks["wrong_complete_zero"] is True,
        "candidate_default_false": receipts["s9"]["candidate_default"] is False,
        "formal_holdout_untouched": True,
        "schema_lane_not_entered": receipts["s9"]["schema_lane"]
        == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "architecture_unchanged": architecture["passed"] is True,
        "quality_postgresql_security_passed": receipts["s9"]["passed"] is True,
        "failure_index_append_only_unique": len(failure_records)
        == len({row["failure_id"] for row in failure_records}),
        "deliverable_count_24": True,
    }
    full_success_checks = {
        "reader_lane": True,
        "recall_binding_lane": True,
        "temporal_lane": False,
        "answer_lane": False,
        "correct_case_regression_zero": False,
        "efficiency": s7_metrics["additional_acquisition_calls_2048"] <= 8,
        "formal_holdout_untouched": True,
        "candidate_default_false": True,
    }
    receipt = {
        "schema": "milai.dg22.s10-terminal-receipt.v0.1",
        "run_id": run_id,
        "status": "TERMINAL_DISPOSITION_SEALED",
        "overall_disposition": dispositions["overall"],
        "reader_disposition": dispositions["reader"],
        "recall_binding_disposition": dispositions["recall_binding"],
        "temporal_disposition": dispositions["temporal"],
        "answer_disposition": dispositions["answer"],
        "quality_disposition": EXPECTED_STATUS["s9"],
        "full_success": False,
        "full_success_gate": {"passed": False, "checks": full_success_checks},
        "terminal_seal_gate": {
            "passed": all(terminal_checks.values()),
            "checks": terminal_checks,
        },
        "opened_development_metrics": {
            "safe_oracle_normalized_recall": s7_metrics[
                "safe_oracle_normalized_recall"
            ],
            "required_evidence_coverage_2048": s7_metrics[
                "required_evidence_coverage_2048"
            ],
            "required_evidence_coverage_512": s7_metrics[
                "required_evidence_coverage_512"
            ],
            "accepted_binding_precision": s7_metrics["accepted_binding_precision"],
            "useful_candidate_rate": s7_metrics["useful_candidate_rate"],
            "additional_acquisition_calls_2048": s7_metrics[
                "additional_acquisition_calls_2048"
            ],
            "candidates_hydrated_2048": s7_metrics["candidates_hydrated_2048"],
            "opened_count_operator_ready": s6_metrics["opened_count_operator_ready"],
            "opened_count_wrong_complete": s6_metrics["opened_count_wrong_complete"],
            "answer_summaries": receipts["s8"]["summaries"],
            "baseline_correct_regression_zero_both_budgets": False,
        },
        "observed_safety": {
            "wrong_complete": 0,
            "canonical_mutations": 0,
            "time_axis_substitutions": 0,
            "automatic_retries": 0,
            "provider_controller_calls": 0,
            "case_id_or_gold_runtime_inputs": 0,
            "formal_holdout_consumed": False,
        },
        "candidate_default": False,
        "formal_holdout_consumed": False,
        "production_release_authorized": False,
        "database_schema_changed_by_dg22": False,
        "public_mcp_schema_changed_by_dg22": False,
        "architecture_v1_changed_by_dg22": False,
        "schema_lane": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "stage_receipts": {
            stage: _identity(path) for stage, path in STAGE_RECEIPTS.items()
        },
        "historical_failure_receipts": [
            _identity(path) for path in HISTORICAL_RECEIPTS
        ],
        "plan": _identity(plan_path),
        "source_manifest": receipts["s9"]["source_manifest"],
        "quality_artifact_manifest": receipts["s9"]["artifact_manifest"],
        "terminal_artifact_manifest": _identity(artifact_manifest_path),
        "deliverable_index": _identity(deliverable_path),
        "failure_index": _identity(FAILURE_INDEX),
        "runbook": _identity(RUNBOOK),
        "goal": _identity(GOAL),
        "architecture_validation": architecture,
        "runner": _identity(Path(__file__)),
        "claim_boundary": (
            "On the frozen synthetic and deidentified opened-development protocol, the "
            "requirement-complete applicability-aware candidate passed the retrieval/Binding "
            "lane with 0.80 safe-oracle-normalized recall, 19/23 and 18/23 required-evidence "
            "coverage, 1.0 accepted Binding precision, and zero Wrong COMPLETE within the "
            "declared call/hydration ceilings. Full temporal COUNT remains partial because "
            "opened event points are unresolved. Although aggregate 512/2048 EM/F1 floors "
            "passed, one baseline-correct answer regressed, so matched answer correctness and "
            "overall success fail. This does not establish formal LongMemEval improvement, "
            "universal memory correctness, production quality/latency, schema readiness, "
            "architecture freeze readiness, or production readiness."
        ),
    }
    if receipt["terminal_seal_gate"]["passed"] is not True:
        raise DG22S10Error("terminal seal checks failed")
    _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg22-s10-terminal-20260829-001")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    try:
        receipt = run(run_id=args.run_id, output=output)
    except Exception as exc:
        if output.exists() and not (output / "failure-ledger.json").exists():
            _write(
                output / "failure-ledger.json",
                {
                    "schema": "milai.dg22.s10-failure-ledger.v0.1",
                    "run_id": args.run_id,
                    "status": "FAILED_PRESERVED_FOR_DIAGNOSIS",
                    "failure_type": type(exc).__name__,
                    "reason": str(exc),
                    "automatic_retry_attempted": False,
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
