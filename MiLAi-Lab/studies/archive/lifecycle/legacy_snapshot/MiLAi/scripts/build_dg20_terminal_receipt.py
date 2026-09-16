#!/usr/bin/env python3
"""Validate DG-20 evidence and seal separate core/residual terminal lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime/.venv/bin/python"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"

DEFAULT_STAGE_PATHS = {
    "s0": ROOT / "var/dg20/s0/dg20-s0-fresh-state-20260828-003",
    "s1": ROOT / "var/dg20/s1/dg20-s1-official-channel-oracle-projection-20260828-005",
    "s2": ROOT / "var/dg20/s2/dg20-s2-deterministic-policy-20260828-002",
    "s3": ROOT / "var/dg20/s3/dg20-s3-conditional-disposition-20260828-002",
    "s4": ROOT / "var/dg20/s4/dg20-s4-product-faithful-projection-20260828-004",
    "s5": ROOT / "var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005",
}
DEFAULT_QUALITY = ROOT / "var/dg20/quality/dg20-quality-postgres-20260828-008/receipt.json"

EXPECTED_STAGE_STATUS = {
    "s0": "PASS_S0_FRESH_STATE_AUDIT",
    "s1": "PASS_S1_OFFICIAL_CHANNEL_ORACLE",
    "s2": "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY",
    "s3": "PASS_S3_CONDITIONAL_DISPOSITION",
    "s4": "PASS_S4_ONE_PASS_PRODUCT_FAITHFUL_INTEGRATION",
    "s5": "PASS_REQUIREMENT_STATE_ALIGNED_ACQUISITION",
}
CORE_DISPOSITION = "PASS_REQUIREMENT_STATE_ALIGNED_ACQUISITION"
RESIDUAL_DISPOSITION = "DISABLED_NOT_NEEDED"
STANDARD_ARTIFACTS = (
    "plan.json",
    "sealed-product-trace.json",
    "score.json",
    "receipt.json",
    "acquisition-loss-ledger.json",
)

SOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "requirement_state": (
        "runtime/src/milai/domain/requirement_state.py",
        "runtime/src/milai/application/requirement_state.py",
    ),
    "acquisition_capability": (
        "runtime/src/milai/domain/acquisition_capability.py",
        "runtime/src/milai/application/acquisition_capability.py",
    ),
    "acquisition_plan_and_state": (
        "runtime/src/milai/domain/acquisition.py",
        "runtime/src/milai/application/acquisition.py",
        "runtime/src/milai/application/acquisition_state.py",
    ),
    "official_executor": ("runtime/src/milai/application/evidence_acquisition.py",),
    "repository_retrieval": (
        "runtime/src/milai/persistence/retrieval_repository.py",
        "runtime/src/milai/application/retrieval.py",
    ),
    "semantic_query_and_binding": (
        "runtime/src/milai/domain/semantic_query.py",
        "runtime/src/milai/application/memory_query.py",
        "runtime/src/milai/application/query_ir_compat.py",
        "runtime/src/milai/application/query_planner.py",
        "runtime/src/milai/application/evidence_semantics.py",
    ),
    "sufficiency": (
        "runtime/src/milai/domain/sufficiency.py",
        "runtime/src/milai/application/sufficiency.py",
    ),
    "observation_recovery_and_cue": (
        "runtime/src/milai/domain/acquisition_observation.py",
        "runtime/src/milai/domain/deterministic_recovery.py",
        "runtime/src/milai/domain/residual_cue.py",
        "runtime/src/milai/application/deterministic_recovery.py",
    ),
    "runtime_integration": (
        "runtime/src/milai/config/settings.py",
        "runtime/src/milai/api/app.py",
    ),
    "evaluator_and_scorer": (
        "evals/dg20/__init__.py",
        "evals/dg20/fresh_state_audit.py",
        "evals/dg20/official_channel_oracle.py",
        "evals/dg20/deterministic_policy_eval.py",
        "evals/dg20/product_faithful_eval.py",
        "evals/dg20/matched_q6_eval.py",
        "evals/dg17/q6_matched.py",
    ),
    "direct_runners": (
        "scripts/run_dg20_s0_fresh_state_audit.py",
        "scripts/run_dg20_s1_official_channel_oracle.py",
        "scripts/run_dg20_s2_deterministic_policy.py",
        "scripts/run_dg20_s3_disposition.py",
        "scripts/run_dg20_s4_product_faithful.py",
        "scripts/run_dg20_s5_matched_q6.py",
        "scripts/project_dg20_stage_artifacts.py",
        "scripts/run_dg20_quality_gates.py",
        "scripts/build_dg20_terminal_receipt.py",
    ),
    "fixture_and_product_view": (
        "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json",
        "var/dg11/paper/freeze/longmemeval-full-inputs.json",
        "var/dg14/splits/public-deidentified-dev-v1/source-ids.json",
        "var/dg17/a2/dg17-a2-per-slot-fusion-20260827-004/product-contexts-001/contexts.json",
    ),
    "contracts_and_runbook": (
        "MiLAi_DG-20_RequirementState对齐与Capability约束证据再查找_GOALS.md",
        "docs/dg20-residual-cue-artifact-contract.md",
        "docs/runbooks/dg20-requirement-aligned-acquisition.md",
    ),
    "terminal_tests": ("tests/test_dg20_terminal_receipt.py",),
}


class DG20TerminalError(RuntimeError):
    """Terminal evidence is missing, inconsistent, or unsafe."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path, *, relative: bool = False) -> dict[str, object]:
    resolved = path.resolve()
    display = str(resolved.relative_to(ROOT)) if relative else str(resolved)
    return {"path": display, "sha256": _sha256(resolved), "size": resolved.stat().st_size}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG20TerminalError(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DG20TerminalError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: Mapping[str, object]) -> None:
    if path.exists():
        raise DG20TerminalError(f"refusing to overwrite artifact: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20TerminalError(f"{field} must be an object")
    return value


def _assert_identity(reference: object, path: Path, field: str) -> None:
    identity = _object(reference, field)
    if identity.get("sha256") != _sha256(path):
        raise DG20TerminalError(f"{field} SHA-256 does not match {path}")


def validate_stage_directory(stage: str, directory: Path) -> dict[str, Any]:
    """Validate one immutable standard stage directory and its internal links."""

    if stage not in EXPECTED_STAGE_STATUS:
        raise DG20TerminalError(f"unknown stage: {stage}")
    missing = [name for name in STANDARD_ARTIFACTS if not (directory / name).is_file()]
    if missing:
        raise DG20TerminalError(f"{stage} standard artifact(s) missing: {', '.join(missing)}")
    receipt = _read(directory / "receipt.json")
    if receipt.get("status") != EXPECTED_STAGE_STATUS[stage]:
        raise DG20TerminalError(f"{stage} receipt status is not authoritative PASS")
    if stage in {"s1", "s4"}:
        if not (
            receipt.get("artifact_projection") is True
            and receipt.get("byte_identical_seal") is True
            and receipt.get("byte_identical_score") is True
        ):
            raise DG20TerminalError(f"{stage} immutable artifact projection is invalid")
    for field, name in (
        ("plan", "plan.json"),
        ("sealed_product_trace", "sealed-product-trace.json"),
        ("score", "score.json"),
        ("acquisition_loss_ledger", "acquisition-loss-ledger.json"),
    ):
        _assert_identity(receipt.get(field), directory / name, f"{stage}.{field}")
    for name in STANDARD_ARTIFACTS:
        if _contains_true_key(_read(directory / name), "formal_holdout_consumed"):
            raise DG20TerminalError(f"{stage} consumed formal holdout")
    if stage == "s4":
        source_identity = _object(receipt.get("source_receipt"), "s4.source_receipt")
        raw_path = source_identity.get("path")
        if not isinstance(raw_path, str):
            raise DG20TerminalError("s4.source_receipt path is invalid")
        source_path = Path(raw_path)
        source_path = source_path if source_path.is_absolute() else ROOT / source_path
        source_path = source_path.resolve()
        try:
            source_path.relative_to(ROOT)
        except ValueError as exc:
            raise DG20TerminalError("s4.source_receipt escaped repository root") from exc
        _assert_identity(source_identity, source_path, "s4.source_receipt")
        source_receipt = _read(source_path)
        if source_receipt.get("status") != EXPECTED_STAGE_STATUS[stage]:
            raise DG20TerminalError("s4 source receipt status is not authoritative PASS")
        return {
            **receipt,
            "candidate_flag_default": source_receipt.get("candidate_flag_default"),
            "hard_gate": source_receipt.get("hard_gate"),
            "validated_source_receipt": _identity(source_path),
        }
    return receipt


def _contains_true_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return any(
            (key == target and item is True) or _contains_true_key(item, target)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_true_key(item, target) for item in value)
    return False


def validate_terminal_evidence(
    stage_receipts: Mapping[str, Mapping[str, Any]], quality: Mapping[str, Any]
) -> dict[str, bool]:
    """Evaluate the non-negotiable terminal gates without mutating evidence."""

    s0 = stage_receipts["s0"]
    s2 = stage_receipts["s2"]
    s3 = stage_receipts["s3"]
    s4 = stage_receipts["s4"]
    s5 = stage_receipts["s5"]
    checks = {
        "all_stage_statuses_authoritative": all(
            receipt.get("status") == EXPECTED_STAGE_STATUS[stage]
            for stage, receipt in stage_receipts.items()
        ),
        "s0_hard_gate_passed": _object(s0.get("hard_gate"), "s0.hard_gate").get("passed") is True,
        "s2_hard_gate_passed": _object(s2.get("hard_gate"), "s2.hard_gate").get("passed") is True,
        "s3_core_lane_passed": s3.get("core_lane") == CORE_DISPOSITION,
        "residual_lane_disabled_not_needed": (
            s3.get("residual_assist") == RESIDUAL_DISPOSITION
            and s5.get("residual_assist") == RESIDUAL_DISPOSITION
        ),
        "s4_candidate_default_disabled": s4.get("candidate_flag_default") is False,
        "s4_hard_gates_passed": _all_nested_passed(s4.get("hard_gate")),
        "s5_core_disposition_exact": (
            s5.get("core_disposition") == CORE_DISPOSITION and s5.get("status") == CORE_DISPOSITION
        ),
        "s5_hard_gates_passed": _all_boolean_true(s5.get("hard_gate")),
        "s5_safety_zero": _s5_safety_zero(s5),
        "quality_passed": (
            quality.get("passed") is True and quality.get("status") == "PASS_DG20_QUALITY_GATES"
        ),
        "postgresql_integration_executed": quality.get("integration_executed") is True,
        "openworker_release_claim_excluded": (
            quality.get("openworker_composition_executed") is False
            and quality.get("openworker_composition_disposition")
            == "OUT_OF_SCOPE_OPTIONAL_GATE_PER_DG20_SECTION_3_10"
        ),
        "formal_holdout_untouched": not any(
            _contains_true_key(receipt, "formal_holdout_consumed")
            for receipt in [*stage_receipts.values(), quality]
        ),
    }
    if not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        raise DG20TerminalError("terminal gate(s) failed: " + ", ".join(failed))
    return checks


def _all_boolean_true(value: object) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _all_nested_passed(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(isinstance(item, dict) and item.get("passed") is True for item in value.values())
    )


def _s5_safety_zero(receipt: Mapping[str, Any]) -> bool:
    safety = receipt.get("safety_and_cost")
    state = receipt.get("state_correctness")
    if not isinstance(safety, dict) or not isinstance(state, dict):
        return False
    return all(
        safety.get(key) == 0
        for key in (
            "automatic_retries",
            "canonical_mutation_count",
            "controller_model_calls",
            "governance_violation_count",
            "provider_calls",
            "wrong_complete_count",
        )
    ) and all(
        state.get(key) == 0
        for key in (
            "controller_state_epoch_mismatch_count",
            "execution_state_digest_mismatch_count",
            "satisfied_requirement_target_count",
            "state_digest_rejection_accepted_mismatch_count",
            "unsupported_action_proposal_count",
        )
    )


def _source_manifest() -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    for group, paths in SOURCE_GROUPS.items():
        missing = [path for path in paths if not (ROOT / path).is_file()]
        if missing:
            raise DG20TerminalError(
                f"transitive source identity missing in {group}: {', '.join(missing)}"
            )
        groups[group] = [_identity(ROOT / path, relative=True) for path in paths]
    flattened = [item for identities in groups.values() for item in identities]
    return {
        "schema": "milai.dg20.source-artifact-manifest.v0.1",
        "identity_count": len(flattened),
        "groups": groups,
        "manifest_digest": hashlib.sha256(
            json.dumps(flattened, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "formal_holdout_consumed": False,
    }


def _run_architecture_gates(output: Path) -> dict[str, object]:
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG20TerminalError("frozen architecture manifest trust anchor drifted")
    commands = (
        (
            "validate-bundle",
            [str(PYTHON), "architecture/v1.0/scripts/validate_bundle.py"],
        ),
        (
            "verify-release-lock",
            [
                str(PYTHON),
                "architecture/v1.0/scripts/verify_lock.py",
                "--scope",
                "bundle",
                "--mode",
                "release",
                "--expected-manifest-sha256",
                ARCHITECTURE_MANIFEST_SHA256,
            ],
        ),
    )
    environment = dict(os.environ)
    environment["MILAI_ARCHITECTURE_LOCK_SCOPE"] = "bundle"
    gates: list[dict[str, object]] = []
    for gate_id, command in commands:
        completed = subprocess.run(  # noqa: S603 - fixed repository validation commands
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        log = output / f"architecture-{gate_id}.log"
        _write_text(log, completed.stdout + completed.stderr)
        gates.append(
            {
                "gate_id": gate_id,
                "command": command,
                "exit_code": completed.returncode,
                "passed": completed.returncode == 0,
                "log": _identity(log),
            }
        )
    if not all(bool(gate["passed"]) for gate in gates):
        raise DG20TerminalError("frozen architecture validation failed")
    return {
        "manifest": _identity(ARCHITECTURE_MANIFEST, relative=True),
        "external_manifest_sha256": ARCHITECTURE_MANIFEST_SHA256,
        "scope": "bundle",
        "mode": "release",
        "passed": True,
        "gates": gates,
        "changed_by_dg20": False,
    }


def _write_text(path: Path, value: str) -> None:
    if path.exists():
        raise DG20TerminalError(f"refusing to overwrite artifact: {path}")
    path.write_text(value, encoding="utf-8")


def _stage_artifacts(stage_paths: Mapping[str, Path]) -> dict[str, object]:
    return {
        stage: {
            name.removesuffix(".json").replace("-", "_"): _identity(directory / name)
            for name in STANDARD_ARTIFACTS
        }
        for stage, directory in stage_paths.items()
    }


def _prior_failures(output: Path) -> dict[str, object]:
    receipts: list[dict[str, object]] = []
    ledgers: list[dict[str, object]] = []
    for path in sorted((ROOT / "var/dg20").glob("*/*/receipt.json")):
        if output in path.parents:
            continue
        value = _read(path)
        if value.get("passed") is False or str(value.get("status", "")).startswith("FAILED"):
            receipts.append(_identity(path, relative=True))
    for path in sorted((ROOT / "var/dg20").glob("*/*/failure-ledger.json")):
        if output not in path.parents:
            ledgers.append(_identity(path, relative=True))
    return {"failed_receipts": receipts, "failure_ledgers": ledgers}


def _ledger(stage_paths: Mapping[str, Path], *, run_id: str) -> dict[str, object]:
    stages: dict[str, object] = {}
    total = 0
    for stage, directory in stage_paths.items():
        path = directory / "acquisition-loss-ledger.json"
        value = _read(path)
        count = value.get("record_count")
        if not isinstance(count, int) or count < 0:
            raise DG20TerminalError(f"{stage} loss ledger record_count is invalid")
        if count and not _ledger_first_loss_complete(value, count):
            raise DG20TerminalError(f"{stage} loss ledger first-loss uniqueness failed")
        total += count
        stages[stage] = {"identity": _identity(path), "record_count": count}
    return {
        "schema": "milai.dg20.s6-acquisition-loss-ledger.v0.1",
        "run_id": run_id,
        "aggregation": "REFERENCE_ONLY_NO_RECLASSIFICATION",
        "stage_record_count_total": total,
        "stage_ledgers": stages,
        "all_nonempty_stage_ledgers_have_exactly_one_first_loss": True,
        "formal_holdout_consumed": False,
    }


def _ledger_first_loss_complete(value: Mapping[str, Any], count: int) -> bool:
    if value.get("all_records_have_exactly_one_first_loss") is True:
        return True
    records = value.get("records")
    return (
        value.get("first_loss_policy") == "ONE_EARLIEST_STAGE_PER_UNRESOLVED_REQUIREMENT"
        and value.get("first_loss_assigned_count") == count
        and value.get("unresolved_requirement_denominator") == count
        and value.get("coverage") == 1
        and isinstance(records, list)
        and len(records) == count
        and all(
            isinstance(record, dict)
            and isinstance(record.get("first_loss_stage"), str)
            and bool(record["first_loss_stage"])
            for record in records
        )
    )


def run(
    *,
    run_id: str,
    output: Path,
    stage_paths: Mapping[str, Path],
    quality_path: Path,
) -> dict[str, object]:
    if output.exists():
        raise DG20TerminalError("output exists; choose a fresh terminal run ID")
    output.mkdir(parents=True)
    plan_path = output / "plan.json"
    plan = {
        "schema": "milai.dg20.s6-terminal-plan.v0.1",
        "run_id": run_id,
        "mode": "EVIDENCE_ONLY_TERMINAL_DISPOSITION",
        "expected_core_disposition": CORE_DISPOSITION,
        "expected_residual_disposition": RESIDUAL_DISPOSITION,
        "stage_receipts": {
            stage: str((path / "receipt.json").resolve()) for stage, path in stage_paths.items()
        },
        "quality_receipt": str(quality_path.resolve()),
        "formal_holdout_consumed": False,
        "public_schema_change_authorized": False,
        "database_schema_change_authorized": False,
        "production_release_authorized": False,
    }
    _write(plan_path, plan)
    try:
        if set(stage_paths) != set(EXPECTED_STAGE_STATUS):
            raise DG20TerminalError("exactly S0-S5 stage paths are required")
        stage_receipts = {
            stage: validate_stage_directory(stage, path) for stage, path in stage_paths.items()
        }
        quality = _read(quality_path)
        checks = validate_terminal_evidence(stage_receipts, quality)
        settings_source = (ROOT / "runtime/src/milai/config/settings.py").read_text(
            encoding="utf-8"
        )
        if "retrieval_deterministic_recovery_enabled: bool = False" not in settings_source:
            raise DG20TerminalError("DG-20 candidate is not default-disabled in Runtime settings")
        architecture = _run_architecture_gates(output)
        manifest_path = output / "source-artifact-manifest.json"
        _write(manifest_path, _source_manifest())
        stage_artifacts = _stage_artifacts(stage_paths)
        prior_failures = _prior_failures(output)
        ledger_path = output / "acquisition-loss-ledger.json"
        ledger = _ledger(stage_paths, run_id=run_id)
        sealed_path = output / "sealed-product-trace.json"
        sealed = {
            "schema": "milai.dg20.s6-terminal-sealed-trace.v0.1",
            "run_id": run_id,
            "status": "TERMINAL_EVIDENCE_SEALED",
            "core_disposition": CORE_DISPOSITION,
            "residual_disposition": RESIDUAL_DISPOSITION,
            "stage_artifacts": stage_artifacts,
            "quality_receipt": _identity(quality_path),
            "architecture_validation": architecture,
            "prior_failures_preserved": prior_failures,
            "formal_holdout_consumed": False,
            "labels_loaded": False,
        }
        _write(sealed_path, sealed)
        _write(ledger_path, ledger)
        s5 = stage_receipts["s5"]
        score_path = output / "score.json"
        score = {
            "schema": "milai.dg20.s6-terminal-score.v0.1",
            "run_id": run_id,
            "status": CORE_DISPOSITION,
            "core_disposition": CORE_DISPOSITION,
            "residual_disposition": RESIDUAL_DISPOSITION,
            "terminal_checks": checks,
            "comparisons": s5.get("comparisons"),
            "safety_and_cost": s5.get("safety_and_cost"),
            "state_correctness": s5.get("state_correctness"),
            "formal_holdout_consumed": False,
        }
        _write(score_path, score)
        receipt_path = output / "receipt.json"
        receipt: dict[str, object] = {
            "schema": "milai.dg20.s6-terminal-receipt.v0.1",
            "run_id": run_id,
            "status": "TERMINAL_DISPOSITION_SEALED",
            "core_disposition": CORE_DISPOSITION,
            "residual_disposition": RESIDUAL_DISPOSITION,
            "terminal_checks": checks,
            "candidate_flag_default": False,
            "formal_holdout_consumed": False,
            "production_release_authorized": False,
            "public_mcp_schema_changed": False,
            "database_schema_changed": False,
            "architecture_changed": False,
            "plan": _identity(plan_path),
            "sealed_product_trace": _identity(sealed_path),
            "score": _identity(score_path),
            "acquisition_loss_ledger": _identity(ledger_path),
            "source_artifact_manifest": _identity(manifest_path),
            "quality_receipt": _identity(quality_path),
            "architecture_validation": architecture,
            "stage_artifacts": stage_artifacts,
            "prior_failures_preserved": prior_failures,
            "runner": _identity(Path(__file__)),
            "claim_boundary": (
                "Opened-development deterministic acquisition passed DG-20 gates with the "
                "candidate default-disabled and residual assistance unnecessary. This does not "
                "authorize formal holdout use, schema freeze, production release, or closure of "
                "the out-of-scope primary OpenWorker composition risks."
            ),
        }
        _write(receipt_path, receipt)
        return receipt
    except Exception as exc:
        _write_failure_artifacts(output, run_id=run_id, plan_path=plan_path, error=exc)
        raise


def _write_failure_artifacts(
    output: Path, *, run_id: str, plan_path: Path, error: Exception
) -> None:
    reason = str(error)
    failure_path = output / "failure-ledger.json"
    if not failure_path.exists():
        _write(
            failure_path,
            {
                "schema": "milai.dg20.s6-failure-ledger.v0.1",
                "run_id": run_id,
                "status": "FAILED_GOVERNANCE_INVARIANT",
                "first_loss_stage": "TERMINAL_VALIDATION",
                "reason_code": type(error).__name__,
                "detail": reason,
                "retry_performed": False,
            },
        )
    standard: dict[str, Mapping[str, object]] = {
        "sealed-product-trace.json": {
            "schema": "milai.dg20.s6-terminal-sealed-trace.v0.1",
            "run_id": run_id,
            "status": "FAILED_GOVERNANCE_INVARIANT",
            "formal_holdout_consumed": False,
        },
        "acquisition-loss-ledger.json": {
            "schema": "milai.dg20.s6-acquisition-loss-ledger.v0.1",
            "run_id": run_id,
            "record_count": 0,
            "records": [],
            "all_records_have_exactly_one_first_loss": True,
        },
        "score.json": {
            "schema": "milai.dg20.s6-terminal-score.v0.1",
            "run_id": run_id,
            "status": "FAILED_GOVERNANCE_INVARIANT",
        },
    }
    for name, value in standard.items():
        path = output / name
        if not path.exists():
            _write(path, value)
    receipt_path = output / "receipt.json"
    if not receipt_path.exists():
        _write(
            receipt_path,
            {
                "schema": "milai.dg20.s6-terminal-receipt.v0.1",
                "run_id": run_id,
                "status": "FAILED_GOVERNANCE_INVARIANT",
                "core_disposition": "FAILED_GOVERNANCE_INVARIANT",
                "residual_disposition": "NOT_EVALUATED",
                "plan": _identity(plan_path),
                "sealed_product_trace": _identity(output / "sealed-product-trace.json"),
                "score": _identity(output / "score.json"),
                "acquisition_loss_ledger": _identity(output / "acquisition-loss-ledger.json"),
                "failure_ledger": _identity(failure_path),
                "formal_holdout_consumed": False,
            },
        )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "var/dg20/s6")
    for stage, default in DEFAULT_STAGE_PATHS.items():
        parser.add_argument(f"--{stage}", type=Path, default=default)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    stage_paths = {stage: Path(getattr(args, stage)).resolve() for stage in EXPECTED_STAGE_STATUS}
    try:
        receipt = run(
            run_id=args.run_id,
            output=(args.output_root / args.run_id).resolve(),
            stage_paths=stage_paths,
            quality_path=args.quality.resolve(),
        )
    except DG20TerminalError as exc:
        print(json.dumps({"status": "FAILED_GOVERNANCE_INVARIANT", "reason": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "core_disposition": receipt["core_disposition"],
                "residual_disposition": receipt["residual_disposition"],
                "receipt": str(
                    (args.output_root / args.run_id / "receipt.json").resolve().relative_to(ROOT)
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
