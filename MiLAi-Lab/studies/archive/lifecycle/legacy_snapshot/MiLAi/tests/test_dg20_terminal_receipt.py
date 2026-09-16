from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.build_dg20_terminal_receipt import (
    CORE_DISPOSITION,
    EXPECTED_STAGE_STATUS,
    RESIDUAL_DISPOSITION,
    DG20TerminalError,
    _ledger_first_loss_complete,
    validate_stage_directory,
    validate_terminal_evidence,
)


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_standard_stage_validation_rejects_post_receipt_artifact_drift(
    tmp_path: Path,
) -> None:
    for name in (
        "plan.json",
        "sealed-product-trace.json",
        "score.json",
        "acquisition-loss-ledger.json",
    ):
        _write(tmp_path / name, {"formal_holdout_consumed": False, "name": name})
    receipt = {
        "status": EXPECTED_STAGE_STATUS["s0"],
        "hard_gate": {"passed": True},
        "plan": {"sha256": _sha256(tmp_path / "plan.json")},
        "sealed_product_trace": {"sha256": _sha256(tmp_path / "sealed-product-trace.json")},
        "score": {"sha256": _sha256(tmp_path / "score.json")},
        "acquisition_loss_ledger": {"sha256": _sha256(tmp_path / "acquisition-loss-ledger.json")},
    }
    _write(tmp_path / "receipt.json", receipt)
    assert validate_stage_directory("s0", tmp_path)["status"] == EXPECTED_STAGE_STATUS["s0"]

    _write(tmp_path / "score-drift.json", {"unexpected": True})
    (tmp_path / "score.json").write_bytes((tmp_path / "score-drift.json").read_bytes())
    with pytest.raises(DG20TerminalError, match="SHA-256"):
        validate_stage_directory("s0", tmp_path)


def _terminal_receipts() -> dict[str, dict[str, Any]]:
    receipts = {
        stage: {"status": status, "formal_holdout_consumed": False}
        for stage, status in EXPECTED_STAGE_STATUS.items()
    }
    receipts["s0"]["hard_gate"] = {"passed": True}
    receipts["s2"]["hard_gate"] = {"passed": True}
    receipts["s3"].update({"core_lane": CORE_DISPOSITION, "residual_assist": RESIDUAL_DISPOSITION})
    receipts["s4"].update({"candidate_flag_default": False, "hard_gate": {"one": {"passed": True}}})
    receipts["s5"].update(
        {
            "core_disposition": CORE_DISPOSITION,
            "residual_assist": RESIDUAL_DISPOSITION,
            "hard_gate": {"one": True},
            "safety_and_cost": {
                "automatic_retries": 0,
                "canonical_mutation_count": 0,
                "controller_model_calls": 0,
                "governance_violation_count": 0,
                "provider_calls": 0,
                "wrong_complete_count": 0,
            },
            "state_correctness": {
                "controller_state_epoch_mismatch_count": 0,
                "execution_state_digest_mismatch_count": 0,
                "satisfied_requirement_target_count": 0,
                "state_digest_rejection_accepted_mismatch_count": 0,
                "unsupported_action_proposal_count": 0,
            },
        }
    )
    return receipts


def _quality() -> dict[str, Any]:
    return {
        "status": "PASS_DG20_QUALITY_GATES",
        "passed": True,
        "integration_executed": True,
        "openworker_composition_executed": False,
        "openworker_composition_disposition": ("OUT_OF_SCOPE_OPTIONAL_GATE_PER_DG20_SECTION_3_10"),
        "formal_holdout_consumed": False,
    }


def test_terminal_evidence_keeps_core_and_residual_lanes_separate() -> None:
    checks = validate_terminal_evidence(_terminal_receipts(), _quality())

    assert checks["s5_core_disposition_exact"] is True
    assert checks["residual_lane_disabled_not_needed"] is True


def test_terminal_evidence_rejects_residual_disposition_drift() -> None:
    receipts = _terminal_receipts()
    receipts["s5"]["residual_assist"] = "VALIDATED_OPTIONAL_ONE_CALL_CUE"

    with pytest.raises(DG20TerminalError, match="residual_lane_disabled_not_needed"):
        validate_terminal_evidence(receipts, _quality())


def test_terminal_evidence_rejects_false_complete_safety_drift() -> None:
    receipts = _terminal_receipts()
    receipts["s5"]["safety_and_cost"]["wrong_complete_count"] = 1

    with pytest.raises(DG20TerminalError, match="s5_safety_zero"):
        validate_terminal_evidence(receipts, _quality())


def test_s5_loss_ledger_uses_explicit_coverage_contract() -> None:
    ledger = {
        "record_count": 2,
        "first_loss_assigned_count": 2,
        "unresolved_requirement_denominator": 2,
        "coverage": 1,
        "first_loss_policy": "ONE_EARLIEST_STAGE_PER_UNRESOLVED_REQUIREMENT",
        "records": [
            {"first_loss_stage": "CHANNEL"},
            {"first_loss_stage": "BINDING"},
        ],
    }

    assert _ledger_first_loss_complete(ledger, 2) is True
    ledger["first_loss_assigned_count"] = 1
    assert _ledger_first_loss_complete(ledger, 2) is False
