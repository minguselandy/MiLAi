from __future__ import annotations

from pathlib import Path

from evals.dg21.preference_expressivity import run_preference_expressivity_matrix


def test_s4_preference_expressivity_matrix_passes_all_hard_gates() -> None:
    report = run_preference_expressivity_matrix(Path(__file__).resolve().parents[1])

    assert report["status"] == "PASS_PREFERENCE_REQUIREMENT_EXPRESSIVITY"
    assert report["hard_gate"]["passed"] is True
    assert all(report["hard_gate"]["checks"].values())
    assert report["metrics"] == {
        "synthetic_positive_count": 4,
        "synthetic_negative_count": 4,
        "current_intent_false_satisfied_count": 0,
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "additional_acquisition_passes": 0,
        "canonical_mutations": 0,
        "runtime_case_id_occurrences": 0,
    }
    assert report["opened_a89_diagnosis"]["match_count_by_requirement"] == {
        "PREFERENCE_SIGNAL_SET": 1,
        "CURRENT_INTENT": 1,
    }
    assert report["opened_a89_diagnosis"]["formal_holdout_consumed"] is False
    assert report["opened_a89_diagnosis"]["label_fields_accessed"] is False
    assert report["a82_regression"]["token_budget"] == 2048
    assert report["a82_regression"]["frozen_answer_exact_match"] == 1
    assert report["a82_regression"]["semantic_ir_frozen_contract_preserved"] is True
    assert report["a82_regression"]["semantic_ir_added_paths"] == [
        "$.requirements[0].semantic_roles.actor"
    ]
