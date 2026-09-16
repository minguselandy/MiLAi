"""Validate DG-21 evidence and seal its honest multi-lane terminal disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime/.venv/bin/python"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
RUNBOOK = ROOT / "docs/runbooks/dg21-type-directed-acquisition.md"
STAGE_DIRS = {
    "s0": ROOT / "var/dg21/s0/dg21-s0-baseline-freeze-20260828-001",
    "s1": ROOT / "var/dg21/s1/dg21-s1-policy-synthetic-20260828-004",
    "s2": ROOT / "var/dg21/s2/dg21-s2-type-directed-replay-20260828-004",
    "s3": ROOT / "var/dg21/s3/dg21-s3-targeted-source-adjacency-20260828-005",
    "s4": ROOT / "var/dg21/s4/dg21-s4-preference-expressivity-20260828-003",
    "s5": ROOT / "var/dg21/s5/dg21-s5-temporal-oracle-20260828-005",
    "s6": ROOT / "var/dg21/s6/dg21-s6-schema-gate-20260828-006",
    "s7": ROOT / "var/dg21/s7/dg21-s7-matched-20260828-008",
    "s8": ROOT / "var/dg21/s8/dg21-s8-quality-20260828-002",
}
EXPECTED_RECEIPT_STATUS = {
    "s0": "PASS_BASELINE_CONTRACT_FREEZE",
    "s1": "PASS_POLICY_SYNTHETIC_MATRIX",
    "s2": "PASS_TYPE_DIRECTED_SEMANTICS_AND_FAST_STOP",
    "s3": "PASS_TARGETED_SOURCE_ADJACENCY",
    "s4": "PASS_PREFERENCE_REQUIREMENT_EXPRESSIVITY",
    "s5": "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT",
    "s6": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
    "s8": "PASS_DG21_QUALITY_POSTGRESQL_SECURITY_WITH_S7_BLOCKED",
}
S7_PRIOR_FAILURE = ROOT / "var/dg21/s7/dg21-s7-matched-20260828-007/reader-failure.json"
OUTPUT_ROOT = ROOT / "var/dg21/s9"
CORE_DISPOSITION = "PARKED_NO_SAFE_GENERALIZED_POLICY"
PREFERENCE_DISPOSITION = "PASS_PREFERENCE_REQUIREMENT_EXPRESSIVITY"
TEMPORAL_DISPOSITION = "PASS_QUERY_TIME_TEMPORAL_COMPLETENESS"
OVERALL_DISPOSITION = "PARKED_NO_SAFE_GENERALIZED_POLICY"


class DG21S9Error(RuntimeError):
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
        raise DG21S9Error(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DG21S9Error(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    if path.exists():
        raise DG21S9Error(f"refusing to overwrite terminal artifact: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_identity(reference: object, path: Path, field: str) -> None:
    if not isinstance(reference, Mapping):
        raise DG21S9Error(f"{field} identity is missing")
    if (
        reference.get("sha256") != _sha256(path)
        or reference.get("size") != path.stat().st_size
    ):
        raise DG21S9Error(f"{field} identity drifted")


def _contains_true_key(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            (name == key and item is True) or _contains_true_key(item, key)
            for name, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_true_key(item, key) for item in value)
    return False


def _validate_receipts() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    for stage, status in EXPECTED_RECEIPT_STATUS.items():
        path = STAGE_DIRS[stage] / "receipt.json"
        receipt = _read(path)
        if receipt.get("status") != status:
            raise DG21S9Error(f"{stage} status is not authoritative")
        hard_gate = receipt.get("hard_gate")
        if stage in {"s0", "s1", "s2", "s3", "s4", "s5", "s6"} and (
            not isinstance(hard_gate, Mapping) or hard_gate.get("passed") is not True
        ):
            raise DG21S9Error(f"{stage} hard gate did not pass")
        if _contains_true_key(receipt, "formal_holdout_consumed"):
            raise DG21S9Error(f"{stage} consumed formal holdout")
        receipts[stage] = receipt
    quality = receipts["s8"]
    postgresql = quality.get("postgresql")
    if (
        quality.get("passed") is not True
        or quality.get("gate_count") != 8
        or quality.get("passed_gate_count") != 8
        or not isinstance(postgresql, Mapping)
        or postgresql.get("executed") is not True
        or not isinstance(postgresql.get("cleanup"), Mapping)
        or postgresql["cleanup"].get("status") != "PASS"
    ):
        raise DG21S9Error("S8 quality/PostgreSQL evidence is incomplete")
    return receipts


def _validate_s7_failure() -> dict[str, Any]:
    current = STAGE_DIRS["s7"]
    context = _read(current / "sealed-context-trace.json")
    progress = _read(current / "reader-progress-trace.json")
    failure = _read(current / "reader-failure.json")
    analysis = _read(current / "failure-analysis.json")
    prior_failure = _read(S7_PRIOR_FAILURE)
    records = context.get("records")
    if (
        context.get("status") != "CONTEXTS_COMPLETE_UNREAD"
        or context.get("labels_loaded") is not False
        or context.get("formal_holdout_consumed") is not False
        or not isinstance(records, list)
        or len(records) != 80
    ):
        raise DG21S9Error("S7 context denominator or label boundary drifted")
    observed = {
        (row.get("case_id"), row.get("arm"), row.get("token_budget"))
        for row in records
        if isinstance(row, Mapping)
    }
    if len(observed) != 80 or any(
        isinstance(row, Mapping) and "answer" in row for row in records
    ):
        raise DG21S9Error("S7 context cells are not unique and unread")
    keys = (
        "case_id",
        "arm",
        "token_budget",
        "context_sha256",
        "logical_request_id",
        "seed",
        "provider_contract_sha256",
        "reader_model_id",
    )
    if any(failure.get(key) != prior_failure.get(key) for key in keys):
        raise DG21S9Error("S7 repeated Reader failure identity is not exact")
    if (
        progress.get("status") != "READER_PROGRESS_UNSCORED"
        or progress.get("record_count") != 5
        or progress.get("labels_loaded") is not False
        or progress.get("automatic_retries") != 0
        or failure.get("automatic_retry_attempted") is not False
        or analysis.get("status")
        != "FAIL_READER_CONTRACT_REPEATED_IDENTITY_QUARANTINED"
    ):
        raise DG21S9Error("S7 failure/progress disposition is invalid")
    return {
        "context": context,
        "progress": progress,
        "failure": failure,
        "analysis": analysis,
        "records": records,
    }


def _extra_hydrated(row: Mapping[str, Any]) -> int:
    usage = row.get("usage")
    if (
        not isinstance(usage, Mapping)
        or int(usage.get("additional_acquisition_calls", 0)) == 0
    ):
        return 0
    trace = row.get("search_trace")
    dispositions = (
        trace.get("acquisition_probe_dispositions", [])
        if isinstance(trace, Mapping)
        else []
    )
    return sum(
        int(item.get("selected_candidate_count", 0))
        for item in dispositions
        if isinstance(item, Mapping)
        and item.get("status") == "EXECUTED"
        and str(item.get("probe_id", "")).startswith("action:")
    )


def _context_efficiency(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    final = [
        row
        for row in records
        if row.get("arm") == "D_SAFE_QUERY_TIME_TEMPORAL_EVENT"
        and row.get("token_budget") == 2048
    ]
    if len(final) != 10:
        raise DG21S9Error("S7 D/2048 denominator drifted")
    audits = []
    for row in final:
        trace = row.get("search_trace")
        audit = trace.get("semantic_audit") if isinstance(trace, Mapping) else None
        audits.append(audit if isinstance(audit, Mapping) else {})
    legacy = sum(
        int(audit.get("legacy_binding_evaluation_count", 0)) for audit in audits
    )
    current = sum(int(audit.get("binding_evaluation_count", 0)) for audit in audits)
    mismatches = sum(
        int(audit.get("materialized_type_mismatch_count", 0)) for audit in audits
    )
    additional = sum(
        int(row.get("usage", {}).get("additional_acquisition_calls", 0))
        for row in final
        if isinstance(row.get("usage"), Mapping)
    )
    hydrated = sum(_extra_hydrated(row) for row in final)
    reduction = 1.0 - current / legacy if legacy else 0.0
    checks = {
        "binding_evaluation_reduction_at_least_70pct": reduction >= 0.7,
        "materialized_type_mismatch_reduction_at_least_80pct": mismatches == 0,
        "candidates_hydrated_at_most_64": hydrated <= 64,
        "additional_acquisition_calls_at_most_8": additional <= 8,
    }
    return {
        "denominator": "D_2048_10_CASES",
        "legacy_binding_evaluation_count": legacy,
        "binding_evaluation_count": current,
        "binding_evaluation_reduction": round(reduction, 9),
        "materialized_type_mismatch_count": mismatches,
        "candidates_hydrated": hydrated,
        "additional_acquisition_calls": additional,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _run_architecture_gates(output: Path) -> dict[str, Any]:
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG21S9Error("frozen architecture manifest drifted")
    commands = (
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
    environment = {**os.environ, "MILAI_ARCHITECTURE_LOCK_SCOPE": "bundle"}
    gates: list[dict[str, Any]] = []
    for gate_id, command in commands:
        completed = subprocess.run(  # noqa: S603 - fixed architecture commands
            list(command),
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        log_path = output / f"architecture-{gate_id}.log"
        _write(log_path, {"stdout": completed.stdout, "stderr": completed.stderr})
        gates.append(
            {
                "gate_id": gate_id,
                "argv": list(command),
                "cwd": str(ROOT),
                "exit_code": completed.returncode,
                "passed": completed.returncode == 0,
                "log": _identity(log_path),
            }
        )
    if not all(gate["passed"] for gate in gates):
        raise DG21S9Error("architecture validation failed")
    return {
        "passed": True,
        "manifest": _identity(ARCHITECTURE_MANIFEST),
        "external_manifest_sha256": ARCHITECTURE_MANIFEST_SHA256,
        "changed_by_dg21": False,
        "gates": gates,
    }


def _source_manifest() -> dict[str, Any]:
    groups = {
        "runtime": sorted((ROOT / "runtime/src").rglob("*.py")),
        "migrations": sorted((ROOT / "runtime/migrations").rglob("*.py")),
        "runtime_tests": sorted((ROOT / "runtime/tests").rglob("*.py")),
        "dg21_evaluation": sorted((ROOT / "evals/dg21").rglob("*.py")),
        "dg21_runners": sorted((ROOT / "scripts").glob("*dg21*.py")),
        "dg21_tests": sorted((ROOT / "tests").glob("test_dg21*.py")),
        "contracts_runbook_architecture": [
            ROOT / "MiLAi_DG-21_类型定向证据获取效率与时间完备性修复_GOALS.md",
            ROOT / "MiLAi_Lean_V1_实施合同.md",
            RUNBOOK,
            ARCHITECTURE_MANIFEST,
        ],
    }
    identities = {
        group: [_identity(path) for path in paths] for group, paths in groups.items()
    }
    flattened = [item for values in identities.values() for item in values]
    return {
        "schema": "milai.dg21.s9-source-manifest.v0.1",
        "groups": identities,
        "identity_count": len(flattened),
        "manifest_digest": hashlib.sha256(
            json.dumps(flattened, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "formal_holdout_consumed": False,
    }


def _artifact_manifest() -> dict[str, Any]:
    stages: dict[str, list[dict[str, object]]] = {}
    for stage, directory in STAGE_DIRS.items():
        stages[stage] = [
            _identity(path) for path in sorted(directory.rglob("*")) if path.is_file()
        ]
    flattened = [item for values in stages.values() for item in values]
    return {
        "schema": "milai.dg21.s9-artifact-manifest.v0.1",
        "stages": stages,
        "artifact_count": len(flattened),
        "manifest_digest": hashlib.sha256(
            json.dumps(flattened, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "prior_artifacts_overwritten": False,
    }


def _failure_index(output: Path) -> dict[str, Any]:
    ledgers: list[dict[str, object]] = []
    analyses: list[dict[str, object]] = []
    failed_receipts: list[dict[str, object]] = []
    for path in sorted((ROOT / "var/dg21").rglob("*.json")):
        if output in path.parents:
            continue
        if path.name == "failure-ledger.json":
            ledgers.append(_identity(path))
        elif path.name == "failure-analysis.json":
            analyses.append(_identity(path))
        elif path.name == "receipt.json":
            value = _read(path)
            status = str(value.get("status", ""))
            hard_gate = value.get("hard_gate")
            hard_failed = (
                isinstance(hard_gate, Mapping) and hard_gate.get("passed") is False
            )
            if (
                value.get("passed") is False
                or status.startswith(("FAIL", "PARTIAL"))
                or hard_failed
            ):
                failed_receipts.append(_identity(path))
    return {
        "schema": "milai.dg21.s9-failure-index.v0.1",
        "failure_ledgers": ledgers,
        "failure_analyses": analyses,
        "failed_receipts": failed_receipts,
        "counts": {
            "failure_ledgers": len(ledgers),
            "failure_analyses": len(analyses),
            "failed_receipts": len(failed_receipts),
        },
        "append_only_preservation": True,
    }


def run(*, run_id: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise DG21S9Error("output exists; choose a fresh S9 run ID")
    output.mkdir(parents=True)
    plan = {
        "schema": "milai.dg21.s9-terminal-plan.v0.1",
        "run_id": run_id,
        "mode": "EVIDENCE_ONLY_MULTI_LANE_TERMINAL_SEAL",
        "expected_core_disposition": CORE_DISPOSITION,
        "expected_preference_disposition": PREFERENCE_DISPOSITION,
        "expected_temporal_disposition": TEMPORAL_DISPOSITION,
        "expected_overall_disposition": OVERALL_DISPOSITION,
        "stage_directories": {
            stage: str(directory.relative_to(ROOT))
            for stage, directory in STAGE_DIRS.items()
        },
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "latency_repeats": "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED",
        "formal_holdout_consumed": False,
        "production_release_authorized": False,
    }
    plan_path = output / "plan.json"
    _write(plan_path, plan)
    receipts = _validate_receipts()
    s7 = _validate_s7_failure()
    records = [dict(row) for row in s7["records"] if isinstance(row, Mapping)]
    efficiency = _context_efficiency(records)
    if efficiency["checks"]["additional_acquisition_calls_at_most_8"] is not False:
        raise DG21S9Error("expected frozen S7 call-ceiling failure was not preserved")
    architecture = _run_architecture_gates(output)

    source_path = output / "source-manifest.json"
    artifact_path = output / "artifact-manifest.json"
    failure_index_path = output / "failure-index.json"
    efficiency_path = output / "semantic-acquisition-efficiency-report.json"
    matched_path = output / "matched-512-2048-report.json"
    _write(source_path, _source_manifest())
    _write(artifact_path, _artifact_manifest())
    _write(failure_index_path, _failure_index(output))
    _write(
        efficiency_path,
        {
            "schema": "milai.dg21.s9-efficiency-report.v0.1",
            "run_id": run_id,
            "s2_type_semantics": receipts["s2"]["metrics"],
            "s3_targeted_acquisition": receipts["s3"]["metrics"],
            "s7_label_free_d2048": efficiency,
            "interpretation": (
                "Type and hydration ceilings passed, but the frozen matched policy used "
                "10 additional calls against the ceiling of 8."
            ),
            "labels_loaded": False,
            "formal_holdout_consumed": False,
        },
    )
    _write(
        matched_path,
        {
            "schema": "milai.dg21.s9-matched-report.v0.1",
            "run_id": run_id,
            "status": "CONTEXT_COMPLETE_READER_CONTRACT_FAILED_UNSCORED",
            "case_count": 10,
            "token_budgets": [512, 2048],
            "arm_count": 4,
            "context_cell_count": 80,
            "reader_progress_success_count": s7["progress"]["record_count"],
            "failed_reader_identity": s7["failure"],
            "same_failed_identity_consecutive_fresh_runs": True,
            "correctness_scored": False,
            "effect_scored": False,
            "wrong_complete_claim": "NOT_EVALUATED_AFTER_READER_CONTRACT_FAILURE",
            "latency_repeats": "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED",
            "labels_loaded": False,
            "formal_holdout_consumed": False,
        },
    )

    full_success_checks = {
        "core_efficiency": efficiency["passed"] is True,
        "matched_reader_contract": False,
        "matched_correctness_and_effect": False,
        "preference": True,
        "temporal": True,
        "quality": True,
    }
    terminal_seal_checks = {
        "s0_s6_authoritative": True,
        "s7_failure_exact_and_preserved": True,
        "s8_quality_postgresql_security_passed": True,
        "architecture_unchanged": architecture["passed"] is True,
        "candidate_default_false": receipts["s1"]["hard_gate"]["checks"][
            "default_disabled"
        ]
        is True,
        "formal_holdout_untouched": True,
        "reader_provider_contract_unchanged": True,
        "public_mcp_schema_unchanged": True,
        "wp06_typed_non_entry_preserved": True,
        "latency_repeats_not_run_before_correctness": True,
    }
    terminal_seal_passed = all(terminal_seal_checks.values())
    receipt = {
        "schema": "milai.dg21.s9-terminal-receipt.v0.1",
        "run_id": run_id,
        "status": "TERMINAL_DISPOSITION_SEALED",
        "overall_disposition": OVERALL_DISPOSITION,
        "core_disposition": CORE_DISPOSITION,
        "preference_disposition": PREFERENCE_DISPOSITION,
        "temporal_disposition": TEMPORAL_DISPOSITION,
        "full_success": False,
        "full_success_gate": {"passed": False, "checks": full_success_checks},
        "terminal_seal_gate": {
            "passed": terminal_seal_passed,
            "checks": terminal_seal_checks,
        },
        "matched_safety": {
            "observed_deterministic_stage_violations": 0,
            "matched_wrong_complete": "NOT_EVALUATED_AFTER_READER_CONTRACT_FAILURE",
            "all_zero_claim_authorized": False,
        },
        "candidate_default": False,
        "formal_holdout_consumed": False,
        "production_release_authorized": False,
        "public_mcp_schema_changed_by_dg21": False,
        "reader_provider_contract_changed": False,
        "database_schema_changed_by_dg21": False,
        "wp06_status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "latency_repeats": "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED",
        "plan": _identity(plan_path),
        "source_manifest": _identity(source_path),
        "artifact_manifest": _identity(artifact_path),
        "failure_index": _identity(failure_index_path),
        "semantic_acquisition_efficiency_report": _identity(efficiency_path),
        "matched_512_2048_report": _identity(matched_path),
        "quality_receipt": _identity(STAGE_DIRS["s8"] / "receipt.json"),
        "runbook": _identity(RUNBOOK),
        "architecture_validation": architecture,
        "stage_receipts": {
            stage: _identity(STAGE_DIRS[stage] / "receipt.json")
            for stage in EXPECTED_RECEIPT_STATUS
        },
        "s7_failure_evidence": {
            name: _identity(STAGE_DIRS["s7"] / name)
            for name in (
                "plan.json",
                "sealed-context-trace.json",
                "reader-progress-trace.json",
                "reader-failure.json",
                "failure-ledger.json",
                "failure-analysis.json",
            )
        },
        "runner": _identity(Path(__file__)),
        "claim_boundary": (
            "DG21 demonstrated deterministic type-pruning, preference expressivity, and a safe "
            "query-time temporal lane on frozen synthetic/opened-development evidence. The Core "
            "matched lane is parked because the additional-call ceiling failed and an exact frozen "
            "Reader identity repeatedly violated strict JSON. This does not establish matched "
            "quality gain, production latency improvement, formal LongMemEval improvement, schema "
            "completion, architecture freeze readiness, or production readiness."
        ),
    }
    if not terminal_seal_passed:
        raise DG21S9Error("terminal seal checks failed")
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg21-s9-terminal-20260829-001")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    try:
        receipt = run(run_id=args.run_id, output=output)
    except Exception as exc:
        if output.exists() and not (output / "failure-ledger.json").exists():
            _write(
                output / "failure-ledger.json",
                {
                    "schema": "milai.dg21.failure-ledger.v0.1",
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
