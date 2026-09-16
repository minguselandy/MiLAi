from __future__ import annotations

from pathlib import Path

from evals.dg23.baseline_freeze import run_baseline_freeze

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s0_binds_all_predecessor_identities_and_denominators() -> None:
    baseline = run_baseline_freeze(ROOT)

    assert baseline["status"] == "PASS_DG23_BASELINE_DENOMINATOR_FREEZE"
    assert baseline["hard_gate"]["passed"]
    assert len(baseline["bound_artifacts"]) == 7
    assert baseline["denominator"]["case_count"] == 10
    assert baseline["denominator"]["candidate_context_cell_count"] == 20
    assert len(baseline["denominator"]["source_snapshot_digests"]) == 10
    assert baseline["denominator"]["legacy_diagnostic_budgets"] == [512, 2048]


def test_dg23_s0_freezes_historical_regression_without_opening_labels() -> None:
    baseline = run_baseline_freeze(ROOT)

    assert baseline["denominator"]["historical_regression_case_ids"] == {
        "2048": ["gpt4_88806d6e"],
        "512": [],
    }
    assert (
        len(baseline["denominator"]["historical_candidate_correct_case_ids"]["512"])
        == 6
    )
    assert (
        len(baseline["denominator"]["historical_candidate_correct_case_ids"]["2048"])
        == 4
    )
    assert baseline["label_boundary"] == {
        "sealed_dg22_score_read": True,
        "source_labels_loaded": False,
        "formal_holdout_consumed": False,
    }
    assert baseline["safety"]["reader_calls"] == 0
    assert baseline["safety"]["provider_calls"] == 0


def test_dg23_s0_freezes_budget_independent_seed_namespace_and_candidate_off() -> None:
    baseline = run_baseline_freeze(ROOT)
    controls = baseline["frozen_controls"]

    assert controls["dg23_seed_namespace"] == "milai-dg23-matched-v1"
    assert "excludes arm and presentation budget" in controls["dg23_seed_formula"]
    assert baseline["safety"]["candidate_default"] is False
    assert baseline["hard_gate"]["checks"]["architecture_mutations_zero"]
