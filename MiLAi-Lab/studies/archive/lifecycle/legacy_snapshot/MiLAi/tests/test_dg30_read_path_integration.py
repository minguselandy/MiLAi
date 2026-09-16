from __future__ import annotations

from pathlib import Path

from evals.dg30.read_path_integration import evaluate_read_path_integration

ROOT = Path(__file__).resolve().parents[1]


def test_admitted_read_path_integrates_and_rolls_back_cleanly() -> None:
    result = evaluate_read_path_integration(ROOT)

    assert result["status"] == "PASS_READ_PATH_INTEGRATION"
    assert all(result["checks"].values())
    assert result["metrics"]["target_binding_groups"] == 7
    assert result["metrics"]["accepted_binding_precision"] == 1.0
    assert result["metrics"]["wrong_complete"] == 0
    assert result["implementation_rollback"]["equivalent_to_dg28_lite"] is True
    assert result["dg29_disposition"] == "NOT_ENTERED_NO_REFINDING_OPPORTUNITY"


def test_integration_is_not_misreported_as_release_ready() -> None:
    result = evaluate_read_path_integration(ROOT)

    assert result["release_ready"] is False
    assert result["formal_holdout_used"] is False
    assert result["canonical_mutations"] == 0
    assert result["reader_calls"] == 0
    assert result["model_calls"] == 0
