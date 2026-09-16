from __future__ import annotations

from pathlib import Path

from evals.dg23.synthetic_matrix import build_synthetic_matrix_report

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s5_all_generic_synthetic_shapes_run_full_ladder() -> None:
    report = build_synthetic_matrix_report(ROOT)

    assert report["status"] == "PASS_DG23_SYNTHETIC_CONTRACT_MATRIX"
    assert report["hard_gate"]["passed"]
    assert len(report["case_summaries"]) == 11
    assert len(report["records"]) == 77
    assert report["diagnostic_budgets"] == [128, 256, 512, 1024, 2048, 4096, 8000]


def test_dg23_s5_structural_and_safety_gates_have_zero_violations() -> None:
    report = build_synthetic_matrix_report(ROOT)
    checks = report["hard_gate"]["checks"]

    assert checks["nestedness_violations_zero"]
    assert checks["order_violations_zero"]
    assert checks["atomic_truncations_zero"]
    assert checks["saturation_violations_zero"]
    assert checks["conflict_sides_and_open_issue_protected"]
    assert checks["oversized_required_always_infeasible"]


def test_dg23_s5_property_trials_and_permutation_are_deterministic() -> None:
    report = build_synthetic_matrix_report(ROOT)

    assert report["property_report"]["trial_count"] == 128
    assert report["property_report"]["failure_count"] == 0
    assert report["hard_gate"]["checks"][
        "repository_permutation_plan_digest_invariant"
    ]
    assert report["label_boundary"]["source_labels_loaded"] is False
    assert report["execution_counts"]["reader_calls"] == 0
